"""
REGRESSION PARITY TEST — Engine v2 (flag legacy) vs Engine lama (repo asli)
Harus menghasilkan equity curve & statistik IDENTIK ke bit terakhir.
"""
import sys
import os
import importlib.util
import dataclasses
import pandas as pd

sys.path.insert(0, '.')
from config import config

DATA = 'data/historical/xauusd_m5.csv'

# ---- engine lama dari repo asli (referensi) ----
# [AUDIT FORENSIK 2 — F-13] Path absolut repo lama di-hardcode di sini sehingga
# test ini MATI (FileNotFoundError) di setiap checkout lain — artinya regresi
# parity live/backtest tidak pernah benar-benar dijaga. Kini lokasi engine lama
# dicari berurutan dari: $ICAS_LEGACY_ENGINE, beberapa path kandidat, lalu SKIP
# eksplisit (bukan crash) bila memang tidak tersedia.
_CANDIDATES = [
    os.getenv("ICAS_LEGACY_ENGINE", ""),
    os.path.expanduser("~/testagent/model_icas_bot/src/backtest/engine.py"),
    os.path.join("..", "model_icas_bot", "src", "backtest", "engine.py"),
    os.path.join("..", "..", "model_icas_bot", "src", "backtest", "engine.py"),
]
_legacy_path = next((c for c in _CANDIDATES if c and os.path.exists(c)), None)
if _legacy_path is None:
    print("=" * 78)
    print(" SKIP - engine legacy pembanding tidak ditemukan.")
    print("        Set ICAS_LEGACY_ENGINE=/path/ke/model_icas_bot/src/backtest/engine.py")
    print("        untuk mengaktifkan regresi parity ini.")
    print("=" * 78)
    sys.exit(0)
print(f"• Engine legacy referensi: {_legacy_path}")
spec_old = importlib.util.spec_from_file_location("engine_old", _legacy_path)
engine_old_mod = importlib.util.module_from_spec(spec_old)
spec_old.loader.exec_module(engine_old_mod)

from src.backtest.engine import IcasBacktestEngine  # engine baru

df = pd.read_csv(DATA)

PERIODS = [('2026-01-01', '2026-06-30 23:59:59'), ('2025-06-01', '2026-06-30 23:59:59')]
ok_all = True
for start, end in PERIODS:
    for compounding in (False, True):
        cap_old, t_old = engine_old_mod.IcasBacktestEngine(config).run(
            df, start_date=start, end_date=end, compounding=compounding)
        cfg_legacy = dataclasses.replace(
            config, CONSERVATIVE_INTRABAR=False,
            INCLUDE_SPREAD_AND_SLIPPAGE_IN_RISK=False,
            SLIPPAGE_USD=0.0,
            ENFORCE_SPREAD_GUARD_IN_BACKTEST=False)
        cap_new, t_new = IcasBacktestEngine(cfg_legacy).run(
            df, start_date=start, end_date=end, compounding=compounding)

        same_cap = abs(cap_old - cap_new) < 1e-6
        same_len = len(t_old) == len(t_new)
        same_curve = same_len and bool((t_old['balance'].round(6) == t_new['balance'].round(6)).all())
        same_res = same_len and bool((t_old['res'] == t_new['res']).all())
        same_trail = same_len and bool((t_old['trail_stepped'] == t_new['trail_stepped']).all())
        ok = same_cap and same_curve and same_res and same_trail
        ok_all &= ok
        print(f"[{start[:7]} .. {end[:7]} comp={int(compounding)}] "
              f"trades {len(t_old)}=={len(t_new)} | cap {cap_old:.2f}=={cap_new:.2f} | "
              f"curve:{same_curve} res:{same_res} trail:{same_trail} -> {'✅ PARITY' if ok else '❌ MISMATCH'}")

print("=" * 70)
print("SEMUA PARITY TEST LULUS ✅" if ok_all else "ADA MISMATCH ❌")
sys.exit(0 if ok_all else 1)
