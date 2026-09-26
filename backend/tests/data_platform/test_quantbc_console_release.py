"""The admin data browser reads one published BC release with crypto disabled."""

from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.data_platform.test_crypto_research_release import _publish


@pytest.fixture
def console_client(tmp_path, monkeypatch):
    # Execute the real router, replacing only DB-backed authentication in this test.
    source = (
        Path(__file__).parents[2]
        / "services/api/routers/admin/global_market_console.py"
    )
    tree = ast.parse(source.read_text())
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.ImportFrom)
            and node.module == "backend.services.api.user_app.middleware.auth"
        )
    ]
    module = types.ModuleType("quantbc_console_under_test")
    module.require_admin = lambda: {"username": "test-admin"}
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(tree, str(source), "exec"), module.__dict__)
    root = tmp_path / "quantbc"
    monkeypatch.setenv("ENABLE_CRYPTO", "false")
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(root))
    app = FastAPI()
    app.include_router(
        module.make_market_router(
            market="BC",
            env_var="QM_QUANTBC_DATA_DIR",
            default_dir="/data/quantbc",
            sync_entry="backend.scripts.quantbc_daily_sync",
        ),
        prefix="/quantbc",
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield module, client, root


def test_catalog_and_preview_read_release_without_enabling_crypto(console_client):
    _, client, root = console_client
    release = _publish(root, "first")
    catalog = client.get("/quantbc/catalog").json()["data"]
    assert catalog["data_dir"] == str(release)
    assert catalog["release_id"] == "first"
    assert catalog["timezone"] == "UTC" and catalog["data_end"] == "2024-01-07"
    assert catalog["point_in_time_verified"] is False
    daily = next(
        item for item in catalog["datasets"] if item["dataset"] == "daily_forward"
    )
    assert daily["synced"] and daily["files"] == 2
    assert daily["start_date"] == "20240106" and daily["end_date"] == "20240107"
    assert "UTC" in daily["note"] and "first" in daily["note"]
    preview = client.get(
        "/quantbc/preview",
        params={
            "dataset": "daily_forward",
            "symbol": "btcusdt",
            "limit": 50,
        },
    ).json()["data"]
    assert preview["release_id"] == "first" and preview["rows_total"] == 1
    assert preview["file"] == "1_kline_data/daily_forward/dt=20240107/data.parquet"
    row = preview["data"][0]
    assert row["symbol"] == "BTCUSDT" and row["amount"] == row["quote_volume"] == 1047
    assert row["available_at"] == "2024-01-08T00:00:00+00:00"
    assert client.get("/quantbc/config").json()["data"]["data_dir"] == str(root)


@pytest.mark.parametrize("endpoint", ["catalog", "preview"])
def test_request_stays_on_one_release_during_pointer_change(
    console_client, monkeypatch, endpoint
):
    module, client, root = console_client
    first = _publish(root, "first")
    if endpoint == "catalog":
        original = module._build_catalog_payload

        def advance_pointer(market, specs, groups, pinned):
            assert pinned == first
            _publish(root, "second", offset=50)
            return original(market, specs, groups, pinned)

        monkeypatch.setattr(module, "_build_catalog_payload", advance_pointer)
        payload = client.get("/quantbc/catalog").json()["data"]
    else:
        original = module.pd.read_parquet

        def advance_pointer(path, *args, **kwargs):
            assert Path(path).is_relative_to(first)
            _publish(root, "second", offset=50)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(module.pd, "read_parquet", advance_pointer)
        payload = client.get("/quantbc/preview?dataset=daily_forward").json()["data"]
        assert {row["close"] for row in payload["data"]} == {105.0}
    assert payload["release_id"] == "first" and payload["data_dir"] == str(first)
    assert json.loads((root / "CURRENT.json").read_text())["release_id"] == "second"


def test_broken_pointer_fails_closed_instead_of_reading_root(console_client):
    _, client, root = console_client
    _publish(root, "first")
    pointer = json.loads((root / "CURRENT.json").read_text())
    pointer["manifest_sha256"] = "0" * 64
    (root / "CURRENT.json").write_text(json.dumps(pointer))
    assert client.get("/quantbc/catalog").status_code == 500
    assert client.get("/quantbc/preview?dataset=daily_forward").status_code == 500
