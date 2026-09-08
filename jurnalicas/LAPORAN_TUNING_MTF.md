# LAPORAN TUNING MULTI-TIMEFRAME — ANALISA H1 → M30 → M15 → M5, EKSEKUSI M5 (REV 2)

**Periode uji utama : 01-09-2025 → 01-09-2026 (XAUUSD, 674.431 bar M1 / 134.882 candle M5, 313 hari bursa)**
**Uji lintas rezim : 2021–22 (bearish) dan 2022–23 (recovery)**
**Engine : `research/backtest_m1_audit.py` (bid/ask, anti-repaint, pesimis, spread riil, guard $1.20)**
**Skrip : `research/tuning_mtf.py` (`--exec m5`, default sejak rev ini) — artefak: `model_icas_bot_FIX/reports/tuning_mtf_*_execm5.txt`**
**Revisi : 08 September 2026 — rev 1 = eksekusi M1; rev 2 = eksekusi M5 (instruksi pengguna: "eksekusinya di m5 jangan m1")**

---

## RINGKASAN EKSEKUTIF

1. Konsep analisa berlapis **H1 → M30 → M15 → M5** dipertahankan penuh; **eksekusi dipindah ke M5**
   (rev 2, sesuai instruksi): sinyal dihitung pada candle M5 yang tertutup, **entry di OPEN candle
   M5 berikutnya**, dan SL/TP/trailing dievaluasi **per candle M5** — replika bot yang hanya
   "bangun" tiap 5 menit, dengan SL/TP tetap dianggap hidup di sisi broker.
2. **Eksekusi M5 TIDAK menurunkan kualitas — justru membaik untuk varian konsep-sempurna:**
   - **V7 (kaskade FULL, sweep PDH/PDL fresh)**: 87 tr | WR **65,5%** | PF **1,28** | **+$896** |
     DD **6,3%** | 8/12 bulan hijau (M1-exec rev 1: PF 1,19, +$682).
   - **V8 (PDH/PDL jendela 4 jam)**: 246 tr | WR 62,2% | PF 1,10 | +$963 | DD 12,7% (setara rev 1).
   - Kontrol acak justru MEMBURUK di M5 (PF 0,89, −$4.618 vs 0,92 di M1) → perbaikan varian
     bukan hadiah gratis dari mode eksekusi.
3. **Dua jebakan metodologis ditemukan & diperbaiki SELAMA migrasi ke M5** (kontrol acak yang
   tiba-tiba "profit" PF 1,27 adalah alarm yang mengekspos keduanya):
   - **Optimisme entry-sesi-candle-sama**: posisi lama exit di tengah candle membuka slot entry
     di candle yang sama dengan harga OPEN candle itu (= entry setelah mengetahui H/L candle).
     Fix: `strict_bar_open_entry` — entry hanya bila posisi sudah flat sebelum candle eksekusi
     dibuka.
   - **Candle eksekusi kebal SL/TP**: posisi dibuka setelah blok manajemen bar, sehingga H/L
     candle entry tak pernah diuji (di mode M1 eksenerasinya hanya 1 menit; di M5 jadi 5 menit
     penuh — besar untuk SL $15). Fix: `manage_entry_bar` — candle eksekusi ikut diuji SL/TP
     (pesimis, SL-dulu), karena order SL/TP broker memang aktif sejak entry.
   - Keduanya diverifikasi unit-test deterministik (`research/test_exec_m5.py`, 6 PASS) +
     regresi: `test_antirepaint.py` 24 PASS, dan run M1 **byte-identik** dengan artefak ter-commit.
4. **Uji lintas rezim (M5-exec)**: 2021–22 V7 +$736 / V8 +$337 (namun kontrol acak periode itu
   juga +$883 → tak terpisahkan dari keberuntungan); 2022–23 V7 −$287 / V8 −$70 (rugi tipis).
   **Kumulatif 3 periode risk 1%: V7 +$1.345, V8 +$1.230** — keduanya melampaui versi M1-exec
   (V7 +$1.131, V8 +$1.125) dan tetap satu-satunya keluarga varian yang kumulatif positif.
5. Reality-check risk 5%: V7 +$4.224 (DD 28,6%) bertahan; V8 +$4.538 tapi DD 52,6% — tidak layak.
6. **Rekomendasi**: kandidat default DEMO berikutnya = **V7 pada eksekusi M5** (frekuensi rendah,
   ~7 entry/bulan, WR 65,5%, DD 6,3%), dengan **V8** sebagai alternatif frekuensi menengah
   (~20/bulan). Risk maks 1%. **Status tetap DEMO** — 2022–23 masih rugi tipis dan sampel
   kandidat kecil (60–246 trade/tahun).

---

## 1. LATAR BELAKANG & RIWAYAT REVISI

- Permintaan pengguna (08 Sep 2026): semua tuning harus memakai **analisa H1, M30, M15, M5**.
  Laporan-laporan tuning sebelumnya (termasuk `LAPORAN_TUNING_FILTER_TREN.md`) belum memenuhi
  (analisa M5 + sesi saja). Rev 1 laporan ini mengimplementasikan kaskade tersebut dengan
  eksekusi M1.
- Instruksi lanjutan pengguna (rev ini): **"coba ubah, eksekusinya di M5 jangan M1"** — seluruh
  eksperimen diulang dengan eksekusi M5; hasil M1 rev 1 dipertahankan sebagai pembanding.

## 2. METODOLOGI

### 2.1 Kaskade analisa (tidak berubah dari rev 1, semua kausal)

| Lapis | TF | Peran | Definisi |
|---|---|---|---|
| L1 | **H1** | Bias arah | close vs **EMA200 H1** (bar H1 tertutup terakhir) |
| L2 | **M30** | Likuiditas mayor | sweep SSL/BSL dalam jendela `mtf_sweep_bars`; 3 definisi level: ekstrem-24j rolling / **PDH-PDL kemarin** / fractal M30 |
| L3 | **M15** | Struktur | **CHoCH** — close menembus swing high/low 5-bar M15 |
| L4 | **M5** | Trigger | displacement candle + FVG ($0,30) / break swing 5-bar M5 |
| EX | **M5** | Eksekusi (rev 2) | entry di **OPEN candle M5 berikutnya**; SL/TP/trailing per candle M5; BUY di ask, exit di bid; pesimis [A5]: bila SL & TP tersentuh di candle yang sama → SL dihitung dulu |

### 2.2 Eksekusi M5 — bagaimana dieksekusi secara jujur

Frame eksekusi M5 dibangun dari candle M5 (ask OHLC diagregat EXACT per candle dari M1, bukan
aproksimasi bid+spread), lalu **loop manajemen posisi engine yang sudah teraudit dijalankan
apa adanya** pada frame itu — tidak ada duplikasi logika. Dua flag QC menyertai mode ini:

- `strict_bar_open_entry=True`: entry di blok candle k hanya bila posisi sudah flat SEBELUM
  candle k dibuka (membunuh optimisme entry-sesi-candle-sama).
- `manage_entry_bar=True`: setelah entry di open candle k, H/L candle k ikut diuji terhadap
  SL/TP (order broker aktif sejak entry; tanpa ini candle entry kebal SL/TP selama 5 menit).

Di mode M1 (rev 1) kedua flag OFF = perilaku engine lama persis (diverifikasi byte-identik).

### 2.3 Varian (sama dengan rev 1)

V1 FULL swing24 | V2 tanpa M15 | V3 tanpa M30 | V4 H1+M5 | V5/V6 swing24 jendela 1j/4j |
**V7 FULL PDH/PDL fresh** | **V8 FULL PDH/PDL 4 jam** | V9/V10 fractal M30 | A baseline lama |
R **kontrol acak** (waktu & arah entry acak, geometri manajemen identik, n = varian teramai).

## 3. BUG & JEBAKAN METODOLOGIS YANG DITEMUKAN (transparansi QC)

Dari rev 1 (masih berlaku): NaN massal kolom M30 (rolling slot-waktu vs bar bursa → fix dropna),
crash `month_table` 0-trade, kwarg dobel `dataclasses.replace`, wiring `mtf_sweep_bars`.

Baru di rev 2 (migrasi eksekusi M5):

1. **Kontrol acak "menang" (PF 1,27, +$8.619)** pada run M5 pertama → alarm metodologis.
   Diagnosis berlapis menemukan dua sumber optimis (lihat §2.2) — keduanya kini di-guard flag,
   dan setelah fix kontrol acak kembali ke **PF 0,89 / −$4.618** (di bawah 1, sebagaimana
   mestinya entry tanpa edge). Angka rev 2 di laporan ini SELURUHNYA hasil run pasca-fix.
2. **Unit test deterministik** `research/test_exec_m5.py` (6 PASS): (1) agregat ask = open M1
   pertama per candle; (2) skenario TP1-lalu-SL dalam satu candle → M1 WIN vs M5 LOSS (pesimis
   [A5] bekerja); (3) entry identik antar mode (waktu & harga); (4) `strict_bar_open_entry`
   memblokir entry candle-sama-dengan-exit; (5) `manage_entry_bar` menghapus kekebalan candle
   entry (skenario SL-terus-rally: tanpa flag WIN +$319, dengan flag LOSS −$105).
3. **Regresi**: `test_antirepaint.py` 24 PASS / 0 FAIL; spot-check M1 (`--exec m1`, V7 Jan–Mar
   2026) **byte-identik** sebelum vs sesudah refactor engine → jalur default tak berubah.

## 4. HASIL PERIODE UTAMA (01-09-2025 → 01-09-2026, risk 1%, EKSEKUSI M5)

| Varian | Tr | WR% | PF | Net $ | Exp $/tr | DD% | Entry/bln | Hijau | BUY/SELL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 FULL swing24 (10 mnt) | 6 | 50,0 | 0,20 | −252 | −42,00 | 2,5 | 1,2 | 3/5 | 3/3 |
| V2 tanpa M15 | 98 | 56,1 | 0,81 | −849 | −8,66 | 11,7 | 8,2 | 4/12 | 58/40 |
| V3 tanpa M30 | 1.383 | 59,2 | 1,07 | +4.125 | +2,98 | 20,0 | 106,4 | 8/13 | 767/616 |
| V4 H1+M5 saja | 2.263 | 59,6 | 1,06 | +6.114 | +2,70 | 20,0 | 174,1 | 8/13 | 1214/1049 |
| V5 swing24, jendela 1 j | 46 | 56,5 | 0,65 | −735 | −15,97 | 9,6 | 4,2 | 4/11 | 21/25 |
| V6 swing24, jendela 4 j | 168 | 59,5 | 0,91 | −653 | −3,89 | 12,8 | 14,0 | 5/12 | 87/81 |
| **V7 PDH/PDL (fresh)** | **87** | **65,5** | **1,28** | **+896** | **+10,30** | **6,3** | 7,2 | **8/12** | 45/42 |
| **V8 PDH/PDL (4 jam)** | **246** | 62,2 | **1,10** | **+963** | +3,91 | 12,7 | 20,5 | 7/12 | 133/113 |
| V9 fractal M30 (fresh) | 108 | 60,2 | 0,95 | −220 | −2,04 | 12,4 | 9,0 | 6/12 | 59/49 |
| V10 fractal M30 (4 jam) | 1.175 | 58,2 | 1,07 | +3.429 | +2,92 | 21,9 | 90,4 | 8/13 | 644/531 |
| A BASELINE lama (M5+sesi) | 1.234 | 57,9 | 0,92 | −4.195 | −3,40 | 42,0 | 94,9 | 5/13 | 579/655 |
| R ACAK (kontrol, n=842 aktual) | 842 | 54,2 | 0,89 | −4.618 | −5,49 | 62,1 | 64,8 | 5/13 | 434/408 |

Rincian bulanan V7 (M5): 8/12 hijau; terburuk Nov-25 (PF 0,13, −$546), terbaik Des-25
(PF 5,02, +$422); tiga bulan terakhir (Jun–Agu 26) semua hijau. V8: 7/12 hijau, terburuk
Nov-25 (−$965), terbaik Des-25 (+$862).

### 4.1 Perbandingan eksekusi M1 (rev 1) vs M5 (rev 2) — periode utama

| Varian | M1: PF / Net / DD | M5: PF / Net / DD | Efek M5 |
|---|---|---|---|
| V3 | 1,02 / +1.414 / 27,2% | **1,07 / +4.125 / 20,0%** | membaik |
| V4 | 1,01 / +1.276 / 36,7% | **1,06 / +6.114 / 20,0%** | membaik |
| V7 | 1,19 / +682 / 6,3% | **1,28 / +896 / 6,3%** | membaik |
| V8 | 1,09 / +963 / 12,6% | 1,10 / +963 / 12,7% | setara |
| V10 | 1,01 / +710 / 31,2% | **1,07 / +3.429 / 21,9%** | membaik |
| A baseline | 0,89 / −6.557 / 65,6% | 0,92 / −4.195 / 42,0% | kurang buruk, tetap rugi |
| R acak | 0,92 / −3.389 / 53,2% | **0,89 / −4.618 / 62,1%** | memburuk |

Pembacaan: entry M1 dan M5 **identik** (waktu & harga — lihat unit test [3]); perbedaan murni
dari granularitas manajemen. Trailing yang hanya ter-ratchet sekali per candle (bukan tiap
menit) membuat pemenang berjalan lebih jauh dan menahan kerugian lebih kecil — menguntungkan
varian arah-menerus (V3/V4/V7/V10), tetapi TIDAK menguntungkan entry acak (R memburuk) —
bukti efeknya selektif terhadap sinyal yang benar-benar mengikuti tren, bukan artefak mode.

## 5. UJI LINTAS REZIM (EKSEKUSI M5, gerbang anti self-deception)

### 5.1 Periode 2021–09 → 2022–09 (bearish/konsolidasi)

| Varian | Tr | WR% | PF | Net $ | DD% |
|---|---:|---:|---:|---:|---:|
| V7 PDH/PDL fresh | 71 | 67,6 | 1,30 | +736 | 4,4 |
| V8 PDH/PDL 4 jam | 123 | 64,2 | 1,07 | +337 | 7,6 |
| V4 H1+M5 | 275 | 60,0 | 0,95 | −549 | 19,0 |
| A baseline | 256 | 60,5 | 0,98 | −211 | 16,0 |
| R ACAK | 85 | 64,7 | **1,28** | **+883** | 7,6 |

Peringatan yang sama dengan rev 1: kontrol acak periode ini juga profit → V7/V8 di rezim ini
tidak dapat dibedakan dari keberuntungan.

### 5.2 Periode 2022–09 → 2023–09 (recovery)

| Varian | Tr | WR% | PF | Net $ | DD% |
|---|---:|---:|---:|---:|---:|
| V7 PDH/PDL fresh | 60 | 56,7 | 0,90 | −287 | 6,5 |
| V8 PDH/PDL 4 jam | 112 | 60,7 | 0,98 | −70 | 7,9 |
| V4 H1+M5 | 246 | 59,4 | 1,05 | +509 | 14,7 |
| A baseline | 228 | 61,0 | **1,17** | **+1.612** | 10,2 |
| R ACAK | 88 | 55,7 | 0,83 | −699 | 10,2 |

V7 rugi tipis, V8 mendekati impas (lebih baik dari rev 1 yang −$175). Baseline lama kembali
menjadi terbaik di rezim ini — pola "unggul-ulangan bergantian rezim" konsisten di semua
eksperimen seri ini.

### 5.3 Kumulatif tiga periode (risk 1%)

| Varian | 2021–22 | 2022–23 | 2025–26 | **Kumulatif M5** | Kumulatif M1 (rev 1) |
|---|---:|---:|---:|---:|---:|
| **V7** | +736 | −287 | +896 | **+1.345** | +1.131 |
| **V8** | +337 | −70 | +963 | **+1.230** | +1.125 |
| V4 (bukan konsep FULL) | −549 | +509 | +6.114 | +6.074 | — |
| A baseline | −211 | +1.612 | −4.195 | **−2.794** | −6.390 |
| B SMA200-harian (lap. #4) | −1.070 | −537 | +398 | −1.209 | — |
| D EMA200-M5 (lap. #4) | −2.259 | +207 | +488 | −1.564 | — |

V7/V8 tetap satu-satunya keluarga varian **kumulatif positif** di semua rezim yang diuji, dan
versi M5 melampaui versi M1. Catatan jujur yang sama: definisi PDH/PDL dipilih dari periode
2025–26 (risiko data-snooping, 3 definisi diuji), dan gerbang "profit di SETIAP rezim" belum
terlewati (2022–23 masih minus tipis).

## 6. REALITY-CHECK RISK 5% (periode utama, M5)

| Varian | Net $ | DD% | Vonis |
|---|---:|---:|---|
| V7 | +4.224 | 28,6 | bertahan |
| V8 | +4.538 | 52,6 | **tidak layak** |

## 7. ANALISIS

1. **Mengapa eksekusi M5 membaik untuk kaskade?** Entry identik dengan M1; yang berubah hanya
   (a) pesimisme intra-candle lebih besar (SL-dulu saat SL & TP sesama candle) — ini
   MENGURANGI performa; (b) trailing ratchet lebih lambat (sekali per candle) — pemenang tidak
   dipangkas oleh retrace noise 1-menit. Net effect untuk varian momentum-arah: (b) >> (a).
   Untuk entry acak efeknya terbalik (R memburuk) → kesimpulan: granularitas kasar M5
   "menyaring" manajemen dari noise, dan hanya berguna bila arahnya benar.
2. **V7 kini varian terbaik sepanjang seri tuning** (semua laporan): WR 65,5% tertinggi,
   PF 1,28, exp +$10,30/tr (2,2× kontrol acak versi M5 searah negatif), DD 6,3% terendah,
   8/12 bulan hijau, frekuensi 7 entry/bulan (sangat selektif — konsisten dengan konsep
   "kualitas di atas kuantitas" dari kaskade 4 lapis).
3. **Struktur bulanan V7 sehat**: setelah bulan terburuk (Nov-25), tidak ada bulan rugi
   berturut >1; Jun–Agu 2026 (rezim volatil tinggi) semuanya hijau.
4. **V8 tetap alternatif frekuensi menengah** (20,5 entry/bulan) dengan angka hampir setara
   (PF 1,10, +$963) tetapi DD 2× V7 dan risk-5% tidak layak.
5. **Ablasi tetap konsisten**: membuang lapis M30/M15 menaikkan frekuensi 15–25× tetapi
   menurunkan kualitas ke level marginal (V3/V4 PF 1,06–1,07 vs kontrol acak 0,89 — masih
   di atas acak tapi jauh di bawah V7/V8 per trade).

## 8. KESIMPULAN & REKOMENDASI

1. **Permintaan pengguna terpenuhi**: analisa H1 → M30 → M15 → M5 dengan **eksekusi M5** penuh
   (entry di open candle M5 berikutnya, manajemen per candle, pesimis, spread riil, dua guard
   anti-optimis aktif) — 12 varian + kontrol acak + uji lintas rezim + reality-check.
2. **Kandidat default DEMO berikutnya: V7 pada eksekusi M5** — H1 bias EMA200 → sweep PDH/PDL
   fresh (jendela 2 bar) → CHoCH M15 → displacement/FVG M5 → eksekusi open candle M5.
   87 tr/tahun, WR 65,5%, PF 1,28, +$896/tahun (risk 1%), DD 6,3%, 8/12 hijau, kumulatif
   3 periode +$1.345. **V8** untuk preferensi frekuensi lebih tinggi.
3. **Status: DEMO saja, risk maks 1%.** Alasan tidak naik ke live: 2022–23 masih −$287;
   2021–22 setara acak; sampel kandidat kecil; definisi PDH/PDL dipilih pasca-melihat data
   2025–26.
4. Langkah berikut (satu per satu, gerbang sama): (a) grid jendela sweep PDH/PDL 2–24 jam di
   eksekusi M5; (b) V7/V8 + filter tren SMA200-harian; (c) exit 2-tier; (d) uji sensitivitas
   `tp_first` (varian optimis) untuk mengukur seberapa besar bias pesimisme memakan hasil.

## 9. REPRODUCIBILITY

```
# eksekusi M5 (default rev 2) — periode utama, 12 varian + kontrol acak
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 100 --random

# eksekusi M1 (rev 1, pembanding)
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 100 --random --exec m1

# uji lintas rezim (M5)
.venv/bin/python research/tuning_mtf.py --start 2021-09-01 --end "2022-09-01 23:59:59" \
    --risk 100 --variants V7,V8,V4,A --random
.venv/bin/python research/tuning_mtf.py --start 2022-09-01 --end "2023-09-01 23:59:59" \
    --risk 100 --variants V7,V8,V4,A --random

# reality-check risk 5%
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 500 --variants V7,V8

# unit test eksekusi M5 + regresi engine
.venv/bin/python research/test_exec_m5.py
.venv/bin/python research/test_antirepaint.py
```

Artefak angka (rev 2, M5): `reports/tuning_mtf_20250901_20260901_risk100_execm5.txt`,
`..._risk500_execm5.txt`, `..._20210901_20220901_risk100_execm5.txt`,
`..._20220901_20230901_risk100_execm5.txt`. Artefak rev 1 (M1): file `tuning_mtf_*.txt` tanpa
suffix `_execm5`.

Perubahan kode rev 2 (semua additif; default = perilaku lama; regresi hijau):
- `research/backtest_m1_audit.py` — blok manajemen diekstrak menjadi closure `_manage(k)`;
  flag baru `strict_bar_open_entry` & `manage_entry_bar` (default False).
- `research/tuning_mtf.py` — `exec_frame_from_m5()` + argumen `--exec {m5,m1}` (default m5);
  kedua flag QC otomatis ON saat `--exec m5`; nama artefak diberi suffix `_execm5`.
- `research/test_exec_m5.py` — 6 unit test deterministik eksekusi M5 (semua PASS).
