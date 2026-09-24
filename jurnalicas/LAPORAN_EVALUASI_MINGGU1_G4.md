# LAPORAN EVALUASI MINGGU-1 ENGINE G4 LIVE (icas-v3-g4)

**Tanggal evaluasi:** 24 Sep 2026 · **Data:** `logs/trade_journal.jsonl` 3.794 baris (10–22 Sep 2026, dikirim pemilik akun) + state + health marker
**Metode:** rekonstruksi otomatis (`research/evaluate_live_journal.py` → `reports/eval_live_g4_week1.txt`) + analisis per-trade + replikasi backtest setahun untuk konteks statistik
**Pembanding:** backtest G4 setahun (2025-09..2026-09): 1.338 trade, WR 73,0%, PF 1,12, +$4.492,72, avgWin +$43,40, avgLoss −$105,00, TP1 6,1%, trailing-aktif 73,0%, loss beruntun maks 5, MaxDD 19,5%

---

## VERDICT SINGKAT

> **Tidak ada bug. Semua sistem bekerja. Minggu ini adalah minggu yang buruk secara pasar (regime), dan hasilnya MASIH DI DALAM pengalaman backtest setahun — tapi tepat di ekor distribusi. Dua hal butuh tindakan operasional: daemon sudah MATI 2 hari, dan mesin Anda kehilangan ~25% uptime.**

| Metrik | Live (era bersih 16–22 Sep, n=27) | Backtest setahun | Status |
|---|---|---|---|
| Win rate | **48,1%** (13W/14L) | 73,0% | ✗ di ekor bawah (lihat §5) |
| Avg win | **+$41,31** | +$43,40 | ✓ identik |
| Avg loss | **−$105,08** | −$105,00 | ✓ identik persis |
| Net | **−$934,12** (6 hari bursa) | ekspektasi ~+$20/hari | ✗ (lihat §5: worst-6-hari backtest = −$1.010) |
| Trade/hari | 4,5 | 4,27 | ✓ |
| Win via trailing | 12/13 (92%) | 73,0% | ✓ desain terkonfirmasi |
| Loss beruntun | **7** | maks 5 | ⚠ melebihi backtest (n kecil) |
| Slippage | −$1,30..+$0,94 (median ≈ $0) | — | ✓ sehat |

**Total G4 live (10–22 Sep):** +$308,16 (10–14 Sep, era pra-guard) − $934,12 (16–22 Sep, era bersih) = **−$625,96** (−7,1%). Balance 9.008,63 → 8.171,57 — **rekonsiliasi PERSIS ke cent** (awal + Σpnl = akhir ✓).

---

## 1. Integritas & versi kode (penting untuk membaca hasil)

Kronologi restart vs tanggal commit menunjukkan **era bersih dimulai 15 Sep 17:58 WIB** (restart 12 menit setelah fix C5 PD-Athens di-push 17:46 WIB; bukti di jurnal: event `server_clock_offset offset=0 prev=athens_assumption` tercatat di setiap restart pasca-TZ-fix):

| Periode | Kode aktif | Hasil |
|---|---|---|
| 10–14 Sep 23:16 | G4 tanpa guard re-entry / TZ-fix / C5 | +$308,16 (20 trade, 16W — sudah diaudit turn sebelumnya) |
| 14 Sep 23:16 – 15 Sep 17:58 | **BUG TZ aktif** (asumsi Athens vs server GMT+0) | **0 trade** — 132 bar dibuang `signal_skipped_stale` (12/jam × 11 jam). 1 hari bursa hilang. |
| 15 Sep 17:58 – 22 Sep 11:03 | **Semua fix aktif** (TZ + C5 + re-entry + SL re-anchor) | 27 trade, −$934,12 ← *era yang dievaluasi di sini* |

Bukti sistem hidup di era bersih: `server_clock_offset` 5× (UTC+0 ✓), `signal_skipped_reentry` 1× (18 Sep 02:31, SELL bar 17 Sep 19:25 — guard paritas bekerja), `sl_reanchor` 6× (16–17 Sep — proteksi deviasi SL bekerja), stale-skip turun dari 12/jam → ~2/hari (sisa = koneksi riil, normal), `max_fav` terekam 37/37 trade (fix MF-01 bekerja), rekonsiliasi exact, 1 `order_failed` (17 Sep 19:30 — jam-jam sibuk; satu entry terlewat).

## 2. Anatomi 27 trade era bersih

- **14 loss: SEMUA full SL (−$103..−$107) dan max_fav nyaris nol (rata-rata $1,50, maks $3,71)** → sinyal salah arah SEJAK AWAL, bukan salah kelola. Tidak ada satu pun loss yang "seharusnya menang lalu diambil kembali" (0 loss dengan max_fav ≥ $35) → **bukan masalah trailing/laptop**.
- **13 win: 6× +$21 (lock 30p), 3× +$56 (lock 80p), +$16, +$47, +$159 (satu-satunya TP1: 17 Sep 19:01 BUY)** → persis mekanika trailing desain (step 50/lock 30).
- Arah: 21 SELL / 6 BUY. Entri 4.248→4.373 = emas **naik perlahan sepanjang minggu** (bounce setelah crash 4.408→4.256 minggu lalu). L1 bias H1 masih bearish (harga di bawah EMA200 setelah penurunan besar) → sinyal dominan SELL → berulang kali kena stop di pasar yang justru merangkak naik. **Ini loss regime trend-following standar, bukan malfungsi.**
- Hari terburuk 16 Sep: 5 trade, 0W (−$526,94) — lima SELL beruntun saat emas rally 4.278→4.339.

## 3. Perbandingan profil live vs backtest (detil)

| Komponen | Live | Backtest | Kesimpulan |
|---|---|---|---|
| Ukuran win khas | +$21 / +$56 (trail lock 30p/80p) | avgWin +$43,40; 73% win via trailing | ✓ mekanika identik |
| Ukuran loss khas | −$105 (SL 150p penuh) | avgLoss −$105,00 | ✓ identik |
| TP1 (188p) tersentuh | 1/27 = 3,7% | 6,1% | ✓ (n kecil; TP1 memang jarang by design) |
| Frekuensi | 4,5/hari | 4,27/hari | ✓ |
| Median max_fav pemenang | ~$7-10 | median MFE $7,05 | ✓ |

**Yang berbeda HANYALAH win rate** — dan itulah yang ditentukan pasar, bukan kode.

## 4. Konteks statistik (replikasi backtest, 1.338 trade setahun)

- **Rolling-27-trade WR terburuk backtest = 44,4% (12/27)** — terjadi 29 Okt–4 Nov 2025, tepat sebelum bulan merah Nov (−$705). Live minggu ini: 48,1% → **lebih baik dari stretch terburuk backtest**.
- Jendela 27-trade dengan WR ≤ 48,1%: **9 dari 1.312 (0,7%)** — jarang, tapi terjadi ~2-3× setahun di backtest.
- **Rolling-6-hari-bursa terburuk backtest = −$1.010** vs live −$934 → minggu ini BUKAN di luar batas pengalaman backtest.
- 42% hari bursa backtests merah; 41% minggu kalender merah. Sistem ini **memang** merah 2 dari 5 minggu secara struktur.
- MaxDD backtest 19,5% ($2.242). Live drawdown dari puncak (9.105,69 → 8.171,57) = **−10,3%** → masih dalam amplop desain.
- Satu-satunya yang MELEBIHI backtest: **loss beruntun 7 vs maks 5**. Dengan n=27 ini belum konklusif (streak "berkerumun" di regime buruk), tapi dicatat sebagai pemantauan — kalau terulang ke 9-10 di era bersih, itu sinyal untuk evaluasi ulang.

## 5. Operasional (ini yang paling perlu diperbaiki)

| Temuan | Dampak |
|---|---|
| **Daemon MATI sejak 22 Sep 11:03 (engine_stop; saat laporan ini dibuat sudah 2 hari)** | 2 hari bursa tanpa trading & tanpa data. **Restart sekarang.** |
| 15 Sep hilang penuh (bug TZ — sudah difix) | 1 hari bursa |
| `feed_invalid` 120-128/hari di hari aktif + 27 gap equity >20 mnt (maks 337 mnt) | ~1,5-2 jam/hari buta; untungnya 0 loss akibat kelola (§2) — tapi entry bisa terlewat & trailing beku saat gap |
| 1.434 feed_invalid Sabtu 19 Sep | daemon jalan menulis event sampah saat pasar tutup — jinak, tapi boros |
| Restart Senin 21 Sep jam 10:41 WIB | sesi Asia+London-awal Senin terlewat |

Total uptime hilang ≈ 3,5 dari 13 hari kalender ≈ **25%**. Dengan SL di broker ini tidak berbahaya, tapi mengurangi jumlah trade (sampling regime makin lambat) dan membuang sesi London — salah satu sesi paling likuid.

## 6. Rekomendasi

1. **RESTART daemon sekarang** (`git pull` → pastikan `6f00a98`+ → jalankan `python icas_daemon.py`), lalu biarkan jalan.
2. **Jangan ubah parameter apa pun.** Profil eksekusi identik dengan backtest; minggu buruk ≠ sistem rusak. Setiap perubahan = wajib tuning + backtest + parity ulang (prinsip yang kita pegang sejak awal).
3. **Lanjut demo sampai ~akhir Sep/awal Okt** (target ≥ 60-100 trade era bersih) → evaluasi ulang dengan skrip yang sama (`python research/evaluate_live_journal.py --since 2026-09-16`). Keputusan naik real menunggu: WR era bersih ≥ ~60% DAN tanpa insiden operasional besar.
4. **Stabilkan mesin** (dua opsi): `powercfg /change standby-timeout-ac 0` + matikan hibernasi — atau **VPS** (rekomendasi kedua ini yang serius kalau tujuan real; akar 90% insiden minggu ini = laptop).
5. Konfirmasi kecil ke saya: balance MT5 Anda sekarang **$8.171,57**? (harus persis — semua posisi tertutup).

---

## LAMPIRAN — 27 trade era bersih (16–22 Sep)

```
tiket       waktu               arah    pnl     maxfav  tp1  trail  slippage
5105460577  09-16 07:55  SELL  -105.16    2.28   -    0    +0.02
5106699614  09-16 11:50  SELL  -104.31    0.51   -    0    -0.10
5107800240  09-16 15:40  SELL  -106.07    1.21   -    0    -0.24
5108927041  09-16 19:25  SELL  -105.00    2.97   -    0    -0.59
5109740643  09-16 21:05  SELL  -106.40    3.71   -    0    +0.20
5111341582  09-17 01:05  SELL  -105.00    0.41   -    0    -1.30
5111565712  09-17 01:15  SELL   +21.00    6.69   -    1    -0.06
5111953761  09-17 01:35  SELL   +46.59   10.07   -    2    +0.94
5112415391  09-17 02:00  SELL  -106.94    0.00   -    0    +0.28
5112578324  09-17 02:10  SELL   +56.00   14.53   -    2    +0.09
5112748212  09-17 02:20  SELL   +21.00    7.40   -    1    +0.28
5114624503  09-17 09:55  SELL  -105.00    0.45   -    0    +0.65
5117431827  09-17 19:01   BUY  +159.25   25.12   Y    5    -0.70   ← satu-satunya TP1
5117683749  09-17 19:25   BUY   +56.00   10.80   -    2    +0.59
5120057291  09-18 01:35  SELL   +21.00    6.60   -    1    -0.23
5120350925  09-18 03:15  SELL  -102.79    3.31   -    0    -0.32
5121625219  09-18 10:20  SELL  -107.12    2.49   -    0    +0.30
5125319483  09-18 20:55  SELL   +21.00    5.96   -    1    -0.19
5125657228  09-18 21:30  SELL  -106.12    0.00   -    0    +0.16
5131241009  09-21 12:10  SELL   +21.00    5.66   -    1    -0.20
5131646921  09-21 13:20  SELL   +21.00    6.13   -    1    -0.03
5135661081  09-21 23:20   BUY  -106.01    0.00   -    0    +0.15
5136680702  09-22 05:50   BUY   +16.19    5.43   -    1    -0.20
5136732037  09-22 06:05   BUY   +56.00   10.51   -    2    -0.11
5136960144  09-22 07:05   BUY  -102.98    2.38   -    0    -0.29
5137115036  09-22 07:40  SELL  -102.25    1.27   -    0    -0.39
5137511391  09-22 08:50  SELL   +21.00    5.38   -    1    +0.39
```

*Skrip evaluasi: `research/evaluate_live_journal.py` (bisa dijalankan ulang kapan pun). Angka mentah: `reports/eval_live_g4_week1.txt`.*
