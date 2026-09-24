"""R01-P0.3 测试：研究账本公司行动 typed 事件处理（ledger-contract §5-§6 / DG-005）。

覆盖：
- 份额调整开盘前（先于撮合）：qty×multiplier、成本基准同比例调整、不动现金
- 现金分红 EOD（先于 nav）：cash += qty×cash_per_share
- 同日并存：先份额后现金（cash_per_share 已是调整后份额口径）
- 幂等键 (ledger_run_id, symbol, event_date, event_type)：重放不重复计入
- 回归用例：159934.SZ 2025-09-22 qty×0.9481；510500.SZ 冻结倍率 0.2803；
  510300.SH 分红链现金一致性
- 无事件重放同日不重复入账（run_day 幂等保护）
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import build_fixture_package
from backend.services.simulation.replay.r01_ledger import (
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
)


@pytest.fixture()
def pkg(tmp_path):
    return build_fixture_package(tmp_path / "pkg")


def _ledger(pkg, *, initial=100000.0, attempt=1):
    return R01Ledger(
        pkg,
        R01LedgerConfig(
            group="P0",
            strategy_id="fixture-ca-demo",
            strategy_version=1,
            execution_attempt_id=attempt,
            initial_cash=initial,
            slippage_bps=0.0,
        ),
    )


def _buy_full(pkg, ledger, trade_date, symbol, weight=1.0):
    return ledger.run_day(trade_date, {symbol: weight})


def _run_to(pkg, ledger, target_date, weights=None):
    """从上一执行日之后逐日推进到 target_date（W2E3 起账本强制不跳日，
    测试必须按包交易日历逐日 run_day；中间日 None 权重）。"""
    start = ledger._last_trade_date
    summary = None
    for d in pkg.trade_dates():
        if start is not None and d <= start:
            continue
        if d > target_date:
            break
        summary = ledger.run_day(d, weights if d == target_date else None)
    return summary


class TestShareAdjustment:
    def test_qty_multiplier_and_cost_basis(self, pkg):
        ledger = _ledger(pkg)
        # 2025-09-10 建仓 159934.SZ（T+0 品种）
        _buy_full(pkg, ledger, date(2025, 9, 10), "159934.SZ")
        pos = ledger.positions["159934.SZ"]
        qty_before = pos.qty
        cost_before = pos.avg_cost

        # 2025-09-22 份额折算（DG-005 冻结值 0.9481）；事件日不再平衡，
        # 隔离验证公司行动本身（逐日推进，不跳日）
        summary = _run_to(pkg, ledger, date(2025, 9, 22))
        pos = ledger.positions["159934.SZ"]
        assert pos.qty == pytest.approx(qty_before * 0.9481)
        assert pos.avg_cost == pytest.approx(cost_before / 0.9481)
        # 不动现金（份额调整）
        ca = [c for c in summary.corporate_actions_applied if c["symbol"] == "159934.SZ"]
        assert ca and ca[0]["cash_delta"] == 0.0

        # 价值守恒：折算前后（以当日开盘附近价格）份额×成本 不变
        assert pos.qty * pos.avg_cost == pytest.approx(qty_before * cost_before, rel=1e-6)

    def test_510500_regression_multiplier(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 15), "510500.SH")
        qty_before = ledger.positions["510500.SH"].qty
        # fixture 把 2015-04-15 冻结倍率 0.2803 放在 2025-09-18
        _run_to(pkg, ledger, date(2025, 9, 18))
        assert ledger.positions["510500.SH"].qty == pytest.approx(qty_before * 0.2803)

    def test_applies_before_open_no_cash_effect(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "159934.SZ")
        _run_to(pkg, ledger, date(2025, 9, 22))
        # 事件日不再平衡：现金严格不变（份额调整不动现金）
        ca = ledger.corporate_action_log[-1]
        assert ca["cash_delta"] == 0.0
        assert ca["qty_after"] == pytest.approx(ca["qty_before"] * 0.9481)


class TestCashDividend:
    def test_dividend_credited_eod_before_nav(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "510300.SH")
        qty = ledger.positions["510300.SH"].qty

        # 2025-09-19 除息日（fixture：每份 0.05 元）
        summary = _run_to(pkg, ledger, date(2025, 9, 19), {"510300.SH": 1.0})
        credited = summary.dividends_credited
        assert credited and credited[0]["symbol"] == "510300.SH"
        expected = round(qty * 0.05, 4)
        assert credited[0]["cash_delta"] == pytest.approx(expected, abs=0.01)
        # 现金确实入账（当日无交易时差额=分红）
        # 注：当日或有调仓费用；分红记录本身对账
        assert credited[0]["qty"] == pytest.approx(qty)

    def test_dividend_chain_510300(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "510300.SH")
        # 持有跨除息日，dividend_log 记录幂等键完整
        _run_to(pkg, ledger, date(2025, 9, 19), {"510300.SH": 1.0})
        recs = [d for d in ledger.dividend_log if d["symbol"] == "510300.SH"]
        assert len(recs) == 1
        key = recs[0]["idempotency_key"]
        assert key[1:] == ["510300.SH", "2025-09-19", "cash_dividend"]


class TestSameDayShareThenCash:
    def test_same_day_ordering(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "518880.SH")
        qty_before = ledger.positions["518880.SH"].qty
        cash_before = ledger.cash
        # 2025-09-23：先份额折算 ×0.5，后现金分红 0.04（调整后口径）；
        # 事件日不再平衡，隔离验证时序
        summary = _run_to(pkg, ledger, date(2025, 9, 23))
        assert summary.corporate_actions_applied, "份额调整应先于分红"
        assert summary.dividends_credited, "现金分红应入账"

        div = summary.dividends_credited[0]
        # 分红按调整后份额计：qty_after_adjust × 0.04
        assert div["qty"] == pytest.approx(qty_before * 0.5)
        assert div["cash_delta"] == pytest.approx(qty_before * 0.5 * 0.04, abs=0.01)
        # 事件日不再平衡 → 现金变动恰为分红
        assert ledger.cash == pytest.approx(cash_before + qty_before * 0.5 * 0.04, abs=1e-6)


class TestIdempotency:
    def test_action_key_dedup(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "510300.SH")
        _run_to(pkg, ledger, date(2025, 9, 19), {"510300.SH": 1.0})
        # 重复应用同一事件（模拟重放）→ 幂等拒绝
        from backend.services.simulation.replay.etf_input_package import TypedEvent

        ev = [e for e in pkg.events_for("510300.SH") if e.event_type == "cash_dividend"][0]
        assert ledger._apply_cash_dividend(ev, ev.event_date) is None
        assert ledger._apply_share_adjustment(ev) is None  # 非份额事件同键族也已占用

    def test_run_day_same_date_rejected(self, pkg):
        ledger = _ledger(pkg)
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 1.0})
        with pytest.raises(ValueError, match="已执行"):
            ledger.run_day(date(2025, 9, 10), {"510300.SH": 1.0})

    def test_new_attempt_new_run_id_no_inheritance(self, pkg):
        l1 = _ledger(pkg, attempt=1)
        l2 = _ledger(pkg, attempt=2)
        assert l1.ledger_run_id != l2.ledger_run_id
        assert "a0001" in l1.ledger_run_id and "a0002" in l2.ledger_run_id
        # 新 attempt 不继承旧订单键
        assert l2.orders == {}


class TestOrderStateMachine:
    def test_partial_fill_then_expired_unfilled(self, pkg):
        # 现金约束制造部分成交：显式提交超过现金承受力的目标订单
        ledger = _ledger(pkg, initial=2500.0)
        d = date(2025, 9, 10)
        bars = pkg.load_date(d)
        order = ledger.submit_order(d, "510300.SH", "buy", 100000)
        summary = DaySummary(trade_date=d.isoformat())
        ledger._validate_and_execute(order, d, bars, summary)
        assert order.status == "partially_filled"
        assert 0 < order.qty_filled < order.qty_target
        assert order.qty_remaining == order.qty_target - order.qty_filled
        # EOD 收口：剩余量转 expired_unfilled，不隔日挂单
        ledger._eod(d, bars, summary)
        assert order.status == "expired_unfilled"
        assert order.qty_remaining > 0
        assert ledger.cash >= 0

    def test_reject_reasons_audited(self, pkg):
        ledger = _ledger(pkg)
        # 2025-09-16 fixture 停牌日：显式拒单
        ledger.run_day(date(2025, 9, 16), {"510300.SH": 0.5})
        rejected = [o for o in ledger.orders.values() if o.status == "rejected"]
        assert rejected
        assert rejected[0].reject_reason in (
            "no_quote", "suspended", "limit_hit", "insufficient_cash",
            "risk_paused", "lot_inexpressible", "stale_price",
        )

    def test_status_lifecycle_fields(self, pkg):
        ledger = _ledger(pkg)
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 1.0})
        # fixture 09-10 开盘 4.012：原始目标 24925 份 → 整手成交 24900，
        # 余 25 转 expired_unfilled（部分成交当日收口，ledger-contract §4）
        o = ledger.orders[
            f"{ledger.ledger_run_id}:2025-09-10:510300.SH:buy"
        ]
        assert o.qty_filled == 24900
        assert o.qty_remaining == 50
        assert o.status == "expired_unfilled"
        assert o.avg_fill_price > 0
        assert o.fills[0].stamp_duty == 0.0  # ETF 无印花税
        assert o.fills[0].transfer_fee == 0.0
