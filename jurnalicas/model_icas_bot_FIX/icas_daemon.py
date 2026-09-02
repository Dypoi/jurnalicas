"""
========================================================================================
MODEL ICAS AUTONOMOUS LIVE TRADING DAEMON (4-TIER MULTI-TP & GUARANTEED PROFIT BE+)
========================================================================================
Pair: XAUUSD (Gold) | Broker: Exness | Framework: Pure Standalone Model Icas
ENGINE BARU v2 "SWING-150" (kalibrasi grid walk-forward 25 Agu 2026):
  SL 150p | TP 187.5/375/562.5p | Early BE+ DIMATIKAN | Killzone NONAKTIF (24 jam)
  + Jurnal observasi JSONL (logs/trade_journal.jsonl)
  + Rekonsiliasi on/off laptop (adopsi posisi lama, tutup-offline dari deal broker)
========================================================================================
"""
import time
import logging
import datetime
import pandas as pd
from config import config
from src.execution.mt5_bridge import IcasMT5Bridge
from src.execution.trade_journal import TradeJournal
from src.strategy.icas_strategy import ModelIcasStrategy
from src.indicators.sessions import calculate_session_killzones, is_current_in_burst
from src.state_store import StateStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("IcasDaemon")


def _journal_close(journal: TradeJournal, bridge: IcasMT5Bridge, ticket, context: str,
                   extra: dict = None) -> None:
    """Catat penutupan posisi ke jurnal; PnL direkonsiliasi dari deal broker bila bisa."""
    # [AUDIT FIX LIVE-01] Riwayat deal broker bisa telat beberapa detik setelah
    # posisi tertutup; coba ulang sebentar agar realized_total tidak kosong.
    info = None
    for _att in range(3):
        try:
            info = bridge.get_position_realized(ticket)
        except Exception:
            info = None
        if info:
            break
        time.sleep(0.7)
    payload = {"ticket": ticket, "context": context}
    if info:
        payload.update(info)
    if extra:
        payload.update(extra)
    journal.log("position_closed" if context == "online" else "position_closed_offline", **payload)
    if info:
        logger.info(f"🧾 Jurnal: tiket {ticket} closed ({context}) -> realized ${info['realized_total']:+,.2f} "
                    f"({info['result']}, {info['deals_out']} deal OUT)")
    else:
        logger.info(f"🧾 Jurnal: tiket {ticket} closed ({context}) -> PnL tidak tersedia (riwayat deal kosong)")


def main():
    logger.info("=" * 80)
    logger.info(f"   🚀 MODEL ICAS LIVE DAEMON — ENGINE BARU: {getattr(config, 'ENGINE_VERSION', 'v2')}")
    logger.info("=" * 80)
    logger.info(f"• Simbol Target     : {config.SYMBOL} (M5 Timeframe)")
    logger.info(f"• Risk per Trade    : {config.RISK_PER_TRADE_PCT*100:.1f}% (No Layering / 1 Signal 1 Position)")
    logger.info(f"• Initial Stop Loss : {config.STOP_LOSS_PIPS:.1f} pips (${config.STOP_LOSS_PIPS*0.10:.2f})")
    if config.EARLY_BE_TRIGGER_PIPS >= 9999:
        logger.info(f"• Early BE+ Trigger : DIMATIKAN (kalibrasi 25 Agu 2026) — exit full via TP tier/trailing runner")
    else:
        _be_dist = config.EARLY_BE_TRIGGER_PIPS * 0.10
        logger.info(f"• Early BE+ Trigger : +{config.EARLY_BE_TRIGGER_PIPS:.1f} pips (${_be_dist:.2f}) -> Lock Profit BE+ (+{config.BE_PROFIT_OFFSET_PIPS*0.10:.2f})")
    logger.info(f"• 4-Tier Multi-TP   : TP1 +{config.TP1_PIPS:.0f}p (30%) | TP2 +{config.TP2_PIPS:.0f}p (25%) | TP3 +{config.TP3_PIPS:.0f}p (25% & SL ke TP1)")
    logger.info(f"• TP Open Trailing  : Step {config.TRAILING_STEP_PIPS:.0f}p / Lock {config.TRAILING_LOCK_PIPS:.0f}p (20% Runner)")

    kz_status_str = "ICT KILLZONE (London 14:00-16:00 & NY 19:30-21:30 WIB)" if config.USE_KILLZONE else "24 JAM FULL MARKET (Killzone NONAKTIF sesuai permintaan)"
    logger.info(f"• Mode Sesi         : {kz_status_str}")
    logger.info("=" * 80 + "\n")

    bridge = IcasMT5Bridge(config)
    if not bridge.initialize():
        logger.error("Gagal menginisialisasi MT5 Bridge. Periksa koneksi MT5 Anda.")
        return

    # Jurnal observasi JSONL — kehadirannya diverifikasi pengguna di engine_start
    journal = TradeJournal(getattr(config, "JOURNAL_FILE", "logs/trade_journal.jsonl"),
                           getattr(config, "JOURNAL_ENABLED", True),
                           getattr(config, "ENGINE_VERSION", "v2"))
    strategy = ModelIcasStrategy(config)

    # [AUDIT FIX S-03] Persistensi state: pulihkan counter harian & siapkan store
    state_store = StateStore(config.STATE_FILE)
    today_str = str(datetime.datetime.now().date())
    last_day_str = today_str
    restored_daily = state_store.get_daily(today_str)
    if restored_daily["daily_trades_count"] > 0:
        strategy.daily_trades_count = restored_daily["daily_trades_count"]
        strategy.current_date = datetime.datetime.now().date()
        logger.info(f"♻️ Counter harian dipulihkan dari state store: {restored_daily['daily_trades_count']} sinyal hari ini")
    merged_state_tickets = set()
    adopted_logged = set()
    # [AUDIT FIX LIVE-01] Satu pembacaan positions_get kosong TIDAK cukup untuk
    # menyatakan posisi tertutup (gangguan transien MT5 -> None/()). Butuh
    # POSITION_MISS_LIMIT miss berurutan per tiket.
    pending_misses = {}
    POSITION_MISS_LIMIT = 5

    # -------------------- [ENGINE v2] STARTUP RECONCILIATION (on/off laptop) ----
    # Jurnal siklus hidup + snapshot config — bukti config yang benar-benar dipakai.
    try:
        _bal0 = bridge.get_account_balance()
    except Exception:
        _bal0 = None
    journal.log("engine_start",
                symbol=config.SYMBOL, timeframe=config.TIMEFRAME,
                killzone_active=bool(config.USE_KILLZONE),
                balance=_bal0, equity=bridge.get_account_equity(),
                state_file=config.STATE_FILE, journal_file=journal.path,
                config=TradeJournal.config_snapshot(config))

    # (a) Rekonsiliasi tiket yg tertutup SAAT daemon OFF: masih ada di state store,
    #     tapi broker bilang sudah tidak terbuka -> jurnal + bersihkan state.
    try:
        open_pos_now = bridge.get_open_position_details()
        open_ticket_now = str(open_pos_now["ticket"]) if open_pos_now else None
        for t in state_store.list_position_tickets():
            if open_ticket_now is not None and str(t) == open_ticket_now:
                continue  # masih terbuka -> akan diadopsi di loop
            logger.info(f"🔎 Rekonsiliasi: tiket {t} tidak lagi terbuka -> anggap tertutup saat daemon OFF")
            _journal_close(journal, bridge, t, context="offline")
            state_store.clear_position(t)
    except Exception as e:
        logger.warning(f"Rekonsiliasi startup gagal (tidak fatal): {e}")

    # (b) Adopsi posisi yang masih terbuka (sisa sesi sebelumnya)
    if open_pos_now is not None:
        logger.info(f"♻️ ADOPSI: posisi {open_pos_now['ticket']} ({open_pos_now['type']} {open_pos_now['volume']} lot @ {open_pos_now['price_open']}) masih terbuka dari sesi sebelumnya — manajemen dilanjutkan.")

    if config.USE_KILLZONE:
        logger.info("Bot aktif dalam mode ICT Killzone. Memantau sesi London / NY Burst...")
    else:
        logger.info("Bot aktif dalam mode 24 JAM FULL MARKET. Memantau seluruh sesi secara kontinu...")

    last_scanned_bar_time = None
    last_position_ticket = None
    last_pos_snapshot = None
    last_heartbeat_time = 0
    last_equity_snap_time = time.time()
    last_cycle_end = time.time()   # [AUDIT FIX LIVE-01] watchdog stall MT5 IPC
    price_point = bridge.get_point()   # digit-aware: 0.01 (2-digit) atau 0.001 (XAUUSDm 3-digit)
    logger.info(f"• Price Point       : {price_point} USD/point (spread USD = points x point)")
    eq_snap_secs = int(getattr(config, "JOURNAL_EQUITY_SNAPSHOT_SECONDS", 900))
    logger.info(f"• Jurnal JSON       : {journal.path} ('{'AKTIF' if journal.enabled else 'NONAKTIF'}', equity tiap {eq_snap_secs//60} menit)")

    try:
        while True:
            now_time = time.time()
            now_dt = datetime.datetime.now()
            _prev_daily_count = strategy.daily_trades_count  # [AUDIT FIX LIVE-01] rollover harus baca SEBELUM reset
            strategy.reset_daily_stats_if_new_day(now_dt.date())
            today_str = str(now_dt.date())
            if today_str != last_day_str:
                journal.log("day_rollover", closed_date=last_day_str,
                            signals_yesterday=_prev_daily_count)
                last_day_str = today_str

            # Periodic Heartbeat Log every 60 seconds
            if now_time - last_heartbeat_time >= 60:
                last_heartbeat_time = now_time
                tick = bridge.get_current_tick()
                has_pos = bridge.has_open_positions()
                logger.info(f"[HEARTBEAT] Sesi: {kz_status_str} | Bid: {tick['bid']:.2f} | Spread: {tick['spread']:.1f} pts | Sinyal Hari Ini: {strategy.daily_trades_count} | Posisi Aktif: {1 if has_pos else 0}")

            # [ENGINE v2] Telemetri modal berkala untuk kurva observasi
            if now_time - last_equity_snap_time >= eq_snap_secs:
                last_equity_snap_time = now_time
                try:
                    journal.log("equity_snapshot",
                                balance=bridge.get_account_balance(),
                                equity=bridge.get_account_equity(),
                                floating_pnl=(pos["profit"] if (pos := bridge.get_open_position_details()) else 0.0),
                                daily_signals=strategy.daily_trades_count)
                except Exception:
                    pass

            # 1. Manage Active Position
            pos = bridge.get_open_position_details()
            if pos is not None:
                pending_misses.pop(pos["ticket"], None)   # [AUDIT FIX LIVE-01] posisi terlihat sehat
                last_position_ticket = pos["ticket"]
                last_pos_snapshot = dict(pos)

                # [AUDIT FIX S-03] Pulihkan state manajemen sekali per tiket
                # (urutan: file state -> rebuild dari riwayat deal MT5)
                # [AUDIT FIX LIVE-01] Bridge membuat ulang dict posisi (flag
                # "_fresh") setiap kali pembacaan posisi sempat miss -> dict
                # kembali default (tp1_hit=False, dst). State WAJIB dipulihkan
                # ulang dari file/deals, jika tidak TP1/trailing bisa menembak
                # dua kali (teramati di forward-live 27 Agu 2026).
                _fresh_dict = bool(pos.pop("_fresh", False))
                if _fresh_dict or pos["ticket"] not in merged_state_tickets:
                    _was_tracked = pos["ticket"] in merged_state_tickets
                    merged_state_tickets.add(pos["ticket"])
                    if state_store.merge_into(pos):
                        logger.info(f"♻️ State tiket {pos['ticket']} dipulihkan dari file (TP1:{pos.get('tp1_hit')} TP2:{pos.get('tp2_hit')} TP3:{pos.get('tp3_hit')} BE:{pos.get('be_set')} Trail:{pos.get('trail_step')})")
                        if pos["ticket"] not in adopted_logged:
                            adopted_logged.add(pos["ticket"])
                            journal.log("position_adopted", ticket=pos["ticket"], source="state_file",
                                        type=pos.get("type"), volume=pos.get("volume"),
                                        price_open=pos.get("price_open"),
                                        tp1_hit=pos.get("tp1_hit"), tp2_hit=pos.get("tp2_hit"),
                                        tp3_hit=pos.get("tp3_hit"), be_set=pos.get("be_set"),
                                        trail_step=pos.get("trail_step"))
                        elif _was_tracked:
                            journal.log("position_readopted", ticket=pos["ticket"], source="state_file",
                                        tp1_hit=pos.get("tp1_hit"), tp2_hit=pos.get("tp2_hit"),
                                        be_set=pos.get("be_set"), trail_step=pos.get("trail_step"))
                    elif getattr(config, 'STATE_RESTORE_FROM_DEALS', True):
                        inferred = bridge.infer_position_state(pos)
                        if inferred:
                            for k, v in inferred.items():
                                if not k.startswith("_"):
                                    pos[k] = v
                            if pos["ticket"] not in adopted_logged:
                                adopted_logged.add(pos["ticket"])
                                journal.log("position_adopted", ticket=pos["ticket"], source="mt5_deals",
                                            type=pos.get("type"), volume=pos.get("volume"),
                                            price_open=pos.get("price_open"),
                                            tp1_hit=pos.get("tp1_hit"), tp2_hit=pos.get("tp2_hit"),
                                            tp3_hit=pos.get("tp3_hit"), be_set=pos.get("be_set"),
                                            trail_step=pos.get("trail_step", 0))
                            elif _was_tracked:
                                journal.log("position_readopted", ticket=pos["ticket"], source="mt5_deals",
                                            tp1_hit=pos.get("tp1_hit"), trail_step=pos.get("trail_step"))

                tick = bridge.get_current_tick()
                cur_price = tick["bid"] if pos["type"] == "BUY" else tick["ask"]
                ep = pos["price_open"]
                sp_val = tick["spread"]

                # ================================================================
                # [FIXED - ROOT CAUSE 10016] Profit-lock offset untuk Early BE+.
                # BUG LAMA: be_offset = max(0.10, spread_usd + 0.30) -> saat spread
                # 260 pts, offset menjadi $2.90 PADAHAL trigger BE+ hanya $1.00.
                # Akibatnya SL ditempatkan MENEMBUS harga pasar -> MT5 menolak
                # dengan retcode 10016 (Invalid stops).
                # FIX: offset dikunci di (trigger_dist - $0.10 buffer) dan selalu
                # divalidasi terhadap harga pasar + broker stops level sebelum
                # perintah modifikasi dikirim.
                # ================================================================
                trigger_dist_usd = config.EARLY_BE_TRIGGER_PIPS * 0.10          # OFF: 9999 -> tak pernah trigger
                lock_target_usd = (sp_val * price_point) + (config.BE_PROFIT_OFFSET_PIPS * 0.10)
                be_offset = min(lock_target_usd,
                                max(config.BE_PROFIT_OFFSET_PIPS * 0.10, trigger_dist_usd - 0.10))
                min_gap = bridge.get_min_stop_distance()

                def sl_clearance_ok(sl_price: float) -> bool:
                    """True jika SL berada di sisi pasar yang sah dengan jarak aman."""
                    if pos["type"] == "BUY":
                        return (tick["bid"] - sl_price) >= min_gap
                    return (sl_price - tick["ask"]) >= min_gap

                # Calculate favorable excursion
                fav_usd = (cur_price - ep) if pos["type"] == "BUY" else (ep - cur_price)
                if fav_usd > pos.get("max_fav", 0.0):
                    pos["max_fav"] = fav_usd

                fav_pips = pos["max_fav"] * 10.0

                # 1A. Early BE+ Check (NONAKTIF pada engine v2: trigger 9999)
                if not pos.get("be_set", False) and fav_pips >= config.EARLY_BE_TRIGGER_PIPS:
                    new_sl = ep + be_offset if pos["type"] == "BUY" else ep - be_offset
                    if sl_clearance_ok(new_sl) and bridge.modify_sl(pos["ticket"], new_sl):
                        pos["be_set"] = True
                        logger.info(f"🛡️ Early BE+ Aktif pada Ticket {pos['ticket']}! SL dikunci di {new_sl:.2f} (Guaranteed Profit)")
                        journal.log("be_lock", ticket=pos["ticket"], trigger="early_be",
                                    new_sl=round(new_sl, 4), fav_pips=round(fav_pips, 1))
                    elif not sl_clearance_ok(new_sl):
                        logger.info(f"⏳ BE+ menunggu jarak aman dari harga pasar (target SL {new_sl:.2f}, gap min {min_gap:.2f})")

                # 1B. TP1 Check (+187.5 pips -> Close 30% lot)
                if not pos.get("tp1_hit", False) and fav_pips >= config.TP1_PIPS:
                    close_vol = round(pos["initial_volume"] * config.TP1_LOT_RATIO, 2)
                    if close_vol >= 0.01 and bridge.close_partial(pos["ticket"], close_vol):
                        pos["tp1_hit"] = True
                        logger.info(f"🎯 TP1 Hit (1.25xSL / +{config.TP1_PIPS:.0f} pips)! Closed {close_vol} lots ({config.TP1_LOT_RATIO*100:.0f}%) pada Ticket {pos['ticket']}")
                        journal.log("tp_hit", ticket=pos["ticket"], level=1, close_vol=close_vol,
                                    fav_pips=round(fav_pips, 1), remaining_vol=round(pos["initial_volume"] - close_vol, 2))
                        new_sl = ep + be_offset if pos["type"] == "BUY" else ep - be_offset
                        if sl_clearance_ok(new_sl) and bridge.modify_sl(pos["ticket"], new_sl):
                            pos["be_set"] = True
                            journal.log("be_lock", ticket=pos["ticket"], trigger="post_tp1",
                                        new_sl=round(new_sl, 4))

                # 1C. TP2 Check (+375 pips -> Close 25% lot)
                if pos.get("tp1_hit", False) and not pos.get("tp2_hit", False) and fav_pips >= config.TP2_PIPS:
                    close_vol = round(pos["initial_volume"] * config.TP2_LOT_RATIO, 2)
                    if close_vol >= 0.01 and bridge.close_partial(pos["ticket"], close_vol):
                        pos["tp2_hit"] = True
                        logger.info(f"🎯 TP2 Hit (2.5xSL / +{config.TP2_PIPS:.0f} pips)! Closed {close_vol} lots ({config.TP2_LOT_RATIO*100:.0f}%) pada Ticket {pos['ticket']}")
                        journal.log("tp_hit", ticket=pos["ticket"], level=2, close_vol=close_vol,
                                    fav_pips=round(fav_pips, 1))

                # 1D. TP3 Check (+562.5 pips -> Close 25% lot & Step SL to TP1)
                if pos.get("tp2_hit", False) and not pos.get("tp3_hit", False) and fav_pips >= config.TP3_PIPS:
                    close_vol = round(pos["initial_volume"] * config.TP3_LOT_RATIO, 2)
                    if close_vol >= 0.01 and bridge.close_partial(pos["ticket"], close_vol):
                        pos["tp3_hit"] = True
                        logger.info(f"🎯 TP3 Hit (3.75xSL / +{config.TP3_PIPS:.0f} pips)! Closed {close_vol} lots ({config.TP3_LOT_RATIO*100:.0f}%) pada Ticket {pos['ticket']}")
                        # Step SL to TP1
                        tp1_price = ep + (config.TP1_PIPS * 0.10) if pos["type"] == "BUY" else ep - (config.TP1_PIPS * 0.10)
                        if sl_clearance_ok(tp1_price) and bridge.modify_sl(pos["ticket"], tp1_price):
                            logger.info(f"🚀 SL Runner Otomatis Dinaikkan ke Level TP1: {tp1_price:.2f} (+{config.TP1_PIPS:.0f} pips Locked)!")
                            journal.log("sl_step_to_tp1", ticket=pos["ticket"], new_sl=round(tp1_price, 4))
                            pos["be_set"] = True
                        journal.log("tp_hit", ticket=pos["ticket"], level=3, close_vol=close_vol,
                                    fav_pips=round(fav_pips, 1), sl_moved_to_tp1=pos["be_set"])

                # 1E. Trailing Step for Runner beyond TP3 (Every 100 pips -> Lock 30 pips)
                k_step = int(fav_pips // config.TRAILING_STEP_PIPS)
                if k_step >= 1 and k_step > pos.get("trail_step", 0):
                    lock_dist = (k_step - 1) * (config.TRAILING_STEP_PIPS * 0.10) + (config.TRAILING_LOCK_PIPS * 0.10)
                    new_sl = ep + lock_dist if pos["type"] == "BUY" else ep - lock_dist
                    if sl_clearance_ok(new_sl) and bridge.modify_sl(pos["ticket"], new_sl):
                        pos["trail_step"] = k_step
                        logger.info(f"🚀 Trailing Runner Step {k_step} Aktif! SL dinaikkan ke {new_sl:.2f} (Lock profit +{lock_dist*10:.0f} pips)")
                        journal.log("trail_update", ticket=pos["ticket"], step=k_step,
                                    new_sl=round(new_sl, 4), lock_pips=round(lock_dist * 10.0, 1))

                # [AUDIT FIX S-03] Persist state posisi setiap siklus (atomik)
                state_store.save_position(pos)

            else:
                if last_position_ticket is not None:
                    # [AUDIT FIX LIVE-01] Jangan percaya satu pembacaan kosong:
                    # konfirmasi penutupan hanya setelah MISS_LIMIT miss urut.
                    _t = last_position_ticket
                    _st = bridge.is_ticket_open(_t)
                    if _st is True:
                        pending_misses.pop(_t, None)
                    elif _st is False:
                        pending_misses[_t] = pending_misses.get(_t, 0) + 1
                        if pending_misses[_t] == 1:
                            journal.log("position_miss_pending", ticket=_t)
                        logger.info(f"⏳ Tiket {_t} tidak terbaca MT5 (miss {pending_misses[_t]}/{POSITION_MISS_LIMIT}) — menunggu konfirmasi.")
                    # _st None = gangguan IPC -> tidak menambah, tidak mereset.
                    if pending_misses.get(_t, 0) >= POSITION_MISS_LIMIT:
                        logger.info(f"ℹ️ Posisi Ticket {_t} terkonfirmasi ditutup oleh MT5.")
                        _journal_close(journal, bridge, _t, context="online",
                                       extra={"tp1_hit": (last_pos_snapshot or {}).get("tp1_hit"),
                                              "tp2_hit": (last_pos_snapshot or {}).get("tp2_hit"),
                                              "tp3_hit": (last_pos_snapshot or {}).get("tp3_hit"),
                                              "trail_step": (last_pos_snapshot or {}).get("trail_step"),
                                              "max_fav_usd": (last_pos_snapshot or {}).get("max_fav")})
                        state_store.clear_position(_t)   # [AUDIT FIX S-03]
                        pending_misses.pop(_t, None)
                        last_position_ticket = None
                        last_pos_snapshot = None

                # 2. Scan Market for New Entry Signals (or Re-Entry)
                can_trade, reason = strategy.can_trade_today()
                if can_trade:
                    df_m5_raw = bridge.get_latest_m5_candles(count=150)
                    if not df_m5_raw.empty and len(df_m5_raw) >= 15:
                        df_m5 = calculate_session_killzones(df_m5_raw)
                        latest_bar_idx = len(df_m5) - 2 # Latest completed candle
                        latest_time = df_m5['time'].iloc[latest_bar_idx]

                        if latest_time != last_scanned_bar_time:
                            last_scanned_bar_time = latest_time
                            balance = bridge.get_account_balance()
                            spread_now = bridge.get_current_tick()
                            spread_usd_now = spread_now.get("spread", 0.0) * price_point
                            sig = strategy.evaluate_m5_setup(df_m5, latest_bar_idx, balance,
                                                             spread_usd=spread_usd_now)

                            if sig is not None:
                                logger.info(f"⚡ SINYAL TERDETEKSI: {sig.type} | Entry: {sig.entry_price:.2f} | SL: {sig.stop_loss:.2f} | TP1: {sig.tp1_price:.2f} | TP2: {sig.tp2_price:.2f} | TP3: {sig.tp3_price:.2f} | Lot: {sig.lot_size}")
                                journal.log("signal_detected", type=sig.type,
                                            entry=round(sig.entry_price, 4), sl=round(sig.stop_loss, 4),
                                            tp1=round(sig.tp1_price, 4), tp2=round(sig.tp2_price, 4),
                                            tp3=round(sig.tp3_price, 4), lot=sig.lot_size,
                                            spread_usd=round(spread_usd_now, 4), balance=round(balance, 2))
                                ticket = bridge.send_order(sig.type, sig.lot_size, sig.stop_loss, None)
                                if ticket is not None:
                                    strategy.daily_trades_count += 1
                                    state_store.save_daily(today_str, strategy.daily_trades_count,
                                                           strategy.consecutive_losses)   # [AUDIT FIX S-03]
                                    merged_state_tickets.add(ticket)
                                    adopted_logged.add(ticket)   # posisi baru sesi ini -> bukan adopsi
                                    logger.info(f"✅ Order Berhasil Dieksekusi di MT5! Ticket: {ticket} (Trade Hari Ini: {strategy.daily_trades_count})")
                                    journal.log("order_open", ticket=ticket, type=sig.type,
                                                lot=sig.lot_size, entry=round(sig.entry_price, 4),
                                                sl=round(sig.stop_loss, 4),
                                                daily_count=strategy.daily_trades_count)
                                else:
                                    logger.warning("❌ Order GAGAL dieksekusi MT5 — lihat log bridge di atas.")
                                    journal.log("order_failed", type=sig.type, lot=sig.lot_size,
                                                entry=round(sig.entry_price, 4), sl=round(sig.stop_loss, 4))

            _cycle_now = time.time()
            if _cycle_now - last_cycle_end > 120:
                logger.warning(f"⚠️ LOOP STALL {(_cycle_now - last_cycle_end)/60.0:.1f} menit — TP tier & trailing tidak berjalan selama jeda ini (SL tetap aman di broker).")
                journal.log("loop_stall_warning", gap_seconds=round(_cycle_now - last_cycle_end, 1))
            last_cycle_end = _cycle_now
            time.sleep(config.POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        journal.log("engine_stop", reason="keyboard_interrupt", open_ticket=last_position_ticket)
        logger.info("\nBot dihentikan oleh user. State & jurnal aman tersimpan. Sampai jumpa!")
    except Exception as e:
        journal.log("engine_stop", reason=f"exception: {type(e).__name__}: {e}",
                    open_ticket=last_position_ticket)
        logger.exception("Daemon berhenti karena exception tak terduga.")
        raise


if __name__ == '__main__':
    main()
