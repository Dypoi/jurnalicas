# 🕵️ LAPORAN AUDIT FORENSIK KODE — `model_icas_bot`

**Repo:** `Dypoi/testagent` → `model_icas_bot` (branch `main`, commit `f8b1b18`)
**Tanggal audit:** 25 Agustus 2026
**Lingkup:** Full audit statik + dinamis seluruh 20 file (kompilasi, unit test, eksekusi backtest, proof-of-concept replikasi error produksi, mock MetaTrader5)
**Pemicu audit:** Error produksi `code 10016 (Invalid stops)` pada tiket `4970342345`

---

## 1. RINGKASAN EKSEKUTIF

| Kategori | Hasil |
|---|---|
| File diaudit | 20 (Python, BAT, HTML, konfigurasi) |
| Sintaks / kompilasi | ✅ Semua lolos `py_compile` |
| **Bug ditemukan** | **14** (2 Kritis, 3 Tinggi, 4 Sedang, 5 Rendah) |
| **Error Anda (10016)** | ✅ **Root cause ditemukan & berhasil direproduksi — bug logika, bukan error broker acak** |
| Versi perbaikan | ✅ Tersedia di folder **`model_icas_bot_FIX/`** — semua verifikasi hijau (9/9 unit test + 5/5 tes mock MT5 + CLI & backtest OK) |

**Kesimpulan utama:** Sistem secara arsitektur rapi (pemisahan strategy/execution/backtest bagus, mutex 1-sinyal-1-posisi berfungsi, anti-repaint benar), **tetapi terdapat bug matematis pada logika Breakeven+ yang membuat bot memerintahkan SL menembus harga pasar saat spread lebar — inilah penyebab pasti error 10016 Anda.**

---

## 2. 🔴 ROOT CAUSE ERROR ANDA — `[BUG K-01]` 10016 "Invalid stops"

### Log produksi Anda
```
2026-08-25 08:40:32 [HEARTBEAT] ... | Spread: 260.0 pts | Posisi Aktif: 1
2026-08-25 08:40:32 [WARNING] Notice on modifying SL for ticket 4970342345: code 10016 (Invalid stops)
```

### Rantai kejadian (forensik baris per baris)

**`icas_daemon.py` (kode lama):**
```python
be_offset = max(0.10, (sp_val * 0.01) + (config.BE_PROFIT_OFFSET_PIPS * 0.10))
# Spread 260 pts  ->  be_offset = max(0.10, 2.60 + 0.30) = $2.90
```
Sementara **trigger** Early BE+:
```python
if not pos.get("be_set") and fav_pips >= config.EARLY_BE_TRIGGER_PIPS:   # cukup +10 pips = $1.00 !
```

Jadi bot **memicu BE+ saat harga baru bergerak $1.00**, tetapi mencoba memasang SL sejauh **$2.90 dari entry**:

| Posisi | Entry | Harga pasar saat trigger | SL yang diminta | Aturan MT5 | Hasil |
|---|---|---|---|---|---|
| BUY | 4667.80 | Bid ≈ 4668.80 (+$1.00) | **4670.70** | SL BUY wajib **< Bid** | ❌ **10016** melampaui pasar $1.90 |
| SELL | 4668.90 | Ask ≈ 4667.90 (−$1.00) | **4666.00** | SL SELL wajib **> Ask** | ❌ **10016** melampaui pasar $1.90 |

### Bukti reproduksi (Proof-of-Concept dijalankan saat audit)
```
[BUY]  Entry=4667.80 | Bid saat trigger=4668.80
       SL baru diminta = 4670.70  ->  SL $1.90 DI ATAS pasar -> 10016 ✔ TERREPRODUKSI
[SELL] Entry=4668.90 | Ask saat trigger=4667.90
       SL baru diminta = 4666.00  ->  SL $1.90 DI BAWAH pasar -> 10016 ✔ TERREPRODUKSI
```

**Penjelasan awam:** *"Bot menyuruh broker memasang rem darurat (SL) di seberang posisi mobil — padahal rem harus selalu dipasang di belakang mobil."* Broker menolak 10016 setiap polling 3 detik sampai harga menjauh $2.90 dari entry. Ini juga menjelaskan kenapa error muncul tepat saat **spread 260 pts** — rumus `be_offset` ikut membesar bersama spread.

**Dampak sekunder yang sama root-nya:** handler TP1 & trailing memakai `be_offset` yang sama, dan `modify_sl()` lama **tidak memeriksa** sisi pasar / `SYMBOL_TRADE_STOPS_LEVEL` / freeze level sama sekali sebelum `order_send`.

### ✅ Perbaikan (sudah diterapkan & terverifikasi)
1. **`icas_daemon.py`** — offset di-cap: `be_offset = min(lock_target, max($0.30, trigger_dist − $0.10))` → saat spread 260 pts offset menjadi **$0.90** (bukan $2.90), di bawah jarak trigger $1.00. Ditambah pemeriksaan clearance terhadap harga live sebelum kirim.
2. **`mt5_bridge.py`** — guard baru `get_min_stop_distance()` (broker stops level + spread + buffer 20 poin) dan `_validate_sl_side()`: SL ilegal **ditahan aman ("deferred")** dan dicoba ulang otomatis saat harga sudah menjauh — **tanpa error ke broker, tanpa spam log warning.**
3. Retcode `10016` kini dipetakan ke *retry-per-poll* yang bersih.

**Hasil verifikasi mock MT5 (5/5 PASS):**
```
✅ PASS - Server menolak SL 4670.70 dgn 10016 (bug asli terbukti)
✅ PASS - Bridge menahan SL ilegal 4668.70 (tidak dikirim ke server)
✅ PASS - Setelah Bid naik ke 4670.00, SL 4668.70 berhasil dikunci
✅ PASS - SL posisi di server kini = 4668.70
✅ PASS - Spread normal 26 pts: BE+ offset $0.56 langsung diterima
```

---

## 3. TEMUAN LENGKAP (peringkat severity)

### 🔴 KRITIS
| ID | File | Temuan | Status |
|---|---|---|---|
| K-01 | `icas_daemon.py` + `mt5_bridge.py` | **10016 Invalid stops**: offset BE+ ($2.90) > jarak trigger ($1.00); SL menembus pasar | ✅ **DIPERBAIKI** |
| K-02 | `icasbot` + `run_backtest.py` / `run_dashboard.py` | **2 dari 3 perintah master CLI crash**: `icasbot --backtest` → `ImportError: cannot import name 'main'`; `icasbot --dashboard` → `ImportError: cannot import name 'run_server'`. (Tereproduksi saat audit.) | ✅ **DIPERBAIKI** (kedua runner kini punya fungsi `main()`) |

### 🟠 TINGGI
| ID | File | Temuan | Status |
|---|---|---|---|
| T-01 | `icas_strategy.py` vs `engine.py` | **Sinyal live ≠ sinyal backtest**: window CHoCH live `iloc[idx-6:idx]` (6 bar) vs engine `high5[i-6:i-1]` (5 bar). Live dan backtest bisa mengambil keputusan berbeda pada candle yang sama. | ✅ **DIPERBAIKI** (live disamakan dengan engine) |
| T-02 | `test_icas_audit.py` | **"Audit suite" bawaan repo sendiri MERAH: 3/7 test FAIL** (ekspektasi TP 40/30% & BE $0.10 usang vs config 30/25/25/20 & $0.30). Suite lama memberi rasa aman palsu — siapa pun yang menjalankannya melihat kegagalan. | ✅ **DIPERBAIKI** (kini 7/7 OK) |
| T-03 | `test_be_15_pips.py` | 2/2 test FAIL (ekspektasi SL 3300.10/3299.90 padahal offset $0.30 → 3300.30/3299.70); juga **memutasi config global** `EARLY_BE_TRIGGER_PIPS` (side-effect). | ✅ **DIPERBAIKI** (kini 2/2 OK) |

### 🟡 SEDANG
| ID | File | Temuan | Status |
|---|---|---|---|
| S-01 | `mt5_bridge.py` | `mt5.order_send()` bisa mengembalikan `None` → `res.retcode` melempar **AttributeError → daemon crash total** saat koneksi broker goyah. | ✅ **DIPERBAIKI** (guard None di semua jalur order_send) |
| S-02 | `mt5_bridge.py` | Mutex & tracking posisi memakai **semua posisi pada simbol** (`positions_get` tanpa filter magic) — trade manual/EA lain di simbol yang sama ikut dihitung/dikelola. | ✅ **DIPERBAIKI** (filter `magic == 777404`) |
| S-03 | `icas_daemon.py` | **State hanya di memori** (`tp1_hit/be_set/trail_step`, counter harian). Restart bot di tengah posisi → flag reset → **TP1 bisa dieksekusi ganda** dan trailing kacau. | ⚠️ Dicatat — rekomendasi: persist state ke JSON / rebuild dari `history_deals_get` (lihat §5) |
| S-04 | `icas_strategy.py` | **Sizing mengabaikan spread**: risiko dihitung hanya dari SL $2.00. Pada spread 260 pts biaya riil ≈ **$2.60 → risiko efektif ±11.5%** pada sizing 2.5 lot (loss saat SL ≈ $1,150 vs target $500). Spread guard 350 masih membolehkan kondisi ini. | ⚠️ Dicatat — rekomendasi §5 (TIDAK diubah demi konsistensi backtest↔live) |

### 🔵 RENDAH
| ID | File | Temuan | Status |
|---|---|---|---|
| R-01 | `src/backtest/engine.py` | **Bias optimis intrabar**: dalam 1 bar, TP/profit diproses (pakai `high`) **sebelum** SL (`low`), dan trailing naik memakai `max_favorable` sebelum cek stop periode yang sama → hasil backtest lebih mulus dari kenyataan. Juga entry di harga *close* bid tanpa slippage, SL live dihitung dari bid padahal BUY terisi di ask (SL efektif lebih jauh sesuai spread). | ⚠️ Rekomendasi §5 |
| R-02 | `src/dashboard_app.py` | Dashboard terbuka di `0.0.0.0:5000` **tanpa autentikasi** — telemetri akun (login, balance, equity) bisa dilihat siapa pun di jaringan. `datetime.utcnow()` deprecated di Python 3.12+ (warning saja). Server time di-hardcode UTC+3 → bisa meleset 1 jam saat musim dingin (saat ini tidak berdampak karena `USE_KILLZONE=False`). | ⚠️ Rekomendasi §5 |
| R-03 | Pembulatan volume | `round(0.625, 2)` = **0.62** (round-half-even Python) → total partial close menyimpang ±0.01 lot dari rasio desain. Tidak fatal. | ✅ Didokumentasikan di test |
| R-04 | `README.md` | Dokumentasi **usang**: menyebut model 2-tier (TP1 40% +30p, TP2 30% +60p, BE+@20p, max 3 trade/hari, WR 75.35%), sementara kode sekarang 4-tier (30/25/25/20, BE+@10p, unlimited). Hasil audit backtest model **saat ini**: Juni 2026 = 188 trade, WR murni 61.17%, Non-Loss 79.79%, PF 3.05. | ⚠️ Perlu rewrite README |
| R-05 | Repo hygiene | `__pycache__/` (file `.pyc`) ikut ter-commit; tidak ada `.gitignore`; `compare_*.py` berisi parameter model lama (artefak riset usang berisiko menyesatkan). | ✅ `.gitignore` ditambahkan di versi FIX |

**Catatan "by design" (bukan bug):** `MetaTrader5` tidak ada di `requirements.txt` karena paket itu Windows-only — sudah diinstal terpisah via `install_requirements.bat`. Mode simulasi sengaja jika paket tidak tersedia. ✅ OK.

**Yang sudah diperiksa & dinyatakan SEHAT:** mutex lock 1-posisi (test 6 PASS), fallback filling mode FOK/IOC/RETURN (anti-10030), redundancy guard anti-10025, normalisasi lot/price sesuai spec simbol, polling candle tertutup `len-2` (zero repaint/lookahead), semua guard `None` pada `symbol_info_tick / copy_rates / positions_get / account_info`, template dashboard memakai path relatif.

---

## 4. VERSI PERBAIKAN — `model_icas_bot_FIX/` (siap deploy)

**File yang diubah (8 + 2 baru):**

| File | Perubahan |
|---|---|
| `icas_daemon.py` | Fix offset BE+ (cap pada jarak trigger) + clearance harga live + tidak ada lagi klaim sukses palsu |
| `src/execution/mt5_bridge.py` | Guard 10016 berlapis (stops level + sisi pasar + freeze), guard `None` order_send, filter magic number, pre-validasi SL saat entry |
| `src/strategy/icas_strategy.py` | Window CHoCH disamakan dengan engine backtest |
| `icasbot` | `--backtest` & `--dashboard` kini benar-benar jalan |
| `run_backtest.py`, `run_dashboard.py` | Dibungkus fungsi `main()` |
| `test_icas_audit.py`, `test_be_15_pips.py` | Ekspektasi disesuaikan config aktual |
| `.gitignore` ✚ (baru) | Abaikan `__pycache__`, `.env`, log |
| `verify_fix_10016.py` ✚ (baru) | Tes regresi permanen untuk bug 10016 (mock MT5) |

### Matriks verifikasi
| Uji | Sebelum | Sesudah |
|---|---|---|
| `python -m py_compile` (semua) | ✅ | ✅ |
| Reproduksi 10016 (PoC matematis) | ❌ terbukti bug | ✅ tertahan & auto-retry (5/5 mock PASS) |
| `test_icas_audit.py` | ❌ **FAIL** (3/7) | ✅ **7/7 OK** |
| `test_be_15_pips.py` | ❌ **FAIL** (2/2) | ✅ **2/2 OK** |
| `icasbot --backtest` | ❌ ImportError | ✅ Jalan — hasil **identik** engine lama (188 trade, PF 3.05) |
| `icasbot --dashboard` | ❌ ImportError | ✅ Server start |
| `icasbot --live` | ✅ | ✅ (tak berubah) |
| `test_new_icas_tp_be.py` | ✅ | ✅ identik (non-regresi) |

---

## 5. REKOMENDASI TINDAK LANJUT (belum diterapkan — keputusan Anda)

1. **[Prioritas] Persistensi state daemon** (`S-03`): simpan `{ticket: {tp1_hit, be_set, trail_step, max_fav}}` ke `state.json` setiap perubahan + muat ulang saat start; atau rebuild status TP dari `history_deals_get` (komentar deal `"Model Icas Partial TP"`). Menghilangkan risiko double partial-close pasca-restart.
2. **[Prioritas] Koreksi sizing vs spread** (`S-04`): hitung risiko dari `SL + spread + slippage`, misal `sl_eff = 2.00 + spread_usd + 0.30`; atau turunkan `MAX_SPREAD_POINTS` ke ±100–150 saat mode unlimited. Update engine & live **bersamaan** agar tetap konsisten.
3. **Backtest lebih konservatif** (`R-01`): proses SL **sebelum** TP dalam bar yang sama (mode pesimis) atau pakai data M1 untuk sequencing intrabar; tambahkan slippage eksekusi.
4. **Amankan dashboard** (`R-02`): bind ke `127.0.0.1` bila dipakai lokal, atau tambahkan token/Basic Auth bila diakses LAN; jangan expose pola 0.0.0.0 di VPS publik.
5. **Rewrite README** (`R-04`) sesuai arsitektur 4-tier aktual; arsipkan `compare_*.py` ke folder `research/` karena parameternya usang.
6. **Sinkronnya waktu broker** (`R-02`): pakai `SERVER_TIME_OFFSET_HOURS` (bukan hardcode UTC+3) dan perhitungkan DST EET.

---

## 6. CARA DEPLOY KE REPO ANDA

```bash
cd testagent
# Opsi A — replace seluruh folder:
git rm -r --cached model_icas_bot
cp -r /home/user/model_icas_bot_FIX model_icas_bot
git add model_icas_bot && git commit -m "Fix 10016 Invalid stops (BE+ offset cap + SL validation), CLI ImportError, strategy/engine parity, test suite" && git push

# Opsi B — hanya 8 file yang berubah (lihat tabel §4).
```

**Checklist pasca-deploy:** jalankan `python verify_fix_10016.py` & `python test_icas_audit.py` di mesin Windows Anda → semua harus hijau → aman untuk `run_live.bat`.

---

## 7. ✚ BAB TINDAK LANJUT — SEMUA REKOMENDASI §5 TELAH DIIMPLEMENTASIKAN

*(25 Agu 2026 — semua perubahan di folder `model_icas_bot_FIX/`)*

### 7.1 Persistensi State (S-03) ✅
Modul baru `src/state_store.py` (JSON atomik, `os.replace`). Daemon menyimpan state posisi
setiap siklus, memulihkannya saat restart, dan merebuild dari riwayat deal MT5
(`history_deals_get`, comment `"Model Icas Partial TP"`) jika file hilang. Counter harian ikut
terpersist. **Risiko double partial-close pasca restart: DITUTUP.** Verifikasi:
`verify_state_persistence.py` → **14/14 PASS** (termasuk simulasi restart & file hilang).

### 7.2 Sizing sadar spread + slippage (S-04) ✅
`INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK=True` + `SLIPPAGE_USD=0.10` di `config.py`.
Rumus efektif: `risiko_eff = SL($2.00) + spread + slippage`. Contoh dampak nyata (spread 260 pts):
lot turun dari **2.50 → 1.06**, risiko riil terkunci tepat 5% (sebelumnya efektif ±11.5%).
Diterapkan **serentak** di `strategy.py` (live, via parameter `spread_usd`) dan engine backtest.

### 7.3 Engine Backtest v2 Konservatif (R-01) ✅ — DAN TEMUAN BESAR
Engine ditulis ulang total (manajemen posisi parametrik 1-arah, tanpa duplikasi blok):
- **Konservatif (default):** SL dicek **dulu** dalam bar; kenaikan SL (BE/step/trailing) baru
  efektif bar berikutnya; entry kena slippage merugikan; spread guard dihormati (hanya 3 bar
  dari 75.447 yang terdampak).
- **Legacy:** tersedia 1:1 via flag — `verify_engine_parity.py` membuktikan **parity BITWISE**
  dengan engine asli (4/4 PASS: kurva ekuitas, hasil, trailing identik persis).

**🚨 TEMUAN MATERIAL — klaim performa lama tidak bertahan pada mode pesimis:**

| Periode (fixed $500) | Engine | Trades | W/BE/L | Non-Loss | PF | Net |
|---|---|---|---|---|---|---|
| Jan–Jun 2026 | Legacy (optimis) | 1359 | 864/229/266 | 80.43% | 3.88 | +$391,187.88 |
| Jan–Jun 2026 | **Konservatif** | 968 | 311/43/614 | 36.57% | **0.81** | **−$57,846.01** |
| Jun 2025–Jun 2026 | Legacy (optimis) | 2750 | 1450/664/636 | 76.87% | 2.37 | +$453,032.50 |
| Jun 2025–Jun 2026 | **Konservatif** | 1852 | 631/205/1016 | 45.14% | **0.87** | **−$64,637.81** |

Mayoritas "alpha" backtest lama adalah **artefak bias urutan intrabar** (asumsi high dulu
baru low dalam candle yang sama). Kinerja riil berada di antara PF 0.81–3.88 dan tidak bisa
ditentukan dari data M5 saja. **Rekomendasi tegas: validasi data M1/tick + forward test demo
1–3 bulan sebelum modal riil.** README telah ditulis ulang dengan tabel kebenaran ini.

### 7.4 Pengamanan Dashboard (R-02) ✅
- Token auth opsional (`ICAS_DASH_TOKEN`) untuk semua route; template JS mempropagasi `?token=`.
  Tervalidasi live: **401 tanpa token, 200 dengan token**.
- Warning startup jika bind `0.0.0.0` tanpa token; fix `datetime.utcnow()` deprecated;
  jam server diturunkan dari `SERVER_TIME_OFFSET_HOURS` (aman DST), bukan hardcode UTC+3.

### 7.5 Kebersihan Repo (R-04/R-05) ✅
`README.md` ditulis ulang (model 4-tier aktual + angka jujur); `compare_*.py` diarsip ke
`research/` (+ path shim, masih jalan dari root); `.gitignore` kini mengabaikan
`__pycache__/`, `.env`, `state/`, log.

### 7.6 Matriks Verifikasi Akhir Tindak Lanjut
| Uji | Hasil |
|---|---|
| `verify_engine_parity.py` (legacy bitwise) | ✅ **4/4 PASS** |
| `verify_fix_10016.py` (mock MT5) | ✅ **5/5 PASS** |
| `verify_state_persistence.py` | ✅ **14/14 PASS** |
| `test_icas_audit.py` / `test_be_15_pips.py` | ✅ **7/7 + 2/2 OK** |
| `icasbot --backtest` (konservatif & `--legacy`) | ✅ jalan, mode tercetak |
| Dashboard token auth | ✅ 401 / 200 sesuai |
| Kompilasi semua file | ✅ |
| `research/*.py` dari root | ✅ jalan |

**Status akhir: 2 Kritis + 3 Tinggi + 4 Sedang (S-01, S-02) + 5 Rendah = SEMUA DITUTUP atau
dimitigasi**; keputusan strategi (lanjut live / riset ulang edge) kini berada di tangan Anda
dengan data yang jujur.

---

## 8. 🎲 VALIDASI GRANULAR — JAWABAN "PF RIIL-NYA BERAPA?"

*(Lanjutan R-01 — 25 Agu 2026)*

### 8.1 Ketersediaan data granular
Repo hanya berisi **M5/M15/M30/H1** — tidak ada M1/tick. Akses unduhan tick publik
(Dukascopy `.bi5`) dari lingkungan audit **diblokir (HTTP 429 persisten setelah retry)**,
sehingga validasi data-riil granular tidak dapat dilakukan di sisi auditor. Dua solusi
dibangun sebagai gantinya (keduanya sudah TERUJI dan berada di `model_icas_bot_FIX/research/`).

### 8.2 Alat 1 — `monte_carlo_intrabar.py` (stokastik, di atas data Anda)
Untuk setiap bar ambigu (SL **dan** BE/TP tersentuh dalam 1 candle), urutan kejadian
di-sample dengan probabilitas berbanding terbalik jarak level dari harga OPEN
(heuristik jarak / Brownian-bridge ringan). Insight kunci model: jika SL tersentuh maka
posisi pasti keluar pada bar itu (SL hanya naik), sehingga satu-satunya ketidakpastian
sejati adalah **URUTAN** TP/BE-vs-SL — persis yang di-sample.

| Window | N sim | PF median | CI90% PF | Net median | P(PF>1) |
|---|---|---|---|---|---|
| Jan–Jun 2026 (fixed) | 2000 | **1.80** | [1.70 – 1.90] | +$124,800 | 100% |
| Jun 2025–Jun 2026 (fixed) | 1500 | **1.56** | [1.51 – 1.62] | +$171,957 | 100% |

Non-Loss rate realistis: **~67%** (bukan 80%+ klaim lama).

**Kesimpulan lintas-model (3 metode independen):**

| Metode | Sifat | PF 6 Bulan |
|---|---|---|
| Legacy optimis | Batas atas ekstrem | 3.88 |
| **Monte Carlo (jarak-weighted)** | **Estimasi titik terbaik (model)** | **1.80 (median)** |
| Konservatif pesimis | Batas bawah ekstrem | 0.81 |

> Interpretasi profesional: strategi **kemungkinan besar masih memiliki edge** (seluruh
> spektrum MC > 1.0 pada kedua window), tetapi kekuatannya **jauh di bawah klaim lama**
> (PF realistis ≈ 1.5–1.9, bukan ~3.9). Angka 0.81 adalah asumsi "setiap bar jahat" — ekstrem
> yang tidak realistis; angka 3.88 adalah asumsi "setiap bar baik" — sama tidak realistisnya.
> Jawaban definitif memerlukan data granular per-feed broker (alat di 8.3).

### 8.3 Alat 2 — `validate_granular.py` (definitif, pakai M1/tick broker Anda)
Manajemen posisi dieksekusi pada timeframe lebih halus dalam URUTAN WAKTU asli —
tanpa satu pun asumsi urutan intrabar. Plumbing tervalidasi regresi:
`--fine xauusd_m5.csv` mereproduksi mode konservatif **persis**
(Jun 2026: 134 trades | NLR 35.82% | PF 0.73 | Net −$11,656.75 — identik; toleransi ±2 trade
pada window 6 bulan karena nuansa re-entry dalam bar yang sama).

**Yang perlu Anda lakukan untuk jawaban definitif:**
1. Di MT5: *View → Symbols → XAUUSDm → Bars → pilih M1 → Request → Export CSV*
   (header: `time,open,high,low,close,...`) ke `data/historical/xauusd_m1.csv`
2. Jalankan: `python research/validate_granular.py --fine data/historical/xauusd_m1.csv`
   (untuk range panjang, unduh M1 via *History Center* secukupnya; tick = paling definitif)

### 8.4 Rekomendasi final riset
1. Ekspor M1 broker → jalankan 8.3 (kebenaran per-feed).
2. Jika mempertahankan strategi: kalibrasi ulang parameter (SL/TP/trigger BE) pada hasil
   granular/MC — bukan pada angka engine optimis.
3. Forward test demo ≥ 1–3 bulan; baru evaluasi live kecil.

### 8.5 Artefak baru pada tindak lanjut ini
| File | Fungsi |
|---|---|
| `research/monte_carlo_intrabar.py` | Distribusi PF/Net/NLR (N sim, weighted-order sampling) |
| `research/validate_granular.py` | Sequencing definitif dari CSV granular broker |
| Laporan §8 (bab ini) | Dokumentasi metodologi & temuan |

### 8.6 🏁 VALIDASI DEFINITIF PADA FEED BROKER RIIL (data M1 milik Anda, 25 Agu 2026)

**Input:** `XAUUSDm_M1_202605141337_202608251430.csv` (100.000 bar, ekspor MT5 Anda)
**Window:** 2026-05-14 → 2026-08-25 (±3,4 bulan | 908–1.143 trade | sinyal M5 dibangun dari M1 yang sama → 100% satu feed)

**Temuan forensik sepanjang jalan:**
1. **M5 repo ≠ feed live Anda.** Deviasi median ~$15 (0/10.448 bar cocok); lag-fit terbaik anomali +175 menit; harga repo M5 2-digit vs akun Anda 3-digit. ➜ Semua hasil di 8.2/8.3 (PF median MC 1.56–1.80) **berlaku untuk feed repo, belum tentu akun Anda**.
2. **Unit spread berbahaya.** Simbol XAUUSDm Anda 3-digit → point $0.001 → `SPREAD=260` = **$0.26** (bukan $2.60!). Kode lama meng-hardcode `×0.01` (bias biaya **10×**). Sudah diperbaiki di engine/validator/daemon (`get_point()` untuk live; `infer_price_point()` untuk CSV — termasuk fix subtle bug `np.allclose` rtol pada harga ribuan USD).
3. **Model stokastik pun masih terlalu ramah.** MC weighted-distance memberi PF 1.30, kenyataan M1 memberi 0.80 — ordering nyata lebih jahat dari asumsi jarak (momentum & wick).

**Hasil per model (feed riil, spread benar $0.26, slippage $0.10, sizing risk-aware):**

| Model | Trades | W/BE/L | Non-Loss | PF | Net (fixed $500) |
|---|---|---|---|---|---|
| Legacy optimis (referensi) | 1143 | 653/269/221 | 80.66% | 2.22 | +$152,503 |
| Monte Carlo (median, N=1000, CI90% 1.23–1.37) | ~713 | — | ~66.9% | 1.30 | +$34,993 |
| **🔬 M1 SEQUENCING — DEFINITIF** | **908** | **289/269/350** | **61.45%** | **0.80** | **−$34,477** |
| Konservatif M5 (cross-check) | 712 | 259/55/398 | 44.10% | 0.75 | −$49,503 |

**Verdict — bulan hijau: 0 dari 4. Pada feed & periode live Anda, strategi DENGAN parameter sekarang ($2 SL / TP1 +$2 / trigger BE +$1) adalah mesin pembakar spread: biaya $0.26 = 13% dari jarak SL setiap sisi, dan 908 trade riil membuktikan ekspektasi negatif.**

> Rekomendasi tindakan segera:
> 1. **STOP live** sampai parameter dikalibrasi ulang (bot Anda terlihat jalan live per log 25 Agu).
> 2. Jika lanjut scalping emas: besarkan geometri — SL ≥ $4–6 & TP1 ≥ $4 (biaya spread < 7% dari SL), lalu **ulangi validasi M1** (tinggal jalankan ulang `validate_granular.py` setelah edit `config.py`).
> 3. **Verifikasi tipe akun**: simbol `XAUUSDm` + quote 3 digit — cek *Specification → Contract size*; kalkulasi lot bot mengasumsikan 100 oz/lot (akun Standard). Jika ini akun **Cent**, sizing salah total.
> 4. Spread filter: M1 menunjukkan spread mean 257 pts dengan spike 690 — pertimbangkan `MAX_SPREAD_POINTS` lebih ketat atau hindari jam spike.
> 5. Untuk range lebih panjang: scroll-back chart M1 (Max bars = Unlimited agar cache penuh) → export ulang (range kini dibatasi cache terminal, bukan server).

---

## 9. 🎯 KALIBRASI PARAMETER — GRID-SEARCH WALK-FORWARD DI ATAS SEQUENCING M1 DEFINITIF

> Permintaan pengguna (25 Agu 2026): *"kalibrasi ulang parameter (grid-search SL/TP/BE di atas validasi M1 definitif) sampai PF-nya positif"*. Diselesaikan pada hari yang sama dengan disiplin anti-overfitting penuh. **Hasil: konfigurasi baru lolos gerbang out-of-sample & konsistensi bulanan, dan kini sudah diterapkan ke `config.py`.**

### 9.1 Metodologi & disiplin yang dipakai

| Prinsip | Implementasi |
|---|---|
| Optimasi HANYA di window TRAIN | TRAIN = 2026-05-14 → 2026-07-15 (belum pernah dilihat saat memilih pemenang) |
| Konfirmasi out-of-sample | TEST = 2026-07-15 → 2026-08-25 14:30; kandidat hanya layak bila **TEST PF ≥ 1.0** |
| Konsistensi lintas waktu | Gerbang tambahan: **semua 4 bulan (Mei s.d. Agu) harus hijau** di window penuh |
| Kekuatan statistik | Minimal 100 trades/kombo; finalis ≥ 300 trades |
| Keluarga parameter sederhana | TP dinyatakan sebagai kelipatan SL (B=1/2/3×SL, C=1.25/2.5/3.75×SL, dst.) agar tidak "mencari angka ajaib" |
| Executor identik dengan validator | Grid berjalan di atas `src/backtest/granular_sequencer.py` — inti yang sama persis dengan `research/validate_granular.py` (regresi byte-eksak: 908 t / PF 0.80 / −$34.476,77 pada config lama) |
| Biaya & sizing realistis | Spread riil per bar (mean ≈ $0.26) + slippage $0.10 per sisi, dimasukkan ke dalam risiko; risiko tetap $500/trade (5% × $10.000) |

Ruang grid utama: **SL ∈ {20…100 pips} (7) × struktur TP {A,B,C,D} (4) × BE ∈ {10,15,20,30,40,9999=OFF} (6) = 168 kombinasi** (~5 detik). Grid ekstensi: **SL ∈ {100,120,150,200,300} × struktur {B,C,D,E} × BE ∈ {9999,40,60} = 60 kombinasi** — dibuka karena 15 kandidat terbaik grid utama semuanya mentok di batas SL=100 (tanda optimum berada di luar grid awal).

### 9.2 Temuan utama

1. **Config lama rugi, dan tetangga terdekatnya pun rugi.** Baseline (SL20 / struktur warisan / BE10): TRAIN PF **0.74** (514 tr, −$26.3k), TEST PF **0.90** (401 tr, −$7.4k); semua varian tetap di SL20 gagal (TEST PF 0.83–0.84). Profitabilitas baru mulai **muncul** sejak SL ≥ 30–40 pips dengan struktur yang sama (TEST PF dari 1.00 merangkak ke 1.73 di SL60) — bukti bahwa faktor penentunya adalah **perbandingan ukuran SL vs spread**, persis seperti akar masalah di §8.6, dan evolusi naturalnya terus naik menuju zona robust di bawah.
2. **Zona robust yang menguntungkan: SL 150–200 pips ($15–20)** dengan struktur TP **B atau C**, dan **Early BE+ dimatikan (9999) atau dipicu sangat terlambat (60p)**. Semua 12 kandidat TOP-TRAIN lolos uji TEST PF ≥ 1.0.
3. **Early BE+ secara konsisten MENURUNKAN PF** pada rezim ini: makin dini SL digeser ke BE, makin sering posisi dicukur sebelum tren bekerja. Ini menjawab mengapa NLR 61% di config lama tetap rugi — "aman dipandang" ≠ "untung di ekspektasi".
4. **Jebakan overfitting (ditolak secara eksplisit):** kombinasi SL ekstrem + BE OFF tampak spektakuler di satu paruh tetapi instabil / tenaga statistiknya lemah — mis. SL150/E: TRAIN 4.64 vs TEST 30.67 (artefak keberuntungan); SL200/E: 10.12 vs 1.16; SL300/D: 12.40 vs **0.51**; SL300/E: 0.30 vs 0.00. Trade count anjlok (109–180) dan profit bertumpu pada segelintir winner besar di satu rezim rally. **Ini bukan edge — ini noise berpakaian backtest.**

### 9.3 Tabel finalis (window penuh 2026-05-14 → 08-25, risiko tetap $500/trade)

| Preset | SL / TP (pips) | BE+ | Trades | NLR¹ | PF | Net | DD² | Bulan hijau | Ekspektasi/trade | Train/Test PF |
|---|---|---|---|---|---|---|---|---|---|---|
| **F2 — TERPILIH** | **150 / 187.5-375-562.5 (C)** | **OFF** | **326** | **37.4%** | **2.08** | **+$38,067** | **12.8%** | **4/4** | **+$117** | **1.97 / 2.25** |
| F1 | 150 / 150-300-450 (B) | OFF | 326 | 46.0% | 1.98 | +$36,798 | 13.3% | 4/4 | +$113 | 1.88 / 2.13 |
| F3 | 200 / 250-500-750 (C) | OFF | 306 | 19.6% | 2.75 | +$23,954 | 16.9% | 4/4 | +$78 | 2.30 / 4.07 |
| F4 | 200 / 200-400-600 (B) | 60p (terlambat) | 355 | **83.7%** | 1.77 | +$22,380 | 20.1% | 4/4 | +$63 | 1.63 / 2.01 |

¹ NLR = Non-Loss Rate (W + BE). ² DD = max drawdown terhadap ekuitas berjalan pada risiko $500/trade.
Rincian per bulan (bukti tersimpan di `reports/finalist_detail.txt`):

```
F2 (terpilih):  Mei +$9,273 | Jun +$6,564 | Jul +$14,011 | Agu +$8,218   → 4/4 hijau
F1           :  Mei +$9,152 | Jun +$6,523 | Jul +$13,391 | Agu +$7,733   → 4/4 hijau
F3           :  Mei +$7,529 | Jun +$3,130 | Jul +$8,699  | Agu +$4,595   → 4/4 hijau
F4           :  Mei +$5,690 | Jun +$3,556 | Jul +$7,753  | Agu +$5,380   → 4/4 hijau
```

**Mengapa F2:** ekspektasi per trade tertinggi (+$117), drawdown terendah (12.8%), PF terbaik kedua (2.08 lolos TRAIN→TEST tanpa anomali), dan profil WinRate 37% masih "manusiawi" dijalankan (F3 butuh mental baja dengan 80% trade loss). **F4 disediakan sebagai preset alternatif** bagi yang mengutamakan kenyamanan psikologis (NLR 83.7%, hanya 58 trade benar-benar rugi) dengan harga PF lebih rendah.

### 9.4 Perubahan karakter strategi (penting dipahami)

Dengan SL 150p/TP C, bot **tidak lagi scalper** — ia menjadi **intraday-swing**: ~95 trade/bulan (dari ~270), TP1 $18.75 / TP2 $37.50 / TP3 $56.25, dan mayoritas profit datang dari runner trailing. Kelemahan lama (spread $0.26 memakan 13% dari SL $2 per sisi) hilang: biaya kini hanya **~1.7% dari SL**.

### 9.5 Konfigurasi diterapkan ke `config.py` (25 Agu 2026)

```python
STOP_LOSS_PIPS       = 150.0        # sebelumnya 20.0
TP1/2/3_PIPS         = 187.5 / 375.0 / 562.5   # sebelumnya 20/40/60
EARLY_BE_TRIGGER_PIPS = 9999.0      # OFF — sebelumnya 10.0 (9999 = nonaktif; nilai lama disimpan sebagai komentar + preset F4)
# Rasio lot 30/25/25/20, trailing, sizing, killzone, spread filter: TIDAK berubah
```

`EARLY_BE_TRIGGER_PIPS=9999` = konvensi "BE+ nonaktif" (tidak pernah tercapai; blok BE+ otomatis ter-skip, header log daemon kini mencetak "DIMATIKAN"). Mengaktifkan kembali tinggal isi nilai pips kapan pun.

### 9.6 Re-validasi end-to-end pasca-penerapan (semua lulus)

| Pemeriksaan | Hasil |
|---|---|
| `research/validate_granular.py` (config baru, window penuh feed broker) | **326 tr (122W/0BE/204L) · NLR 37.42% · PF 2.08 · Net +$38,066.59 · DD 12.81% · 4/4 bulan hijau** — cocok persis dengan tabel finalis ✓ |
| `verify_engine_parity.py` | 4/4 — parity legacy bitwise identik ✓ |
| `test_icas_audit.py` | OK (setUp kini memaksa trigger BE=10 untuk reproduksi skenario lama) ✓ |
| `test_be_15_pips.py` | OK ✓ |
| `verify_fix_10016.py` | **5 PASS / 0 FAIL** (skenario memaksa trigger 10 — bug 10016 tetap terbukti tertutup) ✓ |
| `verify_state_persistence.py` | 14 PASS / 0 FAIL ✓ |
| Backtest engine (data repo, Jun 2026, smoke test config baru) | 73 tr, PF 1.01, +$124.49 — jalan normal, tidak ada komponen yang patah ✓ |
| Kompilasi seluruh modul | OK ✓ |

### 9.7 Batas kejujuran (baca sebelum menyalakan) + protokol lanjutan

1. **Sampel ini pendek dan satu rezim** (3,4 bulan, Mei–Agu 2026, pasar XAUUSD yang sedang trending kuat). Bahkan TEST-nya pun masih rezim yang sama — maka angka PF 2.08 adalah **hipotesis terbaik**, bukan janji. Forward-test di akun **demo minimal 4–6 minggu (≥ ±100 trade)** adalah syarat sebelum dinilai final.
2. Kriteria berhenti yang disarankan selama forward-test: bila setelah ≥100 trade PF forward < 1.0, atau DD melebihi ~2× DD backtest, matikan dan kalibrasi ulang dengan data forward tsb.
3. **Untuk rencana akun Cent Exness:** semua angka config (INITIAL_CAPITAL, risiko $, dsb.) diasumsikan USD dengan contract size 100 oz/lot. Di akun Cent saldo dinyatakan dalam USC (sen) — geometri SL/TP (pips) tetap valid dan tidak perlu diubah, tetapi **isi INITIAL_CAPITAL = saldo USC** (mis. Equity 100.000 USC), dan cek *Specification → Contract size* simbol XAUUSDm di akun cent (wajib 100; bila berbeda, sizing perlu faktor konversi).
4. Jangan kembalikan config lama (SL20/TP20/BE10) — di feed Anda sendiri konfigurasi itu terbukti −34% per bulan setara PF 0.80; nilainya disimpan hanya sebagai dokumentasi di komentar `config.py`.

---

## 10. 🧪 SIMULASI "FORWARD TEST LIVE" — CONFIG LAMA vs BARU DI ATAS M1 CSV

> Permintaan pengguna (25 Agu 2026): perlakukan M1 CSV **seolah-olah forward test live asli**, bandingkan config lama vs config baru, laporkan hasilnya (tanpa implementasi/deploy).

### 10.1 Bagaimana M1 diperlakukan sebagai "live"

Identik dengan perilaku daemon di akun riil: sinyal dievaluasi di M5 → **entry pada open bar berikutnya**, manajemen posisi (SL / TP1-3 / Early BE+ / trailing runner) diuji **bar-per-bar M1 sesuai urutan waktu** (tanpa asumsi intrabar apa pun), spread **riil per bar** (mean ≈ $0.26) + slippage $0.10 per sisi, sizing live = risiko tetap **$500/trade** (5% × INITIAL_CAPITAL), modal awal simulasi **$10,000**, equity digulung dari PnL riil (compounding). Window "forward" = bagian **out-of-sample 2026-07-15 → 2026-08-25 14:30** (42 hari kalender, 35 hari trading ≈ 6 minggu).

> ⚠️ Catatan kejujuran: window ini adalah yang dipakai sebagai **gerbang kelolosan (TEST)** saat memilih config baru — config tidak dioptimasi padanya, tetapi diseleksi dengannya. Jadi ini bukan forward murni; ini **proxy terdekat** yang tersedia per hari ini. Forward-demo sungguhan tetap wajib.

### 10.2 Hasil forward-test (sequencing M1 = proxy live)

| Metrik (6 minggu, $10k awal) | 🔴 CONFIG LAMA (SL20/TP20-60/BE10) | 🟢 CONFIG BARU (SL150/TP-C/BE OFF) | 🟡 Preset ALT (SL200/TP-B/BE60) |
|---|---|---|---|
| Trades (≈/hari) | 401 (11,5/hari) | 139 (4,0/hari) | 149 (4,4/hari) |
| Distribusi | 129W/127BE/145L | 56W/0BE/83L | 37W/92BE/20L |
| Trades dengan PnL > 0 | 64% | 74% | **87%** |
| **Profit Factor** | **0.90** | **2.25** | 2.01 |
| **Net PnL** | **−$7,366 (−73.7% modal)** | **+$17,445 (+174.4%)** | +$10,139 (+101.4%) |
| Equity akhir | **$2,634** 💀 | **$27,445** 🚀 | $20,139 |
| Max drawdown (kurva equity) | **101.8% — margin call praktis** | **12.7%** | 10.8% |
| Streak loss terpanjang | 5 | 3 | **2** |
| Minggu merah | 5 dari 7 (terburuk −$7,136 di minggu 10–16 Agu) | **0 dari 7** | 1 dari 7 (−$314 saja) |
| Ekspektasi per trade | −$18 | +$126 | +$68 |

Kurva mingguan config baru: `+$2,668 | +$3,606 | +$3,423 | +$4,200 | +$386 | +$1,336 | +$1,826` — **7/7 minggu hijau, tanpa satu pun minggu negatif.**

### 10.3 Jawaban "engine-nya rugi atau profit?" (engine M5 asli, window yang sama)

| Mode engine | Config | Hasil FORWARD 6 minggu |
|---|---|---|
| KONservatif (SL-first, biaya riil) | LAMA | 🔴 308 tr · PF **0.84** · **−$13,046** · DD 130% → **RUGI** |
| KONservatif | BARU | 🟢 137 tr · PF **2.08** · **+$18,445** · DD 12.7% → **PROFIT** (selaras dgn sequencing M1) |
| LEGACY (intrabar optimis pra-audit) | LAMA | 🟡 520 tr · PF 2.03 · +$60,549 → **profit PALSU** — inilah angka yang dulu menyesatkan |
| LEGACY | BARU | 🟢 160 tr · PF 1.60 · +$12,863 → profit |

**Kesimpulan §10:** diperlakukan sebagai forward test live, **config lama RUGI menguras modal (equity $10k → $2.6k, praktis margin call di drawdown >100%), sedangkan config baru PROFIT konsisten setiap minggu (+174%, DD 12.7%).** Engine konservatif setuju secara kualitatif dengan sequencing M1 di kedua config; mode legacy hanya boleh dipakai untuk benchmarking historis, bukan pengambilan keputusan.

> Konteks window penuh (14 Mei → 25 Agu 14:30): LAMA 916 tr PF 0.81 −$33,171 (0/4 bulan) vs BARU 326 tr PF 2.08 +$38,067 (4/4 bulan). Bukti mentah: `reports/forward_test_m1_compare.txt` (regenerasi: `python3 research/forward_test_m1_compare.py`). Rekomendasi berdiri: **forward-demo sungguhan ≥100 trade** sebelum uang riil.

---

## 11. 🖥️ ENGINE BARU v2 "SWING-150" — SIAP DEMO DI LAPTOP (jurnal JSON + anti on/off)

> Permintaan pengguna (25 Agu 2026): implementasikan hasil kalibrasi sebagai **engine baru**, killzone tetap **nonaktif**, jalankan 1 minggu di akun **demo**, siapkan **jurnal JSON** untuk observasi, dan antisipasi pola **on/off** (laptop pribadi, tanpa VPS). **Status: selesai diimplementasikan & terverifikasi.**

### 11.1 Yang berubah/ditambah
| Komponen | Isi |
|---|---|
| `config.py` | Engine params aktif SWING-150 (SL150/TP-C/BE OFF), `USE_KILLZONE=False` (tetap), + identitas `ENGINE_VERSION`, `JOURNAL_ENABLED/FILE`, snapshot equity tiap 15 menit |
| `src/execution/trade_journal.py` **(BARU)** | Penulis jurnal **JSONL append-only** — fail-safe total: jurnal tidak pernah bisa mematikan daemon |
| `icas_daemon.py` | Banner engine v2 + wiring jurnal lengkap + **rekonsiliasi on/off saat startup** + telemetri equity + fix tanggal stale `save_daily` (run multi-hari) |
| `src/execution/mt5_bridge.py` | `get_account_equity()` dan `get_position_realized(ticket)` — PnL realized dari riwayat deal broker (termasuk partial close, komisi, swap) |
| `src/state_store.py` | `list_position_tickets()` untuk rekonsiliasi horizontal startup |
| `research/journal_report.py` **(BARU)** | Alat observasi seminggu: rekap trade, PnL/entry per hari, kurva equity, durasi hold, statistik on/off, **evaluasi otomatis vs referensi forward-test** → `reports/journal_observasi.txt` |
| `START_ENGINE_DEMO.bat` **(BARU)** | Launcher 1-klik Windows untuk laptop |
| README | Bab "Mode Demo di Laptop (tanpa VPS)" |

### 11.2 Isi jurnal `logs/trade_journal.jsonl`
Satu event JSON per baris: `engine_start/stop` (+snapshot config lengkap sebagai bukti versi), `signal_detected`, `order_open/failed`, `tp_hit(1-3)`, `be_lock`, `sl_step_to_tp1`, `trail_update`, `equity_snapshot` (balance/equity/floating tiap 15 menit), `day_rollover`, dan khusus on/off laptop: `position_adopted` (posisi lama dilanjutkan — dari state file atau rebuild deal broker) dan `position_closed_offline` (posisi tertutup **saat daemon mati**, PnL direkonsiliasi dari riwayat deal).

### 11.3 Mekanisme anti on/off (tanpa VPS)
1. **State persist atomik** (sudah ada, diuji 14/14): status TP1-3/BE/trailing/volume awal tiap siklus → restart tanpa TP ganda.
2. **Adopsi posisi**: posisi yang masih terbuka saat engine ON kembali dilanjutkan manajemennya, tercatat di jurnal.
3. **Rekonsiliasi tutup-saat-OFF**: tiket yang ada di state tetapi sudah tak terbuka di broker → dicatat `position_closed_offline` dengan PnL realized dari deal broker → state dibersihkan. Uang "hilang" semasa OFF kini selalu tertelusur.
4. **Catatan inheren**: selama OFF, BE+/trailing tidak diperbarui (tak ada proses) — posisi terlindungi SL awal di sisi broker; begitu ON lagi, manajemen kalibrasi mengambil alih.

### 11.4 Verifikasi sebelum diserahkan
Kompilasi seluruh modul OK · test_icas_audit OK · test_be_15_pips OK · **verify_fix_10016 5/5** · **verify_state_persistence 14/14** · **parity legacy bitwise 4/4** · smoke-test jalur jurnal end-to-end (fabrikasi event → `journal_report.py`): PF/PnL/harian/kurva equity/evaluasi semuanya terhitung benar · import daemon & API StateStore baru OK.

### 11.5 Protokol observasi 1 minggu (saran)
Nyalakan engine di sesi pasar sebanyak yang laptop memungkinkan (referensi ~3–5 entry/hari → seminggu ≈ 15–25 trade). Akhir minggu: `python3 research/journal_report.py`. Aturan main (otomatis juga dinilai oleh laporan): **PF forward ≥ 1.8 → SEHAT lanjutkan; PF < 1.0 setelah ≥ 30 trade → STOP, kalibrasi ulang dengan data jurnal**. Seluruh minggu, `logs/trade_journal.jsonl` adalah satu-satunya sumber kebenaran — arsipkan bersama `reports/journal_observasi.txt`.

---

## 12. 🖥️ AUDIT FORENSIK DASHBOARD — 5 TEMUAN, SEMUA DIPERBAIKI

> Pertanyaan pengguna (25 Agu 2026): *"apakah dashboard sudah diaudit forensik juga? agar saya enak memantaunya."* Jawaban sebelumnya: **belum** — dashboard hanya tersentuh fix token & jam ([R-02]). Sekarang audit penuh telah dilakukan, dan dashboard disinergikan dengan **engine v2 + jurnal JSON** agar minggu observasi demo nyaman dipantau.

### 12.1 Temuan forensik (peringkat severity)

| ID | Severity | Temuan | Akibat riil |
|---|---|---|---|
| **D-01** | 🔴 HIGH | `spread_usd = spread_pts * 0.01` di-hardcode di `/api/status` | Di XAUUSDm 3-digit spread 260 pts tampil **$2.60** padahal hanya **$0.26** — kelas bug yang sama dengan root-cause error 10016 di daemon. Dashboard memberi gambaran biaya 10× lebih besar dari kenyataan. |
| **D-02** | 🔴 HIGH | Panel "4-Tier Target Protocols" + badge milestone + header tabel **hardcode parameter legacy** (SL 20p/$2.00, BE+ @10p, TP1 "1:1", "+20p") | Dengan engine v2 (SL150p, BE+ OFF, TP 1.25/2.5/3.75×SL), dashboard menampilkan aturan main yang **sudah tidak dipakai bot** — pemantau dibingungkan angka hantu. |
| **D-03** | 🟠 MED | `/api/stats` tanpa label sumber; prioritas terburuknya: fallback diam-diam ke **backtest dataset repo** | Dataset repo secara forensik BUKAN feed live Anda (deviasi median ~$15, §8.6) — tanpa label, angkanya bisa dibaca sebagai performa live. |
| **D-04** | 🟠 MED | Statistik "live 7 hari" menghitung **deal OUT mentah**, tidak per posisi | Setiap partial close TP1/TP2/TP3 = 1 deal → 1 posisi riil dihitung 2–4 "trade"; total_trades, win rate, dan PF **menggembung/bias**. |
| **D-05** | 🟠 MED | Dashboard tidak tahu **engine hidup atau mati** | Pada pola on/off laptop (tanpa VPS), pemantau tidak bisa membedakan "tenang tanpa sinyal" vs "daemon mati" tanpa mengintip konsol. |

### 12.2 Perbaikan yang diterapkan
1. **D-01**: `spread_usd` kini `spread_pts × price_point` via `bridge.get_point()` (digit-aware), field `price_point` ikut diekspos.
2. **D-02**: `templates/index.html` merender **seluruh label dari `/api/status`** — SL/TP dalam pips+$ dan rasio `×SL` dihitung dinamis; Early BE+ OFF ditampilkan jujur ("DIMATIKAN — engine v2"); hardcode legacy dihapus total.
3. **D-03**: hierarki sumber statistik eksplisit: **(1) JURNAL ENGINE v2** (`_stats_from_journal` — per-tiket, realized akurat termasuk semua partial+komisi+swap) → (2) live-deals MT5 7 hari → (3) backtest repo dengan label merah tebal *"⚠️ BUKAN feed live Anda"* (`dataset_warning`). Sumber ditampilkan di header tabel riwayat.
4. **D-04**: live-deals **diagregasi per `position_id`** sebelum statistik (partial menyatu kembali ke 1 trade); bridge kini mengembalikan `position_id`.
5. **D-05**: `journal_summary()` di `/api/status` + panel **"📒 Jurnal Engine & Observasi On/Off"**: status engine (AKTIF 🟢 / AKTIF? 🟡 / MATI 🔴 dinilai dari umur event vs interval snapshot), event terakhir, sinyal/order hari ini, **PnL realized hari ini & 7 hari**, hitungan siklus ON/OFF, mini-feed 8 event terakhir (`/api/journal`), dan badge status besar di navbar + versi engine.

### 12.3 Verifikasi
Suite baru **`verify_dashboard_v2.py`** (Flask test-client, 21 cek — jurnal asli dibackup & dipulihkan, contoh jurnal sintetik): **21 PASS / 0 FAIL** — mencakup kecocokan spread digit-aware, status engine AKTIF dari event baru, PnL harian (+12.50 dari 512.5−500), sumber stats=jurnal saat jurnal aktif, pemangkasan field config dari feed publik, dan tidak adanya sisa hardcode legacy di template. Regresi penuh tetap hijau: 10016 5/5 · state 14/14 · parity bitwise 4/4 · unit OK · kompilasi OK.

**Cara memantau**: jalankan dashboard seperti biasa (`run_dashboard.bat` / `python run_dashboard.py`, default `http://localhost:5000`) **berdampingan dengan daemon** — dashboard membaca `logs/trade_journal.jsonl` yang ditulis daemon, sehingga pola on/off Anda tampak jelas tanpa membuka konsol. Set `ICAS_DASH_TOKEN` bila membuka port di luar laptop.

---

*Disusun oleh audit forensik otomatis (statik + dinamis + mock MT5 + simulasi stokastik + sequencing M1 riil milik pengguna). Semua angka di atas adalah output nyata saat audit, bukan ilustrasi. Config baru bersifat hipotesis tervalidasi-OOS; konfirmasi akhir wajib lewat forward-test demo hidup.*
