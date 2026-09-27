import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from backend.services.research_agent.continuous_stock import freeze, inventory
from backend.services.engine.research import runtime


class StockScopeTests(unittest.TestCase):
    def test_existing_template_is_clipped_without_mutating_source(self):
        cfg = {
            "source": "/data/research/inputs/test",
            "snapshot_id": "test",
            "manifest_sha256": "a" * 64,
        }
        base = {
            "split": {
                "train": ["2023-01-03", "2024-12-31"],
                "valid": ["2025-01-06", "2025-03-31"],
                "test": ["2025-04-07", "2026-08-31"],
            },
            "features": ["mom_ret_20d"],
            "universe": {"size": 100},
            "portfolio": {"initial_capital": 10000000},
            "exchange": {},
        }
        with (
            patch.object(runtime, "ROOT", Path("/tmp/no-test-stock-override")),
            patch.object(runtime, "settings", return_value=cfg),
            patch.object(runtime.frozen, "read", return_value=base),
            patch.object(runtime, "code_hashes", return_value={}),
        ):
            frozen = freeze("2026-03-24")
        self.assertEqual(base["split"]["test"][1], "2026-08-31")
        self.assertEqual(frozen["base_config"]["split"]["test"][1], "2026-03-24")
        self.assertEqual(frozen["base_config"]["development_end"], "2026-03-24")
        self.assertNotIn("development_end", base)
        self.assertNotIn("source", inventory(frozen))

    def test_no_future_lag_or_python_in_factor_expression(self):
        from research_expression import validate

        for e in (
            "lag(mom_ret_20d,-1)",
            '__import__("os")',
            'open("x")',
            "mom_ret_20d.__class__",
        ):
            with self.assertRaises((ValueError, SyntaxError)):
                validate(e, ["mom_ret_20d"])
        self.assertEqual(validate("rank(mom_ret_20d)", ["mom_ret_20d"])["lookback"], 0)


class StockAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_or_pending_baseline_cannot_admit_factor(self):
        from backend.services.research_agent.continuous_stock import submit
        from backend.services.engine.qlib_app.services.backtest_persistence import (
            BacktestPersistence,
        )

        task = {
            "id": "stock",
            "kind": "stock_factor",
            "experiments": {"baseline": {"expression": "", "backtest_id": "original"}},
        }
        program = {
            "tasks": {"stock": task},
            "contract": {"max_experiments_per_task": 6},
            "stock_contract": {
                "manifest_sha256": "a" * 64,
                "base_config": {"features": ["mom_ret_20d"]},
            },
        }
        action = {
            "action": "stock_factor",
            "name": "test",
            "hypothesis": "add a causal feature",
            "expression": "rank(mom_ret_20d)",
        }
        for state in ("failed", "pending"):
            with patch.object(
                BacktestPersistence,
                "get_run",
                new=AsyncMock(return_value={"status": state}),
            ):
                with self.assertRaisesRegex(ValueError, "baseline_must_complete"):
                    await submit(
                        "id",
                        program,
                        task,
                        action,
                        SimpleNamespace(user_id="1", tenant_id="test"),
                    )


if __name__ == "__main__":
    unittest.main()
