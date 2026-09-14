# LAPORAN AUDIT FORENSIK — "MAX FAVORABLE" SALAH PERHITUNGAN PIPS

**Tanggal**: 10 Sep 2026 · **Commit**: `0d69d97`
**Pemicu**: laporan user live — *"pada saat running ada perbedaan pips dengan setelah kena SL, di bagian Max Favorable (riwayat transaksi)"*.
**Scope**: seluruh rantai data Max Favorable — tick MT5 → `icas_daemon.py` (tracking `max_fav`) → `src/state_store.py` → jurnal JSONL → `src/dashboard_app.py` (`_stats_from_journal`) → `templates/index.html` (tabel riwayat).
**Hasil**: **6 temuan — 2 HIGH + 2 MEDIUM diperbaiki; 1 terbukti BUKAN bug (beda definisi); 1 keterbatasan terdokumentasi.** Konversi pips diaudit rantai penuh: **konsisten, tidak ada bug konversi** — akarnya adalah *kehilangan data puncak saat koneksi goyah*, bukan salah hitung.

---

## 1. Ringkasan eksekutif

Gejala: banner posisi saat running menampilkan +N pips, tetapi setelah posisi kena SL,
kolom "Max Favorable" di tabel Riwayat Transaksi menampilkan angka lebih kecil
(sering `+0.0`). Audit menemukan bahwa angka pips yang di-*track* daemon **hilang
di tengah jalan** tepat pada skenario koneksi putus-menyambung — bukan salah
konversi. Perbaikan inti: **pemulihan `max_fav` monoton** (puncak tak boleh
turun akibat pemulihan state) + **kolom tabel jujur** (`—` = tak terlacak,
`0.0` = benar-benar nol).

## 2. Rantai data Max Favorable (dengan konversi di tiap hop)

```
tick MT5 (USD)
  └─ daemon: fav_usd = (cur − entry) utk BUY / (entry − cur) utk SELL     [USD]
       max_fav = max(max_fav, fav_usd)                                    [USD]
  └─ state store: snap["max_fav"]                                          [USD]
  └─ jurnal close: max_fav_usd = snap["max_fav"]                           [USD]
  └─ dashboard: max_fav = max_fav_usd × 10                                 [PIPS]
  └─ template: "+{max_fav} pips"
```

Konversi USD→pips terjadi **satu kali** (di dashboard, ×10 — karena 1 pip emas =
$0,10). Verifikasi silang dengan log live user (tiket 5075405797): trailing lock
30 pips × 0,07 lot × $100 = **$21,00 persis** seperti yang direalisasikan →
konversi benar di kedua arah. Yang salah adalah **ketersediaan data**, bukan aritmetika.

## 3. Registry temuan

| ID | Severity | Lokasi | Temuan | Status |
|----|----------|--------|--------|--------|
| MF-01 | **HIGH** | `icas_daemon.py` pemulihan state | Puncak `max_fav` HILANG saat koneksi putus: dict posisi segar ber-`max_fav=0.0`; deals-rebuild tidak meng-infer bila trailing belum bergeser; fallback snapshot memori (benar) TERLEWAT karena rebuild "sukses" | ✅ FIX |
| MF-02 | **HIGH** | `icas_daemon.py` rekonsiliasi startup (close-offline) | Event `position_closed_offline` ditulis TANPA `max_fav_usd`/flag tier — state store memilikinya tapi tidak dibawa | ✅ FIX |
| MF-03 | MEDIUM | `templates/index.html` | Truthy-check `if (e.get("max_fav_usd"))` menganggap `0.0` sebagai "tidak ada" (aman secara kebetulan, kini eksplisit + teruji) | ✅ FIX (eksplisit) |
| MF-04 | MEDIUM | `dashboard_app._stats_from_journal` + template | Event TANPA field max_fav ditampilkan `+0.0 pips` — menyaru sebagai "tidak pernah profit"; kini `None` → `—` (tak terlacak) | ✅ FIX |
| MF-05 | — (bukan bug) | banner vs tabel | Banner running = pips posisi SAAT INI (live tick); tabel = PUNCAK historis sejak entry. Setelah SL harga sudah balik — beda angka itu definisi, bukan bug. Konversi ×10 konsisten di seluruh rantai. | 📄 Didokumentasikan |
| MF-06 | LOW (batas) | sampling daemon | Daemon membaca tick tiap 3 dtk (`POLL_INTERVAL_SECONDS`) — puncak intrabar di antara dua polling bisa terlewat beberapa pips pada statistik (tidak memengaruhi uang: SL/TP dieksekusi broker). | 📄 Batas terdokumentasi |

## 4. MF-01 — akar masalah (walk-through skenario user)

1. Posisi berjalan normal: daemon tiap 3 dtk meng-update `pos["max_fav"]`; snapshot
   disalin ke `open_tickets[ticket]["snapshot"]` tiap siklus; state store ikut
   menyimpan (merge monotonic: `stored_max > pos_max → pakai stored_max`). ✔
2. **Koneksi putus** → `positions_get` gagal/miss → bridge membangun ulang dict
   posisi dengan default `max_fav: 0.0` (`_fresh`).
3. Koneksi pulih → daemon jalur pemulihan:
   - state file: bila siklus `save_position` terakhir gagal (persis saat putus) →
     data basi/kosong → gagal merge;
   - **deals-rebuild SUKSES** → `infer_position_state` hanya bisa meng-infer
     `max_fav` **bila SL sudah bergeser** (dari jarak SL ke entry). Trade user:
     trailing belum sempat aktif → infer `max_fav = 0.0`;
   - fallback snapshot memori (jalur ke-3, yang benar) **tidak pernah dicapai**
     karena jalur deals sudah mengembalikan hasil.
4. Hasil: `max_fav` kembali 0,0 padahal puncak +N pips pernah terjadi; saat posisi
   tutup, `max_fav_usd: 0.0` (atau tanpa field) masuk jurnal → tabel `+0.0`.

Log user yang mengonfirmasi jalur ini: `♻️ State tiket 5075405797 direbuilt dari
riwayat deal: partials=0 (TP1:False …)` — rebuild dari deals, bukan state file.

**FIX (monotonic recovery):** SETELAH blok pemulihan (jalur apa pun), snapshot
memori `open_tickets[t].snapshot.max_fav` selalu di-MAX-kan ke `pos["max_fav"]`
+ log info `📈 max_fav tiket … dipulihkan dari snapshot memori`. Puncak yang sudah
terlihat tidak akan hilang lagi.

## 5. MF-02 — close-offline tanpa data

Rekonsiliasi startup (posisi tutup saat daemon OFF) memanggil `_journal_close`
**tanpa `extra`** — padahal `state_store.get_position(t)` masih memegang snapshot
terakhir (termasuk `max_fav`). FIX: `extra` kini membawa `tp1/2/3_hit`,
`trail_step`, `max_fav_usd` dari state store (dibaca sebelum `mark_closed` yang
memindahkannya ke tombstone).

## 6. MF-03/MF-04 — tampilan jujur

- Parsing dashboard kini `isinstance(max_fav_usd, (int, float))` — `0.0` adalah
  nilai sah (loss lurus), ketiadaan field = `None`.
- Template: `(t.max_fav === null) ? '—' : '+' + t.max_fav + ' pips'` — pembaca
  tidak lagi disesatkan `+0.0` palsu. (Backtest & live-deals lama tanpa field
  juga mendapat `—`.)

## 7. MF-05 — analisis "bukan bug" (penting dibaca)

Dua angka yang user bandingkan itu **berbeda definisi**:

| Tampilan | Definisi |
|---|---|
| Banner "Running Profit" (saat running) | pips posisi **saat ini** terhadap entry (live tick) |
| Kolom "Max Favorable" (setelah close) | **puncak** pips sejak entry s.d. close |

Setelah SL kena, harga sudah berbalik — puncak yang sempat terlihat di banner
memang lebih besar dari posisi akhir. Ditambah MF-01 (puncak hilang), kesan
"salah hitung" makin kuat. Audit konversi rantai penuh: **tidak ditemukan
double-conversion maupun salah faktor** — semua hop memakai USD dan hanya
dikonversi ×10 sekali di presentation layer.

## 8. MF-06 — batas yang tersisa (jujur)

Sampling 3 detik: puncak intrabar M5 antara dua polling bisa terlewat pada
statistik (underestimate beberapa pips). Tidak memengaruhi eksekusi/uang.
Opsi masa depan (tidak diimplementasi): backfill puncak dari OHLC M1/M5 broker
(`copy_rates`) saat konfirmasi tutup — kompleksitas vs manfaat rendah, dicatat
sebagai ide.

## 9. Verifikasi

| Suite | Hasil |
|---|---|
| `verify_dashboard_v3.py` + blok MF (6 cek baru) | **53 PASS / 0 FAIL** |
| — close online `max_fav_usd 5.67` → `56.7 pips` | PASS |
| — close TANPA field → `None` (bukan 0.0 palsu) | PASS |
| — close `max_fav_usd 0.0` asli → tetap `0.0` | PASS |
| — template null-safe (`—`) | PASS |
| — daemon MF-01 (`_snap_max_fav`) & MF-02 (`_st_pos`) ada | PASS |
| `verify_dashboard_v2.py` (regresi) | **24 PASS / 0 FAIL** |
| `py_compile` daemon/dashboard/verify | ✅ |

## 10. Panduan membaca kolom Max Favorable (mulai `0d69d97`)

| Tampilan | Arti |
|---|---|
| `+37.4 pips` | puncak terlacak (benar) |
| `0.0` | posisi tidak pernah profit sama sekali (loss lurus) |
| `—` | puncak tak terlacak (event jurnal tanpa data — mis. histori lama pra-fix) |

Log daemon baru yang mungkin Anda lihat: `📈 max_fav tiket … dipulihkan dari
snapshot memori: $X.XX (N pips)` — informasi normal pasca pemulihan koneksi.

---
*Dokumen terkait: `LAPORAN_AUDIT_DASHBOARD.md` (audit D6-01..D6-11),
`LAPORAN_STRATEGI_G4.md` (strategi & paritas), `verify_dashboard_v3.py` (harness).*
