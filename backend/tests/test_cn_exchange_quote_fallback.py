import os
import sys
import logging
from unittest.mock import Mock

import pandas as pd
import pytest

project_root = os.path.join(os.path.dirname(__file__), "../../")
sys.path.append(project_root)

from backend.services.engine.qlib_app.utils.cn_exchange import CnExchange
from qlib.backtest.decision import Order, OrderDir


class DummyQuote:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_data(self, stock_id, start_time, end_time, field, method="ts_data_last"):
        key = (stock_id, pd.Timestamp(start_time).strftime("%Y-%m-%d"), field)
        return self.mapping.get(key)

    def get_all_stock(self):
        return {"SH600000"}


def make_exchange(mapping):
    exchange = CnExchange.__new__(CnExchange)
    exchange.quote = DummyQuote(mapping)
    exchange.buy_price = "$close"
    exchange.sell_price = "$close"
    exchange.quote_fallback_lookback_days = 3
    exchange.backtest_id = "test"
    exchange.redis_client = None
    exchange.logger = logging.getLogger("exchange-test")
    return exchange


def test_get_close_falls_back_to_previous_valid_quote():
    exchange = make_exchange(
        {
            ("SH600000", "2026-03-25", "$close"): 0.0,
            ("SH600000", "2026-03-24", "$close"): 12.34,
        }
    )

    price = exchange.get_close(
        "SH600000", pd.Timestamp("2026-03-25"), pd.Timestamp("2026-03-25")
    )

    assert price == pytest.approx(12.34)


def test_get_factor_falls_back_to_previous_valid_quote():
    exchange = make_exchange(
        {
            ("SH600000", "2026-03-25", "$factor"): 0.0,
            ("SH600000", "2026-03-24", "$factor"): 0.256,
        }
    )

    factor = exchange.get_factor(
        "SH600000", pd.Timestamp("2026-03-25"), pd.Timestamp("2026-03-25")
    )

    assert factor == pytest.approx(0.256)


def test_get_deal_price_never_falls_back_to_recent_valid_close():
    exchange = make_exchange(
        {
            ("SH600000", "2026-03-25", "$close"): 0.0,
            ("SH600000", "2026-03-24", "$close"): 8.88,
        }
    )

    price = exchange.get_deal_price(
        "SH600000",
        pd.Timestamp("2026-03-25"),
        pd.Timestamp("2026-03-25"),
        OrderDir.BUY,
    )

    assert pd.isna(price)


def quote_mapping(**overrides):
    fields = {
        "$close": 10.0,
        "$open": 9.9,
        "$volume": 10000,
        "$change": 0.0,
        "$factor": 1.0,
    }
    fields.update(overrides)
    return {("SH600000", "2026-03-25", key): value for key, value in fields.items()}


@pytest.mark.parametrize("field", ["$close", "$open", "$volume", "$factor"])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), 0, -1])
def test_invalid_execution_observation_rejects_order_without_fill(field, invalid):
    mapping = quote_mapping(**{field: invalid})
    mapping[("SH600000", "2026-03-24", field)] = 10
    exchange = make_exchange(mapping)
    exchange.buy_price = "$open"
    exchange._calc_trade_info_by_order = Mock(
        side_effect=AssertionError("must not fill")
    )
    order = Order(
        "SH600000",
        100,
        OrderDir.BUY,
        pd.Timestamp("2026-03-25"),
        pd.Timestamp("2026-03-25"),
    )
    value, cost, price = exchange.deal_order(order)
    assert value == cost == order.deal_amount == 0
    assert pd.isna(price)
    exchange._calc_trade_info_by_order.assert_not_called()


@pytest.mark.parametrize(
    "change,buy,sell",
    [
        (0, True, True),
        (0.10, False, True),
        (-0.10, True, False),
        (None, False, False),
        (float("inf"), False, False),
    ],
)
def test_directional_limits_and_missing_limit_data(change, buy, sell):
    exchange = make_exchange(quote_mapping(**{"$change": change}))
    dt = pd.Timestamp("2026-03-25")
    assert exchange.is_stock_tradable("SH600000", dt, dt, OrderDir.BUY) is buy
    assert exchange.is_stock_tradable("SH600000", dt, dt, OrderDir.SELL) is sell


def test_missing_open_does_not_block_valid_sell_close():
    exchange = make_exchange(quote_mapping(**{"$open": None}))
    exchange.buy_price = "$open"
    dt = pd.Timestamp("2026-03-25")
    assert not exchange.is_stock_tradable("SH600000", dt, dt, OrderDir.BUY)
    assert exchange.is_stock_tradable("SH600000", dt, dt, OrderDir.SELL)
