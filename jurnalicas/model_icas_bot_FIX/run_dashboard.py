"""
Single-command CLI Runner for Model Icas Real-Time Web Dashboard
Auto-detects missing dependencies on Windows and provides instant fixes.
"""
import sys
import os
import subprocess

def ensure_dependencies():
    try:
        import flask
        import pandas
        import numpy
    except ImportError as e:
        missing_module = str(e).split("'")[-2] if "'" in str(e) else str(e)
        print("=" * 75)
        print(f"⚠️  MODUL DIPERLUKAN BELUM TERPASANG: {missing_module}")
        print("=" * 75)
        print("[*] Menginstal dependensi otomatis (flask, pandas, numpy, requests)...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print("[✅] Semua dependensi berhasil diinstal!\n")
        except Exception as install_err:
            print(f"[!] Gagal menginstal otomatis: {install_err}")
            print("\nSilakan jalankan perintah manual berikut di Command Prompt (CMD):")
            print("    pip install -r requirements.txt")
            print("    pip install MetaTrader5\n")
            sys.exit(1)

from src.dashboard_app import run_server  # exposed at module level (dipakai oleh icasbot --dashboard)


def main():
    from config import config
    ensure_dependencies()
    print("\n" + "=" * 75)
    print(f"       ⚡ MODEL ICAS DASHBOARD RUNNING DI http://localhost:{config.DASHBOARD_PORT}")
    print("=" * 75)
    if config.DASHBOARD_AUTH_TOKEN:
        print(f"• 🔒 Mode aman AKTIF — akses: http://localhost:{config.DASHBOARD_PORT}/?token=<ICAS_DASH_TOKEN>")
    print(f"• Tekan Ctrl + C untuk menghentikan server.\n")
    run_server()


if __name__ == '__main__':
    main()
