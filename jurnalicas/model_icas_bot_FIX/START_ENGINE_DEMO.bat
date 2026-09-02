@echo off
REM ============================================================================
REM  MODEL ICAS - START ENGINE BARU v2 (SWING-150) di AKUN DEMO - mode laptop
REM ============================================================================
REM  Cara pakai:
REM    1. Buka MT5 (Exness) -> PASTIKAN login ke akun DEMO Anda (bukan Real!)
REM    2. Biarkan MT5 tetap berjalan di belakang.
REM    3. Klik dua kali file ini. Engine menempel ke terminal MT5 yang sedang
REM       berjalan (bila perlu, set MT5_PATH via env var di config.py).
REM    4. Mematikan engine: Ctrl+C (aman). Menyalakan lagi: klik dua kali lagi.
REM       Posisi lama akan diadopsi otomatis; posisi yg tertutup saat OFF akan
REM       tercatat otomatis di logs\trade_journal.jsonl.
REM    5. Setelah seminggu observasi: python research\journal_report.py
REM ============================================================================
echo [ENGINE v2] Memastikan dependensi terpasang...
python -m pip install -r requirements.txt >nul 2>&1
echo [ENGINE v2] Menjalankan daemon demo (Killzone NONAKTIF, jurnal JSON aktif)...
python run_live.py
echo.
echo [ENGINE v2] Daemon berhenti. State ^& jurnal aman. Tekan tombol apa pun utk tutup.
pause >nul
