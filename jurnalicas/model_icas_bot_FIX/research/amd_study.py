#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STUDI AMD (Accumulation-Manipulation-Distribution) — XAUUSD, tiga periode
================================================================================
[Pertanyaan pemilik akun 24 Sep 2026: "kalo di tambahkan strategi amd gimana?"]

Definisi kuantitatif (ICT klasik, disesuaikan blok bangunan engine — semua
KAUSAL, tanpa lookahead; level sesi dari session_levels_norepaint, waktu
SERVER = Europe/Athens):

  ACCUMULATION  : range sesi Asia 03:00-07:00 srv (asian_high/asian_low,
                  terpublikasi tepat 07:00 — kolom engine, tanpa repaint).
  MANIPULATION  : harga menyapu SATU sisi range Asia SETELAH 07:00 srv
                  (wick low <= asian_low = sweep bawah; wick high >=
                  asian_high = sweep atas). Varian AMD-L: sweep hanya boleh
                  terjadi di sesi London 08:00-12:00 srv (judas swing klasik).
  DISTRIBUTION  : di jendela 12:00-18:00 srv (London close -> NY pagi),
                  bar M5 TERTUTUP pertama yang close KEMBALI ke sisi level
                  (close > asian_low utk BUY / close < asian_high utk SELL)
                  + candle displacement searah (close > open utk BUY) → entry
                  di open bar M5 berikutnya (engine eksekusi M5).

  Maks 1 sinyal per arah per hari (karakter "one play a day" AMD).
  Exit = geometri IDENTIK G4 (SL150, TP plan 187.5/375/562.5 split
  30/25/25/20, trail cepat 50/30, strict_bar_open_entry, manage_entry_bar,
  guard spread $1.20, risk $100) — hasil langsung sebanding dgn G4.

Periode uji: 2021-09..2022-09, 2022-09..2023-09, 2025-09..2026-09
(dua periode pertama = lebih "out-of-sample" utk konsep yang dirumuskan
sekarang; 2025-26 = periode tuning G4 — hati-hati multiple testing).

Jalankan:
  python research/amd_study.py [--out reports/amd_study.txt] [--skip-g4]
================================================================================
"""
from __future__ import annotations

import sys
import argparse
import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from research.backtest_m1_audit import (  # noqa: E402
    StratCfg, CFG_CURRENT, load_m1, session_levels_norepaint, resample_m5,
    run_backtest,
)
from research.backtest_m1_period import print_stats, month_table  # noqa: E402
from research.tuning_mtf import VARIANTS, exec_frame_from_m5  # noqa: E402
from research.tuning_trend_filter import find_files_for  # noqa: E402

PERIODS = [
    ("2021-09-01", "2022-09-01 23:59:59"),
    ("2022-09-01", "2023-09-01 23:59:59"),
    ("2025-09-01", "2026-09-01 23:59:59"),
]


def add_amd_columns(m5: pd.DataFrame, dist_start: int = 12, dist_end: int = 18,
                    london_only: bool = False) -> pd.DataFrame:
    """Kolom sinyal AMD: amd_buy / amd_sell (bool per bar M5 tertutup).

    Kausal: level Asia hari ini hanya terlihat mulai 07:00 srv (kolom
    asian_* sudah tanpa-repaint); sweep diakumulasi maju per bar; sinyal
    hanya di jendela distribusi; maks 1 per arah per hari. Hari dikelompokkan
    per transisi srv_hour menurun (robust terhadap DST, tanpa perlu srv_date).
    """
    m5 = m5.copy()
    hr = m5["srv_hour"].to_numpy()
    lo = m5["low"].to_numpy()
    hi = m5["high"].to_numpy()
    cl = m5["close"].to_numpy()
    op = m5["open"].to_numpy()
    a_hi = m5["asian_high"].to_numpy()
    a_lo = m5["asian_low"].to_numpy()
    n = len(m5)

    day = np.zeros(n, dtype=int)
    for i in range(1, n):
        day[i] = day[i - 1] + (1 if hr[i] < hr[i - 1] else 0)

    buy = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    for d in range(day[-1] + 1):
        idxs = np.where(day == d)[0]
        hrd = hr[idxs]
        # level Asia hari INI: nilai kolom pada bar pertama dgn srv jam >= 7
        m7 = np.where(hrd >= 7)[0]
        if len(m7) == 0:
            continue
        j0 = idxs[m7[0]]
        asian_lo, asian_hi_d = a_lo[j0], a_hi[j0]
        if np.isnan(asian_lo) or np.isnan(asian_hi_d):
            continue
        swept_dn = swept_up = False
        fired_buy = fired_sell = False
        for k, i in enumerate(idxs):
            h = hrd[k]
            if h < 7:
                continue
            in_lon = (8 <= h < 12)
            if (h >= 8 and (not london_only or in_lon)) or (7 <= h < 8 and not london_only):
                if lo[i] <= asian_lo:
                    swept_dn = True
                if hi[i] >= asian_hi_d:
                    swept_up = True
            if dist_start <= h < dist_end:
                c, o = cl[i], op[i]
                if (not fired_buy) and swept_dn and c > asian_lo and c > o:
                    buy[i] = True
                    fired_buy = True
                if (not fired_sell) and swept_up and c < asian_hi_d and c < o:
                    sell[i] = True
                    fired_sell = True
    m5["amd_buy"] = buy
    m5["amd_sell"] = sell
    return m5


def load_period(start: str, end: str):
    files, warm = find_files_for(start, end, warm_days=330)
    if not files:
        raise SystemExit(f"tidak ada file M1 utk {start}..{end}")
    m1 = pd.concat([load_m1(f, max(warm, "2016-09-01"), end) for f in files])
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    return m1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-g4", action="store_true", help="lewati pembanding G4")
    args = ap.parse_args()
    buf: list = []

    def P(t: str = "") -> None:
        print(t)
        buf.append(t)

    P("=" * 96)
    P(" STUDI AMD (Accumulation-Manipulation-Distribution) — XAUUSD M5 | geometry exit = G4")
    P(" Asia 03-07 srv | sweep setelah 07:00 (AMD) / hanya London 08-12 (AMD-L) | distribusi 12-18 srv")
    P("=" * 96)

    g4_tdfs: dict = {}
    for (start, end) in PERIODS:
        P(f"\n{'#' * 96}\n### PERIODE {start[:10]} .. {end[:10]}\n{'#' * 96}")
        m1 = load_period(start, end)
        base = resample_m5(session_levels_norepaint(m1))
        m1x = exec_frame_from_m5(m1, base)

        # ---------- AMD ----------
        m5a = add_amd_columns(base, london_only=False)
        # ---------- AMD-L (sweep hanya sesi London) ----------
        m5l = add_amd_columns(base, london_only=True)

        for label, m5x in (("AMD", m5a), ("AMD-L", m5l)):
            n_b = int(m5x["amd_buy"].sum())
            n_s = int(m5x["amd_sell"].sum())
            P(f"\n>>> {label} — sinyal kolom: {n_b} BUY / {n_s} SELL")
            if n_b + n_s == 0:
                P("    (tidak ada sinyal — lewati)")
                continue
            cfg = dataclasses.replace(
                CFG_CURRENT, name=f"{label} — Asia sweep→NY distribusi (trail 50/30)",
                signal_mode="amd", trail_step_pips=50.0, risk_usd=100.0,
                max_spread_usd=1.20, strict_bar_open_entry=True, manage_entry_bar=True)
            st = run_backtest(m1x, m5x, cfg, capital0=10000.0, trade_from=start)
            print_stats(st, f"{label} — Asia sweep→NY distribusi (risk $100)", buf)
            month_table(st["tdf"], f"{label}", buf, capital0=10000.0)
            if label == "AMD" and start.startswith("2025"):
                st["tdf"].to_pickle("/tmp/amd_trades.pkl")

        # ---------- pembanding G4 ----------
        if not args.skip_g4:
            from research.tuning_mtf import add_mtf_columns
            m5g = add_mtf_columns(base)
            name, ov = VARIANTS["G4"]
            cfg = dataclasses.replace(
                CFG_CURRENT, name=f"G4 — {name}", risk_usd=100.0, max_spread_usd=1.20,
                strict_bar_open_entry=True, manage_entry_bar=True, **ov)
            st = run_backtest(m1x, m5g, cfg, capital0=10000.0, trade_from=start)
            print_stats(st, f"G4 — pembanding (risk $100)", buf)
            if start.startswith("2025"):
                st["tdf"].to_pickle("/tmp/g4_trades.pkl")

    # ---------- komplementaritas (periode 2025-26) ----------
    try:
        g4 = pd.read_pickle("/tmp/g4_trades.pkl")
        amd = pd.read_pickle("/tmp/amd_trades.pkl")
        P(f"\n{'#' * 96}\n### KOMPLEMENTARITAS G4 vs AMD (2025-09..2026-09)\n{'#' * 96}")
        for nm, tdf in (("G4", g4), ("AMD", amd)):
            d = pd.to_datetime(tdf["open_ts"])
            P(f"  {nm}: {len(tdf)} trade | jam entry (UTC) p25-p75: "
              f"{d.dt.hour.quantile(0.25):.0f}-{d.dt.hour.quantile(0.75):.0f} "
              f"| hari dgn entry: {d.dt.date.nunique()}")
        g4d = g4.assign(_d=pd.to_datetime(g4["open_ts"]).dt.date)
        amd_ = amd.assign(_d=pd.to_datetime(amd["open_ts"]).dt.date)
        days_both = len(set(g4d["_d"]) & set(amd_["_d"]))
        P(f"  hari dgn entry G4 & AMD bersamaan: {days_both} "
          f"({100 * days_both / max(1, len(set(amd_['_d']))):.0f}% dari hari AMD)")
        dg = g4d.groupby("_d")["pnl"].sum()
        da = amd_.groupby("_d")["pnl"].sum()
        all_days = sorted(set(dg.index) | set(da.index))
        x = pd.Series([dg.get(dd, 0.0) for dd in all_days])
        y = pd.Series([da.get(dd, 0.0) for dd in all_days])
        if len(all_days) > 5:
            P(f"  korelasi PnL harian G4 vs AMD: {x.corr(y):+.2f} "
              f"(1 = ganda risiko, 0 = pelengkap sempurna, -1 = lindung nilai)")
        P(f"  net G4 {g4['pnl'].sum():+.0f} + net AMD {amd['pnl'].sum():+.0f} "
          f"= gabungan {g4['pnl'].sum() + amd['pnl'].sum():+.0f} (naif, tanpa alokasi modal)")
    except Exception as e:
        P(f"  (komplementaritas dilewati: {e})")

    P("\n" + "=" * 96)
    P("CATATAN KEJUJURAN: 2025-26 = periode tuning G4 (in-sample utk konsep baru ini);")
    P("hasil positif apa pun WAJIB diverifikasi forward-test sebelum dipakai live.")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(buf) + "\n", encoding="utf-8")
        P(f"\nLaporan ditulis ke {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
