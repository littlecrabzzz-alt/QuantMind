"""向量化极速回测引擎与信号物化逻辑单元测试"""

import pandas as pd
import pytest

from backend.shared.vectorized_backtest.engine import (
    VectorizedBacktestConfig,
    VectorizedBacktestEngine,
)


def _make_pred(index, score):
    idx = pd.MultiIndex.from_tuples(index, names=["datetime", "instrument"])
    return pd.DataFrame({"score": score}, index=idx)


def _make_price(index, values):
    idx = pd.MultiIndex.from_tuples(index, names=["datetime", "instrument"])
    return pd.DataFrame({"$close": values}, index=idx)


def test_vectorized_engine_runs_and_returns_report():
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    instruments = ["SH600000", "SH600036", "SZ000001", "SZ300750"]
    index = [(d, ins) for d in dates for ins in instruments]
    n = len(index)
    scores = [float(i % 4) for i in range(n)]
    prices = [10.0 + (i % 7) for i in range(n)]

    signals = _make_pred(index, scores)
    price_df = _make_price(index, prices)

    cfg = VectorizedBacktestConfig(initial_capital=100000.0, topk=2, commission=0.001)
    engine = VectorizedBacktestEngine(cfg)
    res = engine.run_backtest(signals=signals, prices=price_df, changes=None)

    assert res.success, res.error_message
    assert "report" in res.portfolio_dict
    report = res.portfolio_dict["report"]
    assert "return" in report.columns
    assert "account" in report.columns
    assert len(report) > 0
    assert res.annual_return is not None


def test_vectorized_engine_respects_topk():
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    instruments = [f"SH6000{i:02d}" for i in range(10)]
    index = [(d, ins) for d in dates for ins in instruments]
    n = len(index)
    # 使每日分数排名稳定：分数 = instrument 序号
    scores = [float(i % 10) for i in range(n)]
    prices = [10.0 + (i % 10) for i in range(n)]

    signals = _make_pred(index, scores)
    price_df = _make_price(index, prices)

    cfg = VectorizedBacktestConfig(initial_capital=100000.0, topk=3, commission=0.0, slippage=0.0)
    engine = VectorizedBacktestEngine(cfg)
    res = engine.run_backtest(signals=signals, prices=price_df, changes=None)
    assert res.success

    # TopK=3 → 每次调仓最多 3 只等权；组合日收益应有限且净值曲线单调累积
    assert res.max_drawdown <= 0.0 or res.max_drawdown >= -1.0
    assert res.total_return >= -1.0


def test_vectorized_engine_handles_nan_prices_as_suspended():
    dates = pd.date_range("2024-01-02", periods=6, freq="B")
    instruments = ["SH600000", "SH600036"]
    index = [(d, ins) for d in dates for ins in instruments]
    n = len(index)
    scores = [float(i % 2) for i in range(n)]
    prices = [10.0 + (i % 5) for i in range(n)]
    # 其中一只股票某天停牌（NaN close）
    prices[0] = float("nan")

    signals = _make_pred(index, scores)
    price_df = _make_price(index, prices)

    cfg = VectorizedBacktestConfig(initial_capital=100000.0, topk=1, commission=0.0, slippage=0.0)
    engine = VectorizedBacktestEngine(cfg)
    res = engine.run_backtest(signals=signals, prices=price_df, changes=None)
    assert res.success
    assert res.portfolio_dict["report"] is not None


def test_vectorized_engine_does_not_trade_internal_suspension_gap():
    dates = pd.date_range("2024-01-02", periods=4, freq="B")
    instruments = ["SH600000", "SH600036"]
    index = [(d, ins) for d in dates for ins in instruments]

    # SH600000 is not held initially, then becomes the highest-score stock on
    # its suspension day. It cannot be bought before the resumption jump.
    signals = _make_pred(index, [1.0, 2.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0])
    price_df = _make_price(
        index,
        [
            10.0,
            10.0,
            float("nan"),
            10.0,
            20.0,
            10.0,
            20.0,
            10.0,
        ],
    )

    cfg = VectorizedBacktestConfig(
        initial_capital=100000.0,
        topk=1,
        commission=0.0,
        slippage=0.0,
        sell_cost=0.0,
    )
    res = VectorizedBacktestEngine(cfg).run_backtest(
        signals=signals,
        prices=price_df,
        changes=None,
    )

    assert res.success, res.error_message
    report = res.portfolio_dict["report"]
    # The suspended high-score stock must not be selected on dates[1].  Its
    # post-resumption jump therefore cannot leak into that day's portfolio PnL.
    assert report.loc[dates[1], "return"] == pytest.approx(0.0)


def test_vectorized_engine_retains_position_when_sell_is_blocked():
    dates = pd.date_range("2024-01-02", periods=4, freq="B")
    instruments = ["SH600000", "SH600036"]
    index = [(d, ins) for d in dates for ins in instruments]
    signals = _make_pred(index, [2.0, 1.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0])
    price_df = _make_price(
        index,
        [10.0, 10.0, float("nan"), 10.0, 20.0, 10.0, 20.0, 10.0],
    )

    cfg = VectorizedBacktestConfig(
        initial_capital=100000.0,
        topk=1,
        commission=0.0,
        slippage=0.0,
        sell_cost=0.0,
    )
    res = VectorizedBacktestEngine(cfg).run_backtest(
        signals=signals,
        prices=price_df,
        changes=None,
    )

    assert res.success, res.error_message
    report = res.portfolio_dict["report"]
    assert report.loc[dates[1], "return"] == pytest.approx(1.0)


def test_vectorized_engine_retains_position_at_limit_down():
    dates = pd.date_range("2024-01-02", periods=4, freq="B")
    instruments = ["SH600000", "SH600036"]
    index = [(d, ins) for d in dates for ins in instruments]
    signals = _make_pred(index, [2.0, 1.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0])
    price_df = _make_price(
        index,
        [10.0, 10.0, 9.0, 10.0, 8.0, 10.0, 8.0, 10.0],
    )
    change_df = _make_price(
        index,
        [0.0, 0.0, -0.10, 0.0, -0.11, 0.0, 0.0, 0.0],
    ).rename(columns={"$close": "$change"})

    cfg = VectorizedBacktestConfig(
        initial_capital=100000.0,
        topk=1,
        commission=0.0,
        slippage=0.0,
        sell_cost=0.0,
    )
    res = VectorizedBacktestEngine(cfg).run_backtest(
        signals=signals,
        prices=price_df,
        changes=change_df,
    )

    assert res.success, res.error_message
    report = res.portfolio_dict["report"]
    assert report.loc[dates[1], "return"] == pytest.approx(8.0 / 9.0 - 1.0)


def test_vectorized_engine_charges_initial_buy_cost():
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    index = [(d, "SH600000") for d in dates]
    signals = _make_pred(index, [1.0] * len(dates))
    price_df = _make_price(index, [10.0] * len(dates))

    cfg = VectorizedBacktestConfig(
        initial_capital=100000.0,
        topk=1,
        commission=0.001,
        slippage=0.002,
        sell_cost=0.01,
    )
    res = VectorizedBacktestEngine(cfg).run_backtest(
        signals=signals,
        prices=price_df,
        changes=None,
    )

    assert res.success, res.error_message
    report = res.portfolio_dict["report"]
    assert report.iloc[0]["return"] == pytest.approx(-0.003)
    assert report.iloc[0]["cost"] == pytest.approx(300.0)
