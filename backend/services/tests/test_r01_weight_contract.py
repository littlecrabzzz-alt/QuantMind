"""R01-P0.3 测试：权重契约与账本验收（ledger-contract §9 / DG-001 / TG-004 / TG-010 / TG-012）。

覆盖：
- 2 万 / 3 万本金：ideal_weight vs realized_weight（国债高价低手数粗粒度）
- 残余现金计息 0% 计入 nav（不虚置）
- 独立复算：从原始明细（fills+公司行动+分红+包收盘价）重算现金/净值
  逐日对齐（ledger-contract §9）
- 确定性：同一定义+同一包两次运行（不同 attempt）账务结果一致（TG-012）
- 同订单重试不重复成交（client_order_id 幂等）
- 六组并行会话隔离：互不串账
- 风险线全流程：触线→买入被拒（risk_paused）→既定卖出执行→逐线确认→恢复
- 禁止追加资金（initial_cash 锁定）
- fixture 显著标注：不进策略收益排行
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import build_fixture_package
from backend.services.simulation.replay.r01_ledger import (
    R01Ledger,
    R01LedgerConfig,
    independent_recompute,
    make_ledger_run_id,
)


@pytest.fixture()
def pkg(tmp_path):
    return build_fixture_package(tmp_path / "pkg")


def _config(
    *,
    group="P0",
    strategy_id="fixture-weight-demo",
    initial=30000.0,
    attempt=1,
    loss_line=None,
    dd=0.30,
    slippage=0.0,
):
    return R01LedgerConfig(
        group=group,
        strategy_id=strategy_id,
        strategy_version=1,
        execution_attempt_id=attempt,
        initial_cash=initial,
        loss_line_amount=loss_line,
        drawdown_pct=dd,
        slippage_bps=slippage,
    )


def _run_scenario(pkg, config, days_weights):
    """按 [(date, weights|None)] 序列推演，返回 ledger。"""
    ledger = R01Ledger(pkg, config)
    for d, w in days_weights:
        ledger.run_day(d, w)
    return ledger


class TestWeightContract:
    def test_treasury_lot_granularity_2w(self, pkg):
        # 2 万本金：511010 价格 ~107 → 单手 ~10700（占本金 53%）
        ledger = _run_scenario(
            pkg,
            _config(initial=20000.0),
            [(date(2025, 9, 10), {"511010.SH": 0.35})],
        )
        order = ledger.orders[
            f"{ledger.ledger_run_id}:2025-09-10:511010.SH:buy"
        ]
        # 0.35×20000=7000 < 10700 → 零手 → 无成交（lot_inexpressible 留痕）
        assert order.status == "rejected"
        assert order.reject_reason == "lot_inexpressible"
        assert order.ideal_weight == 0.35
        snap = ledger.equity[-1]
        # 残余现金计入 nav、计息 0（无持仓 → nav=现金=本金）
        assert snap["nav"] == pytest.approx(20000.0)

    def test_treasury_lot_granularity_3w(self, pkg):
        # 3 万本金：0.35×30000=10500 <10700 仍不可表达；0.4 → 1 手
        ledger = _run_scenario(
            pkg,
            _config(initial=30000.0),
            [(date(2025, 9, 10), {"511010.SH": 0.40})],
        )
        order = ledger.orders[
            f"{ledger.ledger_run_id}:2025-09-10:511010.SH:buy"
        ]
        # 原始目标 112 份，整手可表达 100 份：部分成交后剩余 12 份
        # 当日收盘转 expired_unfilled（ledger-contract §4，不隔日挂单）
        assert order.status == "expired_unfilled"
        assert order.qty_filled == 100
        assert order.qty_remaining == 12
        snap = ledger.equity[-1]
        # ideal=0.40；realized=100×close/nav（DG-001 粗粒度偏差入证据）
        assert order.ideal_weight == pytest.approx(0.40)
        realized = order.realized_weight
        assert realized is not None
        assert 0.3 < realized < 0.45
        # 残余现金（含费用）计入 nav
        assert snap["cash"] > 0
        assert snap["nav"] == pytest.approx(snap["cash"] + snap["market_value"], rel=1e-6)

    def test_residual_cash_earns_zero_interest(self, pkg):
        days = [
            (date(2025, 9, 10), {"510300.SH": 0.5, "511010.SH": 0.3}),
            (date(2025, 9, 11), None),
            (date(2025, 9, 12), None),
            (date(2025, 9, 15), None),
        ]
        ledger = _run_scenario(pkg, _config(initial=30000.0), days)
        # 无交易日现金严格不变（计息 0%）
        cash_d1 = ledger.equity[0]["cash"]
        for snap in ledger.equity[1:]:
            assert snap["cash"] == pytest.approx(cash_d1)

    def test_ideal_vs_realized_recorded(self, pkg):
        ledger = _run_scenario(
            pkg,
            _config(initial=30000.0),
            [(date(2025, 9, 10), {"510300.SH": 0.3, "518880.SH": 0.3})],
        )
        for order in ledger.orders.values():
            assert order.ideal_weight is not None
            assert order.realized_weight is not None
            # realized 与成交金额/nav 相符
            if order.status == "filled":
                snap = ledger.equity[-1]
                pos = ledger.positions.get(order.symbol)
                if pos:
                    expected = pos.qty * snap["positions"][order.symbol]["close"] / snap["nav"]
                    assert order.realized_weight == pytest.approx(expected, abs=1e-4)


class TestIndependentRecompute:
    def test_full_scenario_alignment(self, pkg):
        # 完整场景：建仓→停牌日→分红→折算→同日双事件→调仓
        days = [
            (date(2025, 9, 10), {"510300.SH": 0.4, "511010.SH": 0.3, "518880.SH": 0.3}),
            (date(2025, 9, 11), None),
            (date(2025, 9, 12), None),
            (date(2025, 9, 15), None),
            (date(2025, 9, 16), {"510300.SH": 0.4, "511010.SH": 0.3, "518880.SH": 0.3}),  # 停牌日
            (date(2025, 9, 17), {"510300.SH": 0.4, "511010.SH": 0.3, "518880.SH": 0.3}),
            (date(2025, 9, 18), None),  # 510500 折算（未持有）
            (date(2025, 9, 19), None),  # 510300 分红
            (date(2025, 9, 22), None),  # 159934 折算（未持有）
            (date(2025, 9, 23), {"510300.SH": 0.5, "518880.SH": 0.5}),  # 同日双事件+调仓
            (date(2025, 9, 24), {"510300.SH": 0.2, "511010.SH": 0.6}),
        ]
        ledger = _run_scenario(pkg, _config(initial=30000.0), days)
        evidence = ledger.export_evidence()
        recomputed = independent_recompute(evidence, package=pkg)
        assert len(recomputed) == len(ledger.equity)
        for rec, snap in zip(recomputed, ledger.equity, strict=True):
            assert rec["trade_date"] == snap["trade_date"], f"日期错位 {rec} {snap}"
            assert rec["cash"] == pytest.approx(
                snap["cash"], abs=0.01
            ), f"{snap['trade_date']} cash 复算不一致"
            assert rec["nav"] == pytest.approx(
                snap["nav"], abs=0.01
            ), f"{snap['trade_date']} nav 复算不一致"


class TestDeterminism:
    def test_two_attempts_identical_accounting(self, pkg):
        days = [
            (date(2025, 9, 10), {"510300.SH": 0.5, "518880.SH": 0.3}),
            (date(2025, 9, 19), {"510300.SH": 0.2}),
            (date(2025, 9, 23), {"518880.SH": 0.4}),
        ]
        l1 = _run_scenario(pkg, _config(attempt=1), days)
        l2 = _run_scenario(pkg, _config(attempt=2), days)
        e1, e2 = l1.export_evidence(), l2.export_evidence()

        def _strip_run_ids(node):
            if isinstance(node, dict):
                return {
                    k: _strip_run_ids(v)
                    for k, v in node.items()
                    if k not in ("client_order_id", "ledger_run_id", "idempotency_key")
                }
            if isinstance(node, list):
                return [_strip_run_ids(x) for x in node]
            return node

        # 账务部分逐项一致（运行标识随 attempt 变化，其余账务字段必须
        # 一致，TG-012）
        assert _strip_run_ids(e1["orders"]) == _strip_run_ids(e2["orders"])
        for key in ("equity", "corporate_actions", "dividends"):
            assert _strip_run_ids(e1[key]) == _strip_run_ids(e2[key]), f"{key} 不一致"
        assert l1.ledger_run_id != l2.ledger_run_id

    def test_run_id_format(self):
        rid = make_ledger_run_id("B1", "strat-x", 2, 3)
        assert rid == "r01-B1-strat-x-v2-a0003"


class TestOrderIdempotency:
    def test_same_order_retry_no_duplicate_fill(self, pkg):
        ledger = R01Ledger(pkg, _config(initial=30000.0))
        d = date(2025, 9, 10)
        bars = pkg.load_date(d)
        from backend.services.simulation.replay.r01_ledger import DaySummary

        order = ledger.submit_order(d, "510300.SH", "buy", 1000)
        ledger._validate_and_execute(order, d, bars, DaySummary(trade_date=d.isoformat()))
        cash_after = ledger.cash
        # 同 client_order_id 重试 → 返回原订单，不产生第二笔成交
        again = ledger.submit_order(d, "510300.SH", "buy", 1000)
        assert again is order
        assert len(order.fills) == 1
        assert ledger.cash == pytest.approx(cash_after)
        buys = [
            o for o in ledger.orders.values()
            if o.symbol == "510300.SH" and o.side == "buy"
        ]
        assert len(buys) == 1

    def test_same_day_same_symbol_side_single_order(self, pkg):
        # 月频再平衡同一 symbol 同日同方向只允许一笔目标订单
        ledger = R01Ledger(pkg, _config(initial=30000.0))
        o1 = ledger.submit_order(date(2025, 9, 10), "510300.SH", "buy", 1000)
        o2 = ledger.submit_order(date(2025, 9, 10), "510300.SH", "buy", 999)
        assert o1 is o2


class TestSixGroupIsolation:
    def test_parallel_sessions_no_cross_talk(self, pkg):
        days = [
            (date(2025, 9, 10), {"510300.SH": 0.5}),
            (date(2025, 9, 19), {"510300.SH": 0.1}),  # 分红日调仓
        ]
        ledgers = {}
        for group, initial in (
            ("A", 30000.0), ("B1", 30000.0), ("B2", 20000.0),
            ("B3", 30000.0), ("D", 30000.0), ("N", 30000.0),
        ):
            ledgers[group] = _run_scenario(
                pkg, _config(group=group, strategy_id=f"fixture-{group.lower()}-demo", initial=initial), days
            )
        # 各自 initial_cash、互不串账
        for group, ledger in ledgers.items():
            expected_initial = 30000.0 if group != "B2" else 20000.0
            assert ledger.config.initial_cash == expected_initial
            navs = [s["nav"] for s in ledger.equity]
            assert all(0 < n < expected_initial * 1.5 for n in navs)
            # B2（2 万）与 A（3 万）净值轨迹不同（本金隔离可见）
        assert ledgers["A"].equity[0]["nav"] != ledgers["B2"].equity[0]["nav"]
        # 订单键不冲突
        ids_a = {o.client_order_id for o in ledgers["A"].orders.values()}
        ids_b2 = {o.client_order_id for o in ledgers["B2"].orders.values()}
        assert not (ids_a & ids_b2)


class TestRiskIntegration:
    def test_full_risk_flow(self, pkg):
        # 构造触发：1.5 万本金、止损线默认 30%（4500 → nav≤10500 触发）
        ledger = R01Ledger(
            pkg,
            _config(initial=15000.0, strategy_id="fixture-risk-demo", dd=0.5),
        )
        # 建仓后人为把账本打到线下（直接改现金模拟亏损——工程手段）
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.8})
        ledger.cash -= 5000.0  # 工程注记：模拟亏损使 nav 跌破损失线
        summary = ledger.run_day(date(2025, 9, 11), None)
        # 触发 loss_line（dd=0.5 分离两线）
        assert any(
            e["risk_line"] == "loss_line" for e in summary.risk_events
        ), "本金损失线应触发"
        assert ledger.risk.status == "paused"
        assert not ledger.risk.buys_allowed

        # 买入被拒（risk_paused），既定卖出继续有效
        ledger.run_day(date(2025, 9, 12), {"510300.SH": 0.0})  # 全退（卖出）
        sells = [
            o for o in ledger.orders.values()
            if o.side == "sell" and o.trade_date == "2025-09-12"
        ]
        assert sells and sells[0].status == "filled"
        ledger.run_day(date(2025, 9, 15), {"510300.SH": 0.5})  # 重入买入
        buys = [
            o for o in ledger.orders.values()
            if o.side == "buy" and o.trade_date == "2025-09-15"
        ]
        assert buys and buys[0].status == "rejected"
        assert buys[0].reject_reason == "risk_paused"
        assert any(
            b["client_order_id"] == buys[0].client_order_id
            for b in ledger.risk_blocked_orders
        )

        # 确认前保持暂停；确认后恢复
        ev = ledger.risk.events[
            f"{ledger.ledger_run_id}:2025-09-11:loss_line"
        ]
        assert not ev.confirmed
        ledger.confirm_risk_event(ev.risk_event_id, confirmed_by="user-1")
        assert ledger.risk.buys_allowed
        ledger.run_day(date(2025, 9, 16), {"510300.SH": 0.5})
        buys2 = [
            o for o in ledger.orders.values()
            if o.side == "buy" and o.trade_date == "2025-09-16"
        ]
        # 2025-09-16 为 fixture 停牌日：显式拒单（suspended），但不再是 risk_paused
        assert buys2 and buys2[0].reject_reason == "suspended"

    def test_deposit_rejected(self, pkg):
        ledger = R01Ledger(pkg, _config(initial=15000.0, strategy_id="fixture-dep-demo"))
        rec = ledger.deposit(10000.0, requested_by="user-1")
        assert rec["accepted"] is False
        assert ledger.cash == pytest.approx(15000.0)
        assert len(ledger.deposit_rejections) == 1

    def test_nav_rebound_no_auto_resume(self, pkg):
        ledger = R01Ledger(
            pkg, _config(initial=15000.0, strategy_id="fixture-rebound-demo", dd=0.5)
        )
        ledger.run_day(date(2025, 9, 10), None)
        ledger.cash -= 6000.0
        ledger.run_day(date(2025, 9, 11), None)
        assert not ledger.risk.buys_allowed
        ledger.cash += 8000.0  # 反弹回线上方
        ledger.run_day(date(2025, 9, 12), None)
        assert not ledger.risk.buys_allowed, "净值反弹不自动解除"


class TestFixtureMarking:
    def test_fixture_banner_and_metadata(self, pkg):
        ledger = _run_scenario(pkg, _config(), [(date(2025, 9, 10), {"510300.SH": 0.5})])
        evidence = ledger.export_evidence()
        assert "FIXTURE" in evidence["banner"]
        assert "不进策略收益排行" in evidence["banner"]
        assert evidence["session"]["is_fixture"] is True
        assert evidence["session"]["strategy_id"].startswith("fixture-")

    def test_p0_group_requires_fixture_prefix(self):
        with pytest.raises(ValueError, match="fixture-"):
            R01LedgerConfig(
                group="P0", strategy_id="real-strategy", strategy_version=1,
                execution_attempt_id=1, initial_cash=30000.0,
            )

    def test_group_validation(self):
        with pytest.raises(ValueError, match="非法运行组别"):
            R01LedgerConfig(
                group="X", strategy_id="fixture-x", strategy_version=1,
                execution_attempt_id=1, initial_cash=30000.0,
            )
