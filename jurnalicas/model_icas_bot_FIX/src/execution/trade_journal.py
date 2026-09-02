"""
================================================================================
MODEL ICAS — TRADE JOURNAL (JSONL) untuk observasi engine v2
================================================================================
[DITAMBAHKAN 25 Agu 2026 — permintaan pengguna: "siapkan JSON agar perjalanan
trading engine baru selama seminggu bisa diobservasi"]

Format: JSON Lines (1 event per baris) di logs/trade_journal.jsonl
  • Append-only → aman terhadap crash/matikan mendadak (laptop on/off).
  • Tiap event berstempel waktu ISO lokal + field bebas sesuai jenis event.
  • Semua penulisan dibungkus try/except — jurnal TIDAK PERNAH boleh
    mematikan daemon trading.

[AUDIT FORENSIK 2 — 02 Sep 2026]
  F-08: Kegagalan tulis TIDAK lagi senyap. `error_count` & `last_error`
        dipelihara dan bisa dibaca dashboard/operator; peringatan dicetak sekali
        saat gagal pertama dan sekali saat pulih.
  F-15: Rotasi otomatis saat file melewati JOURNAL_MAX_BYTES.

Jenis event yang dicatat daemon:
  engine_start / engine_stop        — siklus hidup + snapshot config lengkap
  equity_snapshot                   — telemetri modal berkala (observasi kurva)
  signal_detected                   — sinyal lolos filter (sebelum order)
  order_open / order_failed         — hasil eksekusi entry
  tp_hit (level 1-3)                — partial close tier TP
  be_lock                           — SL terkunci profit (jika BE+ aktif)
  trail_update                      — trailing runner naik
  position_adopted                  — daemon ON menemukan posisi lama (on/off!)
  position_revived                  — [F-03] tiket "tutup" ternyata masih hidup
  position_closed                   — posisi tertutup saat daemon ON
  position_closed_offline           — posisi tertutup SAAT daemon OFF (rekonsiliasi)
  feed_invalid / cycle_error        — [F-04/F-06] gangguan koneksi & ketahanan

Analisis: python3 research/journal_report.py
================================================================================
"""
import json
import os
import logging
import threading
import datetime
from typing import Any, Dict

logger = logging.getLogger("TradeJournal")


class TradeJournal:
    """Penulis jurnal JSONL yang fail-safe (tidak pernah raise ke daemon)."""

    def __init__(self, path: str = "logs/trade_journal.jsonl", enabled: bool = True,
                 engine_version: str = "unknown", max_bytes: int = 0,
                 keep_rotated: int = 5):
        self.path = path
        self.enabled = enabled
        self.engine_version = engine_version
        self.max_bytes = int(max_bytes or 0)
        self.keep_rotated = int(keep_rotated or 0)
        self._lock = threading.Lock()
        # [F-08] telemetri kesehatan jurnal
        self.error_count = 0
        self.last_error: str = ""
        self.written_count = 0
        self._degraded = False
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        except OSError as e:
            self.enabled = False
            self.error_count += 1
            self.last_error = f"makedirs gagal: {e}"
            logger.error(f"❌ [JURNAL] tidak bisa membuat direktori jurnal: {e}")

    # ------------------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        """[F-08] Status penulis jurnal — ditampilkan di dashboard /api/status."""
        return {
            "enabled": self.enabled,
            "path": self.path,
            "written_count": self.written_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "degraded": self._degraded,
        }

    # ------------------------------------------------------------------
    def log(self, event: str, **fields: Any) -> None:
        """Tulis satu baris JSON. Selalu senyap bila gagal (tapi TERHITUNG)."""
        if not self.enabled:
            return
        try:
            rec: Dict[str, Any] = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "engine_version": self.engine_version,
                "event": event,
            }
            rec.update(fields)
            line = json.dumps(rec, ensure_ascii=False, default=str)
            with self._lock:
                self._maybe_rotate(len(line) + 1)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
            self.written_count += 1
            if self._degraded:                     # [F-08] pulih
                self._degraded = False
                logger.info("✅ [JURNAL] penulisan jurnal pulih kembali.")
        except Exception as e:
            # prinsip: jurnal tidak boleh mengganggu eksekusi trading —
            # TETAPI kegagalan harus terlihat, tidak boleh senyap total.
            self.error_count += 1
            self.last_error = f"{type(e).__name__}: {e}"
            if not self._degraded:
                self._degraded = True
                logger.error(f"❌ [JURNAL] gagal menulis ke {self.path}: {self.last_error} "
                             f"— observasi berhenti, eksekusi trading tetap jalan.")

    # ------------------------------------------------------------------
    def _maybe_rotate(self, incoming_bytes: int) -> None:
        """[F-15] Rotasi sederhana: file -> .1 -> .2 ... (dipanggil dalam lock)."""
        if self.max_bytes <= 0:
            return
        try:
            size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        except OSError:
            return
        if size + incoming_bytes <= self.max_bytes:
            return
        try:
            oldest = f"{self.path}.{self.keep_rotated}"
            if self.keep_rotated > 0 and os.path.exists(oldest):
                os.remove(oldest)
            for i in range(self.keep_rotated - 1, 0, -1):
                src, dst = f"{self.path}.{i}", f"{self.path}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            if os.path.exists(self.path):
                os.replace(self.path, f"{self.path}.1")
            logger.info(f"🗂️ [JURNAL] rotasi: {self.path} -> {self.path}.1 "
                        f"(batas {self.max_bytes} bytes)")
        except OSError as e:
            logger.warning(f"[JURNAL] rotasi gagal (lanjut menulis): {e}")

    # ------------------------------------------------------------------
    @staticmethod
    def config_snapshot(cfg) -> Dict[str, Any]:
        """Snapshot parameter penting — dibawa oleh event engine_start."""
        keys = (
            "SYMBOL", "TIMEFRAME", "RISK_PER_TRADE_PCT", "USE_COMPOUNDING",
            "STOP_LOSS_PIPS", "EARLY_BE_TRIGGER_PIPS", "BE_PROFIT_OFFSET_PIPS",
            "TP1_PIPS", "TP1_LOT_RATIO", "TP2_PIPS", "TP2_LOT_RATIO",
            "TP3_PIPS", "TP3_LOT_RATIO", "RUNNER_LOT_RATIO",
            "TRAILING_STEP_PIPS", "TRAILING_LOCK_PIPS",
            "USE_KILLZONE", "MAX_SPREAD_POINTS",
            "INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK", "SLIPPAGE_USD",
            "MAX_TRADES_PER_DAY", "MAX_CONSECUTIVE_LOSSES",
            # [AUDIT FORENSIK 2] parameter ketahanan ikut disnapshot
            "POSITION_MISS_LIMIT", "CLOSE_REQUIRE_BROKER_PROOF",
            "MAX_TICK_AGE_SECONDS", "REQUIRE_VALID_TICK",
            "TP_TRIGGER_ON_CURRENT_PRICE", "RESILIENT_CYCLE",
        )
        snap = {}
        for k in keys:
            try:
                snap[k] = getattr(cfg, k, None)
            except Exception:
                snap[k] = None
        return snap
