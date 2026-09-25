"""R01 持续虚拟盘（H2.2-R1/R2/R3）流水线测试。

工程口径：全部使用 fixture 输入包（build_fixture_package，2025-09-08..
10-01 共 18 个包交易日，月末 09-30→10-01）+ InMemory 锁/状态/检查点
后端 + FrozenClock 可控时钟。真实日增量包联调（p02 D1/D2）另派。

对齐 h2-interfaces §5 H2.2 验收矩阵：
- 月末信号→次日执行 / 休市日 / 无交易日 / 数据迟到
- 重复任务 / 中途崩溃恢复 / 风险暂停 / 确认恢复
- 补跑/重启与连续运行一致（三对照）
- 收盘信号不倒用当天开盘（四元组+账本强制）
- 无订单日=有证据的有效运行（R2）
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from backend.services.simulation.replay.etf_input_package import (
    EtfInputPackage,
    build_fixture_package,
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import LedgerOrderingError
from backend.services.simulation.virtual_run import (
    FrozenClock,
    VirtualRunConfig,
    VirtualRunPipeline,
)
from backend.services.simulation.virtual_run.gating import StaticPackageProvider
from backend.services.simulation.virtual_run.locks import InMemoryLockBackend
from backend.services.simulation.virtual_run.pipeline import CrashInjection
from backend.services.simulation.virtual_run.recovery import (
    InMemoryCheckpointStore,
    NeedsManualReview,
)
from backend.services.simulation.virtual_run.states import InMemoryRunStateStore

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


class Harness:
    """一套共享后端的运行环境（模拟一个持续运行的节点进程）。"""

    def __init__(
        self,
        pkg: EtfInputPackage,
        config: VirtualRunConfig,
        *,
        late_dates=None,
        blocked_dates=None,
        crash_points=None,
    ):
        self.pkg = pkg
        self.config = config
        self.clock = FrozenClock(
            datetime(2025, 9, 10, 3, 0, tzinfo=__import__("datetime").timezone.utc)
        )
        self.locks = InMemoryLockBackend()
        self.store = InMemoryRunStateStore()
        self.checkpoints = InMemoryCheckpointStore()
        self.provider = StaticPackageProvider(
            pkg,
            late_dates=set(late_dates or ()),
            blocked_dates=dict(blocked_dates or {}),
        )
        self.schedule_cfg = None

    def pipeline(self, crash_points=None) -> VirtualRunPipeline:
        return VirtualRunPipeline(
            self.config,
            self.provider,
            clock=self.clock,
            lock_backend=self.locks,
            state_store=self.store,
            checkpoint_store=self.checkpoints,
            schedule_cfg=self.schedule_cfg,
            crash_points=set(crash_points or ()),
        )

    def decide(self, day: date, hhmm: str = "15:15"):
        """决策相位：拨到 day 收盘后运行。"""
        self.clock.set_shanghai(day, hhmm)
        return self.pipeline().run_day(day)

    def execute(self, decision_day: date, hhmm: str = "09:31"):
        """执行相位：拨到次一交易日执行窗口运行同一决策日。"""
        exec_day = self.pkg.next_trade_date(decision_day)
        assert exec_day is not None
        self.clock.set_shanghai(exec_day, hhmm)
        return self.pipeline().run_day(decision_day)

    def ledger_state(self) -> dict:
        led = self.checkpoints.load(self.pkg, self.config.to_ledger_config())
        assert led is not None
        return led.export_checkpoint()

    def day_record(self, day: date) -> dict:
        return self.store.get_day(self.config.ledger_run_id, day.isoformat())


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    return build_fixture_package(tmp_path_factory.mktemp("vr-pkg") / "pkg")


@pytest.fixture
def h(pkg) -> Harness:
    return Harness(pkg, make_config())


# ---------------------------------------------------------------------------
# R1：交易日运行流水线
# ---------------------------------------------------------------------------


def test_entry_then_monthly_rebalance_and_daily_review(h: Harness):
    """首日建仓 → 每日审查（无订单）→ 月末信号 → 次日执行（R1/R2）。"""
    # 09-10（周三）首个决策日：建仓信号，未到执行窗口
    r = h.decide(date(2025, 9, 10))
    assert r.outcome == "pending_execute"
    assert r.today_decision["action"] == "entry_pending_execution"

    # 执行相位（09-11 09:31 开盘窗口）
    r = h.execute(date(2025, 9, 10))
    assert r.outcome == "completed"
    rec = h.day_record(date(2025, 9, 10))
    assert rec["today_decision"]["action"] == "entry"
    four = rec["execution"]
    assert four == {
        "signal_date": "2025-09-10",
        "order_decision_date": "2025-09-10",
        "execution_date": "2025-09-11",
        "price_mode": "open",
        "executed": True,
    }
    assert rec["orders_summary"], "建仓日应有订单"
    assert {o["side"] for o in rec["orders_summary"]} == {"buy"}

    # 09-11..09-29 每日审查：无新订单也是有证据的有效运行（R2）
    d = date(2025, 9, 11)
    while d < date(2025, 9, 30):
        if h.pkg.is_trade_date(d):
            r = h.decide(d)
            assert r.outcome == "pending_execute"
            r = h.execute(d)
            assert r.outcome == "completed"
            rec = h.day_record(d)
            assert rec["today_decision"]["action"] == "no_trade"
            assert (
                "monthly_rebalance_not_due" in rec["today_decision"]["no_trade_reason"]
            )
            assert rec["orders_summary"] == []
            assert rec["completed_at"], "无订单日也要有完成证据"
        d = date.fromordinal(d.toordinal() + 1)

    # 09-30 月末信号 → 10-01 执行
    r = h.decide(date(2025, 9, 30))
    assert r.outcome == "pending_execute"
    r = h.execute(date(2025, 9, 30))
    assert r.outcome == "completed"
    rec = h.day_record(date(2025, 9, 30))
    assert rec["today_decision"]["action"] == "rebalance"
    assert rec["execution"]["execution_date"] == "2025-10-01"
    assert rec["orders_summary"], "月末调仓应有订单"

    # 心跳/run_status（§4 字段）
    status = h.store.get_status(h.config.ledger_run_id)
    assert status["input_date"]["decision_date"] == "2025-09-30"
    assert status["today_decision"]["action"] == "rebalance"
    assert status["last_success_at"]
    assert status["last_heartbeat"]
    assert status["next_run_at"] == "pending_activation"  # 无调度配置=待启用
    assert status["nav"] and status["hwm"]
    for k in (
        "positions",
        "cash",
        "dividend_receivable",
        "orders",
        "nav",
        "drawdown",
        "hwm",
        "risk_state",
        "anomalies",
        "pending_actions",
        "stop_restore_status",
    ):
        assert k in status

    # 对账（settle 阶段证据）
    settle = h.store.get_stage(h.config.ledger_run_id, "2025-09-30", "settle")
    assert settle["reconciliation"]["ok"] is True
    assert settle["reconciliation"]["days_compared"] > 0


def test_not_trade_day_and_package_end(h: Harness):
    """休市日（周末）与包末尾（无下一交易日）。"""
    r = h.decide(date(2025, 9, 27))  # 周六
    assert r.outcome == "not_trade_day"
    assert h.day_record(date(2025, 9, 27))["today_decision"]["no_trade_reason"]

    # 包最后一日 10-01：有决策但无下一交易日 → 终态收口（不执行）
    h.decide(date(2025, 9, 30))
    r = h.execute(date(2025, 9, 30))
    assert r.outcome == "completed"
    r = h.decide(date(2025, 10, 1))
    assert (
        r.outcome == "completed"
    )  # 无下一交易日：execute 阶段 no_next_trade_date 收口
    rec = h.day_record(date(2025, 10, 1))
    assert rec["orders_summary"] == []
    ex = h.store.get_stage(h.config.ledger_run_id, "2025-10-01", "execute")
    assert ex["status"] == "no_next_trade_date"


def test_data_blocked_explicit(pkg):
    """数据迟到 → 显式阻塞，不冒充当日已执行（H2.1-D2 消费侧）。"""
    h = Harness(pkg, make_config(), late_dates={date(2025, 9, 12)})
    # 前两天正常建仓
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    h.decide(date(2025, 9, 11))
    h.execute(date(2025, 9, 11))
    st = h.ledger_state()
    assert st["executed_dates"][-1] == "2025-09-12"

    # 09-12 数据迟到：显式受阻
    r = h.decide(date(2025, 9, 12))
    assert r.outcome == "data_blocked"
    assert "data_late" in r.detail
    assert h.day_record(date(2025, 9, 12))["anomalies"]

    # 09-15 决策 → 09-16 执行；补 09-15 无决策估值日（日历连续）
    r = h.decide(date(2025, 9, 15))
    assert r.outcome == "pending_execute"
    r = h.execute(date(2025, 9, 15))
    assert r.outcome == "completed"
    ex = h.store.get_stage(h.config.ledger_run_id, "2025-09-15", "execute")
    assert "2025-09-15" in ex["executed_sessions"]  # 补 session（无订单）
    st = h.ledger_state()
    assert st["executed_dates"] == [
        "2025-09-11",
        "2025-09-12",
        "2025-09-15",
        "2025-09-16",
    ]
    # 阻塞日无任何订单/决策证据
    assert h.day_record(date(2025, 9, 12))["today_decision"]["action"] == "data_blocked"


def test_close_signal_not_same_day_open(pkg):
    """收盘信号不得倒用当天开盘成交：账本层强制 + 四元组证据。"""
    led_pkg = pkg
    from backend.services.simulation.replay.r01_ledger import R01Ledger

    led = R01Ledger(led_pkg, make_config().to_ledger_config())
    with pytest.raises(LedgerOrderingError) as ei:
        led.run_day(date(2025, 9, 11), {SYM_A: 1.0}, signal_date=date(2025, 9, 11))
    assert ei.value.reason == "same_day_signal"

    # 流水线路径：执行日=决策日次一交易日，订单 signal_date=决策日
    h = Harness(pkg, make_config())
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    rec = h.day_record(date(2025, 9, 10))
    assert rec["execution"]["signal_date"] == "2025-09-10"
    assert rec["execution"]["execution_date"] == "2025-09-11"
    st = h.ledger_state()
    assert st["orders"], "entry 应有订单"


# ---------------------------------------------------------------------------
# R3：幂等 / 锁 / 恢复
# ---------------------------------------------------------------------------


def test_duplicate_dispatch_idempotent(h: Harness):
    """重复调度：同日重跑不重复扣款/第二份订单。"""
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    orders_after_first = h.ledger_state()["orders"]
    cash1 = h.ledger_state()["cash"]
    # 同一日重复调度（决策+执行再各跑一遍）
    r2 = h.pipeline().run_day(date(2025, 9, 10))
    assert r2.outcome == "completed"
    st = h.ledger_state()
    assert st["orders"] == orders_after_first
    assert st["cash"] == cash1
    assert (
        len([o for o in st["orders"].values() if o["trade_date"] == "2025-09-11"]) == 2
    )  # 两标的各一笔


def test_double_worker_busy(h: Harness):
    """双 worker：第二持有者拿不到锁，让出且无副作用。"""
    from backend.services.simulation.virtual_run.locks import (
        DayRunLock,
        InMemoryLockBackend,
    )

    be = InMemoryLockBackend()
    l1 = DayRunLock(be, h.config.ledger_run_id, "2025-09-10", ttl_seconds=600)
    assert l1.acquire()
    l2 = DayRunLock(be, h.config.ledger_run_id, "2025-09-10", ttl_seconds=600)
    assert not l2.acquire()
    # TTL 过期后允许接管（崩溃残留）
    be._locks[l1.key] = (be._locks[l1.key][0], 0.0)
    assert l2.acquire()


def _run_window_continuous(h: Harness, days: list[date]) -> dict:
    """连续运行基准：每天决策+执行。"""
    for d in days:
        h.decide(d)
        h.execute(d)
    return h.ledger_state()


CRASH_POINTS = [
    "after_data_check_state",
    "after_freeze_state",
    "after_signal_state",
    "after_risk_state",
    "after_execute_ledger_before_checkpoint",
    "after_execute_checkpoint_before_state",
    "after_settle_state",
]


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_crash_resume_equals_continuous(pkg, crash_point):
    """中途崩溃（各注入点）→ 重启续跑 == 相同输入连续运行（逐字节一致）。"""
    days = [
        date(2025, 9, 10),
        date(2025, 9, 11),
        date(2025, 9, 12),
        date(2025, 9, 15),
        date(2025, 9, 16),
    ]

    base = Harness(pkg, make_config())
    expected = _run_window_continuous(base, days)

    h = Harness(pkg, make_config())
    for d in days:
        # 决策相位（首个崩溃点在决策链上，其余在执行链上）；崩溃注入为
        # 一次性（真实崩溃后重启不会在同一位置再崩）
        h.clock.set_shanghai(d, "15:15")
        try:
            h.pipeline(crash_points={crash_point}).run_day(d)
        except CrashInjection:
            h.pipeline().run_day(d)
        # 执行相位
        exec_day = h.pkg.next_trade_date(d)
        h.clock.set_shanghai(exec_day, "09:31")
        try:
            h.pipeline(crash_points={crash_point}).run_day(d)
        except CrashInjection:
            h.pipeline().run_day(d)
    got = h.ledger_state()
    assert got["equity"] == expected["equity"]
    assert got["orders"] == expected["orders"]
    assert got["cash"] == expected["cash"]
    assert got["positions"] == expected["positions"]
    assert got["executed_dates"] == expected["executed_dates"]


def test_unknown_state_needs_manual_review(h: Harness):
    """阶段标记与账本权威矛盾 → 显式报错，不自动重跑。"""
    h.decide(date(2025, 9, 10))
    # 伪造：execute 标记已执行但账本检查点被回滚（结果不明）
    h.store.set_stage(
        h.config.ledger_run_id,
        "2025-09-10",
        "execute",
        {
            "task_id": f"{h.config.ledger_run_id}:2025-09-10:execute",
            "status": "executed",
            "execution": {"execution_date": "2025-09-11"},
            "orders": [],
        },
    )
    h.checkpoints._states.clear()
    h.clock.set_shanghai(date(2025, 9, 11), "09:31")
    with pytest.raises(NeedsManualReview):
        h.pipeline().run_day(date(2025, 9, 10))


def test_sleep_wake_catchup_equals_continuous(pkg):
    """休眠唤醒：错过数个决策日 → 唤醒后接续，估值日补齐且不补写决策。"""
    days_all = [
        d for d in pkg.trade_dates() if date(2025, 9, 10) <= d <= date(2025, 9, 22)
    ]

    base = Harness(pkg, make_config())
    for d in days_all:
        base.decide(d)
        base.execute(d)
    expected = base.ledger_state()

    h = Harness(pkg, make_config())
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    h.decide(date(2025, 9, 11))
    h.execute(date(2025, 9, 11))
    # 休眠：09-12..09-19 决策窗口全部错过（唤醒后逐日记录 missed）
    h.clock.set_shanghai(date(2025, 9, 22), "15:15")
    for d in [d for d in days_all if date(2025, 9, 12) <= d <= date(2025, 9, 19)]:
        r = h.pipeline().run_day(d)
        assert r.outcome == "missed_decision_window"
        assert (
            h.day_record(d)["today_decision"]["no_trade_reason"]
            == "decision_window_missed"
        )
    # 09-22 恢复决策 → 09-23 执行，自动补 09-15..09-22 无决策估值日
    r = h.decide(date(2025, 9, 22))
    assert r.outcome == "pending_execute"
    r = h.execute(date(2025, 9, 22))
    assert r.outcome == "completed"
    ex = h.store.get_stage(h.config.ledger_run_id, "2025-09-22", "execute")
    for d in [
        "2025-09-15",
        "2025-09-16",
        "2025-09-17",
        "2025-09-18",
        "2025-09-19",
        "2025-09-22",
    ]:
        assert d in ex["executed_sessions"]
    got = h.ledger_state()
    # 无订单期间补 session 与连续运行的每日审查完全一致（同为无订单估值日）
    assert got["equity"] == expected["equity"]
    assert got["orders"] == expected["orders"]
    assert got["cash"] == expected["cash"]


def test_missed_execution_window_skip_and_record(h: Harness):
    """错过执行窗口：默认 skip_and_record，订单不执行、不回填。"""
    h.decide(date(2025, 9, 10))
    # 窗口已过（09-11 16:00 > 09:31+30min）才醒来
    h.clock.set_shanghai(date(2025, 9, 11), "16:00")
    r = h.pipeline().run_day(date(2025, 9, 10))
    assert r.outcome == "missed_execution_window"
    rec = h.day_record(date(2025, 9, 10))
    assert rec["orders_summary"] == []
    assert rec["execution"]["executed"] is False
    # 错过建仓执行且账本从未建立：无任何订单（不伪造）
    assert h.checkpoints.load(h.pkg, h.config.to_ledger_config()) is None
    # 下一决策日照常（09-11 决策＝首个建仓决策 → 09-12 执行）
    r = h.decide(date(2025, 9, 11))
    assert r.outcome == "pending_execute"
    r = h.execute(date(2025, 9, 11))
    assert r.outcome == "completed"
    st = h.ledger_state()
    assert st["executed_dates"] == ["2025-09-12"]
    assert st["orders"]


def test_stop_restore_three_stage(h: Harness):
    """停止/恢复三段：requested→received→effective；仅执行端确认后生效。"""
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    run_id = h.config.ledger_run_id
    now = h.clock.now()

    # 决策已完成、待执行时请求停止：tick 置 received，当日仍安全收口
    r = h.decide(date(2025, 9, 11))
    assert r.outcome == "pending_execute"
    h.store.set_stage(
        run_id,
        "_control",
        "control",
        {
            "command": "stop",
            "state": "requested",
            "requested_by": "user",
            "requested_at": now.isoformat(),
        },
    )
    # 执行完成=安全点 → effective
    r = h.execute(date(2025, 9, 11))
    assert r.outcome == "completed"
    ctl = h.store.get_stage(run_id, "_control", "control")
    assert ctl["state"] == "received" or ctl["state"] == "effective"
    ctl = h.store.get_stage(run_id, "_control", "control")
    assert ctl["state"] == "effective"

    # 已生效：新决策日不再推进
    r = h.decide(date(2025, 9, 12))
    assert r.outcome == "stopped"
    assert h.day_record(date(2025, 9, 12)) is None

    # resume：requested → 新决策日开始前安全点生效 → 恢复运行
    h.store.set_stage(
        run_id,
        "_control",
        "control",
        {
            "command": "resume",
            "state": "requested",
            "requested_by": "user",
            "requested_at": now.isoformat(),
        },
    )
    r = h.decide(date(2025, 9, 12))
    assert r.outcome == "pending_execute"
    ctl = h.store.get_stage(run_id, "_control", "control")
    assert ctl["state"] == "effective" and ctl["command"] == "resume"
    r = h.execute(date(2025, 9, 12))
    assert r.outcome == "completed"


# ---------------------------------------------------------------------------
# 风险链路（H2.2-R5 接线：每日检查/暂停买入/用户确认恢复）
# ---------------------------------------------------------------------------


def _crash_pkg(tmp_path) -> EtfInputPackage:
    """在 fixture 基础上重写收盘价：510300 自 09-12 起连续 8 日 -10%（风险两线
    触发，且月末时 518880 超配产生卖出腿：既定退出仍执行、买入腿 risk_paused）。"""
    import shutil

    import pandas as pd

    src = build_fixture_package(tmp_path / "src-pkg")
    dst = tmp_path / "crash-pkg"
    (dst / "daily").mkdir(parents=True, exist_ok=True)
    (dst / "events").mkdir(parents=True, exist_ok=True)
    crash_dates = {
        date(2025, 9, 12),
        date(2025, 9, 15),
        date(2025, 9, 16),
        date(2025, 9, 17),
        date(2025, 9, 18),
        date(2025, 9, 19),
        date(2025, 9, 22),
        date(2025, 9, 23),
    }
    for sym in [s["code"] for s in src.manifest["symbols"]]:
        df = pd.read_parquet(src.root / "daily" / f"{sym}.parquet")
        rows = []
        cur = None
        for _, r in df.iterrows():
            d = date.fromisoformat(str(r["trade_date"]))
            close = float(r["close"])
            if sym == SYM_A:
                if cur is None:
                    cur = close
                elif d in crash_dates:
                    cur = round(cur * 0.90, 4)
                # 非 crash 日维持已跌后价位（不回跳）
                close = cur
            openp = round(close * 0.999, 4)
            rows.append(
                {
                    "trade_date": str(r["trade_date"]),
                    "open": openp,
                    "high": round(max(openp, close) * 1.003, 4),
                    "low": round(min(openp, close) * 0.997, 4),
                    "close": close,
                    "volume": float(r["volume"]),
                    "amount": round(close * float(r["volume"]), 2),
                    "adj_factor": float(r["adj_factor"]),
                }
            )
        pd.DataFrame(rows).to_parquet(dst / "daily" / f"{sym}.parquet", index=False)
        ev = src.root / "events" / f"{sym}.parquet"
        if ev.is_file():
            shutil.copy(ev, dst / "events" / f"{sym}.parquet")
    manifest = dict(src.manifest)
    manifest["package_id"] = "fixture-vr-crash-pkg"
    (dst / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_etf_input_package(dst)


def test_risk_pause_and_confirm_recovery(tmp_path):
    """本金损失线触发 → 暂停买入 → 月末买入腿拒单 risk_paused → 用户确认恢复。"""
    pkg = _crash_pkg(tmp_path)
    h = Harness(pkg, make_config())
    run_id = h.config.ledger_run_id

    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))  # 建仓：60% 510300 + 40% 518880

    # 下跌期每日审查（无订单），直至风险线触发
    triggered_day = None
    d = date(2025, 9, 11)
    while d <= date(2025, 9, 22) and triggered_day is None:
        if pkg.is_trade_date(d):
            h.decide(d)
            h.execute(d)
            led = h.checkpoints.load(pkg, h.config.to_ledger_config())
            if not led.risk.buys_allowed:
                triggered_day = d
        d = date.fromordinal(d.toordinal() + 1)
    assert triggered_day is not None, "连续 -10% 应触发风险线"
    led = h.checkpoints.load(pkg, h.config.to_ledger_config())
    unconfirmed = [
        e
        for e in led.export_evidence()["risk_state"]["events"]
        if not e.get("confirmed_by")
    ]
    assert unconfirmed, "触发后应有待确认风险事件"
    # 平台状态暴露待处置
    status = h.store.get_status(run_id)
    assert status["risk_state"]["buys_allowed"] is False
    assert status["risk_state"]["unconfirmed_events"]

    # 月末调仓：买入腿被账本拒单 risk_paused（既定卖出仍执行）
    h.decide(date(2025, 9, 30))
    r = h.execute(date(2025, 9, 30))
    assert r.outcome == "completed"
    rec = h.day_record(date(2025, 9, 30))
    assert "risk_paused" in rec["today_decision"]["action"]
    buys = [o for o in rec["orders_summary"] if o["side"] == "buy"]
    sells = [o for o in rec["orders_summary"] if o["side"] == "sell"]
    assert buys and all(o.get("reject_reason") == "risk_paused" for o in buys)
    assert sells and all(o.get("reject_reason") is None for o in sells)

    # 用户逐线确认 → 恢复买入（净值反弹不自动恢复）
    event_ids = [e["risk_event_id"] for e in unconfirmed]
    out = h.pipeline().confirm_risk_events(event_ids, confirmed_by="user-test")
    assert out["buys_allowed"] is True
    status = h.store.get_status(run_id)
    assert status["risk_state"]["buys_allowed"] is True


# ---------------------------------------------------------------------------
# run_status / 调度（无内置默认调度）
# ---------------------------------------------------------------------------


def test_no_implicit_daily_timing(h: Harness):
    """R2：审查日即使价格大幅波动也不产生订单（不暗中变每日择时）。"""
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    for d in [date(2025, 9, 11), date(2025, 9, 12), date(2025, 9, 15)]:
        h.decide(d)
        h.execute(d)
        assert h.day_record(d)["orders_summary"] == []


def test_schedule_none_means_pending_activation(h: Harness):
    h.decide(date(2025, 9, 10))
    h.execute(date(2025, 9, 10))
    status = h.store.get_status(h.config.ledger_run_id)
    assert status["next_run_at"] == "pending_activation"

    h2 = Harness(h.pkg, make_config())
    h2.schedule_cfg = {
        "enabled": True,
        "decision_cutoff": "15:10",
        "timezone_name": "Asia/Shanghai",
    }
    h2.decide(date(2025, 9, 10))
    h2.execute(date(2025, 9, 10))
    status = h2.store.get_status(h2.config.ledger_run_id)
    # J4R2 #5：已启用调度 → 实际下一调度时刻（ISO，含时区），非描述串
    assert status["schedule_enabled"] is True
    assert status["next_run_at"].startswith("2025-09-"), status["next_run_at"]
    assert "+08:00" in status["next_run_at"]
