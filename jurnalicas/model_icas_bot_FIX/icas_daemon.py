"""
========================================================================================
MODEL ICAS AUTONOMOUS LIVE TRADING DAEMON (4-TIER MULTI-TP & GUARANTEED PROFIT BE+)
========================================================================================
Pair: XAUUSD (Gold) | Broker: Exness | Framework: Pure Standalone Model Icas
ENGINE BARU v2 "SWING-150" (kalibrasi grid walk-forward 25 Agu 2026):
  SL 150p | TP 187.5/375/562.5p | Early BE+ DIMATIKAN | Killzone NONAKTIF (24 jam)
  + Jurnal observasi JSONL (logs/trade_journal.jsonl)
  + Rekonsiliasi on/off laptop (adopsi posisi lama, tutup-offline dari deal broker)

----------------------------------------------------------------------------------------
[AUDIT FORENSIK 2 — 02 Sep 2026] PERBAIKAN KETAHANAN ERROR / KONEKSI TERPUTUS
----------------------------------------------------------------------------------------
F-01  `open_pos_now` tidak lagi bisa memicu UnboundLocalError saat pembacaan posisi
      pertama gagal (daemon dulu mati seketika di startup).
F-02  Rekonsiliasi startup kini PROOF-GATED: tiket hanya dinyatakan tutup-offline
      bila terminal+feed sehat DAN riwayat broker membuktikan posisi lunas.
F-03  Penutupan posisi tidak lagi menghapus state. State dipindah ke tombstone dan
      bisa dipulihkan (position_revived) bila broker ternyata masih membuka posisi.
      -> memusnahkan bug TP1 dobel (jurnal produksi 27 Agu: 0.10 / 0.07 / 0.05 lot).
F-04  Guard feed: tick bid/ask 0 atau basi membuat SEMUA manajemen posisi & entry
      dilewati satu siklus (dulu: SELL + tick 0 -> fav $4600 -> TP1/2/3 + trail 46).
F-05  Partial close idempoten per tier (anti dobel-close saat ack order hilang).
F-06  Satu exception transien tidak lagi mematikan daemon (RESILIENT_CYCLE).
F-07  Pelacakan multi-tiket: penutupan tiket lama tetap dicatat walau posisi baru
      sudah terbuka (dulu event close-nya hilang total).
F-11  TP tier dipicu harga saat ini, bukan max_fav historis.
F-12  Partial close tidak lagi mandek saat lot hasil bagi < lot minimum broker.
F-16  consecutive_losses akhirnya diperbarui -> circuit breaker benar-benar hidup.
========================================================================================
"""
import os
import time
import json
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

LOT_EPS = 0.011   # toleransi 1 step lot


def _journal_close(journal: TradeJournal, bridge: IcasMT5Bridge, ticket, context: str,
                   extra: dict = None, attempts: int = 3) -> dict:
    """Catat penutupan posisi ke jurnal; PnL direkonsiliasi dari deal broker bila bisa.

    [AUDIT FIX LIVE-01] Riwayat deal broker bisa telat beberapa detik setelah
    posisi tertutup; coba ulang sebentar agar realized_total tidak kosong.
    Return dict info (mungkin kosong) supaya pemanggil bisa membedakan
    "bukti tutup ada" vs "riwayat kosong".
    """
    info = None
    for _att in range(max(1, attempts)):
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
        payload.update({k: v for k, v in extra.items() if v is not None})
    journal.log("position_closed" if context == "online" else "position_closed_offline", **payload)
    if info:
        logger.info(f"🧾 Jurnal: tiket {ticket} closed ({context}) -> realized ${info['realized_total']:+,.2f} "
                    f"({info['result']}, {info['deals_out']} deal OUT)")
    else:
        logger.info(f"🧾 Jurnal: tiket {ticket} closed ({context}) -> PnL tidak tersedia (riwayat deal kosong)")
    return info or {}


def _write_health_marker(path: str, journal_health: dict, bridge: IcasMT5Bridge,
                         open_tickets: list) -> None:
    """[F-08] Tulis penanda kesehatan daemon+jurnal agar dashboard (proses terpisah)
    bisa menampilkan apakah jurnal masih hidup dan apakah feed sehat."""
    if not path:
        return
    try:
        tick = bridge.get_current_tick()
        payload = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "engine_version": getattr(config, "ENGINE_VERSION", "v2"),
            "journal": journal_health,
            "feed_valid": bool(tick.get("valid", True)),
            "feed_reason": tick.get("reason", "ok"),
            "terminal_healthy": bridge.is_feed_healthy(),
            "open_tickets": [str(t) for t in open_tickets],
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass  # marker bersifat informatif, tidak boleh mengganggu daemon


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
                           getattr(config, "ENGINE_VERSION", "v2"),
                           max_bytes=getattr(config, "JOURNAL_MAX_BYTES", 0),
                           keep_rotated=getattr(config, "JOURNAL_KEEP_ROTATED", 5))
    strategy = ModelIcasStrategy(config)

    # [AUDIT FIX S-03] Persistensi state: pulihkan counter harian & siapkan store
    state_store = StateStore(config.STATE_FILE,
                             tombstone_keep=getattr(config, "CLOSED_TOMBSTONE_KEEP", 40))
    today_str = str(datetime.datetime.now().date())
    last_day_str = today_str
    restored_daily = state_store.get_daily(today_str)
    if restored_daily["daily_trades_count"] > 0:
        strategy.daily_trades_count = restored_daily["daily_trades_count"]
        strategy.current_date = datetime.datetime.now().date()
        logger.info(f"♻️ Counter harian dipulihkan dari state store: {restored_daily['daily_trades_count']} sinyal hari ini")
    if restored_daily["consecutive_losses"] > 0:
        strategy.consecutive_losses = restored_daily["consecutive_losses"]   # [F-16]
    merged_state_tickets = set()
    adopted_logged = set()
    # [F-07] Pelacakan MULTI-tiket. Dulu hanya satu `last_position_ticket`, sehingga
    # bila posisi baru terbuka sebelum tiket lama selesai dikonfirmasi, event
    # penutupan tiket lama HILANG permanen dari jurnal (terbukti pada tiket
    # 5009576843: tutup 31 Agu 09:50, baru tercatat 02 Sep 08:46 sebagai offline).
    open_tickets = {}          # ticket -> {"snapshot": dict, "misses": int}
    POSITION_MISS_LIMIT = int(getattr(config, "POSITION_MISS_LIMIT", 5))
    REQUIRE_PROOF = bool(getattr(config, "CLOSE_REQUIRE_BROKER_PROOF", True))
    REVIVE_WINDOW = int(getattr(config, "POSITION_REVIVE_WINDOW_SECONDS", 3600))
    MAX_PENDING_CLOSE = int(getattr(config, "MAX_PENDING_CLOSE_SECONDS", 900))

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

    # [F-01] Inisialisasi SEBELUM try — bug lama: bila pembacaan posisi pertama
    # melempar exception, baris `if open_pos_now is not None` memicu
    # UnboundLocalError dan daemon mati sebelum loop pertama.
    open_pos_now = None
    feed_ok_at_startup = False

    # (a) Rekonsiliasi tiket yg tertutup SAAT daemon OFF: masih ada di state store,
    #     tapi broker bilang sudah tidak terbuka -> jurnal + pindahkan ke tombstone.
    try:
        feed_ok_at_startup = bridge.is_feed_healthy()
        if feed_ok_at_startup:
            open_pos_now = bridge.get_open_position_details()
        else:
            logger.warning("⚠️ Terminal/feed MT5 belum sehat saat startup — "
                           "rekonsiliasi on/off DITUNDA (state tidak disentuh).")
            journal.log("startup_reconcile_deferred", reason="feed_unhealthy")
    except Exception as e:
        logger.warning(f"Pembacaan posisi saat startup gagal (tidak fatal): {e}")
        journal.log("startup_reconcile_deferred", reason=f"{type(e).__name__}: {e}")

    if feed_ok_at_startup:
        open_ticket_now = str(open_pos_now["ticket"]) if open_pos_now else None
        for t in state_store.list_position_tickets():
            if open_ticket_now is not None and str(t) == open_ticket_now:
                continue  # masih terbuka -> akan diadopsi di loop
            # ---- [F-02] gerbang bukti: jangan percaya satu pembacaan kosong ----
            status = bridge.is_ticket_open(t)
            if status is not False:
                logger.info(f"🔎 Rekonsiliasi: status tiket {t} tidak pasti "
                            f"({status}) -> state DIPERTAHANKAN, tunda konfirmasi.")
                journal.log("startup_reconcile_deferred", ticket=t,
                            reason="ticket_status_unknown")
                continue
            closed_vol = bridge.get_position_closed_volume(t) if REQUIRE_PROOF else None
            stored = state_store.get_position(t) or {}
            initial_vol = float(stored.get("initial_volume") or stored.get("volume") or 0.0)
            if REQUIRE_PROOF:
                if closed_vol is None:
                    logger.warning(f"🔎 Rekonsiliasi: riwayat deal tidak terbaca utk tiket {t} "
                                   f"-> state DIPERTAHANKAN.")
                    journal.log("startup_reconcile_deferred", ticket=t,
                                reason="history_unavailable")
                    continue
                if initial_vol > 0 and closed_vol + LOT_EPS < initial_vol:
                    logger.warning(f"🔎 Rekonsiliasi: tiket {t} baru tertutup {closed_vol:.2f} "
                                   f"dari {initial_vol:.2f} lot -> BUKAN tutup penuh, "
                                   f"state DIPERTAHANKAN.")
                    journal.log("startup_reconcile_deferred", ticket=t,
                                reason="partial_close_only",
                                closed_volume=closed_vol, initial_volume=initial_vol)
                    continue
            logger.info(f"🔎 Rekonsiliasi: tiket {t} terbukti tidak lagi terbuka -> "
                        f"tertutup saat daemon OFF")
            _journal_close(journal, bridge, t, context="offline")
            state_store.mark_closed(t, reason="offline_reconcile")   # [F-03]

    # (b) Adopsi posisi yang masih terbuka (sisa sesi sebelumnya)
    if open_pos_now is not None:
        logger.info(f"♻️ ADOPSI: posisi {open_pos_now['ticket']} ({open_pos_now['type']} {open_pos_now['volume']} lot @ {open_pos_now['price_open']}) masih terbuka dari sesi sebelumnya — manajemen dilanjutkan.")

    if config.USE_KILLZONE:
        logger.info("Bot aktif dalam mode ICT Killzone. Memantau sesi London / NY Burst...")
    else:
        logger.info("Bot aktif dalam mode 24 JAM FULL MARKET. Memantau seluruh sesi secara kontinu...")

    last_scanned_bar_time = None
    last_position_ticket = None
    last_heartbeat_time = 0
    last_equity_snap_time = time.time()
    last_cycle_end = time.time()   # [AUDIT FIX LIVE-01] watchdog stall MT5 IPC
    last_feed_warn = 0.0
    price_point = bridge.get_point()   # digit-aware: 0.01 (2-digit) atau 0.001 (XAUUSDm 3-digit)
    logger.info(f"• Price Point       : {price_point} USD/point (spread USD = points x point)")
    eq_snap_secs = int(getattr(config, "JOURNAL_EQUITY_SNAPSHOT_SECONDS", 900))
    logger.info(f"• Jurnal JSON       : {journal.path} ('{'AKTIF' if journal.enabled else 'NONAKTIF'}', equity tiap {eq_snap_secs//60} menit)")
    logger.info(f"• Ketahanan         : miss_limit={POSITION_MISS_LIMIT} proof={REQUIRE_PROOF} "
                f"resilient={getattr(config, 'RESILIENT_CYCLE', True)} "
                f"tick_max_age={getattr(config, 'MAX_TICK_AGE_SECONDS', 0)}s")

    consecutive_cycle_errors = 0
    MAX_CYCLE_ERRORS = int(getattr(config, "MAX_CONSECUTIVE_CYCLE_ERRORS", 20))

    try:
        while True:
          # ====================================================================
          # [F-06] Satu siklus dibungkus try/except: exception transien (IPC MT5,
          # pandas, dsb.) TIDAK boleh mematikan daemon dan meninggalkan posisi
          # tanpa manajemen TP/trailing.
          # ====================================================================
          try:
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
                _jh = journal.health()
                _write_health_marker(getattr(config, "JOURNAL_HEALTH_FILE", ""), _jh,
                                     bridge, list(open_tickets.keys()))
                logger.info(f"[HEARTBEAT] Sesi: {kz_status_str} | Bid: {tick['bid']:.2f} | Spread: {tick['spread']:.1f} pts | Sinyal Hari Ini: {strategy.daily_trades_count} | Posisi Aktif: {1 if has_pos else 0} | Feed: {'OK' if tick.get('valid') else tick.get('reason')} | Jurnal err: {_jh['error_count']}")

            # [ENGINE v2] Telemetri modal berkala untuk kurva observasi
            if now_time - last_equity_snap_time >= eq_snap_secs:
                last_equity_snap_time = now_time
                try:
                    _eq_pos = bridge.get_open_position_details()
                    journal.log("equity_snapshot",
                                balance=bridge.get_account_balance(),
                                equity=bridge.get_account_equity(),
                                floating_pnl=(_eq_pos["profit"] if _eq_pos else 0.0),
                                daily_signals=strategy.daily_trades_count,
                                journal_errors=journal.error_count)
                except Exception:
                    pass

            # ==================================================================
            # [F-04] GUARD FEED — satu pemeriksaan untuk seluruh siklus.
            # ==================================================================
            tick = bridge.get_current_tick()
            if getattr(config, "REQUIRE_VALID_TICK", True) and not tick.get("valid", True):
                if now_time - last_feed_warn >= 30:
                    last_feed_warn = now_time
                    logger.warning(f"⚠️ FEED TIDAK VALID ({tick.get('reason')}) — manajemen posisi, "
                                   f"TP tier, trailing, dan entry DILEWATI siklus ini. "
                                   f"SL Anda tetap aktif di sisi broker.")
                    journal.log("feed_invalid", reason=tick.get("reason"),
                                open_tickets=list(open_tickets.keys()))
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # 1. Manage Active Position
            pos = bridge.get_open_position_details()
            if pos is not None:
                open_tickets[pos["ticket"]] = {"snapshot": dict(pos), "misses": 0}
                last_position_ticket = pos["ticket"]

                # [AUDIT FIX S-03] Pulihkan state manajemen sekali per tiket
                # (urutan: file state -> tombstone -> rebuild dari riwayat deal MT5)
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
                        # [F-03] tiket ini pernah dinyatakan tutup -> revive
                        if pos.pop("_revived", False):
                            tomb = state_store.get_closed(pos["ticket"]) or {}
                            age = StateStore.closed_age_seconds(tomb)
                            if age is not None and age <= REVIVE_WINDOW:
                                logger.warning(f"🧟 REVIVE: tiket {pos['ticket']} dinyatakan tutup "
                                               f"{age:.0f}s lalu tetapi MASIH TERBUKA di broker — "
                                               f"state dipulihkan, TP tidak akan dobel.")
                                journal.log("position_revived", ticket=pos["ticket"],
                                            declared_closed_at=tomb.get("closed_at"),
                                            age_seconds=round(age, 1),
                                            tp1_hit=pos.get("tp1_hit"), tp2_hit=pos.get("tp2_hit"),
                                            tp3_hit=pos.get("tp3_hit"), trail_step=pos.get("trail_step"))
                            state_store.save_position(pos)
                            state_store.drop_closed(pos["ticket"])
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
                                            tp1_hit=pos.get("tp1_hit"), trail_step=pos.get("trail_step", 0))
                        elif _was_tracked:
                            # [F-03] kedua jalur pemulihan gagal. JANGAN pakai nilai
                            # default — pertahankan snapshot terakhir yang kita punya.
                            snap = (open_tickets.get(pos["ticket"]) or {}).get("snapshot") or {}
                            for k in ("tp1_hit", "tp2_hit", "tp3_hit", "be_set",
                                      "trail_step", "initial_volume", "max_fav", "closed_volume"):
                                if snap.get(k) is not None:
                                    pos[k] = snap[k]
                            logger.warning(f"⚠️ Pemulihan state tiket {pos['ticket']} gagal "
                                           f"(state file & riwayat deal kosong) — memakai "
                                           f"snapshot memori terakhir.")
                            journal.log("state_recovery_fallback", ticket=pos["ticket"],
                                        source="memory_snapshot",
                                        tp1_hit=pos.get("tp1_hit"), tp2_hit=pos.get("tp2_hit"),
                                        tp3_hit=pos.get("tp3_hit"), trail_step=pos.get("trail_step"))

                # [F-03] initial_volume tidak boleh menyusut jadi volume sisa
                _iv = pos.get("initial_volume")
                if not isinstance(_iv, (int, float)) or _iv <= 0 or _iv < pos.get("volume", 0.0):
                    pos["initial_volume"] = pos.get("volume", 0.0)

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
                # [F-11] TP tier memakai ekskursi SAAT INI. Dengan max_fav historis,
                # partial close bisa dieksekusi di harga yang jauh lebih buruk dari
                # level TP-nya (harga sudah balik arah, tetapi sisa max lama masih
                # di atas ambang). max_fav tetap dipakai untuk trailing.
                cur_fav_pips = fav_usd * 10.0
                tp_metric_pips = cur_fav_pips if getattr(config, "TP_TRIGGER_ON_CURRENT_PRICE", True) else fav_pips

                min_lot = bridge.get_min_lot()
                remaining_vol = float(pos.get("volume", 0.0) or 0.0)

                def _tier_volume(ratio: float) -> float:
                    """[F-12] Volume partial yg layak kirim: >= lot minimum broker,
                    tidak pernah melebihi sisa posisi."""
                    v = round(float(pos["initial_volume"]) * ratio, 2)
                    if v < min_lot:
                        v = min_lot
                    return round(min(v, remaining_vol), 2)

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
                if not pos.get("tp1_hit", False) and tp_metric_pips >= config.TP1_PIPS:
                    close_vol = _tier_volume(config.TP1_LOT_RATIO)
                    if close_vol > 0 and bridge.close_partial(pos["ticket"], close_vol, tier=1):
                        pos["tp1_hit"] = True
                        remaining_vol = round(remaining_vol - close_vol, 2)
                        pos["closed_volume"] = round(float(pos.get("closed_volume", 0.0)) + close_vol, 2)
                        logger.info(f"🎯 TP1 Hit (1.25xSL / +{config.TP1_PIPS:.0f} pips)! Closed {close_vol} lots ({config.TP1_LOT_RATIO*100:.0f}%) pada Ticket {pos['ticket']}")
                        journal.log("tp_hit", ticket=pos["ticket"], level=1, close_vol=close_vol,
                                    fav_pips=round(cur_fav_pips, 1), remaining_vol=remaining_vol)
                        new_sl = ep + be_offset if pos["type"] == "BUY" else ep - be_offset
                        if sl_clearance_ok(new_sl) and bridge.modify_sl(pos["ticket"], new_sl):
                            pos["be_set"] = True
                            journal.log("be_lock", ticket=pos["ticket"], trigger="post_tp1",
                                        new_sl=round(new_sl, 4))

                # 1C. TP2 Check (+375 pips -> Close 25% lot)
                if pos.get("tp1_hit", False) and not pos.get("tp2_hit", False) and tp_metric_pips >= config.TP2_PIPS:
                    close_vol = _tier_volume(config.TP2_LOT_RATIO)
                    if close_vol > 0 and bridge.close_partial(pos["ticket"], close_vol, tier=2):
                        pos["tp2_hit"] = True
                        remaining_vol = round(remaining_vol - close_vol, 2)
                        pos["closed_volume"] = round(float(pos.get("closed_volume", 0.0)) + close_vol, 2)
                        logger.info(f"🎯 TP2 Hit (2.5xSL / +{config.TP2_PIPS:.0f} pips)! Closed {close_vol} lots ({config.TP2_LOT_RATIO*100:.0f}%) pada Ticket {pos['ticket']}")
                        journal.log("tp_hit", ticket=pos["ticket"], level=2, close_vol=close_vol,
                                    fav_pips=round(cur_fav_pips, 1), remaining_vol=remaining_vol)

                # 1D. TP3 Check (+562.5 pips -> Close 25% lot & Step SL to TP1)
                if pos.get("tp2_hit", False) and not pos.get("tp3_hit", False) and tp_metric_pips >= config.TP3_PIPS:
                    close_vol = _tier_volume(config.TP3_LOT_RATIO)
                    if close_vol > 0 and bridge.close_partial(pos["ticket"], close_vol, tier=3):
                        pos["tp3_hit"] = True
                        remaining_vol = round(remaining_vol - close_vol, 2)
                        pos["closed_volume"] = round(float(pos.get("closed_volume", 0.0)) + close_vol, 2)
                        logger.info(f"🎯 TP3 Hit (3.75xSL / +{config.TP3_PIPS:.0f} pips)! Closed {close_vol} lots ({config.TP3_LOT_RATIO*100:.0f}%) pada Ticket {pos['ticket']}")
                        # Step SL to TP1
                        tp1_price = ep + (config.TP1_PIPS * 0.10) if pos["type"] == "BUY" else ep - (config.TP1_PIPS * 0.10)
                        if sl_clearance_ok(tp1_price) and bridge.modify_sl(pos["ticket"], tp1_price):
                            logger.info(f"🚀 SL Runner Otomatis Dinaikkan ke Level TP1: {tp1_price:.2f} (+{config.TP1_PIPS:.0f} pips Locked)!")
                            journal.log("sl_step_to_tp1", ticket=pos["ticket"], new_sl=round(tp1_price, 4))
                            pos["be_set"] = True
                        journal.log("tp_hit", ticket=pos["ticket"], level=3, close_vol=close_vol,
                                    fav_pips=round(cur_fav_pips, 1), sl_moved_to_tp1=pos["be_set"])

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

                # [AUDIT FIX S-03] Persist state posisi setiap siklus (atomik).
                # [F-14] StateStore kini melewati penulisan bila isi tidak berubah.
                state_store.save_position(pos)
                open_tickets[pos["ticket"]]["snapshot"] = dict(pos)

            # ==================================================================
            # [F-03/F-07] Konfirmasi penutupan — berlaku untuk SEMUA tiket yang
            # pernah terlihat, bukan hanya satu tiket terakhir.
            # ==================================================================
            visible_ticket = pos["ticket"] if pos is not None else None
            for tk in list(open_tickets.keys()):
                if tk == visible_ticket:
                    continue
                entry = open_tickets[tk]
                snap = entry.get("snapshot") or {}
                _st = bridge.is_ticket_open(tk)
                if _st is True:
                    entry["misses"] = 0
                    entry.pop("pending_since", None)      # [T-04] mutex aktif lagi
                    entry.pop("mutex_released", None)
                    continue
                if _st is None:
                    # IPC/terminal bermasalah -> tidak menambah, tidak mereset.
                    continue
                entry["misses"] = int(entry.get("misses", 0)) + 1
                if entry["misses"] == 1:
                    journal.log("position_miss_pending", ticket=tk)
                logger.info(f"⏳ Tiket {tk} tidak terbaca MT5 (miss {entry['misses']}/{POSITION_MISS_LIMIT}) — menunggu konfirmasi.")
                if entry["misses"] < POSITION_MISS_LIMIT:
                    continue

                # ---- [F-02/F-03] GERBANG BUKTI sebelum menyatakan tutup ----
                initial_vol = float(snap.get("initial_volume") or snap.get("volume") or 0.0)
                closed_vol = bridge.get_position_closed_volume(tk) if REQUIRE_PROOF else None
                if REQUIRE_PROOF:
                    if closed_vol is None:
                        logger.warning(f"🔎 Tiket {tk}: riwayat deal tidak terbaca — penutupan "
                                       f"BELUM dikonfirmasi, state DIPERTAHANKAN.")
                        journal.log("close_unconfirmed", ticket=tk, reason="history_unavailable")
                        entry["misses"] = 0
                        continue
                    if initial_vol > 0 and closed_vol + LOT_EPS < initial_vol:
                        logger.warning(f"🔎 Tiket {tk}: baru {closed_vol:.2f}/{initial_vol:.2f} lot "
                                       f"tertutup di riwayat broker — BUKAN tutup penuh, "
                                       f"state DIPERTAHANKAN.")
                        journal.log("close_unconfirmed", ticket=tk, reason="partial_close_only",
                                    closed_volume=closed_vol, initial_volume=initial_vol)
                        entry["misses"] = 0
                        continue

                logger.info(f"ℹ️ Posisi Ticket {tk} terkonfirmasi ditutup oleh MT5.")
                info = _journal_close(journal, bridge, tk, context="online",
                                      extra={"tp1_hit": snap.get("tp1_hit"),
                                             "tp2_hit": snap.get("tp2_hit"),
                                             "tp3_hit": snap.get("tp3_hit"),
                                             "trail_step": snap.get("trail_step"),
                                             "max_fav_usd": snap.get("max_fav")})
                state_store.mark_closed(tk, reason="online_confirmed")   # [F-03]
                open_tickets.pop(tk, None)
                if visible_ticket is None:
                    last_position_ticket = None
                # [F-16] circuit breaker akhirnya punya data
                _res = info.get("result")
                if _res == "LOSS":
                    strategy.consecutive_losses += 1
                elif _res in ("WIN", "SCRATCH"):
                    strategy.consecutive_losses = 0
                state_store.save_daily(today_str, strategy.daily_trades_count,
                                       strategy.consecutive_losses)

            # 2. Scan Market for New Entry Signals (or Re-Entry)
            # ==================================================================
            # [F-07/T-04] MUTEX SESUNGGUHNYA. `pos is None` saja TIDAK cukup:
            # saat IPC miss, bridge tidak melihat posisi apa pun padahal tiket
            # lama mungkin masih hidup. Selama masih ada tiket yang menunggu
            # konfirmasi tutup, entry BARU ditahan — inilah yang mencegah dua
            # posisi terbuka bersamaan (teramati di jurnal 31 Agu 09:50:50-51).
            # Katup pengaman: setelah MAX_PENDING_CLOSE_SECONDS penantian tanpa
            # kepastian, mutex dilepas agar bot tidak macet selamanya; tiket lama
            # tetap dilacak dan SL-nya tetap aktif di sisi broker.
            # ==================================================================
            _pending = [tk for tk in open_tickets if tk != visible_ticket]
            if _pending:
                _now = time.time()
                for tk in _pending:
                    open_tickets[tk].setdefault("pending_since", _now)
                    _waited = _now - open_tickets[tk]["pending_since"]
                    if _waited > MAX_PENDING_CLOSE and not open_tickets[tk].get("mutex_released"):
                        open_tickets[tk]["mutex_released"] = True
                        logger.warning(f"⚠️ Tiket {tk} sudah {_waited/60:.1f} menit menunggu "
                                       f"konfirmasi tutup tanpa kepastian dari broker — "
                                       f"mutex dilepas, entry baru diizinkan lagi.")
                        journal.log("mutex_released_stale", ticket=tk,
                                    waited_seconds=round(_waited, 1))
                _blocking = [tk for tk in _pending
                             if not open_tickets[tk].get("mutex_released")]
            else:
                _blocking = []

            if pos is None and not _blocking:
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
                                    # [F-17] harga fill NYATA + slippage terukur
                                    _f = getattr(bridge, "last_fill", None) or {}
                                    _fp = _f.get("price") or 0.0
                                    _slip = None
                                    if _fp:
                                        _slip = round((_fp - sig.entry_price)
                                                      if sig.type == "BUY"
                                                      else (sig.entry_price - _fp), 4)
                                        if abs(_slip) > 1.0:
                                            logger.warning(f"⚠️ Slippage entry {_slip:+.2f} USD "
                                                           f"({abs(_slip)*10:.0f} pips) — jauh di atas "
                                                           f"asumsi config ${config.SLIPPAGE_USD:.2f}.")
                                    journal.log("order_open", ticket=ticket, type=sig.type,
                                                lot=sig.lot_size, entry=round(sig.entry_price, 4),
                                                fill_price=round(_fp, 4) if _fp else None,
                                                slippage_usd=_slip,
                                                sl=round(sig.stop_loss, 4),
                                                daily_count=strategy.daily_trades_count)
                                else:
                                    logger.warning("❌ Order GAGAL dieksekusi MT5 — lihat log bridge di atas.")
                                    journal.log("order_failed", type=sig.type, lot=sig.lot_size,
                                                entry=round(sig.entry_price, 4), sl=round(sig.stop_loss, 4))

            consecutive_cycle_errors = 0
          except KeyboardInterrupt:
            raise
          except Exception as cyc_err:
            consecutive_cycle_errors += 1
            logger.exception(f"⚠️ Exception pada siklus daemon (#{consecutive_cycle_errors}) — "
                             f"daemon tetap jalan, posisi tetap dijaga SL broker.")
            journal.log("cycle_error", error=f"{type(cyc_err).__name__}: {cyc_err}",
                        consecutive=consecutive_cycle_errors,
                        open_tickets=list(open_tickets.keys()))
            if consecutive_cycle_errors >= MAX_CYCLE_ERRORS:
                logger.critical(f"🛑 {consecutive_cycle_errors} exception beruntun — daemon "
                                f"berhenti sadar agar tidak berputar tanpa kendali. "
                                f"SL posisi Anda tetap aktif di sisi broker.")
                journal.log("engine_stop", reason="too_many_cycle_errors",
                            consecutive=consecutive_cycle_errors,
                            open_ticket=last_position_ticket)
                raise

          _cycle_now = time.time()
          if _cycle_now - last_cycle_end > 120:
            logger.warning(f"⚠️ LOOP STALL {(_cycle_now - last_cycle_end)/60.0:.1f} menit — TP tier & trailing tidak berjalan selama jeda ini (SL tetap aman di broker).")
            journal.log("loop_stall_warning", gap_seconds=round(_cycle_now - last_cycle_end, 1))
          last_cycle_end = _cycle_now
          time.sleep(config.POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        journal.log("engine_stop", reason="keyboard_interrupt", open_ticket=last_position_ticket,
                    journal_errors=journal.error_count)
        logger.info("\nBot dihentikan oleh user. State & jurnal aman tersimpan. Sampai jumpa!")
    except Exception as e:
        journal.log("engine_stop", reason=f"exception: {type(e).__name__}: {e}",
                    open_ticket=last_position_ticket, journal_errors=journal.error_count)
        logger.exception("Daemon berhenti karena exception tak terduga.")
        raise


if __name__ == '__main__':
    main()
