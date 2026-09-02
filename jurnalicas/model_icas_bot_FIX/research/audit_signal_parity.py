"""
================================================================================
AUDIT PARITAS SINYAL: BACKTEST (lookahead) vs KAUSAL vs EMULASI LIVE (window 150)
================================================================================
[AUDIT FORENSIK 2 Sep 2026 — temuan LA-01]

`calculate_session_killzones()` menghitung asian_high/low & london_high/low
dengan `groupby(date).agg(max/min)` lalu merge kembali ke SEMUA bar tanggal itu.
Akibatnya bar jam 01:00 server sudah "tahu" range Asia 03:00-07:00 dan range
London 08:00-12:00 yang belum terjadi -> sinyal backtest mengandung LOOKAHEAD
pada ~50% bar harian (00:00-12:00 server).

Di sisi live, daemon hanya memuat 150 bar M5 (12,5 jam): sebelum jam 03:00
server tidak ada bar Asia hari ini DAN bar Asia kemarin sudah di luar window
-> `fillna(df['high'])` -> target = high/low bar itu sendiri (degenerate) ->
filter "Judas sweep" praktis mati dan sinyal berubah menjadi breakout polos.

Skrip ini menjalankan sequencer M1 yang SAMA (src/backtest/granular_sequencer)
dengan tiga definisi sinyal, sehingga selisih hasil murni berasal dari definisi
level sesi:
  (A) BACKTEST  : level sesi seperti engine/grid-search lama (lookahead)
  (B) KAUSAL    : level sesi hanya dari bar yang sudah selesai (expanding),
                  sebelum sesi hari ini dimulai pakai range final hari sebelumnya
  (C) LIVE-EMU  : persis perhitungan daemon — window 150 bar berjalan

Cara pakai:
  python3 research/audit_signal_parity.py
  python3 research/audit_signal_parity.py --m5 data/historical/xauusd_m5_from_m1.csv \
      --fine data/historical/xauusd_m1_broker.csv --start 2026-05-14 --end "2026-08-25 14:30"
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import dataclasses
import types
import numpy as np
import pandas as pd
from config import config
from src.indicators.sessions import calculate_session_killzones, calculate_session_levels_causal
from src.backtest.granular_sequencer import run_granular, precompute_signals

OLD = dict(STOP_LOSS_PIPS=20.0, TP1_PIPS=20.0, TP2_PIPS=40.0, TP3_PIPS=60.0, EARLY_BE_TRIGGER_PIPS=10.0)
NEW = dict(STOP_LOSS_PIPS=150.0, TP1_PIPS=187.5, TP2_PIPS=375.0, TP3_PIPS=562.5, EARLY_BE_TRIGGER_PIPS=9999.0)


def mk(**ov):
    b = dataclasses.asdict(config)
    b.update(ov)
    b.setdefault("RISK_USD_OVERRIDE", 500.0)
    return types.SimpleNamespace(**b)


def live_emulated_signals(df_raw: pd.DataFrame, cfg, window: int = 150):
    """Emulasi persis jalur daemon: tiap bar i dievaluasi memakai
    calculate_session_killzones() pada window 150 bar yang berakhir di bar i
    (bar i = 'latest completed candle' di daemon)."""
    n = len(df_raw)
    buy = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    H = df_raw['high'].values; L = df_raw['low'].values
    C = df_raw['close'].values; O = df_raw['open'].values
    S = df_raw['spread'].values
    for i in range(window - 1, n):
        win = df_raw.iloc[i - window + 1:i + 1]
        sess = calculate_session_killzones(win)
        r = sess.iloc[-1]
        bsl = max(float(r['asian_high']), float(r['london_high']))
        ssl = min(float(r['asian_low']), float(r['london_low']))
        if i < 6:
            continue
        swing_h = H[i - 6:i - 1].max(); swing_l = L[i - 6:i - 1].min()
        bull_fvg = L[i] > H[i - 2] + 0.30
        bear_fvg = H[i] < L[i - 2] - 0.30
        ssl_swept = (L[i - 1] <= ssl) or (L[i - 2] <= ssl)
        bsl_swept = (H[i - 1] >= bsl) or (H[i - 2] >= bsl)
        if S[i] > cfg.MAX_SPREAD_POINTS:
            continue
        buy[i] = ssl_swept and (C[i] > O[i]) and (C[i] > swing_h or bull_fvg)
        sell[i] = bsl_swept and (C[i] < O[i]) and (C[i] < swing_l or bear_fvg)
    return buy, sell


def line(label, st):
    return (f"{label:44s} | {st['trades']:4d} tr | {st['wins']:3d}W/{st['be']:3d}BE/{st['losses']:3d}L | "
            f"NLR {st['nlr']:5.1f}% | PF {st['pf']:5.2f} | Net ${st['net']:+10,.0f} | DD {st['dd_pct']:5.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--m5', default='data/historical/xauusd_m5_from_m1.csv')
    ap.add_argument('--fine', default='data/historical/xauusd_m1_broker.csv')
    ap.add_argument('--start', default='2026-05-14')
    ap.add_argument('--end', default='2026-08-25 14:30')
    ap.add_argument('--skip-live-emu', action='store_true', help='lewati emulasi live (lebih lambat)')
    args = ap.parse_args()

    df = pd.read_csv(args.m5); df['time'] = pd.to_datetime(df['time'])
    fine = pd.read_csv(args.fine); fine['time'] = pd.to_datetime(fine['time'])
    fine = fine.sort_values('time').reset_index(drop=True)

    df_look = calculate_session_killzones(df)            # (A) lookahead (engine lama)
    df_caus = calculate_session_levels_causal(df)        # (B) kausal

    print("=" * 118)
    print(" 🔬 AUDIT PARITAS SINYAL — sequencer M1 identik, hanya definisi level sesi yang berbeda")
    print("=" * 118)
    print(f"Data: {args.m5} ({len(df)} bar M5) | fine: {args.fine} | window {args.start} .. {args.end}")

    # Ukur langsung berapa banyak bar yang level sesinya berbeda antara lookahead vs kausal
    diff_asia = (~np.isclose(df_look['asian_high'].values, df_caus['asian_high'].values)) | \
                (~np.isclose(df_look['asian_low'].values, df_caus['asian_low'].values))
    diff_lon = (~np.isclose(df_look['london_high'].values, df_caus['london_high'].values)) | \
               (~np.isclose(df_look['london_low'].values, df_caus['london_low'].values))
    print(f"Bar dengan level ASIA berbeda (lookahead vs kausal)  : {diff_asia.mean()*100:5.1f}%")
    print(f"Bar dengan level LONDON berbeda (lookahead vs kausal): {diff_lon.mean()*100:5.1f}%")

    results = {}
    for cfg_name, ov in (("CONFIG LAMA SL20/BE10", OLD), ("CONFIG AKTIF SWING-150 (SL150/BE OFF)", NEW)):
        cfg = mk(**ov)
        print("\n" + "-" * 118)
        print(f" {cfg_name}")
        print("-" * 118)
        bA, sA = precompute_signals(df_look, cfg)
        stA = run_granular(df_look, fine, cfg, args.start, args.end, buy_sig=bA, sell_sig=sA, return_trades=True)
        print(line("(A) BACKTEST/GRID-SEARCH (lookahead sesi)", stA))
        bB, sB = precompute_signals(df_caus, cfg)
        stB = run_granular(df_caus, fine, cfg, args.start, args.end, buy_sig=bB, sell_sig=sB, return_trades=True)
        print(line("(B) KAUSAL (tanpa lookahead)", stB))
        results[(cfg_name, 'A')] = stA; results[(cfg_name, 'B')] = stB
        if not args.skip_live_emu:
            bC, sC = live_emulated_signals(df, cfg)
            stC = run_granular(df_look, fine, cfg, args.start, args.end, buy_sig=bC, sell_sig=sC, return_trades=True)
            print(line("(C) EMULASI LIVE daemon (window 150 bar)", stC))
            results[(cfg_name, 'C')] = stC
            # Overlap sinyal
            t64 = df['time'].values.astype('datetime64[ns]')
            a = int(np.searchsorted(t64, np.datetime64(args.start))); b = int(np.searchsorted(t64, np.datetime64(args.end)))
            sigA = (bA | sA)[a:b]; sigB = (bB | sB)[a:b]; sigC = (bC | sC)[a:b]
            print(f"    Kandidat sinyal (bar): backtest={sigA.sum()} | kausal={sigB.sum()} | live-emu={sigC.sum()} "
                  f"| irisan backtest∩live={int((sigA & sigC).sum())} | Jaccard(backtest,live)={(sigA & sigC).sum()/max(1,(sigA | sigC).sum()):.2f}")
            # Distribusi jam server sinyal live-emu (degenerate window 00-03)
            hrs = df['time'].dt.hour.values[a:b]
            deg = ((hrs < 3) & sigC).sum()
            print(f"    Sinyal live-emu pada jam 00:00-02:59 server (level degenerate): {deg} dari {sigC.sum()} ({deg/max(1,sigC.sum())*100:.0f}%)")
        for k, st in (("A", stA), ("B", stB)):
            tdf = st['tdf']
            if len(tdf):
                months = sorted(tdf['month'].unique())
                green = sum(1 for m in months if tdf[tdf.month == m].pnl.sum() > 0)
                print(f"    ({k}) bulan hijau {green}/{len(months)} | " +
                      " | ".join(f"{m}: ${tdf[tdf.month == m].pnl.sum():+,.0f}" for m in months))

    print("\n" + "=" * 118)
    print(" KESIMPULAN OTOMATIS")
    print("=" * 118)
    a = results[("CONFIG AKTIF SWING-150 (SL150/BE OFF)", 'A')]; b = results[("CONFIG AKTIF SWING-150 (SL150/BE OFF)", 'B')]
    print(f"Config aktif: PF backtest(lookahead) {a['pf']:.2f} -> PF kausal {b['pf']:.2f} | "
          f"Net ${a['net']:+,.0f} -> ${b['net']:+,.0f}")
    if b['pf'] < 1.0 <= a['pf']:
        print("⛔ Edge yang dilaporkan grid-search TIDAK bertahan tanpa lookahead: kalibrasi 25 Agu dibangun di atas sinyal yang mengintip masa depan.")
    elif b['pf'] < a['pf'] * 0.75:
        print("⚠️ Sebagian besar edge backtest adalah artefak lookahead; sisa edge kausal jauh lebih kecil dari klaim.")
    else:
        print("✅ Edge relatif bertahan tanpa lookahead.")


if __name__ == '__main__':
    main()
