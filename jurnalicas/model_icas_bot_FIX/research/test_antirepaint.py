"""
================================================================================
UJI ANTI-REPAINT untuk research/backtest_m1_audit.py
================================================================================
Tujuh uji. Yang paling menentukan adalah **T7 (truncation invariance)**: bila
engine benar-benar tidak melihat masa depan, memotong data di tanggal T harus
menghasilkan trade yang IDENTIK untuk semua trade yang dibuka sebelum T.
Itu bukti empiris, bukan janji di komentar.

Setiap uji "tidak ada X" dilengkapi KONTROL POSITIF supaya tidak lolos kosong.

Jalankan dari model_icas_bot_FIX:
    .venv/bin/python research/test_antirepaint.py
================================================================================
"""
from __future__ import annotations
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from research.backtest_m1_audit import (  # noqa: E402
    load_m1, session_levels_norepaint, resample_m5, signal_at, run_backtest,
    StratCfg, CFG_CURRENT, CFG_RECO, SERVER_TZ, PIP,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "..", "XAUUSD_M1", "XAUUSD_M1_20250901_20260901.csv")
START, END = "2025-12-01", "2026-06-30 23:59"
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f"   {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}   {detail}")


print("=" * 78)
print("MEMUAT DATA")
print("=" * 78)
m1 = session_levels_norepaint(load_m1(CSV, START, END))
m5 = resample_m5(m1)
print(f"  M1 : {len(m1):,} bar  {m1.index.min()} -> {m1.index.max()}")
print(f"  M5 : {len(m5):,} bar   (hari server: {m1.srv_date.nunique()})")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T1  KAUSALITAS LEVEL SESI  (ganggu masa depan -> masa lalu tak boleh berubah)")
print("=" * 78)
perturbed = m1.copy()
cut = len(perturbed) // 2
_hb, _lb = perturbed["high_bid"].to_numpy().copy(), perturbed["low_bid"].to_numpy().copy()
_hb[cut:] = 9999.0
_lb[cut:] = 1.0
perturbed["high_bid"], perturbed["low_bid"] = _hb, _lb
rep = session_levels_norepaint(perturbed)
before_ok = all(np.allclose(m1[c].iloc[:cut].to_numpy(), rep[c].iloc[:cut].to_numpy(),
                            equal_nan=True)
                for c in ("asian_high", "asian_low", "london_high", "london_low"))
check("gangguan pada bar paruh-2 TIDAK mengubah level sesi paruh-1", before_ok)
after_changed = not np.allclose(m1["asian_high"].iloc[cut + 500:].to_numpy(),
                                rep["asian_high"].iloc[cut + 500:].to_numpy(),
                                equal_nan=True)
check("kontrol positif: gangguan benar-benar masuk", after_changed)

asian_mask = (m1["srv_hour"] >= 3) & (m1["srv_hour"] < 7)
per_day = m1[asian_mask].groupby("srv_date")["high_bid"].max()
ds = list(per_day.index)
prev_of = {d: (per_day[ds[j - 1]] if j >= 1 else np.nan) for j, d in enumerate(ds)}
early = m1[(m1["srv_hour"] < 7) & m1["asian_high"].notna()]
same_day = per_day.reindex(early["srv_date"]).to_numpy()
leak = int(np.isclose(early["asian_high"].to_numpy(), same_day, equal_nan=True).sum())
check("bar sebelum 07:00 TIDAK memakai high Asia hari itu", leak == 0,
      f"(0 dari {len(early)} bar)")
match_prev = np.isclose(early["asian_high"].to_numpy(),
                        early["srv_date"].map(prev_of).to_numpy(), equal_nan=True)
check("bar sebelum 07:00 memakai range Asia hari sebelumnya", match_prev.all(),
      f"({int(match_prev.sum())}/{len(early)} cocok)")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T2  KAUSALITAS SINYAL  (ganggu M5 setelah idx -> signal_at(idx) tetap)")
print("=" * 78)
idxs = [i for i in range(200, len(m5) - 600, 37)][:150]
base = {i: signal_at(m5, i, CFG_CURRENT) for i in idxs}
m5p = m5.copy()
tail = idxs[-1] + 200
for col, val in (("high", 9999.0), ("low", 1.0), ("close", 5000.0),
                 ("asian_high", 9999.0), ("london_high", 9999.0)):
    v = m5p[col].to_numpy().copy()
    v[tail:] = val
    m5p[col] = v
new = {i: signal_at(m5p, i, CFG_CURRENT) for i in idxs}
diff = [i for i in idxs if base[i] != new[i]]
n_sig = sum(1 for v in base.values() if v)
check("signal_at(idx) tidak berubah saat masa depan diubah", not diff,
      f"({len(idxs)} bar diuji, {len(diff)} berubah)")
check("kontrol positif: ada sinyal di sampel", n_sig > 0, f"({n_sig} sinyal)")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T3  ENTRY TIDAK DI BAR SINYAL + MATEMATIKA EXIT")
print("=" * 78)
resA = run_backtest(m1, m5, CFG_CURRENT)
tdf = resA["tdf"]
m5set, m1set = set(m5.index), set(m1.index)
ok_t = all((ts - pd.Timedelta(minutes=5)) in m5set and ts in m1set
           for ts in pd.to_datetime(tdf.open_ts))
check("setiap entry = open bar M1 tepat 5 menit setelah bar sinyal tutup", ok_t,
      f"({len(tdf)} trade)")
# exit SL harus tepat di SL yang berlaku (awal ATAU hasil trailing lock)
pure = tdf[(tdf.reason == "SL") & (~tdf.tp1) & (~tdf.tp2) & (~tdf.tp3)].copy()
step_d = CFG_CURRENT.trail_step_pips * PIP
lock_d = CFG_CURRENT.trail_lock_pips * PIP
lock = np.where(pure.trail >= 1,
                (pure.trail - 1) * step_d + lock_d,
                -CFG_CURRENT.sl_pips * PIP)
exp = lock * pure.lots * 100.0
dev = float((pure.pnl - exp).abs().max())
check("exit SL tepat di level SL yang berlaku (awal atau trailing lock)",
      dev < 0.02, f"({len(pure)} trade SL-murni, deviasi maks ${dev:.4f}; "
      f"{int((pure.trail >= 1).sum())} di antaranya keluar di trailing lock)")
check("kontrol positif: ada trade SL di level awal", int((pure.trail == 0).sum()) > 0,
      f"({int((pure.trail == 0).sum())} trade rugi penuh ${CFG_CURRENT.sl_pips*PIP*pure.lots.iloc[0]*100:,.0f})")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T4  SPREAD BENAR-BENAR DIBAYAR  (bid/ask vs ask=bid)")
print("=" * 78)
zero = m1.copy()
for c in ("open_ask", "high_ask", "low_ask", "close_ask"):
    zero[c] = zero[c.replace("_ask", "_bid")]
zero["spread_usd"] = 0.0
resZ = run_backtest(zero, resample_m5(zero), CFG_CURRENT)
delta = resZ["net"] - resA["net"]
per_trade = delta / max(1, len(tdf))
check("versi tanpa spread lebih untung (spread benar-benar jadi biaya)", delta > 0,
      f"selisih ${delta:,.0f} | net {resA['net']:,.0f} -> {resZ['net']:,.0f} | "
      f"PF {resA['pf']} -> {resZ['pf']}")
print(f"    -> biaya spread ${per_trade:,.2f}/trade = "
      f"{per_trade/CFG_CURRENT.risk_usd*100:.2f}% dari risk ${CFG_CURRENT.risk_usd:,.0f}/trade")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T5  URUTAN INTRABAR PESIMIS  (SL dulu vs TP dulu)")
print("=" * 78)
resOpt = run_backtest(m1, m5, CFG_CURRENT, tp_first=True)
check("default (SL dulu) <= varian optimis (TP dulu) pada data nyata",
      resA["net"] <= resOpt["net"],
      f"net ${resA['net']:,.0f} vs ${resOpt['net']:,.0f}")
# kontrol positif: flag harus benar-benar berpengaruh bila SL/TP rapat
tight = StratCfg(name="tight", sl_pips=8, tp1_pips=8, tp2_pips=16, tp3_pips=24,
                 r1=1.0, r2=0.0, r3=0.0, trail_step_pips=9999, trail_lock_pips=0,
                 risk_usd=50.0)
rt_p = run_backtest(m1, m5, tight, capital0=10_000_000, tp_first=False)["net"]
rt_o = run_backtest(m1, m5, tight, capital0=10_000_000, tp_first=True)["net"]
check("kontrol positif: dengan SL/TP rapat, tp_first menghasilkan net berbeda",
      abs(rt_p - rt_o) > 1.0, f"pesimis ${rt_p:,.0f} vs optimis ${rt_o:,.0f}")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T6  REGRESI F-18: fungsi produksi calculate_session_killzones() kini KAUSAL")
print("=" * 78)
from src.indicators.sessions import calculate_session_killzones  # noqa: E402


def _srv_naive(frame):
    return frame.index.tz_localize("UTC").tz_convert(SERVER_TZ).tz_localize(None)


sample = m1.loc["2026-03-08 20:00":"2026-03-11 23:59"].copy()
sd = sample[["open_bid", "high_bid", "low_bid", "close_bid"]].reset_index(drop=True)
sd.columns = ["open", "high", "low", "close"]
sd["time"] = _srv_naive(sample)
pr = calculate_session_killzones(sd)
_d = pd.Timestamp("2026-03-10").date()
first = pr[pr.time.dt.date == _d].iloc[0]
day_asian = pr[(pr.time.dt.date == _d) & (pr.time.dt.hour >= 3)
               & (pr.time.dt.hour < 7)]["high"].max()
check("produksi: bar 00:00 TIDAK lagi memakai high Asia sepanjang hari (F-18 fixed)",
      abs(first["asian_high"] - day_asian) > 1e-9,
      f"asian_high@00:00 = {first['asian_high']:.3f} != max Asia hari itu {day_asian:.3f}")
prev_date = sorted(d for d in set(m1.srv_date) if d < _d)[-1]
prev_max = m1[(m1.srv_date == prev_date) & (m1.srv_hour >= 3)
              & (m1.srv_hour < 7)]["high_bid"].max()
check("produksi: bar 00:00 memakai range hari sebelumnya",
      abs(first["asian_high"] - prev_max) < 1e-9,
      f"{first['asian_high']:.3f} == hari sebelumnya {prev_max:.3f}")
# kesetaraan penuh dgn engine teraudit pada irisan yang sama
ref = m1[["asian_high", "london_high"]].copy()
ref.index = _srv_naive(m1)          # samakan basis waktu: server-naive
cmp = pr.merge(ref.rename(columns={"asian_high": "ah_ref", "london_high": "lh_ref"}),
               left_on="time", right_index=True, how="inner")
assert len(cmp) > 1000, f"irisan terlalu kecil: {len(cmp)}"
# bar paling awal sampel tidak punya histori hari sebelumnya -> fungsi produksi
# jatuh ke fallback degeneratif. Bandingkan hanya setelah warm-up satu hari penuh.
warm = cmp[cmp["time"] >= pd.Timestamp("2026-03-10")]
cold = cmp[cmp["time"] < pd.Timestamp("2026-03-10")]
n_cold_diff = int((~np.isclose(cold["asian_high"], cold["ah_ref"], equal_nan=True)).sum())
ok_a = np.isclose(warm["asian_high"], warm["ah_ref"], equal_nan=True).all()
ok_l = np.isclose(warm["london_high"], warm["lh_ref"], equal_nan=True).all()
check("produksi == engine teraudit untuk asian_high (pasca warm-up)", ok_a,
      f"({len(warm)} bar, 0 selisih)")
check("produksi == engine teraudit untuk london_high (pasca warm-up)", ok_l)
check("kontrol: selisih hanya di daerah tanpa histori hari sebelumnya",
      n_cold_diff > 0, f"({n_cold_diff} dari {len(cold)} bar pra-warm-up berbeda, "
      f"sesuai dugaan fallback)")
# kausalitas langsung: ubah masa depan, masa lalu tak boleh berubah
cutp = len(sd) // 2
sd2 = sd.copy()
sd2.loc[sd2.index[cutp:], "high"] = 9999.0
pr2 = calculate_session_killzones(sd2)
check("produksi: gangguan di paruh-2 tidak mengubah paruh-1",
      np.allclose(pr["asian_high"].iloc[:cutp], pr2["asian_high"].iloc[:cutp],
                  equal_nan=True))

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T7  TRUNCATION INVARIANCE  — bukti terkuat tidak ada lookahead")
print("=" * 78)
print("    Jika engine melihat masa depan, memotong data mengubah trade lama.")
for cfg, label in ((CFG_CURRENT, "A"), (CFG_RECO, "B")):
    CUT_T = pd.Timestamp("2026-04-01")
    full = run_backtest(m1, m5, cfg)
    part = run_backtest(m1[m1.index < CUT_T], m5[m5.index < CUT_T], cfg)
    fp = full["tdf"]
    fp = fp[pd.to_datetime(fp.open_ts) < CUT_T].reset_index(drop=True)
    tp_ = part["tdf"].reset_index(drop=True)
    same = (len(fp) == len(tp_)
            and np.allclose(fp["pnl"].to_numpy(), tp_["pnl"].to_numpy(), atol=0.01)
            and (fp["open_ts"].astype(str).to_numpy()
                 == tp_["open_ts"].astype(str).to_numpy()).all())
    check(f"config {label}: run terpotong <{CUT_T:%Y-%m-%d} identik dgn run penuh",
          same, f"n={len(tp_)} vs {len(fp)}, "
          f"net ${tp_.pnl.sum():,.0f} vs ${fp.pnl.sum():,.0f}")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print("T8  ARITMETIKA EKUITAS / DRAWDOWN")
print("=" * 78)
CAP = 10_000.0
import dataclasses
# pakai risk 1% supaya akun tidak bangkrut -> DD terukur, bukan artefak blow-up
_low = dataclasses.replace(CFG_CURRENT, risk_usd=100.0)
resA = run_backtest(m1, m5, _low, CAP)
tdf = resA["tdf"]
cs = tdf.pnl.cumsum()
eq_true = CAP + pd.Series([0.0] + list(cs))
dd_true = float((eq_true.cummax() - eq_true).max())
ok_eq = abs(resA["dd_abs"] - dd_true) < 0.02
check("DD$ engine == DD$ dari ekuitas (modal + PnL kumulatif)", ok_eq,
      f"engine ${resA['dd_abs']:,.2f} vs rehitung ${dd_true:,.2f}")
check("DD$ tidak mungkin melebihi modal + puncak laba",
      resA["dd_abs"] <= CAP + max(0.0, float(cs.max())) + 0.02,
      f"DD ${resA['dd_abs']:,.2f}, ekuitas min ${eq_true.min():,.2f} / maks ${eq_true.max():,.2f}")
ok_net = abs(resA["net"] - float(tdf.pnl.sum())) < 0.02
check("Net == jumlah PnL semua trade", ok_net,
      f"${resA['net']:,.2f} vs ${float(tdf.pnl.sum()):,.2f}")
gw = float(tdf.loc[tdf.pnl > 0, "pnl"].sum())
gl = abs(float(tdf.loc[tdf.pnl < 0, "pnl"].sum()))
check("PF == gross win / gross loss", abs(resA["pf"] - round(gw / gl, 3)) < 0.002,
      f"{resA['pf']} vs {gw/gl:.3f}  (GW ${gw:,.0f} / GL ${gl:,.0f})")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 78)
print(f"HASIL: {PASS} PASS / {FAIL} FAIL")
print("=" * 78)
sys.exit(1 if FAIL else 0)
