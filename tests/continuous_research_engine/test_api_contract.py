"""Run in the Engine image (shares existing platform dependencies)."""

import asyncio
import unittest
from unittest.mock import patch, AsyncMock
from backend.services.engine.routers.continuous_research import (
    act,
    ExperimentAction,
    ReportAction,
)
from backend.services.research_agent import continuous_state as st


class ContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = st.initial(
            {
                "start_date": "2014-08-01",
                "end_date": "2026-03-24",
                "max_experiments_per_task": 6,
                "symbols": ["510300.SH"],
            }
        )
        self.t = next(iter(self.c["tasks"].values()))
        self.action = {
            "action": "experiment",
            "name": "baseline",
            "hypothesis": "test hypothesis",
            "code": 'def on_signal(ctx):\n return {"targets":None,"reason":"test"}',
            "parameters": {"symbols": ["510300.SH"]},
            "start_date": "2015-01-01",
            "end_date": "2015-01-10",
        }

    async def test_holdout_rejected_before_storage(self):
        with self.assertRaisesRegex(ValueError, "holdout"):
            await act(
                "x",
                self.c,
                self.t,
                dict(self.action, end_date="2026-03-25"),
                None,
                None,
            )

    async def test_missing_symbols_rejected_before_storage(self):
        with self.assertRaisesRegex(ValueError, "symbols"):
            await act("x", self.c, self.t, dict(self.action, parameters={}), None, None)

    async def test_existing_id_cannot_be_supplied(self):
        with self.assertRaises(ValueError):
            await act(
                "x", self.c, self.t, dict(self.action, strategy_id="61"), None, None
            )

    async def test_malformed_types_and_unknown_tools(self):
        for action in (
            [],
            {"action": "shell", "command": "x"},
            dict(self.action, code=7),
            dict(self.action, parameters=[]),
        ):
            with self.assertRaises(ValueError):
                await act("x", self.c, self.t, action, None, None)

    async def test_same_code_parameters_dates_reuses_version_across_title_changes(self):
        import ast

        key = st.fingerprint(
            [
                ast.dump(ast.parse(self.action["code"])),
                self.action["parameters"],
                self.action["start_date"],
                self.action["end_date"],
            ]
        )
        self.t["experiments"][key] = {
            "strategy_id": "777",
            "revision_id": "test-revision",
            "backtest_id": "test-run",
        }
        result = await act(
            "x",
            self.c,
            self.t,
            dict(
                self.action,
                name="another title",
                code="# extra comment\n" + self.action["code"],
            ),
            None,
            None,
        )
        self.assertEqual(result["strategy_id"], "777")

    async def test_report_without_results_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires_public"):
            await act(
                "x", self.c, self.t, {"action": "report", "text": "a" * 100}, None, None
            )

    def test_report_invalid_followup_does_not_expand_scope(self):
        with self.assertRaises(ValueError):
            ReportAction.model_validate(
                {
                    "action": "report",
                    "text": "a" * 100,
                    "followups": [
                        {"topic": "live-trading", "question": "x", "reason": "x"}
                    ],
                }
            )

    async def test_full_queue_saves_report_and_defers_followup_without_duplication(
        self,
    ):
        self.t["experiments"]["original"] = {"backtest_id": "original"}
        for i in range(17):
            st.add_task(self.c, "risk", str(i), "evidence")
        with patch(
            "backend.services.engine.routers.continuous_research.results",
            new=AsyncMock(return_value={"original": {"status": "completed"}}),
        ):
            result = await act(
                "x",
                self.c,
                self.t,
                {
                    "action": "report",
                    "text": "a" * 100,
                    "followups": [
                        {"topic": "risk", "question": "next", "reason": "evidence"}
                    ],
                },
                None,
                None,
            )
        self.assertTrue(result["saved"])
        self.assertEqual(len(self.t["reports"]), 1)
        self.assertEqual(len(self.c["tasks"]), 20)
        proposal = self.t["reports"][0]["followups"][0]
        self.assertNotIn("task_id", proposal)
        self.t["status"] = "done"
        st.promote_followups(self.c)
        self.assertIn(proposal["task_id"], self.c["tasks"])
        st.promote_followups(self.c)
        self.assertEqual(len(self.c["tasks"]), 21)
        self.assertEqual(
            sum(t["status"] not in st.TERMINAL for t in self.c["tasks"].values()), 20
        )

    async def test_review_cannot_launch_experiments(self):
        self.t["kind"] = "evidence_review"
        with self.assertRaisesRegex(ValueError, "read_only"):
            await act("x", self.c, self.t, self.action, None, None)

    async def test_review_requires_bound_evidence_and_accepts_no_new_backtest(self):
        self.t.update(kind="evidence_review", evidence={"id": "trusted-packet"})
        report = {"action": "report", "text": "a" * 100}
        with self.assertRaisesRegex(ValueError, "cite_bound"):
            await act("x", self.c, self.t, report, None, None)
        with patch(
            "backend.services.engine.routers.continuous_research.results",
            new=AsyncMock(return_value={}),
        ):
            result = await act(
                "x",
                self.c,
                self.t,
                dict(report, evidence_ids=["trusted-packet"]),
                None,
                None,
            )
        self.assertTrue(result["saved"])
        self.assertEqual(self.t["experiments"], {})
        self.assertEqual(self.t["reports"][0]["evidence_ids"], ["trusted-packet"])

    def test_review_slots_do_not_require_extra_compute_tasks(self):
        for i in range(17):
            st.add_task(self.c, "risk", str(i), "evidence")
        for i in range(6):
            st.add_task(
                self.c, "data_coverage", str(i), "evidence", kind="evidence_review"
            )
        with self.assertRaisesRegex(ValueError, "queue_full"):
            st.add_task(
                self.c, "data_coverage", "overflow", "evidence", kind="evidence_review"
            )


if __name__ == "__main__":
    unittest.main()
