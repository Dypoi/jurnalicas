"""
Single-command CLI Runner for Model Icas Live Trading Execution
Auto-detects missing dependencies and provides instant fixes.
"""
import sys
import subprocess

def ensure_dependencies():
    try:
        import pandas
        import numpy
    except ImportError as e:
        print("[*] Menginstal dependensi otomatis...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        except Exception:
            pass

if __name__ == '__main__':
    ensure_dependencies()
    from icas_daemon import main
    main()
