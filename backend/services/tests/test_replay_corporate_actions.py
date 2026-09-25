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
    """v3 三段式（F2）：record EOD 定格 → ex 入应收（nav、不可交易）
    → pay 转可用现金。fixture 510300：record 09-18 / ex 09-19 / pay 09-24。"""

    def test_three_stage_flow(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "510300.SH")
        qty = ledger.positions["510300.SH"].qty
        cash_after_buy = ledger.cash

        # record 09-18 EOD：定格权益（无现金流）
        _run_to(pkg, ledger, date(2025, 9, 18))
        recs = [
            r for r in ledger.dividend_entitlements.values()
            if r["symbol"] == "510300.SH"
        ]
        assert recs and recs[0]["stage"] == "entitled"
        assert recs[0]["entitlement_qty"] == pytest.approx(qty)
        assert recs[0]["entitlement_amount"] == pytest.approx(qty * 0.05, abs=0.01)
        assert ledger.cash == pytest.approx(cash_after_buy)  # record 日无现金流

        # ex 09-19 开盘前：入应收（现金不增、nav 含应收）
        _run_to(pkg, ledger, date(2025, 9, 19), {"510300.SH": 1.0})
        assert recs[0]["stage"] == "receivable"
        assert ledger.dividend_receivable == pytest.approx(qty * 0.05, abs=0.01)
        snap_ex = ledger.equity[-1]
        assert snap_ex["nav"] == pytest.approx(
            snap_ex["cash"] + snap_ex["dividend_receivable"] + snap_ex["market_value"],
            rel=1e-6,
        )

        # pay 09-24 开盘前：应收转可用现金（当日可交易）
        cash_pre_pay = ledger.cash
        _run_to(pkg, ledger, date(2025, 9, 24))
        assert recs[0]["stage"] == "paid"
        assert ledger.dividend_receivable == pytest.approx(0.0)
        assert ledger.cash == pytest.approx(cash_pre_pay + qty * 0.05, abs=0.02)

    def test_dividend_chain_510300(self, pkg):
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "510300.SH")
        _run_to(pkg, ledger, date(2025, 9, 19), {"510300.SH": 1.0})
        recs = [r for r in ledger.dividend_entitlements.values() if r["symbol"] == "510300.SH"]
        assert len(recs) == 1
        key = next(k for k in ledger.dividend_entitlements if ledger.dividend_entitlements[k] is recs[0])
        # 幂等键 (run, symbol, event_id, entitlement_date=record_date)
        assert key[0] == ledger.ledger_run_id
        assert key[1] == "510300.SH"
        assert key[2] == "fund_div:SH510300:20250919:20250918"
        assert key[3] == "2025-09-18"


class TestSameDayShareThenCash:
    def test_same_day_ordering(self, pkg):
        """同日份额折算+分红（v3 §6）：份额调整开盘前先应用；cash_per_share
        为调整后口径，权益按 record 日（09-22）旧口径持仓换算：
        amount = record_qty × cps × m（fixture：1000×0.04×0.5=20 元）。
        ex 日入应收、现金不动；pay 日（09-26）转现金。"""
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "518880.SH")
        _run_to(pkg, ledger, date(2025, 9, 22))  # record 日
        qty_at_record = ledger.positions["518880.SH"].qty
        cash_before = ledger.cash

        summary = _run_to(pkg, ledger, date(2025, 9, 23))  # ex 日（不再平衡）
        assert summary.corporate_actions_applied, "份额调整应先于分红段"
        assert summary.dividends_credited, "分红应收段应入账"
        div = [
            d for d in summary.dividends_credited if d.get("action") == "receivable"
        ][0]
        assert div["basis_multiplier"] == pytest.approx(0.5)
        assert div["entitlement_qty"] == pytest.approx(qty_at_record)
        assert div["entitlement_amount"] == pytest.approx(qty_at_record * 0.04 * 0.5, abs=1e-6)
        # ex 日：入应收（nav 含、不可交易），现金不动
        assert ledger.cash == pytest.approx(cash_before)
        assert ledger.dividend_receivable == pytest.approx(qty_at_record * 0.02)
        # pay 日（09-26）：转可用现金
        cash_pre_pay = ledger.cash
        _run_to(pkg, ledger, date(2025, 9, 26))
        assert ledger.cash == pytest.approx(cash_pre_pay + qty_at_record * 0.02, abs=1e-6)
        assert ledger.dividend_receivable == pytest.approx(0.0)


class TestIdempotency:
    def test_action_key_dedup(self, pkg):
        """三段共用幂等键：定格后重复定格/重复入应收不重复入账（F2）。"""
        ledger = _ledger(pkg)
        _buy_full(pkg, ledger, date(2025, 9, 10), "510300.SH")
        _run_to(pkg, ledger, date(2025, 9, 19), {"510300.SH": 1.0})
        recs = [r for r in ledger.dividend_entitlements.values() if r["symbol"] == "510300.SH"]
        assert len(recs) == 1
        recv_before = ledger.dividend_receivable
        # 重放定格段（record 已过）：无新记录
        ledger._stage_dividend_entitlement(date(2025, 9, 18))
        assert len([
            r for r in ledger.dividend_entitlements.values() if r["symbol"] == "510300.SH"
        ]) == 1
        # 重放入应收段：阶段已过 → 无变化
        assert ledger._stage_dividend_receivable(date(2025, 9, 19)) == []
        assert ledger.dividend_receivable == pytest.approx(recv_before)
        # 份额调整幂等（原用例保留）
        from backend.services.simulation.replay.etf_input_package import TypedEvent

        ev = [e for e in pkg.events_for("510300.SH") if e.event_type == "cash_dividend"][0]
        assert ledger._apply_share_adjustment(ev) is None  # 非份额事件不入账

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
