@echo off
title Install Model Icas Dependencies
echo ======================================================================
echo       INSTALLING MODEL ICAS DEPENDENCIES FOR WINDOWS / MT5
echo ======================================================================
echo.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install MetaTrader5
echo.
echo ======================================================================
echo       INSTALLATION COMPLETED SUCCESSFULLY!
echo ======================================================================
echo Anda sekarang dapat menjalankan:
echo   - run_dashboard.bat (untuk membuka dashboard visual)
echo   - run_live.bat (untuk menjalankan bot live di MT5)
echo   - run_backtest.bat (untuk menjalankan backtest)
echo.
pause
