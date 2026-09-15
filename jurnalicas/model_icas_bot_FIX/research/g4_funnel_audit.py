#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
AUDIT FUNNEL KASKADE G4 — pengukuran empiris 4 kekhawatiran audit forensik
================================================================================
[Laporan: jurnalicas/LAPORAN_AUDIT_FORENSIK_G4.md — temuan C1..C5]

Mengukur pada SETAHUN data XAUUSD (2025-09-01..2026-09-01, replika persis
pipeline parity check — kini frame berlabel UTC = jalur live):

  1. FUNNEL L1→L4 (poin audit #4): berapa % bar M5 tertutup yang lolos tiap
     lapis (per arah BUY/SELL) dan AND-gating akhirnya. Konteks: 3.694 sinyal
     geometri/tahun; 1.338 menjadi trade setelah batasan eksekusi engine
     (mutex 1-posisi, strict_bar_open_entry, hari-bursa) — lihat
     LAPORAN_TUNING_SCALPING.md.

  2. KARAKTER SWEEP L2 (poin audit #2): pada bar sinyal — umur sweep (bar &
     jam sejak sentuh level), wick-only vs close-through, "reclaim" (close
     kembali ke sisi level) vs tidak, dan sesering apa KEDUA sisi menyala.

  3. KARAKTER CHoCH L3 (poin audit #1): fraksi sinyal yang bersifat
     continuation (swing lebih tinggi/rendah dari swing sebelumnya = searah
     bias H1) vs reversal (swing lebih rendah/tinggi = pemecahan struktur).

  4. DIVERGENSI PRA-FIX C5 (temuan audit internal): sinyal dengan pengelompokan
     hari label-frame (perilaku LAMA: kalender UTC → PDH/PDL beda dari riset)
     vs kalender Athens (perilaku BARU = riset). Mengukur berapa sinyal
     sebenarnya menyimpang selama ini.

Validasi: implementasi vektorisasi funnel dibandingkan dengan g4_signal_at()
(asli) pada sampel acak + SEMUA bar sinyal — wajib 100% identik.

Jalankan:
  python research/g4_funnel_audit.py [--out reports/g4_funnel_audit.txt]
================================================================================
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from research.g4_parity_check import load_year_m5, build_live_frames  # noqa: E402
from src.strategy.g4_strategy import g4_signal_at, _h1_ema_at  # noqa: E402
import config as cfg_mod  # noqa: E402

SWEEP_BARS = int(getattr(cfg_mod.config, "G4_SWEEP_BARS", 288))
FVG_BUFFER = float(getattr(cfg_mod.config, "G4_FVG_BUFFER_USD", 0.30))
EMA_SPAN = int(getattr(cfg_mod.config, "G4_H1_EMA_SPAN", 200))
MIN_H1 = int(getattr(cfg_mod.config, "G4_MIN_H1_BARS", 260))
START = "2025-09-01"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    _buf: list = []

    def P(t: str = "") -> None:
        print(t)
        _buf.append(t)

    P("=" * 78)
    P("AUDIT FUNNEL KASKADE G4 — setahun penuh, frame UTC (jalur live)")
    P("=" * 78)
    P("Memuat M1 (warm-up 330 hari + setahun) ...")
    m5 = load_year_m5()
    df_m5, df_m15, df_h1 = build_live_frames(m5)   # UTC-labeled (jalur live)
    P(f"  {len(m5):,} bar M5  {df_m5.index[0]} .. {df_m5.index[-1]}")

    need_h1 = MIN_H1
    h1_idx = df_h1.index
    i_start = int(m5.index.searchsorted(pd.Timestamp(START)))
    i0 = i_start
    while i0 < len(m5) and int((h1_idx <= (df_m5.index[i0] - pd.Timedelta(hours=1))).sum()) < need_h1:
        i0 += 1
    n = len(df_m5)
    P(f"  jendela audit: bar {i0}..{n - 1} ({df_m5.index[i0]} ..) = {n - i0:,} bar")

    idx = df_m5.index
    close = df_m5["close"].to_numpy(dtype=float)
    open_ = df_m5["open"].to_numpy(dtype=float)
    high = df_m5["high"].to_numpy(dtype=float)
    low = df_m5["low"].to_numpy(dtype=float)

    # ---------- L1: EMA200 H1 (cache per slot jam, replika _h1_ema_at) ----------
    P("  L1: EMA200-H1 (cache per slot) ...")
    slot_arr = ((idx - pd.Timedelta(hours=1))).floor("1h")
    uniq_slots = slot_arr.unique()
    ema_cache: dict = {}
    for s in uniq_slots:
        ema_cache[s] = _h1_ema_at(df_h1, s + pd.Timedelta(hours=1),
                                  ema_span=EMA_SPAN, min_h1_bars=MIN_H1)
    ema_at = np.array([ema_cache[s] for s in slot_arr], dtype=float)
    l1_bull = close > ema_at
    l1_bear = close < ema_at

    # ---------- L2: PD levels dua mode + sweep ----------
    P("  L2: PDH/PDL dua mode pengelompokan hari + sweep 288 bar ...")
    try:
        from zoneinfo import ZoneInfo
        _ATH = ZoneInfo("Europe/Athens")
    except Exception:
        raise SystemExit("zoneinfo tidak tersedia")
    ath_naive = idx.tz_localize("UTC").tz_convert(_ATH).tz_localize(None)
    ath_days = ath_naive.normalize()

    def _pd_arrays(day_index: pd.DatetimeIndex, t_probe: pd.DatetimeIndex):
        """PDH/PDL per bar: hari terakhir berlabel <= t-24j (mode 'label hari')."""
        day_key = pd.Series(1, index=day_index).groupby(day_index).size().index
        agg_h = pd.Series(high, index=day_index).groupby(day_index).max()
        agg_l = pd.Series(low, index=day_index).groupby(day_index).min()
        pos = day_key.searchsorted((t_probe - pd.Timedelta(hours=24)).normalize(),
                                   side="right") - 1
        ok = pos >= 0
        pos_c = np.clip(pos, 0, len(day_key) - 1)
        pdh = np.where(ok, agg_h.reindex(day_key[pos_c]).to_numpy(dtype=float), np.nan)
        pdl = np.where(ok, agg_l.reindex(day_key[pos_c]).to_numpy(dtype=float), np.nan)
        return pdh, pdl

    # mode ATHENS (baru = riset): hari = kalender Athens (NY close)
    pdh_ath, pdl_ath = _pd_arrays(pd.DatetimeIndex(ath_days), pd.DatetimeIndex(ath_naive))
    # mode LABEL (lama): hari = kalender label frame (UTC pra-fix C5)
    pdh_lab, pdl_lab = _pd_arrays(idx.normalize(), pd.DatetimeIndex(idx))

    roll_lo = pd.Series(low).rolling(SWEEP_BARS, min_periods=1).min().shift(1).to_numpy()
    roll_hi = pd.Series(high).rolling(SWEEP_BARS, min_periods=1).max().shift(1).to_numpy()

    def _sweep_flags(pdh, pdl):
        sb = roll_lo <= pdl
        ss = roll_hi >= pdh
        return sb, ss

    l2_buy_ath, l2_sell_ath = _sweep_flags(pdh_ath, pdl_ath)
    l2_buy_lab, l2_sell_lab = _sweep_flags(pdh_lab, pdl_lab)
    pd_unchanged = (np.nan_to_num(pdh_ath, nan=-9e9) == np.nan_to_num(pdh_lab, nan=-9e9)) & \
                   (np.nan_to_num(pdl_ath, nan=-9e9) == np.nan_to_num(pdl_lab, nan=-9e9))

    # ---------- L3: CHoCH M15 (rolling 5, shift 2) ----------
    P("  L3: swing M15 ...")
    m15_idx = df_m15.index
    m15_h = df_m15["high"].to_numpy(dtype=float)
    m15_l = df_m15["low"].to_numpy(dtype=float)
    sw_h_roll = pd.Series(m15_h).rolling(5).max().shift(2).to_numpy()
    sw_l_roll = pd.Series(m15_l).rolling(5).min().shift(2).to_numpy()
    sw_h_prev = pd.Series(m15_h).rolling(5).max().shift(7).to_numpy()   # window [k-11..k-7]
    sw_l_prev = pd.Series(m15_l).rolling(5).min().shift(7).to_numpy()
    k_arr = m15_idx.searchsorted((idx - pd.Timedelta(minutes=15)).values, side="right") - 1
    kc = np.clip(k_arr, 0, len(m15_idx) - 1)
    sw15_h = sw_h_roll[kc]
    sw15_l = sw_l_roll[kc]
    sw15_h_prev = sw_h_prev[kc]
    sw15_l_prev = sw_l_prev[kc]
    with np.errstate(invalid="ignore"):
        l3_bull = close > sw15_h
        l3_bear = close < sw15_l
        k_ok = (k_arr >= 6)
        l3_bull &= k_ok
        l3_bear &= k_ok

    # ---------- L4: trigger M5 ----------
    sw_h5 = pd.Series(high).rolling(5).max().shift(2).to_numpy()
    sw_l5 = pd.Series(low).rolling(5).min().shift(2).to_numpy()
    h_m2 = pd.Series(high).shift(2).to_numpy()
    l_m2 = pd.Series(low).shift(2).to_numpy()
    with np.errstate(invalid="ignore"):
        bull_fvg = low > (h_m2 + FVG_BUFFER)
        bear_fvg = high < (l_m2 - FVG_BUFFER)
        l4_bull = (close > open_) & ((close > sw_h5) | bull_fvg)
        l4_bear = (close < open_) & ((close < sw_l5) | bear_fvg)

    def _signals(l2b, l2s):
        buy = l1_bull & l2b & l3_bull & l4_bull
        sell = l1_bear & l2s & l3_bear & l4_bear
        return buy, sell

    buy_ath, sell_ath = _signals(l2_buy_ath, l2_sell_ath)
    buy_lab, sell_lab = _signals(l2_buy_lab, l2_sell_lab)
    sig_ath = np.where(buy_ath, "BUY", np.where(sell_ath, "SELL", ""))
    sig_lab = np.where(buy_lab, "BUY", np.where(sell_lab, "SELL", ""))

    # ---------- VALIDASI vs g4_signal_at ----------
    P("  VALIDASI: funnel vektor == g4_signal_at (sampel + semua bar sinyal) ...")
    rng = np.random.default_rng(7)
    sample = np.unique(np.concatenate([
        rng.choice(np.arange(i0, n), size=1200, replace=False),
        np.arange(i0, n)[sig_ath[i0:] != ""],
        np.arange(i0, n)[sig_lab[i0:] != ""]]))
    bad = 0
    for i in sample:
        ref = g4_signal_at(df_m5, df_m15, df_h1, i)
        mine = sig_ath[i] if sig_ath[i] else None
        if (ref or None) != (mine or None):
            bad += 1
            if bad <= 5:
                P(f"    !! bar {i} {idx[i]}: g4_signal_at={ref} funnel={mine}")
    P(f"  validasi: {len(sample):,} bar dicek, mismatch = {bad}")
    if bad:
        P("  STOP: funnel tidak identik dengan g4_signal_at — hasil tidak sahih.")
        return 1

    # ================= LAPORAN =================
    W = n - i0
    P("")
    P("=" * 78)
    P(f"[1] FUNNEL KASKADE — {W:,} bar M5 tertutup (setahun)")
    P("=" * 78)

    def _pct(x):
        return f"{100.0 * x / W:6.2f}%"

    for nm, l1, l2, l3, l4, s in [("BUY", l1_bull, l2_buy_ath, l3_bull, l4_bull, buy_ath),
                                  ("SELL", l1_bear, l2_sell_ath, l3_bear, l4_bear, sell_ath)]:
        c1 = int(l1[i0:].sum()); c2 = int((l1 & l2)[i0:].sum())
        c3 = int((l1 & l2 & l3)[i0:].sum()); c4 = int(s[i0:].sum())
        P(f"  {nm}: L1 bias      : {c1:7,}  ({_pct(c1)})")
        P(f"  {' ' * len(nm)}  L1+L2 sweep   : {c2:7,}  ({_pct(c2)})  [{100.0 * c2 / max(c1, 1):.1f}% dari L1]")
        P(f"  {' ' * len(nm)}  L1+L2+L3 choch : {c3:7,}  ({_pct(c3)})  [{100.0 * c3 / max(c2, 1):.1f}% dari L1+L2]")
        P(f"  {' ' * len(nm)}  SEMUA (sinyal) : {c4:7,}  ({_pct(c4)})  [{100.0 * c4 / max(c3, 1):.1f}% dari L1+L2+L3]")
    tot = int((sig_ath[i0:] != "").sum())
    P(f"  TOTAL sinyal geometri: {tot:,} ({tot / 243.0:.1f}/hari bursa) — "
      f"setelah guard spread $1.20 & batasan eksekusi engine → 1.338 trade "
      f"(5,5/hari; laporan tuning: WR 73,0%, PF 1,12, +$4.493)")

    # ================= [2] KARAKTER SWEEP =================
    P("")
    P("=" * 78)
    P("[2] KARAKTER SWEEP L2 PADA BAR SINYAL (mode Athens = riset)")
    P("=" * 78)
    rows = []
    for i in np.arange(i0, n)[sig_ath[i0:] != ""]:
        typ = sig_ath[i]
        if typ == "BUY":
            lvl = pdl_ath[i]
            win = low[max(0, i - SWEEP_BARS):i]
            touched = np.where(win <= lvl)[0]
            j = max(0, i - SWEEP_BARS) + int(touched[-1]) if len(touched) else None
            wick_only = bool(close[j] > lvl) if j is not None else None
            reclaim = bool(close[i] > lvl)
        else:
            lvl = pdh_ath[i]
            win = high[max(0, i - SWEEP_BARS):i]
            touched = np.where(win >= lvl)[0]
            j = max(0, i - SWEEP_BARS) + int(touched[-1]) if len(touched) else None
            wick_only = bool(close[j] < lvl) if j is not None else None
            reclaim = bool(close[i] < lvl)
        both = bool(l2_buy_ath[i] and l2_sell_ath[i])
        depth = (lvl - low[j]) if (j is not None and typ == "BUY") else \
                ((high[j] - lvl) if j is not None else np.nan)
        rows.append((i, typ, (i - j) if j is not None else None, wick_only, reclaim, both, depth))
    fr = pd.DataFrame(rows, columns=["i", "type", "age_bars", "wick_only", "reclaim", "both_sides", "depth"])
    fr["age_hours"] = fr["age_bars"] * 5.0 / 60.0
    P(f"  n = {len(fr):,} sinyal")
    P(f"  umur sweep saat sinyal : median {fr['age_bars'].median():.0f} bar "
      f"({fr['age_hours'].median():.1f} j), maks {fr['age_bars'].max():.0f} bar "
      f"({fr['age_hours'].max():.1f} j), <1 jam: {(fr['age_bars'] < 12).mean() * 100:.1f}%")
    P(f"  wick-only (close kembali ke sisi level di bar sentuh): {fr['wick_only'].mean() * 100:.1f}%  "
      f"(close-through: {(~fr['wick_only']).mean() * 100:.1f}%)")
    P(f"  reclaim di bar sinyal (close sudah kembali melintasi level): {fr['reclaim'].mean() * 100:.1f}%")
    P(f"  KEDUA sisi sweep menyala bersamaan di bar sinyal: {fr['both_sides'].mean() * 100:.1f}%")
    P(f"  kedalaman sweep median: ${fr['depth'].median():.2f} "
      f"(P90 ${fr['depth'].quantile(0.9):.2f})")

    # ================= [3] KARAKTER CHoCH =================
    P("")
    P("=" * 78)
    P("[3] KARAKTER CHoCH M15 PADA BAR SINYAL (konteks swing sebelumnya)")
    P("=" * 78)
    buys = fr[fr["type"] == "BUY"]
    sells = fr[fr["type"] == "SELL"]
    cont_b = float((sw15_h[buys['i']] >= sw15_h_prev[buys['i']]).mean() * 100) if len(buys) else 0.0
    rev_b = 100.0 - cont_b
    cont_s = float((sw15_l[sells['i']] <= sw15_l_prev[sells['i']]).mean() * 100) if len(sells) else 0.0
    rev_s = 100.0 - cont_s
    P(f"  BUY  (n={len(buys):,}): swing-high LEBIH TINGGI dari swing sebelumnya (continuation/BOS): {cont_b:.1f}%")
    P(f"        swing-high lebih RENDAH (reversal/karakter CHoCH murni): {rev_b:.1f}%")
    P(f"  SELL (n={len(sells):,}): swing-low LEBIH RENDAH (continuation/BOS): {cont_s:.1f}%")
    P(f"        swing-low lebih TINGGI (reversal/karakter CHoCH murni): {rev_s:.1f}%")

    # ================= [4] DIVERGENSI PRA-FIX C5 =================
    P("")
    P("=" * 78)
    P("[4] DIVERGENSI PENGELOMPOKAN HARI: lama (kalender label/UTC) vs baru (Athens = riset)")
    P("=" * 78)
    diff = (sig_ath[i0:] != sig_lab[i0:])
    P(f"  bar dengan PDH/PDL berbeda antar mode        : {(~pd_unchanged[i0:]).sum():,} "
      f"({100.0 * (~pd_unchanged[i0:]).sum() / W:.1f}% bar)")
    P(f"  bar dengan HASIL SINYAL berbeda               : {int(diff.sum()):,} "
      f"({100.0 * diff.sum() / W:.2f}% bar)")
    P(f"  sinyal mode Athens (riset = backtest +$4.493) : {int((sig_ath[i0:] != '').sum()):,}")
    P(f"  sinyal mode label (live pra-fix C5)           : {int((sig_lab[i0:] != '').sum()):,}")
    both_sig = int(((sig_ath[i0:] != '') & (sig_lab[i0:] != '')).sum())
    P(f"  sinyal yang SAMA di kedua mode                : {both_sig:,} "
      f"({100.0 * both_sig / max(1, int((sig_ath[i0:] != '').sum())):.1f}% dari sinyal riset)")

    P("")
    P("KESIMPULAN PENGUKURAN: lihat LAPORAN_AUDIT_FORENSIK_G4.md (temuan C1..C5).")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(_buf) + "\n", encoding="utf-8")
        P(f"\nLaporan funnel ditulis ke {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
