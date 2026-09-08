"""
================================================================================
TUNING MULTI-TIMEFRAME — ANALISA H1 -> M30 -> M15 -> M5, EKSEKUSI M1
================================================================================
Konsep yang DIMINTA pengguna (08 Sep 2026): seluruh tuning harus memakai analisa
berlapis H1, M30, M15, M5 dengan eksekusi di M1. Skrip ini mengimplementasikan
kaskade ICT tersebut di atas engine audit M1 bid/ask (anti-repaint, pesimis):

  L1  H1   — BIAS arah     : close vs EMA200 H1 (bar H1 tertutup terakhir)
  L2  M30  — LIKUIDITAS    : sweep SSL/BSL mayor = swing low/high ~24 jam M30
  L3  M15  — STRUKTUR      : CHoCH — close menembus swing high/low 5-bar M15
  L4  M5   — TRIGGER       : displacement candle + FVG / break swing 5-bar M5
  EX  M5   — EKSEKUSI      : entry di OPEN bar M5 berikutnya; SL/TP/trailing
                             dievaluasi per bar M5, pesimis [A5], spread riil
                             (bot 'bangun' tiap 5 menit). --exec m1 mengembalikan
                             perilaku lama: bar M1 pertama, manajemen per M1.

KAUSALITAS: nilai HTF dipetakan ke bar M5 hanya bila bar HTF itu SUDAH TERTUTUP
saat bar M5 dievaluasi (offset -dur). Tanpa lookahead antar-timeframe.

Varian ablasi (kontribusi tiap lapisan):
  V1 MTF FULL      : H1 + M30 + M15 + M5
  V2 MTF tanpa M15 : H1 + M30 + M5
  V3 MTF tanpa M30 : H1 + M15 + M5
  V4 H1 + M5 saja  : bias + trigger
  V5/V6 = V1 dengan jendela sweep M30 1j/4j (makin lebar makin longgar)
  V7/V8 = V1 dengan likuiditas PDH/PDL kemarin (jendela 2 bar / 4 jam)
  V9/V10 = V1 dengan likuiditas fractal swing M30 (jendela 2 bar / 4 jam)
  A BASELINE       : engine lama (analisa M5 + sesi Asia/London, eksekusi M1)
                     — pembanding; inilah konsep semua laporan tuning sebelumnya.
  R RANDOM (--random) : entry acak geometri sama — kontrol untuk klaim edge.

Contoh:
  python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" --random
  python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
      --variants V1,V4 --risk 500
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import dataclasses
import numpy as np
import pandas as pd

from research.backtest_m1_audit import (  # noqa: E402
    load_m1, session_levels_norepaint, resample_m5, run_backtest,
    StratCfg, CFG_CURRENT, SERVER_TZ,
)
from research.backtest_m1_period import (  # noqa: E402
    month_table, print_stats,
)
from research.tuning_trend_filter import (  # noqa: E402
    find_files_for, month_brief,
)

HERE = os.path.dirname(os.path.abspath(__file__))

VARIANTS = {
    "V1": ("MTF FULL  (H1+M30+M15+M5)", {}),
    "V2": ("MTF tanpa M15 (H1+M30+M5)", {"mtf_m15": False}),
    "V3": ("MTF tanpa M30 (H1+M15+M5)", {"mtf_m30": False}),
    "V4": ("H1+M5 saja (bias+trigger)", {"mtf_m30": False, "mtf_m15": False}),
    "V5": ("MTF FULL, sweep M30 jendela 1 jam", {"mtf_sweep_bars": 12}),
    "V6": ("MTF FULL, sweep M30 jendela 4 jam", {"mtf_sweep_bars": 48}),
    "V7": ("MTF FULL, likuiditas PDH/PDL (fresh)", {"mtf_m30_mode": "pd"}),
    "V8": ("MTF FULL, PDH/PDL jendela 4 jam", {"mtf_m30_mode": "pd", "mtf_sweep_bars": 48}),
    "V9": ("MTF FULL, fractal M30 (fresh)", {"mtf_m30_mode": "fract"}),
    "V10": ("MTF FULL, fractal M30 jendela 4 jam", {"mtf_m30_mode": "fract", "mtf_sweep_bars": 48}),
    "A":  ("BASELINE lama (M5+sesi, eksekusi M1)", {"signal_mode": "choch"}),
}


def _map_htf(series: pd.Series, m5_index: pd.DatetimeIndex, dur: str):
    """Peta nilai HTF ke bar M5 secara KAUSAL: bar M5 bertime t hanya boleh
    memakai bar HTF berlabel <= t-dur (yakni sudah tertutup saat t dibuka;
    HTF label = awal bar, konvensi MT5)."""
    target = m5_index - pd.Timedelta(dur)
    return series.reindex(target, method="pad").to_numpy()


def exec_frame_from_m5(m1: pd.DataFrame, m5: pd.DataFrame) -> pd.DataFrame:
    """[EKSEKUSI M5] Frame eksekusi bar-M5: setiap bar M5 menjadi SATU bar
    eksekusi bagi loop manajemen posisi engine yang sama (anti-repaint,
    pesimis [A5], spread riil).

      entry     : OPEN bar M5 berikutnya setelah sinyal (ask utk BUY, bid utk SELL)
      SL/TP/trailing : dievaluasi per BAR M5 (high/low candle), bukan per M1
                  -> replika bot yang hanya 'bangun' tiap 5 menit; bila SL dan
                  TP tersentuh di candle yang sama, SL dihitung lebih dulu
                  (pesimis, konsisten dgn metodologi audit M1).
    Ask OHLC diagregat EXACT dari M1 per candle (bukan aproksimasi bid+spread).
    Bar M5 tidak lengkap sudah dibuang resample_m5 (n >= 4).
    """
    ex = pd.DataFrame(index=m5.index)
    for c in ("open", "high", "low", "close"):
        ex[f"{c}_bid"] = m5[c].to_numpy()
    a = m1.resample("5min", label="left", closed="left").agg(
        open_ask=("open_ask", "first"), high_ask=("high_ask", "max"),
        low_ask=("low_ask", "min"))
    ex = ex.join(a)
    ex["spread_usd"] = m5["spread"].to_numpy()
    srv = ex.index.tz_localize("UTC").tz_convert(SERVER_TZ)
    ex["srv_hour"] = srv.hour.to_numpy()
    ex["srv_min"] = srv.minute.to_numpy()
    ex["srv_date"] = srv.date
    return ex.dropna(subset=["open_bid", "open_ask"])


def add_mtf_columns(m5: pd.DataFrame) -> pd.DataFrame:
    """Bangun kolom kaskade MTF pada frame M5 (semua kausal)."""
    m5 = m5.copy()
    # ---- L1: H1 EMA200 (bias) ----
    h1_close = m5["close"].resample("1h", label="left", closed="left").last()
    h1_ema = h1_close.ewm(span=200, adjust=False).mean()
    m5["h1_ema200"] = _map_htf(h1_ema, m5.index, "1h")

    # ---- L2: M30 likuiditas mayor (swing ~24 jam = 48 bar M30 BURSA, exclude
    # bar berjalan). NB: resample menghasilkan bar NaN saat bursa tutup
    # (weekend) — bar kosong DI-drop agar rolling 48 = 48 bar bursa terakhir,
    # bukan 48 slot waktu yang selalu putus oleh weekend (bug: 0 nilai valid). ----
    m30 = m5.resample("30min", label="left", closed="left").agg(
        high=("high", "max"), low=("low", "min")).dropna()
    m5["m30_ssl"] = _map_htf(m30["low"].rolling(48, min_periods=48).min().shift(1),
                             m5.index, "30min")
    m5["m30_bsl"] = _map_htf(m30["high"].rolling(48, min_periods=48).max().shift(1),
                             m5.index, "30min")

    # ---- L3: M15 swing 5-bar (CHoCH) — idem: drop bar kosong non-bursa ----
    m15 = m5.resample("15min", label="left", closed="left").agg(
        high=("high", "max"), low=("low", "min")).dropna()
    m5["m15_swing_h"] = _map_htf(m15["high"].rolling(5).max().shift(2),
                                 m5.index, "15min")
    m5["m15_swing_l"] = _map_htf(m15["low"].rolling(5).min().shift(2),
                                 m5.index, "15min")

    # ---- L2b: PDH/PDL (high/low KEMARIN, level ICT klasik). Offset 1 hari
    # menjamin hanya hari yang SUDAH selesai yang terbaca (kausal). ----
    d1 = m5.resample("1D", label="left", closed="left").agg(
        high=("high", "max"), low=("low", "min")).dropna()
    m5["pd_low"] = _map_htf(d1["low"], m5.index, "1D")
    m5["pd_high"] = _map_htf(d1["high"], m5.index, "1D")

    # ---- L2c: fractal swing M30 (bar M30 yang low/high-nya ekstrem terhadap
    # 2 bar M30 di kiri-kanannya). Konfirmasi menunggu 2 bar M30 → shift(2)
    # posisional (aman melewati weekend), lalu ffill ke bar berikutnya. ----
    fl = m30["low"].rolling(5, center=True).min()
    fh = m30["high"].rolling(5, center=True).max()
    fsw = m30["low"].where(m30["low"] <= fl)     # fractal swing low (SSL)
    fsh = m30["high"].where(m30["high"] >= fh)   # fractal swing high (BSL)
    m5["m30_fsw"] = _map_htf(fsw.shift(2).ffill(), m5.index, "30min")
    m5["m30_fsh"] = _map_htf(fsh.shift(2).ffill(), m5.index, "30min")
    return m5


def main():
    ap = argparse.ArgumentParser(description="Tuning MTF: analisa H1/M30/M15/M5, eksekusi M1")
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default="2026-09-01 23:59:59")
    ap.add_argument("--variants", default="V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,A")
    ap.add_argument("--risk", type=float, default=100.0)
    ap.add_argument("--exec", choices=("m5", "m1"), default="m5",
                    help="timeframe eksekusi: 'm5' = entry di open bar M5 berikutnya, "
                         "SL/TP/trailing per bar M5 (default, per instruksi 08 Sep 2026); "
                         "'m1' = perilaku lama (bar M1 pertama, manajemen per M1)")
    ap.add_argument("--random", action="store_true",
                    help="tambah baseline entry ACAK sebagai kontrol (n = varian teramai)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--guard", type=float, default=1.20)
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out: list[str] = []
    E = lambda t="": (print(t), out.append(t))  # noqa: E731

    files, warm_start = find_files_for(args.start, args.end, warm_days=330)
    if not files:
        raise SystemExit(f"tidak ada file XAUUSD_M1 untuk {args.start}..{args.end}")

    E("=" * 100)
    E(f" 🔧 TUNING MULTI-TIMEFRAME (H1->M30->M15->M5, eksekusi {args.exec.upper()}) | {args.start[:10]} .. {args.end[:10]}")
    E("=" * 100)
    E(f"Data          : {len(files)} file XAUUSD_M1 (warm-up {warm_start} → konvergensi EMA200-H1)")

    frames = [load_m1(f, max(warm_start, "2016-09-01"), args.end) for f in files]
    m1 = pd.concat(frames)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    m1 = session_levels_norepaint(m1)
    m5 = add_mtf_columns(resample_m5(m1))
    m5w = m5[m5.index >= pd.Timestamp(args.start)]
    E(f"Bar M1/M5     : {len(m1):,} / {len(m5w):,} (hari bursa M5: {m5w.index.normalize().nunique()})")
    E(f"Harga periode : {m5w['low'].min():,.2f} .. {m5w['high'].max():,.2f}")
    E(f"Guard spread  : ${args.guard:.2f} | risk/trade ${args.risk:,.0f} | modal ${args.capital:,.0f}")
    ok_h1 = int(m5w["h1_ema200"].notna().sum())
    E(f"Kausalitas    : EMA200-H1 valid pada {ok_h1:,}/{len(m5w):,} bar M5"
      + ("  ⚠️ KURANG" if ok_h1 < len(m5w) * 0.9 else "  ✅"))
    ok_m30 = int(m5w["m30_ssl"].notna().sum())
    ok_m15 = int(m5w["m15_swing_h"].notna().sum())
    ok_pd = int(m5w["pd_low"].notna().sum())
    ok_fr = int(m5w["m30_fsw"].notna().sum())
    E(f"Kausalitas    : SSL/BSL-M30 {ok_m30:,}/{len(m5w):,}"
      + ("  ⚠️" if ok_m30 < len(m5w) * 0.9 else "  ✅")
      + f" | PDH/PDL {ok_pd:,}/{len(m5w):,}"
      + ("  ⚠️" if ok_pd < len(m5w) * 0.9 else "  ✅")
      + f" | fract-M30 {ok_fr:,}/{len(m5w):,}"
      + ("  ⚠️" if ok_fr < len(m5w) * 0.9 else "  ✅")
      + f" | swing-M15 {ok_m15:,}/{len(m5w):,}"
      + ("  ⚠️" if ok_m15 < len(m5w) * 0.9 else "  ✅"))
    E("Geometri      : SL150 | TP 187.5/375/562.5 | split 30/25/25/20 | trail 100/30 | BE+ OFF | 24 jam")
    E("Kaskade       : L1 H1 bias EMA200 → L2 M30 sweep SSL/BSL 24j → L3 M15 CHoCH 5-bar "
      "→ L4 M5 displacement/FVG (anti-repaint, pesimis, spread riil)")
    if args.exec == "m5":
        m1x = exec_frame_from_m5(m1, m5)
        E(f"Eksekusi      : M5 — {len(m1x):,} bar eksekusi; entry di OPEN bar M5 berikutnya; "
          "SL/TP/trailing dievaluasi per bar M5 (pesimis [A5]); strict_bar_open_entry ON "
          "(entry diblok bila posisi lama exit di candle sama); manage_entry_bar ON "
          "(candle eksekusi ikut diuji SL/TP — order broker aktif sejak entry)")
    else:
        m1x = m1
        E(f"Eksekusi      : M1 — {len(m1x):,} bar; entry di bar M1 pertama candle M5 berikutnya; "
          "SL/TP/trailing per bar M1")

    codes = [c.strip().upper() for c in args.variants.split(",") if c.strip()]
    strict = args.exec == "m5"
    meb = args.exec == "m5"     # candle eksekusi ikut diuji SL/TP (order broker aktif)
    results = []
    for code in codes:
        if code not in VARIANTS:
            raise SystemExit(f"varian tidak dikenal: {code} (pilih dari {list(VARIANTS)})")
        name, ov = VARIANTS[code]
        kw = {"risk_usd": args.risk, "max_spread_usd": args.guard,
              "strict_bar_open_entry": strict, "manage_entry_bar": meb, **ov}
        kw.setdefault("signal_mode", "mtf" if code.startswith("V") else "choch")
        cfg = dataclasses.replace(CFG_CURRENT, name=f"{code} — {name}", **kw)
        st = run_backtest(m1x, m5, cfg, capital0=args.capital, trade_from=args.start)
        print_stats(st, f"{code} — {name} (risk ${args.risk:,.0f})", out)
        month_table(st["tdf"], f"{code} — {name}", out, capital0=args.capital)
        results.append((code, name, st))

    if args.random:
        n_ref = max((st["trades"] for _, _, st in results), default=0) or 1000
        cfgR = dataclasses.replace(CFG_CURRENT, name="RANDOM", risk_usd=args.risk,
                                   max_spread_usd=args.guard,
                                   strict_bar_open_entry=strict,
                                   manage_entry_bar=meb)
        stR = run_backtest(m1x, m5, cfgR, capital0=args.capital, trade_from=args.start,
                           random_seed=args.seed, n_random=n_ref)
        print_stats(stR, f"BASELINE ACAK (n={n_ref}, risk ${args.risk:,.0f})", out)
        month_table(stR["tdf"], "BASELINE ACAK (kontrol)", out, capital0=args.capital)
        results.append(("R", f"RANDOM n={n_ref} (kontrol)", stR))

    E("\n" + "=" * 100)
    E(f" RINGKASAN PERBANDINGAN MTF (risk ${args.risk:,.0f}, guard ${args.guard:.2f})")
    E("=" * 100)
    E(f" {'Varian':40s} | {'Tr':>5s} | {'WR%':>6s} | {'PF':>6s} | {'Net $':>11s} | "
      f"{'Exp $':>8s} | {'DD%':>6s} | {'Entry/bln':>9s} | {'Hijau':>6s} | {'BUY/SELL':>9s}")
    E("-" * 120)
    for code, name, st in results:
        if st["trades"] == 0:
            E(f" {code+' — '+name:40s} |    0 |")
            continue
        epm, green, nm = month_brief(st["tdf"])
        tdf = st["tdf"]
        nb = int((tdf.type == "BUY").sum()); ns = int((tdf.type == "SELL").sum())
        E(f" {code+' — '+name:40s} | {st['trades']:5d} | {st['wr_pct']:6.1f} | {st['pf']:6.2f} | "
          f"{st['net']:+11,.0f} | {st['expectancy']:+8.2f} | {st['dd_pct']:6.1f} | "
          f"{epm:9.1f} | {green:3d}/{nm:3d} | {nb:4d}/{ns:4d}")

    path = args.out or os.path.join(
        HERE, "..", "reports",
        f"tuning_mtf_{pd.Timestamp(args.start):%Y%m%d}_{pd.Timestamp(args.end):%Y%m%d}"
        f"_risk{int(args.risk)}{'_execm5' if args.exec == 'm5' else ''}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"\n💾 Laporan tersimpan: {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
