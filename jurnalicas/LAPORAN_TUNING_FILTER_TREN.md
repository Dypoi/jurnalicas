# 🔧 LAPORAN TUNING — BASELINE ICT (CISD + LIQUIDITY) vs FILTER TREN MA200/EMA
## Periode utama 01-09-2025 → 01-09-2026 · + uji lintas rezim 2021–2023 · Data `XAUUSD_M1`

**Repo:** `Dypoi/jurnalicas` · **Branch:** `arena/01a080b1-jurnalicas` · **Tanggal:** 8 September 2026
**Permintaan:** *test engine saat ini (konsep ICT: CISD + liquidity) vs engine + filter tren MA200/EMA, backtest 01-09-2025 → 01-09-2026, laporkan hasil lengkap.*
**Tool baru:** `research/tuning_trend_filter.py` (parametrik) + ekstensi additive `research/backtest_m1_audit.py` — regresi audit M1 tetap hijau setelah ekstensi (perilaku default tidak berubah).

---

## 1. RINGKASAN EKSEKUTIF

| Pertanyaan | Jawaban |
|---|---|
| Apakah filter tren MA200/EMA memperbaiki baseline di periode yang diminta? | **Ya, signifikan**: baseline PF 0.89 (−$6.557) → **+SMA200 harian PF 1.02 (+$398)** / **+EMA200-M5 PF 1.07 (+$488, ekspektasi terbaik +$2,82/trade)** |
| Apakah CISD-strict lebih baik dari CHoCH/FVG? | **Tidak.** CISD-strict lebih buruk di SEMUA konfigurasi (PF 0.85–0.93 vs 0.89–1.07) |
| Apakah perbaikan itu edge sungguhan? | **Belum terbukti.** Uji lintas rezim (2 tahun OOS): 2021–2022 semua varian rugi (EMA200-M5 malah terburuk, PF 0.66); 2022–2023 baseline justru terbaik (PF 1.15). Kumulatif 3 tahun: semua varian masih **negatif** |
| Boleh naik real? | **Belum.** Perbaikan tahun utama = efek rezim bull (+63%), bukan edge yang stabil lintas rezim |

---

## 2. DESAIN EKSPERIMEN

### 2.1 Varian yang diuji (8 + kontrol acak)

| Kode | Varian | Makna |
|---|---|---|
| **A** | BASELINE | Engine saat ini: sweep likuiditas (SSL/BSL Asia+London) + displacement CHoCH/FVG |
| **B** | A + **SMA200 HARIAN** | BUY hanya bila close > SMA200 **kemarin** (hari selesai — kausal), SELL hanya di bawah |
| **C** | A + EMA200 HARIAN | idem, EMA200 harian (kemarin) |
| **D** | A + **EMA200 M5** | filter tren intraday: EMA200 pada close M5 bar berjalan (tertutup) |
| **E** | **CISD-strict** | displacement diganti CISD literal: close menembus *open bar pertama dari run ≥2 candle searah* sebelumnya + sweep likuiditas |
| **F/G/H** | CISD + tiap filter | kombinasi |
| **R** | ENTRY ACAK | geometri identik, titik entry acak (pengukur edge vs keberuntungan) |

### 2.2 Kondisi uji (identik untuk semua varian)
- **Data**: `XAUUSD_M1` bid/ask terpisah, spread riil implisit (BUY di ask, exit di bid) · warm-up **330 hari** untuk konvergensi MA200 harian (file 2024–2025 dimuat penuh)
- **Engine**: audit M1 anti-repaint, pesimis (SL dulu intrabar), eksekusi M1 bar berikutnya, kenaikan SL efektif bar berikutnya
- **Geometri** (tidak diubah — ini eksperimen sinyal, bukan geometri): SL 150p · TP 187,5/375/562,5p · split 30/25/25/20 · trailing 100p/30p · BE+ OFF · 24 jam
- **Guard spread $1,20** (p95 feed) — guard literal config $0,35 memblokir 99,6% bar (bot diam)
- **Risk $100/trade (1%)** untuk komparabilitas antar-varian; **$500 (5%)** untuk reality-check varian terbaik · modal $10.000 fixed
- Slippage & komisi tidak dimodelkan (realita akan sedikit lebih buruk)

---

## 3. HASIL PERIODE UTAMA — 01-09-2025 → 01-09-2026 (risk 1%)

| Varian | Tr | WR% | **PF** | **Net $** | Exp $/tr | DD% | **Entry/bln** | Bulan hijau | BUY/SELL |
|---|---|---|---|---|---|---|---|---|---|
| **A — BASELINE** | 1.278 | 57,1 | **0,89** | **−6.557** | −5,13 | 65,6 | 98,3 | 3/13 | 598/680 |
| **B — +SMA200 HARIAN** | 576 | 59,7 | **1,02** | **+398** | +0,69 | 24,6 | 48,0 | **8/12** | 416/160 |
| C — +EMA200 HARIAN | 566 | 59,4 | 1,00 | +76 | +0,13 | 22,4 | 43,5 | 8/13 | 455/111 |
| **D — +EMA200 M5** | 173 | 59,5 | **1,07** | **+488** | **+2,82** | **13,7** | 14,4 | 7/12 | 76/97 |
| E — CISD-strict | 393 | 55,7 | 0,85 | −2.714 | −6,91 | 31,0 | 32,8 | 3/12 | 179/214 |
| F — CISD+SMA200d | 171 | 55,0 | 0,85 | −1.218 | −7,12 | 16,1 | 14,2 | 6/12 | 120/51 |
| G — CISD+EMA200d | 172 | 57,0 | 0,93 | −580 | −3,37 | 10,6 | 14,3 | 6/12 | 133/39 |
| H — CISD+EMA200-M5 | 27 | 63,0 | 0,90 | −103 | −3,80 | 4,0 | 2,7 | 5/10 | 12/15 |
| R — ACAK (kontrol) | 546 | 58,8 | 0,98 | −563 | −1,03 | 22,1 | 42,0 | 8/13 | 283/263 |

**Pembacaan:**
1. **Filter tren menyelesaikan masalah utama tahun ini**: baseline membuka 680 posisi SELL di tahun bull +63% → filter memangkas SELL menjadi 160 (B) / 97 (D) dan membalik PnL dari −$6.557 menjadi positif.
2. **D (EMA200 M5)** ekspektasi per trade terbaik (+$2,82) dan DD terendah (13,7%), tapi frekuensi turun drastis (98 → **14 entry/bulan**). **B (SMA200 harian)** mempertahankan aktivitas 48 entry/bulan dengan 8/12 bulan hijau — paling seimbang.
3. **CISD-strict kalah dari CHoCH/FVG di semua pasangan** (E vs A: 0,85 vs 0,89; F vs B: 0,85 vs 1,02; G vs C: 0,93 vs 1,00; H vs D: 0,90 vs 1,07). Interpretasi CISD literal (tembus open run ≥2 candle) lebih rapuh daripada break swing 5-bar + FVG. **Rekomendasi: pertahankan CHoCH/FVG.**
4. Semua varian terbaik hanya **marginal di atas acak** (R: PF 0,98) — margin tipis, belum edge meyakinkan.

### 3.1 Rincian bulanan varian terbaik

**B — +SMA200 HARIAN (576 trade, 48/bln):**
```
2025-09  +539 | 10  -63 | 12  +406 | 01 +1.347 | 02   +297 | 03 -1.777 | 04  +337
2026-05 -1.116 | 06  +687 | 07   +55 | 08  -386          → 8/12 hijau, puncak DD di Mar-May
```
**D — +EMA200 M5 (173 trade, 14/bln):**
```
2025-09   +63 | 10 -546 | 11  -34 | 12  -233 | 01  +733 | 02    +92 | 03  -229
2026-04  +679 | 05  +164 | 06 +113 | 07  -678 | 08  +364          → 7/12 hijau
```
*(Tabel lengkap 12 baris per varian ada di artefak `reports/tuning_trendfilter_20250901_20260901_risk100.txt`.)*

### 3.2 Reality-check risiko 5% ($500 — setting plan saat ini)

| Varian | Tr | PF | Net | **Max DD** |
|---|---|---|---|---|
| B — +SMA200 harian | 576 | 1,02 | +$1.875 | **62,5%** |
| D — +EMA200 M5 | 173 | 1,07 | +$2.300 | **56,9%** |

Bertahan setahun (baseline bangkrut di bulan ke-2), tetapi drawdown 57–63% tidak layak dijalankan. Pada risiko 1% DD-nya 13,7–24,6% — itulah level risiko yang masuk akal untuk sistem tipis begini.

---

## 4. UJI LINTAS REZIM (out-of-sample — anti self-deception)

Tahun utama DAN tahun warm-up sama-sama bullish, jadi "filter tren bagus" bisa saja cuma menunggangi bull market. Diuji pada dua tahun berbeda rezim, varian yang sama:

| Varian | **2021-09→2022-09** (bearish/mixed, emas ±1830→1700) | **2022-09→2023-09** (recovery, 1700→1900) | **Kumulatif 3 tahun (risk 1%)** |
|---|---|---|---|
| A — BASELINE | PF 0,89 · −$1.219 | **PF 1,15 · +$1.386** | **−$6.390** |
| B — +SMA200 harian | PF 0,86 · −$1.070 | PF 0,93 · −$537 | **−$1.209** |
| D — +EMA200 M5 | PF **0,66** · −$2.259 | PF 1,05 · +$207 | **−$1.564** |

**Temuan jujur:**
- Di tahun bearish/mixed **semua varian rugi** — dan filter tren justru **memperburuk** (D terburuk: PF 0,66; whipsaw MA di pasar ranging menambah filter yang salah arah).
- Di tahun recovery, **baseline tanpa filter justru terbaik** (PF 1,15) — filter memotong profit.
- Kumulatif 3 tahun: filter mengurangi kerugian (−$6.390 → −$1.2 s.d. −$1.6 ribu) **tetapi tetap tidak menghasilkan sistem yang menguntungkan secara konsisten**.
- Kesimpulan metodologis: **perbaikan PF 1,02–1,07 di periode yang Anda minta adalah efek rezim**, bukan edge struktural. Filter tren layak dipertahankan sebagai *risk reducer* di rezim trending, bukan sebagai mesin profit.

---

## 5. KESIMPULAN & LANGKAH TUNING BERIKUTNYA

**Jawaban atas pertanyaan Anda (periode 01-09-2025 → 01-09-2026):**
- Baseline (CISD/CHoCH + liquidity): **PF 0,89 · WR 57,1% · −$6.557 · 98 entry/bulan**
- + Filter tren terbaik: **D (EMA200-M5): PF 1,07 · WR 59,5% · +$488 · 14 entry/bulan · DD 13,7%** dan **B (SMA200 harian): PF 1,02 · WR 59,7% · +$398 · 48 entry/bulan**
- CISD-strict: **selalu lebih buruk** — jangan dipakai menggantikan CHoCH/FVG.

**Rekomendasi tuning lanjutan (berurutan):**
1. **Adopsi B (SMA200 harian) sebagai filter default** bila engine tetap dijalankan di demo — frekuensi masih hidup (48/bln), mengurangi kerugian kumulatif 3 tahun 5×lipat, DD 1% only. Tetap DEMO.
2. Masalah yang belum terjawab: **tahun bearish/ranging tetap rugi di semua varian** → kandidat berikutnya yang layak diuji: filter volatilitas/regime eksplisit (mis. ADX atau lebar range harian), atau pengaruh **timeframe sinyal M15**, atau restukturisasi exit (2-tier) — satu per satu, dengan uji lintas rezim seperti §4 sebagai gerbang wajib.
3. **Jangan menaikkan risiko > 1%** sebelum ada varian yang lulus gerbang: PF > acak dengan margin jelas + positif di ≥2 rezim berbeda.

---

## 6. REPRODUKSI

```bash
cd jurnalicas/model_icas_bot_FIX
# 8 varian + kontrol acak, periode utama:
python research/tuning_trend_filter.py --start 2025-09-01 --end "2026-09-01 23:59:59" --risk 100 --random
# reality-check 5%:
python research/tuning_trend_filter.py --start 2025-09-01 --end "2026-09-01 23:59:59" --variants B,D --risk 500
# uji lintas rezim:
python research/tuning_trend_filter.py --start 2021-09-01 --end "2022-09-01 23:59:59" --variants A,B,D
python research/tuning_trend_filter.py --start 2022-09-01 --end "2023-09-01 23:59:59" --variants A,B,D
```

**Batasan:** MA harian memakai nilai kemarin (kausal); warm-up 330 hari → SMA200 valid penuh di periode uji; EMA200 konvergensi ±8% sisa seed. CISD-strict adalah satu definisi operasional (run ≥2 candle, level = open bar pertama run) — definisi CISD lain mungkin berbeda hasil. Slippage/komisi tidak dimodelkan. Kontrol acak memakai seed 42 (n=1.278).

---

**Disusun oleh:** agent QA/quant pada Arena.ai Agent Mode
**Pesan kunci:** *Filter tren MA200/EMA memang membalik hasil periode yang Anda minta (PF 0,89 → 1,02–1,07) dan wajib jadi kandidat default — tetapi uji lintas rezim membuktikan perbaikan itu lahir dari tahun bull, bukan edge permanen. Gunakan sebagai peredam risiko, bukan janji profit.*
