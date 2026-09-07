import copy
import json
from pathlib import Path
import tempfile
import unittest

from run_quant_baseline import main, submit_once
from verify_quant_baseline import financial_checks, research_decision


class BaselineChecksTest(unittest.TestCase):
    def setUp(self):
        self.result = {
            "status": "completed", "total_trades": 2, "total_return": 0.088,
            "benchmark_return": 0.05,
            "trades": [
                {"date": "2025-01-02", "action": "buy", "totalAmount": 900, "commission": 1,
                 "cash_after": 99, "position_value_after": 900, "equity_after": 999},
                {"date": "2025-01-03", "action": "sell", "totalAmount": 990, "commission": 1,
                 "cash_after": 1088, "position_value_after": 0, "equity_after": 1088},
            ],
            "equity_curve": [{"date": "2025-01-02", "value": 999}, {"date": "2025-01-03", "value": 1088}],
        }

    def test_cash_fees_and_initial_drawdown(self):
        result = financial_checks(self.result, 1000)
        self.assertAlmostEqual(result["total_return"], 0.088)
        self.assertEqual(result["recorded_transaction_cost"], 2)
        self.assertAlmostEqual(result["max_drawdown_including_initial_capital"], -0.001)

    def test_inconsistent_cash_is_rejected(self):
        result = copy.deepcopy(self.result)
        result["trades"][-1]["cash_after"] += 1
        with self.assertRaises(RuntimeError):
            financial_checks(result, 1000)

    def test_changed_config_stops_before_api_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "baseline-config.json").write_text(json.dumps({"features": ["changed"]}))
            (root / "state.json").write_text(json.dumps({"config_sha256": "previous"}))
            with self.assertRaisesRegex(RuntimeError, "Configuration changed"):
                main(["train", "--output", temp])

    def test_lost_submission_is_not_repeated_and_saved_response_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = []

            def lost_response():
                calls.append("POST accepted")
                raise TimeoutError("response lost")

            with self.assertRaises(TimeoutError):
                submit_once(root, "training", {"model": "baseline"}, lost_response)
            with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                submit_once(root, "training", {"model": "baseline"}, lost_response)
            (root / "training-submission.json").write_text(json.dumps({"run_id": "existing"}))
            result = submit_once(root, "training", {"model": "baseline"}, lost_response)
            self.assertEqual(result["run_id"], "existing")
            self.assertEqual(len(calls), 1)
            with self.assertRaisesRegex(RuntimeError, "request changed"):
                submit_once(root, "training", {"model": "different"}, lost_response)

    def test_api_change_stops_before_client_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "baseline-config.json").write_text("{}")
            (root / "state.json").write_text(json.dumps({"api": "http://original:8000"}))
            with self.assertRaisesRegex(RuntimeError, "API endpoint changed"):
                main(["train", "--output", temp])

    def test_resume_keeps_original_catalog_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "baseline-config.json").write_text("{}")
            (root / "catalog.json").write_text(json.dumps({"version_id": "frozen"}))
            main(["prepare", "--output", temp], client=object())
            self.assertEqual(json.loads((root / "catalog.json").read_text())["version_id"], "frozen")

    def test_profitable_completed_run_is_not_automatically_approved(self):
        decision = research_decision(financial_checks(self.result, 1000))
        self.assertEqual(decision["status"], "needs_validation")
        self.assertFalse(decision["paper_trading_eligible"])
        self.assertIn("+3.80", decision["benchmark_comparison"])


if __name__ == "__main__":
    unittest.main()
