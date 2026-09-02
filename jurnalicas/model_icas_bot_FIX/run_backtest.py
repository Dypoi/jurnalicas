"""
Single-command CLI Runner for Model Icas Backtesting with WIN / BE / LOSS Separation
Usage: python run_backtest.py [--start 2026-01-01] [--end 2026-06-30] [--fixed]
"""
import sys
import subprocess

def ensure_dependencies():
    try:
        import pandas
        import numpy
    except ImportError:
        print("[*] Menginstal dependensi otomatis...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        except Exception:
            pass

def main():
    ensure_dependencies()
    import argparse
    import pandas as pd
    from config import config
    from src.backtest.engine import IcasBacktestEngine

    parser = argparse.ArgumentParser(description="Model Icas Historical Backtest Engine")
    parser.add_argument("--start", type=str, default="2026-01-01", help="Start Date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2026-06-30 23:59:59", help="End Date (YYYY-MM-DD)")
    parser.add_argument("--fixed", action="store_true", help="Use Fixed Base Lot ($500 risk) instead of Compounding")
    parser.add_argument("--killzone", action="store_true", help="Enforce ICT London/NY Killzones only")
    parser.add_argument("--no-killzone", action="store_true", help="Disable Killzones (Trade 24 Hours)")
    parser.add_argument("--legacy", action="store_true",
                        help="Mode engine pra-audit (optimis intrabar, tanpa spread/slippage risk) — untuk komparasi")
    args = parser.parse_args()

    use_kz = config.USE_KILLZONE
    if args.killzone:
        use_kz = True
    elif args.no_killzone:
        use_kz = False

    kz_label = "DENGAN Killzone (London & NY Burst)" if use_kz else "TANPA Killzone (24 Jam Full Session)"

    print("\n" + "="*85)
    print(f"       ⚡ MODEL ICAS SCALPING - 4-TIER MULTI-TP BACKTEST ({args.start} s/d {args.end[:10]})")
    print("="*85)
    print(f"• Mode Sesi : {kz_label}")
    print(f"• Pair      : {config.SYMBOL} (M5) | Risk: {config.RISK_PER_TRADE_PCT*100:.1f}% | Early BE+: +{config.EARLY_BE_TRIGGER_PIPS}p | SL: {config.STOP_LOSS_PIPS}p")
    print(f"• Target    : TP1: +{config.TP1_PIPS}p (1:1) | TP2: +{config.TP2_PIPS}p (1:2) | TP3: +{config.TP3_PIPS}p (1:3 -> SL to TP1) | Runner: Step {config.TRAILING_STEP_PIPS}p")
    print("="*85 + "\n")

    csv_path = "data/historical/xauusd_m5.csv"
    print(f"[*] Memuat data historis dari {csv_path}...")
    df_m5 = pd.read_csv(csv_path)

    config.USE_KILLZONE = use_kz
    if args.legacy:
        config.CONSERVATIVE_INTRABAR = False
        config.INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK = False
        config.SLIPPAGE_USD = 0.0
        config.ENFORCE_SPREAD_GUARD_IN_BACKTEST = False
        print("• Mode Engine : LEGACY (pra-audit — intrabar optimis, sizing tanpa spread/slippage)")
    else:
        print(f"• Mode Engine : KONSERVATIF (SL-first intrabar) | Sizing: SL+spread+slipp (${config.SLIPPAGE_USD:.2f}) | Spread Guard: ON")
    engine = IcasBacktestEngine(config)
    compounding = not args.fixed
    final_cap, tdf = engine.run(df_m5, start_date=args.start, end_date=args.end, compounding=compounding)

    if len(tdf) == 0:
        print("Tidak ada transaksi dalam periode ini.")
        sys.exit(0)

    total = len(tdf)
    wins = tdf[tdf['res'] == 'WIN']
    be_trades = tdf[tdf['res'] == 'BE']
    losses = tdf[tdf['res'] == 'LOSS']

    wr = len(wins) / total * 100.0
    be_rate = len(be_trades) / total * 100.0
    loss_rate = len(losses) / total * 100.0
    non_loss_rate = (len(wins) + len(be_trades)) / total * 100.0

    gw = wins['pnl'].sum() + be_trades['pnl'].sum()
    gl = abs(losses['pnl'].sum())
    pf = gw / gl if gl > 0 else 0
    eq = pd.Series([config.INITIAL_CAPITAL] + tdf['balance'].tolist())
    dd = (((eq.cummax() - eq) / eq.cummax()) * 100.0).max()
    net_profit = final_cap - config.INITIAL_CAPITAL
    roi = (net_profit / config.INITIAL_CAPITAL) * 100.0

    print("📊 HASIL PERFORMA LENGKAP (PEMISAHAN WIN / BE / LOSS):")
    print("-" * 75)
    print(f"• Total Transaksi          : {total} Trades")
    print(f"• Distribusi Hasil (3-Way) : {len(wins)} WIN  |  {len(be_trades)} BE+ (Scratch Profit)  |  {len(losses)} LOSS")
    print(f"• Murni Win Rate (TP Hit)  : {wr:.2f}% ({len(wins)} Trades)")
    print(f"• Breakeven Rate (BE+)     : {be_rate:.2f}% ({len(be_trades)} Trades - Hasil Positif / Scratch)")
    print(f"• Loss Rate (SL Hit)       : {loss_rate:.2f}% ({len(losses)} Trades)")
    print(f"• NON-LOSS RATE (Win + BE) : {non_loss_rate:.2f}% (Tingkat Keamanan Modal)")
    print(f"• Profit Factor (PF)       : {pf:.2f}")
    print(f"• Net Profit ($)           : ${net_profit:+,.2f} ({roi:+,.2f}%)")
    print(f"• Saldo Akhir Modal        : ${final_cap:,.2f}")
    print(f"• Maximum Drawdown         : {dd:.2f}%")
    print(f"• TP1 Executed (1:1 / +20p): {len(tdf[tdf['tp1_hit'] == True])} kali ({len(tdf[tdf['tp1_hit'] == True])/total*100:.1f}%)")
    print(f"• TP2 Executed (1:2 / +40p): {len(tdf[tdf['tp2_hit'] == True])} kali ({len(tdf[tdf['tp2_hit'] == True])/total*100:.1f}%)")
    print(f"• TP3 Executed (1:3 / +60p): {len(tdf[tdf['tp3_hit'] == True])} kali ({len(tdf[tdf['tp3_hit'] == True])/total*100:.1f}%) -> SL pindah ke TP1 (+20p)")
    print(f"• Trailing Runner Stepped  : {len(tdf[tdf['trail_stepped'] >= 1])} kali (>=100 pips)")
    print("-" * 75)

    print("\n📅 Rincian Bulan per Bulan (Month-by-Month):")
    months = sorted(tdf['month'].unique())
    green_count = 0
    for m in months:
        m_df = tdf[tdf['month'] == m]
        m_w = len(m_df[m_df['res'] == 'WIN'])
        m_be = len(m_df[m_df['res'] == 'BE'])
        m_l = len(m_df[m_df['res'] == 'LOSS'])
        m_pnl = m_df['pnl'].sum()
        if m_pnl > 0: green_count += 1
        print(f"   • {m} : {len(m_df):2d} Trades ({m_w:2d}W / {m_be:2d}BE / {m_l:2d}L | Non-Loss: {(m_w+m_be)/len(m_df)*100:4.1f}%) | PnL: ${m_pnl:+12,.2f}")
    print(f"\n==> Monthly Win Rate: {green_count}/{len(months)} Bulan Hijau ({green_count/len(months)*100:.1f}%)\n")

if __name__ == '__main__':
    main()
