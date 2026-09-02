"""
Dedicated Live Simulation Test for Early BE+ @ 15 Pips (+ $1.50) on Both BUY and SELL
"""
import unittest
from config import config
from src.execution.mt5_bridge import IcasMT5Bridge

class TestEarlyBE15Pips(unittest.TestCase):
    def setUp(self):
        self.cfg = config
        self.cfg.EARLY_BE_TRIGGER_PIPS = 15.0 # Set to 15.0 pips
        self.bridge = IcasMT5Bridge(self.cfg)
        self.bridge.initialize()

    def test_buy_lifecycle_with_15_pips_be(self):
        """Simulates full BUY order lifecycle with BE+ trigger at +15 pips ($1.50)."""
        ep = 3300.00
        sl_initial = ep - 2.00 # 3298.00
        ticket = self.bridge.send_order('BUY', 2.50, sl_initial)
        self.assertIsNotNone(ticket)
        
        pos = self.bridge.get_open_position_details()
        self.assertEqual(pos['sl'], 3298.00)
        self.assertFalse(pos['be_set'])
        
        # 1. Price moves to 3301.00 (+10 pips) -> BE+ must NOT trigger
        cur_price = 3301.00
        fav_pips = (cur_price - ep) * 10.0 # 10.0 pips
        if not pos['be_set'] and fav_pips >= self.cfg.EARLY_BE_TRIGGER_PIPS:
            pos['sl'] = ep + 0.10
            pos['be_set'] = True
        self.assertFalse(pos['be_set'])
        self.assertEqual(pos['sl'], 3298.00)
        
        # 2. Price reaches 3301.50 (+15 pips) -> BE+ MUST trigger
        cur_price = 3301.50
        fav_pips = (cur_price - ep) * 10.0 # 15.0 pips
        if not pos['be_set'] and fav_pips >= self.cfg.EARLY_BE_TRIGGER_PIPS:
            new_sl = ep + (self.cfg.BE_PROFIT_OFFSET_PIPS * 0.10) # 3300.30
            res = self.bridge.modify_sl(ticket, new_sl)
            self.assertTrue(res)
            pos['be_set'] = True
            
        pos_after = self.bridge.get_open_position_details()
        self.assertTrue(pos_after['be_set'])
        self.assertEqual(pos_after['sl'], 3300.30)
        print("✅ [BUY TEST PASSED] BE+ at +15 pips ($1.50): SL successfully moved from 3298.00 -> 3300.30.")

    def test_sell_lifecycle_with_15_pips_be(self):
        """Simulates full SELL order lifecycle with BE+ trigger at +15 pips ($1.50)."""
        ep = 3300.00
        sl_initial = ep + 2.00 # 3302.00
        ticket = self.bridge.send_order('SELL', 2.50, sl_initial)
        self.assertIsNotNone(ticket)
        
        pos = self.bridge.get_open_position_details()
        self.assertEqual(pos['sl'], 3302.00)
        self.assertFalse(pos['be_set'])
        
        # 1. Price drops to 3299.00 (+10 pips favorable) -> BE+ must NOT trigger
        cur_price = 3299.00
        fav_pips = (ep - cur_price) * 10.0 # 10.0 pips
        if not pos['be_set'] and fav_pips >= self.cfg.EARLY_BE_TRIGGER_PIPS:
            pos['sl'] = ep - 0.10
            pos['be_set'] = True
        self.assertFalse(pos['be_set'])
        self.assertEqual(pos['sl'], 3302.00)
        
        # 2. Price drops to 3298.50 (+15 pips favorable) -> BE+ MUST trigger
        cur_price = 3298.50
        fav_pips = (ep - cur_price) * 10.0 # 15.0 pips
        if not pos['be_set'] and fav_pips >= self.cfg.EARLY_BE_TRIGGER_PIPS:
            new_sl = ep - (self.cfg.BE_PROFIT_OFFSET_PIPS * 0.10) # 3299.70
            res = self.bridge.modify_sl(ticket, new_sl)
            self.assertTrue(res)
            pos['be_set'] = True
            
        pos_after = self.bridge.get_open_position_details()
        self.assertTrue(pos_after['be_set'])
        self.assertEqual(pos_after['sl'], 3299.70)
        print("✅ [SELL TEST PASSED] BE+ at +15 pips ($1.50): SL successfully moved from 3302.00 -> 3299.70.")

if __name__ == '__main__':
    print("\n" + "="*85)
    print("      🧪 VERIFIKASI PENGUJIAN EARLY BE+ DI +15 PIPS ($1.50) BUY & SELL")
    print("="*85)
    unittest.main(verbosity=2)
