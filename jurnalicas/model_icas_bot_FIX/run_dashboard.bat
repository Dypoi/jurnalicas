@echo off
title Model Icas - Live Dashboard
echo ======================================================================
echo           STARTING MODEL ICAS DASHBOARD (PORT 5000)
echo ======================================================================
python run_dashboard.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Terjadi kesalahan. Memeriksa modul Flask...
    python -m pip install flask pandas numpy requests
    python run_dashboard.py
)
pause
