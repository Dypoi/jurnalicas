# ⚡ Model Icas Autonomous Scalper (XAUUSD Gold — M5)

Bot trading otonom *standalone* berbasis **ICT Liquidity Sweep + Judas Displacement (CHoCH/FVG)**
dengan **4-Tier Multi-TP, Early Breakeven+, dan Step Trailing Runner**.
Pair: **XAUUSD (Gold)** — broker **Exness** (Standard / Micro XAUUSDm / Zero).
Aturan risiko ketat: **1 Signal 1 Position (Zero Martingale, Zero Grid, Zero Layering)**.

> ⚠️ **Versi ini adalah hasil Audit Forensik 25 Agu 2026** — 14 bug diperbaiki
> (lihat `LAPORAN_AUDIT_FORENSIK.md`), termasuk root cause error `10016 Invalid stops`.
> **Baca bagian "Hasil Backtest & Kejujuran Statistik" sebelum memakai uang sungguhan.**

---

## 🌟 Fitur Utama (model saat ini)

1. **1 Signal 1 Position** — mutex lock + filter *magic number* (posisi manual/EA lain tidak ikut terkelola).
2. **Early Breakeven+ @ +10 pips** — SL dikunci profit kecil begitu profit berjalan ≥ $1.00;
   offset kunci **di-cap agar tidak pernah melampaui harga pasar** (perbaikan bug 10016) dan
   divalidasi terhadap `SYMBOL_TRADE_STOPS_LEVEL` + spread live.
3. **4-Tier Multi-TP** — TP1 +20p (30% lot) → TP2 +40p (25%) → TP3 +60p (25%, SL naik ke TP1) →
   Runner 20% dengan **step trailing** (setiap 100 pips, kunci 30 pips).
4. **Ukuran posisi sadar biaya** — lot dihitung dari risiko efektif **SL + spread + slippage**
   (`INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK=True`), sehingga risiko riil tidak membengkak saat spread lebar.
5. **Persistensi state** — status TP/BE/trailing tersimpan atomik di `state/icas_state.json`;
   restart bot **tidak lagi mengeksekusi TP ganda**; jika file hilang, status direbuild dari riwayat deal MT5.
6. **Dashboard terproteksi** — token auth opsional (`ICAS_DASH_TOKEN`).

---

## 🚀 Quick Start

```bash
# 1) Install dependensi (Windows + MT5):
install_requirements.bat

# 2) Backtest (engine konservatif default — lihat penjelasan di bawah):
python icasbot --backtest --start 2026-01-01 --end 2026-06-30 --fixed
#    mode engine lama (pra-audit, untuk komparasi): tambahkan --legacy

# 3) Live (isi kredensial via environment variable — JANGAN hardcode di file):
set MT5_LOGIN=12345678 & set MT5_PASSWORD=xxxx & set MT5_SERVER=Exness-MT5Trial6
python icasbot --live

# 4) Dashboard (dengan proteksi token):
set ICAS_DASH_TOKEN=rahasia-anda
python icasbot --dashboard
#    akses: http://localhost:5000/?token=rahasia-anda
```

### Verifikasi kesehatan kode (jalankan kapan pun)
```bash
python verify_fix_10016.py          # regresi bug 10016 (mock MT5)      -> 5/5 PASS
python verify_state_persistence.py  # persistensi & rebuild state       -> 14/14 PASS
python verify_engine_parity.py      # parity bitwise engine baru vs lama-> 4/4 PASS
python test_icas_audit.py           # unit test inti                    -> 7/7 OK
python test_be_15_pips.py           # unit test BE+                     -> 2/2 OK
```

---

## 📊 Hasil Backtest & Kejujuran Statistik (WAJIB BACA)

Audit menemukan **engine lama bersifat optimis intrabar**: dalam 1 candle M5, TP diproses
dulu baru SL — padahal urutan high↔low di dalam candle **tidak dapat diketahui dari data OHLC**.
Engine v2 menyediakan dua mode; **kinerja riil strategi berada DI ANTARA kedua batas ini**:

| Periode | Mode | Trades | W/BE/L | Non-Loss | PF | Net Profit |
|---|---|---|---|---|---|---|
| Jan–Jun 2026 (fixed) | LEGACY (optimis) | 1359 | 864/229/266 | 80.43% | 3.88 | +$391,187.88 |
| Jan–Jun 2026 (fixed) | **KONSERVATIF (pesimis)** | 968 | 311/43/614 | 36.57% | **0.81** | **−$57,846.01** |
| Jun 2025–Jun 2026 (fixed) | LEGACY (optimis) | 2750 | 1450/664/636 | 76.87% | 2.37 | +$453,032.50 |
| Jun 2025–Jun 2026 (fixed) | **KONSERVATIF (pesimis)** | 1852 | 631/205/1016 | 45.14% | **0.87** | **−$64,637.81** |

**Artinya:** klaim performa lama (WR 75%+) sebagian besar adalah artefak bias urutan intrabar.
Kedua angka di tabel hanyalah **batas atas & bawah ekstrem**.

### 🎲 Estimasi titik terbaik & jawaban definitif (tindak lanjut audit)
```bash
# (a) Monte Carlo intrabar (urutan SL/TP di-sample probabilistik, N simulasi):
python research/monte_carlo_intrabar.py 2000 "2026-01-01" "2026-06-30 23:59:59"
#    -> hasil audit: PF median 1.80 (CI90% 1.70-1.90), NLR ~67%, P(PF>1)=100%

# (b) Sequencing definitif dgn M1 ekspor MT5 Anda (tanpa asumsi sama sekali):
python research/validate_granular.py --fine data/historical/xauusd_m1.csv
```
### 🔬 Hasil definitif pada FEED BROKER RIIL (M1 ekspor MT5, 14 Mei–25 Agu 2026)
Validasi sequencing M1 sesungguhnya (908 trade, spread $0.26, sizing risk-aware):
**PF 0.80 | Non-Loss 61.45% | Net −$34,477 (fixed $500) | 0/4 bulan hijau.**
Monte Carlo (N=1000): PF median 1.30. Legacy optimis: 2.22.

⛔ **Kesimpulan jujur:** pada feed live Anda, parameter LAMA $2 SL/TP1 +$2 **ekspektasinya
negatif** (spread $0.26 ≈ 13% dari jarak SL). Catatan penting: dataset M5 di repo **bukan feed
yang sama** dengan akun live Anda (deviasi median ~$15), dan simbol XAUUSDm 3-digit berarti
`SPREAD 260 pts = $0.26` — kode kini digit-aware (`infer_price_point` / `bridge.get_point()`).
Cek juga *Contract size* simbol (jika akun Cent, kalkulasi lot wajib disesuaikan).

### 🎯 Kalibrasi 25 Agu 2026 — parameter BARU sudah diterapkan (LAPORAN §9)
Grid-search walk-forward (168+60 kombo, optimasi di TRAIN 05-14→07-15, konfirmasi OOS di
TEST 07-15→08-25) di atas sequencing M1 definitif menemukan zona robust **SL 150–200 pips,
struktur TP kelipatan SL, Early BE+ dimatikan**. Config aktif sekarang: **SL 150p ($15),
TP 187.5/375/562.5p, BE+ OFF** → hasil window penuh feed broker:
**326 trade | PF 2.08 | Net +$38,067 (risiko tetap $500) | DD 12.8% | 4/4 bulan hijau**
(TRAIN 1.97 / TEST 2.25). Alternatif konservatif (NLR 83.7%, PF 1.77) terdokumentasi di
`config.py`. Jalankan ulang bukti: `python research/grid_search_m1.py` dan
`python research/finalist_detail.py`. ⚠️ Sampel 3,4 bulan satu rezim → **wajib forward-test
demo ≥4–6 minggu sebelum dianggap final**.

## 🖥️ ENGINE BARU v2 — Mode Demo di Laptop (tanpa VPS)

Daemon live (`run_live.py`) kini = **engine baru SWING-150** dengan dua fitur observasi:

**1. Jurnal JSON** — `logs/trade_journal.jsonl` (format JSON Lines, 1 event/baris, append-only →
aman dari crash/cabut listrik). Yang dicatat: siklus hidup `engine_start/stop` (+snapshot config
lengkap), `signal_detected`, `order_open/failed`, `tp_hit` (level 1-3), `be_lock`, `trail_update`,
`position_closed` (+PnL realized dari deal broker), `equity_snapshot` tiap 15 menit, dan dua event
khusus on/off: `position_adopted` (posisi lama dilanjutkan saat Anda ON lagi) &
`position_closed_offline` (posisi yang tertutup **saat laptop OFF**, direkonsiliasi dari riwayat
deal broker).

**2. Anti on/off** — state posisi & counter harian dipersist atomik (`state/icas_state.json`);
saat restart, posisi terbuka diadopsi tanpa TP ganda/sl tersesat (diuji `verify_state_persistence.py`
14/14 + rebuild dari deal broker sebagai cadangan).

Cara pakai (Windows):
```bat
REM 1. Buka MT5, pastikan login akun DEMO. 2. Klik dua kali:
START_ENGINE_DEMO.bat
REM Mematikan: Ctrl+C di jendela engine (aman).
REM Setelah seminggu observasi:
python research/journal_report.py
```
`journal_report.py` merangkum: entry/PnL per hari, PF-NLR-ekspektasi, kurva equity snapshot,
durasi hold, statistik on/off, + evaluasi otomatis vs referensi forward-test (✅ PF≥1.8 sehat ·
🟡 butuh sampel · ⛔ PF<1 setelah ≥30 trade = STOP & kalibrasi ulang). Keluaran disimpan ke
`reports/journal_observasi.txt`.

Catatan laptop: saat OFF, posisi tetap berjalan di broker dengan SL aktif — tetapi BE+/trailing
baru diperbarui setelah engine ON lagi (inheren tanpa VPS). Minggu pertama seminggu penuh
(Minggu-Jumat) memberi sampel ~15-20 trade (referensi ~3-5 entry/hari).

**Dashboard pasca-audit (D-01..D-05, LAPORAN §12)**: jalankan `run_dashboard.bat` berdampingan
dengan daemon. Kini: seluruh label mengikuti engine aktif (tidak ada lagi angka legacy), spread
USD digit-aware, statistik berlabel sumber (**JURNAL ENGINE v2** → live-deals MT5 digabung
per posisi → backtest repo bergaya peringatan), panel baru **"Jurnal Engine & Observasi On/Off"**
(status engine AKTIF/MATI dari umur event jurnal, sinyal/order & PnL realized hari ini + 7 hari,
siklus ON/OFF, mini-feed event), dan badge versi engine di navbar. Verifikasi otomatis:
`python verify_dashboard_v2.py` (21/21).

---

## 📁 Struktur Direktori

```
model_icas_bot/
├── config.py                  # Konfigurasi risiko, broker, killzone, flag engine & keamanan
├── icasbot                    # Master CLI (--live / --backtest / --dashboard)
├── icas_daemon.py             # Daemon eksekusi live (+ persistensi state, guard 10016)
├── run_live.py / run_backtest.py / run_dashboard.py
├── requirements.txt
├── data/historical/           # Dataset MT5 (M5/M15/M30/H1)
├── state/                     # [auto] state/icas_state.json (di-gitignore)
├── research/                  # Skrip riset usang (parameter pra-audit, arsip)
├── src/
│   ├── indicators/            # Session killzone & FVG/CHoCH
│   ├── strategy/              # Sinyal + sizing sadar spread/slippage
│   ├── execution/             # Bridge MT5 (guard stops-level, filter magic, infer state)
│   ├── backtest/              # Engine v2 (konservatif default; parity 1:1 mode legacy)
│   ├── state_store.py         # Persistensi state atomik (JSON + os.replace)
│   └── dashboard_app.py       # Flask dashboard (+ token auth)
├── templates/index.html
├── verify_*.py                # Tes regresi audit
└── test_*.py                  # Unit test inti
```

## 🔐 Catatan Keamanan
- Kredensial MT5 hanya via environment variable (`MT5_LOGIN/PASSWORD/SERVER`) — jangan commit password.
- Dashboard bind `0.0.0.0` tanpa token akan mencetak peringatan; set `ICAS_DASH_TOKEN` atau bind `127.0.0.1`.

## ⚠️ Disclaimer
Perangkat lunak ini untuk riset/edukasi. Trading XAUUSD berisiko tinggi; hasil backtest — dari
mode mana pun — **bukan jaminan** kinerja masa depan. Gunakan akun demo terlebih dahulu.
