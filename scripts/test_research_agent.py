"""Run with the separately locked research-agent environment, never production DB."""

import asyncio
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from backend.services.research_agent.runtime import Policy, Runner
from backend.services.research_agent.sandbox import read_file
from backend.services.research_agent.store import enqueue, stop


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_discussion_cannot_execute_even_with_prior_approval(self):
        state = {
            "generation": 1,
            "status": "running",
            "approval": {"deadline": 10**12},
            "jobs": {},
        }

        class Store:
            async def get(self, ident):
                return {"state": state}

        policy = Policy(SimpleNamespace(store=Store()), "case", 1, False)
        called = []

        async def handler(request):
            called.append(True)

        result = await policy.awrap_tool_call(
            SimpleNamespace(
                tool_call={
                    "id": "call",
                    "name": "execute",
                    "args": {"command": "python job.py"},
                }
            ),
            handler,
        )
        self.assertEqual(result.status, "error")
        self.assertFalse(called)
        policy.generation = 0
        with self.assertRaises(asyncio.CancelledError):
            await policy.awrap_tool_call(
                SimpleNamespace(tool_call={"id": "call", "name": "read_file"}), handler
            )

    async def test_expired_approval_cannot_register_factor(self):
        class Store:
            async def get(self, ident):
                return {
                    "state": {
                        "generation": 0,
                        "status": "running",
                        "approval": {"deadline": 1},
                    }
                }

        policy = Policy(SimpleNamespace(store=Store()), "case", 0, True)

        async def handler(_):
            self.fail("Expired approval reached platform writer")

        result = await policy.awrap_tool_call(
            SimpleNamespace(tool_call={"id": "x", "name": "register_factor"}), handler
        )
        self.assertEqual(result.status, "error")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_case_does_not_block_another_case(self):
        reached = asyncio.Event()
        hold = asyncio.Event()

        class Store:
            async def active(self, node):
                return [{"draft_id": "slow"}, {"draft_id": "interactive"}]

        runner = Runner(SimpleNamespace(node="isolated"), Store())
        completed = asyncio.create_task(asyncio.sleep(0))
        await completed
        runner.tasks = {str(i): completed for i in range(4)}

        async def tick(row):
            self.assertEqual(len(runner.tasks), 0)
            if row["draft_id"] == "slow":
                await hold.wait()
            else:
                reached.set()

        runner.tick = tick
        task = asyncio.create_task(runner.supervise())
        try:
            await asyncio.wait_for(reached.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(all(t.done() for t in runner.ticks.values()))

    async def test_completion_notification_can_correct_earlier_uncertain_status(self):
        s = {
            "sequence": 0,
            "events": [],
            "requests": {},
            "messages": [],
            "inbox": [],
            "status": "waiting_job",
            "approval": {"deadline": 10**12},
            "outcomes": [],
            "jobs": {
                "job": {
                    "id": "job",
                    "name": "container",
                    "kind": "code",
                    "status": "running",
                }
            },
        }
        enqueue(s, "job:job", "prior uncertain launch result", "job")

        class Store:
            @asynccontextmanager
            async def edit(self, ident):
                yield s

        runner = Runner(SimpleNamespace(), Store())
        sandbox = SimpleNamespace(
            observe=lambda _: {"status": "completed", "exit_code": 0}
        )
        with patch(
            "backend.services.research_agent.runtime.Sandbox", return_value=sandbox
        ):
            await runner.poll_jobs("case", s)
            await runner.poll_jobs("case", s)
        self.assertEqual(s["jobs"]["job"]["status"], "completed")
        self.assertEqual(len(s["messages"]), 2)
        self.assertIn("job:job:completed", s["requests"])

    async def test_background_job_allows_status_query_but_blocks_file_edit(self):
        state = {
            "generation": 0,
            "status": "running",
            "jobs": {"j": {"status": "running"}},
        }

        class Store:
            async def get(self, ident):
                return {"state": state}

            async def add_event(self, *args, **kwargs):
                pass

        policy = Policy(SimpleNamespace(store=Store()), "case", 0, False)
        called = []

        async def handler(request):
            called.append(request.tool_call["name"])
            return SimpleNamespace(content="running", status="success")

        for name in ("inspect_research", "read_file", "edit_file"):
            await policy.awrap_tool_call(
                SimpleNamespace(tool_call={"id": name, "name": name}), handler
            )
        self.assertEqual(called, ["inspect_research", "read_file"])


class BoundaryTests(unittest.TestCase):
    def test_file_cannot_follow_symlinks_or_fifo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "valid.txt").write_text("evidence")
            self.assertEqual(read_file(root, "valid.txt"), b"evidence")
            (root / "link").symlink_to("/etc/passwd")
            (root / "outside").symlink_to("/etc", target_is_directory=True)
            os.mkfifo(root / "fifo")
            for name in ("link", "outside/passwd", "../passwd", "/etc/passwd", "fifo"):
                with self.subTest(path=name), self.assertRaises((ValueError, OSError)):
                    read_file(root, name)

    def test_message_retry_is_idempotent_and_stop_revokes_execution(self):
        state = {
            "sequence": 0,
            "events": [],
            "requests": {},
            "messages": [],
            "inbox": [],
            "status": "idle",
            "approval": {"version": 1},
            "generation": 0,
        }
        enqueue(state, "same-key", "问题")
        enqueue(state, "same-key", "问题")
        self.assertEqual(len(state["messages"]), 1)
        with self.assertRaises(ValueError):
            enqueue(state, "same-key", "改变问题")
        stop(state)
        self.assertIsNone(state["approval"])
        self.assertEqual(state["inbox"], [])
        self.assertEqual(state["messages"][0]["status"], "interrupted")
        self.assertEqual(state["generation"], 1)


if __name__ == "__main__":
    unittest.main()
