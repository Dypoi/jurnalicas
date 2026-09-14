# LAPORAN TUNING SCALPING — DIAGNOSIS "APA YANG MEMBUAT ENGINE TIDAK PROFIT?"

**Pertanyaan pengguna (09 Sep 2026):** *"Sebulan cuman segitu entrynya? Niatnya SMC kan buat scalping — dari log, 1 hari bisa beberapa kali entry dan saya cukup senang. Cari tuningan berdasarkan log tersebut: apa yang membuat engine tidak profit? Apakah TP-nya kejauhan, pip-nya kebesaran?"*

**Sumber data : (1) log live `logs/trade_journal.jsonl` — 21 tiket, 26–31 Agu 2026 (bot icas-v2-swing150-c); (2) backtest setahun n=1.234 (sinyal sama, eksekusi M5); (3) grid 29 varian + kontrol acak + Monte-Carlo 32-seed**
**Engine : `research/backtest_m1_audit.py` (bid/ask, anti-repaint, pesimis, spread riil) | risk uji 1%**
**Artefak : `reports/tuning_scalp_*.txt`, `tuning_scalpmtf_*.txt`, `multiseed_mtf_scalp_*.txt`**
**Tanggal : 09 September 2026**

---

## RINGKASAN EKSEKUTIF — JAWABAN LANGSUNG

1. **Frekuensi entry Anda benar dan bisa dipertahankan** — log live: rata-rata 3,5 entry/hari aktif
   (puncak 8 entry/hari pada 28 Agu). Masalahnya BUKAN frekuensi.
2. **TP kejauhan? BUKAN penyebabnya.** Bukti: semua 11 varian "TP didekatkan" (25–200 pips)
   membuat hasil LEBIH BURUK — varian paling agresif (TP 25/75) mencetak WR 79,9% tapi
   **bangkrut** (PF 0,73, −$10.019). Win rate tinggi adalah jebakan klasik scalping: win jadi
   recehan sementara loss tetap penuh.
3. **SL/pip kebesaran? JUGA BUKAN.** Winner sangat tahan terhadap SL 150 (hanya 1,3% winner
   sempat −150 sebelum lari); mengetatkan SL ke 100 memotong 21% winner → varian SL 100
   katasrtofis (PF 0,74–0,83, semua bangkrut).
4. **Biang keroknya: KUALITAS SINYAL, bukan geometri.** Sinyal choch+sesi (yang jalan di bot
   live Anda) di setahun backtest = PF 0,92 — **kalah dari entry acak** (kontrol acak geometri
   sama: PF 1,02). Frekuensi tinggi tanpa edge = kecepatan tinggi kehilangan uang.
5. **Profit engine itu hidup di ekor kanan (runner)** — di log live Anda, SEMUA 8 winner lari
   ≥189 pips; itu satu-satunya sumber dolar. Memotong ekor kanan dengan TP dekat = memotong
   arteri. Geometri plan (TP jauh + BE + trailing) sudah benar; **yang harus diganti sinyalnya**.
6. **Solusi "scalping + profit" yang lolos gerbang**: sinyal MTF sweep PDH/PDL 24 jam (W24h)
   dengan trailing lebih cepat — **G4: ~103 entry/bulan (3–4/hari aktif), PF 1,12, +$4.493/setahun
   (risk 1%), DD 19,5%, signifikan vs 32-seed acak (p=0,000)**; dan **G6 (W24h+SMA200-harian):
   42/bln, PF 1,21, +$4.585, exp +$8,38/tr**. Keduanya masih DEMO + risk 1% (2021–22 belum hijau).

---

## 1. ANATOMI LOG LIVE (21 tiket, 26–31 Agu 2026, lot 0,33 = risk 5%)

| Fakta | Angka |
|---|---|
| Frekuensi | 21 entry / 6 hari aktif = **3,5/hari** (28 Agu: 8 entry) |
| Hasil | **−$1.524** \| 8W/11L \| WR 42% \| PF 0,72 |
| 11 LOSER | MFE maksimal **≤ 2 pips** (median 1 pip) — tidak ada satu pun loser yang sempat +25 pips |
| 8 WINNER | SEMUA lari **≥ 189 pips** (TP1 selalu tersentuh; favorit 189–236 pips) |
| TP2 (375) / TP3 (562) | **tidak pernah kena sekali pun** |
| Per loss | −$490 s/d −$763 (SL penuh + spread/slippage; 29 Agu sempat hold 50 jam lintas weekend) |

**Pembacaan:** two-sided anatomy yang ekstrem — sinyal hidup atau mati dalam hitungan menit.
Loser tidak pernah "hampir menang" (tak bisa diselamatkan TP dekat); winner selalu lari jauh
(tak boleh dipotong TP dekat). Artinya **satu-satunya cara geometri membantu = memperbesar
tangkapan ekor kanan, bukan mempercepat realisasi kecil**.

## 2. VALIDASI DI SAMPEL BESAR (backtest setahun, sinyal choch, n=1.234, plan geometry)

| Pertanyaan | Jawaban data |
|---|---|
| Seberapa jauh trade umumnya bergerak? | MFE: median 111 pips; 71% trade mencapai +50; 58% +100; hanya 26% +187,5 (TP1) |
| Apakah TP dekat bisa menyelamatkan loser? | 53% loser sempat +25 pips — tapi memotong winner lebih mahal (lihat §3) |
| Apakah SL 150 kebesaran? | **Tidak** — hanya 1,3% winner sempat −150; SL 100 memotong 21% winner, SL 75 memotong 34% |
| Ke mana perginya profit? | 40% win adalah win besar (> $80) hasil runner trailing; 55% win scratch ≤ $50 |
| Dekomposisi hasil | 714W × +$71 = +$50.405 vs 520L × −$105 = −$54.600 → PF 0,92 |
| vs acak? | Kontrol acak geometri sama: **PF 1,02** → sinyal TIDAK punya edge |

## 3. GRID SCALPING SINYAL LAMA (S1–S11) — HIPOTESIS "TP DEKAT" GUGUR

| Varian (sinyal choch, frekuensi ±95–173/bln) | Tr | WR% | PF | Net $ | Vonis |
|---|---:|---:|---:|---:|---|
| A plan (TP 187,5/375/562, SL150) — referensi | 1.234 | 57,9 | 0,92 | −4.195 | rugi |
| S1 TP 50/100 (50/50) | 1.528 | 69,5 | 0,80 | −10.010 | **bangkrut** |
| S2 TP 75/150 | 1.500 | 64,4 | 0,89 | −5.974 | rugi |
| S4 TP 50/100 + **SL 100** | 938 | 58,9 | 0,74 | −10.000 | **bangkrut** |
| S5 TP 75/150 + SL 100 | 1.234 | 53,0 | 0,83 | −10.015 | **bangkrut** |
| S6 TP 100/200 | 1.338 | 57,3 | 0,89 | −6.374 | rugi |
| S7 TP1 50 (70%) + runner | 1.450 | 70,6 | 0,81 | −8.390 | rugi |
| **S8 TP 25/75 (ultra scalp)** | 1.733 | **79,9** | **0,73** | **−10.019** | **bangkrut (WR tertinggi!)** |
| S9 TP 50/100 + trail cepat | 1.806 | 70,0 | 0,82 | −10.003 | bangkrut |
| S10 S1+SMA200d | 825 | 71,3 | 0,85 | −3.605 | rugi |
| S11 S5+SMA200d (terbaik scalp) | 763 | 56,0 | 0,96 | −1.192 | rugi |
| R ACAK (kontrol, geometri plan) | — | ~57 | 1,02 | +748 | **mengalahkan semua varian S** |

**Kesimpulan §3:** pada sinyal tanpa edge, SEMUA manipulasi geometri hanya memindahkan
kerugian. WR 79,9% + bangkrut adalah bukti tekstbook bahwa win-rate bukan tujuan.

## 4. GRID SINYAL MTF (PUNYA EDGE) × GEOMETRI (G1–G6)

Sinyal W24h (kaskade H1→sweep PDH/PDL 24j→CHoCH M15→M5, eksekusi M5) — frekuensi 66/bln:

| Varian | Tr | WR% | PF | Net $ | DD% | Entry/bln |
|---|---:|---:|---:|---:|---:|---:|
| W24h plan (TP 187,5/375/562) — referensi | 855 | 61,2 | 1,15 | +5.257 | 12,4 | 65,8 |
| G1 W24h + TP 100/200 | 1.025 | 60,3 | 1,05 | +2.044 | 23,9 | 78,8 |
| G2 W24h + TP 125/250 | 961 | 61,1 | 1,07 | +2.686 | 19,7 | 73,9 |
| G3 W24h + TP 50/100 (scalp) | 1.477 | 72,4 | 0,91 | **−3.762** | 51,7 | 113,6 |
| **G4 W24h + trail cepat 50/30 (TP plan)** | **1.338** | **73,0** | 1,12 | **+4.493** | 19,5 | **102,9** |
| G5 V8T + TP 100/200 | 170 | 62,9 | 1,18 | +1.169 | 6,0 | 14,2 |
| **G6 W24h + SMA200-harian (TP plan)** | 547 | 62,0 | **1,21** | **+4.585** | 16,7 | 42,1 |

TP dekat tetap merusak walau sinyalnya ber-edge (G3 rugi; G1/G2 di bawah referensi).
**Satu-satunya tweak geometri yang menambah frekuensi TANPA membunuh profit = trailing lebih
cepat (G4)** — karena trailing 50/30 merealisasi scratch lebih sering (WR 73%) namun runner
besar tetap hidup (TP plan tak diubah).

## 5. GERBANG: LINTAS REZIM + MONTE-CARLO 32-SEED

| Varian | 2025–26 | 2021–22 | 2022–23 | Kumulatif | p-value (32-seed, 2025–26) |
|---|---:|---:|---:|---:|---:|
| **G4** (W24h+trail cepat) | +4.493 | −537 | **+219** | **+$4.175** | **0,000 SIGNIFIKAN** |
| **G6** (W24h+SMA200d) | +4.585 | −698 | −577 | +$3.310 | **0,000 SIGNIFIKAN** |
| W24h (referensi) | +5.257 | −366 | −1.252 | +$3.639 | 0,000* |

*W24h telah diuji signifikan pada periode utama (rev 2.2). Kelemahan bersama: **2021–22 masih
merah** (rezim bearish/konsolidasi) — belum ada varian frekuensi-tinggi yang hijau di sana.

## 6. KESIMPULAN & REKOMENDASI

1. **Jawaban untuk Anda:** yang membuat engine tidak profit adalah **sinyalnya (choch+sesi
   Asia/London), bukan TP/SL**. TP jauh + trailing plan Anda justru sudah optimal — 8 winner
   di log live Anda semua ≥189 pips adalah buktinya. Jangan dekatkan TP; jangan kecilkan SL.
2. **Ingin scalping (entry harian) + profit → G4**: sinyal MTF W24h + trailing 50/30.
   ~3–4 entry/hari aktif (103/bln), WR 73%, PF 1,12, +$4.493/thn (risk 1%), DD 19,5%,
   signifikan vs acak, satu-satunya varian frekuensi-tinggi yang positif di 2022–23.
3. **Ingin kualitas per trade lebih tinggi → G6**: 42 entry/bln (±1,6/hari), PF 1,21,
   exp +$8,38/trade, +$4.585/thn.
4. **Saran komposisi DEMO**: jalankan G4 sebagai engine utama (kepuasan frekuensi scalping)
   dan G6/V8T sebagai pembanding paralel di akun demo terpisah — kompetisi 3 bulan,
   evaluasi bulanan dengan standar laporan ini.
5. **Risk maks 1%** (tetap). Live 26–31 Agu Anda jalan di risk 5% (lot 0,33) — dengan WR 42%
   dan 11 loss beruntun potensial, itu yang membuat −$1.524 dalam 6 hari; pada risk 1%,
   kerugian sama ≈ −$305.
6. Langkah berikutnya: (a) forward-test DEMO G4+G6 ≥3 bulan; (b) riset penambal rezim
   2021–22 (filter volatilitas/ADX); (c) opsi: killzone London/NY saja pada G4 untuk
   menaikkan kualitas bila frekuensi masih terasa kurang.

## 7. REPRODUCIBILITY

```
# grid scalp sinyal lama (S1-S11) + baseline + acak
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 100 --random --variants A,S1,S2,S3,S4,S5,S6,S7,S8,S9,S10,S11 \
    --out reports/tuning_scalp_20250901_20260901_risk100_execm5.txt

# grid MTF x geometri (G1-G6) + W24h + acak
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 100 --random --variants W24h,G1,G2,G3,G4,G5,G6 \
    --out reports/tuning_scalpmtf_20250901_20260901_risk100_execm5.txt

# lintas rezim G4/G6
.venv/bin/python research/tuning_mtf.py --start 2021-09-01 --end "2022-09-01 23:59:59" \
    --risk 100 --variants W24h,G4,G6
.venv/bin/python research/tuning_mtf.py --start 2022-09-01 --end "2023-09-01 23:59:59" \
    --risk 100 --variants W24h,G4,G6

# Monte-Carlo 32-seed
.venv/bin/python research/multiseed_check.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 100 --seeds 32 --candidates G4,G6
```

Artefak: `reports/tuning_scalp_20250901_20260901_risk100_execm5.txt` (S-grid),
`reports/tuning_scalpmtf_20250901_20260901_risk100_execm5.txt` (G-grid; run pertama file ini
pra-fix prefix — **seluruh G1–G6 diganti hasil post-fix**, file berisi hasil valid),
`reports/tuning_scalpmtf_2021.../2022...`, `reports/multiseed_mtf_scalp_...`.

Perubahan kode (additif; regresi hijau — test_antirepaint 24 PASS, test_exec_m5 6 PASS,
baris baseline A pada artefak lama terverifikasi identik):
- `research/backtest_m1_audit.py` — tracking **MAE** pada Position (`mae_pips` di tdf) untuk
  analisis anatomi winner/loser.
- `research/tuning_mtf.py` — varian S1–S11 (scalp sinyal choch) & G1–G6 (MTF×geometri),
  `signal_mode` kini eksplisit per varian (fix bug: varian G mula-mula tak sengaja jalan
  sebagai choch karena logika prefix).
- `research/multiseed_check.py` — argumen `--candidates` (pilih varian yang diuji).
