"""
================================================================================
BACKTEST M1 BID/ASK — ENGINE AUDIT (ANTI-REPAINT, TANPA LOOKAHEAD)
================================================================================
Dibangun untuk menjawab: "backtest harus diaudit forensik, tidak boleh repaint".

Sumber data : jurnalicas/XAUUSD_M1/*.csv  (bid & ask TERPISAH, UTC)
Keunggulan  : biaya spread masuk IMPLISIT dan benar —
                BUY  masuk di ASK, keluar di BID
                SELL masuk di BID, keluar di ASK
              (engine lama pakai satu harga + `spread_cost` perkiraan)

--------------------------------------------------------------------------------
DAFTAR ANTI-REPAINT  (semuanya diuji oleh research/test_antirepaint.py)
--------------------------------------------------------------------------------
A1  Level sesi hanya dari sesi yang SUDAH TUTUP.
      Asian  03:00-06:59 server -> tersedia mulai 07:00
      London 08:00-11:59 server -> tersedia mulai 12:00
    Sebelum itu dipakai range hari SEBELUMNYA.
    (Kode produksi MELANGGAR ini: pd.merge(on='date') menaruh agregat sepanjang
     hari ke bar pukul 00:00 — bar 03:05 "mengetahui" high 06:55.)
A2  Sinyal hanya memakai bar <= idx  (slice idx-6:idx-1, idx-1, idx-2, idx).
A3  Entry dieksekusi di OPEN bar M1 berikutnya setelah bar sinyal tutup.
A4  Exit long pakai BID, exit short pakai ASK (spread jadi biaya nyata).
A5  Intrabar KONSERVATIF: dalam satu bar M1, SL diuji LEBIH DULU daripada TP.
A6  SL yang baru dinaikkan (BE / trail) baru efektif bar M1 berikutnya.
A7  Zona waktu: data UTC -> waktu server Exness (Europe/Athens, EET/EEST),
    DST ditangani benar sehingga batas jam config berlaku apa adanya.
A8  Simulasi berjalan MAJU per bar M1; tidak ada akses ke indeks > bar aktif.
================================================================================
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

SERVER_TZ = ZoneInfo("Europe/Athens")     # Exness = EET/EEST
PIP = 0.10                                # 1 "pip" strategi = $0.10
OZ_PER_LOT = 100.0


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StratCfg:
    name: str
    sl_pips: float = 150.0
    tp1_pips: float = 187.5
    tp2_pips: float = 375.0
    tp3_pips: float = 562.5
    r1: float = 0.30
    r2: float = 0.25
    r3: float = 0.25
    runner: float = 0.20
    trail_step_pips: float = 100.0
    trail_lock_pips: float = 30.0
    use_killzone: bool = False
    max_trades_per_day: int = 999
    max_consec_losses: int = 999
    max_spread_usd: float = 1.20          # guard, disetel ke feed ini (lihat laporan)
    risk_usd: float = 500.0               # fixed $ risk per trade (5% dari $10k)


CFG_CURRENT = StratCfg(name="A - PLAN SAAT INI (config.py)")

CFG_RECO = StratCfg(
    name="B - REKOMENDASI (target dipadatkan + killzone + CB)",
    tp1_pips=112.5,      # 0.75R - terjangkau dalam median hold live 1,5 jam
    tp2_pips=187.5,      # 1.25R
    tp3_pips=300.0,      # 2.00R
    trail_step_pips=60.0,
    trail_lock_pips=25.0,
    use_killzone=True,
    max_trades_per_day=6,
    max_consec_losses=3,
)

CFG_RECO_NOKZ = replace(CFG_RECO, name="C - REKOMENDASI tanpa killzone (ablasi)",
                        use_killzone=False, max_trades_per_day=999,
                        max_consec_losses=999)


# --------------------------------------------------------------------------- #
def load_m1(path, start, end, trim_partial_days: bool = True) -> pd.DataFrame:
    """Muat M1 bid/ask + kolom waktu server (EET/EEST).

    trim_partial_days: buang hari-server pertama & terakhir yang tidak lengkap.
    Perlu karena data ber-zona UTC digeser +2/+3 jam ke waktu server, sehingga
    jendela [start, end] selalu menyisakan pecahan hari di kedua ujungnya.
    """
    d = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    d = d.loc[start:end].copy()
    if d.empty:
        raise ValueError(f"tidak ada bar pada {start} .. {end}")
    srv = d.index.tz_localize("UTC").tz_convert(SERVER_TZ)
    d["srv_hour"] = srv.hour.to_numpy()
    d["srv_min"] = srv.minute.to_numpy()
    d["srv_date"] = srv.date
    d["spread_usd"] = (d["close_ask"] - d["close_bid"]).to_numpy()
    if trim_partial_days:
        cnt = d.groupby("srv_date").size()
        full = cnt[cnt >= 1000].index            # hari bursa normal ~1440 bar
        if len(full):
            d = d[d["srv_date"].isin(set(full))]
    return d


def session_levels_norepaint(d: pd.DataFrame) -> pd.DataFrame:
    """[A1] Asian/London high-low TANPA lookahead (satu pass maju)."""
    out = d
    h = out["srv_hour"].to_numpy()
    hi = out["high_bid"].to_numpy()
    lo = out["low_bid"].to_numpy()
    dates = out["srv_date"].to_numpy()
    n = len(out)

    a_hi = np.empty(n); a_lo = np.empty(n)
    l_hi = np.empty(n); l_lo = np.empty(n)

    cur = None
    run_ah = run_al = run_lh = run_ll = np.nan
    pub_ah = pub_al = pub_lh = pub_ll = np.nan          # nilai yang "terpublikasi"
    day_done_ah = day_done_al = np.nan
    day_done_lh = day_done_ll = np.nan

    for i in range(n):
        if dates[i] != cur:
            # rollover hari: apa yang selesai kemarin jadi cadangan
            pub_ah, pub_al = day_done_ah, day_done_al
            pub_lh, pub_ll = day_done_lh, day_done_ll
            cur = dates[i]
            run_ah = run_al = run_lh = run_ll = np.nan
        hr = h[i]
        if 3 <= hr < 7:
            run_ah = hi[i] if np.isnan(run_ah) else max(run_ah, hi[i])
            run_al = lo[i] if np.isnan(run_al) else min(run_al, lo[i])
        elif hr == 7:
            day_done_ah, day_done_al = run_ah, run_al   # Asian TUTUP tepat 07:00
        if 8 <= hr < 12:
            run_lh = hi[i] if np.isnan(run_lh) else max(run_lh, hi[i])
            run_ll = lo[i] if np.isnan(run_ll) else min(run_ll, lo[i])
        elif hr == 12:
            day_done_lh, day_done_ll = run_lh, run_ll   # London TUTUP tepat 12:00
        # nilai yang boleh dilihat bar ini
        if hr >= 7 and not np.isnan(day_done_ah):
            a_hi[i], a_lo[i] = day_done_ah, day_done_al
        else:
            a_hi[i], a_lo[i] = pub_ah, pub_al
        if hr >= 12 and not np.isnan(day_done_lh):
            l_hi[i], l_lo[i] = day_done_lh, day_done_ll
        else:
            l_hi[i], l_lo[i] = pub_lh, pub_ll

    out = out.assign(asian_high=a_hi, asian_low=a_lo,
                     london_high=l_hi, london_low=l_lo)
    return out


def session_levels_repaint(d: pd.DataFrame) -> pd.DataFrame:
    """REPLIKA BUG PRODUKSI (src/indicators/sessions.py) untuk mengukur biasnya.

    Agregat SEPANJANG HARI di-merge ke semua bar tanggal itu, lalu ffill.
    Hanya dipakai sebagai pembanding — JANGAN dipakai untuk angka laporan.
    """
    out = d.copy()
    am = (out["srv_hour"] >= 3) & (out["srv_hour"] < 7)
    lm = (out["srv_hour"] >= 8) & (out["srv_hour"] < 12)
    a = out[am].groupby("srv_date").agg(asian_high=("high_bid", "max"),
                                        asian_low=("low_bid", "min"))
    l = out[lm].groupby("srv_date").agg(london_high=("high_bid", "max"),
                                        london_low=("low_bid", "min"))
    out = out.join(a, on="srv_date").join(l, on="srv_date")
    for c, fb in (("asian_high", "high_bid"), ("asian_low", "low_bid")):
        out[c] = out[c].ffill().fillna(out[fb])
    for c, fb in (("london_high", "asian_high"), ("london_low", "asian_low")):
        out[c] = out[c].ffill().fillna(out[fb])
    return out


def resample_m5(d: pd.DataFrame) -> pd.DataFrame:
    """[A2] M5 dari M1 bid. Label waktu = AWAL bar (konvensi MT5)."""
    m5 = d.resample("5min", label="left", closed="left").agg(
        open=("open_bid", "first"), high=("high_bid", "max"),
        low=("low_bid", "min"), close=("close_bid", "last"),
        n=("open_bid", "count"), spread=("spread_usd", "last"),
        srv_hour=("srv_hour", "last"), srv_min=("srv_min", "last"),
        asian_high=("asian_high", "last"), asian_low=("asian_low", "last"),
        london_high=("london_high", "last"), london_low=("london_low", "last"))
    return m5[m5["n"] >= 4].copy()


def in_killzone(hour: int, minute: int) -> bool:
    """London burst 10:00-12:00 & NY burst 15:30-17:30 (waktu server)."""
    return (10 <= hour < 12 or (hour == 15 and minute >= 30)
            or hour == 16 or (hour == 17 and minute <= 30))


def signal_at(m5: pd.DataFrame, i: int, cfg: StratCfg) -> str | None:
    """[A2] Setup ICT pada bar M5 ke-i yang SUDAH TUTUP."""
    if i < 10:
        return None
    row = m5.iloc[i]
    if pd.isna(row["asian_high"]) or pd.isna(row["asian_low"]) \
       or pd.isna(row["london_high"]) or pd.isna(row["london_low"]):
        return None
    if cfg.use_killzone and not in_killzone(int(row["srv_hour"]), int(row["srv_min"])):
        return None
    if row["spread"] > cfg.max_spread_usd:
        return None
    c, o = row["close"], row["open"]
    bsl = max(row["asian_high"], row["london_high"])
    ssl = min(row["asian_low"], row["london_low"])
    bull_fvg = row["low"] > m5["high"].iat[i - 2] + 0.30
    bear_fvg = row["high"] < m5["low"].iat[i - 2] - 0.30
    swing_h = m5["high"].iloc[i - 6:i - 1].max()
    swing_l = m5["low"].iloc[i - 6:i - 1].min()
    if (m5["low"].iat[i - 1] <= ssl or m5["low"].iat[i - 2] <= ssl) and \
       ((c > o) and (c > swing_h or bull_fvg)):
        return "BUY"
    if (m5["high"].iat[i - 1] >= bsl or m5["high"].iat[i - 2] >= bsl) and \
       ((c < o) and (c < swing_l or bear_fvg)):
        return "SELL"
    return None


# --------------------------------------------------------------------------- #
class Position:
    __slots__ = ("dir", "entry", "lots", "sl", "tp1", "tp2", "tp3",
                 "t1", "t2", "t3", "mfe", "realized", "trail", "be",
                 "open_ts", "spread_entry", "pending_sl", "cfg")

    def __init__(self, sig, fill, lots, cfg: StratCfg, ts):
        d = 1 if sig == "BUY" else -1
        sl_d = cfg.sl_pips * PIP
        self.dir, self.entry, self.lots, self.cfg = d, float(fill), lots, cfg
        self.sl = fill - d * sl_d
        self.tp1 = fill + d * cfg.tp1_pips * PIP
        self.tp2 = fill + d * cfg.tp2_pips * PIP
        self.tp3 = fill + d * cfg.tp3_pips * PIP
        self.t1 = self.t2 = self.t3 = self.be = False
        self.mfe = 0.0
        self.realized = 0.0
        self.trail = 0
        self.open_ts = ts
        self.spread_entry = 0.0
        self.pending_sl = None

    def remaining(self) -> float:
        c = self.cfg
        rem = 1.0
        if self.t1:
            rem -= c.r1
        if self.t2:
            rem -= c.r2
        if self.t3:
            rem -= c.r3
        return rem

    def raise_sl(self, target: float):
        """[A6] hanya dicatat; efektif bar M1 berikutnya."""
        if self.dir == 1:
            if target > self.sl:
                self.pending_sl = target
        elif target < self.sl:
            self.pending_sl = target

    def book(self, exit_price: float, reason: str) -> dict:
        pnl = self.realized + self.dir * (exit_price - self.entry) * \
            (self.lots * self.remaining()) * OZ_PER_LOT
        res = "WIN" if pnl > 1 else ("BE" if pnl >= -1 else "LOSS")
        return {"open_ts": self.open_ts, "type": "BUY" if self.dir == 1 else "SELL",
                "pnl": round(pnl, 2), "res": res, "reason": reason,
                "mfe": round(self.mfe, 3), "mfe_pips": round(self.mfe / PIP, 1),
                "tp1": self.t1, "tp2": self.t2, "tp3": self.t3,
                "trail": self.trail, "be": self.be, "lots": self.lots,
                "spread_entry": round(self.spread_entry, 3),
                "sl_pips": round(self.cfg.sl_pips, 1)}


def _tier_pnl(p: Position, lvl: float, ratio: float) -> float:
    return p.dir * (lvl - p.entry) * (p.lots * ratio) * OZ_PER_LOT


def run_backtest(m1: pd.DataFrame, m5: pd.DataFrame, cfg: StratCfg,
                 capital0: float = 10_000.0, tp_first: bool = False,
                 trade_from=None, random_seed: int | None = None,
                 n_random: int | None = None) -> dict:
    """[A8] Satu pass MAJU di sepanjang bar M1.

    tp_first=True  -> varian OPTIMIS (TP diuji sebelum SL) untuk uji sensitivitas.
                      Default False = [A5] pesimis, yang dipakai di laporan.
    """
    sl_d = cfg.sl_pips * PIP
    step_d, lock_d = cfg.trail_step_pips * PIP, cfg.trail_lock_pips * PIP

    t1 = m1.index
    m1_map = {ts: k for k, ts in enumerate(t1)}
    hb, lb = m1["high_bid"].to_numpy(), m1["low_bid"].to_numpy()
    ha, la = m1["high_ask"].to_numpy(), m1["low_ask"].to_numpy()
    oa, ob = m1["open_ask"].to_numpy(), m1["open_bid"].to_numpy()
    spr = m1["spread_usd"].to_numpy()
    n1 = len(m1)

    # pra-hitung sinyal (hanya bergantung bar <= i) + bar M1 tempat eksekusi
    entries = {}
    if random_seed is None:
        for i in range(10, len(m5)):
            sig = signal_at(m5, i, cfg)
            if sig is None:
                continue
            et = m5.index[i] + pd.Timedelta(minutes=5)
            j = t1.searchsorted(et)             # [A3] bar M1 berikutnya
            if j < n1 and t1[j] == et:
                entries[j] = sig
    else:
        # BASELINE ACAK: jumlah & waktu entry acak, manajemen posisi identik.
        # Dipakai untuk mengukur apakah sinyal menambah edge di atas keberuntungan.
        rng = np.random.default_rng(random_seed)
        cand = [i for i in range(10, len(m5) - 1)
                if m5["spread"].iat[i] <= cfg.max_spread_usd
                and (not cfg.use_killzone
                     or in_killzone(int(m5["srv_hour"].iat[i]), int(m5["srv_min"].iat[i])))]
        size = n_random or 4000
        pick = rng.choice(cand, size=min(len(cand), size), replace=False)
        for i in pick:
            et = m5.index[int(i)] + pd.Timedelta(minutes=5)
            j = t1.searchsorted(et)
            if j < n1 and t1[j] == et:
                entries[j] = "BUY" if rng.random() < 0.5 else "SELL"

    tf = pd.Timestamp(trade_from).date() if trade_from is not None else None
    capital, trades, eq = capital0, [], []
    pos: Position | None = None
    per_day, consec, cur_day = 0, 0, None
    m1_day = m1["srv_date"].to_numpy()      # batas hari = tengah malam SERVER

    for k in range(n1):
        if m1_day[k] != cur_day:
            cur_day = m1_day[k]
            per_day = 0
            consec = 0        # icas_strategy.reset_daily_stats_if_new_day()

        if pos is not None:
            d = pos.dir
            if pos.pending_sl is not None:                # [A6]
                pos.sl = pos.pending_sl
                pos.pending_sl = None
            if d == 1:
                pos.mfe = max(pos.mfe, hb[k] - pos.entry)
                hit_sl = lb[k] <= pos.sl
                hit_tp1 = (not pos.t1) and hb[k] >= pos.tp1
                # [A5] SL diuji lebih dulu kecuali varian uji tp_first
                if hit_sl and not (tp_first and hit_tp1):
                    trades.append(pos.book(pos.sl, "SL"))
                    capital += trades[-1]["pnl"]; eq.append(capital)
                    consec = consec + 1 if trades[-1]["res"] == "LOSS" else 0
                    pos = None
                else:
                    if hit_tp1:
                        pos.realized += _tier_pnl(pos, pos.tp1, cfg.r1)
                        pos.t1 = pos.be = True
                        pos.raise_sl(pos.entry)
                    if pos.t1 and not pos.t2 and hb[k] >= pos.tp2:
                        pos.realized += _tier_pnl(pos, pos.tp2, cfg.r2)
                        pos.t2 = True
                    if pos.t2 and not pos.t3 and hb[k] >= pos.tp3:
                        pos.realized += _tier_pnl(pos, pos.tp3, cfg.r3)
                        pos.t3 = True
                        pos.raise_sl(pos.tp1)
                    kk = int(pos.mfe // step_d)
                    if kk >= 1 and kk > pos.trail:
                        pos.raise_sl(pos.entry + (kk - 1) * step_d + lock_d)
                        pos.trail = kk
            else:
                pos.mfe = max(pos.mfe, pos.entry - la[k])
                hit_sl = ha[k] >= pos.sl
                hit_tp1 = (not pos.t1) and la[k] <= pos.tp1
                if hit_sl and not (tp_first and hit_tp1):
                    trades.append(pos.book(pos.sl, "SL"))
                    capital += trades[-1]["pnl"]; eq.append(capital)
                    consec = consec + 1 if trades[-1]["res"] == "LOSS" else 0
                    pos = None
                else:
                    if hit_tp1:
                        pos.realized += _tier_pnl(pos, pos.tp1, cfg.r1)
                        pos.t1 = pos.be = True
                        pos.raise_sl(pos.entry)
                    if pos.t1 and not pos.t2 and la[k] <= pos.tp2:
                        pos.realized += _tier_pnl(pos, pos.tp2, cfg.r2)
                        pos.t2 = True
                    if pos.t2 and not pos.t3 and la[k] <= pos.tp3:
                        pos.realized += _tier_pnl(pos, pos.tp3, cfg.r3)
                        pos.t3 = True
                        pos.raise_sl(pos.tp1)
                    kk = int(pos.mfe // step_d)
                    if kk >= 1 and kk > pos.trail:
                        pos.raise_sl(pos.entry - ((kk - 1) * step_d + lock_d))
                        pos.trail = kk

        if pos is None and k in entries:
            if per_day < cfg.max_trades_per_day and consec < cfg.max_consec_losses \
               and capital > 0 and (tf is None or m1_day[k] >= tf):
                sig = entries[k]
                fill = oa[k] if sig == "BUY" else ob[k]
                lots = max(0.01, round(cfg.risk_usd / (sl_d * OZ_PER_LOT), 2))
                pos = Position(sig, fill, lots, cfg, t1[k])
                pos.spread_entry = spr[k]
                per_day += 1

    tdf = pd.DataFrame(trades)
    m5w = m5 if tf is None else m5[m5.index >= pd.Timestamp(trade_from)]
    return _stats(tdf, eq, capital0, m5w, cfg)


def _stats(tdf, eq, capital0, m5, cfg) -> dict:
    n = len(tdf)
    base = {"cfg": cfg.name, "trades": n, "sl_pips": cfg.sl_pips,
            "tp1_pips": cfg.tp1_pips, "tp2_pips": cfg.tp2_pips,
            "tp3_pips": cfg.tp3_pips, "killzone": cfg.use_killzone,
            "tdf": tdf}
    if n == 0:
        return base
    wins = tdf[tdf.pnl > 1]; losses = tdf[tdf.pnl < -1]; be = tdf[(tdf.pnl <= 1) & (tdf.pnl >= -1)]
    gw = tdf.loc[tdf.pnl > 0, "pnl"].sum(); gl = abs(tdf.loc[tdf.pnl < 0, "pnl"].sum())
    # ekuitas = modal + PnL kumulatif (dulu salah: cumsum tidak ditambah modal)
    e = capital0 + pd.Series([0.0] + list(tdf.pnl.cumsum()))
    dd_abs = float((e.cummax() - e).max())
    dd_pct = float(((e.cummax() - e) / e.cummax() * 100).max())
    hold = pd.to_datetime(tdf.open_ts)
    days = m5.index.normalize().nunique()
    span = (hold.max() - hold.min()).days + 1
    base.update({
        "wins": len(wins), "be": len(be), "losses": len(losses),
        "wr_pct": round(len(wins) / n * 100, 2),
        "nlr_pct": round((len(wins) + len(be)) / n * 100, 2),
        "pf": round(gw / gl, 3) if gl > 0 else float("inf"),
        "net": round(float(tdf.pnl.sum()), 2),
        "expectancy": round(float(tdf.pnl.mean()), 2),
        "avg_win": round(float(wins.pnl.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.pnl.mean()), 2) if len(losses) else 0.0,
        "dd_abs": round(dd_abs, 2), "dd_pct": round(dd_pct, 2),
        "final_capital": round(capital0 + float(tdf.pnl.sum()), 2),
        "roi_pct": round(float(tdf.pnl.sum()) / capital0 * 100, 2),
        "trades_per_day": round(n / days, 2),
        "trades_per_active_day": round(n / max(1, hold.dt.normalize().nunique()), 2),
        "calendar_days": span, "m5_days": days,
        "tp1_rate": round(float(tdf.tp1.mean()) * 100, 1),
        "tp2_rate": round(float(tdf.tp2.mean()) * 100, 1),
        "tp3_rate": round(float(tdf.tp3.mean()) * 100, 1),
        "trail_rate": round(float((tdf.trail >= 1).mean()) * 100, 1),
        "median_mfe": round(float(tdf.mfe.median()), 2),
        "avg_spread_entry": round(float(tdf.spread_entry.mean()), 3),
    })
    return base
