# LAPORAN AUDIT FORENSIK DASHBOARD — `run_dashboard.py` (rev 1)

**Tanggal**: 09 Sep 2026 · **Auditor**: QC/QA pipeline (Arena Agent Mode)
**Scope**: `run_dashboard.py` → `src/dashboard_app.py` → `templates/index.html`,
beserta permukaan yang disentuhnya: `src/execution/mt5_bridge.py` (read-only),
jurnal JSONL daemon, `state/icas_state.json`, marker kesehatan jurnal.
**Metodologi**: pembacaan statis baris-per-baris + Flask test client +
PoC proses nyata (venv tanpa dependensi) + regresi `verify_dashboard_v2.py`.
**Hasil**: **11 temuan (4 HIGH / 5 MEDIUM / 2 LOW) — semua DIPERBAIKI**;
verifikasi `verify_dashboard_v3.py` **40 PASS / 0 FAIL**; regresi v2 **24 PASS / 0 FAIL**.

---

## 1. Ringkasan eksekutif

Dashboard adalah satu-satunya jendela observasi user saat bot jalan 24/5 —
bug di sini bukan "tampilan saja": satu crash runner (D6-01) membuat user
fresh-clone **tidak bisa membuka dashboard sama sekali**, dan dua bug
metrik (D6-02, D6-04) menampilkan angka **yang salah tentang uang**.
Temuan terparah sekaligus paling mungkin terjadi: `python run_dashboard.py`
di venv baru langsung crash karena urutan import yang salah, dan fitur
auto-install yang seharusnya menyelamatkan justru **dead code** — terbukti
direproduksi persis di sandbox (§D6-01).

Konteks G4: dashboard juga belum menyadari bahwa strategi sudah berganti
(D6-11) dan status spread memakai guard lama yang **kontradiktif** dengan
guard entry live G4 (D6-03).

---

## 2. Registry temuan

| ID | Severity | Lokasi | Temuan singkat | Status |
|----|----------|--------|----------------|--------|
| D6-01 | **HIGH** | `run_dashboard.py` | Import `src.dashboard_app` di level modul, **sebelum** `ensure_dependencies()` → venv baru crash `ModuleNotFoundError: flask`, auto-install dead code. `icasbot --dashboard` tertular sama. | ✅ FIX |
| D6-02 | **HIGH** | `dashboard_app.api_status` | `daily_trades_count` dibaca dari instance `ModelIcasStrategy` **proses dashboard sendiri** → selalu 0 (daemon = proses lain). Field API menyesatkan. | ✅ FIX |
| D6-03 | **HIGH** | `api_status.spread_status` | Status spread dibanding points vs `MAX_SPREAD_POINTS=350` legacy, padahal guard entry live = `MAX_SPREAD_USD=$1.20`. 2-digit 130 pts ($1.30) dilabel "NORMAL" padahal bot **menolak entry**; 3-digit 300 pts ($0.30) berisiko dilabel "TINGGI" padahal aman. | ✅ FIX |
| D6-04 | **HIGH** | `templates/index.html` | "Breakeven Rate" & "Non-Loss Rate" dihitung JS dari `be_activations` (FLAG per-trade: trade bisa WIN *dan* be_set) bukan klasifikasi hasil → rasio dobel-hitung, Non-Loss bisa menembus >100%. | ✅ FIX |
| D6-05 | MEDIUM | `get_backtest_summary` | Kegagalan `engine.run` (CSV korup/hilang) **tidak di-negative-cache** → backtest penuh diulang tiap poll `/api/stats` (5 dtk) = CPU burn tanpa henti. | ✅ FIX |
| D6-06 | MEDIUM | `run_server` | Werkzeug default **single-thread** → satu request lambat (feed stall) membekukan seluruh UI (4 polling loop antre). | ✅ FIX |
| D6-07 | MEDIUM | `api_status` jam server | Offset manual `config.SERVER_TIME_OFFSET_HOURS` (harus diubah user 2×/tahun saat DST) — tidak sinkron dengan daemon G4 yang memakai tz-database Europe/Athens. | ✅ FIX |
| D6-08 | MEDIUM | `api_status` posisi aktif | Tick mati (bid/ask 0) tetap dipakai menghitung fav/pnl → banner menampilkan **−$151.818** (0,33 lot × $4.600) saat feed putus. Kelas bug yang sama dengan F-04 daemon. | ✅ FIX |
| D6-09 | LOW | `run_dashboard.py` | Pesan gagal install menyarankan `pip install MetaTrader5` — tidak relevan untuk dashboard (paket MT5 tidak dibutuhkan). | ✅ FIX |
| D6-10 | LOW | `templates/index.html` | Placeholder hardcoded (login `88921045`, leverage `1:2000`) tampil sebelum fetch pertama; render `innerHTML` tanpa escape untuk teks jurnal (hardening XSS). | ✅ FIX |
| D6-11 | MEDIUM | API + template | Dashboard **buta strategi**: tidak mengekspos `STRATEGY`/parameter kaskade G4; panel sesi/killzone hanya relevan ICAS. | ✅ FIX |

---

## 3. Detail temuan & bukti

### D6-01 — Runner crash di venv baru (auto-install dead code) 【HIGH】

**Kode lama** (`run_dashboard.py`):
```python
def ensure_dependencies(): ...          # dipanggil di main()
from src.dashboard_app import run_server  # ← LINE 30, LEVEL MODUL — EKSEKUSI SAAT IMPORT
def main():
    ensure_dependencies()               # ← terlambat: import di atas sudah crash
```
`src.dashboard_app` meng-import flask/pandas/numpy di top-level. **PoC PRE-FIX**
(venv bersih tanpa flask — kondisi persis fresh-clone user):
```
$ python run_dashboard.py
ModuleNotFoundError: No module named 'flask'
  File "run_dashboard.py", line 30, in <module>
    from src.dashboard_app import run_server
```
Fitur "auto-detects missing dependencies and provides instant fixes" **tidak
pernah berjalan** — dan `icasbot --dashboard` (`from run_dashboard import main`)
mati di titik yang sama.

**Fix**: import berat dipindah ke dalam `main()`, setelah `ensure_dependencies()`
(urutan: cek deps → install bila perlu → baru import). **PoC POST-FIX** (venv
yang sama, tanpa flask): runner mencetak `MODUL DIPERLUKAN BELUM TERPASANG:
flask` → `pip install -r requirements.txt` otomatis (flask 3.1.3 + requests
ter-install) → banner dashboard muncul → server bind & `/api/status` merespons
200. Terverifikasi juga via AST test: level modul `run_dashboard` kini hanya
meng-import `sys/os/subprocess`.

### D6-02 — `daily_trades_count` selalu 0 【HIGH】

Dashboard dan daemon adalah **dua proses OS berbeda**. `strategy_engine =
ModelIcasStrategy(config)` di dashboard membuat counter sendiri (0) —
counter daemon tidak pernah terlihat. Field API `daily_trades_count`
selalu 0 berapa pun trade yang terjadi. **Fix**: instance dihapus; nilai
diambil dari **jurnal daemon** (`order_open` hari ini, `journal_summary()
→ orders_today` — sumber kebenaran lintas proses yang sama dengan D-05).
Test: fixture jurnal 2 `order_open` hari ini + 1 tahun 2020 → API
mengembalikan **2**.

### D6-03 — Status spread kontradiktif dengan guard entry 【HIGH】

Guard entry live (`send_order`) sejak G4 membandingkan **USD**
(`MAX_SPREAD_USD=$1.20`), tapi label dashboard membanding points mentah vs
`MAX_SPREAD_POINTS=350` (legacy ICAS). Dua arah kesalahan terbukti test
client: 2-digit **130 pts = $1.30** → bot menolak entry, dashboard bilang
"NORMAL (Aman) ✅"; 3-digit **300 pts = $0.30** → jauh di bawah guard,
label lama bisa bilang "TINGGI". **Fix**: label dihitung dari
`spread_usd = points × price_point` vs `MAX_SPREAD_USD` (+ payload
`max_spread_usd`); template menampilkan badge **SPREAD: $x.xx** live
dengan warna status. Fallback ke points hanya bila `MAX_SPREAD_USD`
tidak dikonfigurasi.

### D6-04 — Rasio BE/Non-Loss dihitung dari flag yang salah 【HIGH】

JS lama: `beRate = be_activations/total`, `nonLoss = (wins +
be_activations)/total`. `be_activations` = jumlah trade yang **flag**-nya
`be_set` — sebuah trade bisa **WIN sekaligus be_set** → terhitung dua kali.
Skenario test (3 trade: WIN+$100 be_set, LOSS−$100 be_set, BE+$0.50):
label lama menampilkan **Non-Loss 100%** (1W + 2 flag dari 3), nilai benar
**66.67%** (1W + 1BE). **Fix**: server menyediakan `be_rate`/`non_loss_rate`
berbasis klasifikasi hasil (jurnal sejak D-03 sudah punya; live-deals
ditambah; JS memakai nilai server, fallback aman bila field absen). Test:
be_rate 33.33 / non_loss 66.67 PASS.

### D6-05 — Backtest gagal diulang tanpa henti 【MEDIUM】

Bila `engine.run` raise (CSV korup dsb.), handler men-set cache kosong —
`if _cached_stats:` false → **setiap poll /api/stats menjalankan ulang
backtest penuh**. Dengan poll 5 detik = CPU burn permanen + UI lag.
**Fix**: flag `_backtest_failed` (positive-cache tetap: sukses tetap
di-cache selamanya). Test: engine monkeypatched raise → panggilan ke-2
tidak menjalankan engine (`total run == 1`) PASS.

### D6-06 — Server single-thread 【MEDIUM】

`app.run(debug=False)` → werkzeug melayani request satu-per-satu. `/api/status`
membaca jurnal (2MB tail) + tick MT5; saat feed stall, request bisa detikan —
4 polling loop (2/5/8 detik) antre dan **seluruh dashboard tampak mati**.
**Fix**: `threaded=True` (dipastikan via capture kwargs) PASS.

### D6-07 — Jam server tidak sinkron dengan daemon G4 【MEDIUM】

Lama: `7 - config.SERVER_TIME_OFFSET_HOURS` (manual, rawan salah saat DST —
Exness EET/EEST berubah 2×/tahun) sedangkan daemon G4 memakai
`Europe/Athens` tz-database. **Fix**: `zoneinfo.ZoneInfo("Europe/Athens")`
(sama persis dengan `frames_from_raw`), fallback ke rumus lama bila
zoneinfo tak tersedia. Test: jam API == jam Athens sekarang PASS.

### D6-08 — PnL raksasa saat feed mati 【MEDIUM】

`cur_price = tick["bid"]` tanpa cek validitas → tick mati (bid=0) menghasilkan
`fav = −$4.600`, `pnl = −$151.800` (0.33 lot) di banner posisi — persis kelas
bug F-04 yang diperbaiki di daemon tapi terlewat di dashboard. **Fix**: tick
invalid/zero → `fav_pips`/`pnl_usd`/`current_price` = `null` + `feed_valid:
false` + `feed_reason`; JS null-safe menampilkan "FEED MATI (alasan)".
Test client dengan tick `{bid:0, valid:false}` + posisi fake PASS
(pnl `null`, bukan −$151k).

### D6-09 — Pesan install menyesatkan 【LOW】

Saran `pip install MetaTrader5` pada failure path dashboard dihapus
(dashboard berjalan penuh tanpa paket MT5 — mode simulasi bridge).

### D6-10 — Placeholder & XSS-hardening 【LOW】

`88921045`/`Exness-MT5Trial6`/`1:2000` hardcoded tampil ±2 detik sebelum
fetch pertama (dan menyesatkan bila feed lambat) → diganti "…". Semua teks
dari jurnal/broker yang dirender via `innerHTML` kini lewat `esc()`
(feed jurnal, kolom waktu/tipe tabel trade).

### D6-11 — Dashboard buta strategi G4 【MEDIUM】

Setelah switch G4, dashboard tidak menunjukkan strategi aktif & parameternya.
**Fix**: `/api/status` mengekspos `strategy` + `g4` (sweep 288 / FVG $0.30 /
EMA200 / min 260 bar) + `max_spread_usd`; template menambah **badge
STRATEGY: G4**, panel **Kaskade Sinyal G4 (L1-L4 + guard spread)** yang
hanya tampil saat `strategy === 'G4'` (rollback ICAS otomatis menyembunyikan),
dan badge spread live (§D6-03). Smoke test live: `/api/status` →
`strategy: G4`, `g4: {sweep_bars: 288, fvg_buffer_usd: 0.3, h1_ema_span: 200,
min_h1_bars: 260}`.

---

## 4. Bukti verifikasi

| Suite | Hasil |
|---|---|
| `verify_dashboard_v3.py` (baru — menutup D6-01..D6-11 + regresi field lama) | **40 PASS / 0 FAIL** |
| `verify_dashboard_v2.py` (regresi D-01..D-05 lama) | **24 PASS / 0 FAIL** |
| PoC proses nyata D6-01: PRE-FIX crash vs POST-FIX auto-install + server 200 | ✅ |
| Smoke live server: banner, security warning, `/api/status` (G4), `/` HTML | ✅ |
| `py_compile`: run_dashboard.py, dashboard_app.py, verify_dashboard_v3.py | ✅ |
| `run_qa.py` suite standar | + baris `verify_dashboard_v3.py` (0 FAIL) |

`verify_dashboard_v3.py` memakai Flask **test client** + monkeypatch terkontrol
(tick 2/3-digit, feed mati, engine raise, `app.run` capture) — jurnal asli
di-backup & dipulihkan otomatis (`*.verify_backup`), tidak menyentuh MT5.

---

## 5. Yang TIDAK diubah (dicatat, risiko rendah)

1. **Label "Waktu (Server)"** di tabel trade memakai `ts` mesin lokal daemon
   (bukan waktu broker) — konvensi jurnal sejak awal; mengubah = mengubah
   kontrak jurnal.
2. **Threshold WIN live-deals** ($10) vs jurnal ($1) — konvensi klasifikasi
   per sumber; sumber selalu dilabel eksplisit (D-03).
3. **`_journal_events` tail 2MB** — event yang lebih tua dari 2MB tidak masuk
   ringkasan; ukuran cukup untuk ±berhari-hari event (heartbeat ringkas).
4. **Token compare non-constant-time** (`!=`) — ancaman timing praktis nol
   untuk dashboard lokal/LAN; noted untuk hardening berikutnya.

## 6. Batas validitas

- Semua fix adalah **lapisan observasi/telemetri** — jalur trading
  (`icas_daemon.py`, bridge `send_order`, strategi G4) **tidak tersentuh**;
  tidak ada regresi risiko eksekusi.
- Pengujian perilaku live penuh (MT5 nyata, multi-poll berjam-jam) tidak
  dapat disimulasikan penuh di sandbox; yang diverifikasi adalah kontrak API
  + PoC proses. Dashboard live mengikuti konfigurasi & jurnal yang sama.

---
*Dokumen terkait: `LAPORAN_AUDIT_FORENSIK_3.md` (daemon), `TATA_CARA_G4.md`
(operasional), `verify_dashboard_v3.py` (harness), commit ini.*
