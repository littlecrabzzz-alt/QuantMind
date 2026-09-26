"""Published spot bars stay bound across Hub, Qlib, H5 and RD inputs; no network."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from backend.services.engine.data_platform.calendars.calendar import CryptoCalendar
from backend.services.engine.data_platform.quantbc_hub import (
    QuantBCDataHub,
    _resolve_quantbc_data_dir,
)
from backend.services.engine.rd_agent.market_adapters.crypto import CryptoAdapter
from backend.shared.qlib_paths import resolve_qlib_provider_uri
from backend.tests.test_binance_release import intake


def _publish(root, release_id, offset=0):
    release = root / "releases" / release_id
    for day in (date(2024, 1, 6), date(2024, 1, 7)):
        target = (
            release / "1_kline_data/daily_forward" / f"dt={day:%Y%m%d}" / "data.parquet"
        )
        target.parent.mkdir(parents=True)
        bars = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "time": day,
                    "open": 100.0 + offset,
                    "high": 110.0 + offset,
                    "low": 90.0 + offset,
                    "close": 105.0 + offset,
                    "volume": 10.0,
                    "amount": 1047.0,
                    "quote_volume": 1047.0,
                    "open_time": pd.Timestamp(day, tz="UTC"),
                    "close_time": pd.Timestamp(day, tz="UTC")
                    + pd.Timedelta(days=1)
                    - pd.Timedelta(milliseconds=1),
                    "available_at": pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1),
                    "venue": "binance",
                    "product_type": "crypto_spot",
                    "release_id": release_id,
                }
                for symbol in ("BTCUSDT", "ETHUSDT")
            ]
        )
        bars.to_parquet(target, index=False)
    instruments = release / "2_base_sector/instrument_detail/instrument_list.parquet"
    instruments.parent.mkdir(parents=True)
    pd.DataFrame({"symbol": ["BTCUSDT", "ETHUSDT"]}).to_parquet(
        instruments, index=False
    )
    quality = {
        "status": "passed",
        "timezone": "UTC",
        "history_complete": True,
        "end_exclusive": "2024-01-08",
        "rows": 4,
        "source_revisions": [],
        "symbols": {
            s: {
                "rows": 2,
                "first": "2024-01-06",
                "last": "2024-01-07",
                "gaps": 0,
                "duplicates": 0,
                "unclosed": 0,
            }
            for s in ("BTCUSDT", "ETHUSDT")
        },
    }
    (release / "quality.json").write_text(json.dumps(quality))
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "status": "complete",
        "product_type": "crypto_spot",
        "venue": "binance",
        "frequency": "1d",
        "timezone": "UTC",
        "columns": list(bars.columns),
        "quality": quality,
        "available_at_semantics": "bar_period_end_lower_bound",
        "point_in_time_verified": False,
        "history_complete_scope": "current_public_api_daily_bar_coverage",
        "end_exclusive": "2024-01-08",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "data_start": "2024-01-06",
        "data_end": "2024-01-07",
        "files": {
            str(p.relative_to(release)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in release.rglob("*")
            if p.is_file()
        },
    }
    payload = json.dumps(manifest).encode()
    (release / "manifest.json").write_bytes(payload)
    (root / "CURRENT.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_id": release_id,
                "path": f"releases/{release_id}",
                "manifest_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    )
    return release


def test_release_bound_hub_qlib_and_closed_utc_calendar(tmp_path, monkeypatch):
    root = tmp_path / "quantbc"
    release = _publish(root, "first")
    monkeypatch.setenv("ENABLE_CRYPTO", "true")
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(root))
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(tmp_path / "unrelated-cn-cache"))
    adapter = CryptoAdapter()
    assert adapter.get_release_dir() == release
    assert not adapter.is_data_ready()
    hub = QuantBCDataHub(root)
    frame = hub.fetch_daily_kline_batch(
        ["BTCUSDT", "ETHUSDT"], date(2024, 1, 6), date(2024, 1, 7)
    )
    assert len(frame) == 4
    assert set(frame.symbol) == {"BTCUSDT", "ETHUSDT"}
    assert set(frame.amount) == {1047.0}
    assert adapter.prepare_data()
    assert adapter.is_data_ready()
    provider = Path(adapter.get_qlib_provider_uri())
    assert provider == root / "derived/first/bc_data"
    assert resolve_qlib_provider_uri("CRYPTO") == str(provider)
    assert (provider / "calendars/day.txt").read_text().splitlines() == [
        "2024-01-06",
        "2024-01-07",
    ]
    assert (provider / "instruments/all.txt").read_text().startswith("bc_BTCUSDT")
    close = np.fromfile(provider / "features/bc_btcusdt/close.day.bin", dtype="<f4")
    assert close.tolist() == [0.0, 105.0, 105.0]
    assert not (release / ".qlib_cache").exists()

    second = _publish(root, "second", offset=50)
    assert _resolve_quantbc_data_dir() == second
    assert CryptoAdapter().get_release_dir() == second
    assert adapter.get_release_dir() == release
    assert adapter.is_data_ready()
    assert hub.fetch_daily_kline(
        "BTCUSDT", date(2024, 1, 6), date(2024, 1, 7)
    ).close.tolist() == [105.0, 105.0]
    assert not CryptoAdapter().is_data_ready()

    calendar = CryptoCalendar()
    saturday = date(2024, 1, 6)
    assert calendar.is_trading_day(saturday)
    assert calendar.market_open(saturday) == datetime(2024, 1, 6, tzinfo=timezone.utc)
    assert calendar.market_close(saturday) == datetime(2024, 1, 7, tzinfo=timezone.utc)


def test_bad_pointer_and_unpublished_bars_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "quantbc"
    release = _publish(root, "first")
    monkeypatch.setenv("ENABLE_CRYPTO", "true")
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(root))
    parquet = next(release.rglob("data.parquet"))
    parquet.write_bytes(parquet.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        QuantBCDataHub(root)
    assert not CryptoAdapter().is_data_ready()
    assert not CryptoAdapter().prepare_data()
    pointer = json.loads((root / "CURRENT.json").read_text())
    pointer["manifest_sha256"] = "invalid"
    (root / "CURRENT.json").write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="checksum"):
        _resolve_quantbc_data_dir()


def test_tokenized_equity_readable_but_not_admitted_to_crypto_research(
    tmp_path, monkeypatch
):
    root = tmp_path / "tokenized-equity"
    release = _publish(root, "equity")
    manifest = json.loads((release / "manifest.json").read_text())
    manifest["product_type"] = "tokenized_equity_spot"
    payload = json.dumps(manifest).encode()
    (release / "manifest.json").write_bytes(payload)
    current = json.loads((root / "CURRENT.json").read_text())
    current["manifest_sha256"] = hashlib.sha256(payload).hexdigest()
    (root / "CURRENT.json").write_text(json.dumps(current))
    monkeypatch.setenv("ENABLE_CRYPTO", "true")
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(root))
    assert _resolve_quantbc_data_dir() == release
    assert (
        len(
            QuantBCDataHub(root).fetch_daily_kline(
                "BTCUSDT", date(2024, 1, 6), date(2024, 1, 7)
            )
        )
        == 2
    )
    assert not CryptoAdapter().is_data_ready()


@pytest.mark.parametrize(
    "field,value",
    [
        ("frequency", "5m"),
        ("timezone", "Asia/Shanghai"),
        ("quality", {"status": "failed"}),
        ("columns", ["close"]),
        ("available_at_semantics", "verified_publication_time"),
        ("point_in_time_verified", True),
        ("point_in_time_verified", 0),
        ("history_complete_scope", "point_in_time_history"),
        ("available_at_semantics", None),
        ("point_in_time_verified", None),
        ("history_complete_scope", None),
    ],
)
def test_research_rejects_wrong_daily_contract(tmp_path, field, value):
    release = _publish(tmp_path / "quantbc", "bad")
    manifest = json.loads((release / "manifest.json").read_text())
    if value is None:
        manifest.pop(field)
    else:
        manifest[field] = value
    (release / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        CryptoAdapter(release).get_release_dir()


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_current_publisher_contract_is_admitted(intake, monkeypatch, enabled):  # noqa: F811 - shared pytest fixture
    from backend.scripts import blockchain_sync
    from backend.services.engine.rd_agent.market_adapters import (
        get_adapter,
        list_markets,
    )

    monkeypatch.setenv("ENABLE_CRYPTO", enabled)
    published = blockchain_sync.run(**intake)
    adapter = CryptoAdapter(published["data_dir"])
    assert adapter.prepare_data()
    assert adapter.is_data_ready()
    assert adapter.get_data_config().extra["release_id"] == published["release_id"]
    if enabled == "false":
        assert "crypto" not in {item["market_id"] for item in list_markets()}
        with pytest.raises(ValueError, match="disabled"):
            get_adapter("crypto")


def test_release_inventory_symlinks_and_derived_output_are_protected(
    tmp_path, monkeypatch
):
    root = tmp_path / "quantbc"
    release = _publish(root, "protected")
    (release / "unexpected.txt").write_text("not published")
    with pytest.raises(ValueError, match="inventory"):
        CryptoAdapter(release).get_release_dir()
    (release / "unexpected.txt").unlink()
    quality = release / "quality.json"
    external = tmp_path / "external-quality.json"
    external.write_bytes(quality.read_bytes())
    quality.unlink()
    quality.symlink_to(external)
    with pytest.raises(ValueError, match="inventory"):
        CryptoAdapter(release).get_release_dir()
    quality.unlink()
    quality.write_bytes(external.read_bytes())
    (root / "derived").symlink_to(root / "releases", target_is_directory=True)
    with pytest.raises(ValueError, match="derived output"):
        CryptoAdapter(release).get_qlib_provider_uri()
    (root / "derived").unlink()
    pointer = json.loads((root / "CURRENT.json").read_text())
    pointer["path"] = "ignored/../releases/protected"
    (root / "CURRENT.json").write_text(json.dumps(pointer))
    monkeypatch.setenv("ENABLE_CRYPTO", "true")
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(root))
    with pytest.raises(ValueError, match="pointer"):
        _resolve_quantbc_data_dir()


def test_sync_wrapper_and_both_entrypoints_pin_publication_result(monkeypatch):
    from backend.scripts import quantbc_daily_sync as sync

    calls = []
    monkeypatch.setattr(
        sync,
        "_blockchain_run",
        lambda **kwargs: calls.append(kwargs) or {"data_dir": "/fixed/release"},
    )
    monkeypatch.setattr(
        sync,
        "prepare_research_data",
        lambda path: {"qlib_dir": path + "/cache", "release_id": "fixed"},
    )
    result = sync.run(
        datasets=["daily_forward", "instrument_detail"],
        start_date="2024-01-01",
        end_date="2024-02-01",
        source="archive",
        refresh_history=True,
        build_research=True,
    )
    assert result["research_data"]["qlib_dir"] == "/fixed/release/cache"
    assert calls[-1]["start_date"] == "2024-01-01" and calls[-1]["source"] == "archive"
    assert calls[-1]["refresh_history"] is True
    with pytest.raises(ValueError, match="does not produce"):
        sync.run(datasets=["valuation", "min5_kline"])

    # Execute only the orchestration functions, avoiding admin/DB module initialization.
    engine = Path(__file__).parents[2] / "services/engine"
    source = engine / "tasks/market_sync_scheduler.py"
    tree = ast.parse(source.read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "run_market_sync"
    )
    scope = {
        "datetime": datetime,
        "os": os,
        "Any": Any,
        "logger": logging.getLogger(__name__),
        "_has_sync_errors": lambda result: False,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
    scheduled = scope["run_market_sync"](
        "BC", {"days": 5, "datasets": ["daily_forward"], "with_qlib": True}
    )
    assert scheduled["qlib"]["provider_uri"] == "/fixed/release/cache"

    source = engine.parent / "api/routers/admin/global_market_console.py"
    tree = ast.parse(source.read_text())
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_run_sync_job"
    )
    updates = []
    scope = {
        "market": "BC",
        "sync_entry": "backend.scripts.quantbc_daily_sync",
        "Any": Any,
        "SyncDatasetsRequest": SimpleNamespace,
        "logger": logging.getLogger(__name__),
        "_job_update": lambda *args, **kwargs: updates.append(kwargs),
        "_now_iso": lambda: "now",
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
    request = SimpleNamespace(days=5, datasets=["daily_forward"], with_qlib=True)
    scope["_run_sync_job"]("job", request)
    assert updates[-1]["qlib_cache"]["provider_uri"] == "/fixed/release/cache"
    monkeypatch.setattr(
        sync,
        "prepare_research_data",
        lambda path: (_ for _ in ()).throw(ValueError("invalid input")),
    )
    scope["_run_sync_job"]("bad-job", request)
    assert updates[-1]["status"] == "partial"


def test_crypto_status_uses_previous_utc_day_without_stock_calendar():
    # Load the two pure helpers without importing the DB-backed admin router package.
    source = (
        Path(__file__).parents[2] / "services/api/routers/admin/data_status_scanner.py"
    )
    tree = ast.parse(source.read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"resolve_trade_date_sync", "_resolve_trade_date"}
    ]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 7, 0, 1, tzinfo=timezone.utc).astimezone(tz)

    scope = {
        "datetime": Clock,
        "timedelta": timedelta,
        "timezone": timezone,
        "ZoneInfo": ZoneInfo,
        "xcals": None,
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), scope
    )
    assert scope["resolve_trade_date_sync"]("crypto") == "2024-01-06"
    assert (
        asyncio.run(scope["_resolve_trade_date"]("crypto", "test", "test"))
        == "2024-01-06"
    )


def test_data_preparation_keeps_disabled_crypto_research_hidden(tmp_path, monkeypatch):
    pytest.importorskip("tables")
    from backend.scripts.quantbc_daily_sync import prepare_research_data
    from backend.services.engine.rd_agent.market_adapters import (
        get_adapter,
        list_markets,
    )
    from backend.services.engine.rd_agent.rd_loop_wrapper import RDLoopWrapper

    release = _publish(tmp_path / "quantbc", "data-only")
    monkeypatch.setenv("ENABLE_CRYPTO", "false")
    prepared = prepare_research_data(release)
    assert prepared["release_id"] == release.name
    assert (
        Path(prepared["qlib_dir"], "source_manifest.json").read_bytes()
        == (release / "manifest.json").read_bytes()
    )
    assert len(pd.read_hdf(Path(prepared["h5_dir"], "daily_pv_all.h5"), "data")) == 4
    assert "crypto" not in {item["market_id"] for item in list_markets()}
    with pytest.raises(ValueError, match="disabled"):
        get_adapter("crypto")
    with pytest.raises(ValueError, match="disabled"):
        RDLoopWrapper("crypto")


def test_h5_and_rd_workspace_stay_on_published_release(tmp_path, monkeypatch):
    pytest.importorskip("tables")
    from backend.services.engine.rd_agent.rd_loop_wrapper import RDLoopWrapper

    root = tmp_path / "quantbc"
    release = _publish(root, "first")
    monkeypatch.setenv("ENABLE_CRYPTO", "true")
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(root))
    wrapper = RDLoopWrapper("crypto")
    assert wrapper.adapter.prepare_data()
    task = tmp_path / "task"
    wrapper._ensure_data_file(str(task))
    h5 = pd.read_hdf(
        task / "git_ignore_folder/factor_implementation_source_data/daily_pv.h5", "data"
    )
    assert set(h5.index.get_level_values("instrument")) == {"bc_BTCUSDT", "bc_ETHUSDT"}
    assert len(h5) == 4 and set(h5["$factor"]) == {1.0}
    assert set(h5["$amount"]) == {1047.0}
    assert (task / "source_manifest.json").read_bytes() == (
        release / "manifest.json"
    ).read_bytes()
    _publish(root, "second", offset=50)
    newer = RDLoopWrapper("crypto")
    assert newer.adapter.prepare_data()
    with pytest.raises(RuntimeError, match="another crypto release"):
        newer._ensure_data_file(str(task))
    assert pd.read_hdf(
        task / "git_ignore_folder/factor_implementation_source_data/daily_pv.h5", "data"
    ).equals(h5)
    assert str(task / "data/bc_data") == wrapper._crypto_provider_uri
