"""Integration checks against an explicitly disposable research_test PostgreSQL DB.

Apply scripts/research_workbench_v1.sql first and set DATABASE_URL.
This never uses the application database or model credentials.
"""
import asyncio
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

assert os.environ.get("DATABASE_URL", "").endswith("/research_test"), "Disposable DB required"

from sqlalchemy import text
from backend.shared.database_manager_v2 import get_session
from backend.services.engine.research import coordinator, runtime
from backend.services.engine.research.store import Store


async def main():
    store = Store()
    node = uuid4().hex
    owner = ("test-tenant", "test-user")
    payload = {"kind": "strategy", "goal": "persistence acceptance", "hours": .1}
    contract = {"node_id": node, "candidate_limit": 2}
    ids = await asyncio.gather(*(store.create(owner, node, "same-submit", payload, contract) for _ in range(5)))
    assert len(set(ids)) == 1, "Concurrent submissions created duplicate work"
    run = ids[0]
    assert not await store.get(("other-tenant", owner[1]), node, run)
    assert not await store.get((owner[0], "other-user"), node, run)
    assert not await store.get(owner, "other-node", run)
    try:
        await store.create(owner, node, "same-submit", {**payload, "hours": 1}, contract)
        raise AssertionError("Conflicting idempotency request accepted")
    except ValueError:
        pass
    claims = await asyncio.gather(store.claim(node, "worker-a"), store.claim(node, "worker-b"))
    assert sum(row is not None for row in claims) == 1
    row = next(row for row in claims if row)
    lease = row["lease_owner"]
    state = row["checkpoint"]
    state["candidate_count"] = 1
    assert await store.control(owner, node, run, "pause")
    assert await store.checkpoint(run, lease, state) == "pause_requested"
    row = await store.claim(node, "worker-after-restart")
    assert row["checkpoint"]["candidate_count"] == 1
    with tempfile.TemporaryDirectory(prefix="qm-research-check-") as tmp, patch.object(runtime, "ROOT", Path(tmp)):
        await coordinator.advance(row, store, "worker-after-restart")
        paused = (await store.get(owner, node, run))[0]
        assert paused["status"] == "paused"
        resumes = await asyncio.gather(*(store.create(owner, node, "continue-once", {"hours": .1, "parent": run}, contract, parent=run) for _ in range(3)))
        assert len(set(resumes)) == 1 and resumes[0] != run
        resumed = (await store.get(owner, node, resumes[0]))[0]
        assert resumed["case_id"] == row["case_id"] and resumed["checkpoint"]["candidate_count"] == 1
        assert resumed["contract"] == contract and resumed["deadline_epoch"] > paused["deadline_epoch"]
        try:
            await store.create(owner, node, "continue-again", {"hours": .1}, contract, parent=run)
            raise AssertionError("Old window resumed twice")
        except ValueError:
            pass
        # Simulate a worker crash by leaving its lease, then expiring it in the test DB.
        claimed = await store.claim(node, "dead-worker")
        assert claimed and not await store.claim(node, "another-worker")
        async with get_session() as db:
            await db.execute(text("UPDATE research_windows SET lease_until=0 WHERE run_id=:id"), {"id": resumed["run_id"]})
        recovered = await store.claim(node, "recovered-worker")
        assert recovered["run_id"] == resumed["run_id"]
        directory = runtime.case_directory(row["case_id"]) / "experiments/E00"
        directory.mkdir(parents=True)
        name = "qm-research-test-" + node[:12]
        exp = {"id": "E00", "container_name": name, "status": "running"}
        subprocess.run(["docker", "run", "--detach", "--name", name, "--network=none",
            "--label", f"quantmind.research.node={node}", "--label", "quantmind.research.id=E00",
            "--mount", f"type=bind,src={directory},dst=/output", "python:3.11-slim",
            "python", "-c", "import time; time.sleep(300)"], check=True, capture_output=True)
        try:
            state = recovered["checkpoint"]
            exp["container_id"] = runtime.inspect(name)["Id"]
            state["active"] = exp
            await store.checkpoint(resumed["run_id"], "recovered-worker", state)
            assert await store.control(owner, node, resumed["run_id"], "cancel")
            assert not await store.control(owner, node, resumed["run_id"], "pause")
            row = await store.claim(node, "cancelling-worker")
            with patch.object(runtime, "host_path", side_effect=lambda path, **kw: path):
                await coordinator.advance(row, store, "cancelling-worker")
            assert not runtime.inspect(name)["State"]["Running"], "Cancel failed to stop actual compute"
            cancelled = (await store.get(owner, node, resumed["run_id"]))[0]
            assert cancelled["status"] == "cancelled"
            assert cancelled["checkpoint"]["active"]["status"] == "cancelled"
        finally:
            subprocess.run(["docker", "rm", "--force", name], check=True, capture_output=True)
    print("PASS: concurrent idempotency, ownership, exclusive lease, pause, resume, crash recovery, real Docker cancellation")


if __name__ == "__main__":
    asyncio.run(main())
