"""
VERIFIKASI S-03 — Persistensi State Daemon (anti double-TP pasca restart)
--------------------------------------------------------------------------
Skenario:
  1. Posisi running, TP1 & TP2 sudah ter-close -> state tersimpan ke file.
  2. Daemon "restart" (objek bridge/strategy baru, dict posisi baru dari MT5
     hanya berisi flag default False) -> state dipulihkan dari file.
  3. File state DIHAPUS -> state direbuild dari riwayat deal MT5
     (2 deal 'Model Icas Partial TP') -> infer tp1/tp2 True.
  4. Counter harian tersimpan & dipulihkan.
"""
import sys
import os
import time
import types
import tempfile
from collections import namedtuple

# ---- mock MT5 ----
TradeResult = namedtuple("TradeResult", ["retcode", "comment", "order", "price", "deal", "volume"])
Deal = namedtuple("Deal", ["position_id", "comment", "entry", "symbol", "type",
                           "profit", "commission", "swap", "time"])
Position = namedtuple("Position", ["ticket", "type", "volume", "price_open", "sl", "tp", "profit", "magic"])
SymInfo = namedtuple("SymInfo", ["point", "digits", "volume_min", "volume_max", "volume_step",
                                 "visible", "filling_mode", "trade_stops_level", "trade_freeze_level"])
Tick = namedtuple("Tick", ["bid", "ask", "time"])

mock = types.ModuleType("MetaTrader5")
for k, v in dict(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, POSITION_TYPE_BUY=0, POSITION_TYPE_SELL=1,
                 TRADE_ACTION_DEAL=1, TRADE_ACTION_SLTP=6, TRADE_RETCODE_DONE=10009,
                 ORDER_FILLING_IOC=1, ORDER_FILLING_FOK=0, ORDER_FILLING_RETURN=2,
                 ORDER_TIME_GTC=0, TIMEFRAME_M5=5, DEAL_ENTRY_OUT=1, DEAL_TYPE_SELL=1,
                 DEAL_TYPE_BUY=0).items():
    setattr(mock, k, v)
mock.symbol_info = lambda s: SymInfo(0.01, 2, 0.01, 200.0, 0.01, True, 2, 0, 0)
mock.symbol_info_tick = lambda s: Tick(4670.00, 4670.26, int(time.time()))
mock.symbol_select = lambda s, v: True
mock.initialize = lambda **k: True
mock.login = lambda **k: True
mock.last_error = lambda: (1, "ok")
mock._pos = [Position(555001, 0, 1.13, 4667.80, 4669.80, 0.0, 40.0, 777404)]
mock.positions_get = lambda **kw: tuple(p for p in mock._pos if kw.get("ticket") in (None, p.ticket)) if "ticket" in kw else tuple(mock._pos)
mock.history_deals_get = lambda a, b: (
    Deal(555001, "Model Icas Partial TP", 1, "XAUUSDm", 1, 150.0, 0.0, 0.0, 1766999000),
    Deal(555001, "Model Icas Partial TP", 1, "XAUUSDm", 1, 250.0, 0.0, 0.0, 1766999500),
)
mock.order_send = lambda r: TradeResult(10009, "Done", 0, 0.0, 0, 0.0)
sys.modules["MetaTrader5"] = mock

import logging
logging.basicConfig(level=logging.WARNING)
from config import config
from src.state_store import StateStore
from src.execution.mt5_bridge import IcasMT5Bridge

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    print(("  ✅ " if cond else "  ❌ ") + name)
    globals().__setitem__("PASS", PASS + (1 if cond else 0))
    globals().__setitem__("FAIL", FAIL + (0 if cond else 1))

tmp = tempfile.mkdtemp()
state_path = os.path.join(tmp, "icas_state.json")

print("=" * 74)
print("[1] Simpan state posisi running (TP1 & TP2 sudah closed)")
store = StateStore(state_path)
pos_live = {"ticket": 555001, "type": "BUY", "volume": 1.13, "initial_volume": 2.50,
            "price_open": 4667.80, "sl": 4668.70, "tp1_hit": True, "tp2_hit": True,
            "tp3_hit": False, "be_set": True, "max_fav": 5.50, "trail_step": 0}
store.save_position(pos_live)
check("file state tertulis", os.path.exists(state_path))

print("[2] Simulasi RESTART: posisi dari MT5 dengan flag default (hilang semua)")
store2 = StateStore(state_path)  # daemon baru baca file
fresh_pos = {"ticket": 555001, "type": "BUY", "volume": 1.13, "initial_volume": 2.50,
             "price_open": 4667.80, "sl": 4669.80, "tp1_hit": False, "tp2_hit": False,
             "tp3_hit": False, "be_set": False, "max_fav": 0.0, "trail_step": 0}
merged = store2.merge_into(fresh_pos)
check("merge berhasil", merged)
check("tp1_hit pulih True (TP1 TIDAK akan dieksekusi ganda)", fresh_pos["tp1_hit"] is True)
check("tp2_hit pulih True", fresh_pos["tp2_hit"] is True)
check("be_set pulih True", fresh_pos["be_set"] is True)
check("max_fav pulih 5.50 (state lama lebih tinggi)", fresh_pos["max_fav"] == 5.50)

print("[3] File state HILANG -> rebuild dari riwayat deal MT5")
os.remove(state_path)
store3 = StateStore(state_path)
check("file hilang -> merge False", store3.merge_into(dict(fresh_pos)) is False)
bridge = IcasMT5Bridge(config)
bridge.connected = True
inferred = bridge.infer_position_state({"ticket": 555001, "type": "BUY", "volume": 1.13,
                                        "price_open": 4667.80, "sl": 4669.80, "max_fav": 0.0})
check("infer tp1_hit True (2 deal Partial TP)", inferred.get("tp1_hit") is True)
check("infer tp2_hit True", inferred.get("tp2_hit") is True)
check("infer tp3_hit False", inferred.get("tp3_hit") is False)
check("infer initial_volume ~2.50 (1.13 / (1-0.55))", abs(inferred.get("initial_volume", 0) - 1.13 / 0.45) < 0.02)
check("infer be_set True (SL 4669.80 > entry BUY)", inferred.get("be_set") is True)

print("[4] Counter harian")
store3.save_daily("2026-08-25", 3, 1)
d = StateStore(state_path).get_daily("2026-08-25")
check("counter harian pulih (3 trade, 1 loss)", d["daily_trades_count"] == 3 and d["consecutive_losses"] == 1)
check("tanggal lain -> reset 0", StateStore(state_path).get_daily("2026-08-26")["daily_trades_count"] == 0)

print("=" * 74)
print(f"HASIL: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
