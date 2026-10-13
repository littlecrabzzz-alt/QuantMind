"""ashare-lab 撮合引擎桥接：合成数据单元测试（规格见 backend/shared/ashare_lab_bridge/README.md）。"""

import numpy as np
import pandas as pd
import pytest

from backend.shared.ashare_lab_bridge import (
    BridgeConfig,
    import_ashare_lab,
    run_signal_backtest,
    signals_to_scores,
    to_ts_code,
)

lab = import_ashare_lab()


@pytest.mark.parametrize("raw,expected", [
    ("SH600000", "600000.SH"), ("sz000001", "000001.SZ"), ("600000.SH", "600000.SH"),
    ("000001.sz", "000001.SZ"), ("BJ430047", "430047.BJ"), ("SZ300750", "300750.SZ"),
])
def test_to_ts_code(raw, expected):
    assert to_ts_code(raw) == expected


def test_to_ts_code_rejects_garbage():
    with pytest.raises(ValueError):
        to_ts_code("AAPL")


def _signals(rows):
    idx = pd.MultiIndex.from_tuples([(pd.Timestamp(d), i) for d, i, _ in rows],
                                    names=["datetime", "instrument"])
    return pd.DataFrame({"score": [s for *_, s in rows]}, index=idx)


def test_signals_to_scores():
    sig = _signals([("2024-01-03", "SZ000002", 2.0), ("2024-01-02", "SH600000", 1.0),
                    ("2024-01-02", "SZ000001", np.nan), ("2024-01-02", "SZ000002", 3.0)])
    s = signals_to_scores(sig)
    assert list(s.index.names) == ["date", "code"]
    assert list(s.index) == [(pd.Timestamp("2024-01-02"), "000002.SZ"),
                             (pd.Timestamp("2024-01-02"), "600000.SH"),
                             (pd.Timestamp("2024-01-03"), "000002.SZ")]
    assert s.loc[(pd.Timestamp("2024-01-02"), "000002.SZ")] == 3.0


def test_signals_series_input():
    sig = _signals([("2024-01-02", "SH600000", 1.0)])["score"]
    assert len(signals_to_scores(sig)) == 1


@pytest.fixture
def data():
    dates = pd.bdate_range("2024-01-01", periods=300)
    codes = ["600000.SH", "000001.SZ", "000002.SZ", "300750.SZ"]
    idx = pd.DatetimeIndex(dates)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(10 * np.cumprod(1 + rng.normal(0, 0.01, (len(idx), len(codes))), axis=0),
                         index=idx, columns=codes)
    open_ = close.shift(1).fillna(10.0)
    md = lab.MarketData(
        open=open_, close=close,
        up_limit=close.shift(1).fillna(10.0) * 1.1, down_limit=close.shift(1).fillna(10.0) * 0.9,
        adj=pd.DataFrame(1.0, index=idx, columns=codes),
        volume=pd.DataFrame(1e6, index=idx, columns=codes),
        amount=pd.DataFrame(1e9, index=idx, columns=codes),
        suspended=pd.DataFrame(False, index=idx, columns=codes),
        is_st=pd.DataFrame(False, index=idx, columns=codes),
        list_date=pd.Series(pd.Timestamp("2000-01-01"), index=codes),
        delist_date=pd.Series(pd.NaT, index=codes, dtype="datetime64[ns]"),
        members={"000906.SH": pd.DataFrame(True, index=idx, columns=codes)},
        index_close=pd.DataFrame({"000906.SH": np.linspace(100, 110, len(idx))}, index=idx),
    )
    return md


def _sig_for(md, dates):
    rows = []
    for d in dates:
        for k, c in enumerate(md.close.columns):
            code, ex = c.split(".")
            rows.append((d, ex + code, float(k)))
    return _signals(rows)


def test_bridge_equals_native_engine(data):
    # 默认参数（中证 800、上市满 250 日、20 日均成交额 >= 5000 万）与 ashare-lab ScoreStrategy 一致
    cfg = BridgeConfig(initial_capital=1e6, topk=2)
    sig = _sig_for(data, [data.calendar[260], data.calendar[280]])
    res = run_signal_backtest(sig, "2024-01-01", data.calendar[-1], config=cfg, data=data)
    assert res.success, res.error_message
    native = lab.run_backtest(lab.ScoreStrategy(signals_to_scores(sig), top_n=2), data,
                              lab.BacktestConfig("2024-01-01", data.calendar[-1], 1e6, lab.CostModel()))
    pd.testing.assert_series_equal(res.nav, native.nav, check_names=False)
    assert len(native.trades) > 0
    pd.testing.assert_frame_equal(res.trades.reset_index(drop=True), native.trades.reset_index(drop=True))


def test_universe_and_filters_configurable(data):
    sig = _sig_for(data, [data.calendar[260]])
    res = run_signal_backtest(sig, "2024-01-01", data.calendar[-1],
                              config=BridgeConfig(initial_capital=1e6, topk=2, min_amount=2e9), data=data)
    assert res.success and res.trades.empty  # 成交额门槛过高 -> 无可选股票


def test_report_format(data):
    cfg = BridgeConfig(initial_capital=1e6, topk=2)
    sig = _sig_for(data, [data.calendar[260], data.calendar[280]])
    res = run_signal_backtest(sig, "2024-01-01", data.calendar[-1], config=cfg, data=data)
    rep = res.portfolio_dict["report"]
    for col in ("account", "return", "cost", "cost_amount", "turnover", "cash", "value"):
        assert col in rep.columns, col
    assert (rep.index == res.nav.index).all()
    np.testing.assert_allclose(rep["account"], res.nav)
    prev = rep["account"].shift(1).fillna(1e6)
    np.testing.assert_allclose(rep["return"] - rep["cost"], rep["account"] / prev - 1, atol=1e-12)
    np.testing.assert_allclose(rep["value"] + rep["cash"], rep["account"])
    assert rep["cost"].sum() > 0 and rep["turnover"].max() > 0
    assert res.portfolio_dict["execution_model"] == "ashare_lab_next_open_lot"
    assert res.total_return == pytest.approx(res.nav.iloc[-1] / 1e6 - 1)
    assert res.max_drawdown <= 0
    for k in ("annual_return", "sharpe_ratio", "max_drawdown", "total_return"):
        assert np.isfinite(getattr(res, k))


def test_costs_mapped(data):
    sig = _sig_for(data, [data.calendar[260]])
    base = dict(initial_capital=1e6, topk=2)
    cheap = run_signal_backtest(sig, "2024-01-01", data.calendar[-1],
                                config=BridgeConfig(**base, commission=0.0, slippage=0.0), data=data)
    dear = run_signal_backtest(sig, "2024-01-01", data.calendar[-1],
                               config=BridgeConfig(**base, commission=0.003, slippage=0.002), data=data)
    assert cheap.nav.iloc[-1] > dear.nav.iloc[-1]


def test_failure_is_reported_not_raised(data):
    cfg = BridgeConfig(universe="NOPE", min_list_days=0, min_amount=0)
    res = run_signal_backtest(_sig_for(data, [data.calendar[260]]), "2024-01-01", data.calendar[-1],
                              config=cfg, data=data)
    assert not res.success and res.error_message
