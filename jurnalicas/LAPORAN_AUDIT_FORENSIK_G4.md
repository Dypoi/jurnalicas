# LAPORAN AUDIT FORENSIK — LOGIKA KASKADE G4

**Tanggal:** 15 September 2026 · **Pemicu:** 4 kekhawatiran audit dari pemilik akun (CHOCH, sweep, sinyal stale, AND-gating)
**Metode:** pembacaan kode jalur live (`src/strategy/g4_strategy.py`) + pengukuran empiris setahun penuh data XAUUSD (2025-09-01..2026-09-01, 71.128 bar M5 tertutup, replika persis pipeline parity check) + parity check ulang end-to-end.
**Skrip:** `research/g4_funnel_audit.py` (laporan angka: `reports/g4_funnel_audit.txt`), `research/g4_parity_check.py` (laporan: `reports/g4_parity_check_c5fix.txt`).

---

## RINGKASAN VERDICT

| # | Kekhawatiran | Verdict | Bukti kunci |
|---|---|---|---|
| C1 | Definisi CHoCH terlalu sederhana | **Benar sebagai fakta, bukan bug** — 57–60% sinyal sebenarnya continuation/BOS, bukan CHoCH murni | §3 |
| C2 | Sweep hanya ekstrem 24 jam, tanpa klasifikasi | **Sebagian benar** — jauh lebih baik dari dugaan (94% wick-only, 95% reclaim), tapi lemah sebagai filter mandiri (80% waktu kedua sisi menyala; umur median 11,8 jam) | §4 |
| C3 | Sinyal terakhir stale (panel `SELL @ 09-14 20:08`) | **Tidak ada risiko eksekusi** — tidak ada jalur yang memakai sinyal lama; panel = riwayat. Fix label UI diterapkan | §5 |
| C4 | AND-gating 4 lapis → terlalu sedikit trade | **Tidak terbukti** — 3.694 sinyal geometri/thn (15,2/hari) → 1.338 trade (5,5/hari); live 6,7/hari, konsisten | §6 |
| **C5** | **(ditemukan audit ini, tidak ada di daftar)** | **PARITY GAP NYATA di L2: definisi "hari" PD levels live ≠ backtest** — sudah difix & dibuktikan 0 mismatch | §7 |

---

## 1. Cara kerja kaskade (kode sebenarnya)

Sinyal dievaluasi **segala saat bar M5 baru tertutup**, murni dari geometri harga (`g4_signal_at`, replika terbukti identik dengan engine riset):

| Lapis | Kondisi (persis kode) |
|---|---|
| L1 Bias | close M5 vs EMA200-H1 (grid per jam bursa) |
| L2 Sweep | `min(low, 288 bar terakhir sebelum i) ≤ PDL` (BUY) / `max(high) ≥ PDH` (SELL) — PDL/PDH = high/low **hari bursa terakhir** |
| L3 "CHoCH" | close M5 menembus **swing 5-bar M15** (window posisional `[k-6..k-2]`, k = bar M15 terakhir ≤ t−15 mnt) |
| L4 Trigger | candle displacement (close>open) DAN (break swing 5-bar M5 **ATAU** FVG dengan buffer $0,30) |

Sinyal = L1 **AND** L2 **AND** L3 **AND** L4 searah. Tidak ada lookahead (semua jendela eksklusif bar berjalan; diverifikasi parity check + `test_antirepaint.py`).

## 2. Funnel terukur (setahun, 71.128 bar)

| Tahap | BUY | SELL |
|---|---|---|
| L1 bias | 42.845 (60,2%) | 28.283 (39,8%) |
| + L2 sweep | 25.978 (36,5%) | 16.117 (22,7%) |
| + L3 choch | 6.165 (8,7%) | 3.293 (4,6%) |
| + L4 trigger = **sinyal** | **2.457 (3,45%)** | **1.237 (1,74%)** |

Penyempit terbesar: **L3** (hanya ~21–24% yang lolos) dan **L4** (~38–40%). L1+L2 masih menyisakan 37%/23% bar — artinya L2 **bukan** lapis yang menentukan (lihat C2).

## 3. C1 — Definisi "CHoCH"

**Temuan kode:** L3 = "close menembus ekstrem 5-bar M15". Tidak ada pemeriksaan struktur sebelumnya (apakah swing itu lower-high dalam downtrend, dsb.), tidak ada konfirmasi BOS lanjutan — sesuai kekhawatiran.

**Temuan ukur (pada 3.694 bar sinyal):**

| | Continuation (swing searah bias, karakter BOS) | Reversal (swing melawan, karakter CHoCH murni) |
|---|---|---|
| BUY (n=2.457) | 59,7% | 40,3% |
| SELL (n=1.237) | 56,9% | 43,1% |

**Interpretasi:** label "CHoCH" tidak presisi — mayoritas sinyal sebenarnya breakout kelanjutan searah bias H1. **Ini bukan bug**: definisi inilah yang menghasilkan +$4.493/thn (WR 73,0%, PF 1,12) di backtest, dan logika live terbukti identik bar-per-bar (parity 0 mismatch). Mengubah definisi (menambah syarat struktur) = **strategi baru** yang harus ditune & di-backtest ulang dari nol — tidak dilakukan.

## 4. C2 — Kualitas klasifikasi sweep

**Temuan ukur pada bar sinyal:**

| Metrik | Nilai | Makna |
|---|---|---|
| Wick-only (close kembali ke sisi level di bar sentuh) | **93,9%** | hampir semua sweep adalah likuiditas wick klasik, bukan breakdown close-through (6,1%) — jauh lebih baik dari dugaan |
| Reclaim di bar sinyal (close sudah melintasi level kembali) | **95,1%** | sekuens sweep→reclaim muncul **alami** dari AND-gating (L3/L4 mensyaratkan close menembus swing) — tidak perlu aturan reclaim eksplisit |
| Kedua sisi (PDH & PDL) tersapu dalam 24 jam | **79,6%** | jendela 24 jam hampir selalu menyapu dua sisi → **L2 sendirian nyaris tidak menyaring**; ia filter konteks, bukan presisi |
| Umur sweep saat sinyal | median **11,8 jam**, maks 24 jam; hanya 12,6% < 1 jam | "sweep" yang dipakai sering setengah hari lalu — jauh dari ideal "baru tersapu" ICT |
| Kedalaman sentuhan terakhir | median $0,00 (P90 $5,90) | sentuhan terakhir umumnya graze tepat di level |

**Interpretasi:** kekhawatiran "salah klasifikasi" terbukti **sebagian**: L2 permissif dan labelnya longgar (umur tua, dua sisi bersamaan). Namun karena L2 hanya meloloskan 60%/57% dari L1 (penyempit kecil), salah klasifikasi L2 **hampir tidak pernah sampai menjadi trade** tanpa lolos L3+L4 yang ketat. Backtest membuktikan kompositnya menguntungkan. **Rekomendasi (tidak dieksekusi):** varian `G4-S2` dengan syarat umur sweep < N jam bisa diuji sebagai eksperimen terpisah — jangan mengubah G4 aktif.

## 5. C3 — Sinyal stale?

**Temuan kode (jalur eksekusi):** tidak ada sinyal yang "disimpan menunggu". Siklus hidupnya:

1. Setiap bar M5 tertutup → `evaluate()` menghitung segalanya dari nol (tidak ada cache sinyal).
2. `last_scanned_bar_time` menjamin **satu evaluasi per bar** (tidak dievaluasi ulang).
3. Hasilnya langsung dieksekusi atau **dibuang selamanya** — tidak ada antrian/persistence.
4. Gerbang tambahan: usia bar ≤ 120 dtk, re-entry paritas, mutex 1-posisi, guard spread.

**Jadi risiko "bot memakai sinyal basi" = nihil by design.** Panel `SELL @ 09-14 20:08` = event `signal_detected` **terakhir dari jurnal** (riwayat eksekusi) — murni informasi. Kekhawatiran yang valid adalah **manusia salah membaca panel** → sudah difix: label menjadi "Sinyal terakhir (riwayat)" + umur relatif ("· 3j lalu") + tooltip penjelasan (commit ini).

## 6. C4 — AND-gating terlalu ketat?

**Temuan ukur:** 3.694 sinyal geometri/thn = **15,2/hari bursa**. Setelah guard spread $1,20 dan batasan eksekusi engine (mutex 1-posisi, strict_bar_open_entry, bar terpakai oleh posisi terbuka) → **1.338 trade/thn = 5,5/hari** (laporan tuning: WR 73,0%, PF 1,12, +$4.493).

**Live 10–14 Sep: 20 trade / 3 hari bursa = 6,7/hari** — konsisten dengan laju backtest (sedikit lebih tinggi karena 11 re-entry candle-sama yang kini diblokir guard paritas `7d243d4`). **Kesimpulan: gating menghasilkan frekuensi sehat; tidak perlu dilonggarkan.** Setiap pelonggaran = keluar dari wilayah teruji.

## 7. C5 — TEMUAN UTAMA AUDIT INI: definisi "hari" PD levels live ≠ backtest

**Kronologi penemuan (dari kekhawatiran #2 "sweep berbasis ekstrem 24 jam"):**

- Pipeline riset: M1 UTC → dikonversi ke **Europe/Athens** → `resample("1D")` → hari Athens. Tengah malam Athens = **tepat 17:00 New York** (NY close) — inilah hari bursa ICT.
- Jalur live: frame berlabel UTC → `_pd_levels` lama mengelompokkan hari per **kalender label frame**. Pra-TZ-FIX: batas hari 03:00 UTC; pasca-TZ-FIX: 00:00 UTC. **Keduanya ≠ 21:00/22:00 UTC (midnight Athens).**
- Akibat: PDH/PDL live dihitung dari "hari" yang memotong 3 jam di tempat berbeda → level berbeda → sweep L2 berbeda dari backtest. Parity check lama tidak menangkapnya karena kedua sisi diberi frame berlabel SAMA (Athens) — jalur labeling live sesungguhnya tidak pernah diuji.

**Ukuran divergensi (setahun, pra-fix):**

| Metrik | Nilai |
|---|---|
| Bar dengan PDH/PDL berbeda (vs riset) | 54.625 bar (**76,8%**) |
| Bar dengan hasil sinyal berbeda | 810 bar (1,14%) |
| Sinyal riset yang **terlewat** live | 316 dari 3.694 (8,6%) |
| Sinyal live yang **tidak pernah diuji** backtest | 494 |

**Implikasi untuk jurnal 10–14 Sep:** +$308 terjadi dengan definisi hari yang tidak persis backtest — secara paritas murni, sebagian sinyal itu berada di luar himpunan teruji. (Pernyataan "16W/4L konsisten ekspektasi G4" tetap sahih secara statistik, tapi bukan paritas eksak.)

**Fix (`_pd_levels`, commit ini):** pengelompokan hari kini memakai **kalender Athens (NY close) dikonversi dari label UTC** — identik riset untuk broker zona waktu apa pun, tahan DST, tanpa mengubah guard berbasis jam (usia bar, re-entry) yang memang memakai UTC sejati.

**Bukti:**
- `research/g4_parity_check.py` diperbarui agar menguji frame **berlabel UTC (jalur live sebenarnya)** → **PASS A/B/C/D: 0 mismatch** pada 71.128 bar (3.694 sinyal identik, anchor/SL/lot OK, burn-in EMA $0,000000).
- `research/g4_funnel_audit.py`: implementasi vektor funnel diverifikasi identik dengan `g4_signal_at` pada 5.329 bar (sampel acak + semua bar sinyal) — 0 mismatch.
- Dashboard `g4_cascade_detail` memakai `_pd_levels` yang sama → otomatis konsisten.

## 8. Tindakan yang diperlukan pemilik akun

1. `git pull` (pastikan commit terbaru dari branch sesi ini).
2. **Restart daemon** — wajib: fix C5 (hari Athens) + TZ-FIX (offset server) + guard re-entry baru hanya aktif setelah restart. Dashboard juga perlu di-restart (label panel riwayat + jam server).
3. Tidak ada parameter yang berubah (TP/SL/risk sama — sesuai kebijakan).

## 9. Hal yang sengaja TIDAK diubah

- Definisi L1–L4 (termasuk "CHoCH" yang secara semantik lebih tepet disebut break struktur hibrid) — mengubahnya = strategi baru, butuh tuning + backtest + parity ulang.
- TP 187,5/375/562,5 pips, Early BE+ off, risk 1% — sesuai instruksi tetap pengguna.
- Ide varian masa depan (bukan sekarang): umur-sweep < N jam (C2), label L3 dinamis "BOS/CHoCH" di dashboard (C1).
