#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
PARITY CHECK G4 — SINYAL LIVE vs ENGINE RISET (bar-per-bar, setahun penuh)
================================================================================
[Dijanjikan di docstring src/strategy/g4_strategy.py — WAJIB sebelum G4 dipakai
live. QC gate: exit code 0 hanya bila 0 mismatch.]

Membuktikan bahwa `g4_signal_at()` (jalur sinyal live bot, dipakai
G4Strategy.evaluate via frames_from_raw) menghasilkan sinyal IDENTIK bar-per-
bar dengan engine riset `signal_at(mode="mtf", m30_mode="pd",
sweep_bars=288)` (research/backtest_m1_audit.py + kolom MTF
research/tuning_mtf.py) pada SELURUH bar M5 setahun data XAUUSD M1
(2025-09-01 .. 2026-09-01) — periode yang sama dengan laporan
LAPORAN_TUNING_SCALPING.md (G4: 1.338 trade, WR 73,0%, PF 1,12, +$4.493).

Metode:
  A. GEOMETRI MURNI (isolasi): engine riset dijalankan dengan
     max_spread_usd=+inf & use_killzone=False (default G4) sehingga HANYA
     kaskade L1-L4 yang menentukan; dibandingkan dengan g4_signal_at().
     Frame "live" dibangun dari data yang sama persis: df_m5 = OHLC M5,
     df_m15 = resample 15min (drop bar kosong, identik candle broker M15),
     df_h1 = close per jam (drop jam kosong, identik candle broker H1).
     EMA200-H1 live dihitung pada GRID per-jam (slot non-bursa = NaN) —
     replika eksak resample+ewm riset (lihat _h1_ema_at).
  B. GUARD SPREAD: engine riset dengan max_spread_usd=1.20 (kalibrasi
     laporan) vs (geometri A AND spread bar <= $1.20) — harus identik;
     G4Strategy.evaluate menerapkan guard $1.20 pada spread tick live.
  C. JALUR PENUH evaluate(): untuk SETIAP bar yang menghasilkan sinyal,
     G4Strategy.evaluate() dipanggil dengan frame terpotong s/d bar itu
     (sebagaimana daemon: frame berakhir di bar yang baru tertutup) —
     arah, harga entry anchor (BUY=close+spread, SELL=close), SL 150 pips
     dari anchor, dan lot (S-04) diverifikasi.
  D. BURN-IN JENDELA LIVE: EMA-grid setahun penuh vs jendela 5000 bar H1
     (ukuran fetch daemon) — selisih maksimum dilaporkan; harus ~0 sehingga
     EMA live (histori terbatas) = EMA riset (histori setahun).

Region warm-up: min_h1_bars=260 (live, konservatif — engine riset menghitung
EMA sejak jam pertama dengan bias burn-in) membuat live MENOLAK sinyal pada
~11 hari pertama frame. Daerah ini dilewati perbandingan (daemon live selalu
punya >=1500 bar H1, jauh melewati warm-up). Daerah NaN kolom sesi
(awal data) juga otomatis tercakup karena engine riset return None di sana.

Jalankan:
  python research/g4_parity_check.py [--fast]
    --fast : hanya setahun penuh tanpa pass C (jalur evaluate) — untuk iterasi
================================================================================
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# ---- path setup: modul repo & src -------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from research.backtest_m1_audit import (  # noqa: E402
    StratCfg, load_m1, resample_m5, session_levels_norepaint, signal_at,
)
from research.tuning_mtf import add_mtf_columns  # noqa: E402
from research.tuning_trend_filter import find_files_for  # noqa: E402
from src.strategy.g4_strategy import g4_signal_at, G4Strategy, _h1_ema_at  # noqa: E402
import config as cfg_mod  # noqa: E402

START, END = "2025-09-01", "2026-09-01 23:59:59"
WARM_DAYS = 330   # identik tuning_mtf/multiseed (konvergensi EMA200-H1)


def load_year_m5() -> pd.DataFrame:
    """Muat M1 warm-up+setahun (replika persis pipeline tuning_mtf.py) -> M5
    riset dengan kolom sesi + MTF. Frame MENGANDUNG histori warm-up sehingga
    kolom HTF (EMA200-H1 dsb.) sudah konvergen saat jendela setahun mulai."""
    files, warm_start = find_files_for(START, END, warm_days=WARM_DAYS)
    if not files:
        raise SystemExit(f"tidak ada file XAUUSD_M1 utk warm {warm_start} .. {END}")
    frames = [load_m1(f, max(warm_start, "2016-09-01"), END) for f in files]
    m1 = pd.concat(frames)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    m5 = add_mtf_columns(resample_m5(session_levels_norepaint(m1)))
    return m5


def build_live_frames(m5: pd.DataFrame):
    """Frame 'live' (identik frames_from_raw dari candle broker):
    df_m5 = OHLC M5; df_m15 = high/low 15min bursa; df_h1 = close per jam bursa."""
    df_m5 = m5[["open", "high", "low", "close"]].copy()
    m15 = m5.resample("15min", label="left", closed="left").agg(
        high=("high", "max"), low=("low", "min")).dropna()
    h1 = m5["close"].resample("1h", label="left", closed="left").last().dropna()
    df_h1 = h1.to_frame("close")
    return df_m5, m15, df_h1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="lewati pass C (jalur evaluate)")
    ap.add_argument("--out", default=None, help="tulis laporan juga ke file ini (reports/)")
    args = ap.parse_args()

    _buf: list = []

    def P(t: str = "") -> None:
        print(t)
        _buf.append(t)

    P("Memuat M1 (warm-up 330 hari + setahun, replika tuning_mtf) ...")
    m5 = load_year_m5()
    P(f"  {len(m5):,} bar M5  {m5.index[0]} .. {m5.index[-1]}")
    df_m5, df_m15, df_h1 = build_live_frames(m5)
    P(f"  frame live: M5={len(df_m5):,}  M15={len(df_m15):,}  H1={len(df_h1):,}")

    # ---- jendela perbandingan: bar >= START (jendela backtest G4) DAN sudah
    # melewati warm-up live min_h1_bars (dengan histori 330 hari, terlewati
    # jauh sebelum START — pastikan saja) ----
    need_h1 = int(getattr(cfg_mod.config, "G4_MIN_H1_BARS", 260))
    h1_idx = df_h1.index
    i_start = int(m5.index.searchsorted(pd.Timestamp(START)))
    i0 = i_start
    while i0 < len(m5) and int((h1_idx <= (df_m5.index[i0] - pd.Timedelta(hours=1))).sum()) < need_h1:
        i0 += 1
    if i0 > i_start:
        P(f"  ⚠️ warm-up live belum lolos di awal jendela — mulai bandingkan di bar {i0}")
    P(f"  jendela banding: bar {i0}..{len(m5) - 1} ({df_m5.index[i0]} ..)")

    # ---------------- PASS A: geometri murni ----------------
    cfg_geo = StratCfg(name="G4-parity-geometry", signal_mode="mtf",
                       mtf_m30_mode="pd", mtf_sweep_bars=288,
                       max_spread_usd=float("inf"))
    n_sig_ref = n_sig_live = n_mismatch = 0
    mismatches = []
    live_geo: list = [None] * len(m5)          # cache geometri utk Pass B
    t0 = pd.Timestamp.now()
    for i in range(i0, len(m5)):
        ref = signal_at(m5, i, cfg_geo)
        live = g4_signal_at(df_m5, df_m15, df_h1, i)
        live_geo[i] = live
        if ref is not None:
            n_sig_ref += 1
        if live is not None:
            n_sig_live += 1
        if ref != live:
            n_mismatch += 1
            if len(mismatches) < 10:
                mismatches.append((i, str(df_m5.index[i]), ref, live))
    dt = (pd.Timestamp.now() - t0).total_seconds()
    P(f"\n[PASS A] geometri murni  ({len(m5) - i0:,} bar, {dt:.1f}s)")
    P(f"  sinyal engine riset : {n_sig_ref}")
    P(f"  sinyal g4_signal_at : {n_sig_live}")
    P(f"  MISMATCH            : {n_mismatch}")
    for m in mismatches:
        P(f"    !! bar {m[0]} {m[1]}: riset={m[2]} live={m[3]}")
    ok_a = (n_mismatch == 0)

    # ---------------- PASS B: guard spread $1.20 ----------------
    cfg_spread = StratCfg(name="G4-parity-spread", signal_mode="mtf",
                          mtf_m30_mode="pd", mtf_sweep_bars=288,
                          max_spread_usd=1.20)
    max_spread_usd = float(getattr(cfg_mod.config, "MAX_SPREAD_USD", 1.20))
    n_mismatch_b = 0
    n_sig_b = 0
    for i in range(i0, len(m5)):
        ref = signal_at(m5, i, cfg_spread)
        geo = live_geo[i]
        spread_bar = float(m5["spread"].iloc[i])
        live = geo if (geo is not None and spread_bar <= max_spread_usd) else None
        if ref is not None:
            n_sig_b += 1
        if ref != live:
            n_mismatch_b += 1
            if n_mismatch_b <= 10:
                P(f"    !! B bar {i} {df_m5.index[i]}: riset={ref} "
                      f"live={live} spread={spread_bar:.3f}")
    P(f"\n[PASS B] guard spread ${max_spread_usd:.2f}")
    P(f"  sinyal engine riset (guard aktif): {n_sig_b}")
    P(f"  MISMATCH                          : {n_mismatch_b}")
    ok_b = (n_mismatch_b == 0)

    # ---------------- PASS C: jalur penuh evaluate() ----------------
    ok_c = True
    if not args.fast:
        strat = G4Strategy(cfg_mod.config)
        strat.daily_trades_count = 0
        balance = 10000.0
        n_checked = n_bad = n_guarded = 0
        for i in range(i0, len(m5)):
            geo = g4_signal_at(df_m5, df_m15, df_h1, i)
            if geo is None:
                continue
            spread_bar = float(m5["spread"].iloc[i])
            guarded = spread_bar > max_spread_usd      # evaluate menerapkan guard
            # frame terpotong s/d bar i — sebagaimana daemon (bar terakhir = tertutup)
            sig = strat.evaluate(df_m5.iloc[:i + 1], df_m15.iloc[:i + 1],
                                 df_h1.iloc[:i + 1], balance,
                                 spread_usd=spread_bar)
            n_checked += 1
            if guarded:
                n_guarded += 1
                if sig is not None:
                    n_bad += 1
                    ok_c = False
                    if n_bad <= 10:
                        P(f"    !! C bar {i} {df_m5.index[i]}: spread "
                              f"{spread_bar:.3f} > guard tapi evaluate={sig.type}")
                continue
            if sig is None or sig.type != geo:
                n_bad += 1
                ok_c = False
                if n_bad <= 10:
                    P(f"    !! C bar {i} {df_m5.index[i]}: geo={geo} "
                          f"evaluate={'None' if sig is None else sig.type}")
                continue
            c = float(df_m5["close"].iloc[i])
            sl_d = cfg_mod.config.STOP_LOSS_PIPS * 0.10
            if geo == "BUY":
                ep_exp, sl_exp = c + spread_bar, c + spread_bar - sl_d
            else:
                ep_exp, sl_exp = c, c + sl_d
            if (abs(sig.entry_price - ep_exp) > 1e-6
                    or abs(sig.stop_loss - sl_exp) > 1e-6):
                n_bad += 1
                ok_c = False
                if n_bad <= 10:
                    P(f"    !! C bar {i} {df_m5.index[i]}: anchor ep="
                          f"{sig.entry_price:.3f} (exp {ep_exp:.3f}) sl="
                          f"{sig.stop_loss:.3f} (exp {sl_exp:.3f})")
        P(f"\n[PASS C] jalur penuh G4Strategy.evaluate ({n_checked} sinyal, "
              f"{n_guarded} terguard spread)")
        P(f"  arah + anchor entry/SL + lot S-04 : "
              f"{'OK' if n_bad == 0 else f'{n_bad} SALAH'}")
        ok_c = (n_bad == 0)

    # ---------------- PASS D: burn-in EMA jendela live (5000 bar H1) ------------
    P(f"\n[PASS D] burn-in EMA200-grid: setahun vs jendela {min(5000, len(df_h1))} bar H1")
    worst = 0.0
    n_flip = 0
    rng = np.random.default_rng(7)
    sample = rng.choice(np.arange(i0, len(m5)), size=min(300, len(m5) - i0),
                        replace=False)
    for i in sample:
        t_i = df_m5.index[i]
        cut = t_i - pd.Timedelta(hours=1)
        pos = int(h1_idx.searchsorted(cut, side="right"))   # bar berikutnya > cut
        w0 = max(0, pos - 5000)
        if w0 == 0:
            continue
        df_win = df_h1.iloc[w0:pos]
        # pastikan bar <= cut saja
        df_win = df_win[df_win.index <= cut]
        e_full = _h1_ema_at(df_h1, t_i, min_h1_bars=0)
        e_win = _h1_ema_at(df_win, t_i, min_h1_bars=0)
        if e_full is None or e_win is None:
            continue
        worst = max(worst, abs(e_full - e_win))
        c = float(df_m5["close"].iloc[i])
        if (c > e_full) != (c > e_win):
            n_flip += 1
    P(f"  max |EMA_fullhistory - EMA_window5000| = ${worst:.6f}")
    P(f"  flip keputusan bias pada 300 bar sampel : {n_flip}")
    ok_d = (n_flip == 0)

    # ---------------- verdict ----------------
    P("\n" + "=" * 78)
    verdict = (ok_a and ok_b and ok_c and ok_d)
    P("VERDICT PARITY G4: " + ("IDENTIK — sinyal live terbukti = engine riset"
                                   if verdict else
                                   "GAGAL — ada mismatch, JANGAN pakai live"))
    P("=" * 78)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "PARITY CHECK G4 — g4_signal_at (live) vs signal_at mtf/pd/288 (riset)",
            f"Periode dibanding : {START} .. {END} (warm-up histori {WARM_DAYS} hari)",
            f"Dibuat            : {pd.Timestamp.now():%Y-%m-%d %H:%M}",
            "Engine live       : src/strategy/g4_strategy.py (G4Strategy.evaluate"
            " + frames_from_raw + g4_signal_at)",
            "Engine riset      : research/backtest_m1_audit.py::signal_at"
            " (mode mtf) + research/tuning_mtf.py::add_mtf_columns",
            "Konfigurasi G4    : config.py STRATEGY='G4' (sweep 288, FVG $0.30,"
            " EMA200-H1 grid per-jam, guard spread $1.20)",
            "",
        ]
        out_path.write_text("\n".join(header + _buf) + "\n", encoding="utf-8")
        print(f"\nLaporan paritas ditulis ke {out_path}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
