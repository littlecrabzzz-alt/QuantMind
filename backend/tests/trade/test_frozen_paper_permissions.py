"""Frozen observation files never bypass native strategy owner/version permissions."""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from backend.services.simulation.services import frozen_paper_service as service


def test_scope_paths_separate_user_and_tenant(tmp_path):
    first = service.scoped_ledger_root("owner", "tenant-a", tmp_path)
    assert first != service.scoped_ledger_root("other", "tenant-a", tmp_path)
    assert first != service.scoped_ledger_root("owner", "tenant-b", tmp_path)


def test_native_owner_tenant_and_registered_code_are_required(monkeypatch):
    from backend.shared import strategy_storage
    code = "frozen executable source"
    bindings = {"user_id": "owner", "tenant_id": "tenant-a", "accounts": {"lowvol": {
        "strategy_id": "42", "frozen_source_id": "frozen-source", "runtime_code_sha256": "runtime",
        "strategy_code_sha256": hashlib.sha256(code.encode()).hexdigest()}}}
    row = {"code": code, "parameters": {
        "account_id": "lowvol", "frozen_source_id": "frozen-source", "tenant_id": "tenant-a",
        "runtime_code_sha256": "runtime", "frozen": True, "observation_only": True,
        "trading_permission": False}}
    class Storage:
        async def get(self, strategy_id, user_id, resolve_code):
            assert strategy_id == "42" and user_id == "owner" and resolve_code
            return row
    monkeypatch.setattr(strategy_storage, "get_strategy_storage_service", lambda: Storage())
    monkeypatch.setattr(service, "paper_runtime", lambda: SimpleNamespace(
        ACCOUNTS=("lowvol",), _source_hash=lambda: "runtime"))
    assert asyncio.run(service.validate_bindings(bindings, "owner", "tenant-a")) == bindings
    with pytest.raises(PermissionError, match="scope"):
        asyncio.run(service.validate_bindings(bindings, "other", "tenant-a"))
    with pytest.raises(PermissionError, match="scope"):
        asyncio.run(service.validate_bindings(bindings, "owner", "tenant-b"))
    row["code"] = "mutated same strategy ID"
    with pytest.raises(PermissionError, match="code version"):
        asyncio.run(service.validate_bindings(bindings, "owner", "tenant-a"))
    row["code"] = code
    row["parameters"]["trading_permission"] = True
    with pytest.raises(PermissionError, match="identity/tenant"):
        asyncio.run(service.validate_bindings(bindings, "owner", "tenant-a"))


def test_snapshot_writer_busy_is_nonblocking_and_never_reads_financials(tmp_path):
    import fcntl

    calls = []
    runtime = SimpleNamespace(snapshot=lambda root: calls.append(root))
    path = tmp_path / ".paper.lock"
    path.touch()
    with path.open("rb") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        with pytest.raises(service.LedgerUpdating):
            service._snapshot_if_available(runtime, tmp_path)
    assert calls == []


def test_snapshot_retains_shared_lock_during_seal_validation(tmp_path):
    import fcntl

    path = tmp_path / ".paper.lock"
    path.touch()

    def snapshot(root):
        with path.open("rb") as writer:
            with pytest.raises(BlockingIOError):
                fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)

    service._snapshot_if_available(SimpleNamespace(snapshot=snapshot), tmp_path)


def test_snapshot_wait_keeps_event_loop_available_to_other_consumers(tmp_path, monkeypatch):
    import json
    import threading

    root = service.scoped_ledger_root("owner", "tenant-a", tmp_path)
    root.mkdir()
    (root / "bindings.json").write_text(json.dumps({"owner": "binding"}))
    (root / ".paper.lock").touch()
    runtime = service.paper_runtime()
    real_snapshot = runtime.snapshot
    entered = threading.Event()
    released = threading.Event()

    async def authorized_scope(bindings, user_id, tenant_id):
        pass

    def blocked_snapshot(directory):
        entered.set()
        if not released.wait(timeout=5):
            raise TimeoutError("A waiting snapshot prevented cooperative event-loop progress")
        return real_snapshot(directory)

    monkeypatch.setattr(service, "ledger_root", lambda: tmp_path)
    monkeypatch.setattr(service, "validate_bindings", authorized_scope)
    monkeypatch.setattr(runtime, "snapshot", blocked_snapshot)

    async def consume():
        reader = asyncio.create_task(service.get_accounts("owner", "tenant-a"))

        async def cooperate():
            assert await asyncio.to_thread(entered.wait, 5), "Snapshot never reached the gate"
            assert not reader.done(), "Snapshot did not wait for the cooperative consumer"
            released.set()

        collaborator = asyncio.create_task(cooperate())
        try:
            result, _ = await asyncio.wait_for(asyncio.gather(reader, collaborator), timeout=10)
            return result
        finally:
            released.set()
            for task in (reader, collaborator):
                if not task.done():
                    task.cancel()
            await asyncio.gather(reader, collaborator, return_exceptions=True)

    view = asyncio.run(consume())
    assert view["accounts"]
    assert all(account["state"] == "not_initialized" for account in view["accounts"])
    assert all("nav" not in account and "positions" not in account for account in view["accounts"])
