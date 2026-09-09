# LAPORAN LENGKAP — STRATEGI PLAN G4 (icas-v3-g4)

**Model Icas · XAUUSD (Gold) · Exness · Eksekusi M5 · Risk 1%**
Tanggal: 09 Sep 2026 · Engine: `icas-v3-g4 (MTF H1/PD24j/M15/M5 + trail 50/30)`
Kode: `src/strategy/g4_strategy.py` (live) · `research/backtest_m1_audit.py` (riset)

---

## 1. Ringkasan eksekutif

G4 adalah strategi **scalping liquidity-sweep multi-timeframe** emas: harga
"mencuri" likuiditas di bawah/atas high-low kemarin (zona stop-loss para
trader), lalu berbalik dengan momentum — bot masuk pada konfirmasi
perubahan struktur di timeframe kecil. Satu posisi pada satu waktu, exit
bertingkat + trailing cepat.

| Metrik (backtest setahun, risk 1% modal $10k) | Nilai |
|---|---|
| Trade | **1.338** (~103/bln, 3–5/hari aktif) |
| Win rate | **73,0%** |
| Profit factor | **1,12** |
| Net profit | **+$4.493/tahun** (+44,9% modal) |
| Max drawdown | **19,5%** |
| Signifikansi | Monte-Carlo 32-seed: kontrol acak μ −$508 → **p = 0,000** |
| Paritas sinyal live↔riset | **IDENTIK bar-per-bar** (71.128 bar, 3.694 sinyal geometri, 0 mismatch) |

**Batas validitas (wajib diingat):** edge terukur pada rezim 2023–2026.
Backtest 2021–2022 **merah −$537** (era side-way/rate-hike). Mulai dari DEMO.

---

## 2. Mengapa ICAS lama diganti G4

Diagnosis forensik log live 21 tiket + backtest (`LAPORAN_TUNING_SCALPING.md`):

| | ICAS lama (choch+sesi) | G4 |
|---|---|---|
| Akar sinyal | Break swing M5 + sesi Asia/London | Kaskade 4 timeframe H1→M5 |
| PF setahun (2025-26) | 0,92 — **kalah dari acak (1,02)** | **1,12** (p=0,000) |
| Pemicu utama rugi | Sinyal masuk melawan bias besar | Bias H1 jadi gerbang pertama |
| Masalah terukur | 8W/11L live; loser MFE ≤ 2 pips (entry melawan arah) | Winner ≥ 189 pips; frekuensi tetap tinggi |

Kesimpulan audit: TP/SL/trailing lama **bukan** biang keroknya — **sinyalnya**.
G4 mengganti sumber sinyal, mempertahankan geometri exit yang sudah terbukti.

---

## 3. Kaskade sinyal — 4 lapis (semua kausal/anti-repaint)

Sinyal dihitung **tepat setelah candle M5 tertutup**. Semua level hanya dari
data yang sudah final (tidak ada repaint):

```
L1  H1   →  arah besar     (bias)
L2  M5   →  likuiditas     (sweep PDH/PDL 24 jam)
L3  M15  →  struktur      (CHoCH)
L4  M5   →  pemicu         (displacement + FVG)
```

### L1 — Bias H1 (gerbang arah)
- EMA200 atas **close H1**, dihitung pada grid per-jam (slot weekend kosong).
- Bar H1 yang boleh dipakai: label ≤ t−1 jam (bar yang sudah TUTUP saat
  candle M5 sinyal dievaluasi).
- **BUY hanya bila close M5 > EMA200-H1. SELL hanya bila < EMA200-H1.**
- Minimal 260 bar H1 histori (warm-up; daemon live mengambil 5.000 bar).

### L2 — Sweep likuiditas PDH/PDL (kenapa harga mau berbalik)
- **PDH/PDL** = high/low **hari bursa kemarin** (hari UTC; Sabtu/Minggu
  otomatis ter-pad ke Jumat).
- Hari yang sah: berlabel ≤ t−24 jam (kemarin sudah SELESAI — kausal).
- **Sweep** = dalam **288 bar M5 terakhir (24 jam)** sebelum candle sinyal
  (candle sinyal sendiri TIDAK dihitung):
  - `sweep_buy`: low salah satu candle ≤ **PDL** (harga mengambil stop di bawah kemarin → likuiditas buat naik)
  - `sweep_sell`: high salah satu candle ≥ **PDH** (stop di atas kemarin diambil → bahan turun)
- Ini inti strategi: **entry setelah stop-hunt, searah dengan para "pemain besar"**.

### L3 — CHoCH M15 (konfirmasi struktur berubah)
- Swing high/low **5 bar M15**: window posisional `[k−6 .. k−2]`, dengan k =
  bar M15 terakhir berlabel ≤ t−15 menit (bar M15 yang sudah tertutup).
- `choch_bull`: **close M5 menembus ke atas** swing-high 5-bar M15 itu.
- `choch_bear`: close menembus ke bawah swing-low 5-bar M15.

### L4 — Displacement M5 (pemicu eksekusi)
Candle M5 sinyal harus candle **momentum**:
- Bull: `close > open` DAN (close > swing-high 5-bar M5 `[i−6..i−2]` **ATAU**
  meninggalkan FVG bullish: `low > high[i−2] + $0,30`)
- Bear: `close < open` DAN (close < swing-low 5-bar M5 **ATAU** FVG bearish:
  `high < low[i−2] − $0,30`)

### Tabel keputusan

| L1 bias | L2 sweep | L3 CHoCH | L4 trigger | → |
|---|---|---|---|---|
| close > EMA200-H1 | low 24j ≤ PDL | close > swing M15 | bull disp/FVG | **BUY** |
| close < EMA200-H1 | high 24j ≥ PDH | close < swing M15 | bear disp/FVG | **SELL** |
| tidak lolos salah satu lapis saja pun | — | — | — | **NO TRADE** |

BUY dan SELL adalah cermin sempurna (mirror) — tidak ada bias arah hardcoded.

---

## 4. Kapan TIDAK entry (guard & filter)

| Guard | Nilai | Efek |
|---|---|---|
| Spread tick | **> $1,20** → skip | Kalibrasi backtest; blokir jam rollover/berita |
| Mutex posisi | 1 posisi aktif saja | Sinyal berikutnya menunggu posisi tertutup |
| Bar berjalan | dibuang | Hanya candle M5 yang SUDAH close yang dievaluasi |
| Warm-up data | < 350 M5 / 20 M15 / 260 H1 | Daemon baru start = skip sampai histori cukup |
| Maks trade/hari | 999 (praktis tak terbatas) | Frekuensi scalping dipertahankan |
| Killzone/sesi | **TIDAK ADA** — 24 jam | G4 tidak dibatasi sesi (beda vs ICAS lama) |

Catatan penting: sinyal G4 **berkelompok** (median jarak antar sinyal hanya
10 menit) — mutex membuat 3.562 bar sinyal setahun menjadi 1.338 trade
nyata; sinyal lanjutan di kluster yang sama otomatis terlewat (by design).

### Guard $1,20 vs Exness nyata (data setahun)

Guard spread **bukan penilaian keamanan broker** — ia filter kualitas
eksekusi, dan nilainya dikalibrasi dari feed Exness itu sendiri (355.640
menit M1 bid/ask XAUUSD, 2025-09..2026-09):

| Ukuran | Nilai |
|---|---|
| Spread median (semua menit bursa) | **$0,67** |
| Spread median jam London/NY (09:00–22:00 server) | **$0,60** |
| Menit yang melebihi $1,20 (diblokir guard) | **3,14%** |
| Konsentrasi blokir | rollover **00:00–02:00 server**: 25% / 16% / 10% menit |
| Jam puncak sinyal G4 (03–05, 07–08, 16 server) | median $0,71 · blokir hanya 2,6% |

Artinya: pada kondisi Exness normal guard praktis tak pernah aktif — ia
hanya menahan entry tepat di jam pelebaran ekstrem (rollover tengah malam,
news besar), saat entry memang paling berisiko. Rujukan pihak ketiga
(invesnesia.com, Mar 2026) mencatat spread rata-rata XAUUSD akun Standard
Exness ± 11 pip (≈$0,11 jarak harga, tanpa komisi) — jauh di bawah guard;
untuk gold, akun Raw Spread Exness all-in ±$8/lot (spread kecil + komisi
$7 round-turn) vs Standard ±$11/lot spread-only.

---

## 5. Eksekusi entry

1. Candle M5 tutup → evaluasi kaskade (± 1 detik).
2. Lolos semua lapis + guard → **market order** segera (~open candle berikutnya).
3. Harga fill acuan:
   - **BUY** → isi di **ASK** ≈ close + spread
   - **SELL** → isi di **BID** ≈ close
4. **SL/TP dijangkar ke harga fill** (bukan ke close candle):
   - SL = fill ∓ **$15,00** (150 pips)
   - TP1 = fill ± **$18,75** (187,5 pips = 1,25×SL)
   - TP2 = fill ± **$37,50** (375 pips = 2,5×SL)
   - TP3 = fill ± **$56,25** (562,5 pips = 3,75×SL)
5. SL langsung aktif di broker sejak entry — tidak ada posisi "telanjang".

### Ukuran lot (formula S-04)
```
risk_dollar = balance × 1%                 (non-compounding: $10.000 × 1% = $100)
sl_eff      = $15 + spread + slippage($0.10)
lot         = risk_dollar / (sl_eff × 100)
```
Contoh: spread $0,66 → sl_eff $15,76 → lot = 100/1.576 = **0,06 → 0,06** (dibulatkan 2 desimal, min 0,01).

### Contoh walkthrough BUY (angka nyata-format)

- EMA200-H1 = 4.380,50; close M5 = **4.412,00** → bias bull ✅
- Kemarin PDH/PDL = 4.405/4.370; 4 jam lalu low menyentuh **4.369,80** ≤ PDL → sweep ✅
- Swing-high 5-bar M15 = 4.410,00; close 4.412 menembusnya → CHoCH ✅
- Candle sinyal: open 4.406,2 → close 4.412,0 (bullish), swing-high M5
  [i−6..i−2] = 4.409,50 → tertembus, plus low 4.407 > high[i−2] 4.404,30 (FVG) ✅
- **BUY @ ask 4.412,66** (spread $0,66) · SL **4.397,66** · TP1 **4.431,41** ·
  TP2 **4.450,16** · TP3 **4.468,91** · lot **0,06** (risk $100)

Contoh SELL nyata dari data: 2026-09-01 01:25 UTC → SELL @ 4.439,74,
SL 4.454,74, lot 0,07 (spread $0,20).

---

## 6. Exit management — TP bertingkat + trailing 50/30 (monoton)

Distribusi lot: **TP1 30% · TP2 25% · TP3 25% · runner 20%**.

| Peristiwa (favorable excursion dari entry) | Aksi |
|---|---|
| MFE ≥ **+50 pips** ($5) | SL dinaikkan ke **+30 pips** (kunci profit pertama) |
| MFE ≥ +100 pips | SL → +80 pips |
| MFE ≥ +150 pips | SL → +130 pips |
| Harga sentuh **TP1 +187,5p** | tutup **30%** lot; SL minimal BE+ (tak pernah turun) |
| TP2 +375p | tutup **25%** lot |
| TP3 +562,5p | tutup **25%** lot; SL minimal level TP1 |
| Runner 20% sisanya | trailing terus: setiap +50p MFE → SL dikunci 20p di belakang milestone |
| Harga kembali ke SL | posisi tertutup di broker (guaranteed) |

Rumus trailing: `k = floor(MFE / 50)` → `SL = entry + (k−1)×50p + 30p`.
SL **tidak pernah mundur** (monotonic — replika eksak engine riset; guard
`_sl_improves` di daemon, ditambahkan 09 Sep 2026 setelah ditemukan
divergensi exit pasca-TP1/TP3 yang bisa menurunkan SL dari +130p ke +5,6p).

Mengapa 50/30: grid riset menunjukkan frekuensi G4 + trailing cepat =
kombinasi terbaik (WR 73% terjaga karena lock cepat memindahkan loss
menjadi scratch/kecil-untung; profit hidup di runner ekor panjang).

### 6a. Anatomi exit — kenapa TP bertingkat jarang tersentuh (dan kenapa itu by design)

Data aktual G4 setahun: **trailing aktif di 73,0% trade**, sedangkan
TP1/TP2/TP3 hanya **6,1% / 0,4% / 0,1%**; median perjalanan menguntungkan
(MFE) trade = **$7,05 (~70 pips)**. Artinya di G4, exit engine-nya adalah
**trailing**, bukan tangga TP — tangga TP hanyalah jaring pengaman untuk
hari-hari outlier. Tiga penyebab struktural:

1. **Matematika TP3**: 562,5 pips = perjalanan $56 tanpa retracement —
   **5–8× lipat** perjalanan median trade. Setelah sweep-likuiditas,
   gerakan pembalikan tipikal emas selesai dalam 30–90 menit (50–150 pips).
   Hari trend monster yang menempuh 562,5 pips hanya ~0,1–2% trade.
2. **Trailing 50/30 memotong lebih dulu**: pada MFE +100p SL sudah di +80,
   +150p → SL +130 — pullback normal (yang hampir selalu datang) mengeluarkan
   posisi **sebelum** TP1 187,5 tercapai. Itulah kenapa WR tetap 73% meski
   TP1 cuma 6,1% — profit diambil trailing, bukan TP.
3. Setelah TP1, engine menaikkan SL ke BE — runner butuh melanjutkan $37,5
   lagi TANPA balik ke entry untuk TP2; probabilitas rendah di pasar noisy.

**"Kalau TP-nya didekatkan biar sering tersentuh?" — SUDAH DIUJI, dan hasilnya merusak:**

| Varian (setahun, risk 1%) | TP1/TP2/TP3 tersentuh | WR | PF | Net | Max DD |
|---|---|---|---|---|---|
| TP 50/100 (G3, scalp) | 72,4% / 39,4% / 0,1% | 72,4% | **0,91** | **−$3.763** | **51,7%** |
| TP 100/200 (G1) | 60,3% / 27,3% / 0,1% | 60,3% | 1,05 | +$2.044 | 23,9% |
| TP 125/250 (G2) | 44,2% / 16,0% / 0,1% | 61,1% | 1,07 | +$2.686 | 19,7% |
| **G4: TP plan + trail 50/30** | 6,1% / 0,4% / 0,1% | **73,0%** | 1,12 | **+$4.493** | 19,5% |
| W24h: TP plan + trail **100**/30 | **28,5% / 6,9% / 2,1%** | 61,2% | **1,15** | **+$5.257** | **12,4%** |

Semakin dekat TP, semakin sering tersentuh — dan semakin kecil profit:
G3 (TP paling dekat, tersentuh paling sering) justru **BUST −$3.763, DD 52%**.
Kesimpulan riset: edge G4 hidup di **ekor runner** (menang besar sesekali)
yang membayar semua loss kecil — memotong ekor = memotong sumber profit.

**Dua varian teruji yang membuat tangga TP "hidup" lagi:** pelankan trailing
ke 100/30 (preset W24h): TP1 28,5% / TP2 6,9% / TP3 2,1%, PF 1,15, net
+$5.257, DD hanya 12,4% — lebih besar profitnya, lebih kecil DD-nya, TAPI
frekuensi turun 103 → 66 entry/bln dan WR turun 73% → 61%. Cukup ubah satu
baris: `TRAILING_STEP_PIPS: 100.0`. Pilihan ini murni selera: frekuensi
scalping tinggi + WR tinggi (G4) vs tangga TP bermakna + DD ringan (W24h).
(Ref: `reports/tuning_scalpmtf_20250901_20260901_risk100_execm5.txt`.)

---

## 7. Profil sinyal aktual setahun (data, bukan asumsi)

Sumber: scan engine 71.128 bar M5 (artefak
`reports/g4_signal_profile_20250901_20260901.txt`):

- **BUY 67,2% / SELL 32,8%** — tidak dibatasi aturan; cerminan tren naik
  emas 2025–26 (rezim bullish). Di rezim bearish proporsi SELL akan naik.
- **Jam tersibuk (waktu server EET/EEST = WIB −4/−5):**
  puncak **03:00–04:59 server** (≈ 07:00–09:59 WIB, sesi Asia-Eropa),
  sekunder **07:00–08:00** (London) dan **16:00** (NY). Sepi 23:00–00:59.
- **Senin = hari tersibuk: 1.207 sinyal (34%)** — logis: PDH/PDL Jumat +
  gap weekend = pantry likuiditas terbesar. Sabtu 0, Minggu 73 (open malam).
- 268 dari 313 hari bursa punya ≥1 sinyal; rata-rata 13,3 bar sinyal/hari
  (mutex memangkasnya menjadi ~5 entry/hari).
- Spread saat sinyal: median $0,66 · p90 $0,84 · maks $1,20 (guard).
- Bulanan stabil: 203–379 sinyal/bln, tanpa bulan nol.

---

## 8. Bukti & batas validitas

| Uji | Hasil |
|---|---|
| Backtest anti-repaint pesimis 2025-09→2026-09 | 1.338 tr · WR 73,0% · PF 1,12 · +$4.493 · DD 19,5% |
| Monte-Carlo 32-seed (sinyal acak, exit sama) | μ −$508 · G4 menang di semua seed → **p = 0,000** |
| Lintas rezim | 2023–2026: profitable; kumulatif 3 periode +$4.175 |
| Rezim buruk | **2021–2022: −$537** — side-way/rate-hike membunuh L1 bias |
| Paritas sinyal | 0 mismatch bar-per-bar (`g4_parity_check.py`) |
| Paritas exit | SL monoton = engine (guard `_sl_improves`, 09 Sep 2026) |

**Yang membunuh G4:** pasar range sempit berpekan-pekan (L1 bias bolak-balik
dicambuk), spread melebar kronis > $1,20 (broker buruk), dan slippage eksekusi
rutin > $0,50 (guard jurnal `slippage_usd` memantau ini).

---

## 9. Ringkasan operasional

- Menjalankan: `python icas_daemon.py` (lihat `TATA_CARA_G4.md` lengkap).
- Monitoring: `python run_dashboard.py` — badge STRATEGY: G4, panel kaskade
  L1–L4, badge spread USD, banner posisi (post-audit dashboard 09 Sep 2026).
- Rollback: `STRATEGY = "ICAS"` di config.py (jalur lama utuh).
- Verifikasi ulang paritas di mesin Anda: `python research/g4_parity_check.py`
  (exit code 0 = IDENTIK).

---

*Lampiran: `LAPORAN_TUNING_SCALPING.md` (grid riset S/G + Monte-Carlo) ·
`reports/g4_parity_20250901_20260901.txt` (bukti paritas sinyal) ·
`reports/g4_signal_profile_20250901_20260901.txt` (profil sinyal) ·
`reports/multiseed_mtf_scalp_20250901_20260901_risk100.txt` (signifikansi).*
