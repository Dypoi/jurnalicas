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

--------------------------------------------------------------------------------
[AUDIT FORENSIK 2 — F-03] TOMBSTONE / "CLOSED LEDGER"
--------------------------------------------------------------------------------
Bug produksi (jurnal 27 Agu 2026, tiket 4987805272 & 4988300823): saat koneksi
MT5 putus sebentar, positions_get() mengembalikan () sehingga daemon menyatakan
posisi "tutup" lalu MENGHAPUS seluruh state manajemen. Beberapa detik kemudian
posisi yang sama terlihat lagi dengan state default -> TP1 dieksekusi ulang
(close_vol 0.10 lalu 0.07 lalu 0.05 pada tiket yang sama).

Perbaikan: state tiket yang dinyatakan tutup TIDAK dihapus, melainkan dipindah
ke `closed` (tombstone) lengkap dengan waktu tutup. Jika tiket yang sama muncul
lagi di broker dalam POSITION_REVIVE_WINDOW_SECONDS, state dipulihkan utuh dan
kejadian itu dicatat sebagai `position_revived` — bukan diperlakukan sebagai
posisi baru.
"""
import json
import os
import threading
import datetime
from typing import Dict, Any, Optional


class StateStore:
    """JSON state store dengan penulisan atomik dan kunci thread."""

    _POS_KEYS = (
        "tp1_hit", "tp2_hit", "tp3_hit", "be_set",
        "max_fav", "trail_step", "initial_volume", "price_open", "type",
    )

    def __init__(self, path: str = "state/icas_state.json", tombstone_keep: int = 40):
        self.path = path
        self.tombstone_keep = int(tombstone_keep or 40)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data: Dict[str, Any] = {"positions": {}, "daily": {}, "closed": {}}
        self._last_serialized: Optional[str] = None
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
                    # [F-03] backward-compatible: file lama belum punya "closed"
                    self._data["closed"] = data.get("closed", {}) or {}
        except (json.JSONDecodeError, OSError):
            # File korup -> mulai bersih, jangan matikan daemon
            self._data = {"positions": {}, "daily": {}, "closed": {}}
        self._last_serialized = None

    def _flush(self) -> None:
        """Tulis atomik, HANYA bila isi benar-benar berubah (hemat I/O 3-detik)."""
        payload = json.dumps(self._data, ensure_ascii=False, sort_keys=True, default=str)
        if payload == self._last_serialized:
            return
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())          # [F-14] tahan terhadap mati listrik
        os.replace(tmp_path, self.path)   # atomik di POSIX & Windows (Py>=3.3)
        self._last_serialized = payload

    # ------------------------- positions -------------------------
    def save_position(self, pos: Dict[str, Any]) -> None:
        """Simpan snapshot state manajemen untuk sebuah tiket."""
        ticket = str(pos.get("ticket"))
        if not ticket or ticket == "None":
            return
        snap = {k: pos.get(k) for k in self._POS_KEYS if k in pos}
        snap["volume"] = pos.get("volume", snap.get("initial_volume"))
        snap["closed_volume"] = pos.get("closed_volume", 0.0)
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

    # ------------------- [F-03] closed tombstones -------------------
    def mark_closed(self, ticket, reason: str = "") -> None:
        """Pindahkan state tiket aktif ke `closed` (TIDAK dihapus total).

        Inilah perbaikan inti atas bug TP1 dobel: state manajemen tetap ada
        sehingga bila broker ternyata masih membuka posisi ini, TP1/TP2/TP3
        dan trail_step dapat dipulihkan apa adanya.
        """
        tk = str(ticket)
        with self._lock:
            snap = self._data["positions"].pop(tk, None) or {}
            snap["closed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            snap["close_reason"] = reason
            self._data["closed"][tk] = snap
            # batasi ukuran tombstone
            closed = self._data["closed"]
            if len(closed) > self.tombstone_keep:
                for k in sorted(closed, key=lambda x: str(closed[x].get("closed_at", ""))):
                    del closed[k]
                    if len(closed) <= self.tombstone_keep:
                        break
            self._flush()

    def get_closed(self, ticket) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._data["closed"].get(str(ticket)) or {}) or None

    def drop_closed(self, ticket) -> None:
        with self._lock:
            if str(ticket) in self._data["closed"]:
                del self._data["closed"][str(ticket)]
                self._flush()

    def list_closed_tickets(self) -> list:
        with self._lock:
            return list(self._data.get("closed", {}).keys())

    @staticmethod
    def closed_age_seconds(tombstone: Dict[str, Any]) -> Optional[float]:
        try:
            t = datetime.datetime.fromisoformat(str(tombstone.get("closed_at", "")))
            return (datetime.datetime.now() - t).total_seconds()
        except Exception:
            return None

    def merge_into(self, pos: Dict[str, Any]) -> bool:
        """
        Pulihkan field manajemen dari store ke dict posisi live.
        Return True jika ada state tersimpan yang diterapkan.
        Hanya field manajemen yang ditimpa — ticket/price_open/sl/profit
        realtime dari MT5 selalu jadi sumber kebenaran.

        [F-03] Bila tiket tidak ada di `positions` tetapi ada di `closed`,
        state tombstone tetap dipakai sebagai sumber pemulihan terakhir.
        """
        stored = self.get_position(pos.get("ticket"))
        revived_from_tombstone = False
        if not stored:
            stored = self.get_closed(pos.get("ticket"))
            if stored:
                revived_from_tombstone = True
        if not stored:
            return False
        for k in ("tp1_hit", "tp2_hit", "tp3_hit", "be_set", "trail_step",
                  "initial_volume", "closed_volume"):
            if stored.get(k) is not None:
                pos[k] = stored[k]
        if revived_from_tombstone:
            pos["_revived"] = True
        # max_fav: ambil nilai terbesar (state lama mungkin lebih tinggi dari sesi sebelumnya)
        stored_max = stored.get("max_fav")
        if isinstance(stored_max, (int, float)) and stored_max > pos.get("max_fav", 0.0):
            pos["max_fav"] = stored_max
        # initial_volume tidak boleh menyusut menjadi volume sisa (akar bug TP1 dobel)
        iv = pos.get("initial_volume")
        vol = pos.get("volume")
        if isinstance(iv, (int, float)) and isinstance(vol, (int, float)) and iv < vol:
            pos["initial_volume"] = vol
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
