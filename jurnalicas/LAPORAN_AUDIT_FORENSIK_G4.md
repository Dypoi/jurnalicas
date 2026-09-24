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

## 7. C5 — TEMUAN UTAMA AUDIT: definisi "hari" PD levels live vs backtest *(KOREKSI 24 Sep — baca lengkap)*

**Koreksi penting 24 Sep 2026:** klaim awal C5 bahwa pipeline riset mengelompokkan hari per **kalender Athens (NY-close)** adalah **MISDIAGNOSIS**. Verifikasi empiris menyusul (replika persis `_map_htf(dur="1D")` cocok 0/16.164 bar; bar Minggu pertama data berlabel 22:00 = pembukaan Exness dalam UTC): pipeline riset **membiarkan label data = UTC** (hanya kolom `srv_*` yang dikonversi ke Athens), sehingga `resample("1D")` riset mengelompokkan hari per **KALENDER UTC murni** (batas 00:00 UTC).

Kronologi lengkap temuan ini:
- **Pra-TZ-FIX (10–15 Sep pagi):** live mengonversi candle ke label Athens (asumsi server salah) → kalender label = Athens ≠ kalender UTC riset → **misalignment 3 jam yang nyata** di era itu.
- **TZ-FIX (15 Sep 10:46 UTC):** frame live menjadi berlabel UTC sejati → kalender label = kalender UTC = **otomatis persis riset**. Pada titik ini paritas sebenarnya SUDAH tercapai.
- **"Fix" C5 (15 Sep 17:46 UTC):** karena misdiagnosis, `_pd_levels` diubah ke kalender Athens + frame parity check digeser — dua perubahan yang **saling menutupi** di Pass A (0 mismatch yang menyesatkan) dan membuat **era-bersih live (15 Sep 17:58 – 22 Sep 11:03) menyimpang 3 jam dari backtest** untuk sinyal-sinyal yang sensitif L2.
- **KOREKSI (24 Sep):** `_pd_levels` dikembalikan ke kalender label frame (= UTC pasca-TZ-FIX = riset), penggeseran frame di parity check dicabut, dan parity check DIJALANKAN ULANG: **PASS A–D 0 mismatch** pada 71.128 bar — kini tanpa kesalahan yang saling menutupi.

Angka divergensi di §4 laporan funnel (76,8% bar PDH/PDL beda antarmode, 810 bar sinyal beda) tetap benar SEBAGAI ukuran mode-vs-mode; interpretasinya yang dikoreksi: mode yang cocok dengan riset adalah **kalender label/UTC**, bukan Athens.

**Pembelajaran proses:** dua kesalahan yang berkebalikan di dua sisi perbandingan menghasilkan "0 mismatch" palsu — verifikasi semantik harus dilakukan pada SUMBER (replika eksak fungsi riset), bukan hanya pada hasil akhir perbandingan.

## 8. Tindakan yang diperlukan pemilik akun

1. `git pull` (pastikan commit terbaru dari branch sesi ini).
2. **Restart daemon** — wajib: fix C5 (hari Athens) + TZ-FIX (offset server) + guard re-entry baru hanya aktif setelah restart. Dashboard juga perlu di-restart (label panel riwayat + jam server).
3. Tidak ada parameter yang berubah (TP/SL/risk sama — sesuai kebijakan).

## 9. Hal yang sengaja TIDAK diubah

- Definisi L1–L4 (termasuk "CHoCH" yang secara semantik lebih tepet disebut break struktur hibrid) — mengubahnya = strategi baru, butuh tuning + backtest + parity ulang.
- TP 187,5/375/562,5 pips, Early BE+ off, risk 1% — sesuai instruksi tetap pengguna.
- Ide varian masa depan (bukan sekarang): umur-sweep < N jam (C2).

## 10. Chart BOS/CHoCH di dashboard (terimplementasi 15 Sep 2026)

Ide §9 ("label L3 dinamis BOS/CHoCH di dashboard") DIEKSEKUSI sebagai fitur visual read-only (`/api/structure` + `g4_structure_events()`):

- **Definisi marker** (mengikuti cara kerja L3): level swing 5-bar M15 `[k-6..k-2]`; BREAK = crossing PERTAMA close M5 terhadap level aktif. Klasifikasi **konvensi struktur ICT**: searah break terakhir = **BOS** (biru), melawan = **CHoCH** (ungu); ⚡ = bar break yang juga menghasilkan sinyal G4.
- **Statistik setahun** (15.938 event: 12.473 BOS / 3.465 CHoCH): 41,4% bar sinyal G4 menyala **persis di bar break** (1.529 — inilah event ber-⚡, terverifikasi match 100% dengan bar sinyal); sisanya 58,6% menyala di bar lanjutan setelah break (close tetap di luar level aktif) — konsisten dengan karakter continuation temuan C1. NB: klasifikasi chart (flip arah break) adalah sumbu berbeda dari ukuran C1 (swing vs swing sebelumnya); keduanya sahih untuk pertanyaan masing-masing.
- Level swing M15 **aktif** (belum ditembus) digambar sebagai garis SWH/SWL samar.
- Jalur trading TIDAK tersentuh (sinyal tetap `g4_signal_at`; fungsi ini murni untuk gambar).

