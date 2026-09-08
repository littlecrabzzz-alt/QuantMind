"""Isolated numerical and contract checks; no API, DB or production data."""
import copy
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch, AsyncMock

import numpy as np
import pandas as pd

import research_expression as expression
from backend.services.engine.research.coordinator import experiment_config, allowed_candidates, advance, require_method_result
from backend.services.engine.research import runtime
from backend.services.engine.routers.research_runs import NewResearch


class FactorContractTests(unittest.TestCase):
    def frame(self):
        rng = np.random.default_rng(71)
        rows = [{"symbol": f"SH600{i:03}", "trade_date": d, "a": rng.normal(), "b": rng.uniform(.1, 2)}
                for d in pd.date_range("2025-01-01", periods=80) for i in range(20)]
        return pd.DataFrame(rows)

    def test_future_rows_cannot_change_past_factor_values(self):
        frame = self.frame()
        prefix = frame[frame.trade_date <= "2025-02-20"]
        for formula in ("rank(mean(a, 5)) - lag(rank(b), 3)", "a / std(b, 10)", "rank(log1p_abs(a))"):
            pd.testing.assert_series_equal(expression.evaluate(frame, formula, ["a", "b"]).loc[prefix.index],
                                           expression.evaluate(prefix, formula, ["a", "b"]))
        # Verify lag follows each instrument's observations, never adjacent rows from other names.
        values = expression.evaluate(frame, "lag(a, 1)", ["a", "b"])
        pd.testing.assert_series_equal(values, frame.groupby("symbol").a.shift(1), check_names=False)

    def test_no_execution_future_access_or_unbounded_windows(self):
        for formula in ('__import__("os").system("id")', 'a[-1]', 'lag(a,-1)', 'mean(a,100000)',
                        'a ** 100', 'label+a', 'a.mean()', 'mean(mean(mean(a,60),60),60)', '1+2'):
            with self.subTest(formula=formula), self.assertRaises((ValueError, SyntaxError)):
                expression.validate(formula, ["a", "b"])
        values = expression.evaluate(self.frame(), "a / (b-b)", ["a", "b"])
        self.assertTrue(values.isna().all())

    def test_metrics_purge_labels_at_split_end(self):
        frame = self.frame()
        frame["signal"] = frame.a
        frame["forward_return"] = frame.a / 100
        frame["label_end"] = frame.trade_date + pd.Timedelta(days=2)
        cfg = {"split": {"valid": ["2025-01-01", "2025-01-10"]}}
        result = expression.diagnostics(frame, "signal", ["a", "b"], cfg)["splits"]["valid"]
        self.assertEqual(result["rows"], 160)
        self.assertEqual(result["rank_ic"], 1)
        self.assertEqual(result["daily"][-1]["date"], "2025-01-08")

    def test_new_factor_augments_baseline_and_cost_stress_changes_only_costs(self):
        base = json.loads((Path(__file__).parents[1]/"config/research_controls_cn_l1.json").read_text())
        contract = {"base_config": base}
        candidate = experiment_config(contract, {"kind": "candidate", "factor": {
            "expression": "rank(mom_ret_20d) * rank(amt_ratio_5_20)"}}, {})
        self.assertEqual(candidate["features"], base["features"]+["research_signal"])
        state = {"experiments": [{"id": "E01", "config": candidate}]}
        stressed = experiment_config(contract, {"kind": "stress", "origin": "E01"}, state)
        self.assertEqual(stressed["derived_factor"], candidate["derived_factor"])
        self.assertEqual(stressed["features"], candidate["features"])
        self.assertEqual(stressed["exchange"]["commission"], 2*candidate["exchange"]["commission"])
        self.assertNotIn("derived_factor", base)

    def test_start_contract_rejects_extra_identity_and_long_windows(self):
        common = {"idempotency_key": "test-request-1", "kind": "strategy", "node_id": "fixture"}
        with self.assertRaises(ValueError):
            NewResearch(**common, user_id="someone_else")
        with self.assertRaises(ValueError):
            NewResearch(**common, hours=8.01)

    def test_provider_backoff_and_observed_invalid_response(self):
        contract = {"model": "fixture", "model_base_url": "https://fixture.invalid"}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            limited = urllib.error.HTTPError(contract["model_base_url"], 429, "limited", {"Retry-After": "60"}, None)
            with patch.object(runtime, "credentials", return_value={"base_url": contract["model_base_url"], "api_key": "test-only"}), \
                    patch.object(runtime.urllib.request, "urlopen", side_effect=limited) as send:
                for _ in range(2):
                    self.assertIsNone(runtime.model_decision(folder, contract, "choose", {"selected": {}}, "fixture", time.time()+300))
                self.assertEqual(send.call_count, 1, "429 retry ignored provider backoff")
            runtime.frozen.write(folder / "response.json", {"choices": [{"message": {"content": "no tool call"}}]})
            with self.assertRaises(runtime.InvalidDecision):
                runtime.model_decision(folder, contract, "choose", {"selected": {}}, "fixture", time.time()+300)

    def test_assignment_is_returned_for_model_correction_without_computing(self):
        base = json.loads((Path(__file__).parents[1]/"config/research_controls_cn_l1.json").read_text())
        state = {"stage": "propose", "experiments": [], "candidate_count": 0}
        row = {"run_id": "fixture", "case_id": "a"*32, "status": "running", "kind": "method", "goal": "fixture",
               "deadline_epoch": time.time()+1000, "checkpoint": state,
               "contract": {"base_config": base, "candidate_limit": 1, "acceptance": {}}}
        decision = {"hypothesis": "fixture", "expected_outcome": "fixture", "evidence": "fixture",
                    "expression": "research_signal = rank(mom_ret_20d)"}
        store = AsyncMock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, "ROOT", Path(tmp)), \
                patch.object(runtime, "model_decision", return_value=decision):
            asyncio.run(advance(row, store, "fixture"))
        self.assertEqual(state["candidate_count"], 0)
        self.assertNotIn("active", state)
        self.assertIn("纯表达式", state["corrections"]["candidate-1"][0])
        store.checkpoint.assert_awaited_once()

    def test_method_needs_a_real_completed_factor_result(self):
        state = {"experiments": [{"status": "completed", "result": {"summary": {}}},
                                 {"status": "failed", "result": {}}]}
        with self.assertRaisesRegex(ValueError, "没有实际完成"):
            require_method_result({"kind": "method"}, state)
        require_method_result({"kind": "strategy"}, state)


if __name__ == "__main__":
    unittest.main()
