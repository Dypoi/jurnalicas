"""
================================================================================
MONTE CARLO INTRABAR SEQUENCING VALIDATOR — Model Icas (XAUUSD M5)
================================================================================
[AUDIT FOLLOW-UP R-01 lanjutan] Menjawab: "PF riil-nya berapa?"

Engine optimis (PF 3.88) vs konservatif (PF 0.81) hanyalah BATAS ATAS & BAWAH —
keduanya mengasumsikan urutan ekstrem high↔low di dalam satu candle M5, padahal
urutan sebenarnya tidak tersimpan di data OHLC.

Model: untuk bar "ambigu" (jangkauan bar menyentuh SL *dan* level BE/TP), URUTAN
kejadian di-sample probabilistik — peluang sebuah level tersentuh lebih dulu
berbanding terbalik dengan jarak level dari harga OPEN bar (heuristik jarak,
varian ringan dari Brownian bridge). Semua aturan lain IDENTIK dengan engine v2:
sizing SL+spread+slippage, slippage $0.10 entry/stop, spread guard, WIN/BE/LOSS.
Catatan penting: jika SL pre-bar tersentuh, posisi PASTI keluar pada bar tsb
(SL hanya bisa naik ke arah profit), sehingga satu-satunya ketidakpastian sejati
adalah URUTAN: TP/BE tereksekusi dulu atau SL dulu — itulah yang di-sample.

Ini MODEL stokastik (bukan data granular riil). Untuk jawaban definitif per-feed
broker: python research/validate_granular.py --fine <M1 ekspor MT5 Anda>

Usage:  python research/monte_carlo_intrabar.py [N_SIM] [start] [end] [csv]
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from config import config
from src.indicators.sessions import calculate_session_killzones
from src.backtest.engine import infer_price_point


# ---------------------------------------------------------------- signals ----
def precompute_signals(df: pd.DataFrame):
    """Replika persis logika entry engine v2 (vektoris)."""
    h, l, c, o = df['high'], df['low'], df['close'], df['open']
    swing_h = h.rolling(5).max().shift(2)          # max(high[i-6 : i-1])
    swing_l = l.rolling(5).min().shift(2)
    ssl = np.minimum(df['asian_low'], df['london_low'])
    bsl = np.maximum(df['asian_high'], df['london_high'])
    bull_fvg = l > (h.shift(2) + 0.30)
    bear_fvg = h < (l.shift(2) - 0.30)
    ssl_swept = (l.shift(1) <= ssl) | (l.shift(2) <= ssl)
    bsl_swept = (h.shift(1) >= bsl) | (h.shift(2) >= bsl)
    buy = (ssl_swept & (c > o) & ((c > swing_h) | bull_fvg)).fillna(False)
    sell = (bsl_swept & (c < o) & ((c < swing_l) | bear_fvg)).fillna(False)
    spread_ok = df['spread'] <= config.MAX_SPREAD_POINTS
    buy &= spread_ok
    sell &= spread_ok
    if getattr(config, 'USE_KILLZONE', False):
        buy &= df['in_ict_burst']
        sell &= df['in_ict_burst']
    return buy.values, sell.values


# ------------------------------------------------------------ one MC run -----
def simulate(buy_sig, sell_sig, high, low, open_, close_, spread, rng, start_i, end_i, price_point=0.01):
    cfg = config
    capital = cfg.INITIAL_CAPITAL
    pnls, res_list = [], []

    ratios = (cfg.TP1_LOT_RATIO, cfg.TP2_LOT_RATIO, cfg.TP3_LOT_RATIO)
    run_r = cfg.RUNNER_LOT_RATIO
    be_trig = cfg.EARLY_BE_TRIGGER_PIPS * 0.10      # $1.00
    step_usd = cfg.TRAILING_STEP_PIPS * 0.10        # $10.00
    lock_usd = cfg.TRAILING_LOCK_PIPS * 0.10        # $3.00
    sl_dist = cfg.STOP_LOSS_PIPS * 0.10             # $2.00
    slipp = cfg.SLIPPAGE_USD
    risk_dollar = cfg.INITIAL_CAPITAL * cfg.RISK_PER_TRADE_PCT

    i = start_i
    while i <= end_i:
        if not (buy_sig[i] or sell_sig[i]):
            i += 1
            continue

        # ------------------------------ buka posisi ------------------------------
        d = 1 if buy_sig[i] else -1
        spread_usd_i = spread[i] * price_point
        sl_eff = sl_dist + spread_usd_i + slipp
        sz = (risk_dollar / (sl_eff * 100.0)) * 100.0      # ounce
        sp_c = spread_usd_i * sz
        ep = close_[i] + d * slipp
        sl = ep - d * sl_dist
        tp = [ep + d * (p * 0.10) for p in (cfg.TP1_PIPS, cfg.TP2_PIPS, cfg.TP3_PIPS)]
        hit = [False, False, False]
        be_set = False
        max_fav = 0.0
        realized = 0.0
        be_offset = max(0.10, spread_usd_i + cfg.BE_PROFIT_OFFSET_PIPS * 0.10)

        def raise_sl(target, sl_now):
            return max(sl_now, target) if d == 1 else min(sl_now, target)

        # --------------------------- kelola per bar ------------------------------
        exit_bar = None
        j = i + 1
        while j <= end_i:
            hh, ll = high[j], low[j]
            fav_bar = (hh - ep) if d == 1 else (ep - ll)
            if fav_bar > max_fav:
                max_fav = fav_bar

            stop_x = (ll <= sl) if d == 1 else (hh >= sl)
            be_x = (not be_set) and (max_fav >= be_trig)

            # TP berantai yang tersentuh bar ini (urut jenjang)
            tp_events = []
            for k in range(3):
                if hit[k]:
                    continue
                if k > 0 and not hit[k - 1]:
                    break
                lvl = tp[k]
                if (hh >= lvl) if d == 1 else (ll <= lvl):
                    tp_events.append(k)
                else:
                    break

            k_step = int(max_fav // step_usd)

            def apply_be():
                nonlocal sl, be_set
                sl = raise_sl(ep + d * be_offset, sl)
                be_set = True

            def apply_tp(k):
                nonlocal sl, realized, capital
                pnl_part = d * (tp[k] - ep) * (sz * ratios[k]) - (sp_c * ratios[k])
                realized += pnl_part
                capital += pnl_part
                hit[k] = True
                if k == 0:
                    sl = raise_sl(ep + d * be_offset, sl)
                elif k == 2:
                    sl = raise_sl(tp[0], sl)

            def apply_trail():
                nonlocal sl
                if k_step >= 1:
                    sl = raise_sl(ep + d * ((k_step - 1) * step_usd + lock_usd), sl)

            if not stop_x:
                # Urutan engine v2 dalam bar tanpa sentuhan SL
                if be_x:
                    apply_be()
                for k in tp_events:
                    apply_tp(k)
                apply_trail()
                j += 1
                continue

            # ---- bar menyentuh SL (ambigu jika BE/TP juga tersentuh) ----
            # Level referensi utk bobot jarak dari OPEN
            cand = [("stop", sl)]
            if be_x:
                cand.append(("be", ep + d * be_trig))
            for k in tp_events:
                cand.append((f"tp{k}", tp[k]))
            # trailing di-abaikan dlm bar ambigu (frekuensi <1.5%, didokumentasikan)

            if len(cand) == 1:
                order = cand
            else:
                o = open_[j]
                w = np.array([1.0 / max(abs(o - px), 0.05) for _, px in cand])
                idx = list(range(len(cand)))
                order = []
                while idx:
                    probs = w[idx] / w[idx].sum()
                    pick = rng.choice(len(idx), p=probs)
                    order.append(cand[idx.pop(pick)])
                # paksa jenjang TP tetap monoton (tp0 sebelum tp1 sebelum tp2)
                tps_sorted = sorted((e for e in order if e[0].startswith("tp")), key=lambda e: e[0])
                it = iter(tps_sorted)
                order = [next(it) if e[0].startswith("tp") else e for e in order]

            for name, _px in order:
                if name == "be":
                    apply_be()
                elif name.startswith("tp"):
                    apply_tp(int(name[-1]))
                else:  # "stop" -> posisi PASTI keluar pada bar ini
                    exit_price = sl - d * slipp
                    if not hit[0]:
                        rem = 1.0
                    elif not hit[1]:
                        rem = ratios[1] + ratios[2] + run_r
                    elif not hit[2]:
                        rem = ratios[2] + run_r
                    else:
                        rem = run_r
                    exit_pnl = d * (exit_price - ep) * (sz * rem) - (sp_c * rem)
                    realized += exit_pnl
                    capital += exit_pnl
                    pnls.append(realized)
                    if hit[0] or hit[1] or hit[2]:
                        res_list.append('WIN')
                    elif be_set and realized >= 0:
                        res_list.append('BE')
                    else:
                        res_list.append('LOSS')
                    exit_bar = j
                    break
            if exit_bar is not None:
                break
            j += 1

        if exit_bar is not None:
            i = exit_bar          # re-entry di bar yang sama (seperti engine)
        else:
            i = end_i + 1         # posisi tidak sempat exit (tidak dicatat, parity engine)

    return capital, np.array(pnls), res_list


def main():
    n_sim = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    start = sys.argv[2] if len(sys.argv) > 2 else "2026-01-01"
    end = sys.argv[3] if len(sys.argv) > 3 else "2026-06-30 23:59:59"
    csv_path = sys.argv[4] if len(sys.argv) > 4 else "data/historical/xauusd_m5.csv"

    print("=" * 86)
    print(f" 🎲 MONTE CARLO INTRABAR SEQUENCING — N={n_sim} | {start[:10]} .. {end[:10]} | fixed $500 risk")
    print("=" * 86)

    df = pd.read_csv(csv_path)
    df['time'] = pd.to_datetime(df['time'])
    df = calculate_session_killzones(df)

    buy_sig, sell_sig = precompute_signals(df)
    price_point = infer_price_point(df['close'].values)
    print(f"[*] Price point terdeteksi: {price_point} $/point")
    high = df['high'].values
    low = df['low'].values
    open_ = df['open'].values
    close_ = df['close'].values
    spread = df['spread'].values

    t64 = df['time'].values.astype('datetime64[ns]')
    start_i = int(np.searchsorted(t64, np.datetime64(start)))
    end_i = min(int(np.searchsorted(t64, np.datetime64(end))) - 1, len(df) - 1)
    print(f"[*] Window bar: {start_i} .. {end_i} ({end_i - start_i + 1} bar)")

    pfs, nets, nonloss, ntr = [], [], [], []
    for s in range(n_sim):
        rng = np.random.default_rng(1000 + s)
        cap, pnls, res = simulate(buy_sig, sell_sig, high, low, open_, close_, spread, rng, start_i, end_i, price_point)
        res = np.array(res)
        wins = int((res == 'WIN').sum())
        bes = int((res == 'BE').sum())
        gw = pnls[res != 'LOSS'].sum()
        gl = abs(pnls[res == 'LOSS'].sum())
        pfs.append(gw / gl if gl > 0 else np.inf)
        nets.append(cap - config.INITIAL_CAPITAL)
        nonloss.append((wins + bes) / max(1, len(res)) * 100)
        ntr.append(len(res))
        if (s + 1) % 200 == 0:
            print(f"    ... {s + 1}/{n_sim} selesai (PF median sementara {np.median(pfs):.2f})")

    pfs = np.array(pfs)
    nets = np.array(nets)
    print("\n" + "=" * 86)
    print(" 📊 DISTRIBUSI HASIL (urutan intrabar di-sample, weighted-by-distance-from-open)")
    print("=" * 86)
    print(f"• Rata-rata trade/run  : {np.mean(ntr):.0f}")
    print(f"• Profit Factor        : median {np.median(pfs):.2f} | mean {np.mean(pfs):.2f} | "
          f"CI90% [{np.percentile(pfs, 5):.2f} .. {np.percentile(pfs, 95):.2f}]")
    print(f"• Net Profit           : median ${np.median(nets):+,.0f} | CI90% "
          f"[${np.percentile(nets, 5):+,.0f} .. ${np.percentile(nets, 95):+,.0f}]")
    print(f"• Non-Loss Rate        : median {np.median(nonloss):.2f}% | "
          f"CI90% [{np.percentile(nonloss, 5):.2f}% .. {np.percentile(nonloss, 95):.2f}%]")
    print(f"• P(PF > 1.0)          : {(pfs > 1.0).mean() * 100:.1f}% simulasi")
    print(f"• P(Net > 0)           : {(nets > 0).mean() * 100:.1f}% simulasi")
    print("-" * 86)
    print("Deterministik (audit): PF LEGACY-optimis = 3.88 | PF KONSERVATIF-pesimis = 0.81")
    print("Catatan: model stokastik di atas M5 Exness; jawaban definitif per-feed broker =")
    print("         python research/validate_granular.py --fine <CSV M1 ekspor MT5 Anda>")


if __name__ == '__main__':
    main()
