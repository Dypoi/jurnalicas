"""
================================================================================
BACKTEST PER PERIODE — ENGINE AUDIT M1 BID/ASK (anti-repaint, pesimis)
================================================================================
Backtest "strategi plan saat ini" (SWING-150 C) pada data XAUUSD_M1 (bid & ask
TERPISAH, timestamp UTC) untuk periode arbitrer, memakai engine teraudit
research/backtest_m1_audit.py (replikasi exact logika live):

  • Level sesi Asian/London point-in-time — anti-repaint (F-18)
  • Sinyal M5 bar tertutup (Judas sweep + CHoCH/FVG), eksekusi bar M1 berikutnya
  • BUY di ask, exit di bid -> spread riil per bar masuk IMPLISIT
  • SL dicek SEBELUM TP dalam bar M1 yang sama (pesimis, anti bias optimis)
  • Kenaikan SL (BE+/step-TP3/trailing) baru efektif bar M1 berikutnya
  • 4-tier TP 30/25/25/20 + trailing step 100p / lock 30p, BE+ OFF, 24 jam,
    maks 999 trade/hari, CB 999 (semua = config.py saat ini)

Tidak dimodelkan: slippage eksekusi (terukur live ±$1.27/entry), komisi/swap.

Warm-up: 3 minggu sebelum --start dimuat dari file M1 tahun sebelumnya
(bila ada) supaya bar pertama periode sudah punya level sesi kemarin yang sah.

Contoh (permintaan 08 Sep 2026 — setahun penuh):
    python research/backtest_m1_period.py --start 2025-09-01 --end "2026-09-01 23:59:59"
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

HERE = os.path.dirname(os.path.abspath(__file__))
M1_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "XAUUSD_M1"))


def find_files_for(start: str, end: str):
    """Semua file XAUUSD_M1 yang rentangnya menyentuh [start-21d, end]."""
    warm_start = (pd.Timestamp(start) - pd.Timedelta(days=21)).strftime("%Y%m%d")
    files = []
    for fn in sorted(os.listdir(M1_DIR)):
        if not (fn.startswith("XAUUSD_M1_") and fn.endswith(".csv")):
            continue
        a, b = fn[len("XAUUSD_M1_"):-len(".csv")].split("_")
        if b >= warm_start and a <= pd.Timestamp(end).strftime("%Y%m%d"):
            files.append(os.path.join(M1_DIR, fn))
    return files


def month_table(tdf: pd.DataFrame, label: str, out: list, capital0: float = 10_000.0):
    E = lambda t="": (print(t), out.append(t))  # noqa: E731
    s = pd.to_datetime(tdf["open_ts"])
    local = s.dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    month = local.dt.to_period("M").astype(str)
    t2 = tdf.assign(_month=month.to_numpy(), _date=local.dt.date.to_numpy())
    E(f"\n  RINCIAN BULANAN — {label}")
    E(f"  {'Bulan':9s} | {'Entry':>5s} | {'tr/hr-aktif':>10s} | {'W/BE/L':>11s} | "
      f"{'WR%':>6s} | {'PF':>6s} | {'Net $':>12s} | {'Ekuitas $':>12s}")
    E("  " + "-" * 92)
    cum = 0.0
    for m, g in t2.groupby("_month", sort=True):
        n = len(g)
        w = int((g.pnl > 1).sum()); be = int(((g.pnl <= 1) & (g.pnl >= -1)).sum())
        l = int((g.pnl < -1).sum())
        gw = g.loc[g.pnl > 0, "pnl"].sum(); gl = abs(g.loc[g.pnl < 0, "pnl"].sum())
        pf = gw / gl if gl > 0 else float("inf")
        cum += g.pnl.sum()
        ndays = g["_date"].nunique()
        E(f"  {m:9s} | {n:5d} | {n/max(1,ndays):10.2f} | "
          f"{w:3d}/{be:3d}/{l:3d} | {w/n*100:6.1f} | {pf:6.2f} | "
          f"{g.pnl.sum():+12,.0f} | {capital0+cum:12,.0f}")
    n = len(t2)
    E("  " + "-" * 92)
    E(f"  {'TOTAL':9s} | {n:5d} |            | "
      f"{int((t2.pnl>1).sum()):3d}/{int(((t2.pnl<=1)&(t2.pnl>=-1)).sum()):3d}/{int((t2.pnl<-1).sum()):3d}"
      f"   |        |        | {t2.pnl.sum():+12,.0f} |")
    months_seen = t2["_month"].nunique()
    green = sum(1 for m, g in t2.groupby("_month", sort=True) if g.pnl.sum() > 0)
    E(f"  Rata-rata entry/bulan : {n/months_seen:.1f}  ({months_seen} bulan ber-trade, "
      f"{green} bulan hijau)")


def max_consec_losses(tdf) -> int:
    mx = cur = 0
    for r in tdf["res"]:
        cur = cur + 1 if r == "LOSS" else 0
        mx = max(mx, cur)
    return mx


def print_stats(st: dict, label: str, out: list):
    E = lambda t="": (print(t), out.append(t))  # noqa: E731
    E(f"\n>>> {label}")
    if st["trades"] == 0:
        E("    TIDAK ADA TRADE pada periode ini.")
        return
    tdf = st["tdf"]
    n = st["trades"]
    E(f"    Trades        : {n}  ({st['wins']}W / {st['be']}BE / {st['losses']}L)")
    E(f"    Win Rate      : {st['wr_pct']:.2f}%   | Non-Loss Rate: {st['nlr_pct']:.2f}%")
    E(f"    Profit Factor : {st['pf']:.2f}")
    E(f"    Net PnL       : ${st['net']:+,.2f}  (ROI {st['roi_pct']:+.2f}%)")
    E(f"    Ekspektasi    : ${st['expectancy']:+,.2f}/trade")
    E(f"    AvgWin/AvgLoss: ${st['avg_win']:+,.2f} / ${st['avg_loss']:+,.2f}")
    E(f"    Max Drawdown  : {st['dd_pct']:.2f}%  (${st['dd_abs']:,.2f})")
    E(f"    Ekuitas akhir : ${st['final_capital']:,.2f} dari $10,000")
    E(f"    Tr/hari bursa : {st['trades_per_day']}  | tr/hari aktif: {st['trades_per_active_day']}")
    E(f"    TP1/TP2/TP3   : {st['tp1_rate']}% / {st['tp2_rate']}% / {st['tp3_rate']}%"
      f"  | trailing aktif: {st['trail_rate']}%")
    E(f"    Loss beruntun maks : {max_consec_losses(tdf)}")
    nb = int((tdf.type == 'BUY').sum()); ns = int((tdf.type == 'SELL').sum())
    E(f"    BUY/SELL      : {nb}/{ns}")
    E(f"    Median MFE    : ${st['median_mfe']:.2f}  | spread median entry: ${st['avg_spread_entry']:.3f}")
    if st["final_capital"] <= 0:
        E("    ⛔ SIMULASI BANGKRUT (ekuitas habis; entri berhenti saat modal <= 0).")


def main():
    ap = argparse.ArgumentParser(description="Backtest periodik engine audit M1 bid/ask")
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default="2026-09-01 23:59:59")
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--guard", type=float, default=None,
                    help="max spread USD. Default: dua run pembanding (0.35 literal & 1.20 p95 feed)")
    ap.add_argument("--risk", type=float, default=500.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out: list[str] = []
    say = lambda t="": (print(t), out.append(t))  # noqa: E731

    files = find_files_for(args.start, args.end)
    if not files:
        raise SystemExit(f"tidak ada file XAUUSD_M1 untuk {args.start}..{args.end} di {M1_DIR}")

    warm_start = (pd.Timestamp(args.start) - pd.Timedelta(days=21)).strftime("%Y-%m-%d")
    frames = []
    for f in files:
        s = max(warm_start, "2016-09-01")
        frames.append(load_m1(f, s, args.end))
    m1 = pd.concat(frames)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    m1 = session_levels_norepaint(m1)
    m5 = resample_m5(m1)

    m5w = m5[m5.index >= pd.Timestamp(args.start)]
    spr = m5w["spread"].to_numpy()
    say("=" * 100)
    say(f" BACKTEST ENGINE AUDIT M1 BID/ASK — PERIODE {args.start[:10]} s/d {args.end[:10]}")
    say("=" * 100)
    say(f"File data     : {len(files)} file XAUUSD_M1 (warm-up dari {warm_start})")
    say(f"Bar M1/M5     : {len(m1):,} / {len(m5w):,}   | hari bursa M5: {m5w.index.normalize().nunique()}")
    say(f"Harga         : {m5w['low'].min():,.2f} .. {m5w['high'].max():,.2f}")
    say(f"Spread bar    : median ${np.median(spr):.2f} | p95 ${np.percentile(spr,95):.2f} | maks ${spr.max():.2f}")
    say(f"Strategi      : {CFG_CURRENT.name} — SL {CFG_CURRENT.sl_pips:.0f}p | "
        f"TP {CFG_CURRENT.tp1_pips}/{CFG_CURRENT.tp2_pips}/{CFG_CURRENT.tp3_pips:.0f}p | "
        f"split {CFG_CURRENT.r1:.0%}/{CFG_CURRENT.r2:.0%}/{CFG_CURRENT.r3:.0%}/runner | "
        f"trail {CFG_CURRENT.trail_step_pips:.0f}/{CFG_CURRENT.trail_lock_pips:.0f}p | BE+ OFF | killzone OFF")
    say(f"Modal / risiko: ${args.capital:,.0f} / ${args.risk:,.0f} per trade (fixed, non-compounding)")
    say("Engine        : anti-repaint, pesimis (SL dulu intrabar), spread riil bid/ask implisit; "
        "slippage & komisi TIDAK dimodelkan")

    guards = [args.guard] if args.guard is not None else [0.35, 1.20]
    for g in guards:
        pct_pass = float((spr <= g).mean() * 100)
        say(f"Guard spread  : ${g:.2f} -> {pct_pass:.2f}% bar M5 lolos"
            + ("  ⚠️ HAMIR SEMUA BAR DIBLOKIR" if pct_pass < 5 else ""))

    # ---------- RUN ----------
    for g in guards:
        cfg = CFG_CURRENT if g == CFG_CURRENT.max_spread_usd else \
            dataclasses.replace(CFG_CURRENT, max_spread_usd=g)
        tag = f"guard ${g:.2f} | risk ${args.risk:,.0f}"
        st = run_backtest(m1, m5, cfg, capital0=args.capital, trade_from=args.start)
        print_stats(st, f"PLAN SAAT INI — {tag}", out)
        month_table(st["tdf"], f"PLAN SAAT INI — {tag}", out, capital0=args.capital)

        # referensi risiko 1% (hanya untuk guard p95 / guard tunggal)
        if g == max(guards) and args.risk != 100.0:
            st1 = run_backtest(m1, m5, cfg, capital0=args.capital,
                               trade_from=args.start) if False else None
            cfg1 = dataclasses.replace(cfg, risk_usd=100.0)
            st1 = run_backtest(m1, m5, cfg1, capital0=args.capital, trade_from=args.start)
            print_stats(st1, f"PLAN SAAT INI — guard ${g:.2f} | risk $100 (1%, referensi)", out)
            month_table(st1["tdf"], f"PLAN SAAT INI — guard ${g:.2f} | risk $100 (1%)",
                        out, capital0=args.capital)

            # baseline ENTRY ACAK (edge vs keberuntungan), geometri & jumlah sama
            cfgR = dataclasses.replace(cfg1, name="RANDOM BASELINE")
            stR = run_backtest(m1, m5, cfgR, capital0=args.capital, trade_from=args.start,
                               random_seed=args.seed, n_random=st1["trades"])
            print_stats(stR, f"BASELINE ACAK — guard ${g:.2f} | risk $100 (pengukur edge sinyal)", out)

    # ---------- simpan ----------
    default_out = os.path.join(
        HERE, "..", "reports",
        f"backtest_m1_{pd.Timestamp(args.start):%Y%m%d}_{pd.Timestamp(args.end):%Y%m%d}.txt")
    path = args.out or default_out
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"\n💾 Laporan tersimpan: {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
