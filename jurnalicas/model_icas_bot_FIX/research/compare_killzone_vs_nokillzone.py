"""
[ARSIP RISET - parameter model usang pra-audit, disimpan untuk histori saja]
================================================================================
Jalankan dari root project:  python research/<nama_file>.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""

Comparative Backtest: Model Icas (WITH Killzones) vs Model Icas (WITHOUT Killzones / 24H)
Periods:
1. Full 1-Year: Juni 2025 - Juni 2026
2. 6-Month: Januari 2026 - Juni 2026
"""

import pandas as pd
import numpy as np
from config import config
from src.indicators.sessions import calculate_session_killzones

# Load M5 Data
df_m5_raw = pd.read_csv('data/historical/xauusd_m5.csv')
df_m5 = calculate_session_killzones(df_m5_raw)

def run_icas_backtest(df_data, use_killzone=True, risk_pct=0.05, start_date='2025-06-01', end_date='2026-06-30 23:59:59', compounding=True):
    capital = 10000.0
    trades = []
    open_pos = None
    current_date = None
    trades_today = 0
    consecutive_losses_today = 0
    
    high5 = df_data['high'].values
    low5 = df_data['low'].values
    close5 = df_data['close'].values
    open5 = df_data['open'].values
    spread5 = df_data['spread'].values
    times5 = df_data['time'].values
    asian_h_arr = df_data['asian_high'].values
    asian_l_arr = df_data['asian_low'].values
    london_h_arr = df_data['london_high'].values
    london_l_arr = df_data['london_low'].values
    in_burst_arr = df_data['in_ict_burst'].values
    
    tp1_ratio = 0.40
    tp2_ratio = 0.30
    runner_ratio = 0.30
    be_trigger_dist = 2.00 # 20 pips = $2.00
    
    for i in range(20, len(df_data)):
        t = pd.Timestamp(times5[i])
        if t < pd.Timestamp(start_date): continue
        if t > pd.Timestamp(end_date): break
        
        cur_date = t.date()
        if cur_date != current_date:
            current_date = cur_date
            trades_today = 0
            consecutive_losses_today = 0
            
        if open_pos is not None:
            ep = open_pos['entry']
            tp1 = open_pos['tp1']
            tp2 = open_pos['tp2']
            sz = open_pos['size']
            sp_c = open_pos['spread_cost']
            
            if open_pos['type'] == 'BUY':
                max_fav = high5[i] - ep
                if max_fav > open_pos['max_favorable']:
                    open_pos['max_favorable'] = max_fav
                
                # 0. Early Breakeven (BE+) Trigger
                if not open_pos['be_set'] and open_pos['max_favorable'] >= be_trigger_dist:
                    open_pos['sl'] = ep + 0.10
                    open_pos['be_set'] = True
                
                # Trailing Step for Runner (Step 100 pips / Lock 30 pips)
                k_step = int(open_pos['max_favorable'] // 10.00)
                if k_step >= 1:
                    trail_sl = ep + (k_step - 1) * 10.00 + 3.00
                    if trail_sl > open_pos['sl']:
                        open_pos['sl'] = trail_sl
                        open_pos['trail_stepped'] = k_step
                
                # 1. TP1 Check (+30 pips / $3.00)
                if not open_pos['tp1_hit'] and high5[i] >= tp1:
                    pnl_tp1 = (tp1 - ep) * (sz * tp1_ratio) - (sp_c * tp1_ratio)
                    open_pos['realized_pnl'] += pnl_tp1
                    capital += pnl_tp1
                    open_pos['tp1_hit'] = True
                    if open_pos['sl'] < ep + 0.10:
                        open_pos['sl'] = ep + 0.10
                        
                # 2. TP2 Check (+60 pips / $6.00)
                if open_pos['tp1_hit'] and not open_pos['tp2_hit'] and high5[i] >= tp2:
                    pnl_tp2 = (tp2 - ep) * (sz * tp2_ratio) - (sp_c * tp2_ratio)
                    open_pos['realized_pnl'] += pnl_tp2
                    capital += pnl_tp2
                    open_pos['tp2_hit'] = True
                    
                # 3. Stop Loss / Trailing Stop Exit Check
                if low5[i] <= open_pos['sl']:
                    exit_price = open_pos['sl']
                    if not open_pos['tp1_hit']:
                        rem_ratio = 1.0
                    elif not open_pos['tp2_hit']:
                        rem_ratio = tp2_ratio + runner_ratio
                    else:
                        rem_ratio = runner_ratio
                        
                    rem_sz = sz * rem_ratio
                    exit_pnl = (exit_price - ep) * rem_sz - (sp_c * rem_ratio)
                    capital += exit_pnl
                    open_pos['realized_pnl'] += exit_pnl
                    
                    total_pnl = open_pos['realized_pnl']
                    res = 'WIN' if total_pnl > 0 else 'LOSS'
                    trades.append({
                        'time': t,
                        'type': 'BUY',
                        'res': res,
                        'pnl': total_pnl,
                        'balance': capital,
                        'month': t.strftime('%Y-%m'),
                        'tp1_hit': open_pos['tp1_hit'],
                        'tp2_hit': open_pos['tp2_hit'],
                        'be_set': open_pos['be_set'],
                        'trail_stepped': open_pos['trail_stepped'],
                        'max_fav_pips': open_pos['max_favorable'] * 10,
                        'exit_sl_dist': exit_price - ep
                    })
                    if res == 'LOSS': consecutive_losses_today += 1
                    open_pos = None
                    
            elif open_pos['type'] == 'SELL':
                max_fav = ep - low5[i]
                if max_fav > open_pos['max_favorable']:
                    open_pos['max_favorable'] = max_fav
                    
                # 0. Early Breakeven (BE+) Trigger
                if not open_pos['be_set'] and open_pos['max_favorable'] >= be_trigger_dist:
                    open_pos['sl'] = ep - 0.10
                    open_pos['be_set'] = True
                    
                k_step = int(open_pos['max_favorable'] // 10.00)
                if k_step >= 1:
                    trail_sl = ep - ((k_step - 1) * 10.00 + 3.00)
                    if trail_sl < open_pos['sl']:
                        open_pos['sl'] = trail_sl
                        open_pos['trail_stepped'] = k_step
                        
                # 1. TP1 Check (-30 pips / $3.00)
                if not open_pos['tp1_hit'] and low5[i] <= tp1:
                    pnl_tp1 = (ep - tp1) * (sz * tp1_ratio) - (sp_c * tp1_ratio)
                    open_pos['realized_pnl'] += pnl_tp1
                    capital += pnl_tp1
                    open_pos['tp1_hit'] = True
                    if open_pos['sl'] > ep - 0.10:
                        open_pos['sl'] = ep - 0.10
                        
                # 2. TP2 Check (-60 pips / $6.00)
                if open_pos['tp1_hit'] and not open_pos['tp2_hit'] and low5[i] <= tp2:
                    pnl_tp2 = (ep - tp2) * (sz * tp2_ratio) - (sp_c * tp2_ratio)
                    open_pos['realized_pnl'] += pnl_tp2
                    capital += pnl_tp2
                    open_pos['tp2_hit'] = True
                    
                # 3. Stop Loss / Trailing Stop Exit Check
                if high5[i] >= open_pos['sl']:
                    exit_price = open_pos['sl']
                    if not open_pos['tp1_hit']:
                        rem_ratio = 1.0
                    elif not open_pos['tp2_hit']:
                        rem_ratio = tp2_ratio + runner_ratio
                    else:
                        rem_ratio = runner_ratio
                        
                    rem_sz = sz * rem_ratio
                    exit_pnl = (ep - exit_price) * rem_sz - (sp_c * rem_ratio)
                    capital += exit_pnl
                    open_pos['realized_pnl'] += exit_pnl
                    
                    total_pnl = open_pos['realized_pnl']
                    res = 'WIN' if total_pnl > 0 else 'LOSS'
                    trades.append({
                        'time': t,
                        'type': 'SELL',
                        'res': res,
                        'pnl': total_pnl,
                        'balance': capital,
                        'month': t.strftime('%Y-%m'),
                        'tp1_hit': open_pos['tp1_hit'],
                        'tp2_hit': open_pos['tp2_hit'],
                        'be_set': open_pos['be_set'],
                        'trail_stepped': open_pos['trail_stepped'],
                        'max_fav_pips': open_pos['max_favorable'] * 10,
                        'exit_sl_dist': ep - exit_price
                    })
                    if res == 'LOSS': consecutive_losses_today += 1
                    open_pos = None

        # Entry logic:
        # If use_killzone is False -> in_time_window is always True!
        in_time_window = in_burst_arr[i] if use_killzone else True

        if open_pos is None and trades_today < 3 and consecutive_losses_today < 2 and in_time_window:
            c = close5[i]; o = open5[i]
            bsl_target = max(asian_h_arr[i], london_h_arr[i])
            ssl_target = min(asian_l_arr[i], london_l_arr[i])
            
            is_m5_bull_fvg = (low5[i] > high5[i-2] + 0.30)
            is_m5_bear_fvg = (high5[i] < low5[i-2] - 0.30)
            
            m5_swing_h = np.max(high5[i-6:i-1])
            m5_swing_l = np.min(low5[i-6:i-1])
            
            ssl_judas_sweep = (low5[i-1] <= ssl_target or low5[i-2] <= ssl_target)
            bull_choch = (c > o and (c > m5_swing_h or is_m5_bull_fvg))
            is_buy_scalp = ssl_judas_sweep and bull_choch
            
            bsl_judas_sweep = (high5[i-1] >= bsl_target or high5[i-2] >= bsl_target)
            bear_choch = (c < o and (c < m5_swing_l or is_m5_bear_fvg))
            is_sell_scalp = bsl_judas_sweep and bear_choch
            
            if is_buy_scalp or is_sell_scalp:
                sl_dist = 2.00 # 20 pips = $2.00
                risk_base = capital if compounding else 10000.0
                sz = (risk_base * risk_pct) / (sl_dist * 100.0) * 100.0
                sp_c = (spread5[i] * 0.01) * sz
                
                if is_buy_scalp:
                    ep = c
                    sl = ep - sl_dist
                    tp1 = ep + 3.00 # +30 pips
                    tp2 = ep + 6.00 # +60 pips
                    open_pos = {
                        'type': 'BUY', 'entry': ep, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'size': sz, 'spread_cost': sp_c, 'tp1_hit': False, 'tp2_hit': False,
                        'be_set': False, 'max_favorable': 0.0, 'realized_pnl': 0.0, 'trail_stepped': 0
                    }
                    trades_today += 1
                else:
                    ep = c
                    sl = ep + sl_dist
                    tp1 = ep - 3.00 # -30 pips
                    tp2 = ep - 6.00 # -60 pips
                    open_pos = {
                        'type': 'SELL', 'entry': ep, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'size': sz, 'spread_cost': sp_c, 'tp1_hit': False, 'tp2_hit': False,
                        'be_set': False, 'max_favorable': 0.0, 'realized_pnl': 0.0, 'trail_stepped': 0
                    }
                    trades_today += 1

    return capital, pd.DataFrame(trades)

print("="*100)
print("     ⚔️ PERBANDINGAN MODEL ICAS: DENGAN KILLZONE vs TANPA KILLZONE (24 JAM)")
print("="*100)

# Run 1-Year (Jun 2025 - Jun 2026)
cap_kz_1y_c, df_kz_1y_c = run_icas_backtest(df_m5, use_killzone=True, start_date='2025-06-01', end_date='2026-06-30 23:59:59', compounding=True)
cap_nokz_1y_c, df_nokz_1y_c = run_icas_backtest(df_m5, use_killzone=False, start_date='2025-06-01', end_date='2026-06-30 23:59:59', compounding=True)

cap_kz_1y_f, df_kz_1y_f = run_icas_backtest(df_m5, use_killzone=True, start_date='2025-06-01', end_date='2026-06-30 23:59:59', compounding=False)
cap_nokz_1y_f, df_nokz_1y_f = run_icas_backtest(df_m5, use_killzone=False, start_date='2025-06-01', end_date='2026-06-30 23:59:59', compounding=False)

# Run 6-Month (Jan 2026 - Jun 2026)
cap_kz_6m_c, df_kz_6m_c = run_icas_backtest(df_m5, use_killzone=True, start_date='2026-01-01', end_date='2026-06-30 23:59:59', compounding=True)
cap_nokz_6m_c, df_nokz_6m_c = run_icas_backtest(df_m5, use_killzone=False, start_date='2026-01-01', end_date='2026-06-30 23:59:59', compounding=True)

def print_summary(name, df, final_cap, initial=10000.0):
    wins = df[df['res'] == 'WIN']
    losses = df[df['res'] == 'LOSS']
    wr = len(wins) / len(df) * 100 if len(df) > 0 else 0
    gw = wins['pnl'].sum()
    gl = abs(losses['pnl'].sum())
    pf = gw / gl if gl > 0 else 0
    eq = pd.Series([initial] + df['balance'].tolist())
    dd = (((eq.cummax() - eq) / eq.cummax()) * 100.0).max()
    net = final_cap - initial
    roi = (net / initial) * 100
    print(f"📌 {name}")
    print(f"   • Total Trades  : {len(df)} Trades ({len(wins)}W / {len(losses)}L)")
    print(f"   • Win Rate      : {wr:.2f}%")
    print(f"   • Profit Factor : {pf:.2f}")
    print(f"   • Net Profit    : ${net:+12,.2f} ({roi:+,.2f}%)")
    print(f"   • Saldo Akhir   : ${final_cap:12,.2f}")
    print(f"   • Max Drawdown  : {dd:.2f}%")
    
    # Monthly breakdown
    months = sorted(df['month'].unique())
    green = sum(1 for m in months if df[df['month'] == m]['pnl'].sum() > 0)
    print(f"   • Monthly Win Rate: {green}/{len(months)} Bulan Hijau ({green/len(months)*100:.1f}%)")
    print()

print("\n--- [1] HASIL 1 TAHUN PENUH (JUNI 2025 - JUNI 2026) ---")
print_summary("Model Icas DENGAN Killzone (Compounding 5%)", df_kz_1y_c, cap_kz_1y_c)
print_summary("Model Icas TANPA Killzone (24H Compounding 5%)", df_nokz_1y_c, cap_nokz_1y_c)

print("--- [2] HASIL FIXED BASE $500 RISK (JUNI 2025 - JUNI 2026) ---")
print_summary("Model Icas DENGAN Killzone (Fixed $500)", df_kz_1y_f, cap_kz_1y_f)
print_summary("Model Icas TANPA Killzone (Fixed $500)", df_nokz_1y_f, cap_nokz_1y_f)

print("--- [3] HASIL 6 BULAN (JANUARI 2026 - JUNI 2026) ---")
print_summary("Model Icas DENGAN Killzone (2026 Compounding 5%)", df_kz_6m_c, cap_kz_6m_c)
print_summary("Model Icas TANPA Killzone (2026 Compounding 5%)", df_nokz_6m_c, cap_nokz_6m_c)
