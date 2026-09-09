"""
================================================================================
MONTE-CARLO MULTI-SEED — uji signifikansi kandidat MTF vs distribusi acak
================================================================================
Satu kontrol acak tunggal pada n kecil (30-50 trade) tidak bermakana (variance
dominan — bisa "profit" karena keberuntungan, lihat rev 2.2). Skrip ini menjalankan
KONTROL ACAK BANYAK (default 24 seed) dengan GEOMETRI & jumlah entry identik ke
kandidat, lalu melaporkan posisi kandidat dalam distribusi acak:

  p-value empiris = fraksi seed acak yang net-nya >= net kandidat.

  p < 0.05  -> kandidat signifikan di atas keberuntungan (pada periode & geometri ini)
  p >= 0.05 -> TIDAK dapat dibedakan dari acak

Jalankan:
  .venv/bin/python research/multiseed_check.py --start 2025-09-01 \
      --end "2026-09-01 23:59:59" --risk 100 --seeds 24
================================================================================
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import dataclasses
import numpy as np
import pandas as pd

from research.backtest_m1_audit import (  # noqa: E402
    load_m1, session_levels_norepaint, resample_m5, run_backtest,
    StratCfg, CFG_CURRENT,
)
from research.tuning_trend_filter import find_files_for, add_filter_columns  # noqa: E402
from research.tuning_mtf import add_mtf_columns, exec_frame_from_m5, VARIANTS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# kandidat default (nama varian tuning_mtf) — geometri diambil dari VARIANTS
CANDIDATES = ("V7T", "V7E", "V7TA", "V7TD")


def main():
    ap = argparse.ArgumentParser(description="Monte-Carlo multi-seed kontrol acak utk kandidat MTF")
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default="2026-09-01 23:59:59")
    ap.add_argument("--risk", type=float, default=100.0)
    ap.add_argument("--guard", type=float, default=1.20)
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--candidates", default=",".join(CANDIDATES),
                    help="kode varian tuning_mtf yang diuji, dipisah koma")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    candidates = tuple(c.strip() for c in args.candidates.split(",") if c.strip())

    out: list[str] = []
    E = lambda t="": (print(t), out.append(t))  # noqa: E731

    files, warm_start = find_files_for(args.start, args.end, warm_days=330)
    frames = [load_m1(f, max(warm_start, "2016-09-01"), args.end) for f in files]
    m1 = pd.concat(frames)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    m1 = session_levels_norepaint(m1)
    m5 = add_filter_columns(add_mtf_columns(resample_m5(m1)))
    m1x = exec_frame_from_m5(m1, m5)

    E("=" * 96)
    E(f" 🎲 MONTE-CARLO MULTI-SEED | {args.start[:10]} .. {args.end[:10]} | "
      f"risk ${args.risk:,.0f} | {args.seeds} seed acak | eksekusi M5")
    E("=" * 96)
    E(f" {'Kandidat':44s} | {'Tr':>4s} | {'PF':>6s} | {'Net $':>10s} | "
      f"{'Acak net μ (min..maks)':>26s} | {'PF acak μ':>9s} | {'p-value':>8s} | Vonis")
    E("-" * 130)

    rng_seeds = list(range(1, args.seeds + 1))
    for code in candidates:
        if code not in VARIANTS:
            raise SystemExit(f"varian tidak dikenal: {code}")
        name, ov = VARIANTS[code]
        kw = {"risk_usd": args.risk, "max_spread_usd": args.guard,
              "strict_bar_open_entry": True, "manage_entry_bar": True, **ov}
        kw.setdefault("signal_mode", "mtf" if code.startswith(("V", "W")) else "choch")
        cfg = dataclasses.replace(CFG_CURRENT, name=code, **kw)

        st = run_backtest(m1x, m5, cfg, capital0=args.capital, trade_from=args.start)
        n = st["trades"]

        cfgR = dataclasses.replace(cfg, name=f"RANDOM-{code}")
        nets, pfs = [], []
        for s in rng_seeds:
            stR = run_backtest(m1x, m5, cfgR, capital0=args.capital,
                               trade_from=args.start, random_seed=s, n_random=n)
            nets.append(stR["net"])
            pfs.append(stR["pf"] if np.isfinite(stR["pf"]) else 0.0)
        nets = np.asarray(nets)
        p = float((nets >= st["net"]).mean())
        verdict = "SIGNIFIKAN" if p < 0.05 else ("MARGINAL" if p < 0.10 else "TIDAK BEDA DARI ACAK")
        E(f" {code + ' — ' + name:44s} | {n:4d} | {st['pf']:6.2f} | {st['net']:+10,.0f} | "
          f"{nets.mean():+9,.0f} ({nets.min():+8,.0f}..{nets.max():+8,.0f}) | "
          f"{np.mean(pfs):9.2f} | {p:8.3f} | {verdict}")

    E("")
    E("p-value = fraksi seed acak dengan net >= kandidat (empiris, satu sisi).")
    E("Catatan: p-value berlaku utk periode & geometri ini saja; tetap bukan jaminan")

    path = args.out or os.path.join(
        HERE, "..", "reports",
        f"multiseed_mtf_{pd.Timestamp(args.start):%Y%m%d}_{pd.Timestamp(args.end):%Y%m%d}"
        f"_risk{int(args.risk)}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"\n💾 Laporan tersimpan: {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
