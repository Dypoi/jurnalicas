"""
========================================================================================
MODEL ICAS — STRATEGI G4 (KASKADE MTF H1→M30→M15→M5, EKSEKUSI M5)
========================================================================================
Ditambahkan 09 Sep 2026 — menggantikan sinyal choch+sesi (icas-v2) sesuai hasil
tuning riset `LAPORAN_TUNING_SCALPING.md` (rev 2.3):

  G4 = sinyal W24h (kaskade 4 lapis, likuiditas PDH/PDL jendela 24 jam)
       + trailing cepat 50/30, TP plan 187.5/375/562.5, SL 150, risk 1%.

  Backtest setahun (2025-09-01..2026-09-01, risk 1%, engine audit anti-repaint):
    1.338 trade | WR 73.0% | PF 1.12 | +$4.493 | DD 19.5% | ~103 entry/bulan
    Signifikan vs 32-seed kontrol acak (p=0.000).

KASKADE (semua kausal — nilai HTF hanya dari bar yang SUDAH TERTUTUP saat
bar M5 sinyal dievaluasi; replika persis `research/backtest_m1_audit.py`):

  L1  H1   bias arah      : close M5 vs EMA200-H1 (bar H1 berlabel <= t-1 jam)
  L2  M30  likuiditas     : sweep PDH/PDL (high/low HARI BURSA SEBELUMNYA,
                            batas hari UTC, pad ke hari bursa terakhir <= t-24j)
                            dalam jendela 288 bar M5 (24 jam) terakhir
  L3  M15  struktur       : CHoCH — close menembus swing high/low 5-bar M15
                            (window posisional [k-6..k-2], k = bar M15 terakhir
                            berlabel <= t-15 menit)
  L4  M5   trigger        : displacement candle + FVG $0.30 / break swing 5-bar
                            (window [i-6..i-2], bar i-1 dikecualikan — pola
                            "displacement meninggalkan behind")
  EX  M5   eksekusi       : sinyal dihitung PADA candle M5 yang baru tertutup;
                            entry market order ~open candle berikutnya.
                            BUY mengisi di ask, SELL di bid (spread riil).
                            SL/TP langsung aktif di broker (equivalen
                            manage_entry_bar engine). Mutex 1-posisi membuat
                            perilaku identik strict_bar_open_entry engine.

PARITAS DENGAN ENGINE RISET — diverifikasi `research/g4_parity_check.py`
(sinyal identik bar-per-bar sepanjang setahun data 2025-2026).
========================================================================================
"""
from __future__ import annotations

from typing import Optional, Tuple
import pandas as pd

from config import config
from src.strategy.icas_strategy import IcasSignal


def frames_from_raw(m5_raw: pd.DataFrame, m15_raw: pd.DataFrame, h1_raw: pd.DataFrame,
                    server_tz="Europe/Athens") -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Ubah raw candle MT5 (kolom 'time' = waktu SERVER naive + OHLC) menjadi
    frame UTC ber-index DatetimeIndex yang BERAKHIR pada bar TERTUTUP terakhir.

    Konversi server→UTC memakai zone Europe/Athens (EET/EEST, konvensi Exness —
    sama dengan SERVER_TZ di research). Bar terakhir (masih berjalan) DIBUANG.
    Return None bila data kurang / tidak bisa dipakai.
    """
    try:
        tz = pd.Timestamp("2026-01-01", tz=server_tz).tz
    except Exception:
        return None

    def _prep(raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        if raw is None or raw.empty or "time" not in raw.columns:
            return None
        df = raw.copy()
        idx = pd.DatetimeIndex(pd.to_datetime(df["time"]))
        try:
            idx = idx.tz_localize(tz).tz_convert("UTC").tz_localize(None)
        except Exception:
            return None
        df.index = idx
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[["open", "high", "low", "close"]]
        df = df.dropna()
        return df.iloc[:-1] if len(df) > 1 else None   # buang bar berjalan

    m5, m15, h1 = _prep(m5_raw), _prep(m15_raw), _prep(h1_raw)
    if m5 is None or m15 is None or h1 is None:
        return None
    return m5, m15, h1


def _h1_ema_at(df_h1: pd.DataFrame, t_i: pd.Timestamp, ema_span: int = 200,
               min_h1_bars: int = 260) -> Optional[float]:
    """EMA200 close H1 pada GRID PER-JAM (slot tanpa bar bursa = NaN; ewm
    me-carry nilai) — replika eksak `h1_close.resample("1h").ewm(...)` di
    research/tuning_mtf.py add_mtf_columns. Grid per-jam, BUKAN bar bursa
    terkompaksi: ewm dengan ignore_na=False memberi bobot decay ekstra pada
    gap weekend, sehingga grid vs terkompaksi menghasilkan EMA berbeda
    (terukur ~0.1% — cukup untuk membalik bar marginal).

    Bar H1 terakhir yang diizinkan: label <= t_i - 1 jam (bar itu close
    tepat pada/sblm t_i — kausal, identik _map_htf(dur="1h") riset yang
    mem-pad target t-1h ke slot jam terakhir).
    Return None bila histori H1 belum cukup (min_h1_bars) — live daemon
    selalu punya >= 1500 bar sehingga gate ini hanya aktif saat warm-up.
    """
    if df_h1 is None or df_h1.empty:
        return None
    h1_cut = pd.Timestamp(t_i) - pd.Timedelta(hours=1)
    h1_slot = h1_cut.floor("1h")
    if int((df_h1.index <= h1_cut).sum()) < min_h1_bars:
        return None
    grid_idx = pd.date_range(df_h1.index[0], h1_slot, freq="1h")
    if len(grid_idx) == 0:
        return None
    grid = df_h1["close"].reindex(grid_idx)
    return float(grid.ewm(span=ema_span, adjust=False).mean().iloc[-1])


def _pd_levels(df_m5: pd.DataFrame, t_i: pd.Timestamp) -> Optional[Tuple[float, float]]:
    """PDH/PDL = high/low HARI BURSA terakhir yang berlabel <= t_i - 24 jam
    (hari UTC dari bar M5; weekend otomatis ter-pad ke hari bursa terakhir —
    identik resample("1D").dropna() + _map_htf(dur="1D") riset).
    Return (pd_high, pd_low) atau None bila belum ada hari sebelumnya."""
    days = df_m5.index.normalize()
    uniq = days.unique()
    pos = uniq.searchsorted(pd.Timestamp(t_i) - pd.Timedelta(hours=24), side="right") - 1
    if pos < 0:
        return None
    day_mask = days == uniq[pos]
    return float(df_m5["high"][day_mask].max()), float(df_m5["low"][day_mask].min())


def g4_signal_at(df_m5: pd.DataFrame, df_m15: pd.DataFrame, df_h1: pd.DataFrame,
                 i: int, sweep_bars: int = 288, fvg_buffer: float = 0.30,
                 ema_span: int = 200, min_h1_bars: int = 260) -> Optional[str]:
    """Sinyal G4 pada bar M5 ke-i (bar TERAKHIR frame = bar yang baru tertutup).
    Murni geometri harga — tanpa akses config/akun (mudah di-parity-test).
    Return 'BUY' / 'SELL' / None. Replika eksak signal_at(mode='mtf',
    m30_mode='pd', sweep_bars=288) di research/backtest_m1_audit.py.
    """
    if i < 10 or i >= len(df_m5):
        return None
    t_i = df_m5.index[i]
    c = float(df_m5["close"].iloc[i])
    o = float(df_m5["open"].iloc[i])

    # ---- L1: bias H1 — EMA200 pada grid per-jam (lihat _h1_ema_at) ----
    h1_ema = _h1_ema_at(df_h1, t_i, ema_span=ema_span, min_h1_bars=min_h1_bars)
    if h1_ema is None:
        return None
    bias_bull = c > h1_ema
    bias_bear = c < h1_ema

    # ---- L2: likuiditas PDH/PDL — hari bursa terakhir berlabel <= t_i - 24 jam
    # (pad ke hari bursa sebelumnya saat t-24j jatuh di weekend), disweep
    # dalam jendela `sweep_bars` bar M5 terakhir sebelum i (eksklusif-i) ----
    lvl = _pd_levels(df_m5, t_i)
    if lvl is None:
        return None
    pdh, pdl = lvl
    lo_win = df_m5["low"].iloc[max(0, i - sweep_bars):i]
    hi_win = df_m5["high"].iloc[max(0, i - sweep_bars):i]
    sweep_buy = bool((lo_win <= pdl).any())
    sweep_sell = bool((hi_win >= pdh).any())

    # ---- L3: CHoCH M15 — swing 5-bar posisional [k-6..k-2], k = bar M15
    # terakhir berlabel <= t_i - 15 menit (rolling(5).shift(2) riset) ----
    k = df_m15.index.searchsorted(t_i - pd.Timedelta(minutes=15), side="right") - 1
    if k < 6:
        return None
    sw15_h = float(df_m15["high"].iloc[k - 6:k - 1].max())
    sw15_l = float(df_m15["low"].iloc[k - 6:k - 1].min())
    choch_bull = c > sw15_h
    choch_bear = c < sw15_l

    # ---- L4: trigger M5 — displacement + FVG / break swing 5-bar ----
    swing_h5 = float(df_m5["high"].iloc[i - 6:i - 1].max())
    swing_l5 = float(df_m5["low"].iloc[i - 6:i - 1].min())
    bull_fvg = float(df_m5["low"].iloc[i]) > float(df_m5["high"].iloc[i - 2]) + fvg_buffer
    bear_fvg = float(df_m5["high"].iloc[i]) < float(df_m5["low"].iloc[i - 2]) - fvg_buffer
    trig_bull = (c > o) and (c > swing_h5 or bull_fvg)
    trig_bear = (c < o) and (c < swing_l5 or bear_fvg)

    if bias_bull and sweep_buy and choch_bull and trig_bull:
        return "BUY"
    if bias_bear and sweep_sell and choch_bear and trig_bear:
        return "SELL"
    return None


def g4_cascade_detail(df_m5: pd.DataFrame, df_m15: pd.DataFrame, df_h1: pd.DataFrame,
                      spread_usd: Optional[float] = None, sweep_bars: int = 288,
                      fvg_buffer: float = 0.30, ema_span: int = 200,
                      min_h1_bars: int = 260) -> dict:
    """[DASHBOARD 09 Sep 2026] Diagnostik kaskade G4 per-lapis pada bar M5
    TERTUTUP terakhir (frame hasil frames_from_raw — bar berjalan sudah dibuang,
    identik cara daemon mengevaluasi). READ-ONLY untuk UI "kenapa belum entry /
    kenapa BUY / kenapa SELL"; jalur trading tetap G4Strategy.evaluate yang
    paritas-terbukti — JANGAN mengganti logic dua fungsi itu dengan fungsi ini.

    Return dict: ok, bar_time, close, bars, warmup_ok, layers (list per-lapis
    dengan status jalur BUY & SELL + teks penjelas), signal (BUY/SELL/None).
    """
    res: dict = {"ok": False, "signal": None, "layers": [], "warmup_ok": False}
    if df_m5 is None or len(df_m5) < 10:
        res["error"] = "frame M5 kosong / kurang dari 10 bar"
        return res
    i = len(df_m5) - 1
    t_i = df_m5.index[i]
    c = float(df_m5["close"].iloc[i])
    o = float(df_m5["open"].iloc[i])
    res.update({"ok": True, "bar_time": str(t_i), "close": round(c, 2),
                "open": round(o, 2), "spread_usd": spread_usd,
                "bars": {"m5": len(df_m5),
                         "m15": 0 if df_m15 is None else len(df_m15),
                         "h1": 0 if df_h1 is None else len(df_h1)}})
    res["warmup_ok"] = bool(
        len(df_m5) >= 350 and df_m15 is not None and len(df_m15) >= 20
        and df_h1 is not None and len(df_h1) >= min_h1_bars)

    # ---- L1: bias H1 ----
    h1_ema = (_h1_ema_at(df_h1, t_i, ema_span=ema_span, min_h1_bars=min_h1_bars)
              if df_h1 is not None and len(df_h1) else None)
    if h1_ema is None:
        b1 = s1 = False
        l1 = {"name": "L1 · Bias H1 (EMA200)", "buy_ok": False, "sell_ok": False,
              "buy_text": "EMA200-H1 belum valid (histori kurang)",
              "sell_text": "EMA200-H1 belum valid"}
    else:
        b1, s1 = c > h1_ema, c < h1_ema
        l1 = {"name": "L1 · Bias H1 (EMA200)", "buy_ok": b1, "sell_ok": s1,
              "buy_text": f"close {c:.2f} {'>' if b1 else '≤'} EMA {h1_ema:.2f}",
              "sell_text": f"close {c:.2f} {'<' if s1 else '≥'} EMA {h1_ema:.2f}",
              "ema": round(h1_ema, 2)}

    # ---- L2: sweep PDH/PDL ----
    lvl = _pd_levels(df_m5, t_i)
    if lvl is None:
        b2 = s2 = False
        l2 = {"name": f"L2 · Sweep PDH/PDL (24j / {sweep_bars} bar)",
              "buy_ok": False, "sell_ok": False,
              "buy_text": "belum ada hari bursa sebelumnya", "sell_text": "—"}
    else:
        pdh, pdl = lvl
        lo_win = df_m5["low"].iloc[max(0, i - sweep_bars):i]
        hi_win = df_m5["high"].iloc[max(0, i - sweep_bars):i]
        b2 = bool((lo_win <= pdl).any())
        s2 = bool((hi_win >= pdh).any())
        l2 = {"name": f"L2 · Sweep PDH/PDL (24j / {sweep_bars} bar)",
              "buy_ok": b2, "sell_ok": s2,
              "buy_text": (f"low 24j ≤ PDL {pdl:.2f} (sweep ✅)" if b2
                           else f"low 24j belum tembus PDL {pdl:.2f}"),
              "sell_text": (f"high 24j ≥ PDH {pdh:.2f} (sweep ✅)" if s2
                            else f"high 24j belum tembus PDH {pdh:.2f}"),
              "pdh": round(pdh, 2), "pdl": round(pdl, 2)}

    # ---- L3: CHoCH M15 ----
    if df_m15 is None or len(df_m15) < 7:
        b3 = s3 = False
        l3 = {"name": "L3 · CHoCH M15 (swing 5-bar)", "buy_ok": False,
              "sell_ok": False, "buy_text": "histori M15 kurang",
              "sell_text": "histori M15 kurang"}
    else:
        k = df_m15.index.searchsorted(t_i - pd.Timedelta(minutes=15), side="right") - 1
        if k < 6:
            b3 = s3 = False
            l3 = {"name": "L3 · CHoCH M15 (swing 5-bar)", "buy_ok": False,
                  "sell_ok": False, "buy_text": "swing M15 belum terbentuk",
                  "sell_text": "swing M15 belum terbentuk"}
        else:
            sw15_h = float(df_m15["high"].iloc[k - 6:k - 1].max())
            sw15_l = float(df_m15["low"].iloc[k - 6:k - 1].min())
            b3, s3 = c > sw15_h, c < sw15_l
            l3 = {"name": "L3 · CHoCH M15 (swing 5-bar)", "buy_ok": b3, "sell_ok": s3,
                  "buy_text": (f"close {c:.2f} > swing {sw15_h:.2f} ✅" if b3
                               else f"close {c:.2f} ≤ swing {sw15_h:.2f}"),
                  "sell_text": (f"close {c:.2f} < swing {sw15_l:.2f} ✅" if s3
                                else f"close {c:.2f} ≥ swing {sw15_l:.2f}"),
                  "swing_h": round(sw15_h, 2), "swing_l": round(sw15_l, 2)}

    # ---- L4: displacement/FVG M5 ----
    if i < 6:
        b4 = s4 = False
        l4 = {"name": "L4 · Displacement + FVG M5", "buy_ok": False,
              "sell_ok": False, "buy_text": "bar kurang", "sell_text": "bar kurang"}
    else:
        swing_h5 = float(df_m5["high"].iloc[i - 6:i - 1].max())
        swing_l5 = float(df_m5["low"].iloc[i - 6:i - 1].min())
        bull_fvg = float(df_m5["low"].iloc[i]) > float(df_m5["high"].iloc[i - 2]) + fvg_buffer
        bear_fvg = float(df_m5["high"].iloc[i]) < float(df_m5["low"].iloc[i - 2]) - fvg_buffer
        b4 = (c > o) and (c > swing_h5 or bull_fvg)
        s4 = (c < o) and (c < swing_l5 or bear_fvg)
        l4 = {"name": "L4 · Displacement + FVG M5", "buy_ok": b4, "sell_ok": s4,
              "buy_text": ("candle bull " + ("+ break swing" if c > swing_h5 else "")
                           + (" + FVG" if bull_fvg else "")) if b4
                          else "candle M5 belum displacement bull",
              "sell_text": ("candle bear " + ("+ break swing" if c < swing_l5 else "")
                            + (" + FVG" if bear_fvg else "")) if s4
                           else "candle M5 belum displacement bear"}

    res["layers"] = [l1, l2, l3, l4]
    res["signal"] = ("BUY" if (b1 and b2 and b3 and b4)
                     else ("SELL" if (s1 and s2 and s3 and s4) else None))
    return res


class G4Strategy:
    """Kelas strategi G4 — interface kompatibel ModelIcasStrategy (counter harian,
    can_trade_today, evaluate) sehingga daemon & StateStore tetap bekerja."""

    def __init__(self, cfg=config):
        self.cfg = cfg
        self.daily_trades_count = 0
        self.consecutive_losses = 0
        self.current_date = None

    # ---- antarmuka counter harian (identik icas_strategy) ----
    def reset_daily_stats_if_new_day(self, trade_date):
        if self.current_date != trade_date:
            self.current_date = trade_date
            self.daily_trades_count = 0
            self.consecutive_losses = 0

    def can_trade_today(self) -> Tuple[bool, str]:
        if self.daily_trades_count >= self.cfg.MAX_TRADES_PER_DAY:
            return False, f"Max daily trades limit reached ({self.daily_trades_count}/{self.cfg.MAX_TRADES_PER_DAY})"
        if self.consecutive_losses >= self.cfg.MAX_CONSECUTIVE_LOSSES:
            return False, f"Circuit breaker active: {self.consecutive_losses} consecutive losses today"
        return True, "OK"

    def evaluate(self, df_m5: pd.DataFrame, df_m15: pd.DataFrame, df_h1: pd.DataFrame,
                 current_balance: float, spread_usd: float = 0.0) -> Optional[IcasSignal]:
        """Evaluasi bar M5 TERAKHIR frame (wajib bar yang sudah TERTUTUP — daemon
        membuang bar berjalan di frames_from_raw). Entry = market order ~open
        candle berikutnya; BUY mengisi di ask (≈ close + spread), SELL di bid
        (≈ close) — SL/TP dijangkarkan ke harga fill yang diharapkan, replika
        Position engine (fill = open_ask utk BUY / open_bid utk SELL)."""
        can_trade, _ = self.can_trade_today()
        if not can_trade:
            return None

        sweep_bars = int(getattr(self.cfg, "G4_SWEEP_BARS", 288))
        fvg_buffer = float(getattr(self.cfg, "G4_FVG_BUFFER_USD", 0.30))
        ema_span = int(getattr(self.cfg, "G4_H1_EMA_SPAN", 200))
        max_spread_usd = float(getattr(self.cfg, "MAX_SPREAD_USD", 1.20))

        # Guard spread (riset: bar spread <= $1.20; live: spread tick saat order;
        # send_order juga menolak bila spread melebihi batas).
        if spread_usd > max_spread_usd:
            return None

        i = len(df_m5) - 1
        if i < max(10, sweep_bars // 2):
            return None
        direction = g4_signal_at(df_m5, df_m15, df_h1, i,
                                 sweep_bars=sweep_bars, fvg_buffer=fvg_buffer,
                                 ema_span=ema_span)
        if direction is None:
            return None

        c = float(df_m5["close"].iloc[i])

        # ---- ukuran posisi (S-04: SL + spread + slippage, identik icas_strategy) ----
        sl_dist_usd = self.cfg.STOP_LOSS_PIPS * 0.10
        if getattr(self.cfg, "INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK", False):
            sl_eff = sl_dist_usd + spread_usd + getattr(self.cfg, "SLIPPAGE_USD", 0.0)
        else:
            sl_eff = sl_dist_usd
        risk_base = current_balance if self.cfg.USE_COMPOUNDING else self.cfg.INITIAL_CAPITAL
        risk_dollar = risk_base * self.cfg.RISK_PER_TRADE_PCT
        lot_size = round(risk_dollar / (sl_eff * 100.0), 2)
        lot_size = max(0.01, min(50.0, lot_size))

        # ---- anchor SL/TP ke harga fill yang diharapkan (replika engine) ----
        if direction == "BUY":
            ep = c + spread_usd            # fill ask ≈ close + spread
            sl = ep - sl_dist_usd
            tp1 = ep + self.cfg.TP1_PIPS * 0.10
            tp2 = ep + self.cfg.TP2_PIPS * 0.10
            tp3 = ep + self.cfg.TP3_PIPS * 0.10
            early_be = ep + self.cfg.EARLY_BE_TRIGGER_PIPS * 0.10
        else:
            ep = c                          # fill bid ≈ close
            sl = ep + sl_dist_usd
            tp1 = ep - self.cfg.TP1_PIPS * 0.10
            tp2 = ep - self.cfg.TP2_PIPS * 0.10
            tp3 = ep - self.cfg.TP3_PIPS * 0.10
            early_be = ep - self.cfg.EARLY_BE_TRIGGER_PIPS * 0.10

        # ---- level kaskade utk alasan jurnal (diagnostik) ----
        t_i = df_m5.index[i]
        h1_ema = _h1_ema_at(df_h1, t_i, ema_span=ema_span) or 0.0
        lvl = _pd_levels(df_m5, t_i) or (float("nan"), float("nan"))
        pdh, pdl = lvl[0], lvl[1]

        return IcasSignal(
            type=direction,
            entry_price=ep,
            stop_loss=sl,
            early_be_price=early_be,
            tp1_price=tp1,
            tp2_price=tp2,
            tp3_price=tp3,
            lot_size=lot_size,
            risk_amount=risk_dollar,
            reason=(f"G4 kaskade: H1 EMA200 {h1_ema:.2f} | sweep PDH/PDL "
                    f"{pdh:.2f}/{pdl:.2f} (24j) | CHoCH M15 | displacement M5")
        )
