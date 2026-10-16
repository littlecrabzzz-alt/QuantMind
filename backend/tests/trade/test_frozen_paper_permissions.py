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
