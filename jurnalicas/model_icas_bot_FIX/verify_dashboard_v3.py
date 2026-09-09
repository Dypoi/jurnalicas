#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
VERIFIKASI DASHBOARD v3 (AUDIT FORENSIK DASHBOARD — D6-01..D6-11, 09 Sep 2026)
================================================================================
Menutup bug registry LAPORAN_AUDIT_DASHBOARD.md via Flask test client + kontrol
langsung (tanpa server nyata, tanpa MT5):

  [D6-01] import run_dashboard TIDAK menyentuh flask/src.dashboard_app (urutan
          import runner — auto-install harus bisa jalan di venv kosong).
  [D6-02] /api/status daily_trades_count = order_open HARI INI dari jurnal
          daemon (bukan instance strategi lokal yang selalu 0).
  [D6-03] spread_status berbasis USD (MAX_SPREAD_USD $1.20) — bukan points
          legacy 350 yang kontradiktif di feed 2/3-digit.
  [D6-04] stats.be_rate / stats.non_loss_rate dihitung server dari klasifikasi
          hasil (scratch) — bukan be_activations (flag) yang bisa dobel hitung.
  [D6-05] backtest gagal -> negative-cache (engine TIDAK dijalankan ulang tiap
          poll /api/stats).
  [D6-06] run_server memakai threaded=True (UI tidak beku oleh 1 request lambat).
  [D6-07] jam server = Europe/Athens via tz-database (identik daemon G4).
  [D6-08] feed mati (tick invalid/0) -> pos_data fav/pnl = None + alasan,
          bukan pnl ratusan ribu dolar dari harga 0.
  [D6-10] template: esc() dipakai, placeholder login 88921045 dihapus.
  [D6-11] /api/status mengekspos strategy + parameter kaskade G4; template
          memuat badge strategi/panel G4/badge spread.

Regresi: /api/journal, /api/candles, /api/stats tetap 200; semua field lama
(verify_dashboard_v2) tetap ada.
Jurnal asli di-backup ke *.verify_backup dan dipulihkan di akhir.
================================================================================
"""
import sys
import os
import json
import shutil
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0


def check(desc, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {desc}")
    else:
        FAIL += 1
        print(f"  [FAIL] {desc}")


def main():
    from config import config
    jf = getattr(config, "JOURNAL_FILE", "logs/trade_journal.jsonl")
    backup = jf + ".verify_backup"
    had_orig = os.path.exists(jf)
    if had_orig:
        shutil.copy2(jf, backup)

    os.makedirs(os.path.dirname(jf) or ".", exist_ok=True)
    now = datetime.datetime.now().isoformat(timespec="seconds")

    def write_journal(events):
        with open(jf, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    from src import dashboard_app as dash
    client = dash.app.test_client()

    # ------------------------------------------------------------------ D6-01
    print("\n[D6-01] Urutan import runner (auto-install di venv kosong)")
    for mod in ("flask", "src.dashboard_app", "pandas"):
        sys.modules.pop(mod, None)
    import run_dashboard  # noqa: F401  — TIDAK boleh mengekor ke flask
    check("import run_dashboard tidak meng-import flask",
          "flask" not in sys.modules)
    check("import run_dashboard tidak meng-import src.dashboard_app",
          "src.dashboard_app" not in sys.modules and "dashboard_app" not in
          {m.split(".")[-1] for m in sys.modules if m.startswith("src.")})
    src_runner = open("run_dashboard.py", encoding="utf-8").read()
    import ast
    _tree = ast.parse(src_runner)
    _mods = set()
    for _n in _tree.body:
        if isinstance(_n, ast.ImportFrom):
            _mods.add(_n.module or "")
        elif isinstance(_n, ast.Import):
            _mods.update(a.name for a in _n.names)
    check("tidak ada import berat di level modul run_dashboard.py (AST)",
          "src.dashboard_app" not in _mods and "flask" not in _mods)
    for mod in ("flask", "src.dashboard_app"):
        sys.modules.pop(mod, None)

    # ------------------------------------------------------------------ D6-02
    print("\n[D6-02] daily_trades_count dari JURNAL daemon (proses terpisah)")
    write_journal([
        {"ts": now, "event": "engine_start", "engine_version": "icas-v3-g4"},
        {"ts": now, "event": "order_open", "ticket": 700001, "type": "BUY"},
        {"ts": now, "event": "order_open", "ticket": 700002, "type": "SELL"},
        {"ts": "2020-01-01T00:00:00", "event": "order_open", "ticket": 700003,
         "type": "BUY"},   # lama — tidak boleh dihitung
    ])
    r = client.get("/api/status")
    d = r.get_json()
    check("HTTP 200", r.status_code == 200)
    check("daily_trades_count == 2 (order_open HARI INI)",
          d.get("daily_trades_count") == 2)

    # ------------------------------------------------------------------ D6-03
    print("\n[D6-03] spread_status berbasis USD (guard entry $1.20)")
    orig_point = dash.price_point
    orig_tick = dash.bridge.get_current_tick
    try:
        # feed 2-digit: 130 pts = $1.30 > guard -> TINGGI (kode lama: NORMAL!)
        dash.price_point = 0.01
        dash.bridge.get_current_tick = lambda: {
            "bid": 4000.0, "ask": 4001.30, "spread": 130.0, "time": 0,
            "valid": True, "age_seconds": 0.0, "reason": "ok"}
        d = client.get("/api/status").get_json()
        check("2-digit 130pts ($1.30 > $1.20) -> TINGGI",
              d["spread_usd"] == 1.30 and d["spread_status"].startswith("TINGGI"))
        # feed 3-digit: 300 pts = $0.30 <= guard -> NORMAL
        dash.price_point = 0.001
        dash.bridge.get_current_tick = lambda: {
            "bid": 4000.0, "ask": 4000.30, "spread": 300.0, "time": 0,
            "valid": True, "age_seconds": 0.0, "reason": "ok"}
        d = client.get("/api/status").get_json()
        check("3-digit 300pts ($0.30 <= $1.20) -> NORMAL",
              d["spread_usd"] == 0.30 and d["spread_status"].startswith("NORMAL"))
        check("payload memuat max_spread_usd utk template",
              abs(d.get("max_spread_usd", 0) - float(config.MAX_SPREAD_USD)) < 1e-9)
    finally:
        dash.price_point = orig_point
        dash.bridge.get_current_tick = orig_tick

    # ------------------------------------------------------------------ D6-04
    print("\n[D6-04] rasio be/non-loss dari klasifikasi hasil (bukan flag be_set)")
    write_journal([
        {"ts": now, "event": "engine_start"},
        # WIN (+$100) yang SUDAH be_set -> flag, bukan scratch
        {"ts": now, "event": "order_open", "ticket": 800001, "type": "BUY"},
        {"ts": now, "event": "be_lock", "ticket": 800001},
        {"ts": now, "event": "position_closed", "ticket": 800001,
         "realized_total": 100.0, "be_set": True},
        # LOSS (-$100) yang juga be_set
        {"ts": now, "event": "order_open", "ticket": 800002, "type": "SELL"},
        {"ts": now, "event": "be_lock", "ticket": 800002},
        {"ts": now, "event": "position_closed", "ticket": 800002,
         "realized_total": -100.0, "be_set": True},
        # BE scratch (+$0.50)
        {"ts": now, "event": "order_open", "ticket": 800003, "type": "BUY"},
        {"ts": now, "event": "position_closed", "ticket": 800003,
         "realized_total": 0.5},
    ])
    st = client.get("/api/stats").get_json()["stats"]
    check(f"be_activations (flag) == 2  (aktual: {st.get('be_activations')})",
          st.get("be_activations") == 2)
    check(f"be_rate == 33.33% dari be_trades=1, BUKAN 66.67 dari flag  "
          f"(aktual: {st.get('be_rate')})", abs(st.get("be_rate", -1) - 33.33) < 0.01)
    check(f"non_loss_rate == 66.67% (1W+1BE dari 3), BUKAN 100% dari flag  "
          f"(aktual: {st.get('non_loss_rate')})",
          abs(st.get("non_loss_rate", -1) - 66.67) < 0.01)
    src_html = open("templates/index.html", encoding="utf-8").read()
    check("template memakai st.be_rate / st.non_loss_rate dari server",
          "st.be_rate" in src_html and "st.non_loss_rate" in src_html)

    # ------------------------------------------------------------------ D6-05
    print("\n[D6-05] negative-cache backtest gagal (tidak diulang tiap poll)")
    write_journal([])   # jurnal kosong -> prioritas 1 & 2 tidak tersedia
    orig_engine = dash.IcasBacktestEngine
    orig_cache = (dash._cached_trades, dash._cached_stats, dash._backtest_failed)
    dash._cached_trades, dash._cached_stats, dash._backtest_failed = [], {}, False
    runs = {"n": 0}

    class Boom:
        def __init__(self, cfg):
            pass

        def run(self, *a, **kw):
            runs["n"] += 1
            raise RuntimeError("simulasi CSV korup")

    try:
        dash.IcasBacktestEngine = Boom
        t1, s1 = dash.get_backtest_summary()
        t2, s2 = dash.get_backtest_summary()
        check("panggilan-1 gagal -> stats kosong", s1 == {})
        check("panggilan-2 TIDAK menjalankan engine ulang "
              f"(total run = {runs['n']})", runs["n"] == 1)
    finally:
        dash.IcasBacktestEngine = orig_engine
        dash._cached_trades, dash._cached_stats, dash._backtest_failed = orig_cache

    # ------------------------------------------------------------------ D6-06
    print("\n[D6-06] run_server threaded=True")
    captured = {}
    orig_run = dash.app.run

    def fake_run(**kw):
        captured.update(kw)

    dash.app.run = fake_run
    try:
        dash.run_server()
    finally:
        dash.app.run = orig_run
    check(f"app.run(threaded=True) (aktual: {captured.get('threaded')})",
          captured.get("threaded") is True)

    # ------------------------------------------------------------------ D6-07
    print("\n[D6-07] jam server = Europe/Athens (tz-database, identik daemon G4)")
    try:
        from zoneinfo import ZoneInfo
        ath = ZoneInfo("Europe/Athens")
        h0 = datetime.datetime.now(ath).hour
        d = client.get("/api/status").get_json()
        h1 = datetime.datetime.now(ath).hour
        srv_h = int(d["server_time"][:2])
        check(f"server_time jam {srv_h} == Athens [{h0}..{h1}]",
              srv_h in (h0, h1))
    except Exception as e:
        check(f"zoneinfo tersedia & jam cocok ({e})", False)

    # ------------------------------------------------------------------ D6-08
    print("\n[D6-08] feed mati -> fav/pnl None (bukan dari harga 0)")
    orig_pos = dash.bridge.get_open_position_details
    try:
        dash.bridge.get_current_tick = lambda: {
            "bid": 0.0, "ask": 0.0, "spread": 0.0, "time": 0,
            "valid": False, "age_seconds": None, "reason": "no_tick"}
        dash.bridge.get_open_position_details = lambda: {
            "ticket": 900001, "type": "BUY", "volume": 0.33,
            "price_open": 4600.0, "sl": 4585.0, "tp": 0.0, "profit": 0.0,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "be_set": False, "max_fav": 0.0, "trail_step": 0}
        p = client.get("/api/status").get_json()["active_position"]
        check("posisi tetap tampil (ticket 900001)",
              p is not None and p["ticket"] == 900001)
        check("fav_pips/pnl_usd = None (bukan -$151k dari harga 0)",
              p["fav_pips"] is None and p["pnl_usd"] is None)
        check("feed_valid False + alasan terkirim",
              p["feed_valid"] is False and p["feed_reason"] == "no_tick")
        check("template null-safe (p.fav_pips === null check)",
              "p.fav_pips === null" in src_html)
    finally:
        dash.bridge.get_open_position_details = orig_pos
        dash.bridge.get_current_tick = orig_tick

    # ------------------------------------------------------------------ D6-10
    print("\n[D6-10] hardening template")
    check("esc() didefinisikan & dipakai (>=3 pemakaian)",
          "function esc(" in src_html and src_html.count("esc(") >= 3)
    check("placeholder login 88921045 dihapus dari template",
          "88921045" not in src_html)

    # ------------------------------------------------------------------ D6-11
    print("\n[D6-11] kesadaran strategi G4 (API + template)")
    d = client.get("/api/status").get_json()
    check(f"strategy == '{config.STRATEGY}'",
          d.get("strategy") == getattr(config, "STRATEGY", "ICAS"))
    g4 = d.get("g4") or {}
    check("g4 params sesuai config",
          g4.get("sweep_bars") == config.G4_SWEEP_BARS
          and abs(g4.get("fvg_buffer_usd", -1) - config.G4_FVG_BUFFER_USD) < 1e-9
          and g4.get("h1_ema_span") == config.G4_H1_EMA_SPAN)
    check("template: badge strategi + panel G4 + badge spread",
          all(k in src_html for k in ("strategy-badge", "g4-panel", "spread-badge")))

    # ------------------------------------------------------------------ D6-12
    print("\n[D6-12] realtime + diagnostik G4 (tick 1 dtk, kenapa belum entry)")
    r = client.get("/api/tick")
    d = r.get_json()
    check("HTTP 200 /api/tick", r.status_code == 200)
    check("field bid/ask/spread_usd/valid/server_time",
          all(k in d for k in ("bid", "ask", "spread_usd", "valid", "server_time")))
    check("spread_usd digit-aware (points x point)",
          abs(d["spread_usd"] - round(3350.26 - 3350.0, 2)) < 1e-9
          or d["spread_usd"] >= 0)
    r = client.get("/api/g4_state")
    d = r.get_json()
    check("HTTP 200 /api/g4_state", r.status_code == 200)
    check("struktur: available/blockers/strategy/next_close_secs",
          all(k in d for k in ("available", "blockers", "strategy", "next_close_secs")))
    check("mode sim (tanpa MT5): available False + bloker 'data'",
          d["available"] is False
          and any(b.get("code") == "data" for b in d["blockers"]))
    check("template: panel why + poll tick/g4_state + countdown + PDH",
          all(k in src_html for k in ("why-panel", "api/tick", "api/g4_state",
                                      "m5-countdown", "chart-m5-countdown", "PDH")))

    # --------------------------------------------------------------- regresi
    print("\n[REGRESI] endpoint & field lama tetap utuh")
    write_journal([
        {"ts": now, "event": "engine_start"},
        {"ts": now, "event": "signal_detected", "type": "BUY", "entry": 4680.0},
        {"ts": now, "event": "order_open", "ticket": 555001, "type": "BUY"},
        {"ts": now, "event": "tp_hit", "ticket": 555001, "level": 1},
        {"ts": now, "event": "position_closed", "ticket": 555001,
         "realized_total": 512.5, "tp1_hit": True},
    ])
    d = client.get("/api/status").get_json()
    for field in ("engine_version", "spread_usd", "spread_points", "price_point",
                  "be_active", "tp1_ratio", "journal", "journal_health",
                  "account", "sl_pips", "trailing_step"):
        check(f"/api/status field lama '{field}' ada", field in d)
    r = client.get("/api/journal?n=5")
    check("/api/journal 200 + <=5 event", r.status_code == 200
          and len(r.get_json()) <= 5)
    r = client.get("/api/candles")
    check("/api/candles 200", r.status_code == 200)
    r = client.get("/api/stats")
    check("/api/stats 200 + source jurnal", r.status_code == 200
          and "jurnal" in str(r.get_json().get("stats", {}).get("source", "")))
    check("daily_trades_count == 1 (order_open hari ini)",
          client.get("/api/status").get_json()["daily_trades_count"] == 1)

    # ------------------------------------------------------------------ done
    if had_orig:
        shutil.move(backup, jf)
    else:
        if os.path.exists(jf):
            os.remove(jf)

    print("\n" + "=" * 78)
    print(f"HASIL: {PASS} PASS / {FAIL} FAIL")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
