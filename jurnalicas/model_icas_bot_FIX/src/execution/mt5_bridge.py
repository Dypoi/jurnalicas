"""
========================================================================================
MODEL ICAS METATRADER 5 EXECUTION BRIDGE (EXNESS COMPLIANT - DYNAMIC TELEMETRY)
========================================================================================
- Automatic Symbol Detection (XAUUSDm, XAUUSD, GOLD, XAUUSD.m, etc.)
- Adaptive Order Filling Mode (Auto FOK / IOC / RETURN Fallback)
- Real-time Live Candle Streaming directly from MT5 Terminal
- Live Closed Deals & Orders History Stream (history_deals_get)
- Strict Mutex Lock (1 Signal 1 Position)
- Smart SL Modification with Redundancy Protection (Prevents 10025 "No changes" error)
- Partial Close Execution (TP1 30%, TP2 25%, TP3 25%) with Settlement Delay Buffer
========================================================================================
"""
import logging
import time
import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from config import config

logger = logging.getLogger("IcasMT5Bridge")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False
    logger.info("MetaTrader5 package not available in this environment. Operating in Mock/Simulation mode.")

class IcasMT5Bridge:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self.connected = False
        self.resolved_symbol = cfg.SYMBOL
        self.active_position = None
        self.magic_number = 777404 # Unique identifier for Model Icas
        self.simulated_trades_history = []

    def initialize(self) -> bool:
        if not MT5_AVAILABLE:
            logger.info("MT5 Bridge running in Simulation / Live Bridge Relay mode.")
            self.connected = True
            return True

        init_kwargs = {}
        if self.cfg.MT5_PATH:
            init_kwargs["path"] = self.cfg.MT5_PATH

        if not mt5.initialize(**init_kwargs):
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            self.connected = False
            return False

        if self.cfg.MT5_LOGIN > 0 and self.cfg.MT5_PASSWORD:
            login_success = mt5.login(
                login=self.cfg.MT5_LOGIN,
                password=self.cfg.MT5_PASSWORD,
                server=self.cfg.MT5_SERVER
            )
            if not login_success:
                logger.error(f"MT5 login failed for account {self.cfg.MT5_LOGIN}: {mt5.last_error()}")
                self.connected = False
                return False

        self.resolve_symbol()
        self.connected = True
        logger.info(f"✅ MT5 Connected successfully! Broker Symbol: {self.resolved_symbol} | Server: {self.cfg.MT5_SERVER}")
        return True

    def resolve_symbol(self) -> str:
        if not MT5_AVAILABLE or not self.connected:
            return self.cfg.SYMBOL

        candidates = [self.cfg.SYMBOL, "XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.m", "XAUUSD_i", "XAUUSD.s"]
        for sym in candidates:
            info = mt5.symbol_info(sym)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(sym, True)
                self.resolved_symbol = sym
                return sym
        return self.cfg.SYMBOL

    def get_filling_mode(self) -> int:
        """
        Detects broker supported order filling mode (FOK, IOC, or RETURN).
        Prevents 10030: Unsupported filling mode error on Exness accounts.
        """
        if not MT5_AVAILABLE or not self.connected:
            return 1 # IOC

        sym_info = mt5.symbol_info(self.resolved_symbol)
        if sym_info is None:
            return mt5.ORDER_FILLING_IOC

        fill_flags = sym_info.filling_mode
        if fill_flags & 1: # FOK
            return mt5.ORDER_FILLING_FOK
        elif fill_flags & 2: # IOC
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    def normalize_lot(self, requested_lot: float) -> float:
        if not MT5_AVAILABLE or not self.connected:
            return max(0.01, round(requested_lot, 2))

        sym_info = mt5.symbol_info(self.resolved_symbol)
        if sym_info is None:
            return max(0.01, round(requested_lot, 2))

        vol_min = sym_info.volume_min
        vol_max = sym_info.volume_max
        vol_step = sym_info.volume_step if sym_info.volume_step > 0 else 0.01

        lot = round(round(requested_lot / vol_step) * vol_step, 2)
        lot = max(vol_min, min(vol_max, lot))
        return lot

    def normalize_price(self, price: float) -> float:
        if not MT5_AVAILABLE or not self.connected:
            return round(price, 2)

        sym_info = mt5.symbol_info(self.resolved_symbol)
        digits = sym_info.digits if sym_info else 2
        return round(price, digits)

    def get_account_details(self) -> Dict[str, Any]:
        """
        Returns full live telemetry of the connected MT5 account.
        """
        if MT5_AVAILABLE and self.connected:
            acc = mt5.account_info()
            if acc is not None:
                trade_mode_str = "DEMO"
                if hasattr(mt5, "ACCOUNT_TRADE_MODE_REAL") and acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                    trade_mode_str = "REAL"
                elif hasattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST") and acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
                    trade_mode_str = "CONTEST"

                margin_level = round(acc.margin_level, 2) if acc.margin > 0 else 100.0

                return {
                    "connected": True,
                    "is_live_mt5": True,
                    "status_text": "TERHUBUNG KE BROKER (LIVE FEED) ✅",
                    "login": acc.login,
                    "name": acc.name if acc.name else f"Account #{acc.login}",
                    "server": acc.server if acc.server else self.cfg.MT5_SERVER,
                    "trade_mode": trade_mode_str,
                    "currency": acc.currency if acc.currency else "USD",
                    "leverage": f"1:{acc.leverage}",
                    "balance": round(acc.balance, 2),
                    "equity": round(acc.equity, 2),
                    "margin": round(acc.margin, 2),
                    "margin_free": round(acc.margin_free, 2),
                    "margin_level": margin_level,
                    "floating_pnl": round(acc.equity - acc.balance, 2)
                }

        return {
            "connected": True,
            "is_live_mt5": False,
            "status_text": "TERHUBUNG (SIMULASI / BRIDGE LIVE) ✅",
            "login": self.cfg.MT5_LOGIN if self.cfg.MT5_LOGIN > 0 else 88921045,
            "name": "Exness Trader Account",
            "server": self.cfg.MT5_SERVER if self.cfg.MT5_SERVER else "Exness-MT5Trial6",
            "trade_mode": "DEMO / LIVE BRIDGE",
            "currency": "USD",
            "leverage": "1:2000",
            "balance": round(self.cfg.INITIAL_CAPITAL, 2),
            "equity": round(self.cfg.INITIAL_CAPITAL, 2),
            "margin": 0.0,
            "margin_free": round(self.cfg.INITIAL_CAPITAL, 2),
            "margin_level": 100.0,
            "floating_pnl": 0.0
        }

    def get_account_balance(self) -> float:
        acc = self.get_account_details()
        return acc.get("balance", self.cfg.INITIAL_CAPITAL)

    def get_account_equity(self) -> Optional[float]:
        """Equity realtime (balance + floating). None bila tidak tersedia."""
        try:
            if MT5_AVAILABLE and self.connected:
                acc = mt5.account_info()
                if acc is not None:
                    return float(acc.equity)
        except Exception:
            pass
        return None

    def get_position_realized(self, ticket: int) -> Optional[Dict[str, Any]]:
        """
        [ENGINE v2] Total PnL TEREALISASI untuk sebuah tiket posisi, dihitung
        dari riwayat deal broker (termasuk semua partial close + komisi + swap).
        Dipakai jurnal untuk mencatat hasil posisi — baik yang tertutup saat
        daemon ON maupun yang tertutup SAAT daemon OFF (rekonsiliasi on/off).
        Return None bila riwayat tidak tersedia (mock/offline).
        """
        if not MT5_AVAILABLE or not self.connected:
            return None
        try:
            # [AUDIT FIX OFF-01] Normalisasi tiket ke int: StateStore menyimpan
            # tiket sebagai kunci string ("7001"), sedangkan MT5 deal.position_id
            # bertipe int64. Tanpa koersi ini, jalur rekonsiliasi offline tak
            # pernah menemukan deal -> PnL penutupan saat daemon OFF hilang.
            # (Tertangkap oleh verify_onoff_cycle.py, Fase C.)
            try:
                ticket_key = int(ticket)
            except (TypeError, ValueError):
                ticket_key = None
            date_from = datetime.datetime.now() - datetime.timedelta(days=30)
            date_to = datetime.datetime.now() + datetime.timedelta(days=1)
            deals = mt5.history_deals_get(date_from, date_to)
            if not deals:
                return None
            profit = swap = commission = 0.0
            n_out = 0
            first_t = last_t = None
            for d in deals:
                _pid = getattr(d, "position_id", 0)
                if ticket_key is not None:
                    if int(_pid) != ticket_key:
                        continue
                elif _pid != ticket:
                    continue
                if getattr(d, "entry", None) == getattr(mt5, "DEAL_ENTRY_OUT", 1) or \
                   getattr(d, "entry", None) == getattr(mt5, "DEAL_ENTRY_INOUT", 3):
                    n_out += 1
                    profit += float(getattr(d, "profit", 0.0))
                    swap += float(getattr(d, "swap", 0.0))
                    commission += float(getattr(d, "commission", 0.0))
                    t = getattr(d, "time", None)
                    if t:
                        first_t = t if first_t is None else min(first_t, t)
                        last_t = t if last_t is None else max(last_t, t)
            if n_out == 0:
                return None
            total = round(profit + swap + commission, 2)
            return {
                "realized_total": total,
                "deals_out": int(n_out),
                "closed_at_first": str(datetime.datetime.fromtimestamp(first_t)) if first_t else None,
                "closed_at_last": str(datetime.datetime.fromtimestamp(last_t)) if last_t else None,
                "result": "WIN" if total > 1.0 else ("SCRATCH" if total >= 0 else "LOSS"),
            }
        except Exception as e:
            logger.warning(f"get_position_realized gagal utk tiket {ticket}: {e}")
            return None

    def get_current_tick(self) -> Dict[str, float]:
        if not MT5_AVAILABLE or not self.connected:
            return {"bid": 3350.00, "ask": 3350.26, "spread": 26.0, "time": int(time.time())}
        
        tick = mt5.symbol_info_tick(self.resolved_symbol)
        if tick is None:
            return {"bid": 0.0, "ask": 0.0, "spread": 0.0, "time": int(time.time())}
        
        sym_info = mt5.symbol_info(self.resolved_symbol)
        point = sym_info.point if sym_info else 0.01
        spread_points = (tick.ask - tick.bid) / point if point > 0 else 0.0
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round(spread_points, 1),
            "time": tick.time
        }

    def get_latest_m5_candles(self, count: int = 150) -> pd.DataFrame:
        """
        Fetches live real-time M5 candles directly from MT5 terminal.
        """
        if MT5_AVAILABLE and self.connected:
            rates = mt5.copy_rates_from_pos(self.resolved_symbol, mt5.TIMEFRAME_M5, 0, count)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                tick = self.get_current_tick()
                if tick["bid"] > 0 and len(df) > 0:
                    df.loc[df.index[-1], 'close'] = tick['bid']
                    df.loc[df.index[-1], 'high'] = max(df.loc[df.index[-1], 'high'], tick['bid'])
                    df.loc[df.index[-1], 'low'] = min(df.loc[df.index[-1], 'low'], tick['bid'])
                return df

        csv_path = "data/historical/xauusd_m5.csv"
        try:
            df = pd.read_csv(csv_path)
            df['time'] = pd.to_datetime(df['time'])
            return df.tail(count).reset_index(drop=True)
        except Exception:
            return pd.DataFrame()

    def get_live_deals_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Fetches closed deals history directly from MT5 broker terminal.
        """
        if MT5_AVAILABLE and self.connected:
            date_from = datetime.datetime.now() - datetime.timedelta(days=days)
            date_to = datetime.datetime.now() + datetime.timedelta(days=1)
            deals = mt5.history_deals_get(date_from, date_to)
            if deals is not None and len(deals) > 0:
                deals_list = []
                for d in reversed(deals):
                    if d.symbol == self.resolved_symbol and d.entry == mt5.DEAL_ENTRY_OUT: # Closed deal
                        d_time = datetime.datetime.fromtimestamp(d.time).strftime('%Y-%m-%d %H:%M')
                        pnl = round(d.profit + d.commission + d.swap, 2)
                        res_str = "WIN" if pnl >= 10.0 else ("BE" if pnl >= 0 else "LOSS")
                        deal_type = "BUY" if d.type == mt5.DEAL_TYPE_SELL else "SELL"
                        deals_list.append({
                            "time": d_time,
                            "type": deal_type,
                            # [DASH-04] position_id wajib dibawa: dashboard MENGGABUNGKAN
                            # deal-deal partial TP ke 1 tiket sebelum menghitung statistik.
                            "position_id": getattr(d, "position_id", 0),
                            "res": res_str,
                            "pnl": pnl,
                            "balance": round(d.profit, 2),
                            "max_fav": 0.0,
                            "tp1": True if pnl > 0 else False,
                            "tp2": False,
                            "tp3": False,
                            "be_set": True if res_str == "BE" else False,
                            "trail_step": 0
                        })
                if deals_list:
                    return deals_list

        return self.simulated_trades_history

    def _bot_positions(self):
        """Positions on our symbol opened by THIS bot only (magic number filter)."""
        positions = mt5.positions_get(symbol=self.resolved_symbol)
        if positions is None:
            return []
        return [p for p in positions if p.magic == self.magic_number]

    def has_open_positions(self) -> bool:
        if not MT5_AVAILABLE or not self.connected:
            return self.active_position is not None
        return len(self._bot_positions()) > 0

    def is_ticket_open(self, ticket) -> Optional[bool]:
        """[AUDIT FIX LIVE-01] Second opinion apakah sebuah tiket masih terbuka.
        True/False = MT5 menjawab pasti; None = gangguan IPC (JANGAN simpulkan
        apa-apa dan jangan hapus state). Pembeda True/None inilah yang mencegah
        'position closed' palsu saat positions_get miss transien."""
        try:
            tk = int(ticket)
        except (TypeError, ValueError):
            return None
        if not MT5_AVAILABLE or not self.connected:
            return True if (self.active_position or {}).get("ticket") == tk else None
        try:
            pos = mt5.positions_get(ticket=tk)
        except Exception:
            return None
        if pos is None:
            return None   # IPC bermasalah -> tidak diketahui
        return any(p.ticket == tk and p.magic == self.magic_number for p in pos)

    def get_open_position_details(self) -> Optional[Dict[str, Any]]:
        if not MT5_AVAILABLE or not self.connected:
            return self.active_position

        bot_positions = self._bot_positions()
        if len(bot_positions) == 0:
            self.active_position = None
            return None

        p = bot_positions[0]
        pos_type = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        
        if self.active_position is None or self.active_position.get("ticket") != p.ticket:
            self.active_position = {
                "ticket": p.ticket,
                "type": pos_type,
                "volume": p.volume,
                "initial_volume": p.volume,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "be_set": False,
                "max_fav": 0.0,
                "trail_step": 0,
                "_fresh": True   # [AUDIT FIX LIVE-01] daemon WAJIB merge ulang state
            }
        else:
            self.active_position["volume"] = p.volume
            self.active_position["sl"] = p.sl
            self.active_position["profit"] = p.profit

        return self.active_position

    def send_order(self, order_type: str, lot_size: float, sl_price: float, tp_price: Optional[float] = None) -> Optional[int]:
        if self.has_open_positions():
            logger.warning("Order rejected by Mutex Lock: Another position is already active.")
            return None

        tick = self.get_current_tick()
        if tick["spread"] > self.cfg.MAX_SPREAD_POINTS:
            logger.warning(f"Order rejected: Spread ({tick['spread']:.1f} pts) exceeds maximum allowable ({self.cfg.MAX_SPREAD_POINTS} pts).")
            return None

        norm_lot = self.normalize_lot(lot_size)
        norm_sl = self.normalize_price(sl_price)
        norm_tp = self.normalize_price(tp_price) if tp_price is not None and tp_price > 0 else 0.0

        if not MT5_AVAILABLE or not self.connected:
            ticket = int(time.time())
            price = tick["ask"] if order_type == "BUY" else tick["bid"]
            self.active_position = {
                "ticket": ticket,
                "type": order_type,
                "volume": norm_lot,
                "initial_volume": norm_lot,
                "price_open": price,
                "sl": norm_sl,
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "be_set": False,
                "max_fav": 0.0,
                "trail_step": 0
            }
            logger.info(f"[SIMULATED MT5] Order Placed: {order_type} {norm_lot} Lots @ {price:.2f} | SL: {norm_sl:.2f} | Ticket: {ticket}")
            return ticket

        m_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick["ask"] if order_type == "BUY" else tick["bid"]
        primary_filling = self.get_filling_mode()

        # --- Pre-validation vs stops level (prevents 10016 on the ENTRY itself) ---
        min_gap = self.get_min_stop_distance()
        if order_type == "BUY":
            sl_ok = norm_sl <= 0.0 or (price - norm_sl) >= min_gap * 0.8
        else:
            sl_ok = norm_sl <= 0.0 or (norm_sl - price) >= min_gap * 0.8
        if not sl_ok:
            logger.error(f"❌ Entry ditolak: SL {norm_sl:.2f} terlalu dekat dengan harga eksekusi "
                         f"{price:.2f} (min gap {min_gap:.2f}). Tunggu spread menyempit.")
            return None

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.resolved_symbol,
            "volume": norm_lot,
            "type": m_type,
            "price": price,
            "sl": norm_sl,
            "deviation": 50,
            "magic": self.magic_number,
            "comment": "Model Icas Scalper",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": primary_filling,
        }
        if norm_tp > 0:
            request["tp"] = norm_tp

        res = mt5.order_send(request)

        if res is not None and res.retcode == 10030:
            logger.warning(f"Filling mode {primary_filling} rejected. Retrying with fallback modes...")
            for fallback_fill in [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
                if fallback_fill == primary_filling: continue
                request["type_filling"] = fallback_fill
                res = mt5.order_send(request)
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    break

        if res is None:
            logger.error(f"❌ MT5 order_send returned None: {mt5.last_error()}")
            return None

        if res.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ MT5 order_send failed: retcode={res.retcode} ({res.comment})")
            return None

        logger.info(f"🚀 MT5 ORDER EXECUTED! Ticket: {res.order} | {order_type} {norm_lot} lots @ {res.price:.2f} | SL: {norm_sl:.2f}")
        return res.order

    def get_point(self) -> float:
        """Nilai point simbol ($/point): 0.01 utk XAUUSD 2-digit, 0.001 utk XAUUSDm 3-digit."""
        if not MT5_AVAILABLE or not self.connected:
            return 0.01
        sym_info = mt5.symbol_info(self.resolved_symbol)
        p = getattr(sym_info, "point", 0.01) if sym_info else 0.01
        return p if p and p > 0 else 0.01

    def get_min_stop_distance(self) -> float:
        """
        Minimum legal distance (in USD price) between current price and a new SL.
        Combines broker SYMBOL_TRADE_STOPS_LEVEL + current spread + safety buffer.
        Prevents retcode 10016 (Invalid stops) on Exness during wide spreads.
        """
        if not MT5_AVAILABLE or not self.connected:
            return 0.20  # Simulation fallback: $0.20 safety gap

        sym_info = mt5.symbol_info(self.resolved_symbol)
        if sym_info is None:
            return 0.50

        point = sym_info.point if sym_info.point > 0 else 0.01
        stops_level_pts = max(0, getattr(sym_info, "trade_stops_level", 0) or 0)

        tick = mt5.symbol_info_tick(self.resolved_symbol)
        spread_pts = 0.0
        if tick is not None and point > 0:
            spread_pts = max(0.0, (tick.ask - tick.bid) / point)

        # Stop level + current spread + 20 points hard buffer
        min_dist = (max(stops_level_pts, spread_pts) + 20.0) * point
        return round(min_dist, 6)

    def _validate_sl_side(self, pos_type: int, ticket: int, norm_sl: float) -> Tuple[bool, str]:
        """
        Validates that the requested SL is on the legal side of the market
        with at least get_min_stop_distance() clearance. Prevents 10016.
        """
        tick = mt5.symbol_info_tick(self.resolved_symbol)
        if tick is None:
            return False, "No live tick available; deferring SL modification"

        min_gap = self.get_min_stop_distance()
        if pos_type == mt5.POSITION_TYPE_BUY:
            ref = tick.bid
            if norm_sl >= ref - min_gap:
                return False, (f"Deferred: SL {norm_sl:.2f} too close/above market "
                               f"(Bid {ref:.2f}, min gap {min_gap:.2f})")
        else:
            ref = tick.ask
            if norm_sl <= ref + min_gap:
                return False, (f"Deferred: SL {norm_sl:.2f} too close/below market "
                               f"(Ask {ref:.2f}, min gap {min_gap:.2f})")
        return True, "OK"

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        norm_sl = self.normalize_price(new_sl)

        if not MT5_AVAILABLE or not self.connected:
            if self.active_position and self.active_position.get("ticket") == ticket:
                if abs(self.active_position.get("sl", 0.0) - norm_sl) < 1e-4:
                    return True
                self.active_position["sl"] = norm_sl
                logger.info(f"[SIMULATED MT5] SL Modified for Ticket {ticket} -> New SL: {norm_sl:.2f}")
                return True
            return False

        pos = mt5.positions_get(ticket=ticket)
        if pos is None or len(pos) == 0:
            return False

        p = pos[0]
        if abs(p.sl - norm_sl) < 0.005:
            return True  # Redundancy guard: avoids 10025 "No changes"

        # --- HARD GUARD vs 10016 (Invalid stops): never send an SL that is
        # on the wrong side of the market or inside the broker stop level ---
        side_ok, side_msg = self._validate_sl_side(p.type, ticket, norm_sl)
        if not side_ok:
            logger.info(f"⏳ SL modify not sent (ticket {ticket}): {side_msg}")
            return False

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": self.resolved_symbol,
            "sl": norm_sl,
            "tp": p.tp
        }
        res = mt5.order_send(request)

        if res is None:
            logger.warning(f"⚠️ order_send returned None while modifying SL for ticket {ticket}: {mt5.last_error()}")
            return False

        if res.retcode == mt5.TRADE_RETCODE_DONE or res.retcode == 10025:
            logger.info(f"🛡️ SL Successfully Updated for Ticket {ticket}: New SL = {norm_sl:.2f}")
            return True

        if res.retcode == 10016:
            # One last defensive log; should be unreachable after the side guard above
            logger.warning(f"⏳ 10016 on ticket {ticket} despite validation -> will retry next poll "
                           f"(SL {norm_sl:.2f}); broker comment: {res.comment}")
            return False

        logger.warning(f"Notice on modifying SL for ticket {ticket}: code {res.retcode} ({res.comment})")
        return False

    def infer_position_state(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        """
        [AUDIT FIX S-03] Rebuild status TP/BE/trailing untuk posisi yang sedang
        berjalan dari riwayat deal MT5 — dipakai saat daemon restart dan file
        state lokal hilang/korup.

        Logika: hitung deal OUT dengan comment 'Model Icas Partial TP' milik
        position_id tiket ini -> 1 partial = TP1, 2 = TP2, 3 = TP3.
        be_set/trail_step diinferensi dari jarak SL saat ini terhadap entry.
        """
        inferred: Dict[str, Any] = {}
        if not MT5_AVAILABLE or not self.connected:
            return inferred

        try:
            date_from = datetime.datetime.now() - datetime.timedelta(days=30)
            date_to = datetime.datetime.now() + datetime.timedelta(days=1)
            deals = mt5.history_deals_get(date_from, date_to)
            partials = 0
            if deals:
                for d in deals:
                    if getattr(d, "position_id", 0) == pos.get("ticket") and \
                       "Partial TP" in (getattr(d, "comment", "") or ""):
                        partials += 1
            inferred["tp1_hit"] = partials >= 1
            inferred["tp2_hit"] = partials >= 2
            inferred["tp3_hit"] = partials >= 3

            total_v = pos.get("volume", 0.01)
            ratio_done = (0.30 * int(partials >= 1)) + (0.25 * int(partials >= 2)) + (0.25 * int(partials >= 3))
            denom = max(1e-9, 1.0 - ratio_done)
            inferred["initial_volume"] = round(total_v / denom, 2) if partials else total_v

            sl_dist = (pos.get("sl", 0.0) - pos.get("price_open", 0.0))
            if pos.get("type") == "SELL":
                sl_dist = -sl_dist
            inferred["be_set"] = sl_dist > 0.0
            step_usd = self.cfg.TRAILING_STEP_PIPS * 0.10
            lock_usd = self.cfg.TRAILING_LOCK_PIPS * 0.10
            if sl_dist >= lock_usd + step_usd:
                inferred["trail_step"] = int((sl_dist - lock_usd) // step_usd) + 1
                if pos.get("type") == "BUY":
                    inferred["max_fav"] = max(sl_dist, pos.get("max_fav", 0.0))
                else:
                    inferred["max_fav"] = max(sl_dist, pos.get("max_fav", 0.0))
            inferred["_source"] = "mt5_deals"
            logger.info(f"♻️ State tiket {pos.get('ticket')} direbuild dari riwayat deal: "
                        f"partials={partials} (TP1:{inferred['tp1_hit']} TP2:{inferred['tp2_hit']} "
                        f"TP3:{inferred['tp3_hit']}) be_set:{inferred['be_set']} trail:{inferred.get('trail_step', 0)}")
        except Exception as e:
            logger.warning(f"Gagal rebuild state dari riwayat deal: {e}")
        return inferred

    def close_partial(self, ticket: int, close_volume: float) -> bool:
        norm_close_vol = self.normalize_lot(close_volume)

        if not MT5_AVAILABLE or not self.connected:
            if self.active_position and self.active_position.get("ticket") == ticket:
                self.active_position["volume"] = max(0.0, round(self.active_position["volume"] - norm_close_vol, 2))
                logger.info(f"[SIMULATED MT5] Partial Close: Closed {norm_close_vol:.2f} lots | Remaining: {self.active_position['volume']:.2f} lots")
                return True
            return False

        pos = mt5.positions_get(ticket=ticket)
        if not pos or len(pos) == 0:
            return False

        p = pos[0]
        actual_close_vol = min(p.volume, norm_close_vol)
        if actual_close_vol <= 0:
            return False

        tick = self.get_current_tick()
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick["bid"] if p.type == mt5.POSITION_TYPE_BUY else tick["ask"]
        fill_mode = self.get_filling_mode()

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": self.resolved_symbol,
            "volume": actual_close_vol,
            "type": close_type,
            "price": price,
            "deviation": 50,
            "magic": self.magic_number,
            "comment": "Model Icas Partial TP",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill_mode,
        }
        res = mt5.order_send(request)

        if res is not None and res.retcode == 10030:
            for fallback_fill in [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
                if fallback_fill == fill_mode: continue
                request["type_filling"] = fallback_fill
                res = mt5.order_send(request)
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    break

        if res is None:
            logger.error(f"❌ order_send returned None during partial close of ticket {ticket}: {mt5.last_error()}")
            return False

        if res.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ Failed partial close for ticket {ticket}: {res.comment}")
            return False

        logger.info(f"🎯 Partial Close Executed: Ticket {ticket} closed {actual_close_vol:.2f} lots")
        time.sleep(0.15)
        return True
