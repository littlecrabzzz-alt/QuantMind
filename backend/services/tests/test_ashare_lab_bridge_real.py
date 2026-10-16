"""桥接与 ashare-lab 原生回测的真实数据对数：同一策略结果一致到小数点后 4 位。

需要 ashare-lab 面板（ASHARE_LAB_PANEL，默认仓库 vendor/ashare-lab/data/panel）。
"""


import numpy as np
import pandas as pd
import pytest

from backend.shared.ashare_lab_bridge import BridgeConfig, import_ashare_lab, run_signal_backtest
from backend.shared.ashare_lab_bridge.bridge import _panel_dir

PANEL = _panel_dir()
pytestmark = pytest.mark.skipif(not (PANEL / "daily.parquet").exists(), reason="ashare-lab panel missing")


def test_lowvol_parity():
    lab = import_ashare_lab()
    data = lab.load_market_data(PANEL, "2015-01-01", "2018-12-31", universe="000906.SH")
    logret = np.log(data.adj_close()).diff().where(data.close.notna())
    vol = logret.rolling(250, min_periods=200).std()
    dates = lab.month_end_dates(data.calendar)
    dates = dates[dates >= pd.Timestamp("2016-01-01")]
    scores = (-vol.loc[dates]).stack().rename("score")
    scores.index.names = ["date", "code"]

    native = lab.run_backtest(lab.ScoreStrategy(scores, top_n=50), data,
                              lab.BacktestConfig("2016-01-01", "2018-12-31", 1e7, lab.CostModel()))

    # 转成 QuantMind/Qlib 信号格式：MultiIndex(datetime, instrument)，instrument 为 SH600000 式
    qm = scores.copy()
    qm.index = pd.MultiIndex.from_arrays(
        [qm.index.get_level_values(0),
         [c.split(".")[1] + c.split(".")[0] for c in qm.index.get_level_values(1)]],
        names=["datetime", "instrument"])
    res = run_signal_backtest(qm.to_frame("score"), "2016-01-01", "2018-12-31",
                              config=BridgeConfig(initial_capital=1e7, topk=50), data=data)
    assert res.success, res.error_message
    a = (res.nav / 1e7).round(4)
    b = (native.nav / 1e7).round(4)
    pd.testing.assert_series_equal(a, b, check_names=False)
    s = lab.metrics.summary(native)
    assert round(res.annual_return, 4) == round(s["cagr"], 4)
    assert round(res.max_drawdown, 4) == round(s["max_drawdown"], 4)
    assert round(res.sharpe_ratio, 4) == round(s["sharpe"], 4)
    assert len(native.trades) > 1000


def test_loads_panel_when_data_not_given():
    sig = pd.DataFrame({"score": [1.0, 2.0]}, index=pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2020-01-23"), "SH600000"), (pd.Timestamp("2020-01-23"), "SZ000001")],
        names=["datetime", "instrument"]))
    res = run_signal_backtest(sig, "2020-01-02", "2020-03-31",
                              config=BridgeConfig(initial_capital=1e6, topk=2), panel_dir=PANEL)
    assert res.success, res.error_message
    assert set(res.trades.code) <= {"600000.SH", "000001.SZ"} and len(res.trades) >= 2
