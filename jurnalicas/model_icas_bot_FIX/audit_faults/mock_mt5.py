"""
================================================================================
AUDIT FORENSIK 2 — MOCK METATRADER5 DENGAN INJEKSI KEGAGALAN (FAULT INJECTION)
================================================================================
Mock MetaTrader5 yang bisa disuntik kegagalan, dipakai untuk mereproduksi bug
yang terjadi saat koneksi putus / error IPC / laptop sleep.

Mode kegagalan yang didukung (set via mock.faults):
  positions_none        -> positions_get() mengembalikan None   (IPC rusak)
  positions_empty       -> positions_get() mengembalikan ()     (terminal "no connection")
  tick_none             -> symbol_info_tick() mengembalikan None (feed mati)
  tick_zero             -> tick bid/ask = 0.0                    (feed busuk)
  history_raises        -> history_deals_get() melempar exception
  history_none          -> history_deals_get() mengembalikan None
  send_returns_none     -> order_send() mengembalikan None SETELAH order benar-benar
                           dieksekusi server (koneksi putus tepat sesudah kirim)
  send_retcode          -> order_send() mengembalikan retcode tertentu
  account_none          -> account_info() mengembalikan None

Semua state pasar bisa disetel: mock.bid / mock.ask / mock.positions / mock.deals
"""
import time
import types
from collections import namedtuple

TradeResult = namedtuple("TradeResult",
                         ["retcode", "comment", "order", "price", "deal", "volume"])
Tick = namedtuple("Tick", ["bid", "ask", "time", "flags"])
SymInfo = namedtuple("SymInfo", ["point", "digits", "volume_min", "volume_max",
                                 "volume_step", "visible", "filling_mode",
                                 "trade_stops_level", "trade_freeze_level"])
Position = namedtuple("Position", ["ticket", "type", "volume", "price_open",
                                   "sl", "tp", "profit", "magic"])
Deal = namedtuple("Deal", ["ticket", "position_id", "type", "entry", "volume",
                           "price", "profit", "commission", "swap", "time",
                           "symbol", "comment"])
Account = namedtuple("Account", ["login", "name", "server", "trade_mode", "currency",
                                 "leverage", "balance", "equity", "margin",
                                 "margin_free", "margin_level"])


class Faults:
    def __init__(self):
        self.reset()

    def reset(self):
        self.positions_none = False
        self.positions_empty = False
        self.tick_none = False
        self.tick_zero = False
        self.history_raises = False
        self.history_none = False
        self.send_returns_none = False
        self.send_retcode = None          # None = normal (10009)
        self.account_none = False
        self.send_drop_next = 0           # N order_send berikutnya "hilang"


def build(symbol="XAUUSDm", point=0.01, digits=2):
    """Bangun module MetaTrader5 palsu dan kembalikan (module, handle kontrol)."""
    m = types.ModuleType("MetaTrader5")

    # ---- konstanta API ----
    m.ORDER_TYPE_BUY = 0
    m.ORDER_TYPE_SELL = 1
    m.POSITION_TYPE_BUY = 0
    m.POSITION_TYPE_SELL = 1
    m.TRADE_ACTION_DEAL = 1
    m.TRADE_ACTION_SLTP = 6
    m.TRADE_RETCODE_DONE = 10009
    m.TRADE_RETCODE_INVALID_STOPS = 10016
    m.TRADE_RETCODE_INVALID_FILL = 10030
    m.ORDER_FILLING_FOK = 0
    m.ORDER_FILLING_IOC = 1
    m.ORDER_FILLING_RETURN = 2
    m.ORDER_TIME_GTC = 0
    m.TIMEFRAME_M5 = 5
    m.DEAL_ENTRY_IN = 0
    m.DEAL_ENTRY_OUT = 1
    m.DEAL_ENTRY_INOUT = 3
    m.DEAL_TYPE_BUY = 0
    m.DEAL_TYPE_SELL = 1
    m.ACCOUNT_TRADE_MODE_DEMO = 0
    m.ACCOUNT_TRADE_MODE_CONTEST = 1
    m.ACCOUNT_TRADE_MODE_REAL = 2

    # ---- state ----
    m.faults = Faults()
    m.symbol_name = symbol
    m.point = point
    m.digits = digits
    m.bid = 4600.00
    m.ask = 4600.26
    m.positions = []
    m.deals = []
    m.orders_sent = []          # audit trail: semua order_send yang benar-benar masuk
    m.balance = 10000.0
    m.equity = 10000.0
    m._next_ticket = 5000000000
    m._last_error = (-1, "mock ok")

    # ---- helpers ----
    def _sym_info(sym):
        if sym != m.symbol_name:
            return None
        return SymInfo(point=m.point, digits=m.digits, volume_min=0.01,
                       volume_max=200.0, volume_step=0.01, visible=True,
                       filling_mode=2, trade_stops_level=0, trade_freeze_level=0)

    def initialize(**kw):
        return True

    def login(**kw):
        return True

    def shutdown():
        return True

    def last_error():
        return m._last_error

    def symbol_select(sym, vis):
        return True

    def symbol_info(sym):
        return _sym_info(sym)

    def symbol_info_tick(sym):
        if m.faults.tick_none:
            return None
        if m.faults.tick_zero:
            return Tick(bid=0.0, ask=0.0, time=int(time.time()), flags=0)
        return Tick(bid=m.bid, ask=m.ask, time=int(time.time()), flags=0)

    def positions_get(*args, **kwargs):
        if m.faults.positions_none:
            return None
        if m.faults.positions_empty:
            return ()
        if "ticket" in kwargs:
            return tuple(p for p in m.positions if p.ticket == int(kwargs["ticket"]))
        if "symbol" in kwargs and kwargs["symbol"] != m.symbol_name:
            return ()
        return tuple(m.positions)

    def history_deals_get(date_from, date_to, **kw):
        if m.faults.history_raises:
            raise RuntimeError("IPC fault: history_deals_get failed")
        if m.faults.history_none:
            return None
        return tuple(m.deals)

    def account_info():
        if m.faults.account_none:
            return None
        return Account(login=88921045, name="Mock Trader", server="Exness-MT5Trial6",
                       trade_mode=m.ACCOUNT_TRADE_MODE_DEMO, currency="USD",
                       leverage=2000, balance=m.balance, equity=m.equity,
                       margin=0.0, margin_free=m.equity, margin_level=0.0)

    def copy_rates_from_pos(sym, tf, start, count):
        return None

    def _open_position(order_type, volume, price, sl, tp, magic, comment):
        tk = m._next_ticket
        m._next_ticket += 1
        ptype = m.POSITION_TYPE_BUY if order_type == m.ORDER_TYPE_BUY else m.POSITION_TYPE_SELL
        m.positions = list(m.positions) + [Position(
            ticket=tk, type=ptype, volume=round(volume, 2), price_open=price,
            sl=sl, tp=tp, profit=0.0, magic=magic)]
        m.deals = list(m.deals) + [Deal(
            ticket=tk, position_id=tk, type=order_type, entry=m.DEAL_ENTRY_IN,
            volume=round(volume, 2), price=price, profit=0.0, commission=0.0,
            swap=0.0, time=1767000000, symbol=m.symbol_name, comment=comment)]
        return tk

    def order_send(request):
        m.orders_sent = list(m.orders_sent) + [dict(request)]

        # injeksi: koneksi putus tepat sesudah order dieksekusi server
        drop = m.faults.send_drop_next
        if drop > 0:
            m.faults.send_drop_next = drop - 1
            if request["action"] == m.TRADE_ACTION_DEAL and "position" in request:
                _apply_partial(request)
            m._last_error = (-10, "IPC timeout")
            return None
        if m.faults.send_returns_none:
            m._last_error = (-10, "IPC timeout")
            return None

        if m.faults.send_retcode is not None:
            return TradeResult(m.faults.send_retcode, "injected", None, 0.0, 0, 0.0)

        if request["action"] == m.TRADE_ACTION_SLTP:
            # validasi sisi pasar ala server MT5 sungguhan
            pos = next((p for p in m.positions if p.ticket == request["position"]), None)
            if pos is None:
                return TradeResult(10013, "Invalid position", None, 0.0, 0, 0.0)
            if request["price"] if False else False:
                pass
            if pos.type == m.POSITION_TYPE_BUY and request["sl"] >= m.bid:
                return TradeResult(10016, "Invalid stops", None, 0.0, 0, 0.0)
            if pos.type == m.POSITION_TYPE_SELL and request["sl"] <= m.ask:
                return TradeResult(10016, "Invalid stops", None, 0.0, 0, 0.0)
            m.positions = [p._replace(sl=request["sl"]) if p.ticket == pos.ticket else p
                           for p in m.positions]
            return TradeResult(10009, "Done", 0, 0.0, 0, 0.0)

        # TRADE_ACTION_DEAL
        if "position" in request:
            return _apply_partial(request)

        price = request.get("price", 0.0)
        if price <= 0:
            return TradeResult(10020, "Invalid price", None, 0.0, 0, 0.0)
        tk = _open_position(request["type"], request["volume"], price,
                            request.get("sl", 0.0), request.get("tp", 0.0),
                            request.get("magic", 0), request.get("comment", ""))
        return TradeResult(10009, "Done", tk, price, tk, request["volume"])

    def _apply_partial(request):
        pid = request["position"]
        pos = next((p for p in m.positions if p.ticket == pid), None)
        if pos is None:
            return TradeResult(10013, "Invalid position", None, 0.0, 0, 0.0)
        vol = round(min(pos.volume, request["volume"]), 2)
        rem = round(pos.volume - vol, 2)
        close_type = request["type"]
        price = request.get("price", 0.0)
        if price <= 0:
            return TradeResult(10020, "Invalid price", None, 0.0, 0, 0.0)
        sign = 1.0 if close_type == m.ORDER_TYPE_SELL else -1.0
        pnl = round(sign * (price - pos.price_open) * vol * 100.0, 2)
        m.deals = list(m.deals) + [Deal(
            ticket=9_000_000_000 + len(m.deals), position_id=pid, type=close_type,
            entry=m.DEAL_ENTRY_OUT, volume=vol, price=price, profit=pnl,
            commission=0.0, swap=0.0, time=int(time.time()) + len(m.deals),
            symbol=m.symbol_name, comment=request.get("comment", ""))]
        if rem <= 0:
            m.positions = [p for p in m.positions if p.ticket != pid]
        else:
            m.positions = [p._replace(volume=rem) if p.ticket == pid else p
                           for p in m.positions]
        m.balance = round(m.balance + pnl, 2)
        m.equity = m.balance
        return TradeResult(10009, "Done", pid, price, pid, vol)

    m.initialize = initialize
    m.login = login
    m.shutdown = shutdown
    m.last_error = last_error
    m.symbol_select = symbol_select
    m.symbol_info = symbol_info
    m.symbol_info_tick = symbol_info_tick
    m.positions_get = positions_get
    m.history_deals_get = history_deals_get
    m.account_info = account_info
    m.copy_rates_from_pos = copy_rates_from_pos
    m.order_send = order_send

    return m
