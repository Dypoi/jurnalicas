"""
========================================================================================
MODEL ICAS SCALPING STRATEGY ENGINE (4-TIER MULTI-TP & STEP TRAILING ARCHITECTURE)
========================================================================================
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
import numpy as np
import pandas as pd
from config import config

@dataclass
class IcasSignal:
    type: str                  # 'BUY' or 'SELL'
    entry_price: float
    stop_loss: float
    early_be_price: float
    tp1_price: float
    tp2_price: float
    tp3_price: float
    lot_size: float
    risk_amount: float
    reason: str

class ModelIcasStrategy:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self.daily_trades_count = 0
        self.consecutive_losses = 0
        self.current_date = None

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

    def evaluate_m5_setup(self, df_m5: pd.DataFrame, idx: int, current_balance: float,
                          spread_usd: float = 0.0) -> Optional[IcasSignal]:
        """
        Evaluates Model Icas setup on M5 dataset at bar `idx`.
        Zero-repainting & zero-lookahead guaranteed.
        `spread_usd` = spread saat ini dalam USD per oz (spread_points * 0.01).
        [AUDIT FIX S-04] dipakai agar ukuran posisi memperhitungkan biaya spread
        + slippage, selaras dengan backtest engine v2.
        """
        if idx < 10 or idx >= len(df_m5):
            return None

        # Check daily trade limits & circuit breaker
        can_trade, reason = self.can_trade_today()
        if not can_trade:
            return None

        # Check ICT Burst window (only if USE_KILLZONE is True)
        if getattr(self.cfg, 'USE_KILLZONE', False):
            in_burst = df_m5['in_ict_burst'].iloc[idx] if 'in_ict_burst' in df_m5.columns else False
            if not in_burst:
                return None

        c = float(df_m5['close'].iloc[idx])
        o = float(df_m5['open'].iloc[idx])
        h = float(df_m5['high'].iloc[idx])
        l = float(df_m5['low'].iloc[idx])

        asian_h = float(df_m5['asian_high'].iloc[idx]) if 'asian_high' in df_m5.columns else h
        asian_l = float(df_m5['asian_low'].iloc[idx]) if 'asian_low' in df_m5.columns else l
        london_h = float(df_m5['london_high'].iloc[idx]) if 'london_high' in df_m5.columns else asian_h
        london_l = float(df_m5['london_low'].iloc[idx]) if 'london_low' in df_m5.columns else asian_l

        bsl_target = max(asian_h, london_h)
        ssl_target = min(asian_l, london_l)

        # 3-Candle FVG on M5 ($0.30 buffer = 3 pips)
        prev2_h = float(df_m5['high'].iloc[idx - 2])
        prev2_l = float(df_m5['low'].iloc[idx - 2])
        is_bull_fvg = (l > prev2_h + 0.30)
        is_bear_fvg = (h < prev2_l - 0.30)

        # Minor Swing High/Low Break (CHoCH displacement)
        # [FIXED] Window disamakan dengan backtest engine & imbalance.py (idx-6 .. idx-2),
        # sebelumnya live memakai (idx-6 .. idx-1) sehingga sinyal live bisa beda dgn backtest.
        m5_swing_h = float(df_m5['high'].iloc[idx - 6:idx - 1].max())
        m5_swing_l = float(df_m5['low'].iloc[idx - 6:idx - 1].min())

        prev1_l = float(df_m5['low'].iloc[idx - 1])
        prev1_h = float(df_m5['high'].iloc[idx - 1])

        # A. BUY Setup: Judas Sweep SSL (Asian or London Low) + Bullish CHoCH Displacement / FVG
        ssl_swept = (prev1_l <= ssl_target or prev2_l <= ssl_target)
        bull_displacement = (c > o) and (c > m5_swing_h or is_bull_fvg)
        is_buy = ssl_swept and bull_displacement

        # B. SELL Setup: Judas Sweep BSL (Asian or London High) + Bearish CHoCH Displacement / FVG
        bsl_swept = (prev1_h >= bsl_target or prev2_h >= bsl_target)
        bear_displacement = (c < o) and (c < m5_swing_l or is_bear_fvg)
        is_sell = bsl_swept and bear_displacement

        if not (is_buy or is_sell):
            return None

        # Position Sizing based on 5.0% risk & 20 pips SL ($2.00 price distance)
        # [AUDIT FIX S-04] risiko efektif memperhitungkan spread + slippage,
        # konsisten dengan engine backtest v2 (INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK).
        sl_dist_usd = self.cfg.STOP_LOSS_PIPS * 0.10  # 20 pips * 0.10 = $2.00
        if getattr(self.cfg, 'INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK', False):
            sl_eff = sl_dist_usd + spread_usd + getattr(self.cfg, 'SLIPPAGE_USD', 0.0)
        else:
            sl_eff = sl_dist_usd
        risk_base = current_balance if self.cfg.USE_COMPOUNDING else self.cfg.INITIAL_CAPITAL
        risk_dollar = risk_base * self.cfg.RISK_PER_TRADE_PCT
        # In Gold: 1 lot = 100 oz. $1.00 move on 1 lot = $100.
        lot_size = round(risk_dollar / (sl_eff * 100.0), 2)
        lot_size = max(0.01, min(50.0, lot_size))

        if is_buy:
            ep = c
            sl = ep - sl_dist_usd
            early_be = ep + (self.cfg.EARLY_BE_TRIGGER_PIPS * 0.10)
            tp1 = ep + (self.cfg.TP1_PIPS * 0.10) # +20 pips (1:1)
            tp2 = ep + (self.cfg.TP2_PIPS * 0.10) # +40 pips (1:2)
            tp3 = ep + (self.cfg.TP3_PIPS * 0.10) # +60 pips (1:3)
            return IcasSignal(
                type='BUY',
                entry_price=ep,
                stop_loss=sl,
                early_be_price=early_be,
                tp1_price=tp1,
                tp2_price=tp2,
                tp3_price=tp3,
                lot_size=lot_size,
                risk_amount=risk_dollar,
                reason=f"SSL Judas Sweep ({ssl_target:.2f}) + M5 Bullish Displacement CHoCH"
            )
        else:
            ep = c
            sl = ep + sl_dist_usd
            early_be = ep - (self.cfg.EARLY_BE_TRIGGER_PIPS * 0.10)
            tp1 = ep - (self.cfg.TP1_PIPS * 0.10) # -20 pips (1:1)
            tp2 = ep - (self.cfg.TP2_PIPS * 0.10) # -40 pips (1:2)
            tp3 = ep - (self.cfg.TP3_PIPS * 0.10) # -60 pips (1:3)
            return IcasSignal(
                type='SELL',
                entry_price=ep,
                stop_loss=sl,
                early_be_price=early_be,
                tp1_price=tp1,
                tp2_price=tp2,
                tp3_price=tp3,
                lot_size=lot_size,
                risk_amount=risk_dollar,
                reason=f"BSL Judas Sweep ({bsl_target:.2f}) + M5 Bearish Displacement CHoCH"
            )
