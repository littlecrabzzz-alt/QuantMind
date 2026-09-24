"""R01-P0.3 测试：风险状态机（ledger-contract §7 / TG-010）。

覆盖：
- 本金损失线（默认 initial×30%：3万=9000、2万=6000）触发与 risk_event_id
- 高点回撤线：HWM 只增不减、回撤 30% 触发
- 两线独立：同日双线两条事件、逐线确认、单线确认不恢复买入
- 确认幂等：同键重放不重复
- 净值反弹不自动解除
- 触发后：买单被拒（risk_paused）、卖出继续
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.replay.risk_state import (
    RiskConfig,
    RiskStateMachine,
    make_risk_confirm_key,
    make_risk_event_id,
)

D1 = date(2025, 9, 10)
D2 = date(2025, 9, 11)
D3 = date(2025, 9, 12)


def _machine(initial=30000.0, loss=None, dd=0.30):
    return RiskStateMachine(
        "r01-A-fixture-demo-v1-a0001",
        RiskConfig(initial_cash=initial, loss_line_amount=loss, drawdown_pct=dd),
    )


class TestLossLine:
    def test_default_loss_line_amounts(self):
        # 默认 initial×30%：3万=9000，2万=6000
        assert _machine(30000).config.resolved_loss_line_amount() == pytest.approx(9000)
        assert _machine(20000).config.resolved_loss_line_amount() == pytest.approx(6000)

    def test_trigger_at_threshold(self):
        # dd 线取 50% 以分离两线（默认 30%/30% 在 HWM=initial 时重合）
        m = _machine(30000, dd=0.5)
        # nav 21001 > 21000（=30000−9000）不触发
        assert m.on_eod(21001.0, D1) == []
        # nav 21000 ≤ 21000 触发
        events = m.on_eod(21000.0, D2)
        assert len(events) == 1
        ev = events[0]
        assert ev.risk_line == "loss_line"
        assert ev.risk_event_id == make_risk_event_id(m.ledger_run_id, D2, "loss_line")
        assert ev.threshold == pytest.approx(21000.0)
        assert m.status == "paused"
        assert not m.buys_allowed

    def test_run_level_configurable(self):
        m = _machine(30000, loss=5000, dd=0.5)
        events = m.on_eod(25000.0, D1)  # 30000−5000=25000 → 触发
        assert len(events) == 1 and events[0].risk_line == "loss_line"

    def test_same_day_same_line_idempotent(self):
        m = _machine(30000, dd=0.5)
        assert len(m.on_eod(20000.0, D1)) == 1
        assert m.on_eod(20000.0, D1) == []  # 同日同线不重复
        assert len(m.events) == 1


class TestDrawdownLine:
    def test_hwm_only_increases(self):
        m = _machine(30000)
        m.on_eod(35000.0, D1)
        assert m.high_water_mark == pytest.approx(35000)
        m.on_eod(30000.0, D2)
        assert m.high_water_mark == pytest.approx(35000)  # 只增不减

    def test_drawdown_trigger(self):
        m = _machine(30000)
        m.on_eod(40000.0, D1)  # HWM=40000；回撤线=40000×0.7=28000
        assert m.on_eod(28001.0, D2) == []
        events = m.on_eod(28000.0, D3)
        assert len(events) == 1
        assert events[0].risk_line == "drawdown_line"
        assert events[0].threshold == pytest.approx(28000.0)
        assert not m.buys_allowed

    def test_new_high_prevents_drawdown_same_day(self):
        # 新高当日不可能触发回撤（HWM 先更新）
        m = _machine(30000)
        assert m.on_eod(50000.0, D1) == []


class TestBothLines:
    def test_double_trigger_two_events(self):
        m = _machine(30000)
        m.on_eod(40000.0, D1)  # HWM=40000
        # nav=20000：≤21000（loss）且 ≤28000（dd）→ 两条独立事件
        events = m.on_eod(20000.0, D2)
        assert sorted(e.risk_line for e in events) == ["drawdown_line", "loss_line"]
        ids = {e.risk_event_id for e in events}
        assert len(ids) == 2

    def test_two_confirmations_required(self):
        m = _machine(30000)
        m.on_eod(40000.0, D1)
        events = m.on_eod(20000.0, D2)
        assert len(events) == 2
        # 确认第一条：仍暂停
        m.confirm(events[0].risk_event_id, confirmed_by="u1", confirmed_at="2025-09-12T00:00:00Z", nav_at_confirm=20000)
        assert not m.buys_allowed
        assert m.status == "paused"
        # 确认第二条：恢复
        m.confirm(events[1].risk_event_id, confirmed_by="u1", confirmed_at="2025-09-12T00:00:00Z", nav_at_confirm=20000)
        assert m.buys_allowed
        assert m.status == "active"


class TestConfirmationIdempotency:
    def test_confirm_key_format(self):
        key = make_risk_confirm_key("run1", "run1:2025-09-10:loss_line")
        assert key == "run1:risk-confirm:run1:2025-09-10:loss_line"

    def test_double_confirm_same_event(self):
        m = _machine(30000, dd=0.5)
        (ev,) = m.on_eod(20000.0, D1)
        first = m.confirm(ev.risk_event_id, confirmed_by="u1", confirmed_at="t1", nav_at_confirm=20000)
        second = m.confirm(ev.risk_event_id, confirmed_by="u2", confirmed_at="t2", nav_at_confirm=21000)
        # 幂等：首次确认信息保留，不被覆盖
        assert first.confirmed_by == "u1" and first.confirmed_at == "t1"
        assert second.confirmed_by == "u1"
        assert second.confirmed_at == "t1"
        assert second.nav_at_confirm == 20000

    def test_unknown_event_rejected(self):
        m = _machine(30000)
        with pytest.raises(KeyError):
            m.confirm("bogus", confirmed_by="u1", confirmed_at="t", nav_at_confirm=0)


class TestNoAutoResume:
    def test_nav_rebound_does_not_lift_pause(self):
        # dd=0.5 分离两线：loss 阈 21000，dd 阈随 HWM 变化
        m = _machine(30000, dd=0.5)
        m.on_eod(20000.0, D1)  # 触发 loss_line（20000≤21000；dd 阈 15000 未及）
        # 净值大幅反弹回线上方
        m.on_eod(35000.0, D2)
        assert not m.buys_allowed
        assert m.status == "paused"
        # 反弹抬高 HWM 后再度深跌：回撤线新触发（反弹不解除、只记新触发）
        events = m.on_eod(17000.0, D3)  # 35000×0.5=17500 → dd 触发
        assert any(e.risk_line == "drawdown_line" for e in events)
        assert not m.buys_allowed
        # 已有未确认触发的线不逐日重复累积确认义务
        assert len(m.on_eod(16000.0, date(2025, 9, 13))) == 0
        assert sum(1 for e in m.events.values() if not e.confirmed) == 2

    def test_blocked_orders_audited_on_event(self):
        m = _machine(30000, dd=0.5)
        (ev,) = m.on_eod(20000.0, D1)
        m.record_blocked_order(
            ev.risk_event_id,
            {"client_order_id": "x", "symbol": "510300.SH", "qty": 100},
        )
        assert len(m.events[ev.risk_event_id].blocked_orders) == 1

    def test_to_dict_roundtrip_fields(self):
        m = _machine(20000)
        m.on_eod(13000.0, D1)
        data = m.to_dict()
        assert data["config"]["loss_line_amount"] == pytest.approx(6000)
        assert data["status"] == "paused"
        assert data["events"][0]["risk_line"] == "loss_line"
