"""
================================================================================
GRANULAR SEQUENCING VALIDATOR — jawaban definitif "PF riil" dgn data lebih halus
================================================================================
[AUDIT FOLLOW-UP R-01 lanjutan] Menghilangkan bias urutan intrabar SEPENUHNYA
dengan mengeksekusi manajemen posisi pada data yang LEBIH HALUS dari M5
(mis. M1 ekspor dari terminal MT5 / broker Anda sendiri).

Versi CLI dari src/backtest/granular_sequencer.py (semantik 100% sama).

Cara memakai (export M1 dari MT5 Anda):
  MT5 -> View -> Symbols -> XAUUSDm -> tab Bars -> pilih M1 -> Request/Export,
  simpan CSV dengan header: time,open,high,low,close[,tick_volume,spread,real_volume]
  Lalu:
      python research/validate_granular.py --fine data/historical/xauusd_m1.csv

Uji plumbing: --fine pointing ke file M5 yang SAMA mereproduksi mode konservatif
engine v2 (toleransi kecil pada re-entry dalam bar yang sama).
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import numpy as np
import pandas as pd
from config import config
from src.indicators.sessions import calculate_session_killzones
from src.backtest.granular_sequencer import run_granular


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fine', required=True, help='CSV timeframe halus (M1/tick-OHLC)')
    ap.add_argument('--m5', default='data/historical/xauusd_m5.csv')
    ap.add_argument('--start', default='2026-01-01')
    ap.add_argument('--end', default='2026-06-30 23:59:59')
    args = ap.parse_args()

    print("=" * 86)
    print(f" 🔬 GRANULAR SEQUENCING VALIDATOR | {args.start[:10]} .. {args.end[:10]}")
    print("=" * 86)

    df = pd.read_csv(args.m5)
    df['time'] = pd.to_datetime(df['time'])
    df = calculate_session_killzones(df)
    fine = pd.read_csv(args.fine)
    fine['time'] = pd.to_datetime(fine['time'])
    fine = fine.sort_values('time').reset_index(drop=True)

    tf_fine = fine['time'].diff().median()
    tf_m5 = df['time'].diff().median()
    print(f"[*] TF sinyal: {tf_m5} | TF eksekusi: {tf_fine}")
    if tf_fine >= tf_m5:
        print("⚠️  [PERINGATAN] TF eksekusi tidak lebih halus dari TF sinyal — residual ambiguity MAKSIMAL.")
    else:
        resolusi = tf_m5 / max(tf_fine, pd.Timedelta(microseconds=1))
        print(f"[*] Resolusi sequencing ditingkatkan ~{resolusi:.0f}x vs M5 (residual ambiguity ~1/{resolusi:.0f}).")

    st = run_granular(df, fine, config, args.start, args.end, return_trades=True)
    print(f"[*] Price point terdeteksi: {st['price_point']} $/point")

    tdf = st['tdf']
    if len(tdf) == 0:
        print("Tidak ada trade pada window ini.")
        return
    print("\n" + "=" * 86)
    print(" 📊 HASIL GRANULAR (sequencing waktu nyata pada TF eksekusi)")
    print("=" * 86)
    print(f"• Total Trades   : {st['trades']} ({st['wins']}W / {st['be']}BE / {st['losses']}L)")
    print(f"• Non-Loss Rate  : {st['nlr']:.2f}%")
    print(f"• Profit Factor  : {st['pf']:.2f}")
    print(f"• Net Profit     : ${st['net']:+,.2f}")
    print(f"• Max Drawdown   : {st['dd_pct']:.2f}%")
    months = sorted(tdf['month'].unique())
    green = sum(1 for m in months if tdf[tdf.month == m].pnl.sum() > 0)
    print(f"• Bulan hijau    : {green}/{len(months)}")
    print("-" * 86)
    print("Bandingkan: PF optimis (legacy) vs pesimis (konservatif) pada window yang sama.")
    print("Semakin halus TF eksekusi, hasil semakin definitif (tick = tanpa residual).")


if __name__ == '__main__':
    main()
