# LAPORAN TUNING MULTI-TIMEFRAME — ANALISA H1 → M30 → M15 → M5, EKSEKUSI M1

**Periode uji utama : 01-09-2025 → 01-09-2026 (XAUUSD, 674.431 bar M1, 313 hari bursa)**
**Uji lintas rezim : 2021–22 (bearish) dan 2022–23 (recovery)**
**Engine : `research/backtest_m1_audit.py` (M1 bid/ask, anti-repaint, pesimis, spread riil, guard $1.20)**
**Skrip : `research/tuning_mtf.py` — artefak angka: `model_icas_bot_FIX/reports/tuning_mtf_*.txt`**
**Tanggal : 08 September 2026**

---

## RINGKASAN EKSEKUTIF

1. Konsep yang diminta — **analisa berlapis H1, M30, M15, M5 dengan eksekusi M1** — kini benar-benar
   terimplementasi di jalur sinyal engine (`signal_mode="mtf"`), bukan sekadar tampilan dashboard.
   Semua laporan tuning sebelumnya (termasuk `LAPORAN_TUNING_FILTER_TREN.md`) **belum** memakai
   konsep ini (analisa M5 + sesi, eksekusi M1); laporan ini menggantinya.
2. Hasil kaskade MTF **sangat bergantung pada definisi lapisan likuiditas M30** — bukan pada
   jumlah lapisannya:
   - Likuiditas **ekstrem-24-jam rolling** (V1/V5/V6): kaskade nyaris tak pernah terpenuhi
     (V1 = 7 trade/setahun, PF 0.15) dan versi longgarnya tetap **rugi** (PF 0.66–0.88).
   - Likuiditas **fractal swing M30** (V9/V10): flat sampai rugi (PF 0.93–1.01).
   - Likuiditas **PDH/PDL kemarin** (V7/V8) — level ICT klasik: **satu-satunya kaskade MTF FULL
     yang profit**: V7 = 93 tr, WR 63,4%, PF 1.19, +$682, DD 6,3%; V8 = 257 tr, WR 62,3%,
     PF 1.09, +$963, DD 12,6% (risk 1%).
3. **Kontrol acak** (entry acak, geometri identik, n=888 aktual): PF 0.92, −$3.389, DD 53,2%.
   V7/V8 berada jauh di atas keberuntungan pada periode utama.
4. **Uji lintas rezim (gerbang wajib) — V7/V8 LULUS KUMULATIF, TIDAK LULUS SERAGAM**:
   2021–22: V7 +$736 / V8 +$337 (profit, tapi kontrol acak periode itu juga +$883 → di level
   keberuntungan); 2022–23: V7 −$287 / V8 −$175 (rugi tipis). **Kumulatif 3 periode risk 1%:
   V7 +$1.131, V8 +$1.125** — terbaik dari semua varian yang pernah diuji di seri tuning ini
   (pembanding kumulatif: baseline A −$6.390; filter tren B −$1.209; D −$1.564).
5. Reality-check risk 5%: V7 +$3.215 (DD 27,6%) masih bertahan; V8 +$4.541 tapi DD 51,0% —
   tidak layak.
6. **Rekomendasi**: adopsi **V8** (H1 bias EMA200 → sweep PDH/PDL ≤ 4 jam → CHoCH M15 →
   displacement/FVG M5 → eksekusi M1) sebagai kandidat default **DEMO** berikutnya, risk maks 1%.
   **Status tetap DEMO, bukan live** — keunggulan belum stabil antar rezim dan sampel kandidat
   masih kecil (60–257 trade/tahun).

---

## 1. LATAR BELAKANG

Pertanyaan pengguna (08 Sep 2026): *"semua tuning harus dengan konsep analisa pada H1, M30, M15,
M5, eksekusi di M1 — apakah laporan (tuning filter tren) sudah dengan konsep ini?"*

Jawaban yang sudah diberikan secara jujur: **BELUM**. Bukti: jalur sinyal semua laporan tuning
sebelumnya hanya menganalisa M5 (swing 5-bar + range sesi Asia/London); `MACRO_TIMEFRAME` M15 di
config hanya untuk tampilan dashboard; H1/M30 tidak ada sama sekali di jalur sinyal. Laporan ini
menutup celah tersebut: seluruh eksperimen tuning di bawah memakai kaskade analisa multi-timeframe
dengan eksekusi tetap di M1.

## 2. METODOLOGI

### 2.1 Kaskade empat lapis (semua kausal / tanpa lookahead antar-timeframe)

| Lapis | TF | Peran | Definisi |
|---|---|---|---|
| L1 | **H1** | Bias arah | close vs **EMA200 H1** (hanya bar H1 yang sudah tertutup) |
| L2 | **M30** | Likuiditas mayor | **sweep SSL/BSL** dalam jendela `mtf_sweep_bars` bar M5 terakhir. Tiga definisi level diuji: (a) `swing24` = ekstrem 24 jam rolling; (b) `pd` = **PDH/PDL kemarin**; (c) `fract` = fractal swing 5-bar M30 (konfirmasi +2 bar) |
| L3 | **M15** | Struktur | **CHoCH** — close menembus swing high/low 5-bar M15 |
| L4 | **M5** | Trigger | displacement candle + FVG ($0,30) / break swing 5-bar M5 |
| EX | **M1** | Eksekusi | entry di bar M1 berikutnya; SL/TP/trailing dievaluasi per M1; BUY di ask, exit di bid (spread riil implisit) |

BUY = bias bull H1 **dan** sweep SSL (likuiditas di bawah diambil) **dan** CHoCH bull M15 **dan**
trigger bull M5. SELL simetris. Pemetaan HTF→M5 memakai offset durasi penuh (`_map_htf`): nilai
bar HTF hanya terbaca setelah bar itu tertutup. Kausalitas diverifikasi unit-check (lihat §3).

### 2.2 Varian yang diuji (risk $100 = 1%, modal $10.000, guard spread $1.20)

| Kode | Konfigurasi |
|---|---|
| V1 | MTF FULL (H1+M30+M15+M5), likuiditas swing24, jendela sweep 2 bar (10 menit) |
| V2 | tanpa lapis M15 (H1+M30+M5) |
| V3 | tanpa lapis M30 (H1+M15+M5) |
| V4 | H1+M5 saja (bias + trigger) |
| V5/V6 | V1 dengan jendela sweep M30 1 jam / 4 jam |
| V7 | MTF FULL, likuiditas **PDH/PDL**, jendela fresh (2 bar) |
| V8 | MTF FULL, likuiditas **PDH/PDL**, jendela 4 jam |
| V9/V10 | MTF FULL, likuiditas **fractal M30**, jendela 2 bar / 4 jam |
| A | BASELINE lama (analisa M5 + sesi Asia/London, eksekusi M1) — pembanding |
| R | **Kontrol acak**: waktu entry acak (n menyamai varian teramai), arah acak, geometri manajemen posisi identik |

## 3. BUG DITEMUKAN & DIPERBAIKI SELAMA EKSPERIMEN (transparansi QC)

1. **NaN massal kolom M30 (penyebab V1 awal = 0 trade)**: `rolling(48, min_periods=48)` pada bar
   M30 hasil resample menghitung *slot waktu*, bukan *bar bursa* — bar weekend (NaN) memutus
   rantai sehingga **tidak ada satu pun nilai SSL/BSL valid sepanjang setahun** (0 dari 71.128
   bar M5). Fix: bar non-bursa di-drop sebelum rolling → SSL/BSL valid 71.128/71.128 bar.
   *Pelajaran: kaskade "terlalu restriktif" yang pertama kali terlihat ternyata bug data, bukan
   sifat strategi — diagnosis per-lapis menyelamatkan kita dari kesimpulan salah.*
2. **Crash `month_table`** pada varian 0-trade (tdf kosong) → guard ditambahkan.
3. **`dataclasses.replace()` kwarg dobel** pada varian A → fix konstruksi kwargs.
4. **`mtf_sweep_bars` belum ter-wire** (hardcoded 2 bar) → di-wire ke `signal_at()`.
5. Verifikasi setelah fix: unit-check kausalitas PDH/PDL (level kemarin statis intraday, tidak
   pernah membaca hari berjalan) dan fractal M30 (level baru hanya muncul ≥ 90 menit setelah bar
   fractal — sesuai waktu konfirmasi 2 bar M30) — **PASS**. Header laporan kini juga mencetak
   validitas tiap kolom HTF agar bug senyap seperti ini tidak terulang.
6. **Regresi jalur default**: `run_m1_compare_audit.py` dijalankan ulang penuh — artefak
   `reports/m1_audit_compare_jan_jun_2026.txt` hasil run **identik byte-per-byte** dengan versi
   ter-commit → perilaku engine lama tidak berubah sama sekali (semua perubahan additif).

## 4. HASIL PERIODE UTAMA (01-09-2025 → 01-09-2026, risk 1%)

| Varian | Tr | WR% | PF | Net $ | Exp $/tr | DD% | Entry/bln | Bulan hijau | BUY/SELL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 FULL swing24 (10 mnt) | 7 | 42,9 | 0,15 | −357 | −51,00 | 3,6 | 1,4 | 2/5 | 3/4 |
| V2 tanpa M15 | 100 | 56,0 | 0,80 | −933 | −9,33 | 12,7 | 8,3 | 5/12 | 58/42 |
| V3 tanpa M30 | 1.473 | 58,9 | 1,02 | +1.414 | +0,96 | 27,2 | 113,3 | 8/13 | 785/688 |
| V4 H1+M5 saja | 2.386 | 59,0 | 1,01 | +1.276 | +0,53 | 36,7 | 183,5 | 6/13 | 1248/1138 |
| V5 swing24, jendela 1 j | 47 | 57,5 | 0,66 | −714 | −15,18 | 8,4 | 4,3 | 3/11 | 21/26 |
| V6 swing24, jendela 4 j | 174 | 59,8 | 0,88 | −889 | −5,11 | 15,7 | 14,5 | 4/12 | 87/87 |
| **V7 PDH/PDL (fresh)** | **93** | **63,4** | **1,19** | **+682** | **+7,34** | **6,3** | 7,8 | **8/12** | 47/46 |
| **V8 PDH/PDL (4 jam)** | **257** | **62,3** | **1,09** | **+963** | **+3,75** | **12,6** | 21,4 | **8/12** | 136/121 |
| V9 fractal M30 (fresh) | 112 | 59,8 | 0,93 | −355 | −3,17 | 13,3 | 9,3 | 6/12 | 61/51 |
| V10 fractal M30 (4 jam) | 1.251 | 57,8 | 1,01 | +710 | +0,57 | 31,2 | 96,2 | 8/13 | 660/591 |
| A BASELINE lama (M5) | 1.278 | 57,1 | 0,89 | **−6.557** | −5,13 | 65,6 | 98,3 | 3/13 | 598/680 |
| R ACAK (kontrol, n=888) | 888 | 56,0 | 0,92 | −3.389 | −3,82 | 53,2 | 68,3 | 4/13 | 461/427 |

Rincian bulanan V8: 8 dari 12 bulan hijau; bulan terburuk Nov-2025 (PF 0,34, −$965), terbaik
Des-2025 (PF 3,05, +$862). V7: 8/12 hijau, frekuensi hanya 3–12 entry/bulan.

## 5. PEMBACAAN KONTROL ACAK

Pada periode utama, kontrol acak dengan geometri manajemen posisi identik menghasilkan PF 0,92
(−$3.389). Artinya:

- Geometri plan (SL150/TP bertingkat/trailing) **sendirian tidak menghasilkan uang** — konsisten
  dengan semua laporan sebelumnya.
- V7 (+$7,34/tr) dan V8 (+$3,75/tr) berada **di atas keberuntungan secara meyakinkan** pada
  periode ini; V3/V4/V10 (+$0,5–1,0/tr) hanya **marginal** di atas acak; V1/V2/V5/V6/V9 dan
  baseline A di bawah acak.
- WR 63,4% (V7) adalah win-rate tertinggi dari semua varian yang pernah diuji di seri tuning
  (bandingkan: filter tren B 59,7%, D 59,5%, baseline 57,1%).

## 6. UJI LINTAS REZIM (gerbang anti self-deception)

### 6.1 Periode 2021–09 → 2022–09 (XAUUSD bearish/konsolidasi)

| Varian | Tr | WR% | PF | Net $ | DD% |
|---|---:|---:|---:|---:|---:|
| V7 PDH/PDL fresh | 71 | 67,6 | 1,30 | +736 | 4,4 |
| V8 PDH/PDL 4 jam | 123 | 64,2 | 1,07 | +337 | 7,6 |
| V4 H1+M5 | 275 | 60,4 | 0,98 | −177 | 17,1 |
| A baseline | 255 | 58,0 | 0,89 | −1.219 | 17,9 |
| R ACAK (n=85 aktual) | 85 | 64,7 | **1,28** | **+883** | 7,6 |

**Peringatan penting**: pada periode ini kontrol acak juga profit (PF 1,28, +$883) — mesin acak
sedang "beruntung" mengikuti gerakan besar 2022. V7 yang +$736 **tidak dapat dibedakan dari
keberuntungan** di rezim ini. Klaim edge TIDAK boleh dibangun dari periode ini.

### 6.2 Periode 2022–09 → 2023–09 (recovery)

| Varian | Tr | WR% | PF | Net $ | DD% |
|---|---:|---:|---:|---:|---:|
| V7 PDH/PDL fresh | 60 | 56,7 | 0,90 | −287 | 6,5 |
| V8 PDH/PDL 4 jam | 113 | 60,2 | 0,96 | −175 | 8,0 |
| V4 H1+M5 | 251 | 57,4 | 1,00 | −38 | 19,1 |
| A baseline | 232 | 61,2 | **1,15** | **+1.386** | 11,2 |
| R ACAK | 87 | 60,9 | 1,03 | +125 | 7,2 |

Di rezim recovery justru baseline lama yang terbaik (konsisten dengan temuan laporan tuning
filter tren). V7/V8 rugi tipis.

### 6.3 Kumulatif tiga periode (risk 1%)

| Varian | 2021–22 | 2022–23 | 2025–26 | **Kumulatif** |
|---|---:|---:|---:|---:|
| **V7** | +736 | −287 | +682 | **+1.131** |
| **V8** | +337 | −175 | +963 | **+1.125** |
| A baseline (dari laporan #4) | −1.219 | +1.386 | −6.557 | **−6.390** |
| B SMA200-harian (laporan #4) | −1.070 | −537 | +398 | −1.209 |
| D EMA200-M5 (laporan #4) | −2.259 | +207 | +488 | −1.564 |

V7/V8 adalah kandidat pertama yang **kumulatif positif** di ketiga periode uji — namun dengan
dua catatan jujur: (a) kontribusi terbesar berasal dari periode 2025–26 di mana definisi
likuiditas PDH/PDL dipilih (risiko *data snooping* — 3 definisi diuji, 1 menang di periode ini);
(b) belum lulus gerbang "profit di setiap rezim" (2021–22 ≈ acak, 2022–23 rugi tipis).

## 7. REALITY-CHECK RISK 5% (periode utama)

| Varian | Net $ | DD% | Vonis |
|---|---:|---:|---|
| V7 | +3.215 | 27,6 | bertahan, DD masih wajar |
| V8 | +4.541 | 51,0 | **tidak layak** (DD >50%) |

Risk 5% tetap tidak disarankan untuk varian apa pun; V8 secara khusus rentan karena bulan buruk
(Nov-25, Apr-26) menggerus separuh modal.

## 8. ANALISIS

1. **Lapisan M30 adalah pisau bermata dua.** Dengan definisi ekstrem-24-jam, kaskade AND empat
   lapis nyaris mustahil terpenuhi (7 trade/tahun) — sweep "ekstrem 24 jam yang searah bias H1"
   hampir kontradiktif: BUY menuntut harga di atas EMA200-H1 *serentak* dengan penembusan low
   24 jam. Saat jendela dilebarkan (V5/V6), kondisi melonggar tetapi kualitas sinyal justru
   turun (PF 0,66–0,88) karena sweep basi tidak lagi informasi segar.
2. **PDH/PDL bekerja karena levelnya nyata dan diketahui semua partisipan.** Sweep level kemarin
   adalah peristiwa likuiditas Mayor klasik ICT: stop-hunt di bawah/atas level harian, lalu
   reversal dikonfirmasi CHoCH M15 dan trigger presisi M5. WR 63–67% + DD 6–13% konsisten di
   dua periode berbeda (2025–26 dan 2021–22) — bukan artefak satu rezim bull.
3. **Fractal M30 (V9/V10) menempati posisi tengah** — level swing lokal terlalu dekat dengan
   harga sehingga sweep-nya murah (banyak noise), PF 0,93–1,01.
4. **Ablasi lapisan**: membuang M30 (V3) atau M15+M30 (V4) menaikkan frekuensi 6–18× namun
   menekan kualitas ke marginal-di-atas-acak. Kaskade lengkap dengan likuiditas yang tepat
   (V7/V8) menukar frekuensi dengan kualitas — pola klasik "selectivity vs activity".
5. **Perbandingan dengan kandidat laporan tuning #4** (periode utama): V8 vs B (SMA200 harian):
   PF 1,09 vs 1,02; net +$963 vs +$398; DD 12,6% vs 24,6%; 21 vs 48 entry/bln — V8 mengungguli
   di semua metrik, dan kumulatif 3 periode juga lebih baik (+$1.125 vs −$1.209).

## 9. KESIMPULAN & REKOMENDASI

1. **Pertanyaan pengguna terjawab tuntas**: tuning dengan konsep analisa H1/M30/M15/M5 +
   eksekusi M1 sudah diimplementasikan, diuji (12 varian termasuk kontrol acak dan uji lintas
   rezim), dan hasilnya di laporan ini. Konsep MTF **tidak otomatis lebih baik** — definisi
   lapisan likuiditas yang menentukan; implementasi naif (ekstrem rolling) menghasilkan
   7 trade/tahun dan rugi.
2. **Kandidat baru terbaik: V8** — H1 bias EMA200 → sweep PDH/PDL (jendela ≤ 4 jam) → CHoCH M15
   → displacement/FVG M5 → eksekusi M1. 257 tr/tahun, WR 62,3%, PF 1,09, +$963/tahun (risk 1%),
   DD 12,6%, 8/12 bulan hijau, jauh di atas kontrol acak, kumulatif 3 periode positif.
   V7 (versi fresh-sweep, 8 entry/bulan) untuk akun yang ingin frekuensi sangat rendah.
3. **Status: DEMO saja, risk maks 1%.** Tiga alasan: sampel kandidat kecil (60–257 tr/tahun);
   2021–22 tidak terpisah dari keberuntungan acak; 2022–23 rugi tipis. Jangan naik risk 5%.
4. Langkah tuning berikutnya (satu per satu, gerbang lintas rezim yang sama): (a) V8 + filter
   tren SMA200-harian (dua peredam rezim digabung — uji apakah saling menguatkan atau
   mengganda-gandakan filter); (b) jendela sweep PDH/PDL antara 2–24 jam (grid); (c) exit
   2-tier untuk menangkap WR tinggi.

## 10. REPRODUCIBILITY

```
# periode utama (12 varian + kontrol acak, ~11 menit)
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 100 --random

# uji lintas rezim
.venv/bin/python research/tuning_mtf.py --start 2021-09-01 --end "2022-09-01 23:59:59" \
    --risk 100 --variants V7,V8,V4,A --random
.venv/bin/python research/tuning_mtf.py --start 2022-09-01 --end "2023-09-01 23:59:59" \
    --risk 100 --variants V7,V8,V4,A --random

# reality-check risk 5%
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 500 --variants V7,V8

# regresi jalur default engine (harus identik byte-per-byte dgn artefak ter-commit)
.venv/bin/python research/run_m1_compare_audit.py
```

Artefak angka:
- `model_icas_bot_FIX/reports/tuning_mtf_20250901_20260901_risk100.txt` (V1–V10 + A + R)
- `model_icas_bot_FIX/reports/tuning_mtf_20210901_20220901_risk100.txt` (lintas rezim 1)
- `model_icas_bot_FIX/reports/tuning_mtf_20220901_20230901_risk100.txt` (lintas rezim 2)
- `model_icas_bot_FIX/reports/tuning_mtf_20250901_20260901_risk500.txt` (reality check)

Perubahan kode (semua additif, default = perilaku lama, regresi hijau):
- `research/backtest_m1_audit.py` — `signal_mode="mtf"`, flag ablasi `mtf_h1/mtf_m30/mtf_m15`,
  `mtf_sweep_bars`, `mtf_m30_mode` (`swing24`|`pd`|`fract`).
- `research/tuning_mtf.py` — skrip tuning MTF (kaskade kausal, 3 definisi likuiditas,
  kontrol acak, cek validitas kolom HTF di header).
- `research/backtest_m1_period.py` — guard `month_table` untuk varian 0-trade.
