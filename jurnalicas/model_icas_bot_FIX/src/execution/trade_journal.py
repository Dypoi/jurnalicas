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

Jenis event yang dicatat daemon:
  engine_start / engine_stop        — siklus hidup + snapshot config lengkap
  equity_snapshot                   — telemetri modal berkala (observasi kurva)
  signal_detected                   — sinyal lolos filter (sebelum order)
  order_open / order_failed         — hasil eksekusi entry
  tp_hit (level 1-3)                — partial close tier TP
  be_lock                           — SL terkunci profit (jika BE+ aktif)
  trail_update                      — trailing runner naik
  position_adopted                  — daemon ON menemukan posisi lama (on/off!)
  position_closed                   — posisi tertutup saat daemon ON
  position_closed_offline           — posisi tertutup SAAT daemon OFF (rekonsiliasi)

Analisis: python3 research/journal_report.py
================================================================================
"""
import json
import os
import threading
import datetime
from typing import Any, Dict


class TradeJournal:
    """Penulis jurnal JSONL yang fail-safe (tidak pernah raise ke daemon)."""

    def __init__(self, path: str = "logs/trade_journal.jsonl", enabled: bool = True,
                 engine_version: str = "unknown"):
        self.path = path
        self.enabled = enabled
        self.engine_version = engine_version
        self._lock = threading.Lock()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        except OSError:
            self.enabled = False

    # ------------------------------------------------------------------
    def log(self, event: str, **fields: Any) -> None:
        """Tulis satu baris JSON. Selalu senyap bila gagal."""
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
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass  # prinsip: jurnal tidak boleh mengganggu eksekusi trading

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
        )
        snap = {}
        for k in keys:
            try:
                snap[k] = getattr(cfg, k, None)
            except Exception:
                snap[k] = None
        return snap
