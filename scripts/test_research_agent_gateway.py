"""Run inside an isolated main-backend environment; no DB or provider calls."""

import unittest
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


if __name__ == "__main__":
    unittest.main()
