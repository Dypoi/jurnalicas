"""
================================================================================
E2E: DAEMON NYATA (icas_daemon.main) vs MOCK MT5 yang PUTUS DI TENGAH POSISI
================================================================================
[AUDIT FORENSIK 2 Sep 2026] Reproduksi insiden 2 Sep 10:04-15:20 WIB:
posisi SELL 5025658205 terbuka, lalu koneksi MT5 mati 5 jam.

Skenario mock (per siklus loop):
  siklus 0-2   : sehat, posisi SELL berjalan, fav kecil (< TP1)
  siklus 3-8   : PUTUS TOTAL — tick None, positions_get None, account_info None,
                 terminal_info None (persis kondisi insiden)
  siklus 9+    : pulih (reconnect berhasil), fav masih kecil
  siklus 14    : KeyboardInterrupt (hentikan daemon dgn rapi)

Yang HARUS terjadi (engine v2-d):
  • TIDAK ADA order_send apa pun selama putus (dulu: TP1/TP2/TP3 + modify SL
    beruntun karena bid=0 -> fav 43.000 pips).
  • Daemon TIDAK mati (tidak ada engine_stop exception); jurnal mencatat
    mt5_disconnected 1x dan mt5_reconnected 1x.
  • Tidak ada equity_snapshot dengan balance 10000 palsu.
  • State file posisi tetap ada (tidak dihapus sebagai 'closed' palsu).
  • Setelah pulih, posisi dikelola lagi (state di-merge ulang) tanpa TP palsu.
"""
import sys
import os
import json
import types
import time
import tempfile
import shutil
from collections import namedtuple

import numpy as np

# ------------------------------------------------------------ mock MT5 ------
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
                 DEAL_TYPE_BUY=0).items():
    setattr(mock, k, v)

EP = 4297.533
TICKET = 5025658205
S = {"cycle": 0, "sent": [], "phase_log": [], "now": 1788000000}

def phase():
    c = S["cycle"]
    if c < 3:
        return "healthy"
    if c < 9:
        return "down"
    return "recovered"

def symbol_info(sym): return SymInfo(0.001, 3, 0.01, 200.0, 0.01, True, 2, 0, 0)
def symbol_info_tick(sym):
    if phase() == "down":
        return None
    return Tick(EP - 1.0, EP - 0.74, S["now"])          # SELL fav +$0.74 (7 pips) -> jauh < TP1
def positions_get(*a, **kw):
    if phase() == "down":
        return None
    p = Position(TICKET, 1, 0.33, EP, EP + 15.0, 0.0, 24.0, 777404)
    if "ticket" in kw:
        return (p,) if kw["ticket"] == TICKET else ()
    return (p,)
def account_info():
    if phase() == "down":
        return None
    return AccInfo(88921045, "Demo", "Exness-MT5Trial6", 0, "USD", 2000, 9155.73, 9179.73, 100.0, 9079.73, 9179.0)
def terminal_info():
    if phase() == "down":
        return None
    return TermInfo(True, True)
def copy_rates_from_pos(sym, tf, start, count):
    if phase() == "down":
        return None
    t0 = S["now"] - 300 * count
    return np.array([(t0 + 300 * i, EP, EP + 0.5, EP - 0.5, EP, 100, 260, 0) for i in range(count)],
                    dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                           ("tick_volume", "i8"), ("spread", "i8"), ("real_volume", "i8")])
def order_send(req):
    S["sent"].append((S["cycle"], phase(), dict(req)))
    return TradeResult(10009, "Done", 1, 0.0, 1, 0.0)
def initialize(**kw):
    return phase() != "down"
def shutdown(): pass
def login(**kw): return True
def last_error(): return (1, "mock")
def symbol_select(s, v): return True
def history_deals_get(a, b): return ()

for fn in (symbol_info, symbol_info_tick, positions_get, account_info, terminal_info, copy_rates_from_pos,
           order_send, initialize, shutdown, login, last_error, symbol_select, history_deals_get):
    setattr(mock, fn.__name__, fn)
sys.modules["MetaTrader5"] = mock

# --------------------------------------------- lingkungan terisolasi ---------
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.chdir(ROOT)
from config import config
config.STATE_FILE = os.path.join(tmp, "icas_state.json")
config.JOURNAL_FILE = os.path.join(tmp, "trade_journal.jsonl")
config.POLL_INTERVAL_SECONDS = 0
config.RECONNECT_BACKOFF_SECONDS = (0, 0, 0)
config.JOURNAL_EQUITY_SNAPSHOT_SECONDS = 0   # snapshot tiap siklus agar terlihat
import icas_daemon

# time.sleep di daemon -> hitung siklus & hentikan pada siklus 14
_real_sleep = time.sleep
def fake_sleep(sec):
    S["cycle"] += 1
    S["phase_log"].append(phase())
    if S["cycle"] >= 15:
        raise KeyboardInterrupt()
icas_daemon.time.sleep = fake_sleep

import logging
logging.getLogger().setLevel(logging.ERROR)

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    PASS += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name)

print("=" * 78)
print(" E2E DAEMON: posisi SELL terbuka, MT5 putus total 6 siklus, lalu pulih")
print("=" * 78)
crashed = None
try:
    icas_daemon.main()
except KeyboardInterrupt:
    pass
except Exception as e:
    crashed = e
finally:
    icas_daemon.time.sleep = _real_sleep

events = []
with open(config.JOURNAL_FILE, encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if ln:
            events.append(json.loads(ln))
evc = {}
for e in events:
    evc[e["event"]] = evc.get(e["event"], 0) + 1
print(f"  siklus berjalan: {S['cycle']} | fase: {''.join('H' if p=='healthy' else ('D' if p=='down' else 'R') for p in S['phase_log'])}")
print(f"  event jurnal   : {evc}")

check("daemon TIDAK crash (tidak ada exception ke luar main)", crashed is None)
check("engine_stop tercatat dengan reason keyboard_interrupt (bukan exception)",
      any(e["event"] == "engine_stop" and e.get("reason") == "keyboard_interrupt" for e in events))
sent_down = [s for s in S["sent"] if s[1] == "down"]
check(f"TIDAK ADA order_send selama putus (dulu TP1/2/3 + SL beruntun) -> {len(sent_down)} order", len(sent_down) == 0)
check(f"TIDAK ADA order_send sama sekali (fav 7 pips < TP1) -> total {len(S['sent'])}", len(S["sent"]) == 0)
check("jurnal: mt5_disconnected tercatat tepat 1x", evc.get("mt5_disconnected", 0) == 1)
check("jurnal: mt5_reconnected tercatat 1x", evc.get("mt5_reconnected", 0) == 1)
check("jurnal: TIDAK ADA tp_hit / be_lock / trail_update palsu",
      evc.get("tp_hit", 0) == 0 and evc.get("be_lock", 0) == 0 and evc.get("trail_update", 0) == 0)
check("jurnal: TIDAK ADA position_closed palsu", evc.get("position_closed", 0) == 0 and evc.get("position_closed_offline", 0) == 0)
snaps = [e for e in events if e["event"] == "equity_snapshot"]
check("equity_snapshot: tidak ada balance 10000.0 palsu",
      all(e.get("balance") != 10000.0 for e in snaps))
check("equity_snapshot: ada yang connected=True dengan balance akun nyata 9155.73",
      any(e.get("balance") == 9155.73 for e in snaps))
with open(config.STATE_FILE, encoding="utf-8") as f:
    st = json.load(f)
check("state file: posisi 5025658205 MASIH tersimpan (tidak dihapus sebagai closed palsu)",
      str(TICKET) in st.get("positions", {}))
check("state file: max_fav wajar (< $2), bukan ribuan dollar",
      float(st["positions"][str(TICKET)].get("max_fav", 0.0)) < 2.0)
disc = next((e for e in events if e["event"] == "mt5_disconnected"), None)
check("mt5_disconnected membawa open_ticket posisi yang sedang dikelola",
      disc is not None and disc.get("open_ticket") == TICKET)

shutil.rmtree(tmp, ignore_errors=True)
print("\n" + "=" * 78)
print(f" HASIL: {PASS} PASS / {FAIL} FAIL")
print("=" * 78)
sys.exit(0 if FAIL == 0 else 1)
