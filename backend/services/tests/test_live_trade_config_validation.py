from backend.services.live_trading.routers.real_trading_utils import (
    _default_execution_config,
    _default_live_trade_config,
    _normalize_execution_config,
    _normalize_live_trade_config,
)
import pytest
from fastapi import HTTPException


def test_live_trade_config_accepts_valid_sell_buy_time_for_all_phase():
    live_config = _normalize_live_trade_config(
        {
            "schedule_type": "interval",
            "rebalance_days": 3,
            "enabled_sessions": ["AM"],
            "sell_time": "09:30",
            "buy_time": "09:31",
            "sell_first": True,
            "order_type": "MARKET",
            "max_price_deviation": 0.02,
            "max_orders_per_cycle": 20,
        },
        _default_live_trade_config(),
    )
    execution_config = _normalize_execution_config(
        {
            "max_buy_drop": -0.03,
            "stop_loss": -0.08,
        },
        _default_execution_config(),
    )

    assert live_config["schedule_type"] == "interval"
    assert live_config["rebalance_days"] == 3
    assert live_config["enabled_sessions"] == ["AM"]
    assert live_config["sell_time"] == "09:30"
    assert live_config["buy_time"] == "09:31"
    assert live_config["order_type"] == "MARKET"
    assert execution_config["max_buy_drop"] == -0.03
    assert execution_config["stop_loss"] == -0.08


def test_live_trade_config_rejects_am_time_before_continuous_auction():
    with pytest.raises(HTTPException) as exc_info:
        _normalize_live_trade_config(
            {
                "enabled_sessions": ["AM"],
                "sell_time": "09:00",
                "buy_time": "09:05",
            },
            _default_live_trade_config(),
        )
    detail = str(exc_info.value.detail)
    assert "sell_time=09:00" in detail
    assert "09:30-11:30" in detail


def test_live_trade_config_auto_heals_pm_times_with_am_only_session():
    live_config = _normalize_live_trade_config(
        {
            "enabled_sessions": ["AM"],
            "sell_time": "14:00",
            "buy_time": "14:05",
        },
        _default_live_trade_config(),
    )
    assert "PM" in live_config["enabled_sessions"]
    assert live_config["sell_time"] == "14:00"
    assert live_config["buy_time"] == "14:05"


def test_live_trade_config_strips_seconds_from_hhmmss():
    live_config = _normalize_live_trade_config(
        {
            "enabled_sessions": ["AM"],
            "sell_time": "09:30:00",
            "buy_time": "09:35:00",
        },
        _default_live_trade_config(),
    )
    assert live_config["sell_time"] == "09:30"
    assert live_config["buy_time"] == "09:35"
