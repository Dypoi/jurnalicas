# 📊 LAPORAN STRATEGI JURNALICAS — STATUS SAAT INI & RE-VALIDASI KRITIS

**Repo:** `Dypoi/jurnalicas` → `jurnalicas/model_icas_bot_FIX`
**Branch:** `arena/01a080b1-jurnalicas` · **Tanggal:** 8 September 2026
**Pertanyaan yang dijawab:** *bagaimana strategi plan jurnalicas saat ini?*
**Metode:** pembacaan seluruh artefak riset ter-commit (laporan audit 1–2, README, `reports/*`) **+ menjalankan ulang validator, forward-test, dan grid-search pada kondisi kode & data hari ini** — bukan sekadar mengutip klaim lama.

---

## 1. RINGKASAN EKSEKUTIF

| Aspek | Status | Catatan |
|---|---|---|
| **Identitas strategi** | Model ICAS v2 "SWING-150 C" — XAUUSD M5, ICT Liquidity Sweep + CHoCH/FVG, 4-tier TP 30/25/25/20, trailing 100p/30p, Early BE+ OFF, 24 jam, risiko tetap $500/trade (5% × $10.000) | Terpasang di `config.py` sejak 25 Agu 2026 |
| **Infrastruktur eksekusi** | ✅ **SEHAT** | 3 audit forensik (37 bug diperbaiki), QA `run_qa.py` 8 PASS/0 FAIL, 36 assertion fault-injection koneksi |
| **Bukti edge strategi** | 🔴 **TIDAK LAGI DIDUKUNG** | Klaim PF 2.08 lahir dari mesin sinyal yang masih **repaint**; setelah fix anti-repaint (F-18, 02 Sep) konfigurasi yang sama = **PF 1.02 (breakeven)** dan **tidak pernah direvalidasi** — sampai hari ini |
| **Grid-search ulang (168 kombo)** | 🔴 Tidak ada zona robust | Kandidat terbaik full-window **PF 1.06**; zona "SL 150–200 PF 2+" tahun lama **hilang** |
| **Dataset independen (bid/ask 6 bulan)** | 🔴 Negatif | Geometri sama: PF 0.93 @risk 1%, **bangkrut @risk 5%**; edge vs entry acak hanya +0,04 PF |
| **Live demo (jurnal 26 Agu–2 Sep)** | 🔴 PF 0.78, −$1.306,66 | 21 trade (tercemar bug lama; kini diperbaiki), saldo $10.075 → $8.661 (−14%) |

> **Verdict singkat:** mesinnya sehat, ** strateginya belum terbukti menguntungkan**. Rencana "SWING-150 C" saat ini berdiri di atas bukti yang sudah kedaluwarsa. Rekomendasi tegas: **tetap di demo, turunkan risiko riset, jalankan ulang kalibrasi di mesin yang sudah bersih (atau redesain sinyal) sebelum mempertaruhkan uang nyata.** Rincian rencana bertahap di §9.

---

## 2. STRATEGI SAAT INI — APA YANG BENAR-BENAR BERJALAN

### 2.1 Logika sinyal (mesin M5, bar tertutup, anti-repaint)
1. **Level likuiditas**: Asian range 03:00–06:59 & London range 08:00–11:59 (waktu server) — sejak F-18 bersifat *point-in-time* (bar hanya melihat sesi yang SUDAH selesai; sebelum selesai memakai range hari sebelumnya).
2. **Judas Sweep**: bar-1/bar-2 sebelumnya menyapu SSL (low Asia/London) → kandidat BUY; menyapu BSL (high) → kandidat SELL.
3. **Displacement CHoCH/FVG**: candle saat ini bullish & menembus swing high 5-bar **atau** membentuk bullish FVG (gap $0.30) → sinyal BUY (cermin untuk SELL).
4. **Filter**: spread ≤ 350 points ($0.35 pada simbol 3-digit), killzone **NONAKTIF** (trading 24 jam), maks 999 trade/hari, circuit breaker 999 (praktis nonaktif).
5. **Eksekusi**: 1 sinyal 1 posisi (mutex + magic number), entry di harga pasar saat bar sinyal selesai.

### 2.2 Parameter aktif (`config.py`)

| Parameter | Nilai | Makna |
|---|---|---|
| STOP_LOSS_PIPS | **150** ($15) | 1R = $15/oz |
| TP1 / TP2 / TP3 | **187.5 / 375 / 562.5** ($18.75/$37.50/$56.25) | 1.25R / 2.5R / 3.75R |
| Lot split TP1/TP2/TP3/Runner | **30% / 25% / 25% / 20%** | partial close bertingkat |
| Early BE+ | **OFF** (9999) | dimatikan kalibrasi 25 Agu ("BE dini membunuh expectancy") |
| Trailing runner | step **100p**, lock **30p** | tiap +$10 gerak, kunci +$3 |
| Risiko/trade | **$500 tetap** (5% × $10.000, non-compounding) | sadar spread+slippage ($0.10) |
| Maks. spread | 350 pts ($0.35) | guard entry |
| Sesi | 24 jam | killzone OFF sesuai permintaan |
| Posisi maks | 1 | zero martingale/grid/layering |

### 2.3 Karakter strategi
Bukan lagi scalper: ~4–5 trade/hari (dari ~11), durasi hold median 1,5 jam (live) hingga >1 hari, mayoritas profit dirancang datang dari runner trailing. Profil psikologis berat: **hanya ~37% trade yang tidak rugi** — 6 dari 10 trade ditutup rugi penuh −$500.

### 2.4 Infrastruktur eksekusi & observasi (yang sehat)
Daemon tahan gangguan (guard feed, mutex bukti-broker, tombstone/revive, PnL backfill), jurnal JSONL lengkap + fsync, state persist atomik, dashboard berlabel sumber, QA 8/8. *Ini modal yang tetap berharga apa pun nasib parameternya.*

---

## 3. 🔴 TEMUAN MATERIAL #1 — BUKTI KALIBRASI SUDAH KEDALUWARSA

### 3.1 Kronologi (dari artefak repo)

| Tanggal | Kejadian | Konsekuensi |
|---|---|---|
| 25 Agu | Grid-search walk-forward memilih **F2 "SWING-150 C"** → diterapkan ke `config.py` | Klaim: 326 tr, **PF 2.08**, +$38.067, 4/4 bulan hijau, OOS 2.25 |
| 25 Agu | Forward-test OOS config baru: 139 tr, **PF 2.25** | Diklaim sebagai konfirmasi |
| 02 Sep | **F-18: fix anti-repaint `sessions.py`** (level sesi bocor masa depan) | Mesin sinyal **berubah total** |
| 02 Sep | Audit M1 bid/ask (Jan–Jun): geometri sama → PF 0.93 | Sinyal bahaya, tapi **tidak ditindaklanjuti** |
| 02–08 Sep | **Tidak ada re-validasi feed Exness, tidak ada re-kalibrasi** | Config lama tetap terpasang |
| **8 Sep (hari ini)** | Re-validasi independen (laporan ini) | **PF 1.02** — lihat §3.2 |

### 3.2 Reproduksi — data sama, dua mesin sinyal

Semua run: feed M1 broker Anda (`xauusd_m1_broker.csv`, 100.000 bar, 14 Mei–25 Agu), M5 di-resample dari M1 yang sama (satu feed), sequencing M1, spread riil per bar, risiko $500.

| Mesin sinyal | Trades | W/L | PF | Net | DD | Bulan hijau |
|---|---|---|---|---|---|---|
| **Versi lama (repaint, rekonstruksi kondisi saat kalibrasi 25 Agu)** | 331 | 124/207 | **1.97** | +$36.874 | 13,2% | **4/4** |
| **Versi sekarang (anti-repaint F-18 — kode di repo hari ini)** | 404 | 114/290 | **1.02** | +$1.048 | **69,2%** | **2/4** |
| Klaim yang tercatat di README/audit-1 §9 | 326 | 122/204 | 2.08 | +$38.067 | 12,8% | 4/4 |

Rekonstruksi versi-lama (PF 1.97) cocok dengan klaim (2.08; selisih kecil dari detail fallback rekonstruksi). **Kesimpulan: hampir seluruh "edge" PF 2.08 adalah artefak level sesi yang membocorkan masa depan.** Setelah bocor itu ditutup, ekspektasi praktis nol:

| Window | Mesin sekarang (F-18) |
|---|---|
| TRAIN 14 Mei–15 Jul | 245 tr · PF **1.00** · +$137 |
| TEST/OOS 15 Jul–25 Agu | 158 tr · PF **1.03** · +$824 |

> Analogi awam: kalibrasi lama seperti ujian menghafal soal yang **kunci jawabannya menempel di dinding** (level sesi "sudah tahu" high/low restol hari itu). Saat lembar jawaban itu dicabut (F-18), nilai ujiannya kembali ke rata-rata kelas.

---

## 4. 🔴 TEMUAN MATERIAL #2 — GRID-SEARCH ULANG: TIDAK ADA LAGI ZONA ROBUST

Grid yang sama persis dengan kalibrasi 25 Agu (168 kombo: SL 20–100 × struktur TP A–D × BE 10–9999), kini dijalankan di atas mesin bersih (artefak: `reports/grid_search_post_f18_20260908.txt`):

- **Baseline (config Anda sekarang)**: TRAIN PF 1.00 / TEST PF 1.03.
- **Top-15 TRAIN tertinggi: PF 1.03** (SL100 B/C/D, BE OFF) — datar.
- **Survivor OOS terbaik**: SL80 B → TEST PF 1.20, tapi **full-window hanya 1.06**; SL80 C → 1.08/1.03.
- **Tidak satu pun kombo mencapai PF ≥ 1.2 full-window.** Zona "SL 150–200, PF 2+" yang dulu sekarang menghasilkan PF ≈ 1.0 (para finalis lama bahkan tidak masuk top-15 baru).

**Artinya: masalahnya bukan salah pilih parameter — peta profitable-nya sendiri yang hilang setelah kebocoran ditutup.** Re-kalibrasi parameter di sinyal yang sama kemungkinan besar hanya menghasilkan noise-fitting (PF 1.0–1.1).

---

## 5. PETA BUKTI LENGKAP — SEMUA SUMBER DATA YANG ADA

| # | Bukti | Data / periode | Mesin | Hasil | Bobot |
|---|---|---|---|---|---|
| 1 | Klaim kalibrasi 25 Agu (audit-1 §9) | Exness M1, 14 Mei–25 Agu | **repaint** | 326 tr · PF 2.08 · 4/4 hijau | ❌ usang (mesin sudah diganti) |
| 2 | Forward OOS 25 Agu | sama (15 Jul–25 Agu) | **repaint** | 139 tr · PF 2.25 | ❌ usang |
| 3 | **Reproduksi hari ini** | sama | anti-repaint | **404 tr · PF 1.02 · DD 69% · 2/4** | ✅ terkuat utk feed ini |
| 4 | Grid ulang 168 kombo | sama | anti-repaint | tak ada zona > 1.06 full | ✅ |
| 5 | Audit M1 bid/ask (02 Sep, `m1_audit_compare_jan_jun_2026.txt`) | XAUUSD_M1 bid+ask, Jan–Jun 2026, spread riil median $0.69 | anti-repaint | 729 tr · **PF 0.93** @1%; **bangkrut @5%** | ✅ independen |
| 6 | Baseline entry ACAK (geometri sama) | sama | anti-repaint | PF 0.90 → **edge sinyal hanya +0.04 PF** | ✅ paling telanjang |
| 7 | Live demo jurnal | Exness demo, 26 Agu–2 Sep | — | 21 tr · PF 0.78 · −$1.306,66 | ⚠️ kecil + tercemar bug lama |
| 8 | Perbandingan killzone (repo M5, engine lama) | Jan–Jun 2026 | legacy optimis | KZ on PF 1.73 vs off 1.16 | ⚠️ engine tak dipercaya; di bukti #5 killzone justru memperburuk (0.67 vs 0.93) |

**Temuan pendukung dari bukti #5 yang wajib dicerna:**
- **Struktur 4-tier efektif tidak berjalan**: TP2 hanya tersentuh 5,2% trade, TP3 1,2% — sistem praktis menjadi "1 tier + trailing"; 84% "win" hanyalah scratch trailing ~$45.
- **Guard spread tidak portabel**: median spread feed bid/ask $0.69 > guard $0.35 → hanya 0,29% bar lolos (bot praktis idle di broker lain). Strategi ini **sandera pada spread Exness yang sempit**.
- **Slippage live nyata $1.27/entry** (pengukuran F-17 dari jurnal) vs asumsi riset $0.10.

---

## 6. APA YANG MASIH BERDIRI vs APA YANG JATUH

**Berdiri (pertahankan):**
1. Infrastruktur eksekusi tahan-gangguan + jurnal observasi + state persist + dashboard (hasil 3 audit).
2. Disiplin metodologi riset: walk-forward, gerbang OOS, Monte Carlo, sequencing M1, kontrol entry-acak — *justru disiplin inilah yang menyingkap masalahnya*.
3. Dataset: 10 tahun M1 bid/ask (2016–2026) + feed broker 3,4 bulan — modal riset berharga yang **belum dimanfaatkan penuh** (validasi 10-tahun untuk config saat ini belum pernah dijalankan).
4. Hygiene biaya: spread riil per bar, slippage, sizing sadar biaya.

**Jatuh (revisi/desain ulang):**
1. **Edge sinyal ICT sweep+CHoCH/FVG** ≈ nol pada data bersih (PF 0.93 vs acak 0.90 di feed independen; 1.02 di feed sendiri).
2. **Preset "SWING-150 C"** — breakeven pada mesin bersih.
3. **Klaim performa PF 2.08 / OOS 2.25** di README & komentar config — kedaluwarsa dan berpotensi menyesatkan.
4. **Struktur 4-tier** — TP2/TP3 nyaris tak pernah tereksekusi (pertimbangkan 2-tier atau runner murni).
5. **Risiko 5%/trade** — dengan ekspektasi ~0, ini spekulasi ruin: DD 69% (feed sendiri), bangkrut (feed independen).

---

## 7. PROFIL RISIKO JIKA STRATEGI DIJALANKAN APA ADANYA

| Risiko | Ukuran |
|---|---|
| Drawdown backtest (feed sendiri, $500/trade) | **69%** |
| Skenario feed independen @5% | **bangkrut** (equity habis) |
| Loss beruntun backtest terpanjang | 3–5 trade berturut → −$1.500…−$2.500 dalam sekejap |
| Live demo aktual (7 hari) | −14% saldo |
| Ketahanan psikologis | 63% trade rugi penuh; butuh 40+ trade sebelum PF terbaca signifikan |
| Konsentrasi rezim | Seluruh bukti positif berasal dari 3,4 bulan emas 2026 (satu rezim) |
| Operasional | Laptop on/off tanpa VPS; SL broker tetap aktif saat offline, tapi trailing mati |

---

## 8. HYGIENE TOOLING & DOKUMEN (diperbaiki hari ini, kecil tapi penting)

1. **`research/validate_granular.py`** — jebakan terkonfirmasi: default `--m5` = M5 repo (feed lain, 2-digit) dipadukan `--fine` M1 broker (3-digit) menghasilkan **PF 0.52 palsu tanpa peringatan** (bias spread 10× + campur feed). Kini ada **guard keras** untuk mismatch price-point dan rentang waktu yang tidak bertumpangan.
2. **`research/grid_search_m1.py`** — label baseline tercetak hardcode "SL 20p, TP 20/40/60, BE 10p" padahal menjalankan config apa pun; kini dinamis.
3. **README.md** — masih memajang "Early BE+ @ +10 pips" di bagian fitur (config: OFF) dan angka kalibrasi 2.08; butuh rewrite menyeluruh (dicatat, belum diubah di giliran ini).

---

## 9. RENCANA TINDAKAN (strategy plan ke depan)

### Fase 0 — Segera (hari ini)
- [ ] **Jangan naik ke akun real** dengan parameter sekarang. Demo boleh dibiarkan berjalan murni sebagai observasi (ekspektasi ≈ 0, bukan positif).
- [ ] Sadari bahwa angka "PF 2.08" di README/komentar config **tidak berlaku lagi**.
- [ ] (Opsional, disarankan) Turunkan `RISK_PER_TRADE_PCT` ke 0.5–1% selama masa riset — jika edge kembali positif nanti, naikkan bertahap.

### Fase 1 — Riset jujur (1–3 hari kerja, semua tool sudah ada di repo)
1. **Validasi 10 tahun** (`XAUUSD_M1/` 2016–2026, bid/ask): jalankan geometri & variasi pada full history (perpanjang `research/backtest_m1_audit.py` / `run_m1_compare_audit.py` melewati Jan–Jun). *Jika PF < 1 konsisten lintas dekade → sinyal ini tidak punya edge — stop optimasi parameter, lanjut ke poin 3.*
2. **Uji ulang filter** di mesin bersih: killzone (di data bersih justru merugikan — konfirmasi/cabut), batas jam, filter tren HTF, batas trade/hari & circuit breaker nyata (mis. maks 3 loss/hari).
3. **Desain ulang sinyal** bila edge memang nol: kandidat arah — sweep dengan konfirmasi momentum/strukturnya lebih ketat, timeframe berbeda (M15), atau komponen filtro regime (ADX/volatility) — selalu dengan kontrol entry-acak sebagai tolok ukur minimal.
4. **Sederhanakan struktur exit**: uji 2-tier (TP1 1–1.25R + runner) vs 4-tier — bukti MFE menunjukkan TP2/TP3 hanya menambah kompleksitas tanpa frekuensi.

### Fase 2 — Jika ada kandidat yang lolos
- Grid-search walk-forward di mesin bersih (TRAIN/OOS terpisah) → gerbang: OOS PF ≥ 1.3, semua bulan hijau, ≥ 300 trade, kontrol acak terkalahkan jelas.
- Monte Carlo intrabar + sensitivitas spread/slippage 2×.
- **Forward demo ≥ 30–50 trade** dengan kode saat ini (stop-rule PF < 1 setelah 30 trade = gugur).

### Fase 3 — Keputusan real
- Baru setelah Fase 2 hijau: mulai 0.5–1% risiko, naik bertahap. VPS/heartbeat eksternal sebelum 24/7.

---

## 10. CARA MEREPRODUKSI SEMUA ANGKA LAPORAN INI

```bash
cd jurnalicas/model_icas_bot_FIX

# 1) Re-validasi config saat ini di feed broker (mesin anti-repaint, satu feed):
python research/validate_granular.py \
  --fine data/historical/xauusd_m1_broker.csv \
  --m5  data/historical/xauusd_m5_from_m1.csv \
  --start 2026-05-14 --end "2026-08-25 14:30:00"
#    -> 404 tr | PF 1.02 | Net +$1.048 | DD 69.2% | 2/4 bulan hijau

# 2) Grid-search ulang 168 kombo di mesin bersih:
python research/grid_search_m1.py        # artefak: reports/grid_search_post_f18_20260908.txt

# 3) Bukti independen bid/ask 6 bulan:
python research/run_m1_compare_audit.py  # artefak: reports/m1_audit_compare_jan_jun_2026.txt

# 4) Observasi live:
python research/journal_report.py        # PF 0.78 | 21 tr | −$1.306,66
```

---

## 11. BATASAN ANALISIS

1. Sequencing memakai **M1, bukan tick** — sisa ambiguitas intrabar ~1/5 dari M5 (sudah jauh lebih definitif, tapi bukan final).
2. Rekonstruksi mesin repaint adalah pendekatan (fallback NaN bisa beda detail) — karena itu PF 1.97 vs klaim 2.08; arah dan magnitudo temuan tidak berubah.
3. Live n=21 terlalu kecil untuk inferensi statistik — tetap dipakai hanya sebagai konfirmasi arah.
4. Sequencer memodelkan biaya via spread per bar + slippage tetap; komisi/swap belum dimasukkan (di live sudah tercatat di `realized_total`).

---

**Disusun oleh:** agent QA/quant pada Arena.ai Agent Mode
**Inti pesan:** *infrastruktur Anda A-grade; edge strateginya belum terbukti pada data yang jujur. Kabar baik: semua tool untuk membuktikannya — atau membantahnya — sudah ada di repo Anda sendiri, dan laporan ini menyertakan rencana bertahap untuk sampai ke keputusan go/no-go.*
