"""
========================================================================================
MODEL ICAS REAL-TIME INSTITUTIONAL TRADINGVIEW-STYLE MONITORING DASHBOARD (DYNAMIC)
========================================================================================
[AUDIT FORENSIK DASHBOARD — 25 Agu 2026] Perbaikan:
  D-01 spread_usd digit-aware (bridge.get_point()) — kelas bug yg sama dgn root
      cause 10016 (hardcode *0.01 membuat spread XAUUSDm terlihat $2.60 pdhl $0.26).
  D-02 Label protokol TIDAK di-hardcode lagi — semua SL/TP/BE/RR dirender dinamis
      dari /api/status (mengikuti ENGINE v2 SWING-150; lihat templates/index.html).
  D-03 Statistik BERLABEL SUMBER: JURNAL ENGINE v2 (prioritas) > live-deals MT5
      (digabung per tiket) > backtest repo (diberi peringatan "BUKAN feed Anda").
  D-04 Live-deals diagregasi PER POSITION_ID (bug lama: partial TP dihitung
      sebagai trade terpisah -> total_trades digelembungkan 2-4x).
  D-05 Panel observasi on/off: status engine (AKTIF/MATI) dari jurnal JSON.
========================================================================================
"""
from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import datetime
import json
import os
from config import config
from src.indicators.sessions import calculate_session_killzones, is_current_in_burst
from src.strategy.icas_strategy import ModelIcasStrategy
from src.execution.mt5_bridge import IcasMT5Bridge
from src.backtest.engine import IcasBacktestEngine

app = Flask(__name__, template_folder='../templates')

bridge = IcasMT5Bridge(config)
bridge.initialize()
strategy_engine = ModelIcasStrategy(config)
price_point = bridge.get_point()   # [D-01] digit-aware: 0.01 (2-digit) / 0.001 (XAUUSDm 3-digit)

ENGINE_VERSION = getattr(config, "ENGINE_VERSION", "icas-v2")
JOURNAL_FILE = getattr(config, "JOURNAL_FILE", "logs/trade_journal.jsonl")
EQ_SNAP_S = int(getattr(config, "JOURNAL_EQUITY_SNAPSHOT_SECONDS", 900))


# [AUDIT FIX R-02] Proteksi token opsional untuk seluruh endpoint (lihat config.DASHBOARD_AUTH_TOKEN)
@app.before_request
def _auth_guard():
    token = config.DASHBOARD_AUTH_TOKEN
    if not token:
        return None  # tidak diproteksi (mode dev/lokal) — warning dicetak saat start
    provided = request.args.get("token", "") or request.headers.get("X-Auth-Token", "")
    if provided != token:
        return jsonify({"error": "unauthorized", "hint": "sertakan ?token=... atau header X-Auth-Token"}), 401
    return None

_cached_trades = []
_cached_stats = {}

# ============================ [D-05] JURNAL ENGINE v2 ============================

def _journal_events(limit_bytes: int = 2_000_000):
    """Baca event dari jurnal JSONL (tail-safe). Tak pernah raise."""
    try:
        if not os.path.exists(JOURNAL_FILE):
            return []
        with open(JOURNAL_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit_bytes))
            chunk = f.read().decode("utf-8", errors="ignore")
        if size > limit_bytes:                      # potong baris pertama yg mungkin separuh
            nl = chunk.find("\n")
            chunk = chunk[nl + 1:] if nl >= 0 else ""
        evs = []
        for ln in chunk.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                evs.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return evs
    except OSError:
        return []


def journal_summary(days: int = 7):
    """[D-05] Ringkasan observasi dari jurnal: status engine + aktivitas & PnL."""
    evs = _journal_events()
    if not evs:
        return {"exists": False, "engine_state": "BELUM ADA JURNAL",
                "hint": "jalankan engine: python run_live.py"}
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()

    starts = [e for e in evs if e.get("event") == "engine_start"]
    stops = [e for e in evs if e.get("event") == "engine_stop"]
    last_ev_ts = evs[-1].get("ts", "")
    last_start = starts[-1].get("ts", "") if starts else ""
    last_stop = stops[-1].get("ts", "") if stops else ""

    def _age_min(ts):
        try:
            return (datetime.datetime.now() - datetime.datetime.fromisoformat(ts)).total_seconds() / 60.0
        except Exception:
            return None

    age = _age_min(last_ev_ts)
    if last_stop and last_stop >= last_start:
        state = "MATI (engine_stop) 🔴"
    elif not starts:
        state = "TIDAK DIKETAHUI"
    elif age is not None and age <= (EQ_SNAP_S / 60.0) + 10:
        state = "AKTIF 🟢"
    elif age is not None and age <= 120:
        state = f"AKTIF? 🟡 (event terakhir {int(age)} mnt lalu)"
    else:
        state = f"KEMUNGKINAN MATI/MACET 🔴 ({int(age or 0)} mnt tanpa event)"

    sig_today = sum(1 for e in evs if e.get("event") == "signal_detected" and str(e.get("ts", "")).startswith(today))
    ord_today = sum(1 for e in evs if e.get("event") == "order_open" and str(e.get("ts", "")).startswith(today))
    # [D-06/AUDIT FIX LIVE-01] Dedup per tiket: engine lama bisa mencatat satu
    # tiket 'closed' lebih dari sekali (miss transien MT5). realized_total
    # bersifat kumulatif per tiket -> hanya event TERAKHIR yang benar.
    pnl_today = 0.0
    pnl_week = 0.0
    last_closed_by_ticket = {}
    any_closed_by_ticket = {}
    for e in evs:
        if e.get("event") in ("position_closed", "position_closed_offline"):
            tk = str(e.get("ticket"))
            any_closed_by_ticket[tk] = e
            if isinstance(e.get("realized_total"), (int, float)):
                last_closed_by_ticket[tk] = e
    n_closed = len(any_closed_by_ticket)
    for e in last_closed_by_ticket.values():
        v = e["realized_total"]
        d = str(e.get("ts", ""))[:10]
        if d == today:
            pnl_today += v
        if d >= week_ago:
            pnl_week += v
    return {
        "exists": True, "engine_state": state, "journal_file": JOURNAL_FILE,
        "events_total": len(evs), "last_event": last_ev_ts,
        "signals_today": sig_today, "orders_today": ord_today,
        "pnl_today": round(pnl_today, 2), f"pnl_{days}d": round(pnl_week, 2),
        "closed_trades_logged": n_closed,
        "starts": len(starts), "stops": len(stops),
    }


def _stats_from_journal():
    """[D-03] Statistik per-tiket dari jurnal engine v2 (realized_total akurat,
    sudah termasuk semua partial close + komisi + swap)."""
    evs = _journal_events()
    trades = {}
    for e in evs:
        tk = e.get("ticket")
        if tk is None:
            continue
        tr = trades.setdefault(str(tk), {"time": e.get("ts", ""), "type": e.get("type"),
                                         "tp1": False, "tp2": False, "tp3": False,
                                         "be_set": False, "trail_step": 0, "pnl": None,
                                         "max_fav": 0.0})
        ev = e.get("event")
        if ev == "order_open":
            tr["time"] = e.get("ts", ""); tr["type"] = e.get("type")
        elif ev == "tp_hit":
            tr[f"tp{e.get('level')}"] = True
        elif ev == "be_lock":
            tr["be_set"] = True
        elif ev == "trail_update":
            tr["trail_step"] = max(tr["trail_step"], int(e.get("step", 0) or 0))
        elif ev in ("position_closed", "position_closed_offline"):
            tr["time"] = e.get("ts", "")
            if e.get("max_fav_usd"):
                tr["max_fav"] = round(float(e.get("max_fav_usd")) * 10.0, 1)
            for k in ("tp1", "tp2", "tp3"):
                if e.get(f"{k}_hit"):
                    tr[k] = True
            if e.get("trail_step"):
                tr["trail_step"] = max(tr["trail_step"], int(e.get("trail_step")))
            if isinstance(e.get("realized_total"), (int, float)):
                tr["pnl"] = float(e["realized_total"])

    closed = [t for t in trades.values() if t["pnl"] is not None]
    if not closed:
        return None, None
    wins = [t for t in closed if t["pnl"] > 1.0]
    scratch = [t for t in closed if -1.0 <= t["pnl"] <= 1.0]
    losses = [t for t in closed if t["pnl"] < -1.0]
    gw = sum(t["pnl"] for t in wins) + sum(t["pnl"] for t in scratch)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    total = len(closed)
    stats = {
        "source": "jurnal_engine_v2", "is_live": True,
        "total_trades": total, "wins": len(wins), "be_trades": len(scratch),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100.0, 2),
        "be_rate": round(len(scratch) / total * 100.0, 2),
        "non_loss_rate": round((len(wins) + len(scratch)) / total * 100.0, 2),
        "profit_factor": round(pf, 2), "net_profit": round(gw - gl, 2),
        "be_activations": sum(1 for t in closed if t["be_set"]),
        "tp1_hits": sum(1 for t in closed if t["tp1"]),
        "tp2_hits": sum(1 for t in closed if t["tp2"]),
        "tp3_hits": sum(1 for t in closed if t["tp3"]),
        "runner_steps": sum(1 for t in closed if t["trail_step"] >= 1),
    }
    trades_list = [{
        "time": (t["time"] or "")[:16].replace("T", " "), "type": t["type"] or "-",
        "res": ("WIN" if t["pnl"] > 1.0 else ("BE" if t["pnl"] >= -1.0 else "LOSS")),
        "pnl": round(t["pnl"], 2), "balance": 0.0, "max_fav": t["max_fav"],
        "tp1": t["tp1"], "tp2": t["tp2"], "tp3": t["tp3"], "be_set": t["be_set"],
        "trail_step": t["trail_step"]} for t in sorted(closed, key=lambda x: x["time"], reverse=True)[:60]]
    return trades_list, stats


def _stats_from_live_deals():
    """[D-04] Live-deals MT5 DIGABUNG per position_id — hotfix bug agregasi
    (partial TP dahulu dihitung trade terpisah -> total_trades menggembung)."""
    deals = bridge.get_live_deals_history(days=7)
    if not deals:
        return [], {}
    by_pos = {}
    for d in deals:
        pid = d.get("position_id") or d.get("time")  # fallback: per-deal bila tak ada id
        g = by_pos.setdefault(pid, {"time": d["time"], "type": d["type"], "pnl": 0.0,
                                    "be_set": False, "tp1": False, "tp2": False,
                                    "tp3": False, "trail_step": 0, "max_fav": 0.0})
        g["pnl"] += d.get("pnl", 0.0)
        g["tp1"] = g["tp1"] or d.get("tp1", False)
        g["be_set"] = g["be_set"] or d.get("be_set", False)
    grouped = list(by_pos.values())
    wins = [g for g in grouped if g["pnl"] >= 10.0]
    scratch = [g for g in grouped if 0 <= g["pnl"] < 10.0]
    losses = [g for g in grouped if g["pnl"] < 0]
    total = len(grouped)
    gw = sum(g["pnl"] for g in wins) + sum(g["pnl"] for g in scratch)
    gl = abs(sum(g["pnl"] for g in losses))
    pf = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    stats = {
        "source": "live_deals_mt5_7d (grouped per posisi)", "is_live": True,
        "total_trades": total, "wins": len(wins), "be_trades": len(scratch),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100.0, 2) if total else 0,
        "profit_factor": round(pf, 2), "net_profit": round(gw - gl, 2),
        "be_activations": len(scratch),
    }
    trades_list = sorted(grouped, key=lambda x: x["time"], reverse=True)[:60]
    for g in trades_list:
        g["res"] = "WIN" if g["pnl"] >= 10.0 else ("BE" if g["pnl"] >= 0 else "LOSS")
        g["balance"] = g.get("balance", 0.0)
    return trades_list, stats


def get_backtest_summary():
    global _cached_trades, _cached_stats

    # [D-03] Prioritas sumber: JURNAL ENGINE v2 (observasi demo) paling akurat...
    j_trades, j_stats = _stats_from_journal()
    if j_stats:
        return j_trades, j_stats

    # ...lalu live-deals broker 7 hari (digabung per position_id),...
    l_trades, l_stats = _stats_from_live_deals()
    if l_stats:
        return l_trades, l_stats

    # ...baru backtest dataset repo — dengan PERINGATAN eksplisit: dataset ini
    # BUKAN feed live Anda (deviasi median ~$15, temuan forensik §8.6).

    if _cached_stats:
        return _cached_trades, _cached_stats

    csv_path = 'data/historical/xauusd_m5.csv'
    if not os.path.exists(csv_path):
        return [], {}

    try:
        df_m5 = pd.read_csv(csv_path)
        engine = IcasBacktestEngine(config)
        final_cap, tdf = engine.run(df_m5, start_date='2026-01-01', end_date='2026-06-30 23:59:59', compounding=False)
        
        total = len(tdf)
        wins = tdf[tdf['res'] == 'WIN']
        be_trades = tdf[tdf['res'] == 'BE']
        losses = tdf[tdf['res'] == 'LOSS']
        
        wr = len(wins) / total * 100.0 if total > 0 else 0
        be_rate = len(be_trades) / total * 100.0 if total > 0 else 0
        loss_rate = len(losses) / total * 100.0 if total > 0 else 0
        non_loss_rate = (len(wins) + len(be_trades)) / total * 100.0 if total > 0 else 0
        
        # [FIX PF-sign] PF standar = berbasis TANDA pnl: trailing-out profit yg
        # terklasifikasi 'LOSS' (tanpa TP hit) tetap dihitung sebagai profit.
        gw = tdf.loc[tdf['pnl'] > 0, 'pnl'].sum()
        gl = abs(tdf.loc[tdf['pnl'] < 0, 'pnl'].sum())
        pf = gw / gl if gl > 0 else 0
        eq = pd.Series([config.INITIAL_CAPITAL] + tdf['balance'].tolist())
        dd = (((eq.cummax() - eq) / eq.cummax()) * 100.0).max()
        
        _cached_stats = {
            "source": "backtest_repo (⚠️ BUKAN feed live Anda)",
            "total_trades": total,
            "wins": len(wins),
            "be_trades": len(be_trades),
            "losses": len(losses),
            "win_rate": round(wr, 2),
            "be_rate": round(be_rate, 2),
            "loss_rate": round(loss_rate, 2),
            "non_loss_rate": round(non_loss_rate, 2),
            "profit_factor": round(pf, 2),
            "net_profit": round(final_cap - config.INITIAL_CAPITAL, 2),
            "roi_pct": round((final_cap - config.INITIAL_CAPITAL)/100.0, 2),
            "final_balance": round(final_cap, 2),
            "max_drawdown": round(dd, 2),
            "be_activations": len(tdf[tdf['be_set'] == True]),
            "tp1_hits": len(tdf[tdf['tp1_hit'] == True]),
            "tp2_hits": len(tdf[tdf['tp2_hit'] == True]),
            "tp3_hits": len(tdf[tdf['tp3_hit'] == True]),
            "runner_steps": len(tdf[tdf['trail_stepped'] >= 1]),
            "is_live": False,
            "dataset_warning": True,
        }
        
        trades_list = []
        for idx, row in tdf.tail(60).iloc[::-1].iterrows():
            trades_list.append({
                "time": row['time'].strftime('%Y-%m-%d %H:%M'),
                "type": row['type'],
                "res": row['res'],
                "pnl": round(row['pnl'], 2),
                "balance": round(row['balance'], 2),
                "max_fav": round(row['max_fav_pips'], 1),
                "tp1": bool(row['tp1_hit']),
                "tp2": bool(row['tp2_hit']),
                "tp3": bool(row['tp3_hit']),
                "be_set": bool(row['be_set']),
                "trail_step": int(row['trail_stepped'])
            })
        _cached_trades = trades_list
    except Exception as e:
        print(f"Error computing backtest stats: {e}")
        _cached_stats = {}
        _cached_trades = []
        
    return _cached_trades, _cached_stats

@app.route('/')
def index():
    return render_template('index.html', symbol=config.SYMBOL, risk_pct=config.RISK_PER_TRADE_PCT*100)

@app.route('/api/status')
def api_status():
    # [AUDIT FIX R-02] utcnow() deprecated di py3.12+; offset server diturunkan
    # dari config.SERVER_TIME_OFFSET_HOURS (bukan hardcode UTC+3, aman saat DST).
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    server_utc_shift = 7 - config.SERVER_TIME_OFFSET_HOURS   # WIB(UTC+7) minus offset WIB->server
    server_hour = (now_utc.hour + server_utc_shift) % 24
    server_min = now_utc.minute
    server_sec = now_utc.second
    wib_hour = (now_utc.hour + 7) % 24
    
    in_burst = is_current_in_burst(server_hour, server_min)
    
    active_sessions = []
    if 0 <= wib_hour < 6: active_sessions.append("Late NY / Pacific")
    if 7 <= wib_hour < 11: active_sessions.append("Tokyo / Asian (07:00-11:00 WIB)")
    if 12 <= wib_hour < 17: active_sessions.append("London Open (12:00-17:00 WIB)")
    if 18 <= wib_hour < 24: active_sessions.append("New York Open (18:00-24:00 WIB)")
    if not active_sessions: active_sessions.append("Inter-Session Transition")

    acc_info = bridge.get_account_details()
    tick = bridge.get_current_tick()
    pos = bridge.get_open_position_details()

    pos_data = None
    if pos is not None:
        cur_price = tick["bid"] if pos["type"] == "BUY" else tick["ask"]
        ep = pos["price_open"]
        fav_usd = (cur_price - ep) if pos["type"] == "BUY" else (ep - cur_price)
        fav_pips = round(fav_usd * 10.0, 1)
        pnl_usd = round(fav_usd * pos["volume"] * 100.0, 2)
        pos_data = {
            "ticket": pos["ticket"],
            "type": pos["type"],
            "volume": pos["volume"],
            "entry": round(ep, 2),
            "current_price": round(cur_price, 2),
            "sl": round(pos["sl"], 2),
            "fav_pips": fav_pips,
            "pnl_usd": pnl_usd,
            "be_set": bool(pos.get("be_set", False)),
            "tp1_hit": bool(pos.get("tp1_hit", False)),
            "tp2_hit": bool(pos.get("tp2_hit", False)),
            "tp3_hit": bool(pos.get("tp3_hit", False)),
            "trail_step": int(pos.get("trail_step", 0))
        }

    return jsonify({
        "status": "RUNNING",
        "engine_version": ENGINE_VERSION,
        "symbol": bridge.resolved_symbol,
        "timeframe": config.TIMEFRAME,
        "macro_timeframe": config.MACRO_TIMEFRAME,
        "server_time": f"{server_hour:02d}:{server_min:02d}:{server_sec:02d}",
        "wib_time": f"{wib_hour:02d}:{server_min:02d}:{server_sec:02d}",
        "active_sessions": ", ".join(active_sessions),
        "use_killzone": config.USE_KILLZONE,
        "in_killzone": in_burst,
        "bid": round(tick["bid"], 2),
        "ask": round(tick["ask"], 2),
        "spread_points": round(tick["spread"], 1),
        # [D-01] digit-aware: spread_usd = points x point simbol (bukan x0.01 tetap)
        "spread_usd": round(tick["spread"] * price_point, 2),
        "price_point": price_point,
        "spread_status": "NORMAL (Aman) ✅" if tick["spread"] <= config.MAX_SPREAD_POINTS else "TINGGI ⚠️",
        "account": acc_info,
        "risk_pct": config.RISK_PER_TRADE_PCT * 100,
        "sl_pips": config.STOP_LOSS_PIPS,
        "early_be_pips": config.EARLY_BE_TRIGGER_PIPS,
        "be_active": bool(config.EARLY_BE_TRIGGER_PIPS < 9999),
        "tp1_pips": config.TP1_PIPS,
        "tp2_pips": config.TP2_PIPS,
        "tp3_pips": config.TP3_PIPS,
        "tp1_ratio": round(config.TP1_PIPS / max(1e-9, config.STOP_LOSS_PIPS), 2),
        "tp2_ratio": round(config.TP2_PIPS / max(1e-9, config.STOP_LOSS_PIPS), 2),
        "tp3_ratio": round(config.TP3_PIPS / max(1e-9, config.STOP_LOSS_PIPS), 2),
        "trailing_step": config.TRAILING_STEP_PIPS,
        "trailing_lock": config.TRAILING_LOCK_PIPS,
        "journal": journal_summary(),
        "daily_trades_count": strategy_engine.daily_trades_count,
        "active_position": pos_data
    })


@app.route('/api/journal')
def api_journal():
    """[D-05] Feed event jurnal mentah (default 25 terakhir) untuk panel observasi."""
    n = request.args.get("n", 25, type=int)
    evs = _journal_events()
    slim = [{k: v for k, v in e.items() if k != "config"} for e in evs[-max(1, min(200, n)):]]
    return jsonify(slim[::-1])

@app.route('/api/candles')
def api_candles():
    df_raw = bridge.get_latest_m5_candles(120)
    if df_raw.empty:
        return jsonify([])
    
    df = calculate_session_killzones(df_raw)
    
    candles = []
    for idx, row in df.iterrows():
        c = float(row['close'])
        o = float(row['open'])
        h = float(row['high'])
        l = float(row['low'])
        
        is_bull_fvg = False
        is_bear_fvg = False
        if idx >= 2:
            prev2_h = float(df['high'].iloc[idx-2])
            prev2_l = float(df['low'].iloc[idx-2])
            if l > prev2_h + 0.30: is_bull_fvg = True
            if h < prev2_l - 0.30: is_bear_fvg = True
            
        candles.append({
            "time": row['time'].strftime('%m-%d %H:%M'),
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "asian_high": round(float(row.get('asian_high', h)), 2),
            "asian_low": round(float(row.get('asian_low', l)), 2),
            "london_high": round(float(row.get('london_high', h)), 2),
            "london_low": round(float(row.get('london_low', l)), 2),
            "in_burst": bool(row.get('in_ict_burst', False)),
            "bull_fvg": is_bull_fvg,
            "bear_fvg": is_bear_fvg
        })
    return jsonify(candles)

@app.route('/api/stats')
def api_stats():
    trades, stats = get_backtest_summary()
    return jsonify({
        "stats": stats,
        "recent_trades": trades[:30]
    })

def run_server(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT):
    # [AUDIT FIX R-02] Peringatan keamanan jika dashboard ter-expose tanpa token
    if host in ("0.0.0.0", "::") and not config.DASHBOARD_AUTH_TOKEN:
        print("⚠️  [SECURITY] Dashboard terbuka ke SELURUH jaringan tanpa token!")
        print("                Set ICAS_DASH_TOKEN=<rahasia> lalu akses http://<host>:"
              f"{port}/?token=<rahasia> , atau bind ke 127.0.0.1 untuk pemakaian lokal.")
    app.run(host=host, port=port, debug=False)

if __name__ == '__main__':
    run_server()
