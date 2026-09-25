"""R01 虚拟运行调度器测试（H2.2 任务5：复用 market_sync_scheduler 模式）。

- 无配置/未启用 ⇒ 不派发（无内置默认调度；平台 pending_activation）；
- 决策相位到点派发、去重；执行相位（待执行+窗口开）派发；
- beat 条目存在但无配置时为 no-op。

Redis 用进程内 Fake（get/set/scan_iter 语义子集）；_send 打桩记录。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend.services.engine.tasks import r01_virtual_run_scheduler as sched
from backend.services.simulation.replay.etf_input_package import build_fixture_package
from backend.services.simulation.virtual_run.states import (
    InMemoryRunStateStore,
    VirtualRunConfig,
)

SYM_A = "510300.SH"
SYM_G = "518880.SH"


def make_config(**kw) -> VirtualRunConfig:
    base = {
        "group": "A",
        "strategy_id": "fixture-vr-monthly",
        "strategy_version": 1,
        "initial_cash": 30000.0,
        "target_weights": {SYM_A: 0.6, SYM_G: 0.4},
        "commission_rate": 0.0003,
        "commission_min": 0.0,
        "slippage_bps": 0.0,
    }
    base.update(kw)
    return VirtualRunConfig(**base)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value if isinstance(value, str) else value.decode()
        return True

    def scan_iter(self, match=None, count=None):
        import fnmatch

        for k in list(self.data):
            if match is None or fnmatch.fnmatch(k, match):
                yield k


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(sched, "_redis", lambda: r)
    return r


@pytest.fixture
def store():
    return InMemoryRunStateStore()


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple[str, str]] = []
    monkeypatch.setattr(
        sched, "_send", lambda run_id, d: out.append((run_id, d.isoformat()))
    )
    return out


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    return build_fixture_package(tmp_path_factory.mktemp("vr-sched") / "pkg")


@pytest.fixture
def cfg(pkg, tmp_path):
    return make_config(
        package_root=str(pkg.root),
        manifest_sha256=pkg.manifest_sha256,
    )


def _at(day: date, hhmm: str) -> datetime:
    from backend.services.simulation.virtual_run.clock import shanghai

    from datetime import time as dtime

    h, m = hhmm.split(":")
    return datetime.combine(day, dtime(int(h), int(m)), tzinfo=shanghai()).astimezone(
        timezone.utc
    )


def test_no_schedule_means_no_dispatch(fake_redis, sent):
    """未配置任何调度 → 派发器 no-op（无内置默认调度）。"""
    out = sched.dispatch_due_runs(now=_at(date(2025, 9, 10), "15:15"), r=fake_redis)
    assert out["dispatched"] == [] and sent == []


def test_disabled_schedule_no_dispatch(fake_redis, sent, cfg):
    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=False)
    out = sched.dispatch_due_runs(now=_at(date(2025, 9, 10), "15:15"), r=fake_redis)
    assert out["dispatched"] == [] and sent == []


def test_decision_phase_dispatch_and_dedupe(fake_redis, sent, cfg, store):
    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=True)
    now = _at(date(2025, 9, 10), "15:15")  # 过决策截止 15:10
    out = sched.dispatch_due_runs(now=now, r=fake_redis, store=store)
    assert out["dispatched"] == [f"{cfg.ledger_run_id}:decision:2025-09-10"]
    assert sent == [(cfg.ledger_run_id, "2025-09-10")]
    # 同一轮内重复调用：去重（TTL 600s 内不重派）
    out2 = sched.dispatch_due_runs(now=now, r=fake_redis, store=store)
    assert out2["dispatched"] == [] and len(sent) == 1
    # 未到决策截止：不派发（09-11 09:00 未过 15:10）
    out3 = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 11), "09:00"), r=fake_redis, store=store
    )
    assert out3["dispatched"] == []


def test_execute_phase_dispatch_for_pending_decision(fake_redis, sent, cfg, pkg):
    """决策待执行（signal 已落、execute 未落）+ 执行窗口开 → 派发执行。"""
    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=True)
    store = InMemoryRunStateStore()
    run_id = cfg.ledger_run_id
    # 模拟 09-10 决策链已完成（signal 落盘、execute 未落）
    store.set_stage(run_id, "2025-09-10", "signal", {"action": "entry"})
    store.set_day(run_id, "2025-09-10", {"outcome": None})
    # 09-11 09:00：窗口（09:31）未开 → 不派发
    out = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 11), "09:00"), r=fake_redis, store=store
    )
    assert out["dispatched"] == []
    # 09:35：窗口已开 → 派发执行
    out = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 11), "09:35"), r=fake_redis, store=store
    )
    assert out["dispatched"] == [f"{run_id}:execute:2025-09-10"]
    # execute 已收口 → 不再派发
    store.set_stage(run_id, "2025-09-10", "execute", {"status": "executed"})
    fake_redis2 = FakeRedis()
    fake_redis2.data = dict(fake_redis.data)
    out = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 11), "09:40"), r=fake_redis, store=store
    )
    assert out["dispatched"] == []


def test_run_scheduled_day_pending_activation(fake_redis):
    out = sched.run_scheduled_day("r01vr-A-nonexistent-v1")
    assert out["status"] == "pending_activation"


def test_beat_entry_registered_no_default_schedule():
    """beat 有 dispatcher 条目（轮询器），但派发只看 Redis 配置=无内置默认。"""
    from backend.services.engine.qlib_app.celery_config import beat_schedule

    entry = beat_schedule.get("r01-virtual-run-dispatch")
    assert entry and entry["task"] == "engine.tasks.dispatch_r01_virtual_runs"


def test_schedule_roundtrip(fake_redis, cfg):
    saved = sched.save_run_config(cfg.ledger_run_id, cfg, enabled=False)
    assert saved["enabled"] is False  # 保存默认不启用
    got = sched.get_run_config(cfg.ledger_run_id)
    assert got is not None
    config, sched_cfg = got
    assert config.ledger_run_id == cfg.ledger_run_id
    assert config.target_weights == cfg.target_weights
    assert (
        json.loads(fake_redis.get(f"quantmind:r01:vr:schedule:{cfg.ledger_run_id}"))[
            "enabled"
        ]
        is False
    )


def test_pg_config_carrier_mapping():
    """p03 r01_virtual_run_config 行 → runner 冻结配置（H2.1-L3 消费端）。"""
    from types import SimpleNamespace

    from backend.services.engine.tasks.r01_virtual_run_scheduler import (
        virtual_run_config_from_pg_row,
    )

    row = SimpleNamespace(
        ledger_run_id="r01vr-A-myetf-v2",
        enabled=True,
        strategy_id="myetf",
        strategy_version=2,
        group="A",
        initial_cash=30000.0,
        granularity_check_cash=20000.0,
        risk_config={
            "loss_line_amount": 9000.0,
            "drawdown_pct": 0.30,
            "commission_rate": 0.00005,
            "commission_min": 0.1,
        },
        data_source={"baseline_root": "/pkg/v2", "baseline_manifest_sha256": "ab" * 32},
        execution_window={
            "target_weights": {"510300.SH": 0.6, "518880.SH": 0.4},
            "decision_cutoff": "00:30",
            "execution_time": "09:31",
            "missed_window_policy": "execute_next_window",
        },
        schedule_key="quantmind:r01:vr:schedule:r01vr-A-myetf-v1",
        source_plan_ref="frozen-plan-A#v2",
    )
    cfg = virtual_run_config_from_pg_row(row)
    assert cfg.ledger_run_id == "r01vr-A-myetf-v2"
    assert cfg.strategy_version == 2
    assert cfg.target_weights == {"510300.SH": 0.6, "518880.SH": 0.4}
    assert cfg.missed_window_policy == "execute_next_window"
    assert cfg.decision_cutoff == "00:30"
    assert cfg.loss_line_amount == 9000.0
    assert cfg.commission_min == 0.1
    assert cfg.package_root == "/pkg/v2"
    led_cfg = cfg.to_ledger_config()
    assert led_cfg.run_kind == "virtual" and led_cfg.ledger_run_id == "r01vr-A-myetf-v2"
    # 主键与派生身份漂移显式拒绝
    bad = SimpleNamespace(**{**row.__dict__, "ledger_run_id": "r01vr-A-myetf-v1"})
    import pytest as _pytest

    with _pytest.raises(ValueError, match="漂移"):
        virtual_run_config_from_pg_row(bad)


def test_run_scheduled_day_disabled_stops_at_entry(fake_redis, cfg):
    """J4R2 #3：运行中被禁用 → 任务入口即停（stopped_by_config）。"""
    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=True)
    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=False)  # 禁用
    out = sched.run_scheduled_day(cfg.ledger_run_id)
    assert out["status"] == "stopped_by_config"


def test_dispatcher_auto_redispatches_blocked_day_in_window(
    fake_redis, sent, cfg, pkg, store
):
    """J5R3 #4：受阻日数据补齐后自动重新门控执行（不跳过）。

    场景：09-11 决策受阻（outcome=data_blocked）；窗口（09-12 09:31）内
    beat 重派 → 任务重跑重新门控（数据补齐则恢复）；窗口过后不再重派。
    """
    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=True)
    run_id = cfg.ledger_run_id
    store.set_stage(run_id, "2025-09-11", "data_check", {"status": "data_blocked"})
    store.set_day(run_id, "2025-09-11", {"outcome": "data_blocked"})

    # 窗口内（09-11 15:20，执行窗口 09-12 09:31 未到）→ 重派
    out = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 11), "15:20"), r=fake_redis, store=store
    )
    assert out["dispatched"] == [f"{run_id}:decision:2025-09-11"]
    assert sent == [(run_id, "2025-09-11")]

    # 恢复完成（outcome=completed）→ 不再派发
    fake_redis2 = FakeRedis()
    fake_redis2.data = dict(fake_redis.data)
    fake_redis2.data.pop(
        next(k for k in fake_redis2.data if k.endswith(":2025-09-11:decision")), None
    )
    store.set_day(run_id, "2025-09-11", {"outcome": "completed"})
    out = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 11), "15:30"), r=fake_redis2, store=store
    )
    assert out["dispatched"] == []

    # 窗口过后仍受阻（09-12 10:00 > 09:31）→ 受阻终态不重派
    store.set_day(run_id, "2025-09-11", {"outcome": "data_blocked"})
    fake_redis3 = FakeRedis()
    fake_redis3.data = dict(fake_redis2.data)
    out = sched.dispatch_due_runs(
        now=_at(date(2025, 9, 12), "10:00"), r=fake_redis3, store=store
    )
    assert out["dispatched"] == []
    assert any("blocked-final" in x for x in out["skipped"])


def test_dispatcher_blocked_recovery_end_to_end(fake_redis, monkeypatch, cfg, pkg):
    """J6R4 #3 端到端：经 dispatcher/调度入口——受阻→（窗口内）自动重派
    →任务重跑重新门控→数据补齐恢复当日决策→执行收口。

    _send 打桩为内联执行任务体（pipeline 为注入的 fixture 后端）；派发
    判定（何时/是否重派）完全走真实 dispatch_due_runs。
    """
    from datetime import datetime, timezone

    from backend.services.simulation.virtual_run import FrozenClock
    from backend.services.simulation.virtual_run.locks import InMemoryLockBackend
    from backend.services.simulation.virtual_run.pipeline import VirtualRunPipeline
    from backend.services.simulation.virtual_run.recovery import InMemoryCheckpointStore
    from backend.services.simulation.virtual_run.states import InMemoryRunStateStore

    from backend.services.tests.test_r01_virtual_run_fixes import FlakyProvider

    sched.save_run_config(cfg.ledger_run_id, cfg, enabled=True)
    provider = FlakyProvider(pkg, blocked_first={date(2025, 9, 11)})
    clock = FrozenClock(datetime(2025, 9, 11, 7, 0, tzinfo=timezone.utc))
    pipe = VirtualRunPipeline(
        cfg,
        provider,
        clock=clock,
        lock_backend=InMemoryLockBackend(),
        state_store=InMemoryRunStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    store = pipe.store

    def _run_task(ledger_run_id: str, decision_date) -> None:
        # 任务体：beat→dispatcher→send→（此处内联）执行决策日
        d = (
            decision_date
            if isinstance(decision_date, date)
            else date.fromisoformat(decision_date)
        )
        pipe.run_day(d)

    monkeypatch.setattr(sched, "_send", _run_task)
    # 任务入口 build_pipeline 走注入（真实入口联调见集成证据）
    monkeypatch.setattr(sched, "build_pipeline", lambda config, schedule_cfg=None: pipe)

    # 09-10 15:15：正常决策（dispatcher 派发 → 任务执行）
    clock.set_shanghai(date(2025, 9, 10), "15:15")
    out = sched.dispatch_due_runs(now=clock.now(), r=fake_redis, store=store)
    assert "decision:2025-09-10" in ",".join(out["dispatched"])
    # 09-11 09:31：执行相位派发 → 执行
    clock.set_shanghai(date(2025, 9, 11), "09:31")
    out = sched.dispatch_due_runs(now=clock.now(), r=fake_redis, store=store)
    assert "execute:2025-09-10" in ",".join(out["dispatched"])

    # 09-11 15:15：决策受阻（首次门控 blocked，任务如实记录受阻）
    clock.set_shanghai(date(2025, 9, 11), "15:15")
    out = sched.dispatch_due_runs(now=clock.now(), r=fake_redis, store=store)
    assert "decision:2025-09-11" in ",".join(out["dispatched"])
    rec = store.get_day(cfg.ledger_run_id, "2025-09-11")
    assert rec["outcome"] == "data_blocked"

    # 09-11 15:25（窗口内，数据已补齐）：dispatcher 自动重派 → 恢复当日决策
    fake_redis2 = FakeRedis()  # 绕过去重 TTL（模拟下一轮 beat 的键状态）
    fake_redis2.data = dict(fake_redis.data)
    fake_redis2.data.pop(
        next(k for k in fake_redis2.data if k.endswith(":2025-09-11:decision")), None
    )
    clock.set_shanghai(date(2025, 9, 11), "15:25")
    out = sched.dispatch_due_runs(now=clock.now(), r=fake_redis2, store=store)
    assert "decision:2025-09-11" in ",".join(out["dispatched"])
    # 决策已推进：signal 阶段已落、execute 未落（待执行窗口）
    assert store.get_stage(cfg.ledger_run_id, "2025-09-11", "signal") is not None
    assert store.get_stage(cfg.ledger_run_id, "2025-09-11", "execute") is None

    # 09-12 09:31：执行相位派发 → 当日收口
    clock.set_shanghai(date(2025, 9, 12), "09:31")
    out = sched.dispatch_due_runs(now=clock.now(), r=fake_redis, store=store)
    assert "execute:2025-09-11" in ",".join(out["dispatched"])
    rec = store.get_day(cfg.ledger_run_id, "2025-09-11")
    assert rec["outcome"] == "completed"
    led = pipe.checkpoints.load(pkg, cfg.to_ledger_config())
    assert led.export_checkpoint()["executed_dates"] == ["2025-09-11", "2025-09-12"]


def test_recent_trade_dates_monday_covers_friday(pkg):
    """J6R4 #3：回看窗口按交易日历（周一覆盖周五，跳过周末）。"""
    from backend.services.simulation.virtual_run.gating import StaticPackageProvider

    from backend.services.engine.tasks.r01_virtual_run_scheduler import (
        _recent_trade_dates,
    )

    provider = StaticPackageProvider(pkg)
    # 2025-09-15（周一）回看：09-12(五)/09-11(四)/09-10(三)，无周末日
    got = _recent_trade_dates(provider, pkg, date(2025, 9, 15), 3)
    assert got == [date(2025, 9, 12), date(2025, 9, 11), date(2025, 9, 10)]
