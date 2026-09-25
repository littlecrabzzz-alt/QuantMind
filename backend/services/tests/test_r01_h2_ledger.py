"""R01P0-J2E1 测试：H2.1-L1..L5 虚拟运行账本（r01vr-）。

- L1 身份：r01vr-<group>-<strategy>-v<version>（无 attempt）、同引擎复用
- L4 跨日延续：两组合不串账；跨分红日（record/ex/pay）重启恢复==连续执行
- 同事件重放不重复成交/分红
- 数据缺失显式失败
- L5 修订分离：rev<date> 独立轨迹，原始轨迹不回填
- L3 配置载体：ORM 元数据 + 行→冻结 config 映射 + 未启用=待启用语义
真实 v2 包 511090 分红窗口（AC-01 同源）+ fixture。
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import (
    build_fixture_package,
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import (
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
    make_ledger_run_id,
    make_revision_run_id,
    make_virtual_run_id,
)

REAL_PKG = "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7"
REAL_SHA = "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"
real_pkg_needed = pytest.mark.skipif(
    not __import__("pathlib").Path(REAL_PKG, "manifest.json").is_file(),
    reason="真实输入包 v2 不在本机",
)
SYM = "511090.SH"
DIV_WINDOW = [date(2024, 4, 23), date(2024, 4, 24), date(2024, 4, 25), date(2024, 4, 26), date(2024, 4, 29)]


@pytest.fixture(scope="module")
def pkg():
    return load_etf_input_package(REAL_PKG, expect_manifest_sha256=REAL_SHA)


def _vcfg(group="A", strategy="etf-vr-demo", version=1, **kw):
    kw.setdefault("initial_cash", 30000.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(
        group=group, strategy_id=strategy, strategy_version=version,
        execution_attempt_id=1, run_kind="virtual", **kw,
    )


def _run_virtual_days(led, pkg, days, weights=None, seed_date=None, seed_qty=100):
    """种子买入（seed_date 精确数量）后逐日推演。"""
    if seed_date is not None:
        o = led.submit_order(seed_date, SYM, "buy", seed_qty)
        bars = pkg.load_date(seed_date)
        led._validate_and_execute(o, seed_date, bars, DaySummary(trade_date=seed_date.isoformat()))
        led._eod(seed_date, bars, DaySummary(trade_date=seed_date.isoformat()))
    weights = weights or {}
    for d in days:
        if led._last_trade_date is not None and d <= led._last_trade_date:
            continue
        led.run_day(d, weights.get(d))
    return led


# ---------------------------------------------------------------------------
# L1：身份
# ---------------------------------------------------------------------------


class TestVirtualIdentity:
    def test_run_id_format_no_attempt(self):
        cfg = _vcfg()
        assert cfg.ledger_run_id == "r01vr-A-etf-vr-demo-v1"
        assert "-a0001" not in cfg.ledger_run_id  # 无 attempt 段（单轨迹）
        assert make_virtual_run_id("B1", "s", 3) == "r01vr-B1-s-v3"

    def test_version_change_new_trajectory_not_overwrite(self):
        """版本变更 ⇒ 新 r01vr run（旧轨迹只读保留，不覆盖）。"""
        v1 = _vcfg(version=1)
        v2 = _vcfg(version=2)
        assert v1.ledger_run_id != v2.ledger_run_id

    def test_p0_group_rejected_for_virtual(self):
        with pytest.raises(ValueError, match="P0"):
            _vcfg(group="P0", strategy="fixture-x")

    def test_research_identity_unchanged(self):
        cfg = R01LedgerConfig(
            group="A", strategy_id="s", strategy_version=1,
            execution_attempt_id=2, initial_cash=30000.0,
        )
        assert cfg.ledger_run_id == make_ledger_run_id("A", "s", 1, 2)

    @real_pkg_needed
    def test_same_engine_rules_as_research(self, pkg):
        """同一 R01Ledger 引擎：虚拟与研究账本同规则（分红三段式抽查）。"""
        led = R01Ledger(pkg, _vcfg())
        _run_virtual_days(led, pkg, DIV_WINDOW, seed_date=date(2024, 4, 22), seed_qty=100)
        rec = next(iter(led.dividend_entitlements.values()))
        assert rec["stage"] == "paid"
        assert rec["entitlement_amount"] == pytest.approx(150.0)  # 100×1.5
        assert led.dividend_receivable == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# L4：两组合不串账 + 跨分红日重启==连续 + 重放幂等
# ---------------------------------------------------------------------------


class TestTwoGroupsIsolation:
    @real_pkg_needed
    def test_parallel_runs_no_cross_talk(self, pkg):
        a = _run_virtual_days(
            R01Ledger(pkg, _vcfg(group="A")), pkg, DIV_WINDOW,
            seed_date=date(2024, 4, 22), seed_qty=100,
        )
        # B1：2 万本金情景，同买 100 份（1 手）但 04-26 额外减仓 50 份
        # （manual_action），与 A 组形成不同持仓/现金轨迹
        b1 = R01Ledger(pkg, _vcfg(group="B1", initial_cash=20000.0))
        _run_virtual_days(b1, pkg, [date(2024, 4, 23), date(2024, 4, 24)],
                          seed_date=date(2024, 4, 22), seed_qty=100)
        b1.manual_sell(date(2024, 4, 24), SYM, 50, reason="user", requested_by="u")
        _run_virtual_days(b1, pkg, DIV_WINDOW)
        assert a.ledger_run_id != b1.ledger_run_id
        assert a.positions[SYM].qty == 100.0
        assert b1.positions[SYM].qty == 50.0
        # 各自分红按 record 在册定格：A=100×1.5、B1=100×1.5（04-23 收盘
        # 均 100 份；04-24 卖出不消灭权益）——金额相等但独立入账互不串
        a_amt = next(iter(a.dividend_entitlements.values()))["entitlement_amount"]
        b_amt = next(iter(b1.dividend_entitlements.values()))["entitlement_amount"]
        assert a_amt == pytest.approx(150.0)
        assert b_amt == pytest.approx(150.0)
        # 持仓/现金轨迹不同（B1 卖出 50 份），订单键零交集
        assert abs(a.cash - b1.cash) > 1000.0
        ids_a = {o.client_order_id for o in a.orders.values()}
        ids_b = {o.client_order_id for o in b1.orders.values()}
        assert not (ids_a & ids_b)

    @real_pkg_needed
    def test_checkpoints_coexist_by_prefix(self, pkg):
        """r01vr- 与 r01- 检查点同表不同键；restore 各自命中、不互取。"""
        vr = R01Ledger(pkg, _vcfg(strategy="ckpt-prefix"))
        _run_virtual_days(vr, pkg, [date(2024, 4, 23)], seed_date=date(2024, 4, 22), seed_qty=100)
        cp_vr = vr.export_checkpoint()
        research = R01Ledger(pkg, R01LedgerConfig(
            group="A", strategy_id="ckpt-prefix", strategy_version=1,
            execution_attempt_id=1, initial_cash=30000.0, slippage_bps=0.0,
        ))
        _run_virtual_days(research, pkg, [date(2024, 4, 23)], seed_date=date(2024, 4, 22), seed_qty=100)
        cp_re = research.export_checkpoint()
        assert cp_vr["ledger_run_id"].startswith("r01vr-")
        assert cp_re["ledger_run_id"].startswith("r01-")
        # run_id 校验防互取
        with pytest.raises(ValueError, match="ledger_run_id 不匹配"):
            R01Ledger.restore(pkg, _vcfg(strategy="ckpt-prefix"), cp_re)


class TestCrossDayContinuation:
    @real_pkg_needed
    def test_restart_across_dividend_window_equals_continuous(self, pkg):
        """L4 验收：跨分红日（record/ex/pay）崩溃注入恢复 == 连续执行。

        连续：04-22 买入 → 5 日一次跑完；恢复：04-22+04-23 落检查点 →
        restore → 续跑余下日期；逐日 nav/cash/应收/分红段全等。
        """
        cfg = _vcfg(strategy="vr-continuous")
        full = _run_virtual_days(
            R01Ledger(pkg, cfg), pkg, DIV_WINDOW,
            seed_date=date(2024, 4, 22), seed_qty=100,
        )
        part = _run_virtual_days(
            R01Ledger(pkg, cfg), pkg, [date(2024, 4, 23)],
            seed_date=date(2024, 4, 22), seed_qty=100,
        )
        restored = R01Ledger.restore(pkg, cfg, part.export_checkpoint())
        assert restored.ledger_run_id == full.ledger_run_id
        _run_virtual_days(restored, pkg, DIV_WINDOW)  # 续跑（跳过已执行日）
        assert len(restored.equity) == len(full.equity)
        for r, f in zip(restored.equity, full.equity, strict=True):
            assert r["nav"] == pytest.approx(f["nav"], abs=1e-6), f["trade_date"]
            assert r["cash"] == pytest.approx(f["cash"], abs=1e-6)
            assert r["dividend_receivable"] == pytest.approx(f["dividend_receivable"], abs=1e-6)
        assert restored.dividend_entitlements == full.dividend_entitlements
        assert restored.risk.high_water_mark == pytest.approx(full.risk.high_water_mark)

    @real_pkg_needed
    def test_same_event_replay_no_duplicate_fill_or_dividend(self, pkg):
        """同事件重放：同决策日重放被拒（须新轨迹/修订），订单与分红
        幂等键兜底不重复。"""
        led = _run_virtual_days(
            R01Ledger(pkg, _vcfg(strategy="vr-replay")), pkg, DIV_WINDOW,
            seed_date=date(2024, 4, 22), seed_qty=100,
        )
        with pytest.raises(ValueError, match="已执行"):
            led.run_day(date(2024, 4, 29), None)
        # 检查点恢复后重放同日：_executed_dates 随 checkpoint 延续 → 同样拒绝
        restored = R01Ledger.restore(pkg, led.config, led.export_checkpoint())
        with pytest.raises(ValueError, match="已执行"):
            restored.run_day(date(2024, 4, 29), None)
        # 分红三段幂等（F2 已测，此处虚拟轨迹口径复验）
        rec = next(iter(led.dividend_entitlements.values()))
        assert led._stage_dividend_receivable(date(2024, 4, 24)) == []
        assert led._stage_dividend_pay(date(2024, 4, 29)) == []
        assert rec["stage"] == "paid"

    def test_data_missing_explicit_failure(self, tmp_path):
        """数据缺失显式失败：非包交易日/缺行情日不虚构成交。"""
        fx = build_fixture_package(tmp_path / "fx")
        led = R01Ledger(fx, R01LedgerConfig(
            group="A", strategy_id="vr-missing", strategy_version=1,
            execution_attempt_id=1, initial_cash=30000.0, run_kind="virtual",
            slippage_bps=0.0,
        ))
        with pytest.raises(Exception, match="not_trade_date"):
            led.run_day(date(2025, 9, 13))  # 周六
        led.run_day(date(2025, 9, 15), None)  # 正常日先行
        led.run_day(date(2025, 9, 16), {"510300.SH": 0.5})  # fixture 停牌日
        rejects = [o for o in led.orders.values() if o.status == "rejected"]
        assert rejects and rejects[0].reject_reason in ("suspended", "no_quote")


# ---------------------------------------------------------------------------
# L5：修订轨迹分离
# ---------------------------------------------------------------------------


class TestRevisionTrajectory:
    def test_revision_id_format_and_validation(self):
        base = make_virtual_run_id("A", "s", 2)
        assert make_revision_run_id(base, date(2026, 9, 24)) == f"{base}:rev20260924"
        with pytest.raises(ValueError, match="成对"):
            _vcfg(revision_of=base)  # 缺 revision_date
        with pytest.raises(ValueError, match="基轨迹"):
            _vcfg(strategy="other", revision_of=base, revision_date=date(2026, 9, 24))

    @real_pkg_needed
    def test_revision_separate_from_original(self, pkg):
        """补算/修订走独立轨迹：原始向前决策不回填。"""
        base_cfg = _vcfg(strategy="vr-rev")
        original = _run_virtual_days(
            R01Ledger(pkg, base_cfg), pkg, DIV_WINDOW,
            seed_date=date(2024, 4, 22), seed_qty=100,
        )
        orig_equity = [dict(s) for s in original.equity]
        orig_rec = dict(next(iter(original.dividend_entitlements.values())))

        # 修订轨迹：同窗口重放（例如数据修订后的补算）
        rev_cfg = _vcfg(
            strategy="vr-rev",
            revision_of=base_cfg.ledger_run_id,
            revision_date=date(2026, 9, 24),
        )
        assert rev_cfg.ledger_run_id == f"{base_cfg.ledger_run_id}:rev20260924"
        revision = _run_virtual_days(
            R01Ledger(pkg, rev_cfg), pkg, DIV_WINDOW,
            seed_date=date(2024, 4, 22), seed_qty=100,
        )
        # 原始轨迹不被回填（独立对象、独立证据；数值即使相同也是两份记录）
        assert original.ledger_run_id != revision.ledger_run_id
        assert [s["trade_date"] for s in original.equity] == [s["trade_date"] for s in orig_equity]
        assert next(iter(original.dividend_entitlements.values()))["entitlement_amount"] == orig_rec["entitlement_amount"]
        assert original.export_checkpoint()["ledger_run_id"].startswith("r01vr-A-vr-rev-v1")
        assert revision.export_checkpoint()["ledger_run_id"].endswith(":rev20260924")
        # 修订轨迹检查点互不串（restore 按各自 run id）
        with pytest.raises(ValueError):
            R01Ledger.restore(pkg, base_cfg, revision.export_checkpoint())


# ---------------------------------------------------------------------------
# L3：配置载体
# ---------------------------------------------------------------------------


class TestVirtualRunConfigCarrier:
    def test_orm_metadata(self):
        from backend.services.simulation.models.replay import (
            R01VirtualRunConfig,
            R01VirtualRunState,
        )

        assert R01VirtualRunConfig.__tablename__ == "r01_virtual_run_config"
        cols = set(R01VirtualRunConfig.__table__.columns.keys())
        assert {
            "ledger_run_id", "enabled", "strategy_id", "strategy_version",
            "group", "initial_cash", "granularity_check_cash", "risk_config",
            "data_source", "execution_window", "schedule_key",
        } <= cols
        assert R01VirtualRunState.__tablename__ == "r01_virtual_run_state"
        pk = list(R01VirtualRunState.__table__.primary_key.columns.keys())
        assert pk == ["id"]
        uq = [
            c.name for c in R01VirtualRunState.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert "uq_r01vr_state_run_date_stage" in uq

    def test_row_to_frozen_config_defaults(self):
        """runner 消费接口：配置行 → 冻结 config（默认 3 万、损失线默认、
        未配置=待启用由 enabled/schedule_key 语义承载）。"""
        from backend.services.simulation.replay.ledger_persistence import (
            virtual_ledger_config_from_row,
        )

        class _Row:
            ledger_run_id = "r01vr-A-etf-vr-demo-v1"
            enabled = False  # 未启用 → 平台"待启用"，不自动跑
            strategy_id = "etf-vr-demo"
            strategy_version = 1
            group = "A"
            initial_cash = 30000.0
            granularity_check_cash = 20000.0
            risk_config = {}
            data_source = {"package": "node://mac/r01-etf-daily/v2-fcbabbb7"}
            execution_window = {"price_mode": "open"}
            schedule_key = None  # 无调度配置=待启用
            source_plan_ref = None

        row = _Row()
        cfg = virtual_ledger_config_from_row(row)
        assert cfg.ledger_run_id == row.ledger_run_id
        assert cfg.run_kind == "virtual"
        assert cfg.initial_cash == 30000.0
        assert cfg.drawdown_pct == 0.30  # 默认风险线
        assert cfg.slippage_bps == 0.0

        class _RowCustom(_Row):
            risk_config = {"loss_line_amount": 9000.0, "commission_min": 0.1}

        cfg2 = virtual_ledger_config_from_row(_RowCustom())
        assert cfg2.loss_line_amount == 9000.0
        assert cfg2.commission_min == 0.1
