# LAPORAN BACKTEST M1 TERAUDIT — XAUUSD, Jan–Jun 2026

**Tanggal:** 2 September 2026
**Cabang:** `arena/01a06235-jurnalicas`
**Data:** `jurnalicas/XAUUSD_M1/XAUUSD_M1_20250901_20260901.csv`
**Engine:** `model_icas_bot_FIX/research/backtest_m1_audit.py`
**Uji anti-repaint:** `model_icas_bot_FIX/research/test_antirepaint.py` → **24 PASS / 0 FAIL**
**Hasil mentah:** `model_icas_bot_FIX/reports/m1_audit_compare_jan_jun_2026.txt`

---

## 1. Ringkasan eksekutif

Ada empat temuan, dan dua di antaranya membatalkan kesimpulan sebelumnya.

**1. Kode produksi mengandung repaint, dan itu sudah diperbaiki (F-18).**
`src/indicators/sessions.py` menghitung `asian_high/low` dan `london_high/low` dengan
`df[mask].groupby('date').agg(max/min)` lalu `pd.merge(df, stats, on='date')`. Merge itu
menempelkan agregat **sepanjang hari** ke **setiap bar pada tanggal tersebut** — bar pukul
00:00 sudah "mengetahui" high Asia pukul 06:55 dan high London pukul 11:55. Karena level
BSL/SSL adalah dasar seluruh sinyal, ini berarti sinyal dibangun dari data masa depan.

Diukur pada data yang sama, jendela yang sama:

| Konfigurasi A, risk 1% | PF | Net | WR |
|---|---|---|---|
| level sesi bersih (kausal) | 0.93 | **−$2.100** | 58,71% |
| level sesi bocor (replika bug) | 1.36 | **+$6.935** | 64,80% |

Repaint **menggelembungkan net sebesar +$9.035** dan mengubah strategi yang rugi menjadi
tampak untung. `research/forward_test_m1_compare.py` (baris 32 & 137) dan
`src/backtest/engine.py` (baris 50) sama-sama memanggil fungsi yang bocor itu, sehingga
**angka PF 2.25 / PF 2.08 pada laporan forward test sebelumnya tidak dapat dipakai.**

**2. Pada data yang bersih, plan saat ini DAN saran saya sama-sama rugi.**

| Jan–Jun 2026, risk 1%, modal $10.000 | Trades | WR | PF | Net | DD | Entry/hari |
|---|---|---|---|---|---|---|
| **A — plan saat ini** (config.py) | 729 | 58,71% | **0,93** | **−$2.100** | 29,4% | 4,73 |
| **B — rekomendasi** (TP dipadatkan + killzone + CB) | 177 | 63,84% | **0,67** | **−$2.234** | 25,0% | 1,15 |
| **C — rekomendasi tanpa killzone** (ablasi) | 968 | 67,15% | **0,84** | **−$5.300** | 54,2% | 6,29 |

**3. Sinyal tidak menambah edge di atas entry acak.** Dengan geometri SL/TP identik tetapi
waktu dan arah entry diacak:

| | PF sinyal | PF acak | Selisih |
|---|---|---|---|
| A | 0,934 | 0,897 | **+0,037** |
| B | 0,668 | 0,820 | **−0,152** |
| C | 0,841 | 0,935 | **−0,094** |

Untuk B dan C sinyalnya justru **lebih buruk dari acak**. Untuk A selisihnya +0,037 PF —
terlalu kecil untuk disebut edge, dan tetap di bawah 1,0.

**4. Risk 5% memusnahkan akun.** Pada setting `config.py` sekarang (risk 5% = $500/trade),
ketiga konfigurasi menghabiskan seluruh $10.000 sebelum akhir Juni:

| risk 5% | Trades | PF | Net | DD |
|---|---|---|---|---|
| A | 719 | 0,93 | −$10.068 | **100,5% — bangkrut** |
| B | 139 | 0,62 | −$10.054 | **100,5% — bangkrut** |
| C | 187 | 0,71 | −$10.059 | **100,6% — bangkrut** |

---

## 2. Audit forensik: bagaimana "tidak ada repaint" dibuktikan

Bukan klaim, tapi 24 uji yang dijalankan ulang setiap saat. Yang menentukan:

**T7 — Truncation invariance (bukti terkuat).** Kalau engine benar-benar tidak melihat masa
depan, memotong data di tanggal T harus menghasilkan trade yang *identik* untuk semua trade
yang dibuka sebelum T. Hasil:

```
config A: run terpotong <2026-04-01 identik dgn run penuh   n=474 vs 474, net $-3,301 vs $-3,301
config B: run terpotong <2026-04-01 identik dgn run penuh   n=122 vs 122, net $-5,759 vs $-5,759
```

**T1/T2 — Kausalitas lewat perturbasi.** Bar-bar di paruh kedua dataset diganti dengan
`high=9999, low=1`. Level sesi dan `signal_at()` di paruh pertama **tidak berubah sama
sekali** (0 dari 54.116 bar; 0 dari 150 bar sinyal). Kontrol positif memastikan gangguan
benar-benar masuk.

**T3 — Timing entry.** 815 trade diverifikasi: setiap entry terjadi di *open* bar M1 tepat
5 menit setelah bar sinyal tutup, tidak pernah di bar sinyal itu sendiri. Exit SL diverifikasi
tepat di level SL yang berlaku (deviasi maks $0,0000).

**T4 — Spread benar-benar dibayar.** Dataset dijalankan dua kali: bid/ask asli vs `ask = bid`.
Versi tanpa spread lebih untung **$24.994** (PF 0,948 → 1,092), yaitu **$30,67 per trade**.
Ini bukti spread masuk ke simulasi, bukan diabaikan.

**T5 — Urutan intrabar pesimis.** Dalam satu bar M1, SL diuji sebelum TP. Varian optimis
(TP dulu) diuji sebagai pembanding; pada geometri riil keduanya sama karena SL $15 dan
TP1 $18,75 jarang termuat dalam satu bar M1. Kontrol positif dengan SL/TP rapat
(−$18.402 vs −$5.605) membuktikan flag-nya benar-benar berfungsi.

**T6 — Regresi F-18.** Fungsi produksi yang sudah diperbaiki kini cocok **bar-per-bar**
dengan engine teraudit: 2.879 bar dibandingkan, **0 selisih** untuk `asian_high` maupun
`london_high`.

**T8 — Aritmetika ekuitas.** Ditambahkan setelah ditemukan bug nyata di engine saya sendiri:
equity curve dibangun sebagai `[capital0] + list(cumsum(pnl))` — PnL kumulatif tidak
ditambah modal, sehingga DD terbaca 123,56% padahal sebenarnya 29,38%. Sudah diperbaiki dan
sekarang ada assertion yang memverifikasi DD, Net, dan PF terhadap hitung ulang independen.

Daftar aturan anti-repaint yang diimplementasi di engine:

| | Aturan |
|---|---|
| A1 | Level sesi hanya dari sesi yang **sudah tutup** (Asia tersedia 07:00, London 12:00) |
| A2 | Sinyal hanya memakai bar ≤ idx |
| A3 | Entry di *open* bar M1 berikutnya setelah bar sinyal tutup |
| A4 | Exit long pakai **bid**, exit short pakai **ask** |
| A5 | Intrabar konservatif: SL diuji sebelum TP |
| A6 | SL yang baru dinaikkan (BE/trail) baru efektif bar M1 berikutnya |
| A7 | UTC → waktu server Exness (Europe/Athens, EET/EEST), DST ditangani benar |
| A8 | Satu pass maju per bar M1; tidak ada akses ke indeks > bar aktif |

---

## 3. Temuan pada dataset

- **204.595 bar M1** dimuat (Des 2025 sebagai warm-up level sesi, tidak ditradingkan),
  **40.917 bar M5**, **154 hari bursa** pada jendela Jan–Jun 2026.
- **0 NaN, 0 OHLC invalid, 0 timestamp duplikat, 0 spread terbalik.** Gap > 5 menit: 128
  (akhir pekan & libur). Data ini bersih.
- **Kolom bid dan ask terpisah** — ini yang membuat backtest spread-akurat mungkin. File
  `data/historical/*.csv` yang lama hanya punya satu harga dan tidak bisa.
- **Zona waktu data adalah UTC**, terbukti dari profil volume: puncak 15:00 UTC
  (overlap London–NY), lembah 21:00–04:00 UTC, dan hanya 950 bar pada hari Minggu.
  Engine mengonversi ke waktu server Exness (UTC+2 musim dingin, UTC+3 musim panas).

### ⚠️ `MAX_SPREAD_POINTS = 350` tidak cocok dengan feed ini

| | |
|---|---|
| Guard di config | 350 points = **$0,35** |
| Spread feed ini | median **$0,69**, p95 **$1,15** |
| Bar yang lolos guard | **0,29%** |
| Trade yang dihasilkan | **3 dalam 6 bulan** |

Guard itu dikalibrasi untuk feed live Anda (spread $0,26 di jurnal). Pada feed dataset ini
bot praktis tidak pernah entry. Semua run di laporan ini memakai guard **$1,20** (p95 feed
ini) supaya geometrinya yang dibandingkan, bukan guard-nya. **Kalau Anda ingin mereproduksi
backtest ini pada feed live, guard harus disetel ulang per feed.**

Catatan tambahan: `SERVER_TIME_OFFSET_HOURS = 4` (WIB − 4 = UTC+3) hanya benar pada musim
panas. Pada musim dingin server Exness berada di UTC+2, sehingga jam sesi bot meleset
1 jam selama ±5 bulan per tahun.

---

## 4. Kenapa WR tinggi tapi tetap rugi

Ini bagian yang paling penting untuk dibaca sebelum menyentuh parameter apa pun.

| | total | WIN | LOSS | win scratch | win substantif | avg win | avg loss | WR break-even |
|---|---|---|---|---|---|---|---|---|
| **A** | 729 | 428 | 301 | 360 (**84%**) rata $45 | 68 (**9,3%** dari semua trade) rata $196 | $68,94 | −$105,00 | **60,4%** |
| **B** | 177 | 113 | 64 | 112 (**99%**) rata $39 | 1 (**0,6%**) rata $154 | $39,70 | −$105,00 | **72,6%** |
| **C** | 968 | 650 | 318 | 640 (**98%**) rata $41 | 10 (**1,0%**) rata $161 | $43,21 | −$105,00 | **70,8%** |

WR 58–67% itu **palsu**. Hampir seluruhnya adalah trade yang naik $10 lalu ditarik trailing
stop ke lock +$3 (≈ $41–45 pada lot 0,07), bukan trade yang menyentuh TP. Kerugian penuh
tetap $105. Jadi rata-rata menang $43–69 lawan rata-rata kalah $105.

Trailing lock aktif pada **58,8%** trade — jauh lebih sering daripada TP1 (25,2%).

### Ketercapaian target (geometri A)

MFE (gerak menguntungkan maksimum) per trade: median **$10,92**, rata-rata $13,35,
p75 $18,90, p90 $29,41, maks $95,54.

| Level | Jarak | Tercapai |
|---|---|---|
| TP1 | $18,75 (1,25R) | **25,2%** (184 dari 729) |
| TP2 | $37,50 (2,50R) | **5,2%** (38 dari 729) |
| TP3 | $56,25 (3,75R) | **1,2%** (9 dari 729) |

Ini mengonfirmasi temuan pada jurnal live (TP2 dan TP3 tidak pernah tercapai dalam 21 trade)
dengan sampel 35× lebih besar. **Struktur 4-tier berjalan sebagai 1 tier + trailing scratch.**

---

## 5. Koreksi atas saran saya sebelumnya

Saran saya pada giliran sebelumnya harus dikoreksi berdasarkan data ini.

| # | Saran sebelumnya | Verdict sekarang |
|---|---|---|
| 1 | Jangan retune pada 21 trade; kumpulkan 150–300 | **TETAP BENAR**, dan sekarang tidak perlu menunggu: backtest 729 trade sudah memberi jawaban |
| 2 | Turunkan risk 5% → 1–2% | **TERKONFIRMASI KUAT.** Pada 5% ketiga konfigurasi bangkrut 100,5% sebelum akhir Juni |
| 3 | **Padatkan geometri TP ke R:R 0,75–1,0** | **SALAH. Dicabut.** WR memang naik (58,7% → 67,2%) tetapi payoff turun lebih cepat (0,66 → 0,41), sehingga WR break-even naik dari 60,4% ke 70,8% dan PF justru **turun** dari 0,93 ke 0,84 |
| 4 | Aktifkan kembali killzone sebagai A/B | **Teruji, hasilnya negatif.** Killzone memangkas trade 729 → 177 dan PF turun 0,93 → 0,67. Ablasi C membuktikan pemadatan TP-lah yang merusak, bukan killzone-nya saja — tapi keduanya tidak menyelamatkan |
| 5 | Set `MAX_CONSECUTIVE_LOSSES = 3` | **Boleh, tapi bukan penyelamat.** Semantiknya "per hari" (`icas_strategy.py:36`), dan di engine saya sempat menyebabkan deadlock permanen karena tidak di-reset |
| 6 | Perbaiki floor margin/stop-out di backtest | **TETAP BENAR** dan kini terbukti penting: tanpa floor, PF 2,18 pada `test_new_icas_tp_be.py` berasal dari kurva dengan ekuitas −$38.683 |
| 7 | Kalibrasi ulang `SLIPPAGE_USD` dari fill nyata | **TETAP BENAR.** Sudah dikerjakan (F-17) |

Kenapa saran #3 gagal: TP1 $11,25 hanya sedikit di atas trailing lock $3,00 yang aktif
setelah MFE $10. Begitu TP1 dipadatkan mendekati zona trailing, sebagian besar trade yang
tadinya akan mencapai TP1 justru dikunci lebih dulu di +$3. **TP1 harus berada jelas di atas
trailing lock**, bukan di dekatnya.

---

## 6. Validasi silang terhadap jurnal live

| | trades | WR | PF | net | expectancy | TP1 |
|---|---|---|---|---|---|---|
| Backtest A @ risk 5% | 719 | 58,7% | 0,93 | −$10.068 | −$14,00 | 25,0% |
| Live (26 Agu – 02 Sep) | 21 | 42,9% | **0,78** | −$1.307 | −$62,22 | 33,3% |

Keduanya **PF < 1** — arah kesimpulannya sama. Selisih besarnya konsisten dengan:

- slippage nyata **$1,27/entry** (terukur dari event `be_lock`, F-17) yang tidak ada di data
  historis;
- bug F-03/F-05 yang merusak *pemenang* (0 dari 12 loser pernah mencapai TP1), baru diperbaiki;
- n = 21 terlalu kecil untuk memisahkan PF 0,78 dari 1,0.

**Peringkah penting saat membaca jurnal:** `realized_total` bersifat **kumulatif per tiket**,
dan ada 26 close event untuk 21 tiket unik (5 duplikat akibat F-03). Menjumlah semua close
event memberi −$510,70 — **itu salah**. Agregasi yang benar (event terakhir per tiket)
memberi **−$1.306,66 · WR 42,9% · PF 0,781**.

---

## 7. Perubahan kode pada giliran ini

| Berkas | Perubahan |
|---|---|
| `src/indicators/sessions.py` | **F-18 — repaint diperbaiki.** Level sesi kini point-in-time: Asia tersedia mulai 07:00, London mulai 12:00, sebelumnya pakai hari sebelumnya. Ditandatangani sebagai drop-in replacement (kolom & signature sama) |
| `research/backtest_m1_audit.py` | **Baru.** Engine M1 bid/ask anti-repaint (A1–A8), termasuk `session_levels_repaint()` sebagai replika bug untuk mengukur dampaknya, baseline entry acak, dan varian `tp_first` untuk uji sensitivitas |
| `research/test_antirepaint.py` | **Baru.** 24 uji anti-repaint dengan kontrol positif, termasuk truncation invariance dan regresi F-18 |
| `research/run_m1_compare_audit.py` | **Baru.** Runner perbandingan A/B/C × (bersih, repaint, acak) × (risk 1%, 5%) + validasi silang jurnal live |
| `reports/m1_audit_compare_jan_jun_2026.txt` | **Baru.** Hasil mentah lengkap, termasuk rincian per bulan |

**Verifikasi:**
- `research/test_antirepaint.py` → **24 PASS / 0 FAIL**
- `run_qa.py` → **8 PASS / 0 FAIL / 0 SKIP** (POC 27 assertion, 11 skenario kegagalan)
- Smoke backtest engine lama, diukur dengan menukar `sessions.py` lama ↔ baru pada kode
  yang sama persis:

  | `src/backtest/engine.py` (smoke `run_qa.py`) | trades | final capital |
  |---|---|---|
  | `sessions.py` lama (repaint) | 313 | **$51.337,58** |
  | `sessions.py` baru (F-18) | **443** | **$17.409,80** |

  Perbaikan satu bug ini menghapus **$33.928 (−66%)** dari laba yang dilaporkan engine lama,
  pada data dan kode yang identik. Kedua run tetap 8 PASS / 0 FAIL.

---

## 8. Rekomendasi

**Jangan naikkan ukuran posisi dan jangan retune TP.** Tidak ada konfigurasi yang diuji
menghasilkan PF > 1 pada data bersih. Ini bukan masalah kalibrasi parameter; sinyal
`ssl_sweep + bull_displacement` pada data ini tidak bisa dibedakan dari entry acak
(selisih PF +0,037 untuk A, negatif untuk B dan C).

Urutan yang saya sarankan:

1. **Turunkan `RISK_PER_TRADE` ke 1% sekarang juga**, atau lebih baik hentikan trading live.
   Pada 5% akun $10.000 habis dalam < 6 bulan di ketiga konfigurasi.
2. **Jangan pakai angka forward test lama** (PF 2,25 / 2,08). Keduanya dihitung dengan level
   sesi yang bocor. Kalau ingin memvalidasi ulang, jalankan
   `research/forward_test_m1_compare.py` sekarang — `sessions.py` sudah diperbaiki, jadi
   angkanya akan berubah dan itulah angka yang jujur.
3. **Setel ulang `MAX_SPREAD_POINTS` per feed.** Nilai 350 membuat bot mati total pada feed
   dengan spread $0,69.
4. **Kalau tetap ingin melanjutkan, ubah hipotesisnya, bukan parameternya.** Yang perlu diuji:
   apakah *entry*-nya yang bermasalah (bukti: PF ≈ PF acak) atau *manajemen*-nya
   (bukti: 84–99% "win" adalah trailing scratch $41). Uji paling murah: matikan trailing
   sepenuhnya dan lihat apakah payoff naik cukup untuk menutup WR yang turun.
5. **Kumpulkan fill price dari F-17** sebelum mempercayai backtest apa pun terhadap live.
   Selisih expectancy live (−$62,22) vs backtest (−$14,00) sebesar 4,4× sebagian besar
   adalah slippage dan bug yang belum ada di data historis.

---

## 9. Cara mereproduksi

```bash
cd jurnalicas/model_icas_bot_FIX
python3 -m venv .venv && .venv/bin/pip install pandas numpy flask
.venv/bin/python research/test_antirepaint.py        # 24 PASS / 0 FAIL
.venv/bin/python research/run_m1_compare_audit.py    # tulis reports/m1_audit_compare_jan_jun_2026.txt
.venv/bin/python run_qa.py                           # 8 PASS / 0 FAIL / 0 SKIP
```

Waktu jalan: ±100 detik untuk uji anti-repaint, ±100 detik untuk runner perbandingan
(12 konfigurasi × 204.595 bar M1).
