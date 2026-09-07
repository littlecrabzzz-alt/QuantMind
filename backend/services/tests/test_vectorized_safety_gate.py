"""Formal backtests cannot substitute the fractional-share diagnostic engine."""

from types import SimpleNamespace

import pytest

from backend.services.engine.qlib_app.services.backtest_service_runtime import (
    QlibBacktestServiceRuntimeMixin,
)


@pytest.mark.parametrize(
    "strategy_class", ["RedisTopkStrategy", "TopkDropout", "RedisWeightStrategy"]
)
@pytest.mark.parametrize("deal_price", ["open", "close"])
def test_formal_runs_use_step_even_for_full_topk(strategy_class, deal_price):
    request = SimpleNamespace(
        deal_price=deal_price,
        use_vectorized=True,
        min_commission=0,
        strategy_params=SimpleNamespace(signal="<PRED>", topk=50),
    )
    strategy = {"class": strategy_class, "kwargs": {"topk": 50, "n_drop": 50}}
    assert not QlibBacktestServiceRuntimeMixin._is_vectorized_safe(
        QlibBacktestServiceRuntimeMixin(), request, strategy
    )


def test_extract_strategy_config_dict():
    content = 'STRATEGY_CONFIG = {"class": "RedisTopkStrategy", "kwargs": {"topk": 50}}'
    cfg = QlibBacktestServiceRuntimeMixin._extract_strategy_config_from_code(content)
    assert cfg["class"] == "RedisTopkStrategy"
    assert cfg["kwargs"]["topk"] == 50
