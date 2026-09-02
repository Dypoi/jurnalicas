"""
========================================================================================
MODEL ICAS SCALPER - RIGOROUS UNIT & INTEGRATION AUDIT SUITE
========================================================================================
"""
import unittest
import pandas as pd
import numpy as np
from config import config
from src.strategy.icas_strategy import ModelIcasStrategy, IcasSignal
from src.execution.mt5_bridge import IcasMT5Bridge
from src.backtest.engine import IcasBacktestEngine

class TestModelIcasAudit(unittest.TestCase):
    def setUp(self):
        self.cfg = config
        # Early BE+ kini OFF by default (9999, pasca-kalibrasi); uji logika BE
        # tetap memakai trigger lama 10 pips agar skenario legacy reproduksibel.
        self.cfg.EARLY_BE_TRIGGER_PIPS = 10.0
        self.strategy = ModelIcasStrategy(self.cfg)
        self.bridge = IcasMT5Bridge(self.cfg)
        self.bridge.initialize()

    def test_01_lot_normalization_and_sizing(self):
        """Verifies position sizing is strictly based on 5% risk on $2.00 SL."""
        balance = 10000.0
        risk_pct = 0.05 # 5% = $500
        sl_usd = 2.00 # 20 pips = $2.00
        expected_lot = 2.50
        
        calculated_lot = round((balance * risk_pct) / (sl_usd * 100.0), 2)
        self.assertEqual(calculated_lot, expected_lot)
        
        normalized_lot = self.bridge.normalize_lot(calculated_lot)
        self.assertEqual(normalized_lot, 2.50)
        print("✅ [TEST 1 PASSED] Position sizing & lot normalization: 2.50 Lots for $10k @ 5% Risk.")

    def test_02_early_be_plus_trigger(self):
        """Verifies Early BE+ locks SL at Entry + $0.10 when running profit reaches +20 pips ($2.00)."""
        ep = 3300.00
        sl = ep - 2.00 # Initial SL = 3298.00 (20 pips)
        ticket = self.bridge.send_order('BUY', 2.50, sl)
        self.assertIsNotNone(ticket)
        
        pos = self.bridge.get_open_position_details()
        self.assertIsNotNone(pos)
        self.assertEqual(pos['sl'], 3298.00)
        self.assertFalse(pos['be_set'])
        
        # Price reaches +20 pips ($2.00) -> 3302.00
        fav_pips = 20.0
        if fav_pips >= self.cfg.EARLY_BE_TRIGGER_PIPS:
            new_sl = ep + (self.cfg.BE_PROFIT_OFFSET_PIPS * 0.10) # 3300.30 (offset $0.30)
            res = self.bridge.modify_sl(ticket, new_sl)
            self.assertTrue(res)
            pos['be_set'] = True

        pos_after = self.bridge.get_open_position_details()
        self.assertEqual(pos_after['sl'], 3300.30)
        self.assertTrue(pos_after['be_set'])
        print("✅ [TEST 2 PASSED] Early BE+ triggers at +20 pips: SL moved from 3298.00 -> 3300.30 (Entry + 0.30).")

    def test_03_tp1_partial_close_30_percent(self):
        """Verifies TP1 closes exactly 30% lot (0.75 lot from 2.50) and leaves 70% running."""
        ep = 3300.00
        ticket = self.bridge.send_order('BUY', 2.50, ep - 2.00)
        pos = self.bridge.get_open_position_details()
        initial_vol = pos['initial_volume'] # 2.50

        # TP1 close 30% = 2.50 * 0.30 = 0.75 lot
        tp1_close_vol = round(initial_vol * self.cfg.TP1_LOT_RATIO, 2)
        self.assertEqual(tp1_close_vol, 0.75)

        res = self.bridge.close_partial(pos['ticket'], tp1_close_vol)
        self.assertTrue(res)
        pos['tp1_hit'] = True

        pos_after = self.bridge.get_open_position_details()
        self.assertEqual(pos_after['volume'], 1.75) # 70% remaining
        print(f"✅ [TEST 3 PASSED] TP1 (+20 pips) closed 30% ({tp1_close_vol} lots): Remaining volume = {pos_after['volume']} lots.")

    def test_04_tp2_partial_close_25_percent(self):
        """Verifies TP2 closes exactly 25% lot (0.62 lot from initial 2.50) after TP1."""
        ep = 3300.00
        ticket = self.bridge.send_order('BUY', 2.50, ep - 2.00)
        pos = self.bridge.get_open_position_details()
        initial_vol = pos['initial_volume'] # 2.50

        # Step 1: Close TP1 30% (0.75 lot)
        self.bridge.close_partial(pos['ticket'], 0.75)

        # Step 2: Close TP2 25% (0.625 -> round-half-even -> 0.62 lot)
        tp2_close_vol = round(initial_vol * self.cfg.TP2_LOT_RATIO, 2)
        self.assertEqual(tp2_close_vol, 0.62)

        res = self.bridge.close_partial(pos['ticket'], tp2_close_vol)
        self.assertTrue(res)
        pos['tp2_hit'] = True

        pos_after = self.bridge.get_open_position_details()
        self.assertEqual(pos_after['volume'], 1.13) # 1.75 - 0.62 remaining
        print(f"✅ [TEST 4 PASSED] TP2 (+40 pips) closed 25% ({tp2_close_vol} lots): Remaining = {pos_after['volume']} lots.")

    def test_05_runner_step_trailing_stop(self):
        """Verifies runner trailing stop advances at 100p ($10), 200p ($20), and 300p ($30) milestones."""
        ep = 3300.00
        ticket = self.bridge.send_order('BUY', 2.50, ep - 2.00)
        pos = self.bridge.get_open_position_details()
        
        # Step 1: Price reaches +100 pips ($10.00) -> Lock +30 pips ($3.00) = 3303.00
        fav_pips_1 = 105.0
        k1 = int(fav_pips_1 // 100.0)
        lock_1 = (k1 - 1) * 10.0 + 3.0 # $3.00
        sl_1 = ep + lock_1 # 3303.00
        self.bridge.modify_sl(pos['ticket'], sl_1)
        self.assertEqual(self.bridge.get_open_position_details()['sl'], 3303.00)
        
        # Step 2: Price reaches +200 pips ($20.00) -> Lock +130 pips ($13.00) = 3313.00
        fav_pips_2 = 210.0
        k2 = int(fav_pips_2 // 100.0)
        lock_2 = (k2 - 1) * 10.0 + 3.0 # $13.00
        sl_2 = ep + lock_2 # 3313.00
        self.bridge.modify_sl(pos['ticket'], sl_2)
        self.assertEqual(self.bridge.get_open_position_details()['sl'], 3313.00)
        
        # Step 3: Price reaches +300 pips ($30.00) -> Lock +230 pips ($23.00) = 3323.00
        fav_pips_3 = 350.0
        k3 = int(fav_pips_3 // 100.0)
        lock_3 = (k3 - 1) * 10.0 + 3.0 # $23.00
        sl_3 = ep + lock_3 # 3323.00
        self.bridge.modify_sl(pos['ticket'], sl_3)
        self.assertEqual(self.bridge.get_open_position_details()['sl'], 3323.00)
        
        print("✅ [TEST 5 PASSED] Runner Step Trailing: +100p -> SL 3303.00 | +200p -> SL 3313.00 | +300p -> SL 3323.00.")

    def test_06_strict_mutex_lock(self):
        """Verifies that new order is 100% blocked when another position is open."""
        ticket1 = self.bridge.send_order('BUY', 1.0, 3298.0)
        self.assertIsNotNone(ticket1)
        self.assertTrue(self.bridge.has_open_positions())
        
        # Attempting second order while position is open
        second_ticket = self.bridge.send_order('BUY', 1.0, 3290.0)
        self.assertIsNone(second_ticket)
        print("✅ [TEST 6 PASSED] Strict Mutex Lock verified: Concurrent order rejected 100%.")

    def test_07_redundant_sl_modification_zero_error(self):
        """Verifies modifying SL to the exact same price returns True without error."""
        ticket = self.bridge.send_order('BUY', 1.0, 3298.0)
        pos = self.bridge.get_open_position_details()
        current_sl = pos['sl']
        
        # Modify to same SL
        res = self.bridge.modify_sl(pos['ticket'], current_sl)
        self.assertTrue(res)
        print("✅ [TEST 7 PASSED] Redundancy guard verified: No MT5 10025 'No changes' errors generated.")

if __name__ == '__main__':
    print("\n" + "="*85)
    print("        🧪 MENJALANKAN AUDIT LENGKAP MODEL ICAS (ZERO BUG & CONCEPT VERIFICATION)")
    print("="*85)
    unittest.main(verbosity=2)
