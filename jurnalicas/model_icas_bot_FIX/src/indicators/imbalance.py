"""
Imbalance & Fair Value Gap (FVG) / Liquidity Sweep Detector for Model Icas
"""
import numpy as np
import pandas as pd

def detect_m5_fvg_and_choch(high_arr, low_arr, close_arr, open_arr, idx: int):
    """
    Evaluates FVG and displacement CHoCH on M5 at index idx.
    """
    if idx < 6:
        return False, False, 0.0, 0.0
        
    c = close_arr[idx]
    o = open_arr[idx]
    
    # 3-candle FVG gap ($0.30 buffer = 3 pips)
    is_bull_fvg = (low_arr[idx] > high_arr[idx - 2] + 0.30)
    is_bear_fvg = (high_arr[idx] < low_arr[idx - 2] - 0.30)
    
    # Minor swing high/low break (CHoCH displacement)
    swing_h = np.max(high_arr[idx - 6:idx - 1])
    swing_l = np.min(low_arr[idx - 6:idx - 1])
    
    bull_choch = (c > o) and (c > swing_h or is_bull_fvg)
    bear_choch = (c < o) and (c < swing_l or is_bear_fvg)
    
    return bull_choch, bear_choch, swing_h, swing_l
