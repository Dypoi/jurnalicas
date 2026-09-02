"""
Simulation Test: Model Icas with 4-Tier TP (TP1 20p 1:1, TP2 40p 1:2, TP3 60p 1:3 -> SL to TP1, Runner),
BE+ Trigger at +10 pips, Re-Entry enabled after BE+, and Separate WIN / LOSS / BE classification.
"""

import pandas as pd
import numpy as np
from src.indicators.sessions import calculate_session_killzones

df_m5_raw = pd.read_csv('data/historical/xauusd_m5.csv')
df_m5 = calculate_session_killzones(df_m5_raw)

def run_icas_4tier_simulation(df_data, risk_pct=0.05, compounding=False, start_date='2026-01-01', end_date='2026-06-30 23:59:59'):
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
    
    # 4-Tier Distribution: TP1 (30%), TP2 (25%), TP3 (25%), Runner (20%)
    tp1_ratio = 0.30
    tp2_ratio = 0.25
    tp3_ratio = 0.25
    runner_ratio = 0.20
    
    be_trigger_dist = 1.00 # 10 pips = $1.00
    
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
            tp3 = open_pos['tp3']
            sz = open_pos['size']
            sp_c = open_pos['spread_cost']
            sp_val = open_pos['spread_val']
            
            # Minimum offset to guarantee net PnL > $0.00 after spread
            be_offset = max(0.10, (sp_val * 0.01) + 0.05)
            
            if open_pos['type'] == 'BUY':
                max_fav = high5[i] - ep
                if max_fav > open_pos['max_favorable']:
                    open_pos['max_favorable'] = max_fav
                
                # 0. BE+ Trigger at +10 pips ($1.00)
                if not open_pos['be_set'] and open_pos['max_favorable'] >= be_trigger_dist:
                    open_pos['sl'] = ep + be_offset
                    open_pos['be_set'] = True
                
                # 1. TP1 Check (+20 pips / $2.00 -> RR 1:1)
                if not open_pos['tp1_hit'] and high5[i] >= tp1:
                    pnl_tp1 = (tp1 - ep) * (sz * tp1_ratio) - (sp_c * tp1_ratio)
                    open_pos['realized_pnl'] += pnl_tp1
                    capital += pnl_tp1
                    open_pos['tp1_hit'] = True
                    if open_pos['sl'] < ep + be_offset:
                        open_pos['sl'] = ep + be_offset
                        
                # 2. TP2 Check (+40 pips / $4.00 -> RR 1:2)
                if open_pos['tp1_hit'] and not open_pos['tp2_hit'] and high5[i] >= tp2:
                    pnl_tp2 = (tp2 - ep) * (sz * tp2_ratio) - (sp_c * tp2_ratio)
                    open_pos['realized_pnl'] += pnl_tp2
                    capital += pnl_tp2
                    open_pos['tp2_hit'] = True
                    
                # 3. TP3 Check (+60 pips / $6.00 -> RR 1:3) -> Step SL to TP1 (+20 pips / $2.00)
                if open_pos['tp2_hit'] and not open_pos['tp3_hit'] and high5[i] >= tp3:
                    pnl_tp3 = (tp3 - ep) * (sz * tp3_ratio) - (sp_c * tp3_ratio)
                    open_pos['realized_pnl'] += pnl_tp3
                    capital += pnl_tp3
                    open_pos['tp3_hit'] = True
                    # Step SL to TP1 (+20 pips / $2.00)
                    if open_pos['sl'] < tp1:
                        open_pos['sl'] = tp1
                        
                # 4. Trailing Step for Runner beyond TP3 (Step 100 pips / Lock 30 pips)
                k_step = int(open_pos['max_favorable'] // 10.00)
                if k_step >= 1:
                    trail_sl = ep + (k_step - 1) * 10.00 + 3.00
                    if trail_sl > open_pos['sl']:
                        open_pos['sl'] = trail_sl
                        open_pos['trail_stepped'] = k_step
                        
                # 5. Stop Loss / Trailing Stop Exit Check
                if low5[i] <= open_pos['sl']:
                    exit_price = open_pos['sl']
                    # Calculate remaining volume ratio
                    if not open_pos['tp1_hit']:
                        rem_ratio = 1.0
                    elif not open_pos['tp2_hit']:
                        rem_ratio = tp2_ratio + tp3_ratio + runner_ratio
                    elif not open_pos['tp3_hit']:
                        rem_ratio = tp3_ratio + runner_ratio
                    else:
                        rem_ratio = runner_ratio
                        
                    rem_sz = sz * rem_ratio
                    exit_pnl = (exit_price - ep) * rem_sz - (sp_c * rem_ratio)
                    capital += exit_pnl
                    open_pos['realized_pnl'] += exit_pnl
                    
                    total_pnl = open_pos['realized_pnl']
                    
                    # 3-Way Classification: WIN / LOSS / BE
                    if open_pos['tp1_hit'] or open_pos['tp2_hit'] or open_pos['tp3_hit'] or total_pnl > 50.0:
                        res = 'WIN'
                        consecutive_losses_today = 0
                    elif open_pos['be_set'] and total_pnl >= 0:
                        res = 'BE' # Breakeven exit (guaranteed non-negative profit)
                    else:
                        res = 'LOSS'
                        consecutive_losses_today += 1
                        
                    trades.append({
                        'time': t,
                        'type': 'BUY',
                        'res': res,
                        'pnl': total_pnl,
                        'balance': capital,
                        'month': t.strftime('%Y-%m'),
                        'tp1_hit': open_pos['tp1_hit'],
                        'tp2_hit': open_pos['tp2_hit'],
                        'tp3_hit': open_pos['tp3_hit'],
                        'be_set': open_pos['be_set'],
                        'trail_stepped': open_pos['trail_stepped'],
                        'max_fav_pips': open_pos['max_favorable'] * 10,
                        'exit_sl_dist': exit_price - ep
                    })
                    open_pos = None
                    
            elif open_pos['type'] == 'SELL':
                max_fav = ep - low5[i]
                if max_fav > open_pos['max_favorable']:
                    open_pos['max_favorable'] = max_fav
                    
                # 0. BE+ Trigger at +10 pips ($1.00)
                if not open_pos['be_set'] and open_pos['max_favorable'] >= be_trigger_dist:
                    open_pos['sl'] = ep - be_offset
                    open_pos['be_set'] = True
                    
                # 1. TP1 Check (-20 pips / $2.00 -> RR 1:1)
                if not open_pos['tp1_hit'] and low5[i] <= tp1:
                    pnl_tp1 = (ep - tp1) * (sz * tp1_ratio) - (sp_c * tp1_ratio)
                    open_pos['realized_pnl'] += pnl_tp1
                    capital += pnl_tp1
                    open_pos['tp1_hit'] = True
                    if open_pos['sl'] > ep - be_offset:
                        open_pos['sl'] = ep - be_offset
                        
                # 2. TP2 Check (-40 pips / $4.00 -> RR 1:2)
                if open_pos['tp1_hit'] and not open_pos['tp2_hit'] and low5[i] <= tp2:
                    pnl_tp2 = (ep - tp2) * (sz * tp2_ratio) - (sp_c * tp2_ratio)
                    open_pos['realized_pnl'] += pnl_tp2
                    capital += pnl_tp2
                    open_pos['tp2_hit'] = True
                    
                # 3. TP3 Check (-60 pips / $6.00 -> RR 1:3) -> Step SL to TP1 (-20 pips / $2.00)
                if open_pos['tp2_hit'] and not open_pos['tp3_hit'] and low5[i] <= tp3:
                    pnl_tp3 = (ep - tp3) * (sz * tp3_ratio) - (sp_c * tp3_ratio)
                    open_pos['realized_pnl'] += pnl_tp3
                    capital += pnl_tp3
                    open_pos['tp3_hit'] = True
                    if open_pos['sl'] > tp1:
                        open_pos['sl'] = tp1
                        
                # 4. Trailing Step for Runner beyond TP3 (Step 100 pips / Lock 30 pips)
                k_step = int(open_pos['max_favorable'] // 10.00)
                if k_step >= 1:
                    trail_sl = ep - ((k_step - 1) * 10.00 + 3.00)
                    if trail_sl < open_pos['sl']:
                        open_pos['sl'] = trail_sl
                        open_pos['trail_stepped'] = k_step
                        
                # 5. Stop Loss / Trailing Stop Exit Check
                if high5[i] >= open_pos['sl']:
                    exit_price = open_pos['sl']
                    if not open_pos['tp1_hit']:
                        rem_ratio = 1.0
                    elif not open_pos['tp2_hit']:
                        rem_ratio = tp2_ratio + tp3_ratio + runner_ratio
                    elif not open_pos['tp3_hit']:
                        rem_ratio = tp3_ratio + runner_ratio
                    else:
                        rem_ratio = runner_ratio
                        
                    rem_sz = sz * rem_ratio
                    exit_pnl = (ep - exit_price) * rem_sz - (sp_c * rem_ratio)
                    capital += exit_pnl
                    open_pos['realized_pnl'] += exit_pnl
                    
                    total_pnl = open_pos['realized_pnl']
                    
                    if open_pos['tp1_hit'] or open_pos['tp2_hit'] or open_pos['tp3_hit'] or total_pnl > 50.0:
                        res = 'WIN'
                        consecutive_losses_today = 0
                    elif open_pos['be_set'] and total_pnl >= 0:
                        res = 'BE'
                    else:
                        res = 'LOSS'
                        consecutive_losses_today += 1
                        
                    trades.append({
                        'time': t,
                        'type': 'SELL',
                        'res': res,
                        'pnl': total_pnl,
                        'balance': capital,
                        'month': t.strftime('%Y-%m'),
                        'tp1_hit': open_pos['tp1_hit'],
                        'tp2_hit': open_pos['tp2_hit'],
                        'tp3_hit': open_pos['tp3_hit'],
                        'be_set': open_pos['be_set'],
                        'trail_stepped': open_pos['trail_stepped'],
                        'max_fav_pips': open_pos['max_favorable'] * 10,
                        'exit_sl_dist': ep - exit_price
                    })
                    open_pos = None

        # Entry logic: M15/Asian/London Sweep + M5 Judas Displacement CHoCH + FVG
        if open_pos is None:
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
                sp_val = spread5[i]
                
                if is_buy_scalp:
                    ep = c
                    sl = ep - sl_dist
                    tp1 = ep + 2.00 # +20 pips (1:1)
                    tp2 = ep + 4.00 # +40 pips (1:2)
                    tp3 = ep + 6.00 # +60 pips (1:3 -> SL to TP1)
                    open_pos = {
                        'type': 'BUY', 'entry': ep, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                        'size': sz, 'spread_cost': sp_c, 'spread_val': sp_val,
                        'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False,
                        'be_set': False, 'max_favorable': 0.0, 'realized_pnl': 0.0, 'trail_stepped': 0
                    }
                    trades_today += 1
                else:
                    ep = c
                    sl = ep + sl_dist
                    tp1 = ep - 2.00 # -20 pips (1:1)
                    tp2 = ep - 4.00 # -40 pips (1:2)
                    tp3 = ep - 6.00 # -60 pips (1:3 -> SL to TP1)
                    open_pos = {
                        'type': 'SELL', 'entry': ep, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                        'size': sz, 'spread_cost': sp_c, 'spread_val': sp_val,
                        'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False,
                        'be_set': False, 'max_favorable': 0.0, 'realized_pnl': 0.0, 'trail_stepped': 0
                    }
                    trades_today += 1

    return capital, pd.DataFrame(trades)

cap_2026, df_2026 = run_icas_4tier_simulation(df_m5, risk_pct=0.05, compounding=False, start_date='2026-01-01', end_date='2026-06-30 23:59:59')
cap_1y, df_1y = run_icas_4tier_simulation(df_m5, risk_pct=0.05, compounding=False, start_date='2025-06-01', end_date='2026-06-30 23:59:59')

def print_detailed_metrics(title, df, final_cap, initial=10000.0):
    total = len(df)
    wins = df[df['res'] == 'WIN']
    be_trades = df[df['res'] == 'BE']
    losses = df[df['res'] == 'LOSS']
    
    wr = len(wins) / total * 100
    be_rate = len(be_trades) / total * 100
    loss_rate = len(losses) / total * 100
    non_loss_rate = (len(wins) + len(be_trades)) / total * 100
    
    gw = wins['pnl'].sum() + be_trades['pnl'].sum()
    gl = abs(losses['pnl'].sum())
    pf = gw / gl if gl > 0 else 0
    net_pnl = final_cap - initial
    roi = (net_pnl / initial) * 100
    
    eq = pd.Series([initial] + df['balance'].tolist())
    dd = (((eq.cummax() - eq) / eq.cummax()) * 100.0).max()
    
    print(f"📊 {title}")
    print("-" * 80)
    print(f"• Total Transaksi          : {total} Trades")
    print(f"• Distribusi Hasil (3-Way) : {len(wins)} WIN | {len(be_trades)} BE (Scratch Profit) | {len(losses)} LOSS")
    print(f"• Murni Win Rate (TP Hit)  : {wr:.2f}% ({len(wins)} Trades)")
    print(f"• Breakeven Rate (BE+)     : {be_rate:.2f}% ({len(be_trades)} Trades - Hasil Positif / Scratch)")
    print(f"• Loss Rate (SL Hit)       : {loss_rate:.2f}% ({len(losses)} Trades)")
    print(f"• NON-LOSS RATE (Win + BE) : {non_loss_rate:.2f}% (Tingkat Keberhasilan Modal Aman)")
    print(f"• Profit Factor (PF)       : {pf:.2f}")
    print(f"• Net Profit ($)           : ${net_pnl:+,.2f} ({roi:+,.2f}%)")
    print(f"• Saldo Akhir Modal        : ${final_cap:,.2f}")
    print(f"• Maximum Drawdown         : {dd:.2f}%")
    print(f"• TP1 Executed (1:1 / +20p): {len(df[df['tp1_hit'] == True])} kali ({len(df[df['tp1_hit'] == True])/total*100:.1f}%)")
    print(f"• TP2 Executed (1:2 / +40p): {len(df[df['tp2_hit'] == True])} kali ({len(df[df['tp2_hit'] == True])/total*100:.1f}%)")
    print(f"• TP3 Executed (1:3 / +60p): {len(df[df['tp3_hit'] == True])} kali ({len(df[df['tp3_hit'] == True])/total*100:.1f}%) -> SL otomatis naik ke TP1 (+20p)")
    print(f"• Trailing Runner Stepped  : {len(df[df['trail_stepped'] >= 1])} kali (>=100 pips)")
    
    print("\n📅 Rincian Bulan per Bulan (Month-by-Month):")
    months = sorted(df['month'].unique())
    green_count = 0
    for m in months:
        m_df = df[df['month'] == m]
        m_w = len(m_df[m_df['res'] == 'WIN'])
        m_be = len(m_df[m_df['res'] == 'BE'])
        m_l = len(m_df[m_df['res'] == 'LOSS'])
        m_pnl = m_df['pnl'].sum()
        if m_pnl > 0: green_count += 1
        print(f"   • {m} : {len(m_df):2d} Trades ({m_w:2d}W / {m_be:2d}BE / {m_l:2d}L | Non-Loss: {(m_w+m_be)/len(m_df)*100:4.1f}%) | PnL: ${m_pnl:+12,.2f}")
    print(f"   ==> Monthly Win Rate: {green_count}/{len(months)} Bulan Hijau ({green_count/len(months)*100:.1f}%)\n")

print_detailed_metrics("HASIL MODEL ICAS BARU (JANUARI - JUNI 2026 / 6 BULAN)", df_2026, cap_2026)
print_detailed_metrics("HASIL MODEL ICAS BARU (JUNI 2025 - JUNI 2026 / 13 BULAN)", df_1y, cap_1y)
