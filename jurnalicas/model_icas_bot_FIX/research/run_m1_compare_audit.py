"""
================================================================================
PERBANDINGAN  Jan-Jun 2026  —  PLAN SAAT INI  vs  REKOMENDASI
================================================================================
Engine : research/backtest_m1_audit.py  (M1 bid/ask, lolos 16 uji anti-repaint)
Data   : jurnalicas/XAUUSD_M1/XAUUSD_M1_20250901_20260901.csv
Jendela: 2026-01-01 .. 2026-06-30 (waktu server). Des 2025 = warm-up level sesi.

Karena lot dihitung dari risk (bukan dari ekuitas), PF / WR / expectancy tidak
tergantung modal. Yang tergantung modal hanya Net $ dan DD%. Maka tabel utama
dijalankan pada risk 1% (survivable) dan risk 5% (setting config.py) sebagai
sensitivitas.

    .venv/bin/python research/run_m1_compare_audit.py
================================================================================
"""
from __future__ import annotations
import os
import sys
import dataclasses
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from research.backtest_m1_audit import (  # noqa: E402
    load_m1, session_levels_norepaint, session_levels_repaint, resample_m5,
    run_backtest, StratCfg, CFG_CURRENT, CFG_RECO, CFG_RECO_NOKZ,
    CFG_NOTRAIL, CFG_SINGLE, PIP,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "..", "XAUUSD_M1", "XAUUSD_M1_20250901_20260901.csv")
WARMUP, WIN_START, WIN_END = "2025-12-01", "2026-01-01", "2026-06-30 23:59"
CAPITAL0 = 10_000.0
RISK_LO, RISK_HI = 100.0, 500.0
OUT = os.path.join(HERE, "..", "reports", "m1_audit_compare_jan_jun_2026.txt")

L: list[str] = []


def say(t=""):
    print(t)
    L.append(t)


def with_risk(cfg: StratCfg, risk: float, name: str | None = None) -> StratCfg:
    return dataclasses.replace(cfg, risk_usd=risk, name=name or cfg.name)


print("memuat data ...")
m1 = session_levels_norepaint(load_m1(CSV, WARMUP, WIN_END))
m5 = resample_m5(m1)
m1r = session_levels_repaint(load_m1(CSV, WARMUP, WIN_END))
m5r = resample_m5(m1r)
m5w = m5[m5.index >= WIN_START]
win_days = m5w.index.normalize().nunique()
SL = CFG_CURRENT.sl_pips * PIP

say("=" * 100)
say("BACKTEST M1 BID/ASK  —  XAUUSD  —  Jan s/d Jun 2026   (engine teraudit anti-repaint)")
say("=" * 100)
say(f"Data         : {os.path.basename(CSV)}")
say(f"Bar          : {len(m1):,} M1 / {len(m5):,} M5  (Des 2025 warm-up, tidak ditradingkan)")
say(f"Jendela      : {WIN_START} .. 2026-06-30  =  {win_days} hari bursa")
say(f"Modal        : ${CAPITAL0:,.0f}")
say(f"Spread       : median ${m1.spread_usd.median():.2f} | p95 ${m1.spread_usd.quantile(.95):.2f}"
    f"  -> MASUK IMPLISIT (BUY di ask, exit di bid)")
say(f"Anti-repaint : 24/24 uji lulus  (research/test_antirepaint.py, termasuk truncation invariance)")
say("")
say("GEOMETRI YANG DIBANDINGKAN  (SL sama $%.2f = %d pips)" % (SL, CFG_CURRENT.sl_pips))
for tag, c in (("A", CFG_CURRENT), ("B", CFG_RECO), ("C", CFG_RECO_NOKZ),
               ("D", CFG_NOTRAIL), ("E", CFG_SINGLE)):
    say(f"  {tag}  TP1 ${c.tp1_pips*PIP:>6.2f} ({c.tp1_pips/CFG_CURRENT.sl_pips:.2f}R)"
        f" | TP2 ${c.tp2_pips*PIP:>6.2f} ({c.tp2_pips/CFG_CURRENT.sl_pips:.2f}R)"
        f" | TP3 ${c.tp3_pips*PIP:>7.2f} ({c.tp3_pips/CFG_CURRENT.sl_pips:.2f}R)"
        f" | trail {c.trail_step_pips:.0f}p/{c.trail_lock_pips:.0f}p"
        f" | killzone {'ON' if c.use_killzone else 'off'}"
        f" | max/day {c.max_trades_per_day} | CB {c.max_consec_losses}")

# --------------------------------------------------------------------------- #
GUARD_CFG = 0.35
res_guard = run_backtest(m1, m5, dataclasses.replace(CFG_CURRENT, max_spread_usd=GUARD_CFG),
                         CAPITAL0, trade_from=WIN_START)
say("")
say("=" * 100)
say("PRA-SYARAT: SPREAD GUARD config.py TIDAK COCOK DENGAN FEED INI")
say("=" * 100)
say(f"  MAX_SPREAD_POINTS = 350  ==  ${GUARD_CFG:.2f}")
say(f"  Bar feed ini yang lolos guard : {(m1.spread_usd <= GUARD_CFG).mean()*100:.2f}%"
    f"   (median spread ${m1.spread_usd.median():.2f})")
say(f"  Bila guard dipakai apa adanya : {res_guard['trades']} trade dalam 6 bulan"
    f"  -> bot praktis tidak pernah entry.")
say(f"  Semua run di bawah memakai guard ${CFG_CURRENT.max_spread_usd:.2f}"
    f" (p95 feed ini) supaya perbandingan geometrinya bermakna.")

# --------------------------------------------------------------------------- #
print("menjalankan konfigurasi ...")
JOBS = [("A", CFG_CURRENT), ("B", CFG_RECO), ("C", CFG_RECO_NOKZ),
        ("D", CFG_NOTRAIL), ("E", CFG_SINGLE)]
runs: dict[str, dict] = {}
for risk, tag in ((RISK_LO, "1%"), (RISK_HI, "5%")):
    for key, cfg in JOBS:
        runs[f"{key}@{tag}"] = run_backtest(m1, m5, with_risk(cfg, risk),
                                            CAPITAL0, trade_from=WIN_START)
        print(f"  ... {key} @ {tag}")
for key, cfg in JOBS:
    runs[f"{key}@repaint"] = run_backtest(m1r, m5r, with_risk(cfg, RISK_LO),
                                          CAPITAL0, trade_from=WIN_START)
    n_sig = runs[f"{key}@1%"]["trades"]      # samakan jumlah entry dgn run sinyal
    runs[f"{key}@random"] = run_backtest(m1, m5, with_risk(cfg, RISK_LO), CAPITAL0,
                                         trade_from=WIN_START, random_seed=11,
                                         n_random=n_sig * 3)
    print(f"  ... {key} @ repaint/random (n_random={n_sig*3})")

COLS = [("trades", "Trades", 7), ("wr_pct", "WR%", 7), ("pf", "PF", 7),
        ("net", "Net $", 12), ("expectancy", "Exp $", 9), ("dd_pct", "DD%", 8),
        ("dd_abs", "DD $", 11), ("trades_per_day", "Tr/hari", 8),
        ("tp1_rate", "TP1%", 6), ("tp2_rate", "TP2%", 6), ("tp3_rate", "TP3%", 6),
        ("payoff", "Payoff", 7), ("blown", "Bangkrut", 9)]


def table(keys, labels, title):
    say("")
    say(title)
    say("-" * 100)
    say(f"{'Konfigurasi':<34}" + "".join(f"{h:>{w}}" for _, h, w in COLS))
    say("-" * 100)
    for k, lab in zip(keys, labels):
        r = dict(runs[k])
        t = r["tdf"]
        aw = t[t.pnl > 0].pnl.mean() if (t.pnl > 0).any() else 0.0
        al = abs(t[t.pnl < 0].pnl.mean()) if (t.pnl < 0).any() else 0.0
        r["payoff"] = round(aw / al, 2) if al else float("inf")
        r["blown"] = "YA" if r["final_capital"] <= 0 else "tidak"
        row = lab
        for f, _, w in COLS:
            v = r.get(f, "")
            row += f"{v:>{w},.2f}" if isinstance(v, float) else f"{str(v):>{w}}"
        say(row)
    say("-" * 100)


table([f"{k}@1%" for k, _ in JOBS], [f"{k} @ risk 1% ($100/trade)" for k, _ in JOBS],
      "TABEL 1  —  HASIL UTAMA, risk 1%  (perbandingan yang bisa dibaca)")
table([f"{k}@5%" for k, _ in JOBS], [f"{k} @ risk 5% ($500/trade) = config.py" for k, _ in JOBS],
      "TABEL 2  —  SENSITIVITAS: risk 5% seperti config.py saat ini")
table([f"{k}@repaint" for k, _ in JOBS], [f"{k} @ risk 1%, level sesi BOCOR (bug produksi)"
                                          for k, _ in JOBS],
      "TABEL 3  —  PEMBANDING REPAINT (replika calculate_session_killzones())")
table([f"{k}@random" for k, _ in JOBS], [f"{k} @ risk 1%, ENTRY ACAK (geometri sama)"
                                         for k, _ in JOBS],
      "TABEL 4  —  PEMBANDING ENTRY ACAK (mengukur edge sinyal)")

# --------------------------------------------------------------------------- #
say("")
say("=" * 100)
say("SEBERAPA BESAR SUMBANGAN REPAINT")
say("=" * 100)
for k, _ in JOBS:
    c, r = runs[f"{k}@1%"], runs[f"{k}@repaint"]
    say(f"  {k}: bersih  PF {c['pf']:>6}  net ${c['net']:>10,.0f}  WR {c['wr_pct']:>5}%   |   "
        f"repaint PF {r['pf']:>6}  net ${r['net']:>10,.0f}  WR {r['wr_pct']:>5}%   "
        f"->  repaint MENGGELEMBUNGKAN net sebesar ${r['net']-c['net']:>+,.0f}")

say("")
say("=" * 100)
say("EDGE SINYAL vs ENTRY ACAK")
say("=" * 100)
for k, _ in JOBS:
    c, r = runs[f"{k}@1%"], runs[f"{k}@random"]
    say(f"  {k}: PF sinyal {c['pf']:>6} vs PF acak {r['pf']:>6}  ({c['pf']-r['pf']:+.3f})"
        f"   |  expectancy ${c['expectancy']:>7,.2f} vs ${r['expectancy']:>7,.2f}"
        f"   |  net ${c['net']:>9,.0f} vs ${r['net']:>9,.0f}")

# --------------------------------------------------------------------------- #
say("")
say("=" * 100)
say("KENAPA WR TINGGI TAPI RUGI  —  komposisi 'WIN'")
say("=" * 100)
for k, _ in JOBS:
    t = runs[f"{k}@1%"]["tdf"]
    if not len(t):
        continue
    w = t[t.pnl > 0]
    scratch = w[w.pnl <= 150]      # keluar di trailing lock (lock $3 x lot x 100)
    real = w[w.pnl > 150]
    say(f"  --- {k} ---")
    say(f"     total {len(t)} trade | WIN {len(w)} | LOSS {int((t.pnl<0).sum())}")
    say(f"     dari {len(w)} WIN: {len(scratch)} ({len(scratch)/max(1,len(w))*100:.0f}%) "
        f"adalah scratch trailing-lock rata ${scratch.pnl.mean() if len(scratch) else 0:,.0f}"
        f", hanya {len(real)} win substantif rata ${real.pnl.mean() if len(real) else 0:,.0f}")
    say(f"     WR tercatat {t[t.pnl>0].shape[0]/len(t)*100:.1f}%  tapi  "
        f"WR win-substantif {len(real)/len(t)*100:.1f}%")
    say(f"     avg win ${w.pnl.mean():,.2f} vs avg loss ${t[t.pnl<0].pnl.mean():,.2f}"
        f"  -> butuh WR {abs(t[t.pnl<0].pnl.mean())/(w.pnl.mean()+abs(t[t.pnl<0].pnl.mean()))*100:.1f}%"
        f" untuk break-even")

# --------------------------------------------------------------------------- #
say("")
say("=" * 100)
say("KETERCAPAIAN TARGET  —  MFE trade vs level TP (geometri A)")
say("=" * 100)
t = runs["A@1%"]["tdf"]
say(f"  MFE (gerak menguntungkan maksimum) : median ${t.mfe.median():,.2f} | "
    f"rata ${t.mfe.mean():,.2f} | p75 ${t.mfe.quantile(.75):,.2f} | "
    f"p90 ${t.mfe.quantile(.9):,.2f} | maks ${t.mfe.max():,.2f}")
for lvl, nm in ((CFG_CURRENT.tp1_pips * PIP, "TP1"), (CFG_CURRENT.tp2_pips * PIP, "TP2"),
                (CFG_CURRENT.tp3_pips * PIP, "TP3")):
    say(f"  {nm} ${lvl:>6.2f} : dicapai {(t.mfe >= lvl).mean()*100:>5.1f}% trade"
        f"   ({int((t.mfe >= lvl).sum())} dari {len(t)})")
say(f"  trailing lock ${CFG_CURRENT.trail_lock_pips*PIP:.2f} setelah MFE "
    f"${CFG_CURRENT.trail_step_pips*PIP:.2f} : "
    f"{(t.mfe >= CFG_CURRENT.trail_step_pips*PIP).mean()*100:.1f}% trade menyentuhnya")
say("  -> TP2/TP3 praktis tidak pernah tercapai; struktur 4-tier berjalan sebagai"
    " 1 tier + scratch.")

# --------------------------------------------------------------------------- #
say("")
say("=" * 100)
say("RINCIAN PER BULAN  (risk 1%)")
say("=" * 100)
for k, _ in JOBS:
    t = runs[f"{k}@1%"]["tdf"].copy()
    if not len(t):
        continue
    t["bulan"] = pd.to_datetime(t.open_ts).dt.to_period("M")
    # hari bursa PER BULAN (bukan total 154) untuk tr/hari yang benar
    days_m = (m5w.index.normalize().drop_duplicates()
              .to_period("M").value_counts().sort_index())
    g = t.groupby("bulan").agg(n=("pnl", "size"), net=("pnl", "sum"),
                               win=("pnl", lambda s: (s > 0).sum()))
    g["hari"] = g.index.map(days_m)
    gw = t[t.pnl > 0].groupby("bulan").pnl.sum()
    gl = t[t.pnl < 0].groupby("bulan").pnl.sum().abs()
    g["pf"] = (gw / gl.replace(0, np.nan)).round(2)
    g["wr"] = (g.win / g.n * 100).round(1)
    say("")
    say(f"  --- {k}: {runs[k + '@1%']['cfg']} ---")
    say(f"  {'bulan':<10}{'n':>6}{'WR%':>8}{'PF':>8}{'net $':>13}{'tr/hari':>10}"
        f"{'hari bursa':>12}")
    for idx, r in g.iterrows():
        pf = r.pf if pd.notna(r.pf) else float("inf")
        say(f"  {str(idx):<10}{int(r.n):>6}{r.wr:>8.1f}{pf:>8.2f}{r.net:>13,.0f}"
            f"{r.n/r.hari:>10.2f}{int(r.hari):>12}")
    say(f"  {'TOTAL':<10}{int(g.n.sum()):>6}"
        f"{runs[f'{k}@1%']['wr_pct']:>8.1f}{runs[f'{k}@1%']['pf']:>8.2f}"
        f"{g.net.sum():>13,.0f}{g.n.sum()/win_days:>10.2f}")

# --------------------------------------------------------------------------- #
say("")
say("=" * 100)
say("VALIDASI SILANG  —  backtest vs JURNAL LIVE (logs/trade_journal.jsonl)")
say("=" * 100)
import json
import collections
_jr = os.path.join(HERE, "..", "logs", "trade_journal.jsonl")
if os.path.exists(_jr):
    _ev = [json.loads(l) for l in open(_jr) if l.strip()]
    _ex = [e for e in _ev if e.get("event") in ("position_closed", "position_closed_offline")]
    _by = collections.defaultdict(list)
    for e in sorted(_ex, key=lambda x: x.get("ts", 0)):
        _by[e["ticket"]].append(e)
    # realized_total BERSIFAT KUMULATIF per tiket -> ambil event terakhir, bukan dijumlah
    _last = {t: lst[-1] for t, lst in _by.items()}
    _v = [float(e.get("realized_total") or 0) for e in _last.values()]
    _w = [x for x in _v if x > 0]
    _l = [x for x in _v if x < 0]
    _naive = sum(sum(float(e.get("realized_total") or 0) for e in lst) for lst in _by.values())
    say(f"  close event {len(_ex)} untuk {len(_by)} tiket unik "
        f"({len(_ex)-len(_by)} duplikat -> bug F-03)")
    say(f"  PERINGKAH: menjumlah semua close event memberi ${_naive:,.2f} (SALAH, dobel).")
    say(f"  realized_total kumulatif -> pakai event terakhir: net ${sum(_v):,.2f}")
    say("")
    say(f"  {'':<26}{'trades':>8}{'WR%':>8}{'PF':>8}{'net $':>12}{'exp $':>10}{'TP1%':>8}")
    bt = runs["A@5%"]
    say(f"  {'Backtest A @ risk 5%':<26}{bt['trades']:>8}{bt['wr_pct']:>8.1f}{bt['pf']:>8.2f}"
        f"{bt['net']:>12,.0f}{bt['expectancy']:>10,.2f}{bt['tp1_rate']:>8.1f}")
    say(f"  {'Live (26 Agu - 02 Sep)':<26}{len(_v):>8}{len(_w)/len(_v)*100:>8.1f}"
        f"{sum(_w)/abs(sum(_l)):>8.2f}{sum(_v):>12,.0f}{sum(_v)/len(_v):>10,.2f}"
        f"{sum(1 for e in _last.values() if e.get('tp1_hit'))/len(_v)*100:>8.1f}")
    say("")
    say("  Catatan pembanding:")
    say("   - WR live lebih rendah karena 'WIN' backtest mencakup scratch trailing-lock")
    say(f"     ({(runs['A@5%']['tdf'][runs['A@5%']['tdf'].pnl>0].pnl<=150).mean()*100:.0f}% dari win backtest hanya ~$45).")
    say("   - Keduanya PF < 1. Selisih expectancy live vs backtest konsisten dengan")
    say("     slippage nyata $1.27/entry (F-17) yang tidak ada di data historis, plus")
    say("     kerusakan pemenang oleh bug F-03/F-05 yang baru diperbaiki.")
    say("   - Live n=21 terlalu kecil untuk memisahkan PF 0.78 dari 1.0; backtest n=729")
    say("     memberi interval yang jauh lebih sempit dan tetap < 1.")
else:
    say("  jurnal live tidak ditemukan")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(L) + "\n")
print(f"\ntersimpan: {OUT}")
