"""R01 虚拟运行 J4R2 修复测试（复核 1/3/4/5 的 runner 侧）。

- #4 同日重试：错过决策窗口后同日重入不读 identity；data_blocked 窗口内
  数据补齐可恢复当日决策（对齐派发单"数据迟到"验收）；
- #2 冻结输入哈希锁定：运行身份冻结后按注册表锁定的哈希清单取内容
  （不重取最新）；修订包不参与合并；obtained_at 晚于运行时钟 → 受阻；
- #5 状态语义：last_success_at 仅计真实成功执行；next_run_at 为实际
  下一调度时刻（ISO）或待启用；停止先生效后回报（不停留 received）。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.services.simulation.replay.etf_input_package import (
    build_fixture_package,
)
from backend.services.simulation.virtual_run.gating import (
    DailyDataIdentity,
    DailyIncrementProvider,
    StaticPackageProvider,
)
from backend.services.simulation.virtual_run.states import (
    build_run_status,
    to_platform_payload,
)
from backend.services.tests.test_r01_virtual_run_pipeline import (
    Harness,
    make_config,
)

NOW = datetime(2025, 10, 3, 3, 0, tzinfo=timezone.utc)


def _next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d = date.fromordinal(d.toordinal() + 1)
    return d


# ---------------------------------------------------------------------------
# 测试辅助 provider（受阻→恢复）
# ---------------------------------------------------------------------------


class FlakyProvider(StaticPackageProvider):
    """首次对 blocked_first 日期门控受阻，之后放行（模拟数据迟到补齐）。"""

    def __init__(self, pkg, *, blocked_first: set[date]):
        super().__init__(pkg)
        self.blocked_first = set(blocked_first)
        self._seen: set[date] = set()

    def resolve(self, decision_date, *, symbols, now):
        if decision_date in self.blocked_first and decision_date not in self._seen:
            self._seen.add(decision_date)
            from backend.services.simulation.virtual_run.gating import (
                GateCheck,
                GateResult,
            )

            return GateResult(
                status="data_blocked",
                reason="data_late: 注入（首次门控受阻，数据未到）",
                checks=[GateCheck("freshness", "fail", "injected late")],
            )
        return super().resolve(decision_date, symbols=symbols, now=now)


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    return build_fixture_package(tmp_path_factory.mktemp("vr-fix") / "pkg")


# ---------------------------------------------------------------------------
# #4 同日重试 / 受阻恢复
# ---------------------------------------------------------------------------


def test_blocked_recovers_within_window(pkg):
    """数据迟到受阻 → 同窗口内数据补齐 → 当日决策恢复执行。"""
    provider = FlakyProvider(pkg, blocked_first={date(2025, 9, 11)})
    h = Harness(pkg, make_config())
    h.provider = provider
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))

    # 09-11 决策：首次门控受阻
    r = h.decide(date(2025, 9, 11))
    assert r.outcome == "data_blocked"
    assert h.day_record(date(2025, 9, 11))["outcome"] == "data_blocked"
    # last_success_at 不计受阻日（#5）：停留在决策 09-10 的完成时间戳
    status = h.store.get_status(h.config.ledger_run_id)
    assert status["last_success_at"].startswith("2025-09-11T01:31")

    # 同窗口内重试：数据已补齐 → 恢复当日决策并执行
    r = h.decide(date(2025, 9, 11))
    assert r.outcome == "pending_execute"
    r = h.execute(date(2025, 9, 11))
    assert r.outcome == "completed"
    rec = h.day_record(date(2025, 9, 11))
    assert rec["outcome"] == "completed"
    st = h.ledger_state()
    assert "2025-09-12" in st["executed_dates"]
    # 恢复后 last_success_at 前进到决策 09-11 的完成时间戳（执行时刻）
    status = h.store.get_status(h.config.ledger_run_id)
    assert status["last_success_at"].startswith("2025-09-12T01:31")


def test_missed_same_day_retry_no_identity_read(pkg):
    """错过决策窗口后同日重入：不读 identity，返回已记录的错过结果。"""
    h = Harness(pkg, make_config())
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    # 睡过 09-11 决策窗口（09-12 15:00 已过 09-12 09:31 执行窗口开端）
    h.clock.set_shanghai(date(2025, 9, 12), "15:00")
    r = h.pipeline().run_day(date(2025, 9, 11))
    assert r.outcome == "missed_decision_window"
    # 同日再重试：无 KeyError，仍为已记录的错过（不补写决策）
    r2 = h.pipeline().run_day(date(2025, 9, 11))
    assert r2.outcome == "missed_decision_window"
    # last_success_at 不计错过日（#5）：停留在决策 09-10 的完成时间戳
    status = h.store.get_status(h.config.ledger_run_id)
    assert status["last_success_at"].startswith("2025-09-11T01:31")


# ---------------------------------------------------------------------------
# #2 冻结输入哈希锁定 / 修订排除 / obtained_at 时钟校验
# ---------------------------------------------------------------------------


def _write_daily_pkg(
    root: Path,
    version_day: date,
    *,
    baseline_pkg,
    revised: bool = False,
    obtained_at: str | None = None,
) -> dict:
    """合成一个 p02 口径的日增量包（行取自基线 fixture 末日，日期推进）。"""
    import hashlib
    import json

    import pandas as pd

    d8 = version_day.strftime("%Y%m%d")
    dst = root / (f"d{d8}" + ("r1" if revised else ""))
    for sub in ("daily", "events", "factors", "etf_limit"):
        (dst / sub).mkdir(parents=True, exist_ok=True)
    codes = [s["code"] for s in baseline_pkg.manifest["symbols"]]
    last = max(baseline_pkg.trade_dates())
    for code in codes:
        src = Path(baseline_pkg.root) / "daily" / f"{code}.parquet"
        df = pd.read_parquet(src)
        row = df[df["trade_date"] == last.isoformat()]
        if row.empty:
            continue
        new = row.copy()
        new["trade_date"] = version_day.isoformat()
        pd.concat([new], ignore_index=True).to_parquet(
            dst / "daily" / f"{code}.parquet", index=False
        )
    version = f"d{d8}" + ("r1" if revised else "")
    manifest = {
        "schema_version": 3.1,
        "package_kind": "daily_increment",
        "package_id": f"fixture-daily-{d8}",
        "package_version": version,
        "package_uri": f"node://test/r01-etf-daily/{version}",
        "source_release_id": "data-fixture",
        "decision_date": version_day.isoformat(),
        "data_as_of": version_day.isoformat(),
        "obtained_at": obtained_at or f"{version_day.isoformat()}T16:00:00+00:00",
        "revised": revised,
        "supersedes": (
            {"package_version": f"d{d8}", "manifest_sha256": "0" * 64}
            if revised
            else None
        ),
        "quality_gate": {"overall": "pass", "decision_date_is_trade_day": True},
        "symbols": [
            {
                "code": c,
                "role": "primary",
                "data_start": version_day.isoformat(),
                "data_end": version_day.isoformat(),
            }
            for c in codes
        ],
    }
    # 日历（合成：工作日开市、周末休市，覆盖 day-10..day+40）——供
    # next_open_trade_date/前沿判定（H2-AC01 验收场景需要日历已知）
    cal_rows = []
    for i in range(-10, 41):
        dd = date.fromordinal(version_day.toordinal() + i)
        cal_rows.append(
            {
                "exchange": "SSE",
                "cal_date": dd.strftime("%Y%m%d"),
                "is_open": 0 if dd.weekday() >= 5 else 1,
                "pretrade_date": None,
            }
        )
    pd.DataFrame(cal_rows).to_parquet(dst / "calendar.parquet", index=False)
    (dst / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "absolute_path": str(dst),
        "package_id": manifest["package_id"],
        "package_version": version,
        "kind": "daily_increment",
    }


@pytest.fixture
def inc_env(tmp_path):
    """基线 fixture 包 + 可增量写入的临时注册表。"""
    import json

    baseline = build_fixture_package(tmp_path / "base-pkg")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"packages": {}}), encoding="utf-8")
    provider = DailyIncrementProvider(
        str(baseline.root),
        baseline_manifest_sha256=baseline.manifest_sha256,
        registry_path=str(registry),
        cache_dir=str(tmp_path / "merged"),
    )
    return baseline, registry, provider, tmp_path


def _add_entry(registry: Path, uri: str, entry: dict) -> None:
    import json

    data = json.loads(registry.read_text(encoding="utf-8"))
    data["packages"][uri] = entry
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_freeze_lock_excludes_post_freeze_and_revisions(inc_env):
    """冻结后新发布/修订包不改变已冻结运行的输入内容。"""
    baseline, registry, provider, tmp = inc_env
    d1 = _next_weekday(date.fromordinal(max(baseline.trade_dates()).toordinal() + 1))
    _add_entry(
        registry,
        f"node://test/r01-etf-daily/d{d1.strftime('%Y%m%d')}",
        _write_daily_pkg(tmp, d1, baseline_pkg=baseline),
    )
    r = provider.resolve(d1, symbols=["510300.SH", "518880.SH"], now=NOW)
    assert r.status == "ready", r.reason
    lock = provider.input_lock(upto=d1)
    assert [e["package_version"] for e in lock["daily"]] == [
        f"d{d1.strftime('%Y%m%d')}"
    ]

    # 冻结后：发布修订包 + 更晚的新包
    _add_entry(
        registry,
        f"node://test/r01-etf-daily/d{d1.strftime('%Y%m%d')}r1",
        _write_daily_pkg(tmp, d1, baseline_pkg=baseline, revised=True),
    )
    d2 = date.fromordinal(d1.toordinal() + 1)
    _add_entry(
        registry,
        f"node://test/r01-etf-daily/d{d2.strftime('%Y%m%d')}",
        _write_daily_pkg(tmp, d2, baseline_pkg=baseline),
    )

    # 冻结清单加载：内容不含 d2、不含修订包（日历/行都不扩展）
    frozen_pkg = provider.load(r.identity, lock=lock)
    assert frozen_pkg.trade_dates()[-1] == max(baseline.trade_dates()) or (
        frozen_pkg.trade_dates()[-1] == d1
    )
    assert d2 not in frozen_pkg.trade_dates()

    # 未冻结（最新）视图：含 d2、仍不含修订
    latest = provider.load(r.identity)
    assert d2 in latest.trade_dates()
    # 修订包被排除在一切运行合并之外
    assert not any(
        e["package_version"].endswith("r1") for e in provider.input_lock()["daily"]
    )


def test_lock_hash_mismatch_rejected(inc_env):
    """清单哈希与实际内容不符（被动过）→ 显式拒绝，不静默续。"""
    baseline, registry, provider, tmp = inc_env
    d1 = _next_weekday(date.fromordinal(max(baseline.trade_dates()).toordinal() + 1))
    entry = _write_daily_pkg(tmp, d1, baseline_pkg=baseline)
    _add_entry(registry, f"node://test/r01-etf-daily/d{d1.strftime('%Y%m%d')}", entry)
    r = provider.resolve(d1, symbols=["510300.SH"], now=NOW)
    assert r.status == "ready"
    lock = provider.input_lock(upto=d1)
    # 篡改日包 manifest → 哈希失配
    mf = Path(entry["absolute_path"]) / "manifest.json"
    mf.write_text(
        mf.read_text(encoding="utf-8").replace("pass", "pass "), encoding="utf-8"
    )
    ident = DailyDataIdentity(
        decision_date=d1.isoformat(),
        package_id="x",
        package_version=f"d{d1.strftime('%Y%m%d')}",
        source_release_id="x",
        manifest_sha256="0" * 64,
        data_as_of=d1.isoformat(),
        obtained_at=NOW.isoformat(),
    )
    with pytest.raises(ValueError, match="哈希失配|input_lock"):
        provider.load(ident, lock=lock)


def test_obtained_at_in_future_blocked(inc_env):
    """obtained_at 晚于运行时钟：数据未取得，受阻不得进入决策。"""
    baseline, registry, provider, tmp = inc_env
    d1 = _next_weekday(date.fromordinal(max(baseline.trade_dates()).toordinal() + 1))
    future_obtained = (NOW + timedelta(days=2)).isoformat()
    _add_entry(
        registry,
        f"node://test/r01-etf-daily/d{d1.strftime('%Y%m%d')}",
        _write_daily_pkg(tmp, d1, baseline_pkg=baseline, obtained_at=future_obtained),
    )
    r = provider.resolve(d1, symbols=["510300.SH"], now=NOW)
    assert r.status == "data_blocked"
    assert "data_not_yet_obtained" in r.reason


# ---------------------------------------------------------------------------
# #5 状态语义
# ---------------------------------------------------------------------------


def test_last_success_excludes_blocked_and_missed(pkg):
    h = Harness(pkg, make_config())
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    h.decide(date(2025, 9, 11))
    h.execute(date(2025, 9, 11))
    # 09-12 受阻（注入迟到）
    h.provider = FlakyProvider(pkg, blocked_first={date(2025, 9, 12)})
    h.decide(date(2025, 9, 12))
    # 09-15 错过（时钟拨过窗口）
    h.clock.set_shanghai(date(2025, 9, 16), "15:00")
    h.pipeline().run_day(date(2025, 9, 15))
    day_records = {
        d: h.store.get_day(h.config.ledger_run_id, d)
        for d in h.store.list_days(h.config.ledger_run_id)
    }
    status = build_run_status(
        h.config,
        store=h.store,
        day_records=day_records,
        ledger_summary=None,
        schedule_cfg=None,
        now=h.clock.now(),
    )
    # 决策 09-11 的完成时间戳=执行时刻 09-12 09:31 CST；受阻/错过不计入
    assert status["last_success_at"].startswith("2025-09-12T01:31")
    assert day_records["2025-09-12"]["outcome"] == "data_blocked"
    assert day_records["2025-09-15"]["outcome"] == "missed_decision_window"


def test_stop_effective_before_report(pkg):
    """停止：先生效后回报——页面读到的状态不再停留 received。"""
    h = Harness(pkg, make_config())
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    run_id = h.config.ledger_run_id
    h.decide(date(2025, 9, 11))  # 待执行
    h.store.set_stage(
        run_id,
        "_control",
        "control",
        {
            "command": "stop",
            "state": "requested",
            "requested_by": "user",
            "requested_at": h.clock.now().isoformat(),
        },
    )
    r = h.execute(date(2025, 9, 11))
    assert r.outcome == "completed"
    ctl = h.store.get_stage(run_id, "_control", "control")
    assert ctl["state"] == "effective"
    status = h.store.get_status(run_id)
    assert status["stop_restore_status"]["state"] == "effective"
    payload = to_platform_payload(status, control=ctl)
    assert payload["stop_restore"]["job_stop"]["stage"] == "effective"
    assert payload["run_state"] == "paused_job"


def test_reconcile_empty_both_sides_fails():
    """J6R4 #2：账本与复算两侧全空 → fail（不得 ok=true）。"""
    from types import SimpleNamespace

    from backend.services.simulation.virtual_run.recovery import reconcile

    stub = SimpleNamespace(
        package=None,
        export_evidence=lambda: {
            "session": {"initial_cash": 30000.0},
            "orders": [],
            "equity": [],
        },
    )
    out = reconcile(stub)
    assert out["ok"] is False
    assert out["mismatches"][0]["reason"] == "empty_on_both_sides"


def test_reconcile_strict_full_precision_diff(pkg):
    """J7R5：严格判定=全精度值直接相减 ≤1e-6（无 round/format）。"""
    from datetime import date as _d

    from backend.services.simulation.replay.r01_ledger import R01Ledger
    from backend.services.simulation.virtual_run.recovery import reconcile

    cfg = make_config()
    led = R01Ledger(pkg, cfg.to_ledger_config())
    led.run_day(
        _d(2025, 9, 11),
        {"510300.SH": 0.6, "518880.SH": 0.4},
        signal_date=_d(2025, 9, 10),
    )
    led.run_day(_d(2025, 9, 12))
    out = reconcile(led)
    assert out["ok"] is True, out["mismatches"]
    assert out["strict_1e_6"] is True
    assert out["legacy_equity"] is False
    assert out["max_full_precision_diff"] <= 1e-6
    # 全精度对值逐行存在且为数值差（非舍入比较）
    assert all(r["full_precision_diff"] is not None for r in out["rows"])
    assert all(abs(r["full_precision_diff"]) <= 1e-6 for r in out["rows"])


def test_frontier_publish_wait_then_continue(inc_env):
    """H2-AC01 验收场景：仅发布 D 包 → 决策等待 → 再发布下一日所需数据 →
    按冻结的可用时间和窗口继续——不漏决策、不用未来日线、不重复成交；
    晚到超窗按既定政策收口（missed 路径）。

    合成日包（真实 p02 口径 manifest+calendar）：基线为 fixture 冻结包，
    d1/d2 为基线之后的两个开市日（数据行取自基线末日，日期推进）。
    """
    baseline, registry, provider, tmp = inc_env
    d1 = _next_weekday(date.fromordinal(max(baseline.trade_dates()).toordinal() + 1))
    d2 = _next_weekday(date.fromordinal(d1.toordinal() + 1))

    from backend.services.simulation.virtual_run import FrozenClock
    from backend.services.simulation.virtual_run.locks import InMemoryLockBackend
    from backend.services.simulation.virtual_run.pipeline import VirtualRunPipeline
    from backend.services.simulation.virtual_run.recovery import (
        InMemoryCheckpointStore,
    )
    from backend.services.simulation.virtual_run.states import InMemoryRunStateStore

    cfg = make_config()
    clock = FrozenClock()
    h_store, h_cp = InMemoryRunStateStore(), InMemoryCheckpointStore()

    class P:
        """真实 DailyIncrementProvider（注册表可增量发布）。"""

        def __init__(self):
            self._p = provider

        def __getattr__(self, name):
            return getattr(self._p, name)

    pipe = VirtualRunPipeline(
        cfg,
        P(),
        clock=clock,
        lock_backend=InMemoryLockBackend(),
        state_store=h_store,
        checkpoint_store=h_cp,
    )

    # -- 阶段 1：仅发布 d1（取得于 d1 收盘后）→ 次日清晨决策 d1（建仓
    #    信号，真实 DG-006 节奏）→ 执行日 d2 行情未取得 → 等待 ------
    _add_entry(
        registry,
        f"node://test/r01-etf-daily/d{d1.strftime('%Y%m%d')}",
        _write_daily_pkg(tmp, d1, baseline_pkg=baseline),
    )
    assert provider.next_open_trade_date(d1) == d2  # 日历已知 d2（开市日）
    clock.set_shanghai(d2, "08:00")
    r = pipe.run_day(d1)
    assert r.outcome == "waiting_execution_data", r.detail
    rec = h_store.get_day(cfg.ledger_run_id, d1.isoformat())
    assert rec["outcome"] == "waiting_execution_data"
    assert "completed_at" not in rec  # 不计成功
    # 窗口开（09:31）但行情仍未取得：可恢复受阻
    clock.set_shanghai(d2, "09:35")
    r = pipe.run_day(d1)
    assert r.outcome == "execution_data_blocked"
    assert h_store.get_stage(cfg.ledger_run_id, d1.isoformat(), "execute") is None

    # -- 阶段 2：发布 d2（取得于 d2 09:30，窗口内补齐）→ 按冻结窗口继续 --
    _add_entry(
        registry,
        f"node://test/r01-etf-daily/d{d2.strftime('%Y%m%d')}",
        _write_daily_pkg(
            tmp,
            d2,
            baseline_pkg=baseline,
            obtained_at=f"{d2.isoformat()}T01:30:00+00:00",
        ),
    )
    clock.set_shanghai(d2, "09:40")
    r = pipe.run_day(d1)
    assert r.outcome == "completed", r.detail
    ex = h_store.get_stage(cfg.ledger_run_id, d1.isoformat(), "execute")
    assert (
        ex["status"] == "executed"
        and ex["execution"]["execution_date"] == d2.isoformat()
    )
    led = h_cp.load(provider.package, cfg.to_ledger_config())
    st = led.export_checkpoint()
    assert st["executed_dates"] == [d2.isoformat()]
    fills = (
        [f for o in st["orders"].values() for f in o.get("fills", [])]
        if isinstance(next(iter(st["orders"].values()), None), dict)
        else []
    )
    # 不重复成交：重复调度后订单/成交不变
    r2 = pipe.run_day(d1)
    assert r2.outcome == "completed"
    st2 = h_cp.load(provider.package, cfg.to_ledger_config()).export_checkpoint()
    assert st2["orders"] == st["orders"] and st2["cash"] == st["cash"]

    # -- 阶段 3（另一 run）：晚到超窗 → 按冻结策略收口（missed，不补写） --
    cfg_late = make_config()
    clock_l = FrozenClock()
    store_l, cp_l = InMemoryRunStateStore(), InMemoryCheckpointStore()
    provider_l = DailyIncrementProvider(
        str(baseline.root),
        baseline_manifest_sha256=baseline.manifest_sha256,
        registry_path=str(tmp / "registry-late.json"),
        cache_dir=str(tmp / "m2"),
    )
    reg_late = tmp / "registry-late.json"
    reg_late.write_text(json.dumps({"packages": {}}), encoding="utf-8")
    provider_l = DailyIncrementProvider(
        str(baseline.root),
        baseline_manifest_sha256=baseline.manifest_sha256,
        registry_path=str(reg_late),
        cache_dir=str(tmp / "m2"),
    )
    _add_entry(
        reg_late,
        f"node://test/r01-etf-daily/d{d1.strftime('%Y%m%d')}",
        _write_daily_pkg(tmp / "late", d1, baseline_pkg=baseline),
    )
    pipe_l = VirtualRunPipeline(
        cfg_late,
        provider_l,
        clock=clock_l,
        lock_backend=InMemoryLockBackend(),
        state_store=store_l,
        checkpoint_store=cp_l,
    )
    clock_l.set_shanghai(d2, "08:00")
    assert pipe_l.run_day(d1).outcome == "waiting_execution_data"
    clock_l.set_shanghai(d2, "10:05")  # 超窗（09:31+30min）
    r = pipe_l.run_day(d1)
    assert r.outcome == "missed_execution_window"
    ex_l = store_l.get_stage(cfg_late.ledger_run_id, d1.isoformat(), "execute")
    assert ex_l["status"] == "missed_window"
    led_l = cp_l.load(provider_l.package, cfg_late.to_ledger_config())
    assert led_l is None or not led_l.export_checkpoint()["orders"]  # 无成交不补写
