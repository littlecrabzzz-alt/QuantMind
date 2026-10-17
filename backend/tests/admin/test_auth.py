"""Exercise retired routes and authentication through the real admin HTTP router."""

import pytest
from fastapi.testclient import TestClient


class TestAdminHttpBoundary:
    """Exercise the real router without service startup or database access."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI

        from backend.services.api.routers.admin import admin_router

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/api/v1/admin/system/update?confirm=1"),
            ("GET", "/api/v1/admin/system/update/status"),
        ],
    )
    def test_retired_update_endpoints_return_not_found(self, client, method, path):
        response = client.request(method, path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/admin/dashboard/metrics",
            "/api/v1/admin/dashboard/node-history",
            "/api/v1/admin/finbert/status",
        ],
    )
    def test_other_admin_endpoints_still_require_authentication(self, client, path):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
