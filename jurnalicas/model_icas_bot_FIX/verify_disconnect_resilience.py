"""
================================================================================
VERIFIKASI KETAHANAN KONEKSI & INTEGRITAS EKSEKUSI — mock MetaTrader5 (tanpa terminal)
================================================================================
[AUDIT FORENSIK 2 Sep 2026] Mereproduksi insiden NYATA dari logs/trade_journal.jsonl
lalu membuktikan bahwa kode baru menanganinya:

  DC-02  Tick None (feed putus)  -> dulu bid=0 -> fav SELL = +$4.600 -> TP1/2/3 & trailing
         menembak beruntun. Kini: get_current_tick() None, close_partial/modify ditolak.
  DC-03  positions_get None (IPC) -> dulu dianggap "tidak ada posisi" -> mutex 1-posisi
         tembus. Kini: send_order fail-closed, active_position dipertahankan.
  DC-04  copy_rates None saat MT5 tersedia -> dulu jatuh ke CSV repo (bar Juli 2026 beku).
         Kini: DataFrame kosong.
  DC-05  account_info None -> dulu balance=10000 (INITIAL_CAPITAL) "TERHUBUNG ✅"
         (22 snapshot palsu 2 Sep 10:04-15:20). Kini connected=False, balance None.
  DC-01  terminal_info None / connected=False -> is_terminal_connected() False;
         reconnect() memanggil shutdown+initialize dan membersihkan dict posisi.
  SL-01  Never-loosen: modify_sl menolak SL yang MELONGGARKAN (9 insiden be_lock
         pasca-TP1 menurunkan SL trailing di jurnal 27-31 Agu).
  LA-01  Level sesi kausal: tidak ada lookahead; window pendek tidak degenerate.
  ST-01  Startup: get_open_position_details raise -> tidak UnboundLocalError.
"""
import sys
import os
import types
import datetime
from collections import namedtuple

import pandas as pd
import numpy as np

# --------------------------------------------------------------- Mock MT5 ----
TradeResult = namedtuple("TradeResult", ["retcode", "comment", "order", "price", "deal", "volume"])
Tick = namedtuple("Tick", ["bid", "ask", "time"])
SymInfo = namedtuple("SymInfo", ["point", "digits", "volume_min", "volume_max", "volume_step",
                                 "visible", "filling_mode", "trade_stops_level", "trade_freeze_level"])
Position = namedtuple("Position", ["ticket", "type", "volume", "price_open", "sl", "tp", "profit", "magic"])
AccInfo = namedtuple("AccInfo", ["login", "name", "server", "trade_mode", "currency", "leverage",
                                 "balance", "equity", "margin", "margin_free", "margin_level"])
TermInfo = namedtuple("TermInfo", ["connected", "trade_allowed"])

mock = types.ModuleType("MetaTrader5")
for k, v in dict(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, POSITION_TYPE_BUY=0, POSITION_TYPE_SELL=1,
                 TRADE_ACTION_DEAL=1, TRADE_ACTION_SLTP=6, TRADE_RETCODE_DONE=10009,
                 ORDER_FILLING_IOC=1, ORDER_FILLING_FOK=0, ORDER_FILLING_RETURN=2,
                 ORDER_TIME_GTC=0, TIMEFRAME_M5=5, DEAL_ENTRY_OUT=1, DEAL_TYPE_SELL=1,
                 DEAL_TYPE_BUY=0, ACCOUNT_TRADE_MODE_REAL=2).items():
    setattr(mock, k, v)

STATE = {
    "tick": Tick(4297.10, 4297.36, 1788000000),
    "positions": [Position(5025658205, 1, 0.33, 4297.533, 4312.533, 0.0, 0.0, 777404)],  # SELL
    "account": AccInfo(88921045, "Demo", "Exness-MT5Trial6", 0, "USD", 2000, 9155.73, 9345.78, 100.0, 9245.78, 9345.0),
    "terminal": TermInfo(True, True),
    "rates_ok": True,
    "sent": [],            # order_send requests
    "init_calls": 0,
    "shutdown_calls": 0,
    "raise_positions": False,
}

def symbol_info(sym): return SymInfo(0.001, 3, 0.01, 200.0, 0.01, True, 2, 0, 0)
def symbol_info_tick(sym): return STATE["tick"]
def positions_get(*a, **kw):
    if STATE["raise_positions"]:
        raise RuntimeError("IPC broken")
    if STATE["positions"] is None:
        return None
    if "ticket" in kw:
        return tuple(p for p in STATE["positions"] if p.ticket == kw["ticket"])
    return tuple(STATE["positions"])
def account_info(): return STATE["account"]
def terminal_info(): return STATE["terminal"]
def copy_rates_from_pos(sym, tf, start, count):
    if not STATE["rates_ok"]:
        return None
    t0 = 1788000000 - 300 * count
    arr = np.array([(t0 + 300 * i, 4290.0, 4291.0, 4289.0, 4290.5, 100, 260, 0) for i in range(count)],
                   dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                          ("tick_volume", "i8"), ("spread", "i8"), ("real_volume", "i8")])
    return arr
def order_send(req):
    STATE["sent"].append(dict(req))
    if req["action"] == mock.TRADE_ACTION_SLTP:
        ps = STATE["positions"] or []
        for i, p in enumerate(ps):
            if p.ticket == req["position"]:
                ps[i] = p._replace(sl=req["sl"])
        return TradeResult(10009, "Done", 0, 0.0, 0, 0.0)
    return TradeResult(10009, "Done", 999, req.get("price", 0.0), 999, req.get("volume", 0.0))
def initialize(**kw):
    STATE["init_calls"] += 1
    return STATE["terminal"] is not None
def shutdown():
    STATE["shutdown_calls"] += 1
def login(**kw): return True
def last_error(): return (1, "mock")
def symbol_select(s, v): return True
def history_deals_get(a, b): return ()

for fn in (symbol_info, symbol_info_tick, positions_get, account_info, terminal_info, copy_rates_from_pos,
           order_send, initialize, shutdown, login, last_error, symbol_select, history_deals_get):
    setattr(mock, fn.__name__, fn)
sys.modules["MetaTrader5"] = mock
# -----------------------------------------------------------------------------

import logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import config
from src.execution.mt5_bridge import IcasMT5Bridge
from src.indicators.sessions import calculate_session_killzones, calculate_session_levels_causal

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    PASS += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name)

print("=" * 78)
print(" VERIFIKASI KETAHANAN KONEKSI & INTEGRITAS (insiden jurnal 27 Agu - 2 Sep 2026)")
print("=" * 78)

bridge = IcasMT5Bridge(config)
check("[DC-01] initialize OK saat terminal sehat", bridge.initialize() is True)
check("[DC-01] is_terminal_connected True saat sehat", bridge.is_terminal_connected() is True)

# ---------------------------------------------------------------- DC-02 -------
print("\n[DC-02] Tick None (feed putus) — insiden fav +46.000 pips")
STATE["tick"] = None
tick = bridge.get_current_tick()
check("get_current_tick() -> None (bukan bid=0/ask=0)", tick is None)
n_sent_before = len(STATE["sent"])
check("close_partial ditolak tanpa tick (tidak ada order_send)",
      bridge.close_partial(5025658205, 0.1) is False and len(STATE["sent"]) == n_sent_before)
check("modify_sl ditolak tanpa tick (defer)", bridge.modify_sl(5025658205, 4290.0) is False and len(STATE["sent"]) == n_sent_before)
check("send_order ditolak tanpa tick", bridge.send_order("SELL", 0.33, 4310.0) is None and len(STATE["sent"]) == n_sent_before)
# simulasi perhitungan daemon lama vs baru
ep = 4297.533
old_bid = 0.0
fav_old = (ep - old_bid) * 10.0
check(f"BUKTI bug lama: fav_pips dengan bid=0 = {fav_old:,.0f} pips (> TP3 562.5) -> TP1..TP3 menembak",
      fav_old > config.TP3_PIPS)
STATE["tick"] = Tick(0.0, 0.0, 1788000000)
check("tick bid=0/ask=0 dari terminal juga dianggap None", bridge.get_current_tick() is None)
STATE["tick"] = Tick(4297.10, 4297.36, 1788000000)

# ---------------------------------------------------------------- DC-03 -------
print("\n[DC-03] positions_get None (IPC) — mutex & state posisi")
pos_ok = bridge.get_open_position_details()
check("posisi terbaca normal saat IPC sehat", pos_ok is not None and pos_ok["ticket"] == 5025658205)
STATE["positions"] = None
p = bridge.get_open_position_details()
check("get_open_position_details -> None + positions_query_ok False", p is None and bridge.positions_query_ok is False)
check("active_position TIDAK dibuang saat IPC None (state manajemen tetap)", bridge.active_position is not None)
check("has_open_positions_strict -> None (tidak diketahui)", bridge.has_open_positions_strict() is None)
n_sent_before = len(STATE["sent"])
check("send_order fail-closed saat status posisi tidak diketahui (TIDAK order kedua)",
      bridge.send_order("BUY", 0.33, 4280.0) is None and len(STATE["sent"]) == n_sent_before)
check("is_ticket_open -> None (bukan False) saat IPC None", bridge.is_ticket_open(5025658205) is None)
STATE["raise_positions"] = True
check("positions_get raise -> tidak crash, dianggap tidak diketahui",
      bridge.get_open_position_details() is None and bridge.positions_query_ok is False)
STATE["raise_positions"] = False
STATE["positions"] = [Position(5025658205, 1, 0.33, 4297.533, 4312.533, 0.0, 0.0, 777404)]
check("pulih: posisi terbaca lagi & query_ok True",
      bridge.get_open_position_details() is not None and bridge.positions_query_ok is True)

# ---------------------------------------------------------------- DC-04 -------
print("\n[DC-04] copy_rates None saat MT5 tersedia — bar basi CSV")
STATE["rates_ok"] = False
df = bridge.get_latest_m5_candles(150)
check("get_latest_m5_candles -> DataFrame KOSONG (bukan CSV repo Juli 2026)", df.empty)
STATE["rates_ok"] = True
df = bridge.get_latest_m5_candles(150)
check("rates normal -> 150 bar", len(df) == 150)

# ---------------------------------------------------------------- DC-05 -------
print("\n[DC-05] account_info None — balance 10000 palsu")
STATE["account"] = None
acc = bridge.get_account_details()
check("connected=False & balance None (bukan INITIAL_CAPITAL 10000)",
      acc.get("connected") is False and acc.get("balance") is None)
check("get_account_balance -> None saat putus", bridge.get_account_balance() is None)
check("status_text menyatakan TERPUTUS", "TERPUTUS" in acc.get("status_text", ""))
STATE["account"] = AccInfo(88921045, "Demo", "Exness-MT5Trial6", 0, "USD", 2000, 9155.73, 9345.78, 100.0, 9245.78, 9345.0)
check("pulih: balance 9155.73", bridge.get_account_balance() == 9155.73)

# ---------------------------------------------------------------- DC-01 -------
print("\n[DC-01] terminal_info None / connected False -> reconnect")
STATE["terminal"] = None
check("terminal_info None -> is_terminal_connected False", bridge.is_terminal_connected() is False)
STATE["terminal"] = TermInfo(False, True)
check("terminal.connected=False -> is_terminal_connected False", bridge.is_terminal_connected() is False)
STATE["terminal"] = TermInfo(True, True)
sd0, in0 = STATE["shutdown_calls"], STATE["init_calls"]
ok = bridge.reconnect(max_attempts=1)
check("reconnect() -> shutdown + initialize dipanggil & sukses",
      ok is True and STATE["shutdown_calls"] == sd0 + 1 and STATE["init_calls"] == in0 + 1)
check("reconnect membersihkan dict posisi lama (wajib merge ulang state)", bridge.active_position is None)
check("reconnect_count naik", bridge.reconnect_count == 1)

# ---------------------------------------------------------------- SL-01 -------
print("\n[SL-01] Never-loosen SL (9 insiden be_lock pasca-TP1 menurunkan SL trailing)")
# SELL: SL sudah di-trail ke 4606.893 (entry 4633.118). be_lock lama minta 4629.333 (melonggarkan 224 pips)
STATE["positions"] = [Position(4988300823, 1, 0.16, 4633.118, 4606.893, 0.0, 0.0, 777404)]
STATE["tick"] = Tick(4599.00, 4599.26, 1788000000)
bridge.active_position = None
n_before = len(STATE["sent"])
res = bridge.modify_sl(4988300823, 4629.333)
check("SELL: SL 4606.893 -> 4629.333 (melonggarkan) DITOLAK, tidak ada order_send",
      res is False and len(STATE["sent"]) == n_before and STATE["positions"][0].sl == 4606.893)
STATE["tick"] = Tick(4590.00, 4590.26, 1788000000)   # harga sudah jauh di bawah -> SL 4596.893 sah
res = bridge.modify_sl(4988300823, 4596.893)
check("SELL: SL 4606.893 -> 4596.893 (memperketat) DITERIMA",
      res is True and abs(STATE["positions"][0].sl - 4596.893) < 1e-9)
# BUY: SL trail 4629.822 (entry 4616.231); be_lock lama minta 4617.382
STATE["positions"] = [Position(4987805272, 0, 0.16, 4616.231, 4629.822, 0.0, 0.0, 777404)]
STATE["tick"] = Tick(4640.00, 4640.26, 1788000000)
n_before = len(STATE["sent"])
res = bridge.modify_sl(4987805272, 4617.382)
check("BUY: SL 4629.822 -> 4617.382 (melonggarkan 124 pips) DITOLAK",
      res is False and len(STATE["sent"]) == n_before)
res = bridge.modify_sl(4987805272, 4635.0)
check("BUY: SL 4629.822 -> 4635.0 (memperketat) DITERIMA", res is True)

# ---------------------------------------------------------------- LA-01 -------
print("\n[LA-01] Level sesi kausal vs lookahead")
times = pd.date_range("2026-06-09 00:00", "2026-06-10 12:00", freq="5min")
rng = np.random.default_rng(7)
base = 4200 + np.cumsum(rng.normal(0, 0.5, len(times)))
dfm = pd.DataFrame({"time": times, "open": base, "high": base + 1.0, "low": base - 1.0,
                    "close": base, "spread": 260})
# paksa spike di sesi Asia 10 Jun agar terlihat jelas
mask_asia_10 = (dfm.time.dt.date == datetime.date(2026, 6, 10)) & (dfm.time.dt.hour == 5)
dfm.loc[mask_asia_10, "high"] += 50.0
look = calculate_session_killzones(dfm)
caus = calculate_session_levels_causal(dfm)
r_look = look[look.time == pd.Timestamp("2026-06-10 01:00")].iloc[0]
r_caus = caus[caus.time == pd.Timestamp("2026-06-10 01:00")].iloc[0]
asia_prev_final = dfm[(dfm.time.dt.date == datetime.date(2026, 6, 9)) & (dfm.time.dt.hour.between(3, 6))]["high"].max()
asia_today_final = dfm[(dfm.time.dt.date == datetime.date(2026, 6, 10)) & (dfm.time.dt.hour.between(3, 6))]["high"].max()
check("BUKTI lookahead lama: bar 01:00 sudah memuat range Asia 03-07 HARI YANG SAMA (masa depan, termasuk spike 05:00)",
      abs(r_look["asian_high"] - asia_today_final) < 1e-9 and asia_today_final > asia_prev_final + 30.0)
check("kausal: bar 01:00 memakai range Asia FINAL hari sebelumnya",
      abs(r_caus["asian_high"] - asia_prev_final) < 1e-9)
# Window daemon LAMA = 150 bar (12,5 jam): pada 01:30 tidak ada sesi Asia sama sekali
# di window -> fallback high/low bar sendiri (degenerate). Window BARU 600 bar mencakup
# sesi Asia+London hari sebelumnya -> level valid.
end_i = dfm.index[dfm.time == pd.Timestamp("2026-06-10 01:30")][0]
win150 = dfm.iloc[max(0, end_i - 149):end_i + 1].reset_index(drop=True)
win600 = dfm.iloc[max(0, end_i - 599):end_i + 1].reset_index(drop=True)
r150 = calculate_session_levels_causal(win150).iloc[-1]
r600 = calculate_session_levels_causal(win600).iloc[-1]
check("BUKTI window lama 150 bar @01:30: level Asia = high/low bar sendiri (degenerate)",
      abs(r150["asian_high"] - r150["high"]) < 1e-9 and abs(r150["asian_low"] - r150["low"]) < 1e-9)
check("window baru 600 bar @01:30: level Asia = range final hari sebelumnya (valid)",
      abs(r600["asian_high"] - asia_prev_final) < 1e-9)
# no-leak brute force
leak = False
for _, row in caus[caus.time.dt.date == datetime.date(2026, 6, 10)].iterrows():
    past = dfm[(dfm.time <= row.time) & (dfm.time.dt.hour.between(3, 6))]
    if len(past) and row["asian_high"] > past["high"].max() + 1e-9:
        leak = True
check("kausal: tidak ada kebocoran masa depan (brute force per bar)", not leak)
check("kolom keluaran identik dengan versi lama",
      set(look.columns) == set(caus.columns))

# ---------------------------------------------------------------- ST-03 -------
print("\n[ST-03] Rebuild state dari deal TANPA bergantung comment 'Partial TP' (TP1 3x tiket 4987805272)")
Deal = namedtuple("Deal", ["position_id", "comment", "entry", "symbol", "type", "profit", "commission", "swap", "time", "volume"])
def history_deals_get_real(a, b):
    # broker menimpa comment ("[tp]", "" dsb) — engine lama menghitung partials=0
    return (Deal(4987805272, "", 0, "XAUUSDm", 0, 0.0, 0.0, 0.0, 1788000000, 0.33),        # IN
            Deal(4987805272, "[partial]", 1, "XAUUSDm", 1, 150.0, 0.0, 0.0, 1788000100, 0.10),  # OUT (TP1)
            Deal(4987805272, "", 1, "XAUUSDm", 1, 90.0, 0.0, 0.0, 1788000200, 0.07))       # OUT (TP1 ulang, bug lama)
mock.history_deals_get = history_deals_get_real
STATE["positions"] = [Position(4987805272, 0, 0.16, 4616.231, 4629.822, 0.0, 0.0, 777404)]
STATE["tick"] = Tick(4640.00, 4640.26, 1788000000)
inf = bridge.infer_position_state({"ticket": 4987805272, "type": "BUY", "volume": 0.16,
                                   "price_open": 4616.231, "sl": 4629.822, "max_fav": 0.0})
check("infer: tp1_hit True walau comment deal bukan 'Model Icas Partial TP'", inf.get("tp1_hit") is True)
check("infer: initial_volume EKSAK 0.33 (= sisa 0.16 + OUT 0.10 + 0.07)", abs(inf.get("initial_volume", 0) - 0.33) < 1e-9)
check("infer: tiket string '4987805272' juga cocok (koersi int)",
      bridge.infer_position_state({"ticket": "4987805272", "type": "BUY", "volume": 0.16,
                                   "price_open": 4616.231, "sl": 4629.822}).get("tp1_hit") is True)
mock.history_deals_get = history_deals_get

# ---------------------------------------------------------------- ST-01 -------
print("\n[ST-01] Startup: rekonsiliasi tidak crash UnboundLocalError")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icas_daemon.py"), encoding="utf-8").read()
check("open_pos_now diinisialisasi None SEBELUM blok try", "open_pos_now = None" in src.split("try:\n        open_pos_now")[0])
check("loop utama punya try/except per-siklus (cycle_error)", "cycle_error" in src and "consecutive_cycle_errors" in src)
check("daemon memakai level sesi kausal", "calculate_session_levels_causal(df_m5_raw)" in src)
check("daemon punya health-check koneksi sebelum manajemen posisi", "is_terminal_connected()" in src)

print("\n" + "=" * 78)
print(f" HASIL: {PASS} PASS / {FAIL} FAIL")
print("=" * 78)
sys.exit(0 if FAIL == 0 else 1)
