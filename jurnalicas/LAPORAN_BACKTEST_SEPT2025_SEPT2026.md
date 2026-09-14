# 📊 LAPORAN BACKTEST SETAHUN — MODEL ICAS "SWING-150 C" 
## Periode 01-09-2025 → 01-09-2026 · Data `XAUUSD_M1` (bid/ask terpisah)

**Repo:** `Dypoi/jurnalicas` · **Branch:** `arena/01a080b1-jurnalicas` · **Tanggal:** 8 September 2026
**Permintaan:** *backtest engine dengan strategi plan saat ini pada folder `XAUUSD_M1`, periode 01-09-2025 s/d 01-09-2026 — hasil lengkap: WR, PnL, frekuensi entry per bulan, PF.*
**Status kode saat run:** pasca audit forensik #1–#3 (37+6 temuan diperbaiki; QA `run_qa.py` **8 PASS / 0 FAIL**; 36 assertion fault-injection hijau). Engine backtest yang dipakai = replikasi exact logika live, teraudit anti-repaint & pesimis.

---

## 1. RINGKASAN EKSEKUTIF

| Run | Risk/trade | Trades | WR | **PF** | **Net PnL** | Entry/bulan | Status |
|---|---|---|---|---|---|---|---|
| **A — Guard literal config ($0.35)** | $500 (5%) | **7** | 42,9% | **0.72** | **−$558,53** | 1,4 | Bot praktis **tidak bisa entry** di feed ini (99,6% bar diblokir spread guard) |
| **B — Guard p95 feed ($1.20)** | $500 (5%) — *plan* | 110 | 49,1% | **0.64** | **−$10.001,57** | 55 | ⛔ **BANGKRUT dalam 2 bulan** (ekuitas habis 31 Okt 2025) |
| **C — Guard p95 feed ($1.20)** | $100 (1%) — referensi | 1.278 | 57,1% | **0.89** | **−$6.557,01** (−65,6%) | **98** | Bertahan setahun, DD 65,6%, hanya 3/13 bulan hijau |
| **D — BASELINE ACAK** (geometri sama) | $100 (1%) | 833 | 58,3% | **1.02** | **+$779,17** | ~64 | **Entry acak MENGALAHKAN sinyal ICAS** di tahun ini |

**Kesimpulan satu kalimat:** pada data setahun penuh milik Anda sendiri (termasuk bull-market emas $3.436 → $5.597), strategi plan saat ini **kehilangan uang di semua konfigurasi** — dan performanya **lebih buruk daripada entry acak** dengan geometri yang sama.

---

## 2. DATA & METODOLOGI

| Item | Detail |
|---|---|
| Sumber | `XAUUSD_M1/XAUUSD_M1_20250901_20260901.csv` + 3 minggu terakhir file 2024–2025 sebagai **warm-up level sesi** (agar 1 Sep 2025 sudah punya level kemarin yang sah, tanpa lookahead) |
| Bar | **376.338 bar M1** / 71.128 bar M5 · **313 hari bursa** |
| Harga periode | $3.436,55 → $5.596,81 (**tahun bullish +63%**) |
| Spread bar | median **$0,67** · p95 $1,07 · maks $9,95 |
| Engine | `research/backtest_m1_audit.py` (teraudit) via runner baru `research/backtest_m1_period.py` |
| Fitur engine | level sesi **point-in-time** (anti-repaint F-18) · sinyal M5 bar tertutup (sweep+CHoCH/FVG) · eksekusi di M1 berikutnya · **BUY di ask, exit di bid** (spread riil implisit) · **SL dicek sebelum TP** dalam bar (pesimis) · kenaikan SL efektif bar berikutnya |
| Tidak dimodelkan | slippage eksekusi (terukur live ±$1,27/entry — angka nyata akan **lebih buruk**), komisi/swap |
| Parameter | persis `config.py`: SL 150p ($15) · TP 187,5/375/562,5p · split 30/25/25/20 · trailing 100p/30p · BE+ OFF · 24 jam · maks 999/hari · CB 999 · fixed non-compounding |

**Kenapa dua run guard spread?** `MAX_SPREAD_POINTS=350` di config = **$0,35** pada simbol 3-digit. Median spread feed ini **$0,67** → hanya **0,36% bar lolos** — dengan guard apa adanya, bot praktis tidak pernah entry (Run A: 7 trade setahun). Supaya kinerja *strateginya* tetap terukur, disediakan Run B/C dengan guard $1.20 (p95 feed, mengikuti preseden audit M1 sebelumnya). Ini sendiri sudah satu temuan penting: **strategi ini terkunci pada feed ber-spread sempit** — pindah broker/data = tidak bisa jalan.

---

## 3. HASIL UTAMA

### 3.1 Run B — Konfigurasi plan sesungguhnya (risk $500/trade = 5%)

```
Trades        : 110  (54W / 0BE / 56L)
Win Rate      : 49.09%
Profit Factor : 0.64
Net PnL       : −$10.001,57  (ROI −100,02%)
Ekspektasi    : −$90,92/trade
AvgWin/AvgLoss: +$328,12 / −$495,00
Max Drawdown  : 100,02%
Loss beruntun : 6
BUY/SELL      : 25/85        ← 77% posisi SELL di pasar yang naik +63%
⛔ SIMULASI BANGKRUT — ekuitas habis pada 31 Oktober 2025 (bulan ke-2)
```

| Bulan | Entry | W/BE/L | WR% | PF | Net | Ekuitas |
|---|---|---|---|---|---|---|
| 2025-09 | 62 | 30/0/32 | 48,4 | 0,67 | −$5.236 | $4.764 |
| 2025-10 | 48 | 24/0/24 | 50,0 | 0,60 | −$4.766 | **−$2** ⛔ |

### 3.2 Run C — Risiko riset 1% (kurva setahun penuh terlihat)

```
Trades        : 1.278  (730W / 0BE / 548L)
Win Rate      : 57.12%      | Non-Loss Rate: 57.12%
Profit Factor : 0.89
Net PnL       : −$6.557,01  (ROI −65,57%)
Ekspektasi    : −$5,13/trade
AvgWin/AvgLoss: +$69,84 / −$105,00   ← payoff 0.66 → butuh WR 60,2% utk BE; WR aktual 57,1%
Max Drawdown  : 65,57%
Loss beruntun maks : 8
Tr/hari bursa : 4,08
TP1/TP2/TP3   : 25,7% / 4,7% / 1,0%  ← TP2 & TP3 praktis tidak pernah terjangkau
Trailing aktif: 57,1%
BUY/SELL      : 598/680
```

**Rincian bulanan (Run C):**

| Bulan | Entry | tr/hr-aktif | W/BE/L | WR% | PF | Net $ | Ekuitas $ |
|---|---|---|---|---|---|---|---|
| 2025-09 | 62 | 2,82 | 30/0/32 | 48,4 | 0,67 | −1.111 | 8.889 |
| 2025-10 | 109 | 4,74 | 56/0/53 | 51,4 | 0,73 | −1.526 | 7.363 |
| 2025-11 | 73 | 3,84 | 43/0/30 | 58,9 | 0,85 | −474 | 6.889 |
| 2025-12 | 88 | 4,00 | 52/0/36 | 59,1 | **1,04** | **+170** | 7.059 |
| 2026-01 | 102 | 4,86 | 61/0/41 | 59,8 | **1,05** | **+201** | 7.260 |
| 2026-02 | 117 | 6,50 | 72/0/45 | 61,5 | 0,89 | −522 | 6.738 |
| 2026-03 | 169 | 7,68 | 99/0/70 | 58,6 | 0,91 | −632 | 6.105 |
| 2026-04 | 117 | 5,57 | 68/0/49 | 58,1 | 1,01 | +71 | 6.176 |
| 2026-05 | 109 | 5,19 | 66/0/43 | 60,6 | 0,91 | −394 | 5.782 |
| 2026-06 | 115 | 5,23 | 62/0/53 | 53,9 | 0,85 | −823 | 4.958 |
| 2026-07 | 103 | 4,48 | 59/0/44 | 57,3 | 0,92 | −358 | 4.601 |
| 2026-08 | 108 | 5,14 | 60/0/48 | 55,6 | 0,85 | −780 | 3.821 |
| 2026-09 | 6 | 6,00 | 2/0/4 | 33,3 | 0,10 | −378 | 3.443 |
| **TOTAL** | **1.278** | | **730/0/548** | **57,1** | **0,89** | **−6.557** | |

> **Frekuensi entry: rata-rata 98 entry/bulan** (62–169; puncak Maret 2026 = 169). Bulan hijau hanya 3 dari 13.

### 3.3 Run D — Kontrol kejujuran: entry ACAK dengan geometri sama

| | Sinyal ICAS | Entry acak |
|---|---|---|
| PF | **0.89** | **1.02** |
| Net (risk 1%) | −$6.557 | **+$779** |
| WR | 57,1% | 58,3% |
| DD | 65,6% | 22,7% |

**Sinyal ICAS tidak menambah apa pun di atas keberuntungan — bahkan menguranginya.** Ini kontrol paling telanjang: geometri SL/TP/trailing sama, hanya titik entry yang diganti acak.

### 3.4 Run A — Guard spread literal ($0,35)

7 trade setahun (Sep 2025: 2, Mei: 2, Jun: 1, Jul: 1, Agu: 1) · WR 42,9% · PF 0,72 · −$558,53. Makna praktis: **di luar feed Exness ber-spread sempit, bot ini diam** — guard 350 points menghalangi hampir semua bar data manapun yang spread-nya normal.

---

## 4. ANALISIS — MENGAPA RUGI (4 penyebab terukur)

1. **Melawan tren besar.** Tahun data ini emas naik $3.436 → $5.597 (+63%). Sinyal BSL-sweep menghasilkan **77% posisi SELL** (85/110 pada run 5%; 680/1.278 pada run 1%) — short berulang kali di pasar rally → 56 loss penuh menggerus modal. Sinyal ini tidak punya filter regime/tren.
2. **Payoff terbalik.** AvgWin +$69,84 vs AvgLoss −$105 (0,66R). Untuk sekadar break-even butuh WR 60,2% — WR aktual 57,1%. Kombinasi TP1 1,25R yang cuma tercapai 25,7% + TP2/TP3 nyaris mustahil (4,7%/1,0%) membuat "win" didominasi scratch trailing kecil.
3. **Struktur 4-tier ilusi.** Dari 1.278 trade: TP3 tersentuh 1,0%. Sistem berjalan sebagai "SL $15 vs TP1 $18,75 sebagian lot + sisa trailing" — jauh dari desain 4-tier.
4. **Biaya spread struktural.** Spread median $0,67 = 4,5% dari SL $15 per sisi — dikali 98 entry/bulan = ±$660/bulan drag permanen sebelum bicara edge.

---

## 5. KESIMPULAN & REKOMENDASI

**Jawaban langsung atas permintaan Anda (WR, PnL, entry/bulan, PF):**

| Metrik | Risk 5% (plan) | Risk 1% (referensi) |
|---|---|---|
| Win Rate | 49,1% | 57,1% |
| PnL | **−$10.001 (bangkrut bulan ke-2)** | **−$6.557 (−65,6%)** |
| Entry/bulan | 55 (2 bulan) | **98** (62–169) |
| Profit Factor | **0.64** | **0.89** |

**Rekomendasi:**
1. **JANGAN jalankan akun real** dengan parameter ini — setahun data sendiri mengatakan bangkrut di bulan ke-2 pada risiko 5%.
2. Temuan ini meng-konfirmasi laporan strategi sebelumnya (PF 1.02 di feed Exness 3,4 bulan) dan memperkuatnya ke **setahun penuh + kontrol acak**. Masalahnya di **sinyal** (tidak ada edge, melawan tren), bukan di parameter.
3. Langkah berikutnya yang masuk akal (sesuai Fase 1 laporan strategi): filter regime/tren HTF (contoh paling sederhana: larang SELL saat harga di atas MA harian 200 dan sebaliknya) → uji ulang di dataset 10 tahun yang sama → hanya lanjut kalau PF > kontrol acak dengan margin jelas.
4. Turunkan risiko riset ke 0,5–1% bila tetap ingin berjalan di demo sebagai observasi.

---

## 6. REPRODUKSI

```bash
cd jurnalicas/model_icas_bot_FIX
python research/backtest_m1_period.py --start 2025-09-01 --end "2026-09-01 23:59:59"
# Artefak: reports/backtest_m1_20250901_20260901.txt
# Runner ini parametrik — ganti --start/--end/--risk/--guard utk periode lain.
```

**Batasan:** M1 bukan tick (residual ambiguitas intrabar kecil) · slippage & komisi tidak dimodelkan (realita lebih buruk) · hasil M1-bid/ask feed ini adalah estimasi paling jujur yang tersedia, bukan jaminan.

---

**Disusun oleh:** agent QA/quant pada Arena.ai Agent Mode
**Pesan kunci:** *Engine dan infrastruktur Anda sehat dan teruji — angka setahun ini adalah kabar buruk untuk parameter/sinyal saat ini, tapi justru itu gunanya backtest: menemukan ini di data, bukan di akun.*
