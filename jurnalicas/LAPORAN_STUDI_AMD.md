# LAPORAN STUDI AMD (Accumulation–Manipulation–Distribution)

**Tanggal:** 24 September 2026 · **Pertanyaan pemilik akun:** *"kalo di tambahkan strategi amd gimana?"*
**Skrip:** `research/amd_study.py` (dapat dijalankan ulang) · **Angka lengkap:** `reports/amd_study.txt`

---

## Definisi yang diuji (ICT klasik, kausal, tanpa lookahead)

| Tahap | Implementasi |
|---|---|
| **Accumulation** | Range sesi Asia 03:00–07:00 server (kolom `asian_high/low` engine, terpublikasi tepat 07:00) |
| **Manipulation** | Wick menyapu satu sisi range Asia setelah 07:00 (low ≤ Asian low = sweep bawah; high ≥ Asian high = sweep atas). Varian **AMD-L**: sweep hanya boleh di sesi London 08:00–12:00 (judas swing klasik) |
| **Distribution** | Di jendela 12:00–18:00 srv: bar M5 tertutup pertama yang close *kembali* ke sisi level (reclaim) + candle displacement searah → entry di open bar M5 berikutnya. Maks 1 sinyal per arah per hari |
| **Exit** | **Identik G4** (SL150, TP plan 187,5/375/562,5 split 30/25/25/20, trail 50/30, strict_bar_open_entry, manage_entry_bar, guard spread $1,20, risk $100) — hasil langsung sebanding |

## Hasil — tiga periode, geometry exit sama dengan G4

| Periode | Varian | Trades | WR | AvgWin/AvgLoss | PF | Net | | G4 (pembanding) | PF | Net |
|---|---|---|---|---|---|---|---|---|---|---|
| 2021–22 | AMD | 225 | 76,0% | +$34,56/−$105 | **1,04** | +$240 | | 373 tr | 0,95 | −$537 |
| 2021–22 | AMD-L | 190 | 75,3% | +$35,42/−$105 | 1,03 | +$130 | | | | |
| 2022–23 | AMD | 220 | 71,8% | +$34,27/−$105 | **0,83** | −$1.095 | | 385 tr | 1,02 | +$219 |
| 2022–23 | AMD-L | ~* | ~* | ~* | ~0,8* | negatif | | | | |
| 2025–26 | AMD | 238 | 68,5% | +$36,16/−$105 | **0,75** | −$1.980 | | 1.338 tr | 1,12 | +$4.493 |
| 2025–26 | AMD-L | 177 | 69,5% | +$32,88/−$105 | 0,71 | −$1.626 | | | | |

*\*lihat reports/amd_study.txt untuk angka persis AMD-L 2022-23 (berpola sama: PF<1).*

**Total AMD lintas tiga periode: −$2.835.** (AMD-L serupa.) Frekuensi ±0,7 trade/hari — sesuai karakter "one play a day".

## Analisis kenapa gagal (dan itu informatif)

1. **WR tinggi tapi tidak cukup.** 68–76% menang terlihat bagus, tapi avgWin hanya $33–36 (vs $43 G4): distribusi setelah reclaim Asia cenderung **pendek** — median MFE $6 vs $7 G4. Titik impas mekanik geometri ini ≈ 74–75% WR; AMD hanya menembusnya di 2021–22 (PF 1,04 ≈ impas).
2. **Justru terburuk di 2025–26** (PF 0,75) — pasar emas volatil satu arah: sweep Asia sering *bukan* manipulasi yang dibalik, melainkan awal tren hari itu (continuation). Fade-the-sweep kalah di pasar trending.
3. **Komplementaritas: menarik tapi tak berguna.** Korelasi PnL harian AMD vs G4 = **+0,01** (benar-benar tidak berkorelasi; jam entry AMD 09–12 UTC vs G4 menyebar) — tapi diversifikasi tanpa edge hanya menambah noise + loss.

## VERDICT

> **Jangan ditambahkan.** AMD klasik (fade sweep Asia di sesi NY) dengan exit selevel G4 menghasilkan ekspektasi negatif di 2 dari 3 periode dan total −$2.835 lintas 631 trade. G4 sendiri sudah menangkap bagian yang MENGUNTUNGKAN dari ide manipulasi-reversal (L2 sweep + L3 CHoCH + L4 displacement memang komponen serupa, tapi dengan bias H1 sebagai penyaring arah — komponen yang tidak dimiliki AMD murni, dan di 2025-26 justru penyaring itulah yang menyelamatkan G4 dari nasib AMD).

Catatan metodologi: konsep dirumuskan 24 Sep 2026 dan diuji pada data historis → 2021–23 relatif bersih, 2025–26 in-sample-ish; tetap hasil NEGATIF hampir di mana-mana, sehingga kesimpulan "tidak layak" kuat (tidak ada risiko cherry-picking positif).

Bila ingin strategi tambahan yang terukur: kandidat yang lebih menjanjikan tetap **V7T/V7E** (G4 + filter tren harian; PF 1,95–2,04, signifikan vs 32 baseline acak) — dengan syarat validasi lintas periode dulu (belum pernah diuji di 2021–23).


---

# TAMBAHAN 24 Sep sore — v2: IMPLEMENTASI SETIA SPEC PEMILIK AKUN

Setelah pemilik akun menunjukkan spesifikasi AMD lengkapnya, terbukti v1 di atas menguji varian yang BERBEDA (exit G4). v2 mengimplementasikan spec apa adanya: **akumulasi dinamis** (range 3 jam ≤ 0,8×ATR14-H1) atau **range Asia**, sweep, konfirmasi **FVG/CISD/rejection**, **SL struktural** di luar ekstrem sweep, **TP 1:2 / split 1:2+1:3**, timeout 24 jam, risk $100, pesimis (SL dulu bila sebar). Skrip: `research/amd_study_v2.py` · angka: `reports/amd_study_v2.txt`.

## Hasil v2 — 4 konfigurasi × 3 periode (net $)

| Konfigurasi | 2021–22 | 2022–23 | 2025–26 | Total | n |
|---|---|---|---|---|---|
| dinamis / TP 2R | −10.900 | −7.000 | −1.300 | **−19.200** | 705 |
| dinamis / split 2R+3R | −11.250 | −7.850 | −1.801 | **−20.901** | 689 |
| asia / TP 2R | −9.300 | −6.300 | −2.000 | **−17.600** | 734 |
| asia / split 2R+3R | −9.754 | −6.800 | −2.980 | **−19.535** | 734 |

WR 16–30% — di bawah titik impas 33,3% yang dituntut exit RR 1:2 (lagi pula timeout & spread menambah friksi). **Tidak ada satu pun konfigurasi positif di satu pun periode.** (Konfirmasi dominan CISD ~70% — filter paling lemah dari tiganya.)

## Addendum: apakah bias H1 bisa menyelamatkannya?

Filter tambahan "hanya trade searah EMA200-H1" (replika L1 G4) memang MEMPERBAIKI AMD di semua sel (mis. asia/2R: −9.300→−2.400; −2.000→−100) — tapi hasil terbaiknya tetap PF 0,98 (impas), tidak pernah positif.

## Kesimpulan final (v1 + v2 + addendum)

Ide "manipulasi → distribusi" **tidak menghasilkan edge yang dapat ditagih di XAUUSD** dalam bentuk apa pun yang diuji: exit trailing (v1), exit RR sesuai spec (v2), dengan/tanpa bias H1 — 12+ konfigurasi, 3 periode, ~2.100 trade total, semuanya ≤ impas. Yang membuat G4 tetap hidup bukan sekadar "sweep + pembalikan", melainkan **konjungsi penuh kaskade**: sweep level HARI SEBELUMNYA (PDH/PDL, bukan range Asia) + break struktur M15 searah + displacement/FVG M5 + bias H1 + exit trailing yang dikalibrasi ke distribusi pergerakan aktual sinyal itu. Komponen AMD yang "benar" sudah ada di dalam G4; menambahkan AMD sebagai strategi terpisah hanya menambah ekspektasi negatif.

Alternatif yang MASIH layak diuji suatu saat (bukan sekarang): AMD sebagai *filter waktu* untuk G4 (mis. menahan entry G4 pada jam-jam tertentu) — beda pertanyaan, butuh studi tersendiri.
