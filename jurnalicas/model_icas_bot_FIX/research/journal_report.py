"""
================================================================================
JOURNAL REPORT — alat observasi ENGINE v2 dari logs/trade_journal.jsonl
================================================================================
Membaca jurnal JSON yang ditulis icas_daemon.py selama seminggu demo dan
merangkum: aktivitas harian, PF/NLR/PnL, kurva equity, adopsi posisi (on/off),
durasi hold, kesehatan uptime — plus PEMBANDING otomatis terhadap hasil
forward-test backtest M1 (referensi: ~3-5 trade/hari, PF OOS 2.25, target
terima PF forward >= 1.8; stop-rule PF < 1.0 setelah >= 30 trade).

Cara pakai:
  python3 research/journal_report.py
  python3 research/journal_report.py --file logs/trade_journal.jsonl \
      --out reports/journal_observasi.txt --last 15
================================================================================
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import datetime
import collections

BENCH = {
    "trades_per_day_ref": "3-5",
    "pf_target": 1.8,
    "pf_stop": 1.0,
    "pf_stop_min_trades": 30,
}


def load_events(path):
    events = []
    if not os.path.exists(path):
        return events
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                events.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return events


def parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def build_trades(events):
    trades = {}
    def t(ticket):
        return trades.setdefault(str(ticket), {
            "ticket": str(ticket), "open_ts": None, "close_ts": None, "type": None,
            "lot": None, "entry": None, "sl": None, "tp_hits": [], "trails": 0,
            "adopted": False, "adopt_source": None, "closed_context": None,
            "realized_total": None, "result": None, "deals_out": None,
        })

    for e in events:
        ev = e.get("event")
        tk = e.get("ticket")
        if ev in ("order_open", "position_adopted", "tp_hit", "trail_update",
                  "be_lock", "position_closed", "position_closed_offline") and tk is not None:
            tr = t(tk)
            if ev == "order_open":
                tr["open_ts"] = tr["open_ts"] or parse_ts(e.get("ts", ""))
                tr["type"] = e.get("type"); tr["lot"] = e.get("lot")
                tr["entry"] = e.get("entry"); tr["sl"] = e.get("sl")
            elif ev == "position_adopted":
                tr["adopted"] = True; tr["adopt_source"] = e.get("source")
                tr["type"] = tr["type"] or e.get("type")
                tr["entry"] = tr["entry"] or e.get("price_open")
                # adopsi -> buka terjadi sebelum daemon ON; waktu buka tak pasti
                tr["open_ts"] = tr["open_ts"] or parse_ts(e.get("ts", ""))
            elif ev == "tp_hit":
                tr["tp_hits"].append(e.get("level"))
            elif ev == "trail_update":
                tr["trails"] = max(tr["trails"], int(e.get("step", 0) or 0))
            elif ev in ("position_closed", "position_closed_offline"):
                tr["close_ts"] = parse_ts(e.get("ts", "")) or tr["close_ts"]
                tr["closed_context"] = e.get("context")
                if e.get("realized_total") is not None:
                    tr["realized_total"] = e.get("realized_total")
                    tr["result"] = e.get("result")
                    tr["deals_out"] = e.get("deals_out")
    return trades


def fmt_money(x):
    return f"${x:+,.2f}" if isinstance(x, (int, float)) else "-"


def main():
    ap = argparse.ArgumentParser(description="Observasi jurnal Engine v2 (demo seminggu)")
    ap.add_argument("--file", default="logs/trade_journal.jsonl")
    ap.add_argument("--out", default="reports/journal_observasi.txt")
    ap.add_argument("--last", type=int, default=12, help="Cetak N event terakhir")
    args = ap.parse_args()

    out_lines = []
    def P(s=""):
        print(s)
        out_lines.append(s)

    events = load_events(args.file)
    P("=" * 96)
    P(" 📒 JOURNAL REPORT — OBSERVASI ENGINE BARU v2 (SWING-150)")
    P("=" * 96)
    P(f"Sumber jurnal : {args.file}")
    if not events:
        P("❌ Jurnal kosong/belum ada. Jalankan engine (python run_live.py) terlebih dahulu.")
        _save(args.out, out_lines)
        return

    ts_first = parse_ts(events[0].get("ts", ""))
    ts_last = parse_ts(events[-1].get("ts", ""))
    span_days = max(1, ((ts_last or ts_first) - ts_first).days + 1) if ts_first else 1
    counts = collections.Counter(e.get("event") for e in events)
    P(f"Rentang       : {ts_first}  ->  {ts_last}  ({span_days} hari kalender, "
      f"{len(events)} event)")
    P(f"Event terbanyak: " + ", ".join(f"{k}×{v}" for k, v in counts.most_common(8)))

    trades = build_trades(events)
    closed = [t for t in trades.values() if t["realized_total"] is not None]
    open_only = [t for t in trades.values() if t["realized_total"] is None]

    P("\n" + "-" * 96)
    P(" A. REKAP TRADE (key = tiket posisi)")
    P("-" * 96)
    P(f"Total tiket teramati     : {len(trades)}  (tertutup & terhitung PnL: {len(closed)}, "
      f"masih berjalan/PnL-unknown: {len(open_only)})")
    adopted = [t for t in trades.values() if t["adopted"]]
    P(f"Posisi diadopsi (on/off) : {len(adopted)}  "
      f"(via state file: {sum(1 for t in adopted if t['adopt_source']=='state_file')}, "
      f"via deal broker: {sum(1 for t in adopted if t['adopt_source']=='mt5_deals')})")

    if closed:
        pnls = [t["realized_total"] for t in closed]
        wins = [p for p in pnls if p > 1.0]
        losses = [p for p in pnls if p < 0]
        gross_w, gross_l = sum(wins), abs(sum(losses))
        pf = gross_w / gross_l if gross_l > 0 else float("inf")
        nlr = (len(wins) + sum(1 for p in pnls if 0 <= p <= 1.0)) / len(pnls) * 100.0
        P(f"\nProfit Factor (realized) : {pf:.2f}")
        P(f"Non-Loss Rate            : {nlr:.1f}%   (Win>+$1: {len(wins)} | Scratch ~0: "
          f"{len(pnls)-len(wins)-len(losses)} | Loss: {len(losses)})")
        P(f"Net PnL (realized)       : {fmt_money(sum(pnls))}")
        P(f"Ekspektasi/trade         : {fmt_money(sum(pnls)/len(pnls))}")
        P(f"Avg Win / Avg Loss       : {fmt_money(sum(wins)/len(wins)) if wins else '-'} / "
          f"{fmt_money(sum(losses)/len(losses)) if losses else '-'}")
        holds = []
        for t in closed:
            if t["open_ts"] and t["close_ts"]:
                holds.append((t["close_ts"] - t["open_ts"]).total_seconds() / 3600.0)
        if holds:
            holds.sort()
            P(f"Durasi hold (jam)        : median {holds[len(holds)//2]:.1f} | "
              f"min {holds[0]:.1f} | maks {holds[-1]:.1f}")

    P("\n" + "-" * 96)
    P(" B. AKTIVITAS & PNL PER HARI")
    P("-" * 96)
    opens_by_day = collections.Counter()
    pnl_by_day = collections.defaultdict(float)
    n_by_day = collections.Counter()
    for t in trades.values():
        if t["open_ts"]:
            opens_by_day[t["open_ts"].date().isoformat()] += 1
        if t["realized_total"] is not None and t["close_ts"]:
            d = t["close_ts"].date().isoformat()
            pnl_by_day[d] += t["realized_total"]
            n_by_day[d] += 1
    all_days = sorted(set(list(opens_by_day) + list(pnl_by_day)))
    P(f"{'Tanggal':12s} | {'Entry':>5s} | {'Closed':>6s} | {'PnL Realized':>14s} | Catatan")
    tot_entry = 0
    for d in all_days:
        o = opens_by_day.get(d, 0); c = n_by_day.get(d, 0); p = pnl_by_day.get(d, 0.0)
        tot_entry += o
        note = []
        if o == 0: note.append("tanpa entry (bisa jadi daemon OFF/hari libur)")
        if o > 6: note.append("frekuensi tinggi (cek sinyal)")
        P(f"{d:12s} | {o:5d} | {c:6d} | {fmt_money(p):>14s} | {'; '.join(note)}")
    active_days = sum(1 for d in all_days if opens_by_day.get(d, 0) > 0)
    if active_days:
        P(f"\nRata-rata entry/hari aktif: {tot_entry/active_days:.1f} (referensi backtest: "
          f"{BENCH['trades_per_day_ref']})")

    snaps = [e for e in events if e.get("event") == "equity_snapshot" and
             isinstance(e.get("equity"), (int, float))]
    if len(snaps) >= 2:
        P("\n" + "-" * 96)
        P(" C. KURVA EQUITY (snapshot berkala)")
        P("-" * 96)
        for e in snaps:
            fl = e.get("floating_pnl") or 0.0
            P(f"  {e.get('ts','')[:19]}  | balance {fmt_money(e.get('balance'))} | "
              f"equity {fmt_money(e.get('equity'))} | floating {fmt_money(fl)}")
        eq0, eq1 = snaps[0].get("equity"), snaps[-1].get("equity")
        if isinstance(eq0, (int, float)) and isinstance(eq1, (int, float)):
            P(f"\nPerubahan equity teramati: {fmt_money(eq1-eq0)} "
              f"({eq1-eq0 >= 0 and 'naik' or 'turun'} dari {fmt_money(eq0)} ke {fmt_money(eq1)})")

    P("\n" + "-" * 96)
    P(" D. EVALUASI vs FORWARD-TEST BACKTEST (referensi §10 LAPORAN)")
    P("-" * 96)
    if closed:
        pnls = [t["realized_total"] for t in closed]
        wins = [p for p in pnls if p > 1.0]
        losses = [p for p in pnls if p < 0]
        pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")
        n = len(closed)
        if pf >= BENCH["pf_target"] and n >= 10:
            P(f"✅ SEHAT: PF {pf:.2f} >= target {BENCH['pf_target']} dengan {n} trade — lanjutkan observasi.")
        elif pf >= BENCH["pf_stop"]:
            if pf >= BENCH["pf_target"]:
                P(f"🟡 SEHAT-tapi-dini: PF {pf:.2f} >= target {BENCH['pf_target']}, namun sampel baru {n} trade "
                  f"(<10) — teruskan observasi hingga minimal {BENCH['pf_stop_min_trades']} trade.")
            else:
                P(f"🟡 NETRAL: PF {pf:.2f} — di bawah target {BENCH['pf_target']} tapi masih positif; "
                  f"butuh sampel lebih banyak (min {BENCH['pf_stop_min_trades']} trade utk keputusan).")
        else:
            if n >= BENCH["pf_stop_min_trades"]:
                P(f"⛔ STOP-RULE TERPENUHI: PF {pf:.2f} < {BENCH['pf_stop']} dengan {n} trade — "
                  f"matikan engine, kalibrasi ulang dengan data forward ini.")
            else:
                P(f"🟠 WASPADA awal: PF {pf:.2f} < 1.0 tapi sampel baru {n} trade "
                  f"(< {BENCH['pf_stop_min_trades']}) — jangan panik, terus observasi.")
    else:
        P("Belum ada trade tertutup — evaluasi tersedia setelah posisi pertama selesai.")

    starts = [e for e in events if e.get("event") == "engine_start"]
    stops = [e for e in events if e.get("event") == "engine_stop"]
    P(f"\nSiklus hidup daemon        : {len(starts)}× start, {len(stops)}× stop "
      f"(pola on/off Anda terekam lengkap di jurnal).")
    if len(starts) > len(stops):
        P("Catatan: ada sesi tanpa engine_stop berpasangan (listrik mati / kill paksa) — "
          "tidak apa-apa; rekonsiliasi saat start berikutnya sudah menanganinya.")

    # ---------------- [AUDIT 2 Sep 2026] KESEHATAN KONEKSI & INTEGRITAS ----------------
    P("\n" + "-" * 96)
    P(" F. KESEHATAN KONEKSI & INTEGRITAS EKSEKUSI (audit forensik)")
    P("-" * 96)
    # (1) snapshot dengan balance palsu (INITIAL_CAPITAL) / equity None = koneksi putus
    #     tanpa terdeteksi (engine < v2-d). Engine v2-d menulis connected=False eksplisit.
    fake_snaps = [e for e in events if e.get("event") == "equity_snapshot" and
                  (e.get("equity") is None or e.get("connected") is False)]
    if fake_snaps:
        P(f"⚠️ {len(fake_snaps)} snapshot menunjukkan KONEKSI MT5 PUTUS (equity None / connected=False): "
          f"{fake_snaps[0].get('ts','')[:16]} .. {fake_snaps[-1].get('ts','')[:16]}")
    disc = [e for e in events if e.get("event") == "mt5_disconnected"]
    reco = [e for e in events if e.get("event") == "mt5_reconnected"]
    if disc or reco:
        tot_down = sum(float(e.get("downtime_seconds") or 0) for e in reco)
        P(f"Koneksi putus terdeteksi   : {len(disc)}× | pulih otomatis: {len(reco)}× | total downtime {tot_down/60:.1f} menit")
    stalls = [e for e in events if e.get("event") == "loop_stall_warning"]
    if stalls:
        P(f"Loop stall (>2 mnt)        : {len(stalls)}× | terlama {max(float(e.get('gap_seconds') or 0) for e in stalls)/60:.1f} menit "
          f"(laptop sleep / MT5 hang — manajemen TP/trailing tidak berjalan selama jeda)")
    cyc_err = [e for e in events if e.get("event") == "cycle_error"]
    if cyc_err:
        P(f"Exception per-siklus       : {len(cyc_err)}× (daemon tetap hidup; lihat 'error' di jurnal)")
    # (2) integritas: event tp_hit ganda / SL dilonggarkan
    tp1_by_tk = collections.Counter(str(e.get("ticket")) for e in events
                                    if e.get("event") == "tp_hit" and e.get("level") == 1)
    dup_tp1 = {k: v for k, v in tp1_by_tk.items() if v > 1}
    if dup_tp1:
        P(f"⛔ TP1 ganda pada tiket    : {dup_tp1} (bug LIVE-01 engine lama; diperbaiki v2-d)")
    loosen = 0
    last_sl = {}
    typ = {str(e.get("ticket")): e.get("type") for e in events if e.get("event") == "order_open"}
    for e in events:
        if e.get("event") in ("be_lock", "trail_update", "sl_step_to_tp1"):
            tk = str(e.get("ticket")); sl = e.get("new_sl")
            if tk in last_sl and isinstance(sl, (int, float)):
                if (typ.get(tk) == "BUY" and sl < last_sl[tk]) or (typ.get(tk) == "SELL" and sl > last_sl[tk]):
                    loosen += 1
            if isinstance(sl, (int, float)):
                last_sl[tk] = sl
    if loosen:
        P(f"⛔ SL DILONGGARKAN         : {loosen}× (be_lock pasca-TP1 menurunkan SL trailing — bug SL-01; diperbaiki v2-d)")
    if not (fake_snaps or disc or stalls or dup_tp1 or loosen or cyc_err):
        P("✅ Tidak ada anomali koneksi/integritas terdeteksi pada jurnal ini.")

    if args.last > 0:
        P("\n" + "-" * 96)
        P(f" E. {args.last} EVENT TERAKHIR")
        P("-" * 96)
        for e in events[-args.last:]:
            slim = {k: v for k, v in e.items() if k not in ("config",)}
            P("  " + json.dumps(slim, ensure_ascii=False, default=str)[:150])

    P("\n" + "=" * 96)
    P(" Selesai. Simpan file ini sebagai arsip mingguan bersama trade_journal.jsonl.")
    P("=" * 96)
    _save(args.out, out_lines)


def _save(path, lines):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\n💾 Laporan observasi tersimpan ke: {path}")
    except OSError as e:
        print(f"\n⚠️ Gagal menyimpan laporan: {e}")


if __name__ == "__main__":
    main()
