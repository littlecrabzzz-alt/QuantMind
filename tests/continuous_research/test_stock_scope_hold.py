import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

path = Path(__file__).parents[2] / "scripts/continuous_research/hold_stock_scope.py"
spec = importlib.util.spec_from_file_location("hold_stock_scope", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StockScopeHoldTests(unittest.TestCase):
    def state(self):
        return {
            "stock_contract": {"boundary": "2026-03-24", "manifest": "original"},
            "contract": {"concurrency": 6},
            "sequence": 0,
            "events": [],
            "tasks": {
                "stock": {
                    "id": "stock",
                    "kind": "stock_factor",
                    "status": "waiting_compute",
                    "reports": [],
                },
                "etf": {
                    "id": "etf",
                    "kind": "research",
                    "status": "running",
                    "reports": [],
                },
                "done": {
                    "id": "done",
                    "kind": "stock_factor",
                    "status": "done",
                    "reports": [
                        {
                            "text": "original",
                            "followups": [
                                {
                                    "topic": "stock_signal",
                                    "question": "new",
                                    "reason": "r",
                                }
                            ],
                        }
                    ],
                },
            },
        }

    def test_preserves_originals_and_unrelated_running_work(self):
        c = self.state()
        before = copy.deepcopy(c)
        result = module.hold(
            c,
            "incident-20260927",
            "Confirmed frozen loader boundary violation requires audit.",
        )
        self.assertIsNone(c["stock_contract"])
        self.assertEqual(c["stock_scope_hold"]["contract"], before["stock_contract"])
        self.assertEqual(c["tasks"]["etf"], before["tasks"]["etf"])
        self.assertEqual(c["contract"], before["contract"])
        self.assertEqual(result["blocked_tasks"], ["stock"])
        self.assertEqual(c["tasks"]["done"]["reports"][0]["text"], "original")
        self.assertEqual(result["withheld_proposals"], 1)
        self.assertEqual(c["tasks"]["done"]["reports"][0]["followups"], [])

    def test_idempotent_and_conflicting_incident_rejected(self):
        c = self.state()
        module.hold(
            c,
            "incident-20260927",
            "Confirmed frozen loader boundary violation requires audit.",
        )
        before = copy.deepcopy(c)
        self.assertTrue(
            module.hold(
                c,
                "incident-20260927",
                "Confirmed frozen loader boundary violation requires audit.",
            )["already_held"]
        )
        self.assertEqual(c, before)
        with self.assertRaisesRegex(ValueError, "another_stock_scope"):
            module.hold(
                c,
                "another-incident",
                "Confirmed frozen loader boundary violation requires audit.",
            )

    def test_running_model_call_is_not_revoked(self):
        c = self.state()
        c["tasks"]["stock"]["status"] = "running"
        before = copy.deepcopy(c)
        with self.assertRaisesRegex(ValueError, "wait_for_stock_model"):
            module.hold(
                c,
                "incident-20260927",
                "Confirmed frozen loader boundary violation requires audit.",
            )
        self.assertEqual(c, before)

    def test_replay_cannot_disable_restored_scope_or_change_incident(self):
        c = self.state()
        reason = "Confirmed frozen loader boundary violation requires audit."
        module.hold(c, "incident-20260927", reason)
        with self.assertRaisesRegex(ValueError, "incident_reason_conflict"):
            module.hold(c, "incident-20260927", reason + " Changed.")
        c["stock_contract"] = {"manifest": "later accepted input"}
        before = copy.deepcopy(c)
        with self.assertRaisesRegex(ValueError, "stock_scope_was_restored"):
            module.hold(c, "incident-20260927", reason)
        self.assertEqual(c, before)


class StockScopeTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = StockScopeHoldTests().state()
        self.events = []
        self.busy = set()
        self.rows = {}
        self.owner = SimpleNamespace(user_id="owner", tenant_id="tenant")
        self.request = {
            "token": "test-only",
            "program_id": "this-program",
            "incident_id": "incident-20260927",
            "reason": "Confirmed frozen loader boundary violation requires audit.",
        }
        outer = self

        class Lock:
            def __init__(self, key):
                self.key = key

            def acquire(self, blocking):
                outer.assertFalse(blocking)
                if self.key in outer.busy:
                    outer.events.append("busy:" + self.key)
                    return False
                outer.busy.add(self.key)
                outer.events.append("acquire:" + self.key)
                return True

            def release(self):
                outer.assertIn(self.key, outer.busy)
                outer.busy.remove(self.key)
                outer.events.append("release:" + self.key)

        def lock(key, timeout, blocking_timeout):
            self.assertEqual(timeout, 7500)
            self.assertEqual(blocking_timeout, 0)
            return Lock(key)

        self.client = SimpleNamespace(lock=lock)

        class DB:
            async def execute(self, sql, params):
                statement = str(sql)
                if "SELECT" in statement:
                    outer.assertEqual(
                        params, {"u": "owner", "t": "tenant", "p": "this-program"}
                    )
                    outer.assertIn("FOR UPDATE", statement)
                    outer.assertIn("frozen_stock_research", statement)
                    return SimpleNamespace(
                        all=lambda: [
                            (bid, r["status"], copy.deepcopy(r))
                            for bid, r in outer.rows.items()
                            if r["status"] in ("pending", "running")
                        ]
                    )
                bid = params["bid"]
                key = "quantmind:continuous-stock:" + bid
                outer.assertIn(key, outer.busy)
                # A competing worker cannot acquire the same lock before
                # reading pending, including between UPDATE and COMMIT.
                outer.assertFalse(Lock(key).acquire(blocking=False))
                outer.assertEqual(outer.rows[bid]["status"], "pending")
                outer.rows[bid] = json.loads(params["result"])
                outer.events.append("write:" + bid)

        @asynccontextmanager
        async def edit(program, auth):
            self.assertEqual(program, "this-program")
            self.assertIs(auth, self.owner)
            try:
                yield self.c, DB()
            except Exception:
                self.events.append("rollback")
                raise
            else:
                self.events.append("commit")

        self.modules = {
            "redis": SimpleNamespace(from_url=lambda _: self.client),
            "backend.services.trade_shared.deps": SimpleNamespace(
                get_auth_context=AsyncMock(return_value=self.owner)
            ),
            "backend.services.engine.routers.continuous_research": SimpleNamespace(
                edit=edit
            ),
            "backend.services.engine.tasks.continuous_stock_tasks": SimpleNamespace(
                invalidate_result=lambda bid, u, t: self.events.append(
                    "invalidate:" + bid
                )
            ),
        }

    async def apply(self):
        with (
            patch.dict(sys.modules, self.modules),
            patch.dict("os.environ", {"REDIS_URL": "test-only"}),
        ):
            return await module.apply_request(self.request)

    async def test_worker_already_read_pending_is_not_closed(self):
        self.rows = {
            "race": {"status": "pending", "original": "preserved"},
            "running": {"status": "running"},
        }
        self.busy.add("quantmind:continuous-stock:race")
        result = await self.apply()
        self.assertIsNone(self.c["stock_contract"])
        self.assertEqual(result["pending_runs_closed"], [])
        self.assertEqual(result["requires_runtime_stop"], ["race", "running"])
        self.assertEqual(
            self.rows["race"], {"status": "pending", "original": "preserved"}
        )
        self.assertIn("quantmind:continuous-stock:race", self.busy)
        self.assertFalse(any(x.startswith("write:") for x in self.events))

    async def test_lock_covers_commit_and_retry_preserves_later_results(self):
        self.rows = {
            "pending": {"status": "pending", "original": "preserved"},
            "complete": {"status": "completed", "original": "untouched"},
        }
        result = await self.apply()
        self.assertEqual(result["closed_now"], ["pending"])
        self.assertEqual(result["requires_runtime_stop"], [])
        self.assertLess(self.events.index("write:pending"), self.events.index("commit"))
        self.assertLess(
            self.events.index("commit"),
            self.events.index("release:quantmind:continuous-stock:pending"),
        )
        self.assertEqual(self.rows["pending"]["original"], "preserved")
        self.assertEqual(
            self.rows["complete"], {"status": "completed", "original": "untouched"}
        )
        self.assertFalse(self.busy)
        before = copy.deepcopy(self.rows)
        again = await self.apply()
        self.assertTrue(again["already_held"])
        self.assertEqual(again["closed_now"], [])
        self.assertEqual(again["pending_runs_closed"], ["pending"])
        self.assertEqual(self.rows, before)
        self.assertEqual(self.events.count("write:pending"), 1)
        self.assertEqual(self.events.count("invalidate:pending"), 2)

    async def test_retry_closes_only_after_existing_worker_releases(self):
        self.rows = {"pending": {"status": "pending"}}
        key = "quantmind:continuous-stock:pending"
        self.busy.add(key)
        first = await self.apply()
        self.assertEqual(first["requires_runtime_stop"], ["pending"])
        self.busy.remove(key)  # Simulate the existing worker's own finalizer.
        second = await self.apply()
        self.assertTrue(second["already_held"])
        self.assertEqual(second["closed_now"], ["pending"])
        self.assertEqual(self.rows["pending"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
