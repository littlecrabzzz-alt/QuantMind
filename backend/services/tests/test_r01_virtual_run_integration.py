"""R01 虚拟运行真实链路联调测试（p02 日增量包 + p04 run_status 校验）。

- DailyIncrementProvider：真实 d20260924 包（本机注册表）就绪门控 +
  「基线日期走基线包」路径；无包未来日显式 data_blocked；
- 合成未来日增量包（数据行取自真实 d20260924，仅日期掩码推进到基线
  之后；临时注册表隔离）验证 基线+日增量合并 → 流水线跨基线日期
  运行（决策→次日执行全链路）；
- to_platform_payload 全部输出通过 p04 runstatus.validate_run_status
  （平台 POST 侧同源校验，不另写一套口径）。

待联调注记：真实"基线之后"的日包发布后（下一交易日），本文件合成
掩码用例可替换为直接消费（registry 指向真实路径即可）。
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from backend.services.simulation.virtual_run import FrozenClock, VirtualRunPipeline
from backend.services.simulation.virtual_run.gating import DailyIncrementProvider
from backend.services.simulation.virtual_run.locks import InMemoryLockBackend
from backend.services.simulation.virtual_run.pipeline import VirtualRunPipeline as _VP
from backend.services.simulation.virtual_run.recovery import InMemoryCheckpointStore
from backend.services.simulation.virtual_run.states import (
    InMemoryRunStateStore,
    VirtualRunConfig,
    to_platform_payload,
)

BASELINE = (
    "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7"
)
BASELINE_SHA = "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"
REAL_DAILY = (
    "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/d20260924"
)

real_pkg_needed = pytest.mark.skipif(
    not Path(REAL_DAILY, "manifest.json").is_file(),
    reason="真实 d20260924 日包不在本机（p02 发布产物）",
)

NOW = datetime(2026, 9, 25, 8, 0, tzinfo=__import__("datetime").timezone.utc)


def _provider(tmp_path: Path, **kw) -> DailyIncrementProvider:
    return DailyIncrementProvider(
        BASELINE,
        baseline_manifest_sha256=BASELINE_SHA,
        cache_dir=str(tmp_path / "merged"),
        **kw,
    )


@real_pkg_needed
def test_real_daily_package_ready_and_baseline_path(tmp_path):
    """真实 d20260924：优先日包路径；基线内无包日回退基线。"""
    p = _provider(tmp_path)
    # 2026-09-24 有真实日包 → 日增量路径（身份绑定 d20260924）
    r = p.resolve(date(2026, 9, 24), symbols=["510300.SH", "518880.SH"], now=NOW)
    assert r.status == "ready"
    assert r.identity is not None and r.identity.package_version == "d20260924"
    assert r.identity.manifest_sha256 == (
        "4bcf7dac2c6005ff00ae60f3bda3d371185b0b2e37eb96350ef6d425437b9f05"
    )
    assert r.package.trade_dates()[-1] >= date(2026, 9, 24)
    # 2026-09-23 在基线内且无日包 → 回退基线（回放/历史场景）
    r2 = p.resolve(date(2026, 9, 23), symbols=["510300.SH", "518880.SH"], now=NOW)
    assert r2.status == "ready"
    assert r2.package is not None and r2.package.is_trade_date(date(2026, 9, 23))


@real_pkg_needed
def test_real_registry_miss_future_date_blocked(tmp_path):
    """无日包的未来决策日：显式 data_blocked（不臆造休市、不陈旧冒充）。"""
    p = _provider(tmp_path)
    r = p.resolve(date(2026, 10, 9), symbols=["510300.SH"], now=NOW)
    assert r.status == "data_blocked"
    assert "no_daily_package" in (r.reason or "")


def _make_synthetic_future_daily(tmp_path: Path) -> tuple[Path, Path]:
    """从真实 d20260924 派生两个「基线之后」的日包（日期掩码 09-25/26）。

    数据行/因子/事件结构原样取自真实包，仅 decision_date/日期列推进——
    供合并与流水线链路验证；不写真实注册表（临时注册表隔离）。
    """
    import pandas as pd

    src = Path(REAL_DAILY)
    out_root = tmp_path / "daily-out"
    registry = tmp_path / "registry.json"
    entries = {}
    for day in (date(2026, 9, 25), date(2026, 9, 26)):
        d8 = day.strftime("%Y%m%d")
        dst = out_root / f"d{d8}"
        for sub in ("daily", "events", "factors", "etf_limit"):
            sdir = src / sub
            if not sdir.is_dir():
                continue
            (dst / sub).mkdir(parents=True, exist_ok=True)
            for f in sdir.glob("*.parquet"):
                df = pd.read_parquet(f)
                if sub == "daily" and "trade_date" in df.columns:
                    df["trade_date"] = (
                        df["trade_date"]
                        .astype(str)
                        .str.replace("20260924", d8)
                        .str.replace("2026-09-24", day.isoformat())
                    )
                (dst / sub / f.name).parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(dst / sub / f.name)
        manifest = json.loads((src / "manifest.json").read_text())
        manifest["decision_date"] = day.isoformat()
        manifest["data_as_of"] = day.isoformat()
        manifest["package_id"] = f"fixture-daily-{d8}"
        manifest["package_version"] = f"d{d8}"
        manifest["package_uri"] = f"node://mac/r01-etf-daily/d{d8}"
        for sym in manifest.get("symbols", []):
            sym["data_start"] = day.isoformat()
            sym["data_end"] = day.isoformat()
        (dst / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        entries[manifest["package_uri"]] = {
            "absolute_path": str(dst),
            "package_id": manifest["package_id"],
            "package_version": manifest["package_version"],
            "kind": "daily_increment",
        }
    registry.write_text(
        json.dumps({"packages": entries}, ensure_ascii=False), encoding="utf-8"
    )
    return out_root, registry


@real_pkg_needed
def test_merged_package_and_pipeline_across_baseline_end(tmp_path):
    """基线+日增量合并 → 流水线跨基线末尾运行（决策→次日执行）。"""
    _out, registry = _make_synthetic_future_daily(tmp_path)
    p = DailyIncrementProvider(
        BASELINE,
        baseline_manifest_sha256=BASELINE_SHA,
        registry_path=str(registry),
        cache_dir=str(tmp_path / "merged"),
    )
    r = p.resolve(date(2026, 9, 25), symbols=["510300.SH", "518880.SH"], now=NOW)
    assert r.status == "ready", r.reason
    assert r.identity is not None and r.identity.package_version == "d20260925"
    merged = r.package
    tds = merged.trade_dates()
    assert tds[-2:] == [date(2026, 9, 25), date(2026, 9, 26)]

    # 流水线：09-25 决策（首日建仓）→ 09-26 执行
    cfg = VirtualRunConfig(
        group="A",
        strategy_id="fixture-vr-real-increment",
        strategy_version=1,
        initial_cash=30000.0,
        target_weights={"510300.SH": 0.6, "518880.SH": 0.4},
        commission_rate=0.0003,
        commission_min=0.0,
        slippage_bps=0.0,
    )
    clock = FrozenClock()
    clock.set_shanghai(date(2026, 9, 25), "15:15")
    pipeline = VirtualRunPipeline(
        cfg,
        p,
        clock=clock,
        lock_backend=InMemoryLockBackend(),
        state_store=InMemoryRunStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    res = pipeline.run_day(date(2026, 9, 25))
    assert res.outcome == "pending_execute"
    clock.set_shanghai(date(2026, 9, 26), "09:31")
    res = pipeline.run_day(date(2026, 9, 25))
    assert res.outcome == "completed"
    day_rec = pipeline.store.get_day(cfg.ledger_run_id, "2026-09-25")
    assert day_rec["execution"]["execution_date"] == "2026-09-26"
    assert day_rec["orders_summary"], "建仓应有订单（真实日增量合并数据）"
    # 身份五元组入日记录
    ident = day_rec["identity"]
    assert ident["package_version"] == "d20260925"
    assert ident["manifest_sha256"] and ident["obtained_at"]


def _ensure_p04_runstatus_importable():
    """p04 runstatus 仅在 store 层用 psycopg（validate 纯函数）；宿主无
    psycopg 时注入最小 stub 供导入（不做平台写入，只做同源校验）。"""
    import sys
    import types

    try:
        import psycopg  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    if "psycopg" in sys.modules:
        return
    stub = types.ModuleType("psycopg")
    types_mod = types.ModuleType("psycopg.types")
    json_mod = types.ModuleType("psycopg.types.json")

    class _Jsonb:  # store 层占位；validate 不触碰
        def __init__(self, *a, **k):
            pass

    json_mod.Jsonb = _Jsonb
    types_mod.json = json_mod
    stub.types = types_mod
    sys.modules["psycopg"] = stub
    sys.modules["psycopg.types"] = types_mod
    sys.modules["psycopg.types.json"] = json_mod


@real_pkg_needed
def test_platform_payload_passes_p04_validation(tmp_path):
    """to_platform_payload 输出全部通过 p04 POST 侧校验（含待启用/受阻/运行态）。"""
    _ensure_p04_runstatus_importable()
    from backend.services.research_agent import runstatus

    _out, registry = _make_synthetic_future_daily(tmp_path)
    p = DailyIncrementProvider(
        BASELINE,
        baseline_manifest_sha256=BASELINE_SHA,
        registry_path=str(registry),
        cache_dir=str(tmp_path / "merged"),
    )
    cfg = VirtualRunConfig(
        group="A",
        strategy_id="fixture-vr-real-increment",
        strategy_version=1,
        initial_cash=30000.0,
        target_weights={"510300.SH": 0.6, "518880.SH": 0.4},
        commission_rate=0.0003,
        commission_min=0.0,
        slippage_bps=0.0,
    )
    clock = FrozenClock()
    reported: list[dict] = []
    pipeline = VirtualRunPipeline(
        cfg,
        p,
        clock=clock,
        lock_backend=InMemoryLockBackend(),
        state_store=InMemoryRunStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        platform_reporter=reported.append,
    )
    # 未配置调度 → configured=False 且不带 next_run_at（平台强校验）
    clock.set_shanghai(date(2026, 9, 25), "15:15")
    pipeline.run_day(date(2026, 9, 25))
    clock.set_shanghai(date(2026, 9, 26), "09:31")
    pipeline.run_day(date(2026, 9, 25))
    assert reported
    for payload in reported:
        runstatus.validate_run_status(payload)  # 不抛 = 通过平台 POST 校验
    assert all(pl["schedule"]["configured"] is False for pl in reported)
    # 有订单运行日 → running；并带账本导出字段
    assert reported[-1]["run_state"] in ("running", "no_trade_needed")
    assert reported[-1]["nav"] and reported[-1]["positions"] is not None

    # data_blocked 场景载荷（未来日无包）
    r = p.resolve(date(2026, 10, 9), symbols=["510300.SH"], now=NOW)
    status_blocked = {
        "ledger_run_id": cfg.ledger_run_id,
        "strategy_id": cfg.strategy_id,
        "strategy_version": cfg.strategy_version,
        "group": cfg.group,
        "input_date": {"decision_date": "2026-10-09"},
        "today_decision": {"action": "data_blocked", "reason": r.reason},
        "anomalies": [{"kind": "data_blocked", "detail": r.reason}],
    }
    payload = to_platform_payload(status_blocked)
    runstatus.validate_run_status(payload)
    assert payload["run_state"] == "data_blocked"

    # 三段停止生效 → paused_job
    payload2 = to_platform_payload(
        {
            **status_blocked,
            "today_decision": {"action": "no_trade", "reason": "stopped"},
        },
        control={"command": "stop", "state": "effective"},
    )
    runstatus.validate_run_status(payload2)
    assert payload2["run_state"] == "paused_job"
    assert payload2["stop_restore"]["job_stop"]["stage"] == "effective"
