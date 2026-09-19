"""Cancellation keeps orchestration alive until resources have been stopped."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_cancel_request_preserves_resource_cleanup_task(monkeypatch):
    from backend.services.api.routers.admin import admin_training_utils as api
    record = SimpleNamespace(status="running", logs="", progress=12)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: record)), commit=AsyncMock())
    @asynccontextmanager
    async def db():
        yield session
    stream, registry = Mock(), Mock()
    monkeypatch.setattr(api, "get_session", db)
    monkeypatch.setattr(api, "_training_log_stream", stream)
    monkeypatch.setattr(api, "REGISTRY", registry)
    result = await api.cancel_training_run("run1", {"tenant_id": "tenant1", "user_id": "user1"})
    assert result["status"] == "cancelled"
    params = session.execute.call_args.args[0].compile().params
    assert {"run1", "tenant1", "user1"} <= set(params.values())
    stream.mark_cancel_requested.assert_called_once_with("run1")
    registry.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_container_stops_and_removes_using_keyword_options(monkeypatch):
    from backend.services.engine.training.local_docker_orchestrator import LocalDockerOrchestrator
    from backend.shared import database_manager_v2
    calls = []
    class Container:
        attrs = {"State": {"Status": "running"}}
        def reload(self):
            pass
        def stop(self, *, timeout):
            calls.append(("stop", timeout))
        def remove(self, *, force, v):
            calls.append(("remove", force, v))
    record = SimpleNamespace(status="running", logs="", progress=10)
    session = SimpleNamespace(get=AsyncMock(return_value=record), commit=AsyncMock())
    @asynccontextmanager
    async def db():
        yield session
    monkeypatch.setattr(database_manager_v2, "get_session", db)
    fake = SimpleNamespace(docker=SimpleNamespace(containers=SimpleNamespace(get=lambda _: Container())), log_stream=Mock())
    await LocalDockerOrchestrator._cancel_container(fake, "run1", "container1", "tenant1", "user1")
    assert calls == [("stop", 20), ("remove", True, True)]
    assert record.status == "cancelled"
    fake.log_stream.clear_cancel.assert_called_once_with("run1")


@pytest.mark.asyncio
async def test_failed_cleanup_keeps_cancellation_pending():
    from backend.services.engine.training.local_docker_orchestrator import LocalDockerOrchestrator
    fake = SimpleNamespace(docker=SimpleNamespace(containers=SimpleNamespace(
        get=Mock(side_effect=RuntimeError("temporary Docker failure")))), log_stream=Mock())
    assert await LocalDockerOrchestrator._cancel_container(fake, "run1", "container1", "tenant1", "user1") is False
    fake.log_stream.clear_cancel.assert_not_called()
    fake.log_stream.append_log.assert_not_called()
