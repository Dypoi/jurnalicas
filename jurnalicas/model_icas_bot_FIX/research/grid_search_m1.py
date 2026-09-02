"""
================================================================================
GRID SEARCH KALIBRASI PARAMETER — di atas SEQUENCING M1 DEFINITIF (feed broker)
================================================================================
Disiplin anti-overfitting (WAJIB dibaca sebelum percaya hasilnya):
  1. Optimasi HANYA pada window TRAIN.
  2. Top-kandidat dievaluasi ulang pada window TEST (out-of-sample, belum pernah
     dilihat saat optimasi).
  3. Hanya kandidat yang TETAP PF >= 1.0 di TEST yang layak dipertimbangkan.
  4. Sample pendek (3,4 bln, satu rezim pasar) => hasil = HIPOTESIS awal, wajib
     forward-test demo ulang setelah ganti parameter.

Ruang grid:
  STOP_LOSS_PIPS        : 20/30/40/50/60/80/100 ($2-$10)
  Struktur TP (r x SL)  : A(0.75,1.5,2.5) B(1.0,2.0,3.0) C(1.25,2.5,3.75) D(1.5,3.0,5.0)
  EARLY_BE_TRIGGER_PIPS : 10/15/20/30/40/9999(nonaktif)
Cetak: top-15 TRAIN, lalu evaluasi TEST untuk kandidat terbaik.
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import itertools
import types
import dataclasses
import numpy as np
import pandas as pd
from config import config
from src.indicators.sessions import calculate_session_killzones
from src.backtest.granular_sequencer import run_granular, precompute_signals

TRAIN_START, TRAIN_END = "2026-05-14", "2026-07-15"
TEST_START, TEST_END = "2026-07-15", "2026-08-25 14:30"

SL_GRID = [20, 30, 40, 50, 60, 80, 100]
TP_STRUCTS = {
    "A(0.75/1.5/2.5)": (0.75, 1.5, 2.5),
    "B(1.0/2.0/3.0)": (1.0, 2.0, 3.0),
    "C(1.25/2.5/3.75)": (1.25, 2.5, 3.75),
    "D(1.5/3.0/5.0)": (1.5, 3.0, 5.0),
}
BE_GRID = [10, 15, 20, 30, 40, 9999]
MIN_TRADES = 100
TOP_K = 12


def make_cfg(**ov):
    base = dataclasses.asdict(config)
    base.update(ov)
    base.setdefault("RISK_USD_OVERRIDE", 500.0)   # fixed $500 riset (setara fixed base)
    return types.SimpleNamespace(**base)


def row(label, st, extra=""):
    return (f"{label:34s} | {st['trades']:4d} tr | {st['wins']:3d}W/{st['be']:3d}BE/{st['losses']:3d}L | "
            f"NLR {st['nlr']:5.1f}% | PF {st['pf']:5.2f} | Net ${st['net']:+9,.0f} | DD {st['dd_pct']:6.1f}% {extra}")


def main():
    print("=" * 100)
    print(" 🧪 GRID SEARCH PARAMETER di atas SEQUENCING M1 (feed broker, 1 feed konsisten)")
    print("=" * 100)

    df = pd.read_csv('data/historical/xauusd_m5_from_m1.csv')
    df['time'] = pd.to_datetime(df['time'])
    df = calculate_session_killzones(df)
    fine = pd.read_csv('data/historical/xauusd_m1_broker.csv')
    fine['time'] = pd.to_datetime(fine['time'])
    fine = fine.sort_values('time').reset_index(drop=True)

    cfg_sig = make_cfg()
    buy_sig, sell_sig = precompute_signals(df, cfg_sig)

    print("\n— BASELINE (parameter Anda saat ini: SL 20p, TP 20/40/60, BE 10p) —")
    st_base_tr = run_granular(df, fine, config, TRAIN_START, TRAIN_END, buy_sig, sell_sig)
    st_base_te = run_granular(df, fine, config, TEST_START, TEST_END, buy_sig, sell_sig)
    print(row("  baseline TRAIN", st_base_tr))
    print(row("  baseline TEST ", st_base_te))

    results = []
    total = len(SL_GRID) * len(TP_STRUCTS) * len(BE_GRID)
    n = 0
    print(f"\n— OPTIMASI TRAIN ({TRAIN_START[:10]} .. {TRAIN_END[:10]}) — {total} kombinasi ...")
    for sl_pips, (sname, (r1, r2, r3)), be_pips in itertools.product(SL_GRID, TP_STRUCTS.items(), BE_GRID):
        cfg = make_cfg(STOP_LOSS_PIPS=float(sl_pips),
                       TP1_PIPS=sl_pips * r1, TP2_PIPS=sl_pips * r2, TP3_PIPS=sl_pips * r3,
                       EARLY_BE_TRIGGER_PIPS=float(be_pips))
        st = run_granular(df, fine, cfg, TRAIN_START, TRAIN_END, buy_sig, sell_sig)
        n += 1
        if st['trades'] >= MIN_TRADES:
            results.append({
                'label': f"SL{sl_pips} {sname} BE{be_pips}",
                'sl': sl_pips, 'struct': sname, 'be': be_pips,
                'tp': (round(sl_pips * r1, 1), round(sl_pips * r2, 1), round(sl_pips * r3, 1)),
                'train': st, 'cfg': cfg})
        if n % 28 == 0:
            print(f"    ... {n}/{total}")

    results.sort(key=lambda r: (r['train']['pf'], r['train']['net']), reverse=True)
    print(f"\nTOP 15 TRAIN (dari {len(results)} kandidat valid, min {MIN_TRADES} trade):")
    for r in results[:15]:
        print(row(f"  {r['label']}", r['train'], f"| TP {r['tp']}"))

    print(f"\n— KONFIRMASI OUT-OF-SAMPLE TEST ({TEST_START[:10]} .. {TEST_END[:10]}) untuk TOP {TOP_K} —")
    final = []
    for r in results[:TOP_K]:
        st_te = run_granular(df, fine, r['cfg'], TEST_START, TEST_END, buy_sig, sell_sig)
        st_full = run_granular(df, fine, r['cfg'], "2026-05-14", "2026-08-25 14:30", buy_sig, sell_sig)
        r['test'] = st_te
        r['full'] = st_full
        ok = "✅" if st_te['pf'] >= 1.0 else "❌"
        final.append(r)
        print(row(f"  [{ok}] {r['label']}", st_te, f"| full-window PF {st_full['pf']:.2f}"))

    survivors = [r for r in final if r['test']['pf'] >= 1.0]
    survivors.sort(key=lambda r: r['test']['pf'], reverse=True)
    print("\n" + "=" * 100)
    if survivors:
        print(f" 🏆 KANDIDAT LOLOS OOS (TEST PF >= 1.0): {len(survivors)}")
        for r in survivors:
            print(f"   ★ {r['label']}  TP {r['tp']}")
            print(row("       TRAIN", r['train']))
            print(row("       TEST ", r['test']))
            print(row("       FULL ", r['full']))
        best = survivors[0]
        print("\nRekomendasi config (tulis ke config.py):")
        print(f"   STOP_LOSS_PIPS={best['sl']:.0f} | TP1/2/3={best['tp']} | EARLY_BE_TRIGGER_PIPS={best['be']:.0f}")
    else:
        print(" ⛔ TIDAK ADA kandidat yang lolos out-of-sample (TEST PF >= 1.0).")
        print("    Artinya: edge pada entry ini tidak cukup membayar biaya di feed Anda pada rezim ini")
        print("    untuk kombinasi SL/TP/BE manapun yang diuji. Jangan dipaksakan ke live;")
        print("    opsi lanjutan: ubah ENTRY (filter sesi/trend), timeframe eksekusi, atau biaya (akun Zero).")
    print("=" * 100)

    # simpan hasil mentah
    os.makedirs('reports', exist_ok=True)
    rows = []
    for r in final:
        rows.append({'config': r['label'], 'tp': str(r['tp']),
                     'train_pf': round(r['train']['pf'], 3), 'train_nlr': round(r['train']['nlr'], 2),
                     'test_pf': round(r['test']['pf'], 3), 'test_nlr': round(r['test']['nlr'], 2),
                     'full_pf': round(r['full']['pf'], 3), 'full_net': round(r['full']['net'], 2)})
    pd.DataFrame(rows).to_csv('reports/grid_search_topk.csv', index=False)
    print("[*] Ringkasan top-k tersimpan -> reports/grid_search_topk.csv")


if __name__ == '__main__':
    main()
