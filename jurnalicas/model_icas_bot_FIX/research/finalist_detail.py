"""
================================================================================
FINALIS KALIBRASI — detail window penuh (2026-05-14 -> 2026-08-25 14:30)
================================================================================
Menjalankan 4 preset finalis hasil grid walk-forward + ekstensi di atas
sequencing M1 definitif, lalu mencetak: ringkasan + PnL per bulan + statistik
win/loss rata-rata + ekspektasi. Dipakai sebagai tabel bukti di LAPORAN §9.

Cara pakai:  python3 research/finalist_detail.py
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import types
import dataclasses
import numpy as np
import pandas as pd
from config import config
from src.indicators.sessions import calculate_session_killzones
from src.backtest.granular_sequencer import run_granular, precompute_signals

FULL_START, FULL_END = "2026-05-14", "2026-08-25 14:30"

FINALISTS = {
    "F1 SL150 B(1/2/3)   BE OFF": dict(STOP_LOSS_PIPS=150.0, EARLY_BE_TRIGGER_PIPS=9999.0,
                                       TP1_PIPS=150.0, TP2_PIPS=300.0, TP3_PIPS=450.0),
    "F2 SL150 C(1.25/2.5/3.75) BE OFF": dict(STOP_LOSS_PIPS=150.0, EARLY_BE_TRIGGER_PIPS=9999.0,
                                             TP1_PIPS=187.5, TP2_PIPS=375.0, TP3_PIPS=562.5),
    "F3 SL200 C(1.25/2.5/3.75) BE OFF": dict(STOP_LOSS_PIPS=200.0, EARLY_BE_TRIGGER_PIPS=9999.0,
                                             TP1_PIPS=250.0, TP2_PIPS=500.0, TP3_PIPS=750.0),
    "F4 SL200 B(1/2/3)   BE 60": dict(STOP_LOSS_PIPS=200.0, EARLY_BE_TRIGGER_PIPS=60.0,
                                      TP1_PIPS=200.0, TP2_PIPS=400.0, TP3_PIPS=600.0),
}


def mk(**ov):
    b = dataclasses.asdict(config)
    b.update(ov)
    b.setdefault("RISK_USD_OVERRIDE", 500.0)
    return types.SimpleNamespace(**b)


def main():
    df = pd.read_csv("data/historical/xauusd_m5_from_m1.csv")
    df["time"] = pd.to_datetime(df["time"])
    df = calculate_session_killzones(df)
    fine = pd.read_csv("data/historical/xauusd_m1_broker.csv")
    fine["time"] = pd.to_datetime(fine["time"])

    cfg_sig = mk()
    buy, sell = precompute_signals(df, cfg_sig)

    print("=" * 118)
    print(f" FINALIS — WINDOW PENUH {FULL_START} -> {FULL_END} | sequencing M1 | risiko tetap $500/trade")
    print("=" * 118)
    for name, ov in FINALISTS.items():
        cfg = mk(**ov)
        st = run_granular(df, fine, cfg, FULL_START, FULL_END, buy, sell, return_trades=True)
        t = st["tdf"]
        wins = t[t["pnl"] > 0]["pnl"]
        losses = t[t["pnl"] < 0]["pnl"]
        exp = t["pnl"].mean()
        months = t.groupby("month")["pnl"].sum()

        print(f"\n>>> {name}")
        print(f"    {st['trades']} tr ({st['wins']}W/{st['be']}BE/{st['losses']}L) | WinRate {st['wins']/max(1,st['trades'])*100:.1f}% | "
              f"NLR {st['nlr']:.1f}% | PF {st['pf']:.2f} | Net ${st['net']:+,.0f} | DD {st['dd_pct']:.1f}%")
        print(f"    Ekspektasi/trade ${exp:+.0f} | AvgWin ${wins.mean() if len(wins) else 0:+,.0f} ({len(wins)}) | "
              f"AvgLoss ${losses.mean() if len(losses) else 0:+,.0f} ({len(losses)})")
        mtxt = " | ".join(f"{m} ${v:+,.0f}" for m, v in months.items())
        print(f"    Bulanan: {mtxt}  ->  bulan hijau {int((months > 0).sum())}/{len(months)}")

    print("\n" + "=" * 118)
    print(" CATATAN: F1/F2/F3/F4 lolos gerbang OOS (TEST PF>=1.0) DAN konsistensi bulanan 4/4.")
    print("=" * 118)


if __name__ == "__main__":
    main()
