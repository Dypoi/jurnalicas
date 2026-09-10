"""
================================================================================
VERIFIKASI DASHBOARD v2 (pasca audit forensik D-01..D-05)
================================================================================
Memeriksa via Flask test client (tanpa server nyata):
  1. /api/status : engine_version, spread_usd digit-aware, label BE dinamis,
                   blok journal (status engine + PnL realized), rasio TP dinamis.
  2. /api/stats  : SUMBER statistik = jurnal_engine_v2 bila jurnal terisi
                   (tidak kebocoran ke backtest repo saat jurnal aktif).
  3. /api/journal: feed event terakhir terbaca.
Catatan: membuat logs/trade_journal.jsonl contoh dan MENGARSIPKAN yg lama (bila
ada) — jurnal asli Anda tidak akan ditimpa (di-backup ke *.verify_backup).
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
    ev = [
        {"ts": now, "event": "engine_start", "symbol": "XAUUSDm", "balance": 10000.0,
         "engine_version": getattr(config, "ENGINE_VERSION", "v2"), "config": {"x": 1}},
        {"ts": now, "event": "signal_detected", "type": "BUY", "entry": 4680.0, "sl": 4665.0, "lot": 0.31},
        {"ts": now, "event": "order_open", "ticket": 555001, "type": "BUY", "lot": 0.31,
         "entry": 4680.0, "sl": 4665.0},
        {"ts": now, "event": "tp_hit", "ticket": 555001, "level": 1, "close_vol": 0.09},
        {"ts": now, "event": "position_closed", "ticket": 555001, "realized_total": 512.5,
         "deals_out": 2, "result": "WIN", "tp1_hit": True},
        {"ts": now, "event": "position_closed_offline", "ticket": 555000, "realized_total": -500.0,
         "deals_out": 1, "result": "LOSS"},
        # [AUDIT 3 — A3-03] close TANPA PnL (riwayat flaky saat konfirmasi) lalu
        # PnL-nya datang belakangan via position_closed_pnl_backfill.
        {"ts": now, "event": "position_closed", "ticket": 555003,
         "deals_out": 2, "tp1_hit": True},
        {"ts": now, "event": "position_closed_pnl_backfill", "ticket": 555003,
         "realized_total": -250.0, "deals_out": 2, "result": "LOSS", "attempts": 3},
        {"ts": now, "event": "equity_snapshot", "balance": 10012.5, "equity": 10012.5},
    ]
    with open(jf, "w", encoding="utf-8") as f:
        for e in ev:
            f.write(json.dumps(e) + "\n")

    try:
        from src import dashboard_app as dash
        client = dash.app.test_client()

        r = client.get("/api/status")
        d = r.get_json()
        print("\n[A] /api/status")
        check("HTTP 200", r.status_code == 200)
        check("engine_version terkirim", bool(d.get("engine_version")))
        exp_spread = round(d["spread_points"] * d["price_point"], 2)
        check(f"spread_usd digit-aware ({d.get('spread_usd')} == points x point = {exp_spread})",
              abs(d.get("spread_usd", -1) - exp_spread) < 1e-9)
        check("be_active=False (engine v2: BE+ OFF)", d.get("be_active") is False)
        check("rasio TP dinamis (tp3_ratio=3.75)", abs(d.get("tp3_ratio", 0) - 3.75) < 1e-9)
        check("blok journal ada", isinstance(d.get("journal"), dict))
        j = d["journal"]
        check("status engine AKTIF (event barusan) ", "AKTIF" in j.get("engine_state", ""))
        check("signals/orders hari ini 1/1", j.get("signals_today") == 1 and j.get("orders_today") == 1)
        check("PnL hari ini = -237.50 (512.5-500-250, termasuk PnL backfill)",
              abs(j.get("pnl_today", 0) - (-237.5)) < 1e-9)
        check("closed_trades_logged=3", j.get("closed_trades_logged") == 3)

        r = client.get("/api/stats")
        s = r.get_json()
        print("\n[B] /api/stats")
        check("HTTP 200", r.status_code == 200)
        check("Sumber = jurnal_engine_v2 (bukan backtest repo)",
              s.get("stats", {}).get("source") == "jurnal_engine_v2")
        check("total_trades=3 (termasuk tiket yang PnL-nya di-backfill)",
              s.get("stats", {}).get("total_trades") == 3)
        check("PF ≈ 512.5/750 = 0.683 (toleransi float rounding)",
              abs(s.get("stats", {}).get("profit_factor", 0) - 0.683) <= 0.011)
        check("baris recent_trades ada", len(s.get("recent_trades", [])) == 3)

        # [AUDIT 3 — A3-04] flag TP posisi aktif harus dibaca dari state daemon,
        # bukan dari bridge dashboard (yang selalu default False).
        print("\n[B2] /api/status — flag posisi aktif dari state daemon")
        real_state_file = config.STATE_FILE
        fixture_state = os.path.join(os.path.dirname(jf), "icas_state.verify_fixture.json")
        with open(fixture_state, "w", encoding="utf-8") as f:
            json.dump({"positions": {"555002": {
                "tp1_hit": True, "tp2_hit": True, "tp3_hit": False,
                "be_set": True, "trail_step": 2, "initial_volume": 0.31}},
                "daily": {}, "closed": {}}, f)
        config.STATE_FILE = fixture_state
        _pos_backup = dash.bridge.active_position
        dash.bridge.active_position = {
            "ticket": 555002, "type": "BUY", "volume": 0.23, "price_open": 4680.0,
            "sl": 4683.0, "tp": 0.0, "profit": 12.5, "tp1_hit": False, "tp2_hit": False,
            "tp3_hit": False, "be_set": False, "max_fav": 3.1, "trail_step": 0,
            "initial_volume": 0.31}
        try:
            r = client.get("/api/status")
            p = r.get_json().get("active_position") or {}
            check("posisi aktif terkirim", bool(p))
            check("tp1_hit=True & tp2_hit=True dari state daemon (bukan default False)",
                  p.get("tp1_hit") is True and p.get("tp2_hit") is True)
            check("tp3_hit=False & be_set=True & trail_step=2 dari state daemon",
                  p.get("tp3_hit") is False and p.get("be_set") is True
                  and p.get("trail_step") == 2)
        finally:
            config.STATE_FILE = real_state_file
            dash.bridge.active_position = _pos_backup
            try:
                os.remove(fixture_state)
            except OSError:
                pass

        r = client.get("/api/journal?n=6")
        jn = r.get_json()
        print("\n[C] /api/journal")
        check("HTTP 200 & 6 event", r.status_code == 200 and len(jn) == 6)
        check("urutan terbalik (terbaru dulu)", jn[0]["event"] == "equity_snapshot")
        check("field config dipangkas dari feed", all("config" not in e for e in jn))

        # KPI dashboard v2 lama tidak membocorkan dataset repo saat jurnal aktif
        print("\n[D] Regresi label: template merender dinamis")
        with open("templates/index.html", encoding="utf-8") as f:
            html = f.read()
        check("Tidak ada hardcode legacy '20.0 pips ($2.00)' di protokol",
              "20.0 pips ($2.00)" not in html)
        check("Panel jurnal ada (jn-state)", "jn-state" in html)
        check("Badge status engine ada (engine-state-badge)", "engine-state-badge" in html)

    finally:
        if had_orig:
            shutil.copy2(backup, jf)
            os.remove(backup)
        else:
            try:
                os.remove(jf)
            except OSError:
                pass

    print("\n" + "=" * 72)
    print(f" HASIL: {PASS} PASS / {FAIL} FAIL")
    print("=" * 72)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
