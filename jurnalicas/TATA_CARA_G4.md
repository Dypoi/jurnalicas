# TATA CARA JURNAL TRADING G4 (icas-v3-g4)

**Dokumen operasional — bot live Model Icas beralih ke strategi G4**
Dibuat 09 Sep 2026 · commit `81a40d0` · branch `arena/01a080b1-jurnalicas`

---

## 1. Apa yang berubah

Jurnal ICAS sekarang menjalankan **G4** — sinyal kaskade multi-timeframe yang
menggantikan sinyal lama choch+sesi (icas-v2) berdasarkan diagnosis
`LAPORAN_TUNING_SCALPING.md`: masalah engine lama bukan TP/SL, melainkan
**sinyal** (choch PF 0,92 setahun — kalah dari kontrol acak 1,02).

**G4 = kaskade 4 lapis (kausal, tanpa repaint) + trailing cepat:**

| Lapis | TF | Fungsi |
|---|---|---|
| L1 | H1 | Bias arah: close vs EMA200-H1 (bar H1 ≤ t−1 jam) |
| L2 | M5 | Sweep likuiditas PDH/PDL (high/low hari bursa kemarin, ≤ t−24 jam) dalam jendela 288 bar M5 (24 jam) |
| L3 | M15 | CHoCH: close menembus swing 5-bar M15 [k−6..k−2] |
| L4 | M5 | Trigger: displacement candle + FVG $0,30 / break swing 5-bar [i−6..i−2] |

Eksekusi: sinyal dihitung **tepat setelah bar M5 tertutup** → entry market
~open bar berikutnya (BUY isi ask, SELL isi bid). SL 150 pips ($15), TP
187,5/375/562,5 (split 30/25/25% + runner 20%), trailing step 50 / lock 30
pips, **risk 1% per trade**, maks 1 posisi aktif (mutex), guard spread $1,20.

**Angka riset (engine audit anti-repaint, 2025-09-01..2026-09-01, XAUUSD M1
Exness, risk 1% $10k):**

| Metrik | Nilai |
|---|---|
| Trade / WR / PF | **1.338 / 73,0% / 1,12** |
| Net / tahun | **+$4.493** |
| Max drawdown | 19,5% |
| Frekuensi | **~103 entry/bulan** (3–4/hari aktif — karakter scalping dipertahankan) |
| Signifikansi | Monte-Carlo 32-seed, kontrol acak μ −$508 → **p = 0,000** |
| Paritas live↔riset | **IDENTIK bar-per-bar** (71.128 bar setahun, 3.694 sinyal geometri, 0 mismatch) — `reports/g4_parity_20250901_20260901.txt` |

Batas validitas (wajib dibaca): backtest 2021–2022 **merah −$537** (rezim
side-way/rate-hike); edge G4 terukur pada 2023–2026. Hasil masa lalu tidak
menjamin masa depan — **mulai dari akun DEMO**.

---

## 2. Prasyarat

1. **Windows** (paket `MetaTrader5` Python hanya jalan di Windows).
2. **Python 3.10+** terpasang dan masuk PATH (`python --version`).
3. **Terminal MT5 Exness** (Standard/Micro — simbol `XAUUSDm`) — akun
   **DEMO dulu**. Server Exness memakai zona waktu EET/EEST (Europe/Athens);
   konversi waktu candle → UTC mengasumsikan ini.
4. Koneksi internet stabil (VPS Windows direkomendasikan untuk jurnal 24/5).

> Catatan khusus: `XAUUSDm` Exness = **3 digit** (1 point = $0,001). Guard
> spread bot berbasis **USD** (`MAX_SPREAD_USD = $1,20`), bukan points, jadi
> aman untuk quote 2-digit maupun 3-digit.

---

## 3. Instalasi (tinggal clone)

Buka Command Prompt / PowerShell:

```bat
:: 1. Clone repo (branch G4)
git clone -b arena/01a080b1-jurnalicas https://github.com/Dypoi/jurnalicas.git
cd jurnalicas\model_icas_bot_FIX

:: 2. Virtual environment + dependensi
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 3. Jembatan Python -> terminal MT5 (SEKALI SAJA, di dalam venv)
pip install MetaTrader5
```

> **"Saya sudah punya aplikasi MetaTrader 5 — masih perlu `pip install MetaTrader5`?"**
> **YA.** Itu dua hal berbeda: **aplikasi MT5** (terminal trading yang sudah Anda
> punya — grafik, akun, order manual) vs **paket Python `MetaTrader5`** (library
> kecil di dalam venv yang menjadi jembatan bot Python → terminal Anda). Tanpa
> paket ini daemon hanya jalan mode simulasi (log: *"MT5 Bridge running in
> Simulation mode"*) dan **tidak akan trading**. Instalasi ini tidak mengubah
> aplikasi MT5 Anda sama sekali.
>
> NB: perintah berantai `&&` hanya jalan di **CMD** / PowerShell 7+. Di
> PowerShell lama, jalankan perintah satu per satu.

### 3a. Memperbarui clone yang SUDAH ADA (jangan clone ulang!)

Saat ada commit baru di repo, cukup tarik perubahannya — venv, kredensial,
dan konfigurasi lokal **tidak tersentuh** (tidak ada instalasi ulang):

```bat
:: hentikan dulu dashboard/bot yang sedang jalan (Ctrl+C di jendelanya)

cd jurnalicas
git pull

:: cek pembaruan sampai:
git log --oneline -3
```

(Contoh: setelah audit dashboard, commit teratas harus
`313830c Audit forensik dashboard: 11 bug (D6-01..D6-11)...`.)

Verifikasi opsional di mesin Anda (aman — jurnal asli di-backup otomatis):

```bat
cd model_icas_bot_FIX
.venv\Scripts\activate
python verify_dashboard_v3.py      :: harus 40 PASS / 0 FAIL
```

Clone ulang penuh hanya diperlukan bila folder clone lama hilang/korup, atau
memasang di komputer lain. Git akan menolak clone ke folder yang sudah ada.

File penting:

| File | Peran |
|---|---|
| `icas_daemon.py` | Bot live (daemon utama) — **ini yang dijalankan** |
| `config.py` | Semua parameter (strategi, risk, TP/SL, trailing, kredensial) |
| `src/strategy/g4_strategy.py` | Strategi G4 (kaskade MTF) |
| `src/execution/mt5_bridge.py` | Jembatan MT5 (order, candle, spread guard USD) |
| `run_dashboard.py` | Dashboard web monitoring |
| `research/g4_parity_check.py` | QC paritas live↔riset (opsional) |

---

## 4. Kredensial & konfigurasi

Kredensial MT5 **hanya via environment variable** (jangan hardcode/password
di repo):

```bat
:: sesi CMD aktif (disarankan):
set MT5_LOGIN=12345678
set MT5_PASSWORD=passwordanda
set MT5_SERVER=Exness-MT5Trial6
set MT5_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe
```

atau permanen via `setx MT5_LOGIN 12345678` (dst., perlu buka CMD baru).

Cek `config.py` — preset G4 sudah aktif default:

```python
STRATEGY = "G4"            # kaskade MTF (rollback: "ICAS")
RISK_PER_TRADE_PCT = 0.01  # risk 1% per trade (rekomendasi riset)
MAX_SPREAD_USD = 1.20      # guard spread USD (kalibrasi backtest)
TRAILING_STEP_PIPS = 50.0  # trailing cepat 50/30
TRAILING_LOCK_PIPS = 30.0
MAX_TRADES_PER_DAY = 999   # tak terbatas (frekuensi scalping dipertahankan)
```

Tidak ada yang wajib diubah untuk menjalankan G4 default.

---

## 5. Persiapan terminal MT5 (sekali saja)

1. Login akun **demo** di terminal (File → Login to Trade Account).
2. Pastikan `XAUUSDm` tampil di **Market Watch** (klik kanan → Show All).
3. `Tools → Options → Charts → Max bars in chart` = **Unlimited**
   (bot menarik 5.000 bar H1 untuk konvergensi EMA200).
4. Aktifkan tombol **Algo Trading** (hijau) di toolbar.
5. Biarkan terminal tetap berjalan (minimize boleh).

---

## 6. Menjalankan bot

**Urutan lengkap SETIAP KALI menjalankan bot** (bukan sekali klik — ketik di CMD):

```bat
:: masuk folder repo
cd jurnalicas\model_icas_bot_FIX

:: aktifkan venv (prompt berubah jadi (.venv) )
.venv\Scripts\activate

:: kredensial — OPSIONAL bila terminal MT5 Anda sudah login
:: (bot mengikuti akun yang aktif di terminal); WAJIB untuk VPS
set MT5_LOGIN=12345678
set MT5_PASSWORD=passwordanda
set MT5_SERVER=Exness-MT5Trial6

:: JALANKAN BOT
python icas_daemon.py
```

> ⚠️ **Jangan klik dua kali `run_live.bat` begitu saja** — file itu membuka
> jendela baru yang TIDAK mewarisi venv dan env-var sesi CMD Anda, sehingga
> memakai Python global (deps hilang / kredensial kosong). Selalu jalankan
> dari CMD dengan venv aktif seperti di atas. Biarkan jendela terbuka 24/5 —
> itulah bot-nya; jurnal & state tersimpan otomatis, restart aman (posisi
> di-adopsi kembali via magic number).

Setelah start, yang terlihat di log:

- `✅ MT5 Connected successfully! Broker Symbol: XAUUSDm ...` — jembatan siap.
- Heartbeat tiap menit: `[HEARTBEAT] ... Sinyal Hari Ini: N | Posisi Aktif: 0/1`.
- Evaluasi sinyal **tiap bar M5 tertutup** (dedup otomatis; bar berjalan
  dibuang). Saat kaskade L1–L4 penuh:
  `⚡ SINYAL TERDETEKSI [G4]: BUY | Entry: ... | SL: ... | TP1..3: ... | Lot: ...`
  lalu `✅ Order Berhasil Dieksekusi di MT5! Ticket: ...`.
- Penolakan wajar (bukan error): spread > $1,20 (guard), histori belum
  cukup (baru start), mutex 1-posisi.
- Jurnal lengkap: `logs/trade_journal.jsonl` (event `signal_detected`,
  `order_open`, `order_failed`, TP partial, trailing, `order_close`).

**Biarkan daemon jalan 24/5.** Jurnal & state tersimpan otomatis; restart
aman (posisi terbursa di-adopsi kembali via magic number).

---

## 7. Dashboard monitoring

Terminal kedua (venv aktif):

```bat
python run_dashboard.py
```

Buka `http://localhost:5000`. Panel yang tersedia (rev 09 Sep 2026):

- **Kenapa (Belum) Entry** — bloker aktif (mutex/warm-up/spread/kaskade) +
  checklist kaskade L1–L4 per jalur BUY vs SELL + countdown bar M5 +
  alasan sinyal terakhir (hover "Sinyal terakhir" untuk detail lengkap).
- **Chart realtime** — candle bergerak tiap detik (tick live), garis PDH/PDL,
  garis ENTRY/SL/TP1-3 saat posisi aktif, badge ● LIVE / ○ FEED MATI.
- Statistik live, equity, riwayat trade (merge partial-TP per tiket), jurnal
  event, badge spread USD vs guard entry.

Token proteksi opsional: `set ICAS_DASH_TOKEN=...`.

---

## 8. Rollback ke strategi lama (ICAS choch)

Jika suatu saat ingin kembali ke sinyal lama:

```python
# config.py
STRATEGY: str = "ICAS"
```

Restart daemon. Jalur ICAS (choch + sesi Asia/London) tetap utuh di
`src/strategy/icas_strategy.py` — tidak dihapus. *Catatan: riset setahun
menunjukkan ICAS PF 0,92 < acak — rollback hanya untuk investigasi.*

---

## 9. QC opsional: bukti paritas (verifikasi ulang)

Bot live memakai `g4_signal_at` (replika `signal_at(mode="mtf")` engine
riset). Bukti paritas bar-per-bar sudah tersimpan di
`reports/g4_parity_20250901_20260901.txt` (IDENTIK, 0 mismatch). Untuk
verifikasi ulang di mesin Anda (butuh ±11 menit):

```bat
python research\g4_parity_check.py --out reports\g4_parity_20250901_20260901.txt
```

(4 pass: geometri murni · guard spread · jalur penuh evaluate · burn-in EMA
jendela 5.000 bar. Exit code 0 = IDENTIK.)

---

## 10. Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| `MetaTrader5 package not available` | Belum `pip install MetaTrader5`, atau jalan di non-Windows. |
| `MT5 login failed` | Cek MT5_LOGIN/PASSWORD/SERVER; akun demo Exness aktif; MT5_PATH benar. |
| `⚠️ Candle H1 live tidak tersedia` | Terminal belum sync historis — buka chart H1 XAUUSDm sekali, tunggu, atau perbesar Max bars. |
| `⚠️ [G4] Riwayat M5/M15/H1 belum cukup` | Baru start / histori minim. Butuh ≥350 M5, ≥20 M15, ≥260 H1. Terminal dengan histori normal terlewati dalam menit. |
| `Order rejected: Spread ($x.xx) exceeds $1.20` | Guard bekerja (jam rollover/news). Sinyal berikutnya tetap diproses. |
| Tidak ada sinyal berjam-jam | Normal — G4 butuh konfluensi 4 lapis; rerata ~3–4 sinyal/hari bursa. |
| `python: No module named pandas` | Venv belum aktif → `.venv\Scripts\activate`. |

**Mode simulasi (tanpa MT5):** daemon bisa start, tetapi jalur G4 butuh
candle M15/H1 live — tanpa MT5 frame kosong dan sinyal di-skip. G4 hanya
bermakna pada mode live/demo dengan terminal MT5. (Ini by design, bukan bug.)

---

## 11. Checklist sebelum REAL account

- [ ] Demo ≥ 2–4 minggu; bandingkan frekuensi/WR dengan ekspektasi (±103
      entry/bln, WR ~73% — toleransi sampling ±5%).
- [ ] Slippage entry di jurnal (`slippage_usd`) konsisten dengan asumsi
      $0,10; jika rutin > $0,50, hentikan dan evaluasi.
- [ ] DD demo < 20%; psikologis siap dengan 4–5 loss beruntun (WR 73%).
- [ ] Modal sedemikian sehingga 1% = risiko yang nyaman; lot minimum
      broker cocok (0,01).
- [ ] Ingat batas validitas: edge terukur 2023–2026; 2021–22 merah.

---

*Dokumen pendukung: `LAPORAN_TUNING_SCALPING.md` (diagnosis + grid G),
`reports/g4_parity_20250901_20260901.txt` (bukti paritas),
`reports/multiseed_mtf_scalp_20250901_20260901_risk100.txt` (Monte-Carlo).*
