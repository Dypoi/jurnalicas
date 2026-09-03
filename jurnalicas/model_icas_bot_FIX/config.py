"""
========================================================================================
MODEL ICAS AUTONOMOUS BOT - CONFIGURATION SYSTEM (4-TIER MULTI-TP & BE+ ARCHITECTURE)
========================================================================================
Pair: XAUUSD (Gold) | Broker: Exness (Standard / Micro XAUUSDm / Zero)
Strategy: ICT Liquidity Sweep + Judas Displacement + 4-Tier Multi-TP & Step Trailing Stop
========================================================================================
"""

import os
from dataclasses import dataclass

@dataclass
class IcasConfig:
    # Broker & Connection Settings
    SYMBOL: str = "XAUUSDm"                   # Auto-detects XAUUSD, GOLD, XAUUSDm on MT5
    TIMEFRAME: str = "M5"                     # Primary execution timeframe
    MACRO_TIMEFRAME: str = "M15"              # Higher timeframe liquidity map
    MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
    MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str = os.getenv("MT5_SERVER", "Exness-MT5Trial6")
    MT5_PATH: str = os.getenv("MT5_PATH", "")

    # Risk Management Settings (Strict 1 Signal 1 Position)
    INITIAL_CAPITAL: float = 10000.0          # Initial balance base
    RISK_PER_TRADE_PCT: float = 0.05          # 5.0% Risk per trade ($500 per order on $10k base)
    USE_COMPOUNDING: bool = False             # False = Fixed $500/trade (Recommended), True = Dynamic Equity
    MAX_TRADES_PER_DAY: int = 999             # Set 999 for Unlimited trades
    MAX_CONSECUTIVE_LOSSES: int = 999         # Set 999 to disable circuit breaker
    ZERO_MARTINGALE: bool = True              # Absolutely zero martingale
    ZERO_GRID: bool = True                    # Absolutely zero averaging / grid
    ZERO_LAYERING: bool = True                # Single order execution only
    ALLOW_REENTRY_AFTER_BE: bool = True       # Re-entry allowed immediately on high-prob setup after BE+

    # Stop Loss & Guaranteed Profit Early BE+
    # ===================== [KALIBRASI 25 Agu 2026 — grid walk-forward def. M1] =====================
    # BASELINE LAMA (gagal validasi, PF 0.80): SL=20.0, TP=20/40/60, BE=10.0
    # PRESET AKTIF — "SWING-150 C" (ekspektasi maks, PF full 2.08, Train 1.97 / Test 2.25):
    #   SL $15 (150p) | TP $18.75/$37.50/$56.25 | Early BE+ DIMATIKAN (9999)
    #   Full window: 326 tr | NLR 37.4% | Net +$38,067 | DD 12.8% | 4/4 bulan hijau
    # Preset alternatif konservatif-NLR — "SL200 B + BE terlambat" (PF 1.77, NLR 83.7%):
    #   STOP_LOSS_PIPS=200, TP1/2/3=200/400/600, EARLY_BE_TRIGGER_PIPS=60
    STOP_LOSS_PIPS: float = 150.0             # $15.00 — spread kini hanya ~1.7% dari SL
    EARLY_BE_TRIGGER_PIPS: float = 9999.0     # 9999 = Early BE+ OFF (data: BE dini membunuh expectancy)
    BE_PROFIT_OFFSET_PIPS: float = 3.0        # Lock +3 pips ($0.30) jika BE+ diaktifkan lagi
    
    # 4-Tier Multi-Target Split (Sum = 1.0)
    TP1_PIPS: float = 187.5                   # TP1 = 1.25 x SL ($18.75) -> Close 30% lot
    TP1_LOT_RATIO: float = 0.30
    
    TP2_PIPS: float = 375.0                   # TP2 = 2.5 x SL ($37.50) -> Close 25% lot
    TP2_LOT_RATIO: float = 0.25
    
    TP3_PIPS: float = 562.5                   # TP3 = 3.75 x SL ($56.25) -> Close 25% lot
    TP3_LOT_RATIO: float = 0.25
    STEP_SL_TO_TP1_ON_TP3: bool = True        # When TP3 is hit, SL is stepped up to TP1 (+20 pips)
    
    RUNNER_LOT_RATIO: float = 0.20            # Remaining 20% lot runs with Step Trailing Stop
    TRAILING_STEP_PIPS: float = 100.0         # Advance trailing stop every 100 pips ($10.00) running profit
    TRAILING_LOCK_PIPS: float = 30.0          # Lock 30 pips ($3.00) profit per 100-pip milestone

    # Session Killzone Filter:
    USE_KILLZONE: bool = False                # False = 24H Full-Market trading

    # ICT Session Hours (Server Time: EET UTC+2/3 | WIB = UTC+7)
    SERVER_TIME_OFFSET_HOURS: int = 4         # WIB is MT5 Server + 4 hours
    LONDON_BURST_START_SERVER: int = 10
    LONDON_BURST_END_SERVER: int = 12
    NY_BURST_START_HOUR_SERVER: int = 15
    NY_BURST_START_MIN_SERVER: int = 30
    NY_BURST_END_HOUR_SERVER: int = 17
    NY_BURST_END_MIN_SERVER: int = 30

    # Spread Guard (Exness Standard ~ 260 points = $2.60)
    MAX_SPREAD_POINTS: float = 350.0          # Maximum allowable spread before entry (35 pips / $3.50)

    # Dashboard & Polling
    POLL_INTERVAL_SECONDS: int = 3            # Live execution daemon polling frequency
    DASHBOARD_HOST: str = "0.0.0.0"
    DASHBOARD_PORT: int = 5000
    DASHBOARD_AUTH_TOKEN: str = os.getenv("ICAS_DASH_TOKEN", "")  # [AUDIT FIX] kosong = tanpa proteksi (warning)

    # ============================================================================
    # [AUDIT FOLLOW-UP] Execution Realism & State Persistence
    # ============================================================================
    # S-04: Risiko dihitung dari SL + spread + slippage (bukan SL saja)
    INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK: bool = True
    SLIPPAGE_USD: float = 0.10                # Estimasi slippage eksekusi per sisi ($0.10 = 1 pip)

    # R-01: Mode intrabar konservatif — SL dicek DULUAN dalam 1 bar (pesimis),
    # SL yang baru naik (BE/TP-step/trailing) baru berlaku bar berikutnya.
    CONSERVATIVE_INTRABAR: bool = True
    ENFORCE_SPREAD_GUARD_IN_BACKTEST: bool = True   # Lewati entry saat spread > MAX_SPREAD_POINTS

    # S-03: Persistensi state daemon (anti double-TP / state hilang saat restart)
    STATE_FILE: str = "state/icas_state.json"
    STATE_RESTORE_FROM_DEALS: bool = True     # Rebuild status TP dari riwayat deal jika file hilang

    # ============================================================================
    # [AUDIT FORENSIK 2 — 02 Sep 2026] KETAHANAN TERHADAP ERROR / KONEKSI TERPUTUS
    # ============================================================================
    # F-02/F-03: Konfirmasi penutupan posisi. Posisi TIDAK boleh dinyatakan tutup
    # (dan state manajemennya dihapus) hanya karena positions_get() kosong beberapa
    # kali — saat terminal putus koneksi, MT5 mengembalikan () bukan None.
    POSITION_MISS_LIMIT: int = 5              # miss berurutan sebelum konfirmasi tutup
    CLOSE_REQUIRE_BROKER_PROOF: bool = True   # wajib ada deal OUT di riwayat broker
    CLOSED_TOMBSTONE_KEEP: int = 40           # jumlah tiket "tutup" yang disimpan utk revive
    POSITION_REVIVE_WINDOW_SECONDS: int = 3600  # tiket yg muncul lagi < 1 jam = revive, bukan posisi baru
    # [T-04] Mutex ditahan selama ada tiket menunggu konfirmasi tutup. Katup
    # pengaman: setelah ini (detik) tanpa kepastian broker, entry diizinkan lagi
    # agar bot tidak macet selamanya (SL posisi lama tetap aktif di broker).
    MAX_PENDING_CLOSE_SECONDS: int = 900

    # F-04: Guard feed. Tick bid/ask 0 atau basi = feed mati -> SEMUA manajemen
    # posisi & entry dilewati. Tanpa ini, posisi SELL dengan tick 0 menghasilkan
    # fav_usd = entry - 0 = ~$4600 -> TP1/TP2/TP3 + trailing step 46 meledak.
    MAX_TICK_AGE_SECONDS: int = 120           # 0 = nonaktifkan pemeriksaan umur tick
    REQUIRE_VALID_TICK: bool = True

    # F-11: TP tier dieksekusi berdasarkan harga SAAT INI, bukan max_fav historis.
    # max_fav tetap dipakai untuk trailing (itu memang fungsinya). Dengan True,
    # partial close tidak pernah dieksekusi di harga yang lebih buruk dari level TP.
    TP_TRIGGER_ON_CURRENT_PRICE: bool = True

    # F-06: Daemon tidak boleh mati karena satu exception transien.
    RESILIENT_CYCLE: bool = True
    MAX_CONSECUTIVE_CYCLE_ERRORS: int = 20    # setelah ini daemon berhenti sadar (bukan spin)

    # F-15: Rotasi jurnal agar logs/trade_journal.jsonl tidak tumbuh tanpa batas.
    JOURNAL_MAX_BYTES: int = 20_000_000       # 0 = tanpa rotasi
    JOURNAL_KEEP_ROTATED: int = 5
    JOURNAL_HEALTH_FILE: str = "logs/trade_journal.health.json"

    # ============================================================================
    # [ENGINE BARU v2 "SWING-150" — 25 Agu 2026] Identitas + Jurnal Observasi JSON
    # ============================================================================
    ENGINE_VERSION: str = "icas-v2-swing150-c (kalibrasi 25 Agu 2026)"
    JOURNAL_ENABLED: bool = True              # Jurnal JSONL ke logs/trade_journal.jsonl
    JOURNAL_FILE: str = "logs/trade_journal.jsonl"
    JOURNAL_EQUITY_SNAPSHOT_SECONDS: int = 900  # Telemetri modal tiap 15 menit
    # Killzone tetap NONAKTIF sesuai permintaan pengguna (USE_KILLZONE=False di atas).
    # Anti on/off laptop: state posisi & counter harian dipersist atomik (StateStore),
    # posisi lama diadopsi ulang saat daemon ON, posisi yang tertutup saat OFF
    # direkonsiliasi dari riwayat deal broker (lihat icas_daemon.py + trade_journal).

# Global active config instance
config = IcasConfig()
