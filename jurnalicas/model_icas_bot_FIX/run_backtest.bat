@echo off
title Model Icas - Historical Backtest
echo ======================================================================
echo           STARTING MODEL ICAS HISTORICAL BACKTEST
echo ======================================================================
python run_backtest.py --start 2026-01-01 --end 2026-06-30
pause
