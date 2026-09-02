"""
================================================================================
AUDIT FORENSIK 2 — PROOF-OF-CONCEPT BUG SAAT ERROR / KONEKSI TERPUTUS
================================================================================
Menjalankan KODE ASLI repo (src/execution/mt5_bridge.py + icas_daemon.py) terhadap
mock MetaTrader5 yang disuntik kegagalan koneksi.

Dijalankan SEBELUM fix untuk membuktikan tiap bug, lalu SESUDAH fix sebagai
regression test.  Gunakan:
    python3 audit_faults/poc_faults.py            # semua skenario
    python3 audit_faults/poc_faults.py 3 4        # skenario tertentu
"""
import sys
import os
import json
import time
import shutil
import types
import datetime
import importlib
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from audit_faults import mock_mt5            # noqa: E402

RESULTS = []

# Nilai unik yang hanya dipakai sleep() di loop utama daemon. _journal_close juga
# memanggil time.sleep(0.7) — dengan sentinel ini sleep retry itu tidak dihitung
# sebagai satu siklus polling (bug harness, bukan bug repo).
POLL_SENTINEL = -777.0


def record(scen, name, ok, detail=""):
    RESULTS.append({"scen": scen, "name": name, "ok": bool(ok), "detail": detail})
    mark = "✅ PASS" if ok else "❌ FAIL"
    print(f"   {mark} - {name}")
    if detail:
        for ln in str(detail).splitlines():
            print(f"          {ln}")


# --------------------------------------------------------------------------- #
class _Stop(Exception):
    pass


def _load_fresh(mock, tmpdir, cfg_overrides=None):
    """Import ulang modul repo dengan mock MT5 terpasang + config terisolasi."""
    sys.modules["MetaTrader5"] = mock
    for mod in list(sys.modules):
        if mod == "config" or mod.startswith("src.") or mod in (
                "icas_daemon", "src", "src.execution", "src.backtest",
                "src.indicators", "src.strategy"):
            del sys.modules[mod]
    import config as cfgmod
    cfg = cfgmod.config
    cfg.SYMBOL = mock.symbol_name
    cfg.STATE_FILE = os.path.join(tmpdir, "state", "icas_state.json")
    cfg.JOURNAL_FILE = os.path.join(tmpdir, "logs", "trade_journal.jsonl")
    cfg.JOURNAL_HEALTH_FILE = os.path.join(tmpdir, "logs", "trade_journal.health.json")
    cfg.JOURNAL_ENABLED = True
    cfg.POLL_INTERVAL_SECONDS = POLL_SENTINEL   # penanda unik utk sleep loop utama
    for k, v in (cfg_overrides or {}).items():
        setattr(cfg, k, v)
    import src.execution.mt5_bridge as br
    importlib.reload(br)
    import icas_daemon
    importlib.reload(icas_daemon)
    return cfgmod, br, icas_daemon


def _read_journal(path):
    evs = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        evs.append(json.loads(ln))
                    except json.JSONDecodeError:
                        evs.append({"event": "_CORRUPT_LINE", "raw": ln})
    return evs


def _run_daemon(icas_daemon, cycles):
    """Jalankan main() daemon sebanyak `cycles` iterasi lalu hentikan."""
    box = {"n": 0}
    real_sleep = time.sleep

    def fake_sleep(s):
        if s != POLL_SENTINEL:          # sleep internal (retry jurnal, dsb.)
            real_sleep(0)
            return
        box["n"] += 1
        if box["n"] > cycles:
            raise _Stop()
        real_sleep(0)

    orig_sleep = icas_daemon.time.sleep
    icas_daemon.time.sleep = fake_sleep
    err = None
    try:
        icas_daemon.main()
    except _Stop:
        pass
    except BaseException as e:                     # termasuk UnboundLocalError
        err = e
    finally:
        icas_daemon.time.sleep = orig_sleep
    return err, box["n"]


# ============================================================================ #
# S-1  Startup crash saat pembacaan posisi pertama gagal (UnboundLocalError)
# ============================================================================ #
def scen_1_startup_crash_on_read_error():
    print("\n[S-1] STARTUP: koneksi putus saat rekonsiliasi on/off")
    mock = mock_mt5.build()
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        # posisi tersimpan di state store dari sesi sebelumnya
        from src.state_store import StateStore
        st = StateStore(cfgmod.config.STATE_FILE)
        st.save_position({"ticket": 7001, "type": "BUY", "volume": 0.33,
                          "initial_volume": 0.33, "price_open": 4600.0,
                          "tp1_hit": True, "tp2_hit": False, "tp3_hit": False,
                          "be_set": True, "max_fav": 20.0, "trail_step": 1})
        # jembatan gagal tepat saat daemon membaca posisi pertama kali
        boom = {"n": 0}
        real = br.IcasMT5Bridge.get_open_position_details

        def flaky(self):
            boom["n"] += 1
            if boom["n"] == 1:
                raise OSError("IPC transport broken")
            return real(self)

        br.IcasMT5Bridge.get_open_position_details = flaky
        err, n = _run_daemon(icas_daemon, cycles=1)
        br.IcasMT5Bridge.get_open_position_details = real

        crashed = isinstance(err, UnboundLocalError) or (
            err is not None and "open_pos_now" in str(err))
        record("S-1", "daemon TIDAK crash UnboundLocalError saat baca posisi gagal",
               not crashed, f"exception={type(err).__name__ if err else None}: {err}")


# ============================================================================ #
# S-2  Startup: koneksi putus -> semua tiket dianggap "closed offline" + state dihapus
# ============================================================================ #
def scen_2_startup_false_offline_close():
    print("\n[S-2] STARTUP: koneksi putus sebentar -> posisi sehat dinyatakan tutup-offline")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4620.00, 4620.26
    # posisi MASIH TERBUKA di broker
    mock.positions = [mock_mt5.Position(ticket=7001, type=0, volume=0.23,
                                        price_open=4600.0, sl=4610.0, tp=0.0,
                                        profit=460.0, magic=777404)]
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        from src.state_store import StateStore
        st = StateStore(cfgmod.config.STATE_FILE)
        st.save_position({"ticket": 7001, "type": "BUY", "volume": 0.23,
                          "initial_volume": 0.33, "price_open": 4600.0,
                          "tp1_hit": True, "tp2_hit": False, "tp3_hit": False,
                          "be_set": True, "max_fav": 20.0, "trail_step": 1})
        del st

        # koneksi putus HANYA saat pembacaan startup
        mock.faults.positions_empty = True
        err, _ = _run_daemon(icas_daemon, cycles=2)
        mock.faults.positions_empty = False

        evs = _read_journal(cfgmod.config.JOURNAL_FILE)
        false_off = [e for e in evs if e.get("event") == "position_closed_offline"
                     and str(e.get("ticket")) == "7001"]
        st2 = StateStore(cfgmod.config.STATE_FILE)
        state_gone = st2.get_position(7001) is None
        record("S-2", "posisi yang masih terbuka TIDAK dicatat closed_offline",
               len(false_off) == 0,
               f"event position_closed_offline utk 7001 = {len(false_off)}")
        record("S-2", "state manajemen (tp1_hit/trail_step) TIDAK dihapus",
               not state_gone,
               f"state 7001 setelah startup = {st2.get_position(7001)}")


# ============================================================================ #
# S-3  Feed mati (tick 0) -> max_fav meledak -> semua TP tier + trailing gila
# ============================================================================ #
def scen_3_zero_tick_sell_explosion():
    print("\n[S-3] KONEKSI: tick bid/ask = 0.0 (feed busuk) pada posisi SELL")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4600.00, 4600.26
    mock.positions = [mock_mt5.Position(ticket=7002, type=1, volume=0.33,
                                        price_open=4600.0, sl=4615.0, tp=0.0,
                                        profit=0.0, magic=777404)]
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        mock.faults.tick_zero = True
        err, _ = _run_daemon(icas_daemon, cycles=2)
        mock.faults.tick_zero = False

        evs = _read_journal(cfgmod.config.JOURNAL_FILE)
        tps = [e for e in evs if e.get("event") == "tp_hit"]
        trails = [e for e in evs if e.get("event") == "trail_update"]
        sent = [r for r in mock.orders_sent if r.get("action") == mock.TRADE_ACTION_DEAL]
        sl_req = [r["sl"] for r in mock.orders_sent if r.get("action") == mock.TRADE_ACTION_SLTP]
        record("S-3", "TIDAK ada partial close TP saat tick = 0",
               len(tps) == 0, f"tp_hit events = {len(tps)} {[e.get('level') for e in tps]}")
        record("S-3", "TIDAK ada order deal terkirim saat tick = 0",
               len(sent) == 0, f"order_send DEAL = {len(sent)}")
        record("S-3", "TIDAK ada permintaan SL ngawur (SL SELL harus < 4600)",
               not any(s > 4600.0 for s in sl_req), f"SL diminta = {sl_req}")
        st = __import__("src.state_store", fromlist=["StateStore"]).StateStore(
            cfgmod.config.STATE_FILE)
        snap = st.get_position(7002) or {}
        record("S-3", "max_fav TIDAK tercemar harga 0 (harus <= jarak wajar)",
               float(snap.get("max_fav", 0.0) or 0.0) < 100.0,
               f"max_fav tersimpan = {snap.get('max_fav')} USD")
        record("S-3", "struktur TP TIDAK rusak permanen (tp1/2/3 & trail_step utuh)",
               not (snap.get("tp1_hit") or snap.get("tp2_hit") or snap.get("tp3_hit"))
               and int(snap.get("trail_step", 0) or 0) == 0,
               f"state tersimpan = tp1={snap.get('tp1_hit')} tp2={snap.get('tp2_hit')} "
               f"tp3={snap.get('tp3_hit')} trail_step={snap.get('trail_step')}")


# ============================================================================ #
# S-4  Feed mati -> spread guard lolos & entry dikirim di harga 0
# ============================================================================ #
def scen_4_zero_tick_entry():
    print("\n[S-4] KONEKSI: feed mati saat sinyal muncul -> spread guard & harga entry")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4600.00, 4600.26
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        bridge = br.IcasMT5Bridge(cfgmod.config)
        bridge.initialize()
        mock.faults.tick_zero = True
        tk = bridge.send_order("BUY", 0.33, 4585.0, None)
        mock.faults.tick_zero = False
        record("S-4", "order DITOLAK saat tick tidak valid (bukan dikirim di harga 0)",
               tk is None, f"ticket dikembalikan = {tk}, orders_sent = {len(mock.orders_sent)}")


# ============================================================================ #
# S-5  Miss transien mid-loop -> false close + state wipe -> TP1 dobel
#          (reproduksi persis tiket produksi 4987805272 / 4988300823)
# ============================================================================ #
def scen_5_duplicate_tp1_after_false_close():
    print("\n[S-5] KONEKSI: 5x miss beruntun mid-loop -> posisi 'tutup' palsu -> TP1 dobel")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4620.00, 4620.26
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        # posisi BUY 0.33 lot, entry 4600, SL 4585
        mock.positions = [mock_mt5.Position(ticket=7003, type=0, volume=0.33,
                                            price_open=4600.0, sl=4585.0, tp=0.0,
                                            profit=0.0, magic=777404)]
        mock.deals = [mock_mt5.Deal(ticket=1, position_id=7003, type=0, entry=0,
                                    volume=0.33, price=4600.0, profit=0.0,
                                    commission=0.0, swap=0.0, time=1767000000,
                                    symbol=mock.symbol_name, comment="Model Icas Scalper")]
        # skrip pasar per siklus daemon
        script = [
            dict(bid=4620.00, ask=4620.26),                        # 1: TP1 (+200p) -> close 0.10
            dict(bid=4620.00, ask=4620.26),                        # 2: stabil
            dict(positions_empty=True),                            # 3..7: miss 5x
            dict(positions_empty=True),
            dict(positions_empty=True),
            dict(positions_empty=True),
            dict(positions_empty=True),
            dict(bid=4620.00, ask=4620.26, history_raises=True),   # 8: posisi terlihat lagi
            dict(bid=4620.00, ask=4620.26, history_raises=True),   # 9: -> TP1 menembak lagi?
        ]
        state = {"i": 0}
        real_tick = mock.symbol_info_tick

        def scripted_tick(sym):
            return real_tick(sym)

        mock.symbol_info_tick = scripted_tick

        box = {"n": 0}
        real_sleep = time.sleep

        def fake_sleep(s):
            if s != POLL_SENTINEL:
                real_sleep(0)
                return
            box["n"] += 1
            i = box["n"] - 1
            mock.faults.reset()
            if i < len(script):
                step = script[i]
                mock.faults.positions_empty = step.get("positions_empty", False)
                mock.faults.history_raises = step.get("history_raises", False)
                if "bid" in step:
                    mock.bid, mock.ask = step["bid"], step["ask"]
            if box["n"] > len(script):
                raise _Stop()
            real_sleep(0)

        orig = icas_daemon.time.sleep
        icas_daemon.time.sleep = fake_sleep
        try:
            icas_daemon.main()
        except _Stop:
            pass
        except BaseException as e:
            print("   (daemon exception:", type(e).__name__, e, ")")
        finally:
            icas_daemon.time.sleep = orig

        evs = _read_journal(cfgmod.config.JOURNAL_FILE)
        tp1 = [e for e in evs if e.get("event") == "tp_hit" and e.get("level") == 1]
        closes = [e for e in evs if e.get("event", "").startswith("position_closed")]
        partials = [d for d in mock.deals if d.entry == mock.DEAL_ENTRY_OUT]
        record("S-5", "TP1 hanya dieksekusi SATU kali meski ada miss 5x",
               len(tp1) == 1, f"tp_hit L1 events = {len(tp1)} "
                              f"close_vol = {[e.get('close_vol') for e in tp1]}")
        record("S-5", "broker hanya menerima SATU partial close",
               len(partials) == 1, f"deal OUT di broker = {len(partials)} "
                                   f"volume = {[d.volume for d in partials]}")
        record("S-5", "posisi TIDAK dinyatakan tutup saat masih terbuka",
               len(closes) == 0, f"position_closed events = {len(closes)}")


# ============================================================================ #
# S-6  order_send None sesudah order benar-benar dieksekusi -> partial dobel
# ============================================================================ #
def scen_6_lost_ack_double_partial():
    print("\n[S-6] KONEKSI: order_send mengembalikan None PADAHAL partial sudah filled")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4620.00, 4620.26
    mock.positions = [mock_mt5.Position(ticket=7004, type=0, volume=0.33,
                                        price_open=4600.0, sl=4585.0, tp=0.0,
                                        profit=0.0, magic=777404)]
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        bridge = br.IcasMT5Bridge(cfgmod.config)
        bridge.initialize()
        bridge.active_position = {"ticket": 7004}

        # daemon memanggil close_partial(..., tier=N) — kunci idempotensinya per tier
        mock.faults.send_drop_next = 1          # kirim pertama: filled tapi ack hilang
        ok1 = bridge.close_partial(7004, 0.10, tier=1)
        ok2 = bridge.close_partial(7004, 0.10, tier=1)   # retry oleh daemon
        partials = [d for d in mock.deals if d.entry == mock.DEAL_ENTRY_OUT]
        record("S-6", "retry TIDAK menambah partial close kedua (max 1x utk 1 tier)",
               len(partials) == 1,
               f"ack1={ok1} ack2={ok2} | deal OUT broker = {len(partials)} "
               f"vol = {[d.volume for d in partials]} | sisa posisi = "
               f"{[p.volume for p in mock.positions]}")
        # dan daemon memang mengirim tier
        src = open(os.path.join(ROOT, "icas_daemon.py"), encoding="utf-8").read()
        n_tier = src.count("close_partial(pos[\"ticket\"], close_vol, tier=")
        record("S-6", "daemon mengirim kunci tier utk SEMUA tier TP (1/2/3)",
               n_tier == 3, f"pemanggilan close_partial(..., tier=) = {n_tier} (harus 3)")


# ============================================================================ #
# S-7  Exception di tengah siklus -> daemon mati total
# ============================================================================ #
def scen_7_exception_kills_daemon():
    print("\n[S-7] KETANGGUHAN: satu exception transien mematikan seluruh daemon")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4620.00, 4620.26
    mock.positions = [mock_mt5.Position(ticket=7005, type=0, volume=0.33,
                                        price_open=4600.0, sl=4585.0, tp=0.0,
                                        profit=0.0, magic=777404)]
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        calls = {"n": 0}
        real = br.IcasMT5Bridge.get_current_tick

        def spiky(self):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("transient IPC error")
            return real(self)

        br.IcasMT5Bridge.get_current_tick = spiky
        err, n = _run_daemon(icas_daemon, cycles=10)
        br.IcasMT5Bridge.get_current_tick = real
        record("S-7", "daemon BERTAHAN setelah exception transien (lanjut poll)",
               err is None and n >= 10,
               f"exception={type(err).__name__ if err else None}: {err} | siklus={n}")


# ============================================================================ #
# S-8  Jurnal gagal tulis -> daemon harus tetap jalan & melapor
# ============================================================================ #
def scen_8_journal_write_failure():
    print("\n[S-8] JURNAL: direktori jurnal tidak bisa ditulis")
    mock = mock_mt5.build()
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        from src.execution.trade_journal import TradeJournal
        path = os.path.join(tmp, "logs", "j.jsonl")
        j = TradeJournal(path, True, "test")
        j.log("engine_start", x=1)                       # tulis pertama: sukses
        assert os.path.exists(path)
        import builtins
        real_open = builtins.open

        def bad_open(*a, **kw):
            if str(a[0]).endswith("j.jsonl"):
                raise OSError(28, "No space left on device")
            return real_open(*a, **kw)

        builtins.open = bad_open
        raised = False
        try:
            for _ in range(5):
                j.log("tp_hit", level=1)
        except BaseException:
            raised = True
        finally:
            builtins.open = real_open
        record("S-8", "TradeJournal tidak melempar exception saat tulis gagal",
               not raised, f"raised={raised}")
        # kegagalan tulis TIDAK boleh senyap total -> harus ada counter/status
        record("S-8", "kegagalan tulis jurnal TERHITUNG (tidak senyap)",
               int(getattr(j, "error_count", 0) or 0) >= 5,
               f"error_count={getattr(j, 'error_count', 'TIDAK ADA')} "
               f"-> operator tidak akan pernah tahu jurnalnya mati")


# ============================================================================ #
# S-9  Tutup posisi lama tak sempat dicatat karena posisi baru muncul duluan
# ============================================================================ #
def scen_9_orphan_close_event():
    print("\n[S-9] JURNAL: tiket lama ditutup di saat yang sama posisi baru terbuka")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4620.00, 4620.26
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        mock.positions = [mock_mt5.Position(ticket=7006, type=0, volume=0.33,
                                            price_open=4600.0, sl=4585.0, tp=0.0,
                                            profit=0.0, magic=777404)]
        mock.deals = [mock_mt5.Deal(ticket=1, position_id=7006, type=0, entry=0,
                                    volume=0.33, price=4600.0, profit=0.0,
                                    commission=0.0, swap=0.0, time=1767000000,
                                    symbol=mock.symbol_name, comment="Model Icas Scalper")]
        box = {"n": 0}
        real_sleep = time.sleep

        def fake_sleep(s):
            if s != POLL_SENTINEL:
                real_sleep(0)
                return
            box["n"] += 1
            mock.faults.reset()
            if box["n"] == 1:
                pass                                    # posisi 7006 terlihat
            elif box["n"] <= 3:
                mock.faults.positions_empty = True       # miss 2x
            elif box["n"] == 4:
                # posisi lama benar-benar tutup, posisi BARU terbuka
                mock.positions = [mock_mt5.Position(
                    ticket=7007, type=1, volume=0.33, price_open=4610.0,
                    sl=4625.0, tp=0.0, profit=0.0, magic=777404)]
                mock.deals = list(mock.deals) + [mock_mt5.Deal(
                    ticket=2, position_id=7006, type=1, entry=mock.DEAL_ENTRY_OUT,
                    volume=0.33, price=4585.0, profit=-495.0, commission=0.0,
                    swap=0.0, time=1767000010, symbol=mock.symbol_name,
                    comment="sl 4585.00")]
            if box["n"] > 8:
                raise _Stop()
            real_sleep(0)

        orig = icas_daemon.time.sleep
        icas_daemon.time.sleep = fake_sleep
        try:
            icas_daemon.main()
        except _Stop:
            pass
        except BaseException as e:
            print("   (daemon exception:", type(e).__name__, e, ")")
        finally:
            icas_daemon.time.sleep = orig

        evs = _read_journal(cfgmod.config.JOURNAL_FILE)
        closed_7006 = [e for e in evs if e.get("event", "").startswith("position_closed")
                       and str(e.get("ticket")) == "7006"]
        record("S-9", "penutupan tiket 7006 TETAP tercatat walau posisi baru muncul",
               len(closed_7006) >= 1,
               f"event close utk 7006 = {len(closed_7006)}")



# ============================================================================ #
# S-10 INTEGRASI: siklus hidup penuh TP1->(putus koneksi)->TP2->TP3->trailing->tutup
# ============================================================================ #
def scen_10_full_lifecycle_with_outage():
    print("\n[S-10] INTEGRASI: TP1 -> koneksi putus -> TP2 -> TP3 -> trailing -> tutup")
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4610.00, 4610.26
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(mock, tmp)
        ENTRY, SL, LOT = 4600.00, 4585.00, 0.33
        mock.positions = [mock_mt5.Position(ticket=7010, type=0, volume=LOT,
                                            price_open=ENTRY, sl=SL, tp=0.0,
                                            profit=0.0, magic=777404)]
        mock.deals = [mock_mt5.Deal(ticket=1, position_id=7010, type=0, entry=0,
                                    volume=LOT, price=ENTRY, profit=0.0, commission=0.0,
                                    swap=0.0, time=int(time.time()), symbol=mock.symbol_name,
                                    comment="Model Icas Scalper")]

        def _close_all(price):
            """Broker menutup sisa posisi (kena SL/trailing)."""
            p0 = mock.positions[0]
            mock.deals.append(mock_mt5.Deal(
                ticket=99, position_id=7010, type=1, entry=mock.DEAL_ENTRY_OUT,
                volume=p0.volume, price=price,
                profit=round((price - ENTRY) * p0.volume * 100.0, 2),
                commission=0.0, swap=0.0, time=int(time.time()),
                symbol=mock.symbol_name, comment="sl 4673.00"))
            mock.positions = []

        # skrip harga/gangguan per siklus
        def apply_step(i):
            mock.faults.reset()
            if i == 0:                                     # belum ada TP
                mock.bid, mock.ask = 4610.00, 4610.26
            elif i == 1:                                   # TP1 (+200 pips)
                mock.bid, mock.ask = 4620.00, 4620.26
            elif 2 <= i <= 6:                              # koneksi putus 5 siklus
                mock.faults.positions_empty = True
                mock.bid, mock.ask = 4620.00, 4620.26
            elif i == 7:                                   # pulih, harga lanjut naik
                mock.bid, mock.ask = 4622.00, 4622.26
            elif i == 8:                                   # TP2 (+400 pips)
                mock.bid, mock.ask = 4640.00, 4640.26
            elif i == 9:                                   # TP3 (+600 pips)
                mock.bid, mock.ask = 4660.00, 4660.26
            elif i == 10:                                  # trailing runner
                mock.bid, mock.ask = 4680.00, 4680.26
            elif i == 11:
                _close_all(4673.00)                        # SL trailing tersentuh
                mock.bid, mock.ask = 4673.00, 4673.26

        N = 20
        box = {"n": 0}
        real_sleep = time.sleep

        def fake_sleep(s):
            if s != POLL_SENTINEL:
                real_sleep(0)
                return
            i = box["n"]
            box["n"] += 1
            if i < N:
                apply_step(i)
            else:
                mock.faults.reset()
            if box["n"] > N:
                raise _Stop()
            real_sleep(0)

        orig = icas_daemon.time.sleep
        icas_daemon.time.sleep = fake_sleep
        try:
            icas_daemon.main()
        except _Stop:
            pass
        except BaseException as e:
            print("   (daemon exception:", type(e).__name__, e, ")")
        finally:
            icas_daemon.time.sleep = orig

        evs = _read_journal(cfgmod.config.JOURNAL_FILE)
        tps = [e for e in evs if e.get("event") == "tp_hit"]
        levels = sorted(e.get("level") for e in tps)
        closes = [e for e in evs if e.get("event", "").startswith("position_closed")]
        trails = [e for e in evs if e.get("event") == "trail_update"]
        revives = [e for e in evs if e.get("event") == "position_revived"]
        unconf = [e for e in evs if e.get("event") == "close_unconfirmed"]
        partials = [d for d in mock.deals if d.entry == mock.DEAL_ENTRY_OUT]
        daemon_partials = [d for d in partials if "Partial TP" in (d.comment or "")]

        record("S-10", "TP1/TP2/TP3 masing-masing TEPAT SATU kali",
               levels == [1, 2, 3], f"level tp_hit = {levels}")
        record("S-10", "broker menerima tepat 3 partial close dari daemon",
               len(daemon_partials) == 3,
               f"volume = {[d.volume for d in daemon_partials]} "
               f"(harus [0.1, 0.08, 0.08])")
        record("S-10", "posisi ditutup & dicatat SATU kali dengan PnL",
               len(closes) == 1 and isinstance(closes[0].get("realized_total"), (int, float)),
               f"closes={len(closes)} realized={closes[0].get('realized_total') if closes else None}")
        record("S-10", "trailing runner tetap berjalan",
               len(trails) >= 1, f"trail_update = {len(trails)} step={[e.get('step') for e in trails]}")
        record("S-10", "gangguan 5 siklus terdeteksi sebagai 'belum terbukti tutup'",
               len(unconf) >= 1 and len(closes) == 1,
               f"close_unconfirmed={len(unconf)} revive={len(revives)}")
        record("S-10", "state akhir: semua tier hit & trail_step > 0",
               bool(closes and closes[0].get("tp1_hit") and closes[0].get("tp2_hit")
                    and closes[0].get("tp3_hit") and int(closes[0].get("trail_step") or 0) >= 1),
               f"snapshot tutup = {json.dumps({k: closes[0].get(k) for k in ('tp1_hit','tp2_hit','tp3_hit','trail_step')}) if closes else None}")



# ============================================================================ #
# S-11 MUTEX: tiket lama menunggu konfirmasi -> entry baru HARUS ditahan
#             + KONTROL NEGATIF: gate dilepas -> order memang lolos (uji bergigi)
# ============================================================================ #
def _run_s11(max_pending):
    """Jalankan skenario S-11, kembalikan (jumlah send_order, jumlah order_open)."""
    mock = mock_mt5.build()
    mock.bid, mock.ask = 4620.00, 4620.26
    with tempfile.TemporaryDirectory() as tmp:
        cfgmod, br, icas_daemon = _load_fresh(
            mock, tmp, cfg_overrides={"MAX_PENDING_CLOSE_SECONDS": max_pending})
        mock.positions = [mock_mt5.Position(ticket=7011, type=0, volume=0.33,
                                            price_open=4600.0, sl=4585.0, tp=0.0,
                                            profit=0.0, magic=777404)]
        mock.deals = [mock_mt5.Deal(ticket=1, position_id=7011, type=0, entry=0,
                                    volume=0.33, price=4600.0, profit=0.0, commission=0.0,
                                    swap=0.0, time=int(time.time()), symbol=mock.symbol_name,
                                    comment="Model Icas Scalper")]
        attempts = []
        real_send = br.IcasMT5Bridge.send_order

        def spy_send(self, *a, **kw):
            attempts.append(a)
            return real_send(self, *a, **kw)

        br.IcasMT5Bridge.send_order = spy_send

        # PAKSA sinyal selalu ada — tanpa ini uji bisa lolos hanya karena kebetulan
        # tidak ada setup di bar tersebut (uji kosong tidak membuktikan apa pun).
        from src.strategy.icas_strategy import ModelIcasStrategy, IcasSignal
        real_eval = ModelIcasStrategy.evaluate_m5_setup

        def always_signal(self, df, idx, bal, spread_usd=0.0):
            return IcasSignal(type="BUY", entry_price=4620.0, stop_loss=4605.0,
                              early_be_price=0.0, tp1_price=4638.75, tp2_price=4657.5,
                              tp3_price=4676.25, lot_size=0.33, risk_amount=500.0,
                              reason="forced by S-11")

        ModelIcasStrategy.evaluate_m5_setup = always_signal

        box = {"n": 0}
        real_sleep = time.sleep

        def fake_sleep(s):
            if s != POLL_SENTINEL:
                real_sleep(0)
                return
            i = box["n"]
            box["n"] += 1
            mock.faults.reset()
            if 1 <= i <= 2:                      # posisi hilang: menunggu konfirmasi
                mock.faults.positions_empty = True
            if box["n"] > 3:
                raise _Stop()
            real_sleep(0)

        orig = icas_daemon.time.sleep
        icas_daemon.time.sleep = fake_sleep
        try:
            icas_daemon.main()
        except _Stop:
            pass
        except BaseException as e:
            print("   (daemon exception:", type(e).__name__, e, ")")
        finally:
            icas_daemon.time.sleep = orig
            br.IcasMT5Bridge.send_order = real_send
            ModelIcasStrategy.evaluate_m5_setup = real_eval

        evs = _read_journal(cfgmod.config.JOURNAL_FILE)
        n_open = len([e for e in evs if e.get("event") == "order_open"])
        n_pos = len(mock.positions)
        return len(attempts), n_open, n_pos


def scen_11_mutex_holds_while_pending():
    print("\n[S-11] MUTEX: tiket lama belum pasti tutup -> posisi kedua dilarang")
    a_fixed, o_fixed, p_fixed = _run_s11(max_pending=900)      # gate AKTIF
    a_ctrl, o_ctrl, p_ctrl = _run_s11(max_pending=-1)          # gate DILEPAS (kontrol)
    record("S-11", "KONTROL: dengan gate dilepas, order baru MEMANG lolos "
                   "(bukti uji ini tidak kosong)",
           a_ctrl >= 1 and o_ctrl >= 1,
           f"kontrol -> send_order={a_ctrl}x order_open={o_ctrl} posisi={p_ctrl}")
    record("S-11", "dengan gate aktif, TIDAK ada order baru saat tiket lama menunggu",
           a_fixed == 0 and o_fixed == 0,
           f"fixed -> send_order={a_fixed}x order_open={o_fixed}")
    record("S-11", "tidak ada posisi kedua di broker",
           p_fixed == 1, f"posisi di broker = {p_fixed} (harus 1)")


# ============================================================================ #
def main():
    scens = {1: scen_1_startup_crash_on_read_error,
             2: scen_2_startup_false_offline_close,
             3: scen_3_zero_tick_sell_explosion,
             4: scen_4_zero_tick_entry,
             5: scen_5_duplicate_tp1_after_false_close,
             6: scen_6_lost_ack_double_partial,
             7: scen_7_exception_kills_daemon,
             8: scen_8_journal_write_failure,
             9: scen_9_orphan_close_event,
             10: scen_10_full_lifecycle_with_outage,
             11: scen_11_mutex_holds_while_pending}
    only = [int(a) for a in sys.argv[1:]] or list(scens)
    import logging
    logging.disable(logging.CRITICAL)
    print("=" * 78)
    print(" POC AUDIT FORENSIK 2 — BUG SAAT ERROR / KONEKSI TERPUTUS")
    print("=" * 78)
    for i in only:
        try:
            scens[i]()
        except Exception:
            print(f"   ⚠️ skenario {i} error harness:")
            traceback.print_exc()
    npass = sum(1 for r in RESULTS if r["ok"])
    nfail = len(RESULTS) - npass
    print("\n" + "=" * 78)
    print(f" HASIL: {npass} PASS / {nfail} FAIL   (total {len(RESULTS)} assertion)")
    print("=" * 78)
    if nfail:
        print("\nRINCIAN YANG GAGAL:")
        for r in RESULTS:
            if not r["ok"]:
                print(f"  [{r['scen']}] {r['name']}\n        {r['detail']}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
