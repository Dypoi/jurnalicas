"""
================================================================================
GRANULAR SEQUENCER CORE — eksekusi manajemen posisi pada data granular (M1/tick)
================================================================================
Inti dari research/validate_granular.py, dijadikan library agar bisa dipakai
grid-search. Semantik IDENTIK dengan validator definitif (teregresi numerik):
  • Sinyal pada penutupan bar M5 (vektoris, sama dengan engine v2)
  • Manajemen (BE+, TP1/2/3 berantai, trailing, SL) berjalan pada bar fine
    dalam URUTAN WAKTU NYATA — tanpa asumsi intrabar
  • Sizing: SL + spread(infer point) + slippage | slippage $ entry & stop
  • Klasifikasi 3-arah: WIN / BE / LOSS
================================================================================
"""
import numpy as np
import pandas as pd
from src.backtest.engine import infer_price_point


def precompute_signals(df: pd.DataFrame, cfg):
    h, l, c, o = df['high'], df['low'], df['close'], df['open']
    swing_h = h.rolling(5).max().shift(2)
    swing_l = l.rolling(5).min().shift(2)
    ssl = np.minimum(df['asian_low'], df['london_low'])
    bsl = np.maximum(df['asian_high'], df['london_high'])
    bull_fvg = l > (h.shift(2) + 0.30)
    bear_fvg = h < (l.shift(2) - 0.30)
    ssl_swept = (l.shift(1) <= ssl) | (l.shift(2) <= ssl)
    bsl_swept = (h.shift(1) >= bsl) | (h.shift(2) >= bsl)
    buy = (ssl_swept & (c > o) & ((c > swing_h) | bull_fvg)).fillna(False)
    sell = (bsl_swept & (c < o) & ((c < swing_l) | bear_fvg)).fillna(False)
    ok = df['spread'] <= cfg.MAX_SPREAD_POINTS
    buy &= ok
    sell &= ok
    if getattr(cfg, 'USE_KILLZONE', False):
        buy &= df['in_ict_burst']
        sell &= df['in_ict_burst']
    return buy.values, sell.values


def run_granular(df_m5_sess: pd.DataFrame, fine: pd.DataFrame, cfg,
                 start: str, end: str,
                 buy_sig=None, sell_sig=None, return_trades: bool = False):
    """
    df_m5_sess : M5 SUDAH lewat calculate_session_killzones (kolom asian/london ada)
    fine       : DataFrame granular dengan kolom time,high,low (open opsional)
    return     : dict statistik (+ tdf bila return_trades=True)
    """
    if buy_sig is None or sell_sig is None:
        buy_sig, sell_sig = precompute_signals(df_m5_sess, cfg)

    H = df_m5_sess['high'].values
    L = df_m5_sess['low'].values
    C = df_m5_sess['close'].values
    S = df_m5_sess['spread'].values
    T = df_m5_sess['time'].values
    price_point = infer_price_point(C)

    fh = fine['high'].values
    fl = fine['low'].values
    ft = fine['time'].values

    ratios = (cfg.TP1_LOT_RATIO, cfg.TP2_LOT_RATIO, cfg.TP3_LOT_RATIO)
    run_r = cfg.RUNNER_LOT_RATIO
    be_trig = cfg.EARLY_BE_TRIGGER_PIPS * 0.10
    step_usd = cfg.TRAILING_STEP_PIPS * 0.10
    lock_usd = cfg.TRAILING_LOCK_PIPS * 0.10
    sl_dist = cfg.STOP_LOSS_PIPS * 0.10
    slipp = getattr(cfg, 'SLIPPAGE_USD', 0.0)
    risk_includes = getattr(cfg, 'INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK', True)

    t64 = T.astype('datetime64[ns]')
    start_i = int(np.searchsorted(t64, np.datetime64(start)))
    end_i = min(int(np.searchsorted(t64, np.datetime64(end))) - 1, len(df_m5_sess) - 1)

    nT = len(T)

    def fine_span(j):
        a = np.searchsorted(ft, T[j], side='left')
        b = np.searchsorted(ft, T[j + 1], side='left') if j + 1 < nT else len(ft)
        return a, b

    capital = cfg.INITIAL_CAPITAL
    pnls, res_list, trades = [], [], []

    i = start_i
    while i <= end_i:
        if not (buy_sig[i] or sell_sig[i]):
            i += 1
            continue

        d = 1 if buy_sig[i] else -1
        spread_usd_i = S[i] * price_point
        # sizing: risk base unit (RISK_USD_OVERRIDE utk riset) atau initial*risk_pct
        risk_dollar = getattr(cfg, 'RISK_USD_OVERRIDE', None)
        if risk_dollar is None:
            risk_dollar = cfg.INITIAL_CAPITAL * cfg.RISK_PER_TRADE_PCT
        sl_eff = sl_dist + (spread_usd_i + slipp) if risk_includes else sl_dist
        sz = (risk_dollar / (sl_eff * 100.0)) * 100.0
        sp_c = spread_usd_i * sz
        ep = C[i] + d * slipp
        sl = ep - d * sl_dist
        tp = [ep + d * (p * 0.10) for p in (cfg.TP1_PIPS, cfg.TP2_PIPS, cfg.TP3_PIPS)]
        hit = [False, False, False]
        be_set = False
        max_fav = 0.0
        realized = 0.0
        be_offset = max(0.10, spread_usd_i + cfg.BE_PROFIT_OFFSET_PIPS * 0.10)

        def raise_sl(x, cur):
            return max(cur, x) if d == 1 else min(cur, x)

        exit_bar = None
        j = i + 1
        while j <= end_i:
            a, b = fine_span(j)
            exited = False
            for f in range(a, b):
                hh, ll = fh[f], fl[f]
                fav = (hh - ep) if d == 1 else (ep - ll)
                if fav > max_fav:
                    max_fav = fav

                if (ll <= sl) if d == 1 else (hh >= sl):
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
                    if hit[0] or hit[1] or hit[2]:
                        res = 'WIN'
                    elif be_set and realized >= 0:
                        res = 'BE'
                    else:
                        res = 'LOSS'
                    pnls.append(realized)
                    res_list.append(res)
                    if return_trades:
                        trades.append({
                            'time': pd.Timestamp(ft[f]), 'type': 'BUY' if d == 1 else 'SELL',
                            'res': res, 'pnl': realized, 'balance': capital,
                            'month': pd.Timestamp(ft[f]).strftime('%Y-%m'),
                            'tp1_hit': hit[0], 'tp2_hit': hit[1], 'tp3_hit': hit[2],
                            'be_set': be_set})
                    exited = True
                    break

                if not be_set and max_fav >= be_trig:
                    sl = raise_sl(ep + d * be_offset, sl)
                    be_set = True
                for k in range(3):
                    if hit[k] or (k > 0 and not hit[k - 1]):
                        continue
                    lvl = tp[k]
                    if (hh >= lvl) if d == 1 else (ll <= lvl):
                        pnl_part = d * (lvl - ep) * (sz * ratios[k]) - (sp_c * ratios[k])
                        realized += pnl_part
                        capital += pnl_part
                        hit[k] = True
                        if k == 0:
                            sl = raise_sl(ep + d * be_offset, sl)
                        elif k == 2:
                            sl = raise_sl(tp[0], sl)
                k_step = int(max_fav // step_usd)
                if k_step >= 1:
                    sl = raise_sl(ep + d * ((k_step - 1) * step_usd + lock_usd), sl)

            if exited:
                exit_bar = j
                break
            j += 1

        i = exit_bar if exit_bar is not None else end_i + 1

    # ---------------- statistik ----------------
    pnls = np.array(pnls)
    res = np.array(res_list)
    total = len(res)
    wins = int((res == 'WIN').sum())
    bes = int((res == 'BE').sum())
    losses = int((res == 'LOSS').sum())
    gw = pnls[res != 'LOSS'].sum() if total else 0.0
    gl = abs(pnls[res == 'LOSS'].sum()) if total else 0.0
    pf = (gw / gl) if gl > 0 else (float('inf') if gw > 0 else 0.0)
    nlr = (wins + bes) / total * 100 if total else 0.0
    net = capital - cfg.INITIAL_CAPITAL

    bal = np.cumsum(pnls) + cfg.INITIAL_CAPITAL if total else np.array([cfg.INITIAL_CAPITAL])
    peak = np.maximum.accumulate(np.concatenate([[cfg.INITIAL_CAPITAL], bal]))
    dd = float(((peak - np.concatenate([[cfg.INITIAL_CAPITAL], bal])) / peak * 100).max())

    out = {
        'trades': total, 'wins': wins, 'be': bes, 'losses': losses,
        'pf': pf, 'nlr': nlr, 'net': net, 'dd_pct': dd,
        'avg_win': float(pnls[res == 'WIN'].mean()) if wins else 0.0,
        'avg_loss': float(pnls[res == 'LOSS'].mean()) if losses else 0.0,
        'price_point': price_point,
    }
    if return_trades:
        out['tdf'] = pd.DataFrame(trades)
    return out
