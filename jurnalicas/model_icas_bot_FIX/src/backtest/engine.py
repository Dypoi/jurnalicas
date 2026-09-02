"""
================================================================================
Fast Backtesting Engine for Model Icas (4-Tier Multi-TP, Guaranteed Positive BE+,
Re-Entry & 3-Way Classification) — v2 [AUDIT FOLLOW-UP]
================================================================================
Perbaikan atas audit forensik:
  S-04 : Ukuran posisi memperhitungkan spread + slippage (INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK)
  R-01 : Mode intrabar KONSERVATIF (CONSERVATIVE_INTRABAR=True, default):
           1) SL dicek LEBIH DULU dalam 1 bar (pesimis, anti bias optimis),
           2) SL yang baru dinaikkan (BE+/TP-step/trailing) baru EFEKTIF bar berikutnya,
           3) Entry diberi slippage merugikan (SLIPPAGE_USD), exit SL juga kena slippage,
           4) Spread guard dihormati (ENFORCE_SPREAD_GUARD_IN_BACKTEST).
         Mode lama tetap tersedia 1:1 (set semua flag False) — teregresi parity-test.
  NEW  : Nilai spread di-inferensi dari DATA (point 0.01 utk 2-digit, 0.001 utk
         XAUUSDm 3-digit) — memperbaiki bias 10x biaya spread pada feed 3-digit.
================================================================================
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, Optional
from config import config
from src.indicators.sessions import calculate_session_killzones


def infer_price_point(prices: np.ndarray) -> float:
    """Inferensi nilai point ($/point) dari granularitas desimal harga:
    2-digit (4011.21) -> 0.01 ; 3-digit (4681.717, XAUUSDm) -> 0.001."""
    sample = np.asarray(prices[:2000], dtype=float)
    if len(sample) == 0:
        return 0.01
    # PENTING: rtol=0 — default np.allclose(rtol=1e-5) memberi kelonggaran relatif
    # yang salah mengklasifikasikan harga ribuan USD sebagai 2-digit.
    if np.allclose(sample * 100.0, np.round(sample * 100.0), rtol=0.0, atol=1e-6):
        return 0.01
    if np.allclose(sample * 1000.0, np.round(sample * 1000.0), rtol=0.0, atol=1e-6):
        return 0.001
    return 0.01


class IcasBacktestEngine:
    def __init__(self, cfg=config):
        self.cfg = cfg

    # ------------------------------------------------------------------
    def run(self, df_m5_raw: pd.DataFrame, start_date: str = '2026-01-01',
            end_date: str = '2026-06-30 23:59:59',
            compounding: bool = False) -> Tuple[float, pd.DataFrame]:
        cfg = self.cfg

        df_m5 = calculate_session_killzones(df_m5_raw)

        capital = cfg.INITIAL_CAPITAL
        trades = []
        open_pos: Optional[Dict[str, Any]] = None
        current_date = None
        trades_today = 0
        consecutive_losses_today = 0

        high5 = df_m5['high'].values
        low5 = df_m5['low'].values
        close5 = df_m5['close'].values
        open5 = df_m5['open'].values
        spread5 = df_m5['spread'].values
        times5 = df_m5['time'].values
        asian_h_arr = df_m5['asian_high'].values
        asian_l_arr = df_m5['asian_low'].values
        london_h_arr = df_m5['london_high'].values
        london_l_arr = df_m5['london_low'].values
        in_burst_arr = df_m5['in_ict_burst'].values

        # [DIGIT-AWARE] nilai point di-inferensi dari harga (2-digit=0.01, 3-digit=0.001)
        # -> biaya spread benar pada feed XAUUSDm 3-digit (bug 10x pada versi sebelumnya)
        price_point = infer_price_point(close5)
        spread_usd_arr = spread5 * price_point

        tp1_ratio = cfg.TP1_LOT_RATIO    # 0.30
        tp2_ratio = cfg.TP2_LOT_RATIO    # 0.25
        tp3_ratio = cfg.TP3_LOT_RATIO    # 0.25
        runner_ratio = cfg.RUNNER_LOT_RATIO  # 0.20

        be_trigger_dist = cfg.EARLY_BE_TRIGGER_PIPS * 0.10   # $1.00
        use_kz = getattr(cfg, 'USE_KILLZONE', False)

        # --- flag realisme eksekusi (default baru; False semua = perilaku legacy 1:1)
        conservative = getattr(cfg, 'CONSERVATIVE_INTRABAR', False)
        risk_includes_costs = getattr(cfg, 'INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK', False)
        slipp = getattr(cfg, 'SLIPPAGE_USD', 0.0)
        spread_guard = getattr(cfg, 'ENFORCE_SPREAD_GUARD_IN_BACKTEST', False)

        # ============================ helpers ============================
        def tp_reached(tp_level: float, d: int, h: float, l: float) -> bool:
            return h >= tp_level if d == 1 else l <= tp_level

        def stop_reached(sl_level: float, d: int, h: float, l: float) -> bool:
            return l <= sl_level if d == 1 else h >= sl_level

        def book_exit(pos: Dict[str, Any], t, i: int) -> None:
            """Tutup sisa posisi di SL dan catat trade (WIN/BE/LOSS)."""
            nonlocal capital
            d, ep, sz = pos['dir'], pos['entry'], pos['size']
            exit_price = pos['sl'] - d * slipp  # slippage merugikan saat kena stop
            if not pos['tp1_hit']:
                rem_ratio = 1.0
            elif not pos['tp2_hit']:
                rem_ratio = tp2_ratio + tp3_ratio + runner_ratio
            elif not pos['tp3_hit']:
                rem_ratio = tp3_ratio + runner_ratio
            else:
                rem_ratio = runner_ratio

            sp_c = pos['spread_cost']
            exit_pnl = d * (exit_price - ep) * (sz * rem_ratio) - (sp_c * rem_ratio)
            capital += exit_pnl
            pos['realized_pnl'] += exit_pnl
            total_pnl = pos['realized_pnl']

            if pos['tp1_hit'] or pos['tp2_hit'] or pos['tp3_hit']:
                res = 'WIN'
            elif pos['be_set'] and total_pnl >= 0:
                res = 'BE'
            else:
                res = 'LOSS'

            # Parity legacy: WIN mereset counter; BE TIDAK mengubah counter;
            # hanya LOSS yang menambah consecutive losses.
            if res == 'LOSS':
                nonlocal_loss_inc()
            elif res == 'WIN':
                nonlocal_loss_reset()

            trades.append({
                'time': t,
                'type': 'BUY' if d == 1 else 'SELL',
                'res': res,
                'pnl': total_pnl,
                'balance': capital,
                'month': t.strftime('%Y-%m'),
                'tp1_hit': pos['tp1_hit'],
                'tp2_hit': pos['tp2_hit'],
                'tp3_hit': pos['tp3_hit'],
                'be_set': pos['be_set'],
                'trail_stepped': pos['trail_stepped'],
                'max_fav_pips': pos['max_favorable'] * 10,
                'exit_sl_dist': d * (exit_price - ep)
            })

        def nonlocal_loss_inc():
            nonlocal consecutive_losses_today
            consecutive_losses_today += 1

        def nonlocal_loss_reset():
            nonlocal consecutive_losses_today
            consecutive_losses_today = 0

        def advance_exits_and_stops(pos: Dict[str, Any], h: float, l: float) -> None:
            """
            Proses BE+, TP1/TP2/TP3, SL-step ke TP1, dan trailing runner.
            Dipakai oleh KEDUA mode (legacy: sebelum cek stop; konservatif: sesudah).
            """
            nonlocal capital
            d, ep, sz = pos['dir'], pos['entry'], pos['size']
            sp_c = pos['spread_cost']
            be_offset = max(0.10, pos['spread_usd'] + (cfg.BE_PROFIT_OFFSET_PIPS * 0.10))

            # max favorable excursion (bahan BE & trailing)
            fav_bar = (h - ep) if d == 1 else (ep - l)
            if fav_bar > pos['max_favorable']:
                pos['max_favorable'] = fav_bar

            def sl_raise(target: float) -> bool:
                """Naikkan SL hanya ke arah profit (never loosen). True jika berubah."""
                if d == 1:
                    if target > pos['sl']:
                        pos['sl'] = target
                        return True
                else:
                    if target < pos['sl']:
                        pos['sl'] = target
                        return True
                return False

            # 0. Early BE+ pada +10 pips
            if not pos['be_set'] and pos['max_favorable'] >= be_trigger_dist:
                sl_raise(ep + d * be_offset)
                pos['be_set'] = True

            # 1..3. TP1/TP2/TP3 (bertingkat, wajib berurutan)
            for tp_key, tp_lvl, ratio in (('tp1_hit', pos['tp1'], tp1_ratio),
                                          ('tp2_hit', pos['tp2'], tp2_ratio),
                                          ('tp3_hit', pos['tp3'], tp3_ratio)):
                if not pos[tp_key] and tp_reached(tp_lvl, d, h, l) and _chain_ok(pos, tp_key):
                    pnl = d * (tp_lvl - ep) * (sz * ratio) - (sp_c * ratio)
                    pos['realized_pnl'] += pnl
                    capital += pnl
                    pos[tp_key] = True
                    if tp_key == 'tp1_hit':
                        sl_raise(ep + d * be_offset)
                    elif tp_key == 'tp3_hit':
                        sl_raise(pos['tp1'])  # step SL ke TP1

            # 4. Trailing runner (step 100 pips / lock 30 pips)
            k_step = int(pos['max_favorable'] // (cfg.TRAILING_STEP_PIPS * 0.10))
            if k_step >= 1:
                lock = (k_step - 1) * (cfg.TRAILING_STEP_PIPS * 0.10) + (cfg.TRAILING_LOCK_PIPS * 0.10)
                if sl_raise(ep + d * lock):
                    pos['trail_stepped'] = k_step  # parity legacy: hanya saat SL benar-benar naik

        def _chain_ok(pos, tp_key) -> bool:
            """TP2 hanya boleh setelah TP1, TP3 hanya setelah TP2 (sama seperti legacy)."""
            if tp_key == 'tp1_hit':
                return True
            if tp_key == 'tp2_hit':
                return pos['tp1_hit']
            return pos['tp2_hit']

        # ============================ main loop ============================
        for i in range(20, len(df_m5)):
            t = pd.Timestamp(times5[i])
            if t < pd.Timestamp(start_date):
                continue
            if t > pd.Timestamp(end_date):
                break

            cur_date = t.date()
            if cur_date != current_date:
                current_date = cur_date
                trades_today = 0
                consecutive_losses_today = 0

            if open_pos is not None:
                d = open_pos['dir']
                h, l = high5[i], low5[i]

                if conservative:
                    # [R-01] PESIMIS: SL lama dites TERLEBIH DULU; kenaikan SL baru
                    # berlaku bar berikutnya (urutan intrabar tidak dapat diketahui dari OHLC).
                    if stop_reached(open_pos['sl'], d, h, l):
                        book_exit(open_pos, t, i)
                        open_pos = None
                    else:
                        advance_exits_and_stops(open_pos, h, l)
                else:
                    # LEGACY (optimis): proses TP/trailing lalu satu cek stop di akhir bar.
                    advance_exits_and_stops(open_pos, h, l)
                    if stop_reached(open_pos['sl'], d, h, l):
                        book_exit(open_pos, t, i)
                        open_pos = None

            # ------------------------------ entry ------------------------------
            in_session_allowed = in_burst_arr[i] if use_kz else True
            can_trade_limit = (trades_today < cfg.MAX_TRADES_PER_DAY) and \
                              (consecutive_losses_today < cfg.MAX_CONSECUTIVE_LOSSES)
            spread_ok = (spread5[i] <= cfg.MAX_SPREAD_POINTS) if spread_guard else True

            if open_pos is None and can_trade_limit and in_session_allowed and spread_ok:
                c, o = close5[i], open5[i]
                bsl_target = max(asian_h_arr[i], london_h_arr[i])
                ssl_target = min(asian_l_arr[i], london_l_arr[i])

                is_m5_bull_fvg = (low5[i] > high5[i - 2] + 0.30)
                is_m5_bear_fvg = (high5[i] < low5[i - 2] - 0.30)

                m5_swing_h = np.max(high5[i - 6:i - 1])
                m5_swing_l = np.min(low5[i - 6:i - 1])

                ssl_judas_sweep = (low5[i - 1] <= ssl_target or low5[i - 2] <= ssl_target)
                bull_choch = (c > o and (c > m5_swing_h or is_m5_bull_fvg))
                is_buy_scalp = ssl_judas_sweep and bull_choch

                bsl_judas_sweep = (high5[i - 1] >= bsl_target or high5[i - 2] >= bsl_target)
                bear_choch = (c < o and (c < m5_swing_l or is_m5_bear_fvg))
                is_sell_scalp = bsl_judas_sweep and bear_choch

                if is_buy_scalp or is_sell_scalp:
                    d = 1 if is_buy_scalp else -1
                    sl_dist = cfg.STOP_LOSS_PIPS * 0.10            # $2.00
                    spread_usd_i = spread_usd_arr[i]
                    # [S-04] risiko efektif = SL + spread + slippage
                    sl_eff = sl_dist + (spread_usd_i + slipp) if risk_includes_costs else sl_dist

                    risk_base = capital if compounding else cfg.INITIAL_CAPITAL
                    risk_dollar = risk_base * cfg.RISK_PER_TRADE_PCT
                    # grouping identik dg rumus legacy (parity bitwise saat mode legacy)
                    sz = (risk_dollar / (sl_eff * 100.0)) * 100.0   # dalam ounce (1 lot = 100 oz)

                    ep = c + d * slipp                              # entry kena slippage
                    sp_c = spread_usd_i * sz
                    tp_sign = d

                    open_pos = {
                        'dir': d,
                        'entry': ep,
                        'sl': ep - tp_sign * sl_dist,
                        'tp1': ep + tp_sign * (cfg.TP1_PIPS * 0.10),
                        'tp2': ep + tp_sign * (cfg.TP2_PIPS * 0.10),
                        'tp3': ep + tp_sign * (cfg.TP3_PIPS * 0.10),
                        'size': sz,
                        'spread_cost': sp_c,
                        'spread_val': spread5[i],
                        'spread_usd': spread_usd_i,
                        'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False,
                        'be_set': False, 'max_favorable': 0.0,
                        'realized_pnl': 0.0, 'trail_stepped': 0
                    }
                    trades_today += 1

        return capital, pd.DataFrame(trades)
