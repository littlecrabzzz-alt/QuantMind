import ast
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from backend.services.research_agent import continuous_state as st
from scripts.continuous_research import controller
from scripts.continuous_research.set_capacity import set_capacity


def state():
    c = st.initial(
        {
            "concurrency": 3,
            "validation": "development_only",
            "paper_authorized": False,
            "input_manifest_sha256": "unchanged-input",
            "execution": {"initial_cash": 30000},
        }
    )
    c["runtime"] = {"provider": "glm", "model": "glm-5.3", "thinking": "max"}
    st.control(c, "start")
    c["quota"] = {
        "status": "known",
        "remaining_percent": 99,
        "observed_at": 1000,
    }
    for i in range(10):
        st.add_task(c, "trend", f"independent question {i}", "existing evidence")
    return c


def change(c, target, expected, request_id="capacity-request-1"):
    return set_capacity(
        c,
        request_id=request_id,
        expected_concurrency=expected,
        concurrency=target,
        reason="Observed spare quota and independent evidence-backed work",
        operator={"user_id": "owner", "tenant_id": "tenant"},
    )


class CapacityTests(unittest.TestCase):
    def test_six_slots_cannot_overclaim_and_quota_still_gates(self):
        c = state()
        change(c, 6, 3)
        tasks = [st.claim(c, "worker", 1000) for _ in range(6)]
        self.assertEqual(len({t["lease"] for t in tasks}), 6)
        self.assertIsNone(st.claim(c, "worker", 1000))
        for quota in (
            {"status": "unknown", "observed_at": 1000},
            {"status": "known", "remaining_percent": 1, "observed_at": 1000},
        ):
            c = state()
            change(c, 6, 3)
            c["quota"] = quota
            self.assertIsNone(st.claim(c, "worker", 1000))

    def test_drain_preserves_leases_contract_and_settlement(self):
        c = state()
        task = st.claim(c, "worker", 1000)
        before = copy.deepcopy(c)
        change(c, 0, 3)
        self.assertIsNone(st.claim(c, "worker", 1001))
        self.assertEqual(c["tasks"], before["tasks"])
        self.assertEqual(c["generation"], before["generation"])
        self.assertEqual(c["desired"], "running")
        expected = before["contract"] | {"concurrency": 0}
        self.assertEqual(c["contract"], expected)
        st.fence(c, task["id"], task["lease"], 1001)
        task["reports"].append({"text": "existing model result"})
        self.assertEqual(
            st.settle(c, task["id"], task["lease"], "done", now=1002), "done"
        )
        change(c, 6, 0, "capacity-request-2")
        self.assertIsNotNone(st.claim(c, "worker", 1003))

    def test_request_replay_cannot_undo_later_capacity_change(self):
        c = state()
        change(c, 0, 3)
        change(c, 6, 0, "capacity-request-2")
        before = copy.deepcopy(c)
        self.assertTrue(change(c, 0, 3)["already_applied"])
        self.assertEqual(c, before)
        with self.assertRaisesRegex(ValueError, "request_id_conflict"):
            change(c, 1, 3)
        self.assertEqual(c, before)

    def test_invalid_capacity_or_stale_observation_cannot_mutate(self):
        for target, expected in ((-1, 3), (7, 3), (True, 3), (1.5, 3), (6, 2)):
            c = state()
            before = copy.deepcopy(c)
            with self.subTest(target=target, expected=expected):
                with self.assertRaises(ValueError):
                    change(c, target, expected)
                self.assertEqual(c, before)

    def test_other_runtime_or_paper_program_cannot_mutate(self):
        for field in ("model", "thinking", "paper"):
            c = state()
            if field == "paper":
                c["contract"]["paper_authorized"] = True
            else:
                c["runtime"][field] = "other"
            before = copy.deepcopy(c)
            with self.assertRaisesRegex(ValueError, "glm_max_development"):
                change(c, 6, 3)
            self.assertEqual(c, before)

    def test_controller_pool_obeys_server_limit_and_local_cap(self):
        for limit, expected in ((0, 0), (3, 3), (6, 6), (9, 6)):
            c = state()
            active = st.claim(c, "worker", 1000) if limit == 0 else None
            c["contract"]["concurrency"] = limit
            worker = controller.Controller.__new__(controller.Controller)
            worker.stop = threading.Event()
            worker.stop.wait = lambda _, event=worker.stop: event.set()
            worker.credential = lambda: "test-only"
            worker.kill_children = MagicMock()
            worker.work = MagicMock()
            worker.api = MagicMock()
            worker.api.call.side_effect = lambda op, current=c, **kw: (
                copy.deepcopy(current)
                if op == "pulse"
                else {"task": st.claim(current, "worker", 1000)}
            )
            with (
                patch.object(controller, "fetch_quota", return_value=c["quota"]),
                patch.object(controller, "ThreadPoolExecutor") as executor,
            ):
                worker.run()
                executor.assert_called_once_with(max_workers=6)
                pool = executor.return_value.__enter__.return_value
                self.assertEqual(pool.submit.call_count, expected)
                self.assertEqual(worker.api.call.call_count, expected + 1)
                if active:
                    # During drain the regular pulse keeps the running child's
                    # identity allowed; only the later process shutdown kills.
                    self.assertEqual(
                        worker.kill_children.call_args_list[0].args,
                        ({active["id"]},),
                    )


class ExistingStoreScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_edit_rejects_wrong_owner_tenant_node_and_locks(self):
        # Exercise the actual existing store function without importing Qlib or
        # connecting to a database; the helper delegates all scoping to edit.
        path = Path("backend/services/engine/routers/continuous_research.py")
        node = next(
            n for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "edit"
        )
        c = state()
        executions = []
        row_identity = {"tenant": "tenant", "user": "owner", "node": "wrong-node"}

        class DB:
            async def execute(self, sql, params):
                executions.append((str(sql), params))
                if str(sql).startswith("SELECT"):
                    match = all(params[k] == v for k, v in row_identity.items())
                    return SimpleNamespace(
                        first=lambda: ({"continuous": c},) if match else None
                    )

        @asynccontextmanager
        async def session():
            yield DB()

        ns = {
            "asynccontextmanager": asynccontextmanager,
            "get_session": session,
            "text": lambda sql: sql,
            "NODE": "mac-glm-continuous-v1",
            "HTTPException": HTTPException,
            "json": json,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
        for key, bad_value in (("node", "wrong-node"), ("user", "other"), ("tenant", "other")):
            row_identity.update(tenant="tenant", user="owner", node=ns["NODE"])
            row_identity[key] = bad_value
            with self.assertRaises(HTTPException) as exc:
                async with ns["edit"](
                    "program", SimpleNamespace(tenant_id="tenant", user_id="owner")
                ):
                    self.fail("wrong identity entered write scope")
            self.assertEqual(exc.exception.status_code, 404)
        self.assertTrue(all("FOR UPDATE" in sql for sql, _ in executions))
        self.assertEqual(len(executions), 3)


if __name__ == "__main__":
    unittest.main()
