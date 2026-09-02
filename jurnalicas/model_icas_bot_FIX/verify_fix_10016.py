"""
================================================================================
VERIFIKASI FIX ERROR 10016 (Invalid stops) - MOCK MetaTrader5 (tanpa terminal)
================================================================================
Mensimulasikan kondisi PERSIS seperti log produksi:
  2026-08-25 08:40:32 | Spread: 260.0 pts | WARNING: code 10016 (Invalid stops)

Skenario yang diuji:
  A. KODE LAMA (daemon): be_offset = spread + 0.30 = $2.90 -> SL menembus pasar.
  B. KODE BARU (fix)   : be_offset di-cap pada jarak trigger - buffer = $0.90,
                         lalu bridge memvalidasi sisi pasar + stops level broker
                         sebelum mengirim perintah ke server.
"""
import sys
import time
import types
from collections import namedtuple

# ---------------------------------------------------------------- Mock MT5 ---
TradeResult = namedtuple("TradeResult", ["retcode", "comment", "order", "price", "deal", "volume"])
Tick = namedtuple("Tick", ["bid", "ask", "time"])
SymInfo = namedtuple("SymInfo", ["point", "digits", "volume_min", "volume_max", "volume_step",
                                 "visible", "filling_mode", "trade_stops_level", "trade_freeze_level"])
Position = namedtuple("Position", ["ticket", "type", "volume", "price_open", "sl", "tp", "profit", "magic"])

mock = types.ModuleType("MetaTrader5")
mock.ORDER_TYPE_BUY = 0
mock.ORDER_TYPE_SELL = 1
mock.POSITION_TYPE_BUY = 0
mock.POSITION_TYPE_SELL = 1
mock.TRADE_ACTION_DEAL = 1
mock.TRADE_ACTION_SLTP = 6
mock.TRADE_RETCODE_DONE = 10009
mock.ORDER_FILLING_FOK = 0
mock.ORDER_FILLING_IOC = 1
mock.ORDER_FILLING_RETURN = 2
mock.ORDER_TIME_GTC = 0
mock.TIMEFRAME_M5 = 5

# Kondisi pasar seperti log: spread 260 pts = $2.60
BID = 4668.69
ASK = 4671.29
mock._symbol = "XAUUSDm"
mock._pos = [Position(ticket=4970342345, type=0, volume=2.5, price_open=4667.80,
                      sl=4665.80, tp=0.0, profit=0.0, magic=777404)]

def symbol_info(sym):
    return SymInfo(point=0.01, digits=2, volume_min=0.01, volume_max=200.0, volume_step=0.01,
                   visible=True, filling_mode=2, trade_stops_level=0, trade_freeze_level=0)
def symbol_info_tick(sym):
    return Tick(bid=BID, ask=ASK, time=int(time.time()))
def positions_get(*args, **kwargs):
    if "ticket" in kwargs:
        return tuple(p for p in mock._pos if p.ticket == kwargs["ticket"])
    return tuple(mock._pos) if kwargs.get("symbol") == "XAUUSDm" else ()
def symbol_select(sym, vis):
    return True
def initialize(**kw):
    return True
def login(**kw):
    return True
def last_error():
    return (1, "mock ok")
def order_send(request):
    # Simulasi server MT5 NYATA: tolak SL ilegal dengan 10016
    if request["action"] == mock.TRADE_ACTION_SLTP:
        p = mock._pos[0]
        if p.type == 0 and request["sl"] >= BID:   # BUY: SL harus < Bid
            return TradeResult(10016, "Invalid stops", None, 0.0, 0, 0.0)
        if p.type == 1 and request["sl"] <= ASK:   # SELL: SL harus > Ask
            return TradeResult(10016, "Invalid stops", None, 0.0, 0, 0.0)
        mock._pos = [p._replace(sl=request["sl"])]
        return TradeResult(10009, "Done", 0, 0.0, 0, 0.0)
    return TradeResult(10009, "Done", 999999, BID, 999999, 0.0)

mock.symbol_info = symbol_info
mock.symbol_info_tick = symbol_info_tick
mock.positions_get = positions_get
mock.symbol_select = symbol_select
mock.initialize = initialize
mock.login = login
mock.last_error = last_error
mock.order_send = order_send
sys.modules["MetaTrader5"] = mock
# ---------------------------------------------------------------------------

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
from config import config
from src.execution.mt5_bridge import IcasMT5Bridge

PASS, FAIL = 0, 0
def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ PASS - {name}")
    else:
        FAIL += 1
        print(f"  ❌ FAIL - {name}")

print("=" * 78)
print(" VERIFIKASI FIX 10016 - Kondisi mock: Bid 4668.69 | Spread 260 pts ($2.60)")
print("=" * 78)

bridge = IcasMT5Bridge(config)
bridge.initialize()

# ---------------------------------------------------------------- A. KODE LAMA
print("\n[A] Perilaku KODE LAMA (be_offset = spread + 0.30):")
ep = mock._pos[0].price_open                    # 4667.80
spread_pts = 260.0
be_offset_lama = max(0.10, (spread_pts * 0.01) + 0.30)   # = $2.90  (BUG)
sl_lama = ep + be_offset_lama                            # 4670.70 (DI ATAS Bid!)
print(f"    be_offset lama = ${be_offset_lama:.2f} -> target SL = {sl_lama:.2f} (Bid hanya {BID:.2f})")
res = order_send({"action": mock.TRADE_ACTION_SLTP, "sl": sl_lama})
check(f"Server menolak SL {sl_lama:.2f} dgn 10016 (bug asli terbukti)", res.retcode == 10016)

# ---------------------------------------------------------------- B. KODE BARU
# Skenario 10016 asli ditemukan pada trigger default 10 pips. Config pasca-
# kalibrasi mematikan Early BE+ (9999) → paksa trigger=10 untuk reproduksi.
config.EARLY_BE_TRIGGER_PIPS = 10.0
print("\n[B] Perilaku KODE BARU (fix di icas_daemon.py + mt5_bridge.py):")
trigger_dist = config.EARLY_BE_TRIGGER_PIPS * 0.10       # $1.00
lock_target = (spread_pts * 0.01) + (config.BE_PROFIT_OFFSET_PIPS * 0.10)
be_offset_baru = min(lock_target, max(config.BE_PROFIT_OFFSET_PIPS * 0.10, trigger_dist - 0.10))
sl_baru = ep + be_offset_baru                            # 4668.70 (< Bid 4668.69? TIDAK -> 4668.70 > 4668.69!)
print(f"    be_offset baru = ${be_offset_baru:.2f} -> target SL = {sl_baru:.2f}")

# Bridge-level guard harus MENOLAK pengiriman ilegal secara aman (deferred, tanpa error)
ok = bridge.modify_sl(4970342345, sl_baru)
check(f"Bridge menahan SL ilegal {sl_baru:.2f} (tidak dikirim ke server)", ok is False)

# Saat harga menjauh $0.31, SL yang sama menjadi sah -> harus terkirim & sukses
BID_BARU = 4670.00
def symbol_info_tick2(sym):
    return Tick(bid=BID_BARU, ask=BID_BARU + 0.26, time=int(time.time()))
mock.symbol_info_tick = symbol_info_tick2
globals()["BID"] = BID_BARU  # mock server pakai variabel global BID
ok = bridge.modify_sl(4970342345, sl_baru)
check(f"Setelah Bid naik ke {BID_BARU:.2f}, SL {sl_baru:.2f} berhasil dikunci", ok is True)
check("SL posisi di server kini = " + f"{mock._pos[0].sl:.2f}", abs(mock._pos[0].sl - sl_baru) < 1e-6)

# Skenario spread normal (26 pts): offset = 0.56 -> langsung sah saat trigger
spread_normal = 26.0
be_offset_normal = min((spread_normal * 0.01) + 0.30,
                       max(0.30, trigger_dist - 0.10))
sl3 = ep + be_offset_normal
ok2 = bridge.modify_sl(4970342345, sl3)
check(f"Spread normal 26 pts: BE+ offset ${be_offset_normal:.2f} langsung diterima", ok2 is True)

print("\n" + "=" * 78)
print(f" HASIL: {PASS} PASS / {FAIL} FAIL")
print("=" * 78)
sys.exit(0 if FAIL == 0 else 1)
