"""回测服务里的 ashare-lab 开关（规格见 backend/shared/ashare_lab_bridge/README.md「接入回测服务」）。

在 quantmind-oss 镜像里运行（需要 qlib）。有面板的用例需要挂载 ashare-lab：
ASHARE_LAB_SRC=/opt/ashare-lab/src ASHARE_LAB_PANEL=/opt/ashare-lab/data/panel
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services.engine.qlib_app.services import backtest_service_runtime as runtime
from backend.services.engine.qlib_app.services.backtest_service_runtime import (
    QlibBacktestServiceRuntimeMixin,
)

PANEL = Path(os.environ.get("ASHARE_LAB_PANEL", "/nonexistent"))
HAS_PANEL = (PANEL / "daily.parquet").exists()


def _request(universe="csi300", **kw):
    base = dict(
        deal_price="open", use_vectorized=True, min_commission=0, universe=universe,
        start_date="2019-01-02", end_date="2019-06-28", initial_capital=1e7,
        strategy_params=SimpleNamespace(signal="<PRED>", topk=30, rebalance_days=5),
    )
    base.update(kw)
    return SimpleNamespace(**base)


STRATEGY = {"class": "RedisTopkStrategy", "kwargs": {"topk": 30, "rebalance_days": 5}}


@pytest.mark.parametrize("value,expected", [
    ("csi300", "000300.SH"), ("CSI500", "000905.SH"), ("csi800", "000906.SH"),
    ("csi1000", "000852.SH"), ("all", None), ("", None), (None, None),
    ("/data/pools/x.txt", None), ("pool:abc", None),
])
def test_universe_mapping(value, expected):
    assert runtime._ashare_lab_universe(value) == expected


def test_gate_closed_without_panel(monkeypatch):
    monkeypatch.setenv("ASHARE_LAB_PANEL", "/nonexistent/panel")
    gate = QlibBacktestServiceRuntimeMixin._is_vectorized_safe
    for universe in ("csi300", "csi1000", "all"):
        assert not gate(QlibBacktestServiceRuntimeMixin(), _request(universe), STRATEGY)


def test_gate_closed_when_request_has_no_universe(monkeypatch):
    req = _request()
    del req.universe
    assert not QlibBacktestServiceRuntimeMixin._is_vectorized_safe(
        QlibBacktestServiceRuntimeMixin(), req, STRATEGY)


@pytest.mark.skipif(not HAS_PANEL, reason="ashare-lab panel not mounted")
def test_gate_open_with_panel_for_index_universe_only():
    gate = QlibBacktestServiceRuntimeMixin._is_vectorized_safe
    m = QlibBacktestServiceRuntimeMixin()
    assert gate(m, _request("csi300"), STRATEGY)
    assert gate(m, _request("csi1000"), STRATEGY)
    assert not gate(m, _request("all"), STRATEGY)
    assert not gate(m, _request("pool:abc"), STRATEGY)


def _pred(dates, codes):
    idx = pd.MultiIndex.from_product([pd.DatetimeIndex(dates), codes], names=["datetime", "instrument"])
    return pd.DataFrame({"score": range(len(idx))}, index=idx, dtype=float)


def test_sample_rebalance_dates():
    dates = pd.bdate_range("2024-01-01", periods=12)
    pred = _pred(dates, ["SH600000", "SZ000001"])
    out = runtime._sample_rebalance_dates(pred, 5)
    kept = pd.DatetimeIndex(out.index.get_level_values("datetime").unique())
    assert list(kept) == [dates[0], dates[5], dates[10]]
    assert len(out) == 6
    assert runtime._sample_rebalance_dates(pred, 1).equals(pred)


def test_rebalance_days_from_strategy_or_request():
    req = _request()
    assert runtime._rebalance_days(req, {"kwargs": {"rebalance_days": 7}}) == 7
    assert runtime._rebalance_days(req, {"kwargs": {}}) == 5
    req.strategy_params = SimpleNamespace(topk=30)
    assert runtime._rebalance_days(req, {}) == 1


@pytest.mark.skipif(not HAS_PANEL, reason="ashare-lab panel not mounted")
def test_run_ashare_lab_vectorized_matches_bridge():
    from backend.shared.ashare_lab_bridge import BridgeConfig, import_ashare_lab, run_signal_backtest

    lab = import_ashare_lab()
    data = lab.load_market_data(PANEL, "2018-01-01", "2019-06-28", universe="000300.SH")
    codes = [c.split(".")[1] + c.split(".")[0] for c in data.close.columns[:120]]
    dates = data.calendar[(data.calendar >= "2019-01-02")]
    pred = _pred(dates, codes)
    req = _request("csi300")
    res = runtime._run_ashare_lab_vectorized(pred, req, STRATEGY, commission=0.0003, transfer_fee=0.00001)
    assert res.success, res.error_message
    direct = run_signal_backtest(
        runtime._sample_rebalance_dates(pred, 5), "2019-01-02", "2019-06-28",
        config=BridgeConfig(initial_capital=1e7, topk=30, universe="000300.SH",
                            commission=0.0003, transfer=0.00001))
    pd.testing.assert_series_equal(res.nav, direct.nav)
    assert "report" in res.portfolio_dict and len(res.trades) > 0
