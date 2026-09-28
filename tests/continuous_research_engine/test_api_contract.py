"""Run in the Engine image (shares existing platform dependencies)."""

import asyncio
import copy
from contextlib import asynccontextmanager
import unittest
from unittest.mock import patch, AsyncMock
from backend.services.engine.routers.continuous_research import (
    act,
    ExperimentAction,
    ReportAction,
    Command,
    command,
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

    async def test_evidence_followup_saved_without_task_and_can_reference_parent(self):
        self.t["experiments"]["own"] = {"backtest_id": "owned"}
        parent = next(t for t in self.c["tasks"].values() if t is not self.t)
        parent["experiments"]["prior"] = {"backtest_id": "parent-owned"}
        for i in range(17):
            st.add_task(self.c, "risk", f"queued-{i}", "evidence")
        request = {
            "kind": "evidence_review",
            "topic": "trend",
            "question": "核对原件",
            "reason": "摘要不含逐日持仓",
            "backtest_ids": ["owned", "parent-owned"],
        }
        with patch(
            "backend.services.engine.routers.continuous_research.results",
            new=AsyncMock(
                return_value={"own": {"backtest_id": "owned", "status": "completed"}}
            ),
        ):
            response = await act(
                "x",
                self.c,
                self.t,
                {"action": "report", "text": "a" * 100, "followups": [request]},
                None,
                None,
            )
        self.assertTrue(response["saved"])
        self.assertEqual(len(self.c["tasks"]), 20)
        saved = self.t["reports"][0]["followups"][0]
        self.assertTrue(saved["awaiting_evidence"])
        self.assertEqual(saved["backtest_ids"], ["owned", "parent-owned"])
        self.assertNotIn("task_id", saved)

    async def test_invalid_evidence_requests_cannot_mutate_reports_or_queue(self):
        self.t["experiments"]["own"] = {"backtest_id": "owned"}
        stock = st.add_task(self.c, "stock_signal", "stock question", "reason")
        self.c["tasks"][stock]["experiments"]["s"] = {"backtest_id": "stock-run"}
        proposal = {
            "kind": "evidence_review",
            "topic": "trend",
            "question": "review",
            "reason": "missing",
        }
        invalid = (
            dict(proposal, backtest_ids=[]),
            dict(proposal, backtest_ids=["unknown-or-other-programme"]),
            dict(proposal, backtest_ids=["stock-run"]),
            dict(proposal, backtest_ids=["owned", "owned"]),
            dict(proposal, backtest_ids=["owned"] * 7),
            dict(proposal, backtest_ids=["owned"], topic="stock_signal"),
            dict(proposal, backtest_ids=["owned"], kind="research"),
            dict(proposal, backtest_ids=["owned"], kind="experiment"),
        )
        with patch(
            "backend.services.engine.routers.continuous_research.results",
            new=AsyncMock(
                return_value={"own": {"backtest_id": "owned", "status": "completed"}}
            ),
        ):
            for request in invalid:
                before = copy.deepcopy(self.c)
                with self.subTest(request=request), self.assertRaises(ValueError):
                    await act(
                        "x",
                        self.c,
                        self.t,
                        {"action": "report", "text": "a" * 100, "followups": [request]},
                        None,
                        None,
                    )
                self.assertEqual(self.c, before)

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

    async def test_model_feedback_survives_successful_report_without_raw_output(self):
        await self.check_feedback_survives_report(calls=1)

    async def test_model_feedback_without_call_count_preserves_unknown(self):
        await self.check_feedback_survives_report(calls=None)

    async def check_feedback_survives_report(self, calls):
        self.c.update(desired="running", controller={"id": "worker", "until": 1e20})
        self.t.update(
            kind="evidence_review",
            evidence={"id": "packet"},
            status="running",
            lease="lease",
            lease_until=1e20,
            generation=self.c["generation"],
        )
        if calls is not None:
            self.t["usage"]["calls"] = calls
        else:
            self.t["usage"].pop("calls", None)  # Explicit legacy fixture.
        self.assertEqual(self.t["usage"].get("calls"), calls)
        self.t["pending_action"] = {"raw": "must not be archived in feedback"}

        @asynccontextmanager
        async def edit(ident, auth):
            yield self.c, None

        async def send(op, data):
            return await command(
                "x",
                Command(
                    op=op,
                    worker="worker",
                    task_id=self.t["id"],
                    lease="lease",
                    data=data,
                ),
                None,
            )

        with patch(
            "backend.services.engine.routers.continuous_research.edit", new=edit
        ):
            await send("feedback", {"message": "invalid single JSON"})
            with patch(
                "backend.services.engine.routers.continuous_research.results",
                new=AsyncMock(return_value={}),
            ):
                await send(
                    "action",
                    {
                        "action": {
                            "action": "report",
                            "text": "a" * 100,
                            "evidence_ids": ["packet"],
                            "followups": [],
                        }
                    },
                )
        self.assertNotIn("feedback", self.t)
        self.assertNotIn("pending_action", self.t)
        events = [e for e in self.c["events"] if e["kind"] == "model_feedback"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reason"], "invalid single JSON")
        self.assertEqual(events[0]["model_calls"], calls)
        self.assertEqual(events[0]["task_id"], self.t["id"])
        self.assertNotIn("raw", str(events[0]))
        self.assertEqual(self.t["usage"].get("calls"), calls)
        self.assertEqual(len(self.t["reports"]), 1)

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


class IncidentAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = st.initial({"end_date": "2026-03-24", "concurrency": 6})
        self.c["stock_contract"] = None
        self.c["stock_scope_hold"] = {"incident_id": "stock-boundary-20260927"}
        existing = next(iter(self.c["tasks"].values()))
        existing["reports"] = [{"text": "original report remains unchanged"}]
        self.data = {
            "topic": "method_review",
            "question": "D3 更正：核对已知污染字段与最小补证要求",
            "reason": "仅复核开发边界事故，不提供或重用被污染的模型指标。",
            "evidence": {
                "boundary": "2026-03-24",
                "sources": [{"path": "incident-review.json", "sha256": "a" * 64}],
                "checks": [{"status": "insufficient_evidence"}],
            },
        }

    async def run_command(self, op, data):
        @asynccontextmanager
        async def edit(ident, auth):
            yield self.c, None

        with patch(
            "backend.services.engine.routers.continuous_research.edit", new=edit
        ):
            return await command("this-program", Command(op=op, data=data), None)

    async def test_held_scope_cannot_expand_or_repair_even_when_stopped(self):
        for op in ("expand_stock", "repair_stock_input"):
            for hold in ({"incident_id": "stock-boundary-20260927"}, {}, None):
                self.c["stock_scope_hold"] = hold
                before = copy.deepcopy(self.c)
                with (
                    self.subTest(op=op, hold=hold),
                    patch(
                        "backend.services.research_agent.continuous_stock.freeze"
                    ) as freeze,
                ):
                    with self.assertRaisesRegex(ValueError, "held_pending_boundary"):
                        await self.run_command(op, {})
                    freeze.assert_not_called()
                    self.assertEqual(self.c, before)

    async def test_contaminated_fields_are_rejected_at_every_nested_shape(self):
        for key in ("model_metadata_metrics", "test_metrics", "model_metrics"):
            for fragment in (
                {key: {"value": 0.9}},
                {"rows": [{"nested": [{key: None}]}]},
                {"nested": {"rows": [{"deeper": {key: "not admitted"}}]}},
            ):
                data = copy.deepcopy(self.data)
                data["evidence"].update(fragment)
                before = copy.deepcopy(self.c)
                original_data = copy.deepcopy(data)
                with self.subTest(key=key, fragment=fragment):
                    with self.assertRaisesRegex(ValueError, "quarantined_metric_field"):
                        await self.run_command("add_evidence_review", data)
                    self.assertEqual(self.c, before)
                    self.assertEqual(data, original_data)

    async def test_d3_correction_can_name_fields_in_text_without_new_experiments(self):
        data = copy.deepcopy(self.data)
        data["evidence"]["checks"] = [
            {
                "finding": "model_metadata_metrics、test_metrics、model_metrics 来自受影响路径，旧结论不可据此升级。",
                "quarantined_field_names": [
                    "model_metadata_metrics",
                    "test_metrics",
                    "model_metrics",
                ],
                "required_evidence": "仅在边界隔离另行验收后恢复；当前未提供污染指标数值。",
            }
        ]
        previous = copy.deepcopy(self.c["tasks"])
        response = await self.run_command("add_evidence_review", data)
        task = self.c["tasks"][response["task_id"]]
        self.assertEqual(task["kind"], "evidence_review")
        self.assertEqual(task["experiments"], {})
        self.assertEqual(task["evidence"]["checks"], data["evidence"]["checks"])
        self.assertEqual(task["evidence"]["sha256"], st.fingerprint(data["evidence"]))
        self.assertIsNone(self.c["stock_contract"])
        for ident, old in previous.items():
            self.assertEqual(self.c["tasks"][ident], old)


if __name__ == "__main__":
    unittest.main()
