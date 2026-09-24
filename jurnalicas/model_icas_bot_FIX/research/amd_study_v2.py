#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STUDI AMD v2 — implementasi SETIA spesifikasi pemilik akun (24 Sep 2026)
================================================================================
Spec yang diuji (persis dokumen user):
  1. AKUMULASI  : range konsolidasi sempit — DUA definisi diuji:
       (a) DINAMIS  : 36 bar M5 terakhir (3 jam) dgn lebar <= 0.8 x ATR14-H1
                      (k=0.8 dipilih a priori, BUKAN ditune)
       (b) ASIA     : high/low sesi Asia 03:00-07:00 srv (kolom engine, kausal)
  2. MANIPULASI : spike menembus batas range (wick keluar; London/NY khas).
                  Gagal sebagai manipulasi bila close bertahan di luar >= 3 bar
                  beruntun (Itu breakout, bukan stop-hunt) -> episode batal.
  3. DISTRIBUSI : konfirmasi dalam 12 bar setelah sweep (salah SATU dari):
       FVG        : gap 3-bar searah pembalikan (buffer $0.30, konvensi G4)
       CISD       : close menembus open bar pertama dari run searah sweep
       REJECTION  : bar penolakan kuat (wick >= 60% range, close sepertiga ujung)
                  Entry di OPEN bar M5 berikutnya. SL di luar ekstrem sweep
                  (+$0.30 buffer). R = jarak entry->SL.
  4. EXIT       : TP = 2R penuh  |  split 50% @2R + 50% @3R (SL remainder tetap,
                  pesimis). Timeout 288 bar (24 jam) -> tutup di market.
  Risiko $100/trade; PnL = risk x R-multiple. Pesimis: SL dicek lebih dulu bila
  SL & TP tersentuh di bar yang sama. Spread riil per bar (kolom spread data;
  ask = bid + spread). TIDAK ada trailing (spec: pure RR).

Grid: 2 akumulasi x 2 exit = 4 konfigurasi x 3 periode. LAPORAN LENGAP SEMUA
konfigurasi (anti cherry-pick); 'pemenang' harus stabil di 3 periode.

Jalankan: python research/amd_study_v2.py [--out reports/amd_study_v2.txt]
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

from research.backtest_m1_audit import (  # noqa: E402
    load_m1, session_levels_norepaint, resample_m5,
)
from research.tuning_trend_filter import find_files_for  # noqa: E402

PERIODS = [
    ("2021-09-01", "2022-09-01 23:59:59"),
    ("2022-09-01", "2023-09-01 23:59:59"),
    ("2025-09-01", "2026-09-01 23:59:59"),
]
ACC_WIN = 36          # bar M5 jendela akumulasi dinamis (3 jam)
ACC_K = 0.8           # lebar maksimum relatif ATR14-H1 (a priori)
MANIP_WIN = 48        # bar maks menunggu manipulasi setelah akumulasi (4 jam)
CONFIRM_WIN = 12      # bar maks menunggu konfirmasi setelah sweep (1 jam)
FVG_BUFFER = 0.30
SL_BUFFER = 0.30
R_MIN, R_MAX = 0.50, 25.0   # $ — sanity jarak struktural
TIMEOUT_BARS = 288
RISK = 100.0


def load_period(start: str, end: str) -> pd.DataFrame:
    """M5 + level sesi, TERPOTONG ke [start, end] (warm-up ikut dimuat agar
    asian_* hari pertama valid, lalu dibuang)."""
    files, _warm = find_files_for(start, end, warm_days=330)
    m1 = pd.concat([load_m1(f, max(_warm, "2016-09-01"), end) for f in files])
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    m5 = resample_m5(session_levels_norepaint(m1))
    return m5[m5.index >= pd.Timestamp(start)].copy()


def atr_h1_causal(m5: pd.DataFrame) -> np.ndarray:
    """ATR14-H1 (high-low H1 sederhana) per bar M5 — hanya H1 yang SUDAH tutup."""
    h1 = m5["high"].resample("1h", label="left", closed="left").max()
    l1 = m5["low"].resample("1h", label="left", closed="left").min()
    rng = (h1 - l1).dropna()
    atr = rng.rolling(14).mean()
    # map: bar M5 t memakai ATR H1 berlabel <= t - 1 jam (pad = H1 terakhir
    # yang SUDAH tutup saat t; bar H1 berlabel L tutup di L+1h <= t)
    target = m5.index - pd.Timedelta(hours=1)
    return atr.reindex(target, method="pad").to_numpy()


def run_amd(m5: pd.DataFrame, accum: str, exit_mode: str) -> dict:
    o = m5["open"].to_numpy(float)
    h = m5["high"].to_numpy(float)
    l = m5["low"].to_numpy(float)
    c = m5["close"].to_numpy(float)
    sp = m5["spread"].to_numpy(float)
    hr = m5["srv_hour"].to_numpy(float)
    a_hi = m5["asian_high"].to_numpy(float)
    a_lo = m5["asian_low"].to_numpy(float)
    atr = atr_h1_causal(m5)
    n = len(m5)
    ts = m5.index

    trades = []
    conf_count = {"FVG": 0, "CISD": 0, "REJ": 0}
    skip_bad_r = 0
    last_trade_day = None

    def _episode(k0: int, rh: float, rl: float):
        """Scan manipulasi+konfirmasi dari bar k0. Return (trade|None, last_k):
        last_k = bar terakhir yang dikonsumsi episode (pemanggil melanjutkan
        dari last_k+1 — episode TIDAK boleh dipakai ulang)."""
        nonlocal skip_bad_r
        sweep_dir = 0
        ext = 0.0
        j = -1
        beyond = 0
        for k in range(k0, min(k0 + MANIP_WIN, n - 2)):
            if h[k] > rh:
                if sweep_dir <= 0:
                    if sweep_dir == 0:
                        sweep_dir, ext, j = 1, float(h[k]), k
                    else:
                        return None, k          # sweep dua arah -> episode batal
                else:
                    ext = max(ext, float(h[k]))
                beyond = beyond + 1 if c[k] > rh else 0
            elif l[k] < rl:
                if sweep_dir >= 0:
                    if sweep_dir == 0:
                        sweep_dir, ext, j = -1, float(l[k]), k
                    else:
                        return None, k
                else:
                    ext = min(ext, float(l[k]))
                beyond = beyond + 1 if c[k] < rl else 0
            else:
                beyond = 0
            if sweep_dir != 0:
                if beyond >= 3:
                    return None, k              # breakout sah — bukan manipulasi
                if k > j and k - j > CONFIRM_WIN:
                    return None, k              # konfirmasi tidak datang
                if k > j:
                    direction = -sweep_dir
                    conf = None
                    if direction == 1 and l[k] > h[k - 2] + FVG_BUFFER:
                        conf = "FVG"
                    if conf is None and direction == -1 and h[k] < l[k - 2] - FVG_BUFFER:
                        conf = "FVG"
                    if conf is None:
                        m = k - 1
                        while m > 0 and (c[m] - o[m]) * sweep_dir > 0:
                            m -= 1
                        cisd_level = o[m + 1]
                        if direction == 1 and c[k] > cisd_level:
                            conf = "CISD"
                        elif direction == -1 and c[k] < cisd_level:
                            conf = "CISD"
                    if conf is None:
                        rng = h[k] - l[k]
                        if rng > 0:
                            if direction == 1 and (min(o[k], c[k]) - l[k]) >= 0.60 * rng \
                                    and c[k] >= l[k] + 0.60 * rng \
                                    and l[k] <= ext + 0.5 * (rh - rl):
                                conf = "REJ"
                            elif direction == -1 and (h[k] - max(o[k], c[k])) >= 0.60 * rng \
                                    and c[k] <= h[k] - 0.60 * rng \
                                    and h[k] >= ext - 0.5 * (rh - rl):
                                conf = "REJ"
                    if conf is not None:
                        e = k + 1
                        if direction == 1:
                            entry, sl = o[e] + sp[e], ext - SL_BUFFER
                            rdist = entry - sl
                        else:
                            entry, sl = o[e], ext + SL_BUFFER
                            rdist = sl - entry
                        if not (R_MIN <= rdist <= R_MAX):
                            skip_bad_r += 1
                            return None, e      # struktur tak sehat — episode habis
                        conf_count[conf] += 1
                        tp2 = entry + direction * 2 * rdist
                        tp3 = entry + direction * 3 * rdist
                        r_mult, done2, b = None, False, e
                        for b in range(e, min(e + TIMEOUT_BARS, n)):
                            if direction == 1:
                                hit_sl, hit_tp2, hit_tp3 = l[b] <= sl, h[b] >= tp2, h[b] >= tp3
                            else:
                                hit_sl = h[b] + sp[b] >= sl
                                hit_tp2 = l[b] + sp[b] <= tp2
                                hit_tp3 = l[b] + sp[b] <= tp3
                            if hit_sl:
                                r_mult = (1.0 if (done2 and exit_mode != "2r") else 0.0) - 1.0
                                break
                            if exit_mode == "2r":
                                if hit_tp2:
                                    r_mult = 2.0
                                    break
                            else:
                                if hit_tp3:
                                    r_mult = 2.5
                                    break
                                if hit_tp2 and not done2:
                                    done2 = True
                        else:
                            b = min(e + TIMEOUT_BARS, n) - 1
                            px = c[b] + (sp[b] if direction == 1 else 0.0)
                            r_tail = direction * (px - entry) / rdist
                            r_mult = (1.0 + 0.5 * max(-2.0, r_tail)
                                      if (done2 and exit_mode != "2r") else r_tail)
                        trade = {"ts": ts[e], "dir": "BUY" if direction == 1 else "SELL",
                                 "conf": conf, "r": r_mult, "pnl": RISK * r_mult,
                                 "bars": (b - e)}
                        return trade, b
        return None, min(k0 + MANIP_WIN, n - 2)

    i = max(ACC_WIN + 2, 100)
    while i < n - 2:
        if accum == "dinamis":
            if np.isnan(atr[i - 1]):
                i += 1
                continue
            w = slice(i - ACC_WIN, i)
            rh, rl = float(h[w].max()), float(l[w].min())
            if not (rh > rl and (rh - rl) <= ACC_K * atr[i - 1]):
                i += 1
                continue
        else:
            if np.isnan(a_hi[i]) or not (7 <= hr[i] <= 13) or not a_hi[i] > a_lo[i]:
                i += 1
                continue
            if last_trade_day is not None and ts[i].date() == last_trade_day:
                i += 1
                continue
            rh, rl = float(a_hi[i]), float(a_lo[i])
        trade, last_k = _episode(i, rh, rl)
        if trade is not None:
            trades.append(trade)
            last_trade_day = trade["ts"].date()
            i = last_k + 1
        else:
            i = last_k + 1

    tdf = pd.DataFrame(trades)
    return {"tdf": tdf, "conf_count": conf_count, "skipped_r": skip_bad_r}


def stats(tdf: pd.DataFrame, risk: float = RISK) -> str:
    if not len(tdf):
        return "0 trade"
    w = tdf[tdf["pnl"] > 0]
    lss = tdf[tdf["pnl"] <= 0]
    pf = w["pnl"].sum() / abs(lss["pnl"].sum()) if len(lss) and lss["pnl"].sum() != 0 else float("inf")
    eq = tdf["pnl"].cumsum()
    dd = (eq - eq.cummax()).min()
    return (f"n={len(tdf):4d}  WR={100 * len(w) / len(tdf):5.1f}%  avgR={tdf['r'].mean():+.2f}  "
            f"net=${tdf['pnl'].sum():+8.0f}  PF={pf:4.2f}  maxDD=${dd:7.0f}  "
            f"medHold={int(tdf['bars'].median())}bar")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    buf: list = []

    def P(t: str = "") -> None:
        print(t)
        buf.append(t)

    P("=" * 100)
    P(" STUDI AMD v2 — implementasi SETIA spec pemilik akun (SL struktural + RR 1:2/1:3)")
    P(" Akumulasi: dinamis 3j (<=0.8 ATR14-H1) / Asia 03-07 | sweep | konfirmasi FVG/CISD/REJ")
    P(" SL luar ekstrem sweep | TP 2R penuh / split 2R+3R | timeout 24j | risk $100 | pesimis")
    P("=" * 100)

    grid = [("dinamis", "2r"), ("dinamis", "split"), ("asia", "2r"), ("asia", "split")]
    summary = {}
    for (start, end) in PERIODS:
        P(f"\n### PERIODE {start[:10]} .. {end[:10]}")
        m5 = load_period(start, end)
        P(f"    {len(m5):,} bar M5  {m5.index[0]} .. {m5.index[-1]}")
        for accum, exm in grid:
            res = run_amd(m5, accum, exm)
            tdf = res["tdf"]
            key = f"{accum}/{exm}"
            summary.setdefault(key, []).append(tdf["pnl"].sum() if len(tdf) else 0.0)
            P(f"  {key:14s} {stats(tdf)}   [konfirmasi: {res['conf_count']}, skipR: {res['skipped_r']}]")

    P("\n### RINGKASAN STABILITAS (net $ per periode)")
    P(f"  {'konfigurasi':16s} {'2021-22':>10s} {'2022-23':>10s} {'2025-26':>10s} {'TOTAL':>10s}  stabil?")
    for key, vals in summary.items():
        tot = sum(vals)
        stable = all(v > 0 for v in vals)
        P(f"  {key:16s} {vals[0]:>+10.0f} {vals[1]:>+10.0f} {vals[2]:>+10.0f} {tot:>+10.0f}  "
          f"{'YA — positif di SEMUA periode' if stable else 'tidak'}")

    P("\nCATATAN: grid 4 konfigurasi diuji terbuka (semua dilaporkan) — konfigurasi 'menang'")
    P("wajib positif di KETIGA periode agar layak dibahas; selain itu = tidak layak.")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(buf) + "\n", encoding="utf-8")
        P(f"\nLaporan ditulis ke {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
