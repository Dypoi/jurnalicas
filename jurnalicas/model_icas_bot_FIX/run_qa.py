"""
================================================================================
RUNNER QA TERPADU — MODEL ICAS
================================================================================
Menjalankan seluruh gerbang kualitas repo dengan satu perintah:

    python3 run_qa.py            # semua
    python3 run_qa.py --quick    # lewati backtest berat

Isi:
  1. Kompilasi seluruh modul Python
  2. Unit test lama (test_icas_audit, test_be_15_pips)
  3. Verifikasi lama (state persistence, fix 10016, dashboard v2, engine parity)
  4. [BARU] audit_faults/poc_faults.py — 10 skenario kegagalan koneksi
  5. [BARU] Backtest engine tetap berjalan (smoke)
"""
import os
import sys
import subprocess
import py_compile

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

SUITES = [
    ("Unit: audit ICAS",            "test_icas_audit.py",           "OK"),
    ("Unit: BE+ 15 pips",           "test_be_15_pips.py",           "OK"),
    ("Verif: persistensi state",    "verify_state_persistence.py",  "0 FAIL"),
    ("Verif: fix 10016",            "verify_fix_10016.py",          "0 FAIL"),
    ("Verif: dashboard v2",         "verify_dashboard_v2.py",       "0 FAIL"),
    ("Verif: parity engine",        "verify_engine_parity.py",      None),
    ("POC : kegagalan koneksi",     "audit_faults/poc_faults.py",   "0 FAIL"),
]


def main():
    quick = "--quick" in sys.argv
    os.chdir(ROOT)
    print("=" * 78)
    print(" QA TERPADU — MODEL ICAS")
    print("=" * 78)

    # ---- 1. kompilasi ----
    bad = []
    n = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".venv", ".git", "node_modules")]
        for fn in filenames:
            if fn.endswith(".py"):
                n += 1
                try:
                    py_compile.compile(os.path.join(dirpath, fn), doraise=True)
                except Exception as e:
                    bad.append(f"{fn}: {e}")
    print(f"\n[1] Kompilasi {n} file Python : "
          f"{'✅ semua lolos' if not bad else '❌ ' + str(len(bad)) + ' gagal'}")
    for b in bad:
        print("    ", b)

    # ---- 2..4. suite ----
    results = []
    for label, script, marker in SUITES:
        path = os.path.join(ROOT, script)
        if not os.path.exists(path):
            results.append((label, "SKIP", "file tidak ada"))
            continue
        p = subprocess.run([PY, script], capture_output=True, text=True, timeout=1800)
        out = (p.stdout or "") + (p.stderr or "")
        tail = [ln for ln in out.splitlines() if ln.strip()][-3:]
        ok = p.returncode == 0 and (marker is None or any(marker in ln for ln in out.splitlines()))
        results.append((label, "PASS" if ok else "FAIL", " | ".join(tail)))
        print(f"\n[{'✅' if ok else '❌'}] {label}  ({script})")
        for t in tail:
            print(f"      {t.strip()[:110]}")

    # ---- 5. smoke backtest ----
    if not quick:
        print("\n[5] Smoke backtest engine ...")
        code = (
            "import sys; sys.path.insert(0,'.');"
            "import pandas as pd;"
            "from config import config;"
            "from src.backtest.engine import IcasBacktestEngine;"
            "df=pd.read_csv('data/historical/xauusd_m5.csv');"
            "cap,t=IcasBacktestEngine(config).run(df,start_date='2026-01-01',"
            "end_date='2026-03-31 23:59:59',compounding=False);"
            "print(f'      trades={len(t)} final=${cap:,.2f}')"
        )
        p = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=1800)
        ok = p.returncode == 0
        results.append(("Smoke: backtest engine", "PASS" if ok else "FAIL",
                        (p.stdout or p.stderr).strip().splitlines()[-1][:110]))
        print(("      ✅ " if ok else "      ❌ ") + results[-1][2])

    n_suite_fail = sum(1 for _, st, _ in results if st == "FAIL")
    n_pass = sum(1 for _, st, _ in results if st == "PASS")
    n_skip = sum(1 for _, st, _ in results if st == "SKIP")
    total_fail = n_suite_fail + len(bad)
    print("\n" + "=" * 78)
    print(f" HASIL AKHIR: {n_pass} PASS / {total_fail} FAIL / {n_skip} SKIP"
          + ("" if not bad else f"  (+{len(bad)} file gagal kompilasi)"))
    print("=" * 78)
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
