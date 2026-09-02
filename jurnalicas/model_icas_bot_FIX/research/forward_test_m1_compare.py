"""
================================================================================
SIMULASI "FORWARD TEST LIVE" — CONFIG LAMA vs CONFIG BARU di atas M1 CSV
================================================================================
Memperlakukan bar M1 ekspor MT5 seolah-olah tick live: trade masuk di open bar
M5 berikutnya (sama seperti daemon), keluar dengan sequencing M1 definitif
(SL/TP/BE/trailing diuji bar-per-bar sesuai waktu), spread riil per bar +
slippage $0.10 — identik dengan perilaku live, tanpa asumsi intrabar.

Window FORWARD = 2026-07-15 -> 2026-08-25 14:30 (bagian OUT-OF-SAMPLE yang
TIDAK dipakai untuk mengoptimasi parameter baru hanya untuk men-gate kelolosan).
Ditambah ringkasan window penuh (14 Mei -> 25 Agu) untuk konteks.

Usul live: modal awal $10,000, risiko tetap $500/trade (5% sesuai config live,
mengacu INITIAL_CAPITAL) — sama seperti kalkulasi sizing daemon.

Juga dijalankan: ENGINE M5 (run_backtest) pada window yang sama, config lama
vs baru, untuk menjawab "engine-nya rugi atau profit?".

Cara pakai:  python3 research/forward_test_m1_compare.py
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
from src.backtest.engine import IcasBacktestEngine

FWD_START, FWD_END = "2026-07-15", "2026-08-25 14:30"
FULL_START, FULL_END = "2026-05-14", "2026-08-25 14:30"

OLD = dict(STOP_LOSS_PIPS=20.0, TP1_PIPS=20.0, TP2_PIPS=40.0, TP3_PIPS=60.0,
           EARLY_BE_TRIGGER_PIPS=10.0)
NEW = dict(STOP_LOSS_PIPS=150.0, TP1_PIPS=187.5, TP2_PIPS=375.0, TP3_PIPS=562.5,
           EARLY_BE_TRIGGER_PIPS=9999.0)
ALT = dict(STOP_LOSS_PIPS=200.0, TP1_PIPS=200.0, TP2_PIPS=400.0, TP3_PIPS=600.0,
           EARLY_BE_TRIGGER_PIPS=60.0)

EQUITY0 = 10_000.0
RISK = 500.0


def mk(**ov):
    b = dataclasses.asdict(config)
    b.update(ov)
    b.setdefault("RISK_USD_OVERRIDE", RISK)
    return types.SimpleNamespace(**b)


def live_like_stats(st, label):
    """Statistik 'seolah live': equity compounding dari PnL riil, DD pada kurva,
    streak kalah, trades/hari, pembagian mingguan."""
    t = st["tdf"].copy()
    t["equity"] = EQUITY0 + t["pnl"].cumsum()
    run_max = t["equity"].cummax().clip(lower=EQUITY0)
    dd_series = (run_max - t["equity"]) / run_max
    dd_max = float(dd_series.max()) * 100
    trough_i = int(dd_series.idxmax()) if dd_max > 0 else 0

    # streak kalah terpanjang (pnl < 0)
    worst_streak = cur = 0
    for p in t["pnl"]:
        if p < 0:
            cur += 1
            worst_streak = max(worst_streak, cur)
        else:
            cur = 0

    days = t["time"].dt.normalize().nunique()
    span_days = max(1, (t["time"].max() - t["time"].min()).days + 1)
    weeks = t.groupby(t["time"].dt.to_period("W-SUN"))["pnl"].agg(["sum", "count"])

    w = t[t["pnl"] > 0]["pnl"]
    l = t[t["pnl"] < 0]["pnl"]
    print(f"\n>>> {label}")
    print(f"    Trades: {st['trades']} ({st['wins']}W/{st['be']}BE/{st['losses']}L) | "
          f"WinRate(res) {st['wins']/max(1,st['trades'])*100:.1f}% | PnL>0: {len(w)} ({len(w)/max(1,st['trades'])*100:.0f}%)")
    print(f"    PF {st['pf']:.2f} | Net ${st['net']:+,.0f} ({st['net']/EQUITY0*100:+.1f}% modal) | "
          f"Ekspektasi ${st['net']/max(1,st['trades']):+,.0f}/trade")
    print(f"    Equity akhir ${t['equity'].iloc[-1]:,.0f} | MaxDD(kurva berjalan) {dd_max:.1f}% "
          f"(terburuk di trade #{trough_i+1}) | Streak loss terpanjang {worst_streak}")
    print(f"    Aktivitas: {st['trades']} trade / {days} hari trading (~{st['trades']/max(1,days):.1f}/hari, "
          f"span {span_days} hari kalender)")
    print(f"    AvgWin ${w.mean() if len(w) else 0:+,.0f} | AvgLoss ${l.mean() if len(l) else 0:+,.0f}")
    wtxt = " | ".join(f"{str(wk)[5:]}: ${s:+,.0f}({c}t)" for wk, (s, c) in weeks.iterrows())
    print(f"    Mingguan: {wtxt}")
    return dict(label=label, trades=st["trades"], pf=st["pf"], net=st["net"], dd=dd_max,
                streak=worst_streak, wr=len(w)/max(1, st["trades"])*100)


def engine_run(csv, start, end, ov, legacy=False):
    """Jalankan engine M5 asli dengan override config sementara; stats dari tdf."""
    keys = list(ov) + ["CONSERVATIVE_INTRABAR", "INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK",
                       "SLIPPAGE_USD", "ENFORCE_SPREAD_GUARD_IN_BACKTEST"]
    saved = {k: getattr(config, k) for k in keys}
    for k, v in ov.items():
        setattr(config, k, v)
    if legacy:
        config.CONSERVATIVE_INTRABAR = False
        config.INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK = False
        config.SLIPPAGE_USD = 0.0
        config.ENFORCE_SPREAD_GUARD_IN_BACKTEST = False
    df = pd.read_csv(csv)
    engine = IcasBacktestEngine(config)
    final_cap, tdf = engine.run(df, start_date=start, end_date=end, compounding=False)
    for k, v in saved.items():
        setattr(config, k, v)
    return final_cap, tdf


def engine_stats(final_cap, tdf):
    total = len(tdf)
    if total == 0:
        return "-"
    gw = tdf.loc[tdf["pnl"] > 0, "pnl"].sum()
    gl = abs(tdf.loc[tdf["pnl"] < 0, "pnl"].sum())
    pf = gw / gl if gl > 0 else 0.0
    eq = pd.Series([config.INITIAL_CAPITAL] + tdf["balance"].tolist())
    dd = float((((eq.cummax() - eq) / eq.cummax()) * 100.0).max())
    net = final_cap - config.INITIAL_CAPITAL
    w, be, l = (tdf["res"] == "WIN").sum(), (tdf["res"] == "BE").sum(), (tdf["res"] == "LOSS").sum()
    nlr = (w + be) / total * 100.0
    return (f"{total} tr ({w}W/{be}BE/{l}L) | NLR {nlr:.1f}% | PF {pf:.2f} | "
            f"Net ${net:+,.0f} | DD {dd:.1f}%")


def main():
    df = pd.read_csv("data/historical/xauusd_m5_from_m1.csv")
    df["time"] = pd.to_datetime(df["time"])
    df = calculate_session_killzones(df)
    fine = pd.read_csv("data/historical/xauusd_m1_broker.csv")
    fine["time"] = pd.to_datetime(fine["time"])
    buy, sell = precompute_signals(df, mk())

    print("=" * 112)
    print(" SIMULASI FORWARD TEST LIVE (sequencing M1 definitif, biaya riil, equity $10k, risiko $500/trade)")
    print("=" * 112)

    rows = []
    for label, ov in [("CONFIG LAMA  (SL20 | TP20/40/60 | BE10)", OLD),
                      ("CONFIG BARU  (SL150 | TP187.5/375/562.5 | BE OFF)  <- terpasang", NEW),
                      ("Preset ALT   (SL200 | TP200/400/600 | BE60)", ALT)]:
        cfg = mk(**ov)
        st = run_granular(df, fine, cfg, FWD_START, FWD_END, buy, sell, return_trades=True)
        print(f"\n--- [FORWARD/OOS {FWD_START} -> {FWD_END}] ---")
        rows.append(live_like_stats(st, f"{label}"))

    print("\n" + "=" * 112)
    print(" KONTEKS WINDOW PENUH (14 Mei -> 25 Agu) — sequencing M1 yang sama")
    print("=" * 112)
    for label, ov in [("CONFIG LAMA", OLD), ("CONFIG BARU", NEW), ("Preset ALT", ALT)]:
        cfg = mk(**ov)
        st = run_granular(df, fine, cfg, FULL_START, FULL_END, buy, sell)
        months = run_granular(df, fine, cfg, FULL_START, FULL_END, buy, sell, return_trades=True)["tdf"]
        mg = months.groupby("month")["pnl"].sum()
        print(f"  {label:12s}: {st['trades']:4d} tr | PF {st['pf']:5.2f} | Net ${st['net']:+9,.0f} | "
              f"DD {st['dd_pct']:6.1f}% | bulan hijau {int((mg>0).sum())}/{len(mg)}")

    print("\n" + "=" * 112)
    print(" ENGINE M5 ASLI (run_backtest) pada window FORWARD yang sama — config LAMA vs BARU")
    print("=" * 112)
    for label, ov, legacy in [("ENGINE-KONSERVATIF config LAMA", OLD, False),
                              ("ENGINE-KONSERVATIF config BARU", NEW, False),
                              ("ENGINE-LEGACY      config LAMA", OLD, True),
                              ("ENGINE-LEGACY      config BARU", NEW, True)]:
        fc, tdf = engine_run("data/historical/xauusd_m5_from_m1.csv", FWD_START, FWD_END, ov, legacy)
        print(f"  {label:35s}: {engine_stats(fc, tdf)}")

    print("\n" + "=" * 112)
    print(" RINGKASAN FORWARD (OOS 6 minggu):")
    for r in rows:
        print(f"  {r['label']:60s} | {r['trades']:4d} tr | PF {r['pf']:4.2f} | Net ${r['net']:+8,.0f} | "
              f"MaxDD {r['dd']:4.1f}% | PnL>0 {r['wr']:4.0f}% | streak-loss {r['streak']}")
    print("=" * 112)


if __name__ == "__main__":
    main()
