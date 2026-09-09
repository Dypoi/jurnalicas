"""
Single-command CLI Runner for Model Icas Real-Time Web Dashboard
Auto-detects missing dependencies on Windows and provides instant fixes.

[AUDIT DASHBOARD D6-01 — 09 Sep 2026] FIX URUTAN IMPORT:
  BUG lama: `from src.dashboard_app import run_server` dieksekusi di LEVEL MODUL
  (line 30) — SEBELUM ensure_dependencies() sempat dipanggil. src.dashboard_app
  meng-import flask/pandas/numpy di top-level-nya, sehingga pada venv baru
  `python run_dashboard.py` langsung crash `ModuleNotFoundError: No module named
  'flask'` dan fitur auto-install TIDAK PERNAH berjalan (dead code). Bukti PoC
  terlampir di LAPORAN_AUDIT_DASHBOARD.md §D6-01. icasbot (`from run_dashboard
  import main`) turut tertular bug yang sama.
  FIX: import berat dipindah ke DALAM main(), setelah ensure_dependencies().
"""
import sys
import os
import subprocess


def ensure_dependencies():
    try:
        import flask
        import pandas
        import numpy
        return True
    except ImportError as e:
        missing_module = str(e).split("'")[-2] if "'" in str(e) else str(e)
        print("=" * 75)
        print(f"⚠️  MODUL DIPERLUKAN BELUM TERPASANG: {missing_module}")
        print("=" * 75)
        print("[*] Menginstal dependensi otomatis (flask, pandas, numpy, requests)...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print("[✅] Semua dependensi berhasil diinstal!\n")
            return True
        except Exception as install_err:
            print(f"[!] Gagal menginstal otomatis: {install_err}")
            print("\nSilakan jalankan perintah manual berikut di Command Prompt (CMD):")
            print("    pip install -r requirements.txt")
            sys.exit(1)


def main():
    from config import config
    ensure_dependencies()

    # [D6-01] import berat HANYA setelah dependensi terjamin terpasang
    from src.dashboard_app import run_server

    print("\n" + "=" * 75)
    print(f"       ⚡ MODEL ICAS DASHBOARD RUNNING DI http://localhost:{config.DASHBOARD_PORT}")
    print("=" * 75)
    if config.DASHBOARD_AUTH_TOKEN:
        print(f"• 🔒 Mode aman AKTIF — akses: http://localhost:{config.DASHBOARD_PORT}/?token=<ICAS_DASH_TOKEN>")
    print("• Tekan Ctrl + C untuk menghentikan server.\n")
    run_server()


if __name__ == '__main__':
    main()
