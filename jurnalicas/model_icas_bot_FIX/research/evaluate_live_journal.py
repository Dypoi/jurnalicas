#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
EVALUATOR JURNAL LIVE — rekonstruksi & evaluasi kinerja dari trade_journal.jsonl
================================================================================
[Disiapkan 24 Sep 2026 — evaluasi minggu pertama engine G4 (icas-v3-g4) live]

Schema-tolerant: skema jurnal berevolusi (v2 ICAS -> v3 G4 + event baru:
signal_skipped_reentry, signal_skipped_stale, server_clock_offset, dll), maka
semua field dibaca defensif (.get) — bagian yang datanya tak ada dilaporkan
sebagai 0/—, bukan error.

Yang dihitung:
  1. Sensus event + sesi engine (engine_start: versi & waktu -> tahu kode mana
     yang aktif di periode mana).
  2. Trade: rekonstruksi per tiket dari order_open + position_closed(_offline)
     (partial TP = beberapa close per tiket, pnl dijumlah); tabel harian,
     WR, PF, avg win/loss, win/loss terbesar, streak.
  3. Rekonsiliasi balance: balance awal + total pnl vs balance terakhir yang
     tercatat + equity snapshot terakhir.
  4. Kualitas eksekusi: slippage (field mengandung 'slip'), order_failed.
  5. Guard & paritas: signal_skipped_stale, signal_skipped_reentry, mutex,
     server_clock_offset (bukti TZ-fix aktif), max_fav per trade.
  6. Operasional: gap equity snapshot (>20 mnt = kandidat laptop tidur/IPC),
     feed_invalid / stall, hari bursa tercakup (day_rollover).

Jalankan:
  python research/evaluate_live_journal.py [--journal logs/trade_journal.jsonl]
      [--since 2026-09-15] [--out reports/eval_live_XXX.txt]
================================================================================
"""
from __future__ import annotations

import sys
import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_PNL_KEYS = ("realized_total", "pnl", "pnl_usd", "realized", "profit")
_MF_KEYS = ("max_fav_usd", "max_fav", "max_fav_pips")


def _pnl_of(e):
    for k in _PNL_KEYS:
        v = _f(e.get(k))
        if v is not None:
            return v
    return None


def _mf_of(e):
    for k in _MF_KEYS:
        v = _f(e.get(k))
        if v is not None:
            return v
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default=str(ROOT / "logs" / "trade_journal.jsonl"))
    ap.add_argument("--since", default=None, help="hanya event ts >= ini (YYYY-MM-DD)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    lines_raw = Path(args.journal).read_text(encoding="utf-8", errors="replace").splitlines()
    events, bad = [], 0
    for ln in lines_raw:
        ln = ln.strip()
        if not ln:
            continue
        try:
            events.append(json.loads(ln))
        except Exception:
            bad += 1
    if args.since:
        events = [e for e in events if str(e.get("ts", "")) >= args.since]

    buf: list = []

    def P(t: str = "") -> None:
        print(t)
        buf.append(t)

    P("=" * 78)
    P(f"EVALUASI JURNAL LIVE — {args.journal}")
    P(f"  baris: {len(lines_raw):,} | event terbaca: {len(events):,} | rusak: {bad}"
      + (f" | sejak: {args.since}" if args.since else ""))
    if not events:
        P("  (tidak ada event — periksa path / --since)")
        return 1
    P(f"  rentang: {events[0].get('ts')} .. {events[-1].get('ts')}")

    # ---------- 1. sensus & sesi engine ----------
    census = Counter(str(e.get("event", "?")) for e in events)
    P("\n[1] SENSUS EVENT (top 25)")
    for ev, n in census.most_common(25):
        P(f"  {n:6,}  {ev}")

    P("\n[2] SESI ENGINE (engine_start)")
    for e in events:
        if e.get("event") == "engine_start":
            P(f"  {e.get('ts')}  {e.get('engine_version', '?')}  "
              f"balance={e.get('balance')}")

    # ---------- 3. trade ----------
    opens, closes = {}, defaultdict(list)
    for e in events:
        ev = e.get("event")
        tk = e.get("ticket") or e.get("position_id")
        if ev == "order_open" and tk is not None:
            opens[tk] = e
        elif ev in ("position_closed", "position_closed_offline") and tk is not None:
            closes[tk].append(e)

    P(f"\n[3] TRADE — {len(opens)} order_open, {len(closes)} tiket tertutup")
    rows = []
    for tk, o in sorted(opens.items(), key=lambda kv: str(kv[1].get("ts"))):
        cl = closes.get(tk, [])
        pnls = [p for p in (_pnl_of(c) for c in cl) if p is not None]
        pnl = sum(pnls) if pnls else None
        mfs = [m for m in (_mf_of(c) for c in cl) if m is not None]
        rows.append({"ticket": tk, "ts": o.get("ts"), "type": o.get("type"),
                     "closed": bool(cl), "pnl": pnl,
                     "deals": len(cl), "max_fav": (max(mfs) if mfs else None),
                     "close_ts": (max(str(c.get("ts")) for c in cl) if cl else None)})
    done = [r for r in rows if r["closed"]]
    wins = [r for r in done if (r["pnl"] or 0) > 0]
    losses = [r for r in done if (r["pnl"] or 0) <= 0]
    tot = sum(r["pnl"] or 0 for r in done)
    gw = sum(r["pnl"] or 0 for r in wins)
    gl = abs(sum(r["pnl"] or 0 for r in losses))
    if done:
        P(f"  selesai: {len(done)}  | WR {len(wins)}/{len(done)} = {100*len(wins)/len(done):.1f}%"
          f"  | net ${tot:+,.2f}  | PF {(gw/gl if gl else float('inf')):.2f}")
        P(f"  avg win ${sum(r['pnl'] for r in wins)/max(1,len(wins)):+,.2f}  "
          f"avg loss ${sum(r['pnl'] for r in losses)/max(1,len(losses)):+,.2f}  "
          f"terbesar +${max((r['pnl'] or 0) for r in done):,.2f} / "
          f"${min((r['pnl'] or 0) for r in done):,.2f}")
        cur = best = worst = 0
        for r in done:
            cur = (cur + 1) if (r["pnl"] or 0) > 0 else 0
            best = max(best, cur)
        cur = 0
        for r in done:
            cur = (cur + 1) if (r["pnl"] or 0) <= 0 else 0
            worst = max(worst, cur)
        P(f"  streak: menang {best} beruntun / kalah {worst} beruntun")
    unclosed = [r for r in rows if not r["closed"]]
    if unclosed:
        P(f"  ⚠ {len(unclosed)} order tanpa close tercatat: "
          + ", ".join(str(r['ticket']) for r in unclosed[:10]))

    daily = defaultdict(lambda: [0, 0, 0.0])
    for r in done:
        d = str(r["close_ts"])[:10]
        daily[d][0] += 1
        daily[d][1] += 1 if (r["pnl"] or 0) > 0 else 0
        daily[d][2] += r["pnl"] or 0.0
    if daily:
        P("\n  TABEL HARIAN (tanggal close)")
        P(f"  {'tanggal':12} {'n':>3} {'W':>3} {'pnl':>12}")
        for d in sorted(daily):
            n, w, p = daily[d]
            P(f"  {d:12} {n:>3} {w:>3} {p:>+12,.2f}")
        P(f"  {'TOTAL':12} {len(done):>3} {len(wins):>3} {tot:>+12,.2f}")

    # ---------- 4. rekonsiliasi balance ----------
    P("\n[4] REKONSILIASI BALANCE")
    bal_first = None
    for e in events:
        b = _f(e.get("balance"))
        if b:
            bal_first = (str(e.get("ts")), b)
            break
    bal_last_e = None
    for e in reversed(events):
        b = _f(e.get("balance"))
        if b:
            bal_last_e = (str(e.get("ts")), b)
            break
    eq_last = None
    for e in reversed(events):
        if e.get("event") == "equity_snapshot":
            eq_last = (str(e.get("ts")), _f(e.get("equity")) or _f(e.get("equity_usd")))
            if eq_last[1]:
                break
    if bal_first:
        P(f"  balance pertama tercatat : {bal_first[0]}  ${bal_first[1]:,.2f}")
        if bal_last_e:
            P(f"  balance terakhir         : {bal_last_e[0]}  ${bal_last_e[1]:,.2f}")
            if bal_first[1] is not None:
                exp = bal_first[1] + tot
                P(f"  awal + total pnl         : ${exp:,.2f}  "
                  f"{'COCK ✓' if abs(exp - bal_last_e[1]) < 1.0 else f'SELISIH ${bal_last_e[1]-exp:+,.2f}'}")
    if eq_last and eq_last[1]:
        P(f"  equity snapshot terakhir : {eq_last[0]}  ${eq_last[1]:,.2f}")

    # ---------- 5. kualitas eksekusi ----------
    P("\n[5] KUALITAS EKSEKUSI")
    slips = []
    for e in events:
        for k, v in e.items():
            if "slip" in k.lower() and _f(v) is not None:
                slips.append((str(e.get("ts")), e.get("event"), k, _f(v)))
    if slips:
        vals = [s[3] for s in slips]
        P(f"  event dgn field slippage: {len(slips)}  "
          f"(min ${min(vals):+.2f} / max ${max(vals):+.2f})")
        for s in slips[:8]:
            P(f"    {s[0]} {s[1]} {s[2]}={s[3]:+.2f}")
    else:
        P("  slippage: tidak ada field slippage tercatat")
    fails = [e for e in events if e.get("event") == "order_failed"]
    if fails:
        P(f"  order_failed: {len(fails)}")
        for e in fails[:8]:
            P(f"    {e.get('ts')} {e.get('reason', '')}")

    # ---------- 6. guard & paritas ----------
    P("\n[6] GUARD & PARITAS")
    for evname, desc in [
            ("signal_skipped_stale", "bar basi (>120 dtk) dilewati"),
            ("signal_skipped_reentry", "re-entry ditunda (paritas strict_bar_open_entry)"),
            ("mutex_released_stale", "mutex dilepas tanpa kepastian broker"),
            ("server_clock_offset", "deteksi offset jam server (TZ-FIX)")]:
        n = census.get(evname, 0)
        P(f"  {evname:26} {n:5,}  ({desc})")
    offs = sorted({str(e.get('offset_hours')) for e in events
                   if e.get("event") == "server_clock_offset"})
    if offs:
        P(f"    offset jam server terdeteksi: UTC{', UTC'.join(offs)}")
    mf_avail = [r for r in done if r["max_fav"] is not None]
    if mf_avail:
        P(f"  max_fav tercatat pada {len(mf_avail)}/{len(done)} trade "
          f"(median ${sorted(r['max_fav'] for r in mf_avail)[len(mf_avail)//2]:,.2f})")

    # ---------- 7. operasional ----------
    P("\n[7] OPERASIONAL")
    eqs = [e for e in events if e.get("event") == "equity_snapshot"]
    gaps = []
    for a, b in zip(eqs, eqs[1:]):
        try:
            ta = datetime.fromisoformat(str(a.get("ts")))
            tb = datetime.fromisoformat(str(b.get("ts")))
            d = (tb - ta).total_seconds()
            if d > 1200:
                gaps.append((str(a.get("ts")), str(b.get("ts")), d / 60))
        except Exception:
            pass
    P(f"  equity snapshot: {len(eqs):,} | gap >20 mnt: {len(gaps)} "
      f"(kandidat laptop tidur / putus koneksi)")
    for g in gaps[:12]:
        P(f"    {g[0]} -> {g[1]}  ({g[2]:.0f} mnt)")
    n_days = census.get("day_rollover", 0)
    P(f"  hari bursa tercakup (day_rollover): {n_days}")
    stall = sum(n for ev, n in census.items() if "stall" in ev or "invalid" in ev)
    if stall:
        P(f"  event stall/feed-invalid: {stall}")
        for ev, n in census.most_common():
            if "stall" in ev or "invalid" in ev:
                P(f"    {n:6,}  {ev}")

    P("\n" + "=" * 78)
    P("Catatan: bagian '—'/0 = event tidak ada di jurnal (bukan berarti error).")
    P("Evaluasi lengkap vs backtest: lihat prosedur di LAPORAN & sesi evaluasi.")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(buf) + "\n", encoding="utf-8")
        P(f"\nLaporan ditulis ke {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
