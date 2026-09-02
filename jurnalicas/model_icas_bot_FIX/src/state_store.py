"""
================================================================================
MODEL ICAS - PERSISTENT STATE STORE (Anti state-loss saat restart daemon)
================================================================================
[AUDIT FIX S-03] Menyimpan state posisi (tp1_hit/tp2_hit/tp3_hit/be_set/
trail_step/max_fav/initial_volume) dan counter harian ke file JSON secara
atomik (tmp-file + os.replace). Jika daemon di-restart di tengah posisi,
status partial TP & trailing dipulihkan sehingga TP1 TIDAK dieksekusi ganda.

Jika file state hilang, daemon merebuild status dari riwayat deal MT5
(lihat IcasMT5Bridge.infer_position_state).
================================================================================
"""
import json
import os
import threading
from typing import Dict, Any, Optional


class StateStore:
    """JSON state store dengan penulisan atomik dan kunci thread."""

    _POS_KEYS = (
        "tp1_hit", "tp2_hit", "tp3_hit", "be_set",
        "max_fav", "trail_step", "initial_volume", "price_open", "type",
    )

    def __init__(self, path: str = "state/icas_state.json"):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data: Dict[str, Any] = {"positions": {}, "daily": {}}
        self._load()

    # ------------------------- internal I/O -------------------------
    def _load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data["positions"] = data.get("positions", {}) or {}
                    self._data["daily"] = data.get("daily", {}) or {}
        except (json.JSONDecodeError, OSError):
            # File korup -> mulai bersih, jangan matikan daemon
            self._data = {"positions": {}, "daily": {}}

    def _flush(self) -> None:
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
        os.replace(tmp_path, self.path)  # atomik di POSIX & Windows (Py>=3.3)

    # ------------------------- positions -------------------------
    def save_position(self, pos: Dict[str, Any]) -> None:
        """Simpan snapshot state manajemen untuk sebuah tiket."""
        ticket = str(pos.get("ticket"))
        if not ticket or ticket == "None":
            return
        snap = {k: pos.get(k) for k in self._POS_KEYS if k in pos}
        snap["volume"] = pos.get("volume", snap.get("initial_volume"))
        with self._lock:
            self._data["positions"][ticket] = snap
            self._flush()

    def get_position(self, ticket) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._data["positions"].get(str(ticket)) or {}) or None

    def clear_position(self, ticket) -> None:
        with self._lock:
            if str(ticket) in self._data["positions"]:
                del self._data["positions"][str(ticket)]
                self._flush()

    def list_position_tickets(self) -> list:
        """[ENGINE v2] Daftar seluruh tiket yang tersimpan di state — dipakai
        rekonsiliasi on/off: tiket yang sudah tidak terbuka di broker akan
        dicatat ke jurnal sebagai position_closed_offline lalu dibersihkan."""
        with self._lock:
            return list(self._data["positions"].keys())

    def merge_into(self, pos: Dict[str, Any]) -> bool:
        """
        Pulihkan field manajemen dari store ke dict posisi live.
        Return True jika ada state tersimpan yang diterapkan.
        Hanya field manajemen yang ditimpa — ticket/price_open/sl/profit
        realtime dari MT5 selalu jadi sumber kebenaran.
        """
        stored = self.get_position(pos.get("ticket"))
        if not stored:
            return False
        for k in ("tp1_hit", "tp2_hit", "tp3_hit", "be_set", "trail_step", "initial_volume"):
            if stored.get(k) is not None:
                pos[k] = stored[k]
        # max_fav: ambil nilai terbesar (state lama mungkin lebih tinggi dari sesi sebelumnya)
        stored_max = stored.get("max_fav")
        if isinstance(stored_max, (int, float)) and stored_max > pos.get("max_fav", 0.0):
            pos["max_fav"] = stored_max
            return True
        return True

    # ------------------------- daily counters -------------------------
    def save_daily(self, date_str: str, daily_trades_count: int, consecutive_losses: int = 0) -> None:
        with self._lock:
            self._data["daily"] = {
                "date": date_str,
                "daily_trades_count": int(daily_trades_count),
                "consecutive_losses": int(consecutive_losses),
            }
            self._flush()

    def get_daily(self, date_str: str) -> Dict[str, int]:
        with self._lock:
            d = self._data.get("daily", {}) or {}
            if d.get("date") == date_str:
                return {
                    "daily_trades_count": int(d.get("daily_trades_count", 0)),
                    "consecutive_losses": int(d.get("consecutive_losses", 0)),
                }
            return {"daily_trades_count": 0, "consecutive_losses": 0}
