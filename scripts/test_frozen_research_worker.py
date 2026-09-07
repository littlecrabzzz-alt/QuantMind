import copy
import unittest

import pandas as pd

from frozen_research_worker import choose_universe, check_account


class WorkerTest(unittest.TestCase):
    def test_future_liquidity_cannot_select_universe(self):
        frame = pd.DataFrame({"symbol": ["SH600000", "SH600001", "SH600001"],
                              "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2025-01-02"]),
                              "volume": [100, 100, 100], "amount": [200, 100, 100000]})
        result = choose_universe(frame, "2024-12-31", {"liquidity_days": 60, "min_observations": 1, "size": 1})
        self.assertEqual(result["symbol"].tolist(), ["SH600000"])

    def test_cash_and_net_fee_reconciliation(self):
        report = pd.DataFrame({"account": [999., 1088.], "return": [0., 90/999],
                               "cost": [1/1000, 1/999]})
        class Position:
            def __init__(self, cash, stock_value):
                self.cash = cash
                self.stock_value = stock_value
            def get_cash(self):
                return self.cash
            def get_stock_list(self):
                return ["SH600000"] if self.stock_value else []
            def get_stock_amount(self, symbol):
                return 1
            def get_stock_price(self, symbol):
                return self.stock_value
        fills = [{"action": "buy", "amount": 900., "cost": 1., "cash_after": 99.},
                 {"action": "sell", "amount": 990., "cost": 1., "cash_after": 1088.}]
        positions = {0: Position(99., 900.), 1: Position(1088., 0.)}
        checks = check_account(report, positions, fills, 1000.)
        self.assertAlmostEqual(checks["total_return"], .088)
        self.assertAlmostEqual(checks["max_drawdown"], -.001)
        bad = copy.deepcopy(fills)
        bad[-1]["cash_after"] += 1
        with self.assertRaises(RuntimeError):
            check_account(report, positions, bad, 1000.)
        positions[0].stock_value += 1
        with self.assertRaisesRegex(RuntimeError, "positions and cash"):
            check_account(report, positions, fills, 1000.)


if __name__ == "__main__":
    unittest.main()
