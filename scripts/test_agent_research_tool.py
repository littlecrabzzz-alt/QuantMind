import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent_research_tool as tool


class ResearchToolTest(unittest.TestCase):
    def setUp(self):
        self.base = tool.frozen.read(tool.ROOT / "config/research_controls_cn_l1.json")

    def test_agent_cannot_change_evaluation_or_resource_contract(self):
        for changes in ({"split": {}}, {"exchange": {}}, {"model_params": {"num_threads": 64}},
                        {"model_params": {"learning_rate": float("nan")}},
                        {"features": ["mom_ret_20d", "future_return"]},
                        {"features": ["mom_ret_20d", "mom_ret_20d"]},
                        {"model_params": {"num_leaves": 4.5}},
                        {"features": ["mom_ret_20d", "vol_std_20"], "model_params": {"max_depth": 2}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tool.candidate_config(self.base, changes)

    def test_ablation_preserves_all_non_feature_settings(self):
        original = copy.deepcopy(self.base)
        features = ["mom_ret_20d", "vol_std_20"]
        changed = tool.candidate_config(self.base, {"features": features})
        self.assertEqual(self.base, original)
        changed["features"] = original["features"]
        self.assertEqual(changed, original)

    def test_half_returns_include_boundary_day_and_compound_to_total(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "model-equity.csv").write_text("account\n90\n100\n80\n120\n")
            first, second = tool.half_returns(directory, 100)
        self.assertEqual(first, 0)
        self.assertAlmostEqual(second, .2)
        self.assertAlmostEqual((1 + first) * (1 + second) - 1, .2)

    def test_duplicate_or_unfinished_runs_cannot_be_resubmitted(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            d = session / "experiments/E00"
            d.mkdir(parents=True)
            state = {"id": "E00", "kind": "baseline", "status": "submission_uncertain"}
            tool.frozen.write(d / "state.json", state)
            contract = {"deadline_epoch": 99999999999, "base_config": self.base, "maximum_candidates": 3}
            proposal = {"kind": "candidate", "hypothesis": "test", "expected_outcome": "test",
                        "evidence": "E00", "changes": {"model_params": {"max_depth": 4}}}
            with patch.object(tool, "checked_contract", return_value=(contract, session)):
                with self.assertRaisesRegex(ValueError, "active or uncertain"):
                    tool.submit(session, proposal)
                state.update(status="completed", config_sha256=tool.fingerprint(self.base))
                tool.frozen.write(d / "state.json", state)
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    tool.submit(session, proposal)

    def test_final_decision_rejects_a_return_only_winner(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            for i in range(4):
                d = session / f"experiments/E{i:02d}"
                d.mkdir(parents=True)
                tool.frozen.write(d / "state.json", {})
            contract = {"acceptance": {"min_return_improvement": .005,
                        "max_drawdown_degradation": .01, "min_half_excess": -.005}}
            def result(ident):
                is_base = ident == "E00"
                return {"id": ident, "status": "completed",
                        "kind": "baseline" if is_base else "stress" if ident == "E03" else "candidate",
                        "proposal": {"origin": "E01"},
                        "summary": {"comparison": {"model": {
                            "total_return": .1 if is_base else .15,
                            "max_drawdown": -.03 if is_base else -.15}}},
                        "model_metrics": {"validation_metrics": {"rank_ic": .02}},
                        "development_half_returns": [.05, .05]}
            with patch.object(tool, "checked_contract", return_value=(contract, session)), \
                    patch.object(tool, "refresh", side_effect=lambda _, ident: result(ident)):
                with self.assertRaisesRegex(ValueError, "fails fixed development gates"):
                    tool.finish(session, {"selected": "E01", "reason": "high return", "next_question": "test"})
            self.assertFalse((session / "decision.json").exists())


if __name__ == "__main__":
    unittest.main()
