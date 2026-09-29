"""Research families bound references, retries and descendant experiment spend."""

import ast
import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.services.engine.routers import continuous_research as api
from backend.services.research_agent import continuous_state as st


class DurableStrategies:
    """Independent strategy commit survives rollback of the research-state copy."""

    def __init__(self):
        self.rows = []
        self.save_calls = 0

    async def save(self, user, name, code, metadata):
        self.save_calls += 1
        row = {
            "id": str(len(self.rows) + 1),
            "user": user,
            "code": code,
            "config": copy.deepcopy(metadata["config"]),
        }
        self.rows.append(row)
        return {"id": row["id"]}

    async def execute(self, sql, params):
        statement = str(sql)
        if "continuous_family" in statement:
            rows = [
                r
                for r in self.rows
                if r["user"] == params["user"]
                and r["config"]["continuous_program"] == params["program"]
                and r["config"]["continuous_family"] == params["family"]
            ]
            return SimpleNamespace(
                all=lambda: [
                    (
                        r["config"]["continuous_task"],
                        r["config"]["continuous_experiment_key"],
                        r["config"]["continuous_marker"],
                    )
                    for r in rows
                ]
            )
        if "SELECT id,code" in statement:
            row = next(
                (
                    r
                    for r in self.rows
                    if r["user"] == params["user"]
                    and r["config"]["continuous_marker"] == params["marker"]
                ),
                None,
            )
            return SimpleNamespace(
                first=lambda: (row["id"], row["code"]) if row else None
            )
        raise AssertionError("unexpected SQL in synthetic reservation test")


class AssignmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = st.initial(
            {
                "start_date": "2014-08-01",
                "end_date": "2026-03-24",
                "symbols": ["510300.SH"],
                "max_experiments_per_task": 6,
                "execution": copy.deepcopy(api.EXECUTION),
            }
        )
        self.auth = SimpleNamespace(user_id=1, tenant_id="tenant")
        self.data = {
            "topic": "risk",
            "question": "检验固定仓位与单一风险分配机制的区别",
            "reason": "使用既存完整同条件基线与预先冻结的实验预算。",
            "family_key": "allocation-test-v1",
            "max_new_experiments": 2,
            "reference_backtest_ids": ["registered"],
            "brief": {
                "boundary": "2026-03-24",
                "sources": [{"path": "brief.json", "sha256": "a" * 64}],
            },
        }

    async def send(self, data):
        @asynccontextmanager
        async def edit(ident, auth):
            yield self.c, None

        with patch.object(api, "edit", edit):
            return await api.command(
                "program", api.Command(op="add_research", data=data), None
            )

    async def test_assignment_replay_is_idempotent_and_changed_request_conflicts(self):
        with patch(
            "backend.services.research_agent.continuous_evidence.inspect_evidence",
            new=AsyncMock(return_value={"id": "packet", "sha256": "b" * 64}),
        ) as read:
            first = await self.send(self.data)
            saved = copy.deepcopy(self.c)
            replay = await self.send(self.data)
            self.assertEqual(first["task_id"], replay["task_id"])
            self.assertTrue(replay["already_applied"])
            self.assertEqual(self.c, saved)
            read.assert_awaited_once()
            with self.assertRaisesRegex(ValueError, "assignment_conflict"):
                await self.send(dict(self.data, max_new_experiments=3))
            self.assertEqual(self.c, saved)

    async def test_unverified_reference_cannot_create_family(self):
        saved = copy.deepcopy(self.c)
        with patch(
            "backend.services.research_agent.continuous_evidence.inspect_evidence",
            new=AsyncMock(side_effect=ValueError("identity_mismatch")),
        ):
            with self.assertRaisesRegex(ValueError, "identity_mismatch"):
                await self.send(self.data)
        self.assertEqual(self.c, saved)

    async def test_bad_boundary_quarantined_fields_and_duplicate_references_rejected(
        self,
    ):
        for data in (
            dict(self.data, brief=dict(self.data["brief"], boundary="2026-03-25")),
            dict(
                self.data, brief=dict(self.data["brief"], nested={"test_metrics": {}})
            ),
            dict(self.data, reference_backtest_ids=["registered", "registered"]),
            dict(self.data, max_new_experiments=7),
        ):
            saved = copy.deepcopy(self.c)
            with self.subTest(data=data), self.assertRaises(ValueError):
                await self.send(data)
            self.assertEqual(self.c, saved)

    async def test_family_budget_includes_descendants_and_allows_identity_replay(self):
        root = next(iter(self.c["tasks"].values()))
        root["family_id"] = "family"
        self.c["research_families"] = {"family": {"max_new_experiments": 1}}
        child = self.c["tasks"][
            st.add_task(self.c, "risk", "child", "reason", parent=root["id"])
        ]
        action = {
            "action": "experiment",
            "name": "test",
            "hypothesis": "fixed hypothesis",
            "code": 'def on_signal(ctx):\n return {"targets":None,"reason":"test"}',
            "parameters": {"symbols": ["510300.SH"]},
            "start_date": "2015-01-01",
            "end_date": "2015-01-10",
        }
        key = st.fingerprint(
            [
                ast.dump(ast.parse(action["code"])),
                action["parameters"],
                action["start_date"],
                action["end_date"],
            ]
        )
        child["experiments"][key] = {
            "strategy_id": "1",
            "revision_id": "r",
            "backtest_id": "b",
        }
        self.assertEqual(st.family_budget(self.c, root)["remaining"], 0)
        with self.assertRaisesRegex(ValueError, "family_experiment_budget"):
            await api.act(
                "program", self.c, root, action, self.auth, DurableStrategies()
            )
        self.assertEqual(
            (await api.act("program", self.c, child, action, None, None))[
                "backtest_id"
            ],
            "b",
        )
        child["reports"] = [
            {"followups": [{"topic": "risk", "question": "more", "reason": "evidence"}]}
        ]
        st.promote_followups(self.c)
        self.assertTrue(
            child["reports"][0]["followups"][0]["awaiting_family_budget_review"]
        )

    async def _reservation_failure_recovery(self, lose_state):
        programme = "d" * 32
        root = next(iter(self.c["tasks"].values()))
        root["family_id"] = "family"
        self.c["research_families"] = {"family": {"max_new_experiments": 1}}
        child_id = st.add_task(self.c, "risk", "child", "reason", parent=root["id"])
        root_id = root["id"]
        before = copy.deepcopy(self.c)
        action = {
            "action": "experiment",
            "name": "test",
            "hypothesis": "fixed hypothesis",
            "code": 'def on_signal(ctx):\n return {"targets":None,"reason":"test"}',
            "parameters": {"symbols": ["510300.SH"]},
            "start_date": "2015-01-01",
            "end_date": "2015-01-10",
        }
        durable = DurableStrategies()
        public_reservations = set()
        fail_once = True

        async def backtest(sid, request, auth):
            nonlocal fail_once
            public_reservations.add((sid, request.key))
            if fail_once:
                fail_once = False
                if lose_state:
                    raise RuntimeError(
                        "synthetic process death after independent reserve"
                    )
                raise HTTPException(
                    503, "synthetic queue failure after independent reserve"
                )
            return {"backtest_id": "r01bt-" + "c" * 32, "status": "pending"}

        with (
            patch.object(api, "get_strategy_storage_service", return_value=durable),
            patch.object(
                api.public,
                "publish",
                new=AsyncMock(return_value={"revision_id": "a" * 64}),
            ) as publish,
            patch.object(
                api.public, "backtest", new=AsyncMock(side_effect=backtest)
            ) as run,
        ):
            with self.assertRaises(
                RuntimeError if lose_state else HTTPException
            ) as caught:
                await api.act(programme, self.c, root, action, self.auth, durable)
            if not lose_state:
                self.assertEqual(caught.exception.status_code, 503)
            self.assertEqual(root["experiments"], {})
            self.assertEqual(len(durable.rows), 1)
            self.assertEqual(len(public_reservations), 1)
            if lose_state:
                self.c = before  # A crash rolls back state, not the independently saved strategy.
                self.assertEqual(
                    st.family_budget(self.c, self.c["tasks"][root_id])["used"], 0
                )
            sibling = self.c["tasks"][child_id]
            root = self.c["tasks"][root_id]
            with self.assertRaisesRegex(ValueError, "family_experiment_budget"):
                await api.act(programme, self.c, sibling, action, self.auth, durable)
            self.assertEqual(st.family_budget(self.c, root)["used"], 1)
            self.assertEqual(len(root["experiment_reservations"]), 1)
            self.assertEqual(durable.save_calls, 1)
            self.assertEqual(run.await_count, 1)
            recovered = await api.act(
                programme, self.c, root, action, self.auth, durable
            )
            self.assertEqual(recovered["backtest_id"], "r01bt-" + "c" * 32)
            self.assertEqual(len(public_reservations), 1)
            self.assertEqual(durable.save_calls, 1)
            self.assertEqual(
                st.family_budget(self.c, root)["used"], 1
            )  # union, not double charge
            self.assertEqual(st.family_budget(self.c, root)["remaining"], 0)
            self.assertEqual(
                (await api.act(programme, self.c, root, action, self.auth, durable))[
                    "backtest_id"
                ],
                recovered["backtest_id"],
            )
            self.assertEqual(run.await_count, 2)
            self.assertEqual(publish.await_count, 2)

    async def test_enqueue_503_reservation_blocks_sibling_but_same_identity_resumes(
        self,
    ):
        await self._reservation_failure_recovery(lose_state=False)

    async def test_lost_state_recovers_durable_reservation_before_sibling_budget_check(
        self,
    ):
        await self._reservation_failure_recovery(lose_state=True)

    async def test_inspection_budget_does_not_force_new_compute(self):
        t = next(iter(self.c["tasks"].values()))
        t["inspections"] = {str(i): {} for i in range(24)}
        saved = copy.deepcopy(t)
        with self.assertRaisesRegex(ValueError, "inspection_budget"):
            await api.act(
                "program", self.c, t, {"action": "inspect_evidence"}, None, None
            )
        self.assertEqual(t, saved)
        t["reference_overviews"] = [{"id": "trusted"}]
        with patch.object(api, "results", new=AsyncMock(return_value={})):
            response = await api.act(
                "program",
                self.c,
                t,
                {"action": "report", "text": "材料不足，不能开展实验。" * 15},
                None,
                None,
            )
        self.assertTrue(response["saved"])
        self.assertEqual(t["experiments"], {})

    def test_same_followup_in_two_families_cannot_merge_budgets(self):
        roots = list(self.c["tasks"].values())[:2]
        roots[0]["family_id"], roots[1]["family_id"] = "one", "two"
        ids = [
            st.add_task(self.c, "risk", "same question", "same reason", parent=r["id"])
            for r in roots
        ]
        self.assertNotEqual(*ids)
        self.assertEqual([self.c["tasks"][i]["family_id"] for i in ids], ["one", "two"])

    def test_child_keeps_new_parent_results_and_frozen_brief(self):
        root = next(iter(self.c["tasks"].values()))
        root.update(
            family_id="family",
            research_brief={"mechanism": "fixed"},
            reference_backtest_ids=[str(i) for i in range(6)],
        )
        root["experiments"]["new"] = {"backtest_id": "new-parent-result"}
        child = self.c["tasks"][
            st.add_task(self.c, "risk", "child", "why", parent=root["id"])
        ]
        self.assertEqual(child["reference_backtest_ids"][0], "new-parent-result")
        self.assertEqual(len(child["reference_backtest_ids"]), 6)
        child["research_brief"]["mechanism"] = "changed"
        self.assertEqual(root["research_brief"]["mechanism"], "fixed")
