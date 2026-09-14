"""
================================================================================
UNIT TEST — EKSEKUSI M5 vs M1 pada kaskade MTF
================================================================================
Test deterministik bahwa exec_frame_from_m5() benar-benar mengubah granularitas
eksekusi, bukan sekadar pembungkus:

  Skenario : candle sinyal (bar M5 #11) memicu BUY; candle eksekusi (#12)
             menyentuh TP1 (+18.75) di menit ke-2 LALU jatah ke SL (-15)
             di menit ke-4-5.

  EKSEKUSI M1 : loop manajemen per bar M1 -> TP1 terealisasi dulu (tier-1 +
                exit trail/BE) => trade WIN.
  EKSEKUSI M5 : seluruh candle #12 = SATU bar -> SL dan TP tersentuh di bar
                yang sama -> pesimis [A5] SL dulu => trade LOSS penuh (-risk).

  Entry harus SAMA di kedua mode: waktu = open candle #12, harga = open_ask
  bar M1 pertama candle #12 (ask M5 diagregat 'first' dari M1).

Jalankan:  .venv/bin/python research/test_exec_m5.py
================================================================================
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.backtest_m1_audit import (  # noqa: E402
    session_levels_norepaint, resample_m5, run_backtest, StratCfg, SERVER_TZ,
)
from research.tuning_mtf import exec_frame_from_m5  # noqa: E402

SPR = 0.30  # spread konstan $0.30


def _candle(bars):
    """bars: list (o, h, l, c) M1 -> dict kolom M1 untuk satu candle."""
    rows = []
    for o, h, l, c in bars:
        rows.append(dict(open_bid=o, high_bid=max(o, h, c), low_bid=min(o, l, c),
                         close_bid=c))
    return rows


def build_m1(rally: bool = False) -> pd.DataFrame:
    """Data sintetis: filler Senin penuh (supaya level sesi Asia/London Senin
    terpublikasi), lalu 15 candle rekayasa mulai Selasa 11:00 UTC (13:00 server)."""
    t0 = pd.Timestamp("2026-01-06 11:00:00")  # Selasa 13:00 SERVER
    rows = []

    def add(candle_bars):
        nonlocal rows
        rows.extend(candle_bars)

    # ---- filler Senin 01:00 UTC (03:00 server) -> Selasa 10:55 UTC: flat ----
    fill_start = pd.Timestamp("2026-01-05 01:00:00")
    fill_idx = pd.date_range(fill_start, t0 - pd.Timedelta(minutes=1),
                             freq="1min")
    for _ in fill_idx:
        rows.append(dict(open_bid=3988, high_bid=3989, low_bid=3987, close_bid=3988))

    # candle 0..9 : flat 3987-3989 (tidak ada sweep, tidak ada CHoCH)
    for _ in range(10):
        add(_candle([(3988, 3989, 3987, 3988)] * 5))
    if rally:
        # ---- skenario test [6]: sweep+signal, entry (low 3974 = SL), rally, drop ----
        add(_candle([(3988, 3990, 3988, 3989), (3989, 3992, 3988, 3991),
                     (3991, 3991.5, 3986, 3987), (3987, 3988, 3984, 3985),
                     (3985, 3986, 3985, 3990)]))                     # A: sweep+signal#1
        add(_candle([(3990, 3991, 3989.5, 3991), (3991, 3993, 3990, 3993),
                     (3993, 3995, 3992, 3995), (3995, 3996, 3994, 3995.5),
                     (3995.5, 3997, 3974, 3996)]))                    # B: entry#1 (low=SL!) + signal#2
        add(_candle([(3996, 4010, 3995, 4009), (4009, 4030, 4008, 4028),
                     (4028, 4040, 4025, 4038), (4038, 4050, 4035, 4048),
                     (4048, 4060, 4045, 4055)]))                      # C: rally -> TP3
        add(_candle([(4055, 4065, 4050, 4062), (4062, 4070, 4060, 4068),
                     (4068, 4072, 4065, 4070), (4070, 4075, 4066, 4072),
                     (4072, 4078, 4070, 4075)]))                      # D: lanjut rally
        add(_candle([(4075, 4080, 4070, 4078), (4078, 4082, 4076, 4080),
                     (4080, 4084, 4078, 4082), (4082, 4086, 4080, 4084),
                     (4084, 4088, 4082, 4085)]))                      # E: puncak
        add(_candle([(4085, 4086, 4080, 4082), (4082, 4083, 4078, 4080),
                     (4080, 4081, 4075, 4077), (4077, 4078, 4068, 4070),
                     (4070, 4072, 4065, 4070)]))                      # F: drop -> exit runner
    else:
        # candle 10 : low menusuk SSL (sweep utk window bar #11)
        add(_candle([(3988, 3990, 3988, 3989), (3989, 3992, 3988, 3991),
                     (3991, 3991.5, 3986, 3987), (3987, 3988, 3984, 3985),
                     (3985, 3986, 3985, 3990)]))
        # candle 11 : SIGNAL BUY — bull, close 3996 > swing/CHoCH/EMA-H1
        add(_candle([(3990, 3991, 3989.5, 3991), (3991, 3993, 3990, 3993),
                     (3993, 3995, 3992, 3995), (3995, 3996, 3994, 3995.5),
                     (3995.5, 3997, 3995, 3996)]))
        # candle 12 : EKSEKUSI — TP1 (+18.75) tersentuh menit-2, lalu jatuh ke SL (-15)
        #             (low 3974 juga meng-EXIT trade#1 dari candle #10 di test [5])
        add(_candle([(4000, 4010, 3999.9, 4009), (4009, 4021, 4008, 4020),
                     (4020, 4020.5, 4010, 4011), (4011, 4012, 3996, 3997),
                     (3997, 3998, 3974, 3985)]))
        # candle 13 : lanjutan turun (bar eksekusi utk menutup posisi mode M5)
        add(_candle([(3985, 3986, 3984, 3984), (3984, 3985, 3983, 3983.5),
                     (3983.5, 3984, 3983, 3983), (3983, 3984, 3981, 3981.5),
                     (3981.5, 3982, 3980, 3982)]))
        # candle 14 : filler
        add(_candle([(3982, 3984, 3981, 3983)] * 5))

    idx = pd.date_range(fill_start, periods=len(rows), freq="1min")
    m1 = pd.DataFrame(rows, index=idx)
    for c in ("open", "high", "low", "close"):
        m1[f"{c}_ask"] = m1[f"{c}_bid"] + SPR
    m1["spread_usd"] = SPR
    srv = m1.index.tz_localize("UTC").tz_convert(SERVER_TZ)
    m1["srv_hour"] = srv.hour.to_numpy()
    m1["srv_min"] = srv.minute.to_numpy()
    m1["srv_date"] = srv.date
    return m1


def build_m5(m1: pd.DataFrame) -> pd.DataFrame:
    m5 = resample_m5(session_levels_norepaint(m1))
    # 15 candle rekayasa menempel di AKHIR frame (setelah filler Senin)
    assert len(m5) >= 15
    # level MTF direkayasa agar sinyal BUY PASTI muncul di candle #11
    m5["h1_ema200"] = 3900.0          # bias bull
    m5["m30_ssl"] = 3985.0            # disweep oleh low candle #10 (3984)
    m5["m30_bsl"] = 4100.0            # tak terjangkau
    m5["pd_low"] = 3985.0
    m5["pd_high"] = 4100.0
    m5["m30_fsw"] = 3985.0
    m5["m30_fsh"] = 4100.0
    m5["m15_swing_h"] = 3990.0        # CHoCH bull: close #11 = 3996
    m5["m15_swing_l"] = 3000.0
    return m5


def main():
    m1 = build_m1()
    m5 = build_m5(m1)
    # 15 candle rekayasa menempel di AKHIR frame (setelah filler Senin)
    assert len(m5) >= 15

    # ---------- properti frame eksekusi M5 ----------
    ex = exec_frame_from_m5(m1, m5)
    assert len(ex) == len(m5) and not ex[["open_bid", "open_ask"]].isna().any().any()
    c12 = m5.index[-3]                   # candle eksekusi (sinyal di candle [-4])
    assert abs(ex.at[c12, "open_ask"] - (4000 + SPR)) < 1e-9, \
        "open_ask M5 harus = open_ask bar M1 PERTAMA candle (agregat 'first')"
    assert abs(ex.at[c12, "high_bid"] - 4021) < 1e-9
    assert abs(ex.at[c12, "low_bid"] - 3974) < 1e-9
    grp = m1["open_ask"].groupby(pd.Grouper(freq="5min", label="left", closed="left")).first()
    assert np.allclose(ex["open_ask"].to_numpy(), grp.reindex(ex.index).to_numpy()), \
        "ask agregat 'first' per candle harus identik dgn groupby M1"
    print("[1] properti frame eksekusi M5 (ask=first M1, OHLC candle): PASS")

    # ---------- eksekusi M1 (perilaku lama) ----------
    cfg = StratCfg(name="unit-mtf", signal_mode="mtf", risk_usd=100.0,
                   max_spread_usd=1.20)
    st1 = run_backtest(m1, m5, cfg)
    t1 = st1["tdf"]
    assert len(t1) == 1, f"mode M1: harus 1 trade, dapat {len(t1)}"
    assert t1.iloc[0]["type"] == "BUY"
    assert t1.iloc[0]["res"] == "WIN", f"M1 harus WIN (TP1 terealisasi per menit): {t1.iloc[0].to_dict()}"
    assert t1.iloc[0]["pnl"] >= 30, f"pnl M1 terlalu kecil: {t1.iloc[0]['pnl']}"
    print(f"[2] eksekusi M1 : {t1.iloc[0]['res']} pnl {t1.iloc[0]['pnl']:+.2f} "
          f"(TP1 dulu, exit trail/BE): PASS")

    # ---------- eksekusi M5 (baru) ----------
    st5 = run_backtest(ex, m5, cfg)
    t5 = st5["tdf"]
    assert len(t5) == 1, f"mode M5: harus 1 trade, dapat {len(t5)}"
    assert t5.iloc[0]["type"] == "BUY"
    assert t5.iloc[0]["res"] == "LOSS", f"M5 harus LOSS (pesimis SL-dulu dalam candle): {t5.iloc[0].to_dict()}"
    assert abs(t5.iloc[0]["pnl"] + 105.0) < 1.0, f"pnl M5 ~ -105: {t5.iloc[0]['pnl']}"
    print(f"[3] eksekusi M5 : {t5.iloc[0]['res']} pnl {t5.iloc[0]['pnl']:+.2f} "
          f"(SL & TP sesama candle -> SL dulu [A5]): PASS")

    # ---------- entry identik antar mode ----------
    assert t1.iloc[0]["open_ts"] == t5.iloc[0]["open_ts"] == c12, \
        "entry harus di OPEN candle M5 berikutnya di kedua mode"
    assert t1.iloc[0]["lots"] == t5.iloc[0]["lots"]
    print(f"[4] entry identik di kedua mode: open_ts={c12}, "
          f"lots={t1.iloc[0]['lots']}: PASS")

    # ---------- [5] strict_bar_open_entry: blokir entry di candle yang sama
    # dengan exit posisi lama (anti optimis: entry di open bar setelah mengetahui
    # H/L bar itu). Skenario: trade#1 hidup hingga candle #12 (SL tersentuh di
    # tengah candle); sinyal kedua di candle #11 -> entry candle #12.
    #   non-strict : trade#1 exit di candle #12 lalu entry trade#2 di open #12 -> 2 trade
    #   strict     : entry trade#2 diblok -> 1 trade
    cfg_ns = StratCfg(name="ns", signal_mode="mtf", risk_usd=100.0, max_spread_usd=1.20)
    cfg_sx = StratCfg(name="sx", signal_mode="mtf", risk_usd=100.0, max_spread_usd=1.20,
                      strict_bar_open_entry=True)
    # rekayasa: sinyal PERTAMA di candle #10 (sweep candle, close 3990) -> trade#1
    # entry candle #11 (open 3990.3, SL 3975.3); candle #12 (low 3974) meng-EXIT
    # trade#1 di tengah candle; sinyal KEDUA di candle #11 -> entry candle #12.
    m5b = m5.copy()
    m5b["m30_ssl"] = 3987.5         # bar filler 7-8 (low 3987) ikut tersapu -> sinyal di #10
    m5b["m15_swing_h"] = 3989.0     # close candle #10 (3990) lolos CHoCH
    st_ns = run_backtest(ex, m5b, cfg_ns)
    st_sx = run_backtest(ex, m5b, cfg_sx)
    st_m1 = run_backtest(m1, m5b, cfg_sx)
    assert len(st_ns["tdf"]) == 2, f"non-strict harus 2 trade, dapat {len(st_ns['tdf'])}"
    assert len(st_sx["tdf"]) == 1, f"strict harus 1 trade, dapat {len(st_sx['tdf'])}"
    assert len(st_m1["tdf"]) == 1, "M1 (posisi masih terbuka di menit-0 candle #12) juga 1"
    print(f"[5] strict_bar_open_entry: non-strict {len(st_ns['tdf'])} tr vs strict "
          f"{len(st_sx['tdf'])} tr vs M1 {len(st_m1['tdf'])} tr: PASS")

    # ---------- [6] manage_entry_bar: candle eksekusi ikut diuji SL/TP.
    # Skenario: trade#1 entry di candle yang low-nya menusuk SL (-15) tapi
    # close-nya kuat, lalu 3 candle berikutnya rally ke TP3.
    #   manage_entry_bar=False : candle entry kebal -> trade selamat -> TP-FULL WIN
    #   manage_entry_bar=True  : SL tereksekusi di candle entry -> LOSS -105
    m1c = build_m1(rally=True)
    m5c = build_m5(m1c)
    m5c["m30_ssl"] = 3987.5         # sinyal juga muncul di candle sweep (close 3990)
    m5c["m15_swing_h"] = 3989.0
    exc = exec_frame_from_m5(m1c, m5c)
    cfg_meb_off = StratCfg(name="off", signal_mode="mtf", risk_usd=100.0,
                           max_spread_usd=1.20, strict_bar_open_entry=True)
    cfg_meb_on = StratCfg(name="on", signal_mode="mtf", risk_usd=100.0,
                          max_spread_usd=1.20, strict_bar_open_entry=True,
                          manage_entry_bar=True)
    t_off = run_backtest(exc, m5c, cfg_meb_off)["tdf"]
    t_on = run_backtest(exc, m5c, cfg_meb_on)["tdf"]
    assert len(t_off) >= 1 and len(t_on) >= 1
    assert t_off.iloc[0]["res"] == "WIN", \
        f"tanpa manage_entry_bar candle entry kebal SL -> harus WIN: {t_off.iloc[0].to_dict()}"
    assert t_on.iloc[0]["res"] == "LOSS" and abs(t_on.iloc[0]["pnl"] + 105.0) < 1.0, \
        f"dengan manage_entry_bar SL tereksekusi di candle entry: {t_on.iloc[0].to_dict()}"
    print(f"[6] manage_entry_bar: off {t_off.iloc[0]['res']} {t_off.iloc[0]['pnl']:+.2f} vs "
          f"on {t_on.iloc[0]['res']} {t_on.iloc[0]['pnl']:+.2f}: PASS")

    print("\nSEMUA UNIT TEST EKSEKUSI M5 PASS")


if __name__ == "__main__":
    main()
