"""
================================================================================
TUNING — FILTER TREN (MA200/EMA) & MODE CISD vs BASELINE ICT
================================================================================
Membandingkan pada data XAUUSD_M1 (bid/ask, spread riil implisit):

  A  BASELINE           : sweep likuiditas + CHoCH/FVG   (engine saat ini)
  B  + SMA200 HARIAN    : BUY hanya di atas SMA200 kemarin, SELL di bawah
  C  + EMA200 HARIAN    : idem, EMA200 harian
  D  + EMA200 M5        : filter tren intraday (EMA200 pada close M5)
  E  CISD-strict        : displacement diganti Change-in-State-of-Delivery
                          (close menembus open bar pertama dari run >=2 candle
                          searah sebelumnya) + sweep likuiditas
  F/G/H                 : CISD-strict + masing-masing filter tren

Semua varian memakai geometri identik (SL150/TP 187.5-375-562.5/split 30-25-25-20/
trailing 100-30, BE+ OFF, 24 jam) dan engine audit anti-repaint pesimis.
MA harian memakai nilai KEMARIN (hari selesai) — kausal, tanpa lookahead.
Warm-up 330 hari dimuat untuk konvergensi MA200 harian.

Contoh:
  python research/tuning_trend_filter.py --start 2025-09-01 --end "2026-09-01 23:59:59"
  python research/tuning_trend_filter.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
      --variants A,D --risk 500
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
    month_table, print_stats, max_consec_losses,
)

HERE = os.path.dirname(os.path.abspath(__file__))
M1_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "XAUUSD_M1"))

VARIANTS = {
    "A": ("BASELINE sweep+CHoCH/FVG", {}),
    "B": ("BASELINE + SMA200 HARIAN", {"trend_filter": "sma200d"}),
    "C": ("BASELINE + EMA200 HARIAN", {"trend_filter": "ema200d"}),
    "D": ("BASELINE + EMA200 M5", {"trend_filter": "ema200m5"}),
    "E": ("CISD-strict (sweep+CISD)", {"signal_mode": "cisd"}),
    "F": ("CISD + SMA200 HARIAN", {"signal_mode": "cisd", "trend_filter": "sma200d"}),
    "G": ("CISD + EMA200 HARIAN", {"signal_mode": "cisd", "trend_filter": "ema200d"}),
    "H": ("CISD + EMA200 M5", {"signal_mode": "cisd", "trend_filter": "ema200m5"}),
}


def find_files_for(start: str, end: str, warm_days: int = 330):
    warm_start = (pd.Timestamp(start) - pd.Timedelta(days=warm_days)).strftime("%Y%m%d")
    files = []
    for fn in sorted(os.listdir(M1_DIR)):
        if not (fn.startswith("XAUUSD_M1_") and fn.endswith(".csv")):
            continue
        a, b = fn[len("XAUUSD_M1_"):-len(".csv")].split("_")
        if b >= warm_start and a <= pd.Timestamp(end).strftime("%Y%m%d"):
            files.append(os.path.join(M1_DIR, fn))
    return files, warm_start


def cisd_levels(m5: pd.DataFrame):
    """Level CISD per bar M5 (kausal).

    bull[i]  = open bar PERTAMA dari run >=2 candle down-close yang berakhir
               tepat sebelum bar i; bar i bullish dan close-nya MENEMBUS level
               itu -> perubahan state of delivery ke atas.
    bear[i]  = cermin (run >=2 up-close, ditembus ke bawah).
    NaN bila tidak ada perubahan state pada bar itu.
    """
    o = m5["open"].to_numpy()
    c = m5["close"].to_numpy()
    n = len(m5)
    bull = np.full(n, np.nan)
    bear = np.full(n, np.nan)
    down_cnt, down_first = 0, np.nan
    up_cnt, up_first = 0, np.nan
    for i in range(n):
        if c[i] < o[i]:
            down_cnt += 1
            if down_cnt == 1:
                down_first = o[i]
            if up_cnt >= 2 and c[i] < up_first:
                bear[i] = up_first
            up_cnt, up_first = 0, np.nan
        elif c[i] > o[i]:
            up_cnt += 1
            if up_cnt == 1:
                up_first = o[i]
            if down_cnt >= 2 and c[i] > down_first:
                bull[i] = down_first
            down_cnt, down_first = 0, np.nan
        else:   # doji mengakhiri kedua run (konservatif)
            down_cnt, down_first = 0, np.nan
            up_cnt, up_first = 0, np.nan
    return bull, bear


def add_filter_columns(m5: pd.DataFrame) -> pd.DataFrame:
    """Kolom MA (kausal) + level CISD pada frame M5."""
    m5 = m5.copy()
    # EMA200 pada M5 (bar tertutup sendiri — kausal saat evaluasi bar itu)
    m5["ma_ema200m5"] = m5["close"].ewm(span=200, adjust=False).mean()
    # MA harian: nilai KEMARIN (hari yang sudah selesai) — tanpa lookahead harian
    daily_close = m5["close"].resample("1D").last().dropna()
    sma = daily_close.rolling(200).mean().shift(1)
    ema = daily_close.ewm(span=200, adjust=False).mean().shift(1)
    day_idx = m5.index.normalize()
    m5["ma_sma200d"] = sma.reindex(day_idx).to_numpy()
    m5["ma_ema200d"] = ema.reindex(day_idx).to_numpy()
    bull, bear = cisd_levels(m5)
    m5["cisd_bull"] = bull
    m5["cisd_bear"] = bear
    return m5


def month_brief(tdf: pd.DataFrame):
    """(entries/bulan rata2, bulan hijau, jumlah bulan ber-trade)."""
    if not len(tdf):
        return 0.0, 0, 0
    s = pd.to_datetime(tdf["open_ts"])
    local = s.dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    month = local.dt.to_period("M").astype(str)
    g = tdf.groupby(month.to_numpy())["pnl"].sum()
    return len(tdf) / len(g), int((g > 0).sum()), len(g)


def main():
    ap = argparse.ArgumentParser(description="Tuning: filter tren MA200/EMA & mode CISD")
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default="2026-09-01 23:59:59")
    ap.add_argument("--variants", default="A,B,C,D,E,F,G,H",
                    help="kode varian dipisah koma (default semua)")
    ap.add_argument("--risk", type=float, default=100.0)
    ap.add_argument("--guard", type=float, default=1.20)
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--random", action="store_true",
                    help="tambah baseline entry acak sebagai pembanding")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out: list[str] = []
    E = lambda t="": (print(t), out.append(t))  # noqa: E731

    files, warm_start = find_files_for(args.start, args.end)
    if not files:
        raise SystemExit(f"tidak ada file XAUUSD_M1 untuk {args.start}..{args.end}")

    E("=" * 100)
    E(f" 🔧 TUNING — FILTER TREN & CISD | {args.start[:10]} .. {args.end[:10]}")
    E("=" * 100)
    E(f"Data          : {len(files)} file XAUUSD_M1 (warm-up MA200 harian dari {warm_start})")

    frames = [load_m1(f, max(warm_start, "2016-09-01"), args.end) for f in files]
    m1 = pd.concat(frames)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    m1 = session_levels_norepaint(m1)
    m5 = add_filter_columns(resample_m5(m1))
    m5w = m5[m5.index >= pd.Timestamp(args.start)]
    E(f"Bar M1/M5     : {len(m1):,} / {len(m5w):,} (hari bursa M5: {m5w.index.normalize().nunique()})")
    E(f"Harga periode : {m5w['low'].min():,.2f} .. {m5w['high'].max():,.2f}")
    E(f"Guard spread  : ${args.guard:.2f} | risk/trade ${args.risk:,.0f} | modal ${args.capital:,.0f}")
    valid_sma = int(m5w["ma_sma200d"].notna().sum())
    E(f"Warm-up MA    : bar M5 dengan SMA200 harian valid = {valid_sma:,} / {len(m5w):,}"
      + ("  ⚠️ KURANG" if valid_sma < len(m5w) * 0.9 else ""))

    codes = [c.strip().upper() for c in args.variants.split(",") if c.strip()]
    results = []
    for code in codes:
        if code not in VARIANTS:
            raise SystemExit(f"varian tidak dikenal: {code} (pilih dari {list(VARIANTS)})")
        name, ov = VARIANTS[code]
        cfg = dataclasses.replace(CFG_CURRENT, name=f"{code} — {name}",
                                  risk_usd=args.risk, max_spread_usd=args.guard, **ov)
        st = run_backtest(m1, m5, cfg, capital0=args.capital, trade_from=args.start)
        print_stats(st, f"{code} — {name} (risk ${args.risk:,.0f})", out)
        month_table(st["tdf"], f"{code} — {name}", out, capital0=args.capital)
        results.append((code, name, st))

    if args.random:
        cfgR = dataclasses.replace(CFG_CURRENT, name="RANDOM", risk_usd=args.risk,
                                   max_spread_usd=args.guard)
        n_ref = results[0][2]["trades"] if results else 1000
        stR = run_backtest(m1, m5, cfgR, capital0=args.capital, trade_from=args.start,
                           random_seed=args.seed, n_random=n_ref)
        print_stats(stR, f"BASELINE ACAK (n={n_ref}, risk ${args.risk:,.0f})", out)
        results.append(("R", "RANDOM", stR))

    # ---------- tabel ringkasan ----------
    E("\n" + "=" * 100)
    E(f" RINGKASAN PERBANDINGAN (risk ${args.risk:,.0f}, guard ${args.guard:.2f})")
    E("=" * 100)
    E(f" {'Varian':38s} | {'Tr':>5s} | {'WR%':>6s} | {'PF':>6s} | {'Net $':>11s} | "
      f"{'Exp $':>8s} | {'DD%':>6s} | {'Entry/bln':>9s} | {'Hijau':>6s} | {'BUY/SELL':>9s}")
    E("-" * 118)
    for code, name, st in results:
        if st["trades"] == 0:
            E(f" {code+' — '+name:38s} |    0 |        |        |             |"
              f"        |        |           |        |")
            continue
        epm, green, nm = month_brief(st["tdf"])
        tdf = st["tdf"]
        nb = int((tdf.type == "BUY").sum()); ns = int((tdf.type == "SELL").sum())
        E(f" {code+' — '+name:38s} | {st['trades']:5d} | {st['wr_pct']:6.1f} | {st['pf']:6.2f} | "
          f"{st['net']:+11,.0f} | {st['expectancy']:+8.2f} | {st['dd_pct']:6.1f} | "
          f"{epm:9.1f} | {green:3d}/{nm:3d} | {nb:4d}/{ns:4d}")

    path = args.out or os.path.join(
        HERE, "..", "reports",
        f"tuning_trendfilter_{pd.Timestamp(args.start):%Y%m%d}_{pd.Timestamp(args.end):%Y%m%d}"
        f"_risk{int(args.risk)}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"\n💾 Laporan tersimpan: {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
