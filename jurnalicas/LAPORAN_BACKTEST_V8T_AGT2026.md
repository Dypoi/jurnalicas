# LAPORAN BACKTEST — V8T RISK 2%, PERIODE AGUSTUS 2026

**Varian : V8T — kaskade MTF (H1 → M30 → M15 → M5) + filter tren SMA200-harian, eksekusi M5**
**Periode : 01-08-2026 → 31-08-2026 (XAUUSD, 26 hari bursa, 5.796 candle M5 periode)**
**Risk : $200/trade = 2% dari modal $10.000 (sesuai permintaan pengguna, 09 Sep 2026)**
**Engine : `research/backtest_m1_audit.py` (bid/ask, anti-repaint, pesimis [A5], spread riil, guard $1.20)**
**Artefak : `model_icas_bot_FIX/reports/backtest_v8t_20260801_20260831_risk200_execm5.txt` (+ varian setahun `..._20250901_20260901_risk200_execm5.txt`)**
**Tanggal : 09 September 2026**

---

## RINGKASAN EKSEKUTIF

| Metrik | Nilai |
|---|---|
| Trades | **8** (6 WIN / 0 BE / 2 LOSS) |
| Win Rate | **75,0%** |
| Profit Factor | **1,77** |
| Net PnL | **+$301,26** (ROI **+3,01%**/bulan) |
| Ekspektasi | +$37,66/trade |
| Avg Win / Avg Loss | +$115,21 / −$195,00 |
| Max Drawdown | **1,96%** ($198,58) |
| Ekuitas akhir | $10.301,26 dari $10.000 |
| Hari aktif | 5 dari 26 hari bursa (0,31 tr/hari bursa) |
| Loss beruntun maks | 1 |
| BUY/SELL | 6/2 |
| Median MFE | $13,10 (spread median entry $0,709) |

Bulan hijau dengan risiko terkendali — tetapi baca §"Batas Validitas": **n=8 tidak punya
kekuatan statistik**; ini laporan deskriptif bulanan, bukan bukti edge.

## 1. KONFIGURASI VARIAN

Kaskade (semua kausal, tanpa lookahead antar-timeframe):

| Lapis | TF | Aturan |
|---|---|---|
| L1 | H1 | Bias arah: close vs **EMA200 H1** (bar H1 tertutup) |
| L2 | M30 | **Sweep PDH/PDL** kemarin dalam jendela ≤ 4 jam (48 bar M5) |
| L3 | M15 | **CHoCH** — close menembus swing high/low 5-bar M15 |
| L4 | M5 | Trigger: displacement candle + FVG $0,30 / break swing 5-bar |
| F | Harian | Filter tren: close vs **SMA200 harian kemarin** |
| EX | M5 | Entry di **open candle M5 berikutnya**; SL/TP/trailing per candle; pesimis [A5]; `strict_bar_open_entry` + `manage_entry_bar` ON |

Geometri plan: SL 150 pips ($15) | TP 187,5/375/562,5 pips | split 30/25/25/20 | trailing 100/30 | lot = risk/(SL×$10/pip) = **0,13 lot**.

## 2. RINCIAN PER-TRADE (waktu server EET/EEST)

| # | Waktu entry | Arah | PnL $ | Hasil | MFE $ | TP1/2/3 | Trail | Lots | Spread |
|--:|---|---|---:|---|---:|---|---:|---:|---:|
| 1 | Sen 03 Agu 03:45 | SELL | +39,00 | WIN | 10,24 | 0/0/0 | 1 | 0,13 | 0,760 |
| 2 | Sen 24 Agu 03:05 | BUY | +39,00 | WIN | 12,81 | 0/0/0 | 1 | 0,13 | 0,820 |
| 3 | Sen 24 Agu 05:10 | BUY | +39,00 | WIN | 13,39 | 0/0/0 | 1 | 0,13 | 0,810 |
| 4 | Rab 26 Agu 21:05 | BUY | −195,00 | LOSS | 0,96 | 0/0/0 | 0 | 0,13 | 0,650 |
| 5 | Kam 27 Agu 01:10 | BUY | +191,42 | WIN | 22,11 | 1/0/0 | 2 | 0,13 | 0,870 |
| 6 | Kam 27 Agu 14:40 | BUY | −195,00 | LOSS | 0,96→3,52 | 0/0/0 | 0 | 0,13 | 0,570 |
| 7 | Kam 27 Agu 17:45 | BUY | +191,42 | WIN | 20,61 | 1/0/0 | 2 | 0,13 | 0,560 |
| 8 | Sen 31 Agu 05:05 | SELL | +191,42 | WIN | 29,85 | 1/0/0 | 2 | 0,13 | 0,630 |

Ringkasan harian: 03 Agu +$39 | 24 Agu +$78 | 26 Agu −$195 | 27 Agu +$187,84 | 31 Agu +$191,42.

## 3. ANALISIS PERILAKU TRADE

1. **Anatomi profit**: dari 6 win, 4 adalah *scratch-win* trailing-lock +$39 (MFE $10–13 lalu
   terkunci +30 pips) dan 2 win besar +$191,42 (TP1 terealisasi + sisanya keluar via trailing
   level 2). **Seluruh profit bulan ini ditopang 2 trade besar (27 & 31 Agu)** — pola khas
   strategi momentum-arah: banyak scratch kecil, sesekali runner.
2. **Kedua loss bersih** (−$195 penuh, MFE <$4): sinyal gagal segera — konsisten dengan
   desain (SL keras tanpa BE sebelum TP1). Loss beruntun hanya 1.
3. **TP2/TP3 0%** — tidak ada pergerakan ≥$37,5+ yang bertahan di bulan ini; seluruh exit
   via trailing. Trailing aktif pada 75% posisi.
4. **Distribusi waktu**: entry terkonsentrasi dini hari server (01:05–05:10) dan satu di
   14:40/17:45 — konsisten dengan sweep PDH/PDL yang lazim terjadi setelah pembukaan London.
5. **Konsistensi dengan run setahun**: 8 trade Agustus ini identik dengan baris 2026-08 pada
   artefak tahunan V8T risk-1% (8 entry, 6W/2L) — tidak ada perbedaan sinyal antar-window.

## 4. RISK 2% — KONTEKS & IMPLIKASI

- **Skala**: run setahun V8T risk 2% (artefak terpisah): 146 tr, WR 63,0%, PF 1,25,
  **+$2.584,55 (ROI +25,85%)**, **DD 11,92% ($1.337)**, loss beruntun maks **5**.
  Pada risk 1% angka setahunnya: +$1.392, DD 6,6% → risk 2% mendekati 2× di semua metrik
  (pembulatan lot 0,13 vs 0,07 membuatnya tidak tepat linear).
- **Implikasi DD**: loss beruntun maks 5 × $195 ≈ $975 ≈ **9,75% modal** pada episode terburuk
  setahun — pada risk 1% episode sama hanya ~4,9%. DD 1,96% di Agustus ini kecil karena
  loss beruntun bulan ini hanya 1; **jangan mengekstrapolasi DD bulan santai ke bulan buruk**.
- **Catatan kepatuhan**: instruksi tetap saya catat: rekomendasi riset = risk maks 1%;
  permintaan laporan ini = 2% (keputusan pengguna). Laporan ini bukan rekomendasi naik risk —
  justru menunjukkan trade-off: profit 2×, DD juga ~2×.

## 5. BATAS VALIDITAS (QC, wajib dibaca)

1. **n=8 trade / 1 bulan — tidak signifikan secara statistik.** Interval 95% untuk WR 75%
   pada n=8 sangat lebar (~40–93%). Angka bulanan bisa berubah total bulan berikutnya.
2. **Konteks setahun V8T risk 1%**: 146 tr, WR 63,0%, PF 1,25, +$1.392, DD 6,6%, 8/12 bulan
   hijau — Agustus termasuk bulan baik, bukan rata-rata.
3. **Konteks lintas rezim** (laporan utama rev 2.2): keluarga kaskade PDH/PDL signifikan di
   2025–26 & 2021–22 (Monte-Carlo 32-seed), tetapi **rugi di rezim recovery 2022–23**.
4. Agustus 2026 = rezim tren bull kuat (harga $4.019 → $4.697, +~15%) — kondisi ideal untuk
   varian ini; hasil di rezim ranging belum teruji pada bulan tersebut.

## 6. KESIMPULAN

1. V8T risk 2% pada Agustus 2026: **+$301,26 (ROI +3,01%), WR 75%, PF 1,77, DD 1,96%** —
   bulan hijau dengan eksekusi sepenuhnya pesimis/anti-repaint.
2. Profit ditopang 2 runner besar; 4 win scratch trailing — profil return tidak merata.
3. Untuk keputusan berkelanjutan: patuh **risk maks 1%** (setahun: DD ~6,6% vs 11,9% pada 2%),
   dan evaluasi setelah **forward-test DEMO ≥3 bulan**, bukan dari satu bulan backtest.

## 7. REPRODUCIBILITY

```
# bulan Agustus 2026, risk 2% ($200)
.venv/bin/python research/tuning_mtf.py --start 2026-08-01 --end "2026-08-31 23:59:59" \
    --risk 200 --variants V8T --out reports/backtest_v8t_20260801_20260831_risk200_execm5.txt

# konteks setahun penuh, risk 2%
.venv/bin/python research/tuning_mtf.py --start 2025-09-01 --end "2026-09-01 23:59:59" \
    --risk 200 --variants V8T --out reports/backtest_v8t_20250901_20260901_risk200_execm5.txt
```

Rincian per-trade & ringkasan harian tercantum di bagian bawah artefak
`backtest_v8t_20260801_20260831_risk200_execm5.txt`.
