# 🕵️ LAPORAN AUDIT FORENSIK #3 — `model_icas_bot_FIX`

**Repo:** `Dypoi/jurnalicas` → `jurnalicas/model_icas_bot_FIX`
**Branch audit:** `arena/01a080b1-jurnalicas` (basis `main` @ `2855d4e`)
**Tanggal audit:** 8 September 2026
**Fokus yang Anda minta:** *audit forensik GitHub + perbaiki bug jika ditemukan, dengan perhatian khusus bug yang muncul saat error / koneksi terputus pada saat trading journal berjalan*
**Metode:** audit statik independen seluruh 40 file Python (membaca ulang semua perbaikan audit 1–2 dengan mata "baru" — perbaikan bisa mengandung bug baru) + analisis forensik ulang 442 event jurnal produksi + **3 skenario fault-injection baru** (total 14 skenario / 36 assertion) + regresi penuh seluruh gerbang QA.

---

## 1. RINGKASAN EKSEKUTIF

| Kategori | Hasil |
|---|---|
| File diaudit | 40 file Python (kompilasi ✅ semua lolos) |
| **Bug baru ditemukan** | **6** (2 Tinggi, 3 Sedang, 1 Rendah) + 3 temuan kosmetik/minor |
| **Bug yang sudah diperbaiki** | **6 / 6** (+3 minor) — semuanya langsung di-commit di branch ini |
| Bukti perbaikan | ✅ 3 skenario PoC baru dengan **kontrol negatif** (S-12/S-13/S-14) |
| Gerbang QA pasca-fix | ✅ **8 PASS / 0 FAIL** (`python3 run_qa.py`) |
| Uji kegagalan koneksi | ✅ **36 PASS / 0 FAIL** — 14 skenario (sebelumnya 11/27) |
| Verifikasi dashboard | ✅ **24 PASS / 0 FAIL** (sebelumnya 21) |
| Regresi backtest | ✅ **NOL** — smoke test identik pra/pasca fix (443 trade, final $17.409,80) |

**Kesimpulan utama:** Perbaikan audit-2 memang menutup 17 bug yang lama, tetapi audit independen ini menemukan **6 lubang baru** yang semuanya terletak persis di skenario yang Anda khawatirkan — *bot dalam kondisi error/koneksi setengah mati*. Dua yang paling berbahaya: **(1)** saat candle live gagal diambil, bot diam-diam beralih ke CSV repo yang berhenti di 13 Juli 2026 (harga ~$4.011 vs pasar ~$4.600) dan bisa mengirim order live berdasarkan pasar 2 bulan lalu; **(2)** restart bot bersamaan dengan MT5 yang belum selesai sinkron membuka celah posisi ganda karena tiket "tertunda" tidak memegang mutex. Keduanya kini tertutup dan dibuktikan dengan PoC bergigi (kontrol negatif menunjukkan bug memang terjadi bila gate dilepas).

---

## 2. KONTEKS — MENGAPA AUDIT KETIGA DIPERLUKAN

Audit #1 (25 Agu) menemukan 14 bug (termasuk root cause error 10016 Anda). Audit #2 (2 Sep) menemukan 17 bug kegagalan koneksi (termasuk TP1 dobel di tiket 4987805272). Keduanya sudah memperbaiki semua temuannya.

Prinsip QC yang jujur: **setiap perbaikan besar adalah kode baru, dan kode baru adalah calon bug baru.** Audit ini sengaja tidak mempercayai klaim laporan sebelumnya, melainkan:

1. Membaca ulang baris-per-baris seluruh jalur eksekusi yang menyentuh **jurnal trading**, **state**, **mutex**, dan **pemulihan pasca-putus koneksi**;
2. Menelusuri skenario komposit yang belum pernah diuji (restart + feed setengah sehat + daftar posisi belum sync — gabungan tiga kondisi yang masing-masing "sudah diuji" tapi **kombinasinya belum**);
3. Memverifikasi ulang jurnal produksi Anda (442 event, 26 Agu – 2 Sep) untuk memastikan tidak ada pola kerusakan baru pasca-fix.

**Hasil forensik jurnal produksi:** seluruh kerusakan data (TP1 dobel, close palsu, event hilang) terjadi pada 27 Agu — **sebelum** perbaikan audit-2 dideploy. Setelah 2 Sep (kode fix), tidak ada aktivitas trading baru di jurnal repo ini, jadi tidak ada bukti kerusakan baru — dan memang audit ini menemukan bahwa **jalur-jalur komposit di bawah ini masih terbuka** hingga hari ini.

Anomali jurnal yang terkonfirmasi ulang (semuanya sudah dijelaskan audit-2, tidak ada pola baru):
- 2 tiket dengan `position_closed` tanpa `realized_total` → keduanya akhirnya mendapat event close ber-PnL (nasib baik, bukan jaminan — lihat temuan A3-03);
- 4× `loop_stall_warning` (terlama 50,0 menit) — siklus daemon membeku karena panggilan IPC MT5 menggantung; SL broker tetap aktif tapi manajemen TP/trailing mati selama itu;
- 2 sesi `engine_start` tanpa `engine_stop` berpasangan (listrik mati / kill paksa) — ditangani rekonsiliasi startup.

---

## 3. TEMUAN UTAMA (peringkat severity)

### 🟠 [A3-01] TINGGI — Candle live gagal → bot memakai CSV statis 2-bulan-lalu sebagai sumber sinyal

- **File:** `src/execution/mt5_bridge.py :: get_latest_m5_candles`
- **Akar:** Ketika `copy_rates_from_pos()` gagal (terminal baru dinyalakan & chart belum ke-load, koneksi broker goyah, history belum sync), fungsi **jatuh diam-diam** ke `data/historical/xauusd_m5.csv` — file repo yang berhenti di **2026-07-13 19:20, harga terakhir $4.011,21** (pasar Anda saat ini ~$4.600+).
- **Rantai kejadian:**
  1. Koneksi M1/M5 chart terputus sesaat (tick MASIH valid — sering terjadi);
  2. `copy_rates_from_pos` → `None` → fallback CSV basi;
  3. Daemon melihat bar "terakhir yang selesai" = **13 Juli** → `latest_time != last_scanned_bar_time` → dievaluasi **sekali** per sesi gangguan;
  4. Bila bar Juli itu membentuk setup (sweep+displacement pada harga $4.011), sinyal dianggap valid → `send_order` dieksekusi di **harga live $4.6xx** dengan SL/TP/sizing dihitung dari **harga Juli** → order live sungguhan berdasarkan pasar yang sudah tidak ada, risk-reward nyatanya acak.
- **Dampak nyata:** entry ngawur saat tepat kondisi "error/koneksi terputus" yang Anda sebut. Dashboard `/api/candles` juga menampilkan chart 2 bulan lalu tanpa peringatan.
- **Perbaikan:** mode LIVE yang gagal mengambil candle kini mengembalikan DataFrame **kosong** (siklus di-skip, aman) + log warning; `copy_rates_from_pos` dibungkus try/except (IPC exception tidak lagi meledak ke `cycle_error`); fallback CSV hanya berlaku untuk mode simulasi (paket MetaTrader5 tidak terpasang — jalur demo `START_ENGINE_DEMO.bat` tidak berubah).
- **Bukti (S-12, dengan kontrol negatif):**
```
KONTROL: candle hidup  -> send_order=1x order_open=1 posisi=1   ← jalur scan terbukti hidup
FIX    : candle mati  -> send_order=0x order_open=0 posisi=0   ← sinyal DILEWATI, bukan dari CSV basi
```

### 🟠 [A3-02] TINGGI — Restart saat terminal belum sync → mutex bolong → POSISI GANDA

- **File:** `icas_daemon.py` (blok rekonsiliasi startup) + `src/execution/mt5_bridge.py :: send_order`
- **Akar:** Audit-2 (F-07/T-04) membuat tiket yang *terlihat lalu hilang* memegang mutex via `open_tickets`. Tetapi tiket yang statusnya **tertunda sejak startup** (rekonsiliasi ditunda karena feed tidak sehat / status tiket tidak pasti / riwayat tak terbaca / bukti volume belum lunas) **tidak pernah dimasukkan** ke `open_tickets`. Skenario komposit yang lolos:
  1. Anda menyalakan MT5 + bot hampir bersamaan (atau bot start saat koneksi baru pulih);
  2. Startup: `account_info()` masih error → rekonsiliasi DITUNDA → tiket lama (masih hidup di broker!) tidak dilacak;
  3. Beberapa detik kemudian tick sudah hidup & valid, **tetapi daftar posisi terminal belum sync** → `positions_get()` mengembalikan `()` ;
  4. Daemon: `pos = None`, `open_tickets` kosong, `_blocking` kosong → **boleh entry**;
  5. `send_order` → mutex internalnya juga membaca `positions_get()` = kosong → **lolos** → **posisi kedua terbuka padahal posisi pertama masih hidup** → eksposur margin 2× tanpa manajemen ganda.
- **Dampak nyata:** dobel eksposur tepat pada momen restart/laptop on-off — kebiasaan trading Anda yang tercatat di jurnal (6× engine_start dalam 7 hari).
- **Perbaikan (2 lapis):**
  1. **`_defer_ticket()`** — setiap tiket yang penutupannya belum TERBUKTI (keempat cabang tunda di rekonsiliasi startup) kini memegang mutex entry: masuk `open_tickets` dengan `pending_since`, dibatasi katup pengaman `MAX_PENDING_CLOSE_SECONDS` (900 dtk) agar bot tidak macet selamanya. Bila posisinya ternyata masih hidup dan akhirnya terlihat → diadopsi normal; bila benar-benar tutup → dikonfirmasi dengan bukti riwayat broker seperti biasa.
  2. **`send_order()` menolak order bila `positions_get()` mengembalikan `None`** (IPC error) — "status posisi tidak diketahui" tidak lagi dianggap "tidak ada posisi". Ini memperkuat pertahanan terakhir di level bridge.
- **Bukti (S-13, dengan kontrol negatif — kontrol memakai kode fix dengan state dikosongkan):**
```
KONTROL: tanpa state tersimpan -> send_order=1x order_open=1 posisi=2  ← DOBEL POSISI di broker terbukti
FIX    : dengan tiket tertunda -> send_order=0x order_open=0 posisi=1  ← hanya posisi lama, entry ditahan
```

### 🟡 [A3-03] SEDANG — PnL penutupan yang gagal dibaca hilang PERMANEN dari jurnal

- **File:** `icas_daemon.py :: _journal_close`
- **Akar:** Konfirmasi penutupan butuh dua pembacaan riwayat berbeda: `get_position_closed_volume()` (bukti lunas) lalu `get_position_realized()` (PnL). Bila yang pertama berhasil tapi yang kedua gagal (riwayat broker flaky tepat setelah koneksi pulih — persis momen rawan), event `position_closed` tertulis **tanpa `realized_total`** dan tiket langsung di-tombstone → **tidak pernah dikunjungi lagi**. PF / net profit / stop-rule Anda di `journal_report` dan dashboard diam-diam salah selamanya.
- **Bukti kemungkinan nyata di jurnal Anda:** 2 event close tanpa `realized_total` (27 Agu) — keduanya kebetulan mendapat event close berikutnya ber-PnL karena posisinya "hidup lagi" akibat bug TP1 dobel. Tanpa bug itu, PnL-nya hilang permanen.
- **Perbaikan:** antrean **PnL backfill** — tiket yang tutup tanpa PnL dicoba ulang tiap `JOURNAL_PNL_BACKFILL_INTERVAL_SECONDS` (default 30 dtk, maks 120 percobaan ≈ 1 jam); begitu riwayat terbaca, event baru **`position_closed_pnl_backfill`** ditulis berisi `realized_total`/`result`/`deals_out`. Dashboard (`journal_summary`, `_stats_from_journal`) dan `research/journal_report.py` menggabungkannya (sumber terakhir per tiket menang). Bila tetap gagal setelah batas, dicatat eksplisit `position_closed_pnl_missing` — tidak pernah senyap.
- **Bukti (S-14):**
```
TP1 tepat 1x ✓ | close event = 1 (tanpa PnL, riwayat flaky) ✓
backfill = [-30.0]  ← +200 (TP1 0.10 lot) − 230 (sisa 0.23 lot kena SL) ✓ | PnL missing permanen = 0 ✓
```

### 🟡 [A3-04] SEDANG — Dashboard SELALU menampilkan badge TP/BE/trailing "pending" untuk posisi aktif

- **File:** `src/dashboard_app.py :: api_status`
- **Akar:** Dashboard proses terpisah; bridge-nya sendiri tidak pernah merge `StateStore`, sehingga dict posisi aktif selalu lahir dengan `tp1_hit=False, be_set=False, trail_step=0`. Panel posisi aktif menampilkan "TP1 PENDING" padahal TP1 sudah dieksekusi — menyesatkan justru saat sesi on/off laptop ketika Anda paling butuh tahu status manajemen posisi.
- **Perbaikan:** dashboard membaca snapshot `state/icas_state.json` (read-only + retry 3×) dan mengambil flag `tp1/2/3_hit`, `be_set`, `trail_step` dari sana — sumber kebenaran yang ditulis daemon tiap siklus. Verifikasi: 3 assertion baru di `verify_dashboard_v2.py` (B2) — hijau.

### 🟡 [A3-05] SEDANG (Windows) — `os.replace` state bisa kena sharing violation lintas proses → state gagal tersimpan

- **File:** `src/state_store.py :: _flush`, `icas_daemon.py :: _write_health_marker`
- **Akar:** Di Windows, `os.replace(tmp, state.json)` melempar `PermissionError` bila proses lain (dashboard yang kini membaca state — lihat A3-04 — editor, antivirus, backup) membuka file tujuan pada pecahan detik yang sama. Konsekuensinya berantai: `save_position` raise → `cycle_error` → **state tidak tersimpan** → bila daemon crash/listrik mati setelahnya, flag TP hilang → **risiko TP1 dobel (bug produksi 27 Agu) bangkit kembali**.
- **Perbaikan:** retry `os.replace` 3× (backoff 50/100/150 ms) di `_flush` dan `_write_health_marker`; pembaca state di dashboard juga retry. Setelah retry habis, error tetap dilempar (terlihat sebagai `cycle_error` di jurnal — tidak pernah senyap) dan `_last_serialized` tidak diperbarui sehingga siklus berikutnya otomatis mencoba menyimpan ulang.

### 🔵 [A3-06] RENDAH–SEDANG — Jurnal tidak pernah `fsync` → event terakhir hilang saat power loss

- **File:** `src/execution/trade_journal.py :: log`
- **Akar:** `f.flush()` hanya mendorong data ke OS. Saat power loss / hard-crash (bukan shutdown normal), buffer OS belum tentu sampai disk — dan yang paling mungkin hilang justru **event terakhir: `tp_hit` / `position_closed`** — data paling berharga untuk audit. Ironisnya `StateStore` sudah diberi fsync (F-14) sedangkan jurnal yang menjadi "buku besar" tidak.
- **Perbaikan:** flag config `JOURNAL_FSYNC=True` (default) — `os.fsync` per event. Biaya ~ms pada frekuensi tulis jauh di bawah 1 event/detik; set `False` bila Anda menulis ke disk sangat lambat.

### 🔵 Minor / kosmetik (juga diperbaiki)

| ID | Temuan | Perbaikan |
|---|---|---|
| A3-07 | `icas_daemon.py`: bila hanya `consecutive_losses > 0` (count=0) yang dipulihkan saat restart, `current_date` tetap `None` → `reset_daily_stats_if_new_day()` di siklus pertama **menghapus circuit breaker yang baru dipulihkan** | `current_date` diset setiap kali ada state harian yang dipulihkan |
| A3-08 | Label backtest basi `(1:1 / +20p)` di `run_backtest.py` & `test_new_icas_tp_be.py` padahal config 187.5/375/562.5p (rekomendasi audit-2 yang belum dikerjakan) | Label kini dinamis dari config |
| A3-09 | `_stats_from_journal`: event `tp_hit` tanpa `level` membuat kunci `tpNone` | Guard `level in (1,2,3)` |

---

## 4. YANG DIPERIKSA DAN DINYATAKAN SEHAT (tidak berubah)

Mutex 1-sinyal-1-posisi jalur normal · gerbang bukti broker F-02/F-03 (5× miss + bukti volume) · tombstone/revive F-03 · guard feed F-04 (tick 0/basi) · idempotensi partial close per tier F-05 · `RESILIENT_CYCLE` F-06 · pelacakan multi-tiket F-07 · guard 10016 berlapis (stops level + sisi pasar + clearance) · filter magic number · fallback filling FOK/IOC/RETURN · normalisasi lot/price digit-aware · polling candle tertutup `len-2` (anti-repaint) · rotasi jurnal F-15 · dedup PnL per tiket di dashboard (D-06) · level sesi point-in-time (F-18) · smoke backtest **identik bitwise** pra/pasca perbaikan ini (443 trade / $17.409,80).

**Catatan desain yang SENGAJA tidak diubah** (dinilai aman / trade-off sadar, agar Anda tahu):
1. `infer_position_state` bisa *overcount* partial (mis. `tp3_hit=True` padahal baru 2) hanya bila `is_ticket_open` mengembalikan `None` pada saat rebuild — bias arah ini **aman** (menghalangi eksekusi ulang TP, bukan mendorong dobel). Arah sebaliknya (undercount) yang berbahaya, dan sudah dicegah.
2. Bila katup `MAX_PENDING_CLOSE_SECONDS` (900 dtk) tercapai lalu posisi kedua terbuka, daemon hanya **mengelola `bot_positions[0]`** — posisi lain tetap dijaga SL broker tapi tanpa manajemen TP tier. Ini batas arsitektur 1-posisi-aktif yang diwarisi dari desain awal (lihat rekomendasi §8).
3. Guard umur tick memakai jam lokal; laptop dengan jam meleset 2–24 jam ke belakang akan membuat feed dianggap basi terus (fail-safe: bot diam, SL broker tetap aktif). Sinkronisasi waktu Windows menutup ini di praktik.

---

## 5. FORENSIK JURNAL PRODUKSI (442 event, 26 Agu – 2 Sep 2026)

Diverifikasi ulang end-to-end dengan `research/journal_report.py` versi baru (kini memahami `position_closed_pnl_backfill`):

| Metrik | Nilai |
|---|---|
| Trade tertutup ber-PnL | 21 / 21 tiket (tidak ada PnL bolong permanen di data yang ada) |
| Profit Factor | 0,78 · Net **−$1.306,66** · ekspektasi −$62,22/trade |
| Non-Loss Rate | 42,9% (9 W / 12 L) |
| Durasi hold | median 1,5 jam · maks 50,9 jam |
| Gap equity terbesar | 2.735 menit (29→31 Agu) & 2.140 menit (31 Agu→2 Sep) — daemon/laptop OFF |
| Loop stall | 4× (371 dtk, 1.712 dtk, 2.999 dtk, dst.) |
| Start/stop | 6 start / 4 stop bersih + 2 kill paksa |

Seluruh kerusakan struktural (TP1 dobel 4987805272 & 4988300823, close palsu 4986226687) terjadi 27 Agu dengan kode lama. Angka PF 0,78 itu **tercemar bug** (0,19 lot ditutup prematur, trail_step hilang) — penilaian jujur strategi tetap menunggu ≥30 trade dengan kode bersih, sesuai stop-rule Anda sendiri.

---

## 6. VERIFIKASI — APA YANG DIJALANKAN & HASILNYA

```
$ python3 run_qa.py
[1] Kompilasi 40 file Python        : ✅ semua lolos
[✅] Unit: audit ICAS                : 7 tests OK
[✅] Unit: BE+ 15 pips               : 2 tests OK
[✅] Verif: persistensi state        : 14 PASS / 0 FAIL
[✅] Verif: fix 10016                : PASS
[✅] Verif: dashboard v2             : 24 PASS / 0 FAIL   (+3 assertion baru A3-03/A3-04)
[✅] Verif: parity engine            : SKIP eksplisit (engine legacy tidak ada) — exit 0
[✅] POC : kegagalan koneksi         : 36 PASS / 0 FAIL   (14 skenario; +3 baru: S-12/13/14)
[5] Smoke backtest engine            : ✅ trades=443 final=$17,409.80  (identik pra-fix)

HASIL AKHIR: 8 PASS / 0 FAIL / 0 SKIP
```

Matriks skenario fault-injection baru (kode asli repo vs mock MT5):

| # | Skenario | Tanpa fix | Dengan fix |
|---|---|---|---|
| S-12 | Candle live gagal + sinyal dipaksa | ❌ order terkirim dari data Juli (kontrol membuktikan jalur hidup) | ✅ 0 order, 0 posisi |
| S-13 | Restart + terminal belum sync + sinyal dipaksa | ❌ **2 posisi terbuka bersamaan di broker** (kontrol) | ✅ 1 posisi, entry tertahan mutex tiket tertunda |
| S-14 | TP1 → SL → riwayat flaky saat konfirmasi tutup | ❌ close tanpa PnL → hilang permanen | ✅ `position_closed_pnl_backfill` realized −$30,00 tepat |

Regresi skenario lama S-1…S-11: **semua tetap hijau** (27/27) — perbaikan baru tidak merusak perlindungan lama.

---

## 7. PERUBAHAN FILE

```
 12 file diubah | +607 baris | −41 baris

 M  config.py                          +15  flag JOURNAL_FSYNC + PnL backfill (A3-03/A3-06)
 M  icas_daemon.py                     +117 _defer_ticket mutex (A3-02a), PnL backfill (A3-03),
                                        retry health marker (A3-05), restore current_date (A3-07)
 M  src/execution/mt5_bridge.py        +47  guard candle basi (A3-01), mutex None-guard send_order (A3-02b)
 M  src/execution/trade_journal.py     +13  fsync opsi (A3-06) + dok event backfill
 M  src/state_store.py                 +19  retry os.replace (A3-05)
 M  src/dashboard_app.py               +58  konsumsi backfill (A3-03), flag posisi aktif dari state (A3-04)
 M  research/journal_report.py         +10  konsumsi backfill (A3-03)
 M  audit_faults/mock_mt5.py           +34  fault rates_none + history_success_budget + candle M5 live
 M  audit_faults/poc_faults.py        +264  S-12 / S-13 / S-14 (+ kontrol negatif)
 M  verify_dashboard_v2.py             +54  uji backfill + uji merge flag state (B2)
 M  run_backtest.py                    +10  label dinamis (A3-08)
 M  test_new_icas_tp_be.py             +9   label dinamis (A3-08) + import config
```

### Konfigurasi baru (`config.py`, semua punya default aman)

| Flag | Default | Fungsi |
|---|---|---|
| `JOURNAL_FSYNC` | `True` | fsync tiap event jurnal (tahan power-loss) |
| `JOURNAL_PNL_BACKFILL_INTERVAL_SECONDS` | `30` | 0 = tiap siklus; negatif = nonaktif |
| `JOURNAL_PNL_BACKFILL_MAX_ATTEMPTS` | `120` | ±1 jam sebelum dinyatakan `pnl_missing` |

### Event jurnal baru

`position_closed_pnl_backfill` (PnL penutupan berhasil direkonstruksi) · `position_closed_pnl_missing` (pernyataan eksplisit setelah batas percobaan — tidak pernah senyap).

---

## 8. REKOMENDASI TINDAK LANJUT (belum dikerjakan — keputusan Anda)

1. **[Prioritas] Uji lapangan yang menyasar temuan ini.** Di akun demo, dengan posisi terbuka: (a) matikan koneksi internet 2–5 menit → pastikan muncul `feed_invalid`/`close_unconfirmed` dan **tidak ada** `tp_hit` ganda; (b) nyalakan MT5 + bot bersamaan persis setelah posisi terbuka → pastikan di log muncul `🔒 Tiket … menahan mutex entry` dan tidak ada order baru 15 menit pertama; (c) cabut internet tepat saat TP1 tereksekusi → pastikan `position_closed_pnl_backfill` muncul setelah koneksi pulih.
2. **Manajemen multi-posisi** (batas arsitektur §4.2): bila katup 900 dtk pernah dilepas dan 2 posisi hidup bersamaan, hanya satu yang dikelola penuh. Opsi: loop manajemen untuk semua `bot_positions`, ATAU turunkan `MAX_PENDING_CLOSE_SECONDS` — bila Anda lebih takut dobel eksposur daripada bot diam.
3. **Heartbeat eksternal** (Telegram/email) saat `feed_invalid` > N menit atau `loop_stall_warning` — supaya Anda tahu laptop/daemon mati dalam hitungan menit, bukan 46 jam.
4. **Amankan dashboard** bila di-bind `0.0.0.0`: set `ICAS_DASH_TOKEN` (sudah didukung, tinggal dipakai).
5. Tetap **DEMO** sampai ≥30 trade bersih; PF live 0,78 Anda adalah angka tercemar bug — jalankan ulang observasi dengan kode ini sebelum menilai strategi.

---

## 9. CARA MENJALANKAN ULANG SENDIRI

```bash
cd jurnalicas/model_icas_bot_FIX

python3 run_qa.py                       # seluruh gerbang (8 PASS)
python3 audit_faults/poc_faults.py      # 14 skenario kegagalan koneksi (36 assertion)
python3 audit_faults/poc_faults.py 13   # hanya uji mutex restart (S-13)
python3 audit_faults/poc_faults.py 14   # hanya uji PnL backfill (S-14)
python3 research/journal_report.py      # observasi jurnal (kini paham event backfill)
```

> Di sandbox ini dependensi dipasang di `/home/user/jurnalicas/.venv` (pandas 3.0.5, numpy 2.4.6, flask 3.1.3). Di mesin Windows Anda: `pip install -r requirements.txt` cukup.

---

## 10. BATASAN AUDIT (kejujuran metodologi)

1. **Tidak ada terminal MetaTrader5 sungguhan di sandbox ini** (Linux). Semua uji eksekusi memakai mock yang memodelkan retcode, stops-level, filling mode, dan riwayat deal — kini termasuk 10 mode kegagalan. Perilaku broker nyata bisa berbeda di detail.
2. Skenario komposit diuji dengan *fault sequencing* per siklus; realitas bisa menggabungkan kegagalan dengan urutan yang belum dicover.
3. Verifikasi lapangan (§8.1) tetap wajib sebelum akun real — khususnya perilaku `positions_get()` Exness pada 1–2 menit pertama setelah terminal start, asumsi kunci dari fix A3-02.

---

**Ditulis oleh:** agent QA/quant pada Arena.ai Agent Mode
**Status:** 6/6 temuan tinggi-sedang + 3 minor sudah diperbaiki, terverifikasi di mock (36/36 assertion), regresi nol pada backtest. Belum diverifikasi terhadap terminal MT5 nyata — jalankan checklist §8.1 di demo dulu.
