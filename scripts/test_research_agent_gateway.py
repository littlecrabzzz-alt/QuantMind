"""Run inside an isolated main-backend environment; no DB or provider calls."""

import unittest
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from backend.services.api.routers.engine_proxy import research_agent_proxy


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_identity_never_reaches_internal_gateway(self):
        request = SimpleNamespace(
            method="POST", headers={"x-internal-call": "spoof", "x-user-id": "1"}
        )
        with patch(
            "backend.services.api.routers.engine_proxy._proxy", new_callable=AsyncMock
        ) as forward:
            with self.assertRaises(HTTPException) as error:
                await research_agent_proxy(request, None)
            self.assertEqual(error.exception.status_code, 401)
            forward.assert_not_called()

    async def test_authenticated_identity_uses_existing_gateway(self):
        request = SimpleNamespace(method="GET")
        user = {"user_id": "1", "tenant_id": "test"}
        with patch(
            "backend.services.api.routers.engine_proxy._proxy", new_callable=AsyncMock
        ) as forward:
            await research_agent_proxy(request, user)
            forward.assert_awaited_once_with(request, user)

    async def test_strategy_uses_business_user_mapping(self):
        from backend.services.engine.routers.research_agent import strategy

        body = {
            "name": "candidate",
            "content": "pass",
            "sha256": hashlib.sha256(b"pass").hexdigest(),
            "path": "/workspace/strategy.py",
        }
        request = SimpleNamespace(json=AsyncMock(return_value=body))
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar=lambda: 42))
        )

        @asynccontextmanager
        async def session():
            yield db

        state = {"approval": {"allowed_tools": ["register_strategy"], "version": 1}}
        cfg = {"node_id": "isolated", "snapshot_id": "frozen"}
        with (
            patch(
                "backend.services.engine.routers.research_agent.owned_case",
                AsyncMock(return_value=(state, cfg, "business-user", "tenant")),
            ),
            patch(
                "backend.services.engine.routers.research_agent.get_session", session
            ),
            patch(
                "backend.shared.strategy_storage._ensure_int_user_id", return_value=12
            ) as mapping,
        ):
            result = await strategy("case", request)
        mapping.assert_called_once_with("business-user")
        self.assertEqual(result["id"], "42")
        self.assertEqual(db.execute.call_args_list[-1].args[1]["user"], 12)


if __name__ == "__main__":
    unittest.main()
