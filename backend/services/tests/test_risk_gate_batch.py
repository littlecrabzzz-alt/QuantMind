"""Batch exposure limits must not suppress explicitly classified reductions."""

from copy import deepcopy

import pytest

from backend.services.trade.runner.risk_gate import RiskGate


def signal(action="BUY_TO_OPEN", volume=1000, price=10):
    return {
        "symbol": "SH600036",
        "action": action.split("_")[0],
        "trade_action": action,
        "price": price,
        "volume": volume,
    }


def apply(signals, account=None, **config):
    return RiskGate.apply(
        signals,
        account or {"total_value": 100000, "drawdown": 0, "positions": {}},
        config,
        {},
    )


def test_batch_reserves_cumulative_exposure_and_preserves_input():
    signals = [signal(), signal()]
    original = deepcopy(signals)
    result = apply(signals)
    assert [s["volume"] for s in result] == [1000, 500]
    assert signals == original


def test_opposite_opening_orders_do_not_net_pending_exposure():
    result = apply([signal(), signal("SELL_TO_OPEN")])
    assert sum(s["price"] * s["volume"] for s in result) == 15000


def test_overweight_close_survives_concentration_and_turnover_limits():
    account = {
        "total_value": 100000,
        "drawdown": -0.10,
        "positions": {"SH600036": {"market_value": 80000}},
    }
    result = apply([signal("SELL_TO_CLOSE", 8000)], account)
    assert result[0]["volume"] == 8000


def test_close_turnover_consumes_opening_budget_without_reducing_close():
    result = apply([signal("SELL_TO_CLOSE", 1900), signal()])
    assert [s["volume"] for s in result] == [1900, 100]


def test_lowercase_close_is_normalized_before_stop_loss():
    result = apply(
        [signal("sell_to_close")],
        {"total_value": 100000, "drawdown": -0.10, "positions": {}},
    )
    assert result[0]["trade_action"] == "SELL_TO_CLOSE"


@pytest.mark.parametrize("key", ["price", "volume"])
@pytest.mark.parametrize("invalid", [None, "bad", float("nan"), float("inf"), -1, 0])
def test_invalid_orders_cannot_pass_or_poison_batch(key, invalid):
    invalid_signal = signal()
    invalid_signal[key] = invalid
    result = apply([invalid_signal, signal()])
    assert len(result) == 1
    assert result[0]["price"] == 10
    assert result[0]["volume"] == 1000


@pytest.mark.parametrize("total_value", [0, -1, float("nan"), float("inf")])
def test_invalid_account_blocks_new_exposure(total_value):
    assert not apply([signal()], {"total_value": total_value, "positions": {}})


def test_pending_close_does_not_release_concentration_capacity():
    account = {
        "total_value": 100000,
        "positions": {"SH600036": {"market_value": 20000}},
    }
    result = apply([signal("SELL_TO_CLOSE"), signal()], account)
    assert [s["trade_action"] for s in result] == ["SELL_TO_CLOSE"]


def test_short_position_uses_absolute_exposure():
    assert not apply(
        [signal("SELL_TO_OPEN")],
        {"total_value": 100000, "positions": {"SH600036": {"market_value": -20000}}},
    )


def test_invalid_limit_cannot_disable_control():
    assert not apply([signal()], max_single_stock_ratio=float("nan"))


def test_conflicting_action_is_rejected():
    s = signal("BUY_TO_CLOSE")
    s["action"] = "SELL"
    assert not apply([s])
