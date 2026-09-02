"""
[ARSIP RISET - parameter model usang pra-audit, disimpan untuk histori saja]
================================================================================
Jalankan dari root project:  python research/<nama_file>.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""

Head-to-Head Comparison: Model Icas (With Daily Limits & Circuit Breaker) vs (UNLIMITED Trades & No Circuit Breaker)
Period: 1 Januari 2026 - 30 Juni 2026 (6 Bulan Penuh)
Data: MT5 XAUUSD M5 (34,059 Bars) | Exness Spread $2.60
"""

import pandas as pd
import numpy as np
from config import config
from src.indicators.sessions import calculate_session_killzones

df_m5_raw = pd.read_csv('data/historical/xauusd_m5.csv')
df_m5 = calculate_session_killzones(df_m5_raw)

def run_icas_simulation(df_data, max_trades_per_day=3, max_consecutive_losses=2, use_killzone=False, risk_pct=0.05, compounding=False, start_date='2026-01-01', end_date='2026-06-30 23:59:59'):
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
                
                # Trailing Step for Runner
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

        # Entry logic
        in_time_window = in_burst_arr[i] if use_killzone else True
        
        # Check Daily Limits
        can_trade_limit = True
        if max_trades_per_day is not None and trades_today >= max_trades_per_day:
            can_trade_limit = False
        if max_consecutive_losses is not None and consecutive_losses_today >= max_consecutive_losses:
            can_trade_limit = False

        if open_pos is None and can_trade_limit and in_time_window:
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

print("="*105)
print(" ⚔️ PERBANDINGAN MODEL ICAS (JANUARI - JUNI 2026): DENGAN LIMIT & CIRCUIT BREAKER vs TANPA LIMIT (UNLIMITED)")
print("="*105)

# 1. Fixed Base ($500 Risk)
cap_lim_f, df_lim_f = run_icas_simulation(df_m5, max_trades_per_day=3, max_consecutive_losses=2, compounding=False)
cap_unl_f, df_unl_f = run_icas_simulation(df_m5, max_trades_per_day=None, max_consecutive_losses=None, compounding=False)

# 2. Compounding (5% Risk)
cap_lim_c, df_lim_c = run_icas_simulation(df_m5, max_trades_per_day=3, max_consecutive_losses=2, compounding=True)
cap_unl_c, df_unl_c = run_icas_simulation(df_m5, max_trades_per_day=None, max_consecutive_losses=None, compounding=True)

def print_metrics(name, df, final_cap, initial=10000.0):
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
    
    be_cnt = len(df[df['be_set'] == True])
    tp1_cnt = len(df[df['tp1_hit'] == True])
    tp2_cnt = len(df[df['tp2_hit'] == True])
    runner_cnt = len(df[df['trail_stepped'] >= 1])
    
    print(f"📌 {name}")
    print("-" * 80)
    print(f"• Total Transaksi (6 Bulan): {len(df)} Trades ({len(wins)} Win / {len(losses)} Loss)")
    print(f"• Win Rate (Akurasi)       : {wr:.2f}%")
    print(f"• Profit Factor (PF)       : {pf:.2f}")
    print(f"• Net Profit ($)           : ${net:+12,.2f} ({roi:+,.2f}%)")
    print(f"• Saldo Akhir Modal        : ${final_cap:12,.2f}")
    print(f"• Maximum Drawdown         : {dd:.2f}%")
    print(f"• Early BE+ Triggered      : {be_cnt} kali ({be_cnt/len(df)*100:.1f}%)")
    print(f"• TP1 Executed (+30 pips)  : {tp1_cnt} kali ({tp1_cnt/len(df)*100:.1f}%)")
    print(f"• TP2 Executed (+60 pips)  : {tp2_cnt} kali ({tp2_cnt/len(df)*100:.1f}%)")
    print(f"• Runner Trailing Stepped  : {runner_cnt} kali (>=100 pips)")
    
    # Month by month
    print("\n📅 Rincian Profit Bulanan (Month-by-Month):")
    months = sorted(df['month'].unique())
    green = 0
    for m in months:
        m_df = df[df['month'] == m]
        m_win = len(m_df[m_df['res'] == 'WIN'])
        m_loss = len(m_df[m_df['res'] == 'LOSS'])
        m_pnl = m_df['pnl'].sum()
        m_wr = (m_win / len(m_df) * 100.0) if len(m_df) > 0 else 0
        if m_pnl > 0: green += 1
        print(f"   • {m} : {len(m_df):2d} Trades ({m_win:2d}W / {m_loss:2d}L | WR: {m_wr:4.1f}%) | PnL: ${m_pnl:+12,.2f}")
    print(f"   ==> Monthly Win Rate: {green}/{len(months)} Bulan Hijau ({green/len(months)*100:.1f}%)\n")

print("\n--- [1] PERBANDINGAN MODE FIXED BASE ($500 RISK PER TRADE) ---")
print_metrics("MODEL ICAS DENGAN LIMIT (Max 3 Trades & Circuit Breaker 2 Loss) - Fixed $500", df_lim_f, cap_lim_f)
print_metrics("MODEL ICAS TANPA LIMIT (UNLIMITED TRADES & ZERO CIRCUIT BREAKER) - Fixed $500", df_unl_f, cap_unl_f)

print("--- [2] PERBANDINGAN MODE DYNAMIC COMPOUNDING (5% EQUITY RISK) ---")
print_metrics("MODEL ICAS DENGAN LIMIT (Max 3 Trades & Circuit Breaker 2 Loss) - Compounding 5%", df_lim_c, cap_lim_c)
print_metrics("MODEL ICAS TANPA LIMIT (UNLIMITED TRADES & ZERO CIRCUIT BREAKER) - Compounding 5%", df_unl_c, cap_unl_c)

