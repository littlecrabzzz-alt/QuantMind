"""I8 可转债双低的验收测试（docs/13）。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.ideas_cb import conv_price_asof, premium_rate, select_double_low, run_cb_backtest

D = pd.bdate_range("2024-01-01", periods=12)


def test_conv_price_asof_uses_later_of_ann_and_change_date():
    changes = pd.DataFrame({
        "code": ["X", "X", "Y"],
        "ann_date": pd.to_datetime(["2024-01-01", "2024-01-10", "2024-01-01"]),
        "change_date": pd.to_datetime(["2024-01-01", "2024-01-05", "2024-01-08"]),
        "conv_price": [10.0, 8.0, 20.0],
    })
    # X 第二次下修：生效日 01-05 早于公告日 01-10 → 01-10 起才可知
    p = conv_price_asof(pd.Timestamp("2024-01-09"), changes)
    assert p["X"] == 10.0
    assert p["Y"] == 20.0
    # Y 生效日 01-08 晚于公告日 01-01 → 01-07 尚不可用
    p = conv_price_asof(pd.Timestamp("2024-01-07"), changes)
    assert "Y" not in p.index or np.isnan(p["Y"])
    p = conv_price_asof(pd.Timestamp("2024-01-10"), changes)
    assert p["X"] == 8.0 and p["Y"] == 20.0


def test_premium_rate():
    # 转股价值 = 100/10*12 = 120；收盘 132 → 溢价率 10%
    assert premium_rate(132.0, 12.0, 10.0) == pytest.approx(0.10)


def snapshot(**cols):
    base = dict(code=list("ABCDE"), close=[100.0, 110, 105, 120, 99],
                premium=[0.30, 0.05, 0.10, 0.01, 0.50], amount=[1e6] * 5,
                listed_days=[10] * 5, days_to_maturity=[1000] * 5,
                call_announced=[False] * 5)
    base.update(cols)
    return pd.DataFrame(base).set_index("code")


def test_select_double_low_ranking_and_filters():
    # 双低 = close + premium*100：A 130, B 115, C 115, D 121, E 149
    w = select_double_low(snapshot(), n=2)
    assert sorted(w.index) == ["B", "C"]          # 并列按代码
    assert w.sum() == pytest.approx(1.0)
    snap = snapshot(amount=[1e6, 0.0, 1e6, 1e6, 1e6],          # B 当日无成交
                    listed_days=[10, 10, 4, 10, 10],             # C 上市不足 5 日
                    days_to_maturity=[1000, 1000, 1000, 180, 1000],  # D 距到期不足 180 天以上
                    call_announced=[False, False, False, False, True])  # E 已公告强赎
    w = select_double_low(snap, n=2)
    assert list(w.index) == ["A"] and w["A"] == pytest.approx(1.0)
    empty = select_double_low(snapshot(amount=[0.0] * 5), n=2)
    assert empty.empty


def frames():
    cols = ["A", "B"]
    close = pd.DataFrame({"A": np.linspace(100, 111, 12), "B": 100.0}, index=D)
    open_ = close.shift(1).fillna(100.0)
    amount = pd.DataFrame(1e6, index=D, columns=cols)
    return open_, close, amount


def test_backtest_executes_next_open_no_cost():
    open_, close, amount = frames()
    targets = {D[1]: pd.Series({"A": 1.0})}
    nav = run_cb_backtest(open_, close, amount, targets, cost=0.0, initial_cash=1.0)
    # D[1] 收盘信号，D[2] 开盘按 open 买入 A
    assert nav.iloc[1] == pytest.approx(1.0)
    expect = close["A"].iloc[-1] / open_["A"].iloc[2]
    assert nav.iloc[-1] == pytest.approx(expect)


def test_backtest_costs_and_switch():
    open_, close, amount = frames()
    targets = {D[1]: pd.Series({"A": 1.0}), D[5]: pd.Series({"B": 1.0})}
    nav = run_cb_backtest(open_, close, amount, targets, cost=0.001, initial_cash=1.0)
    a = (1 - 0.001) * open_["A"].iloc[6] / open_["A"].iloc[2]   # 买 A 成本，D[6] 开盘卖
    b = a * (1 - 0.001) * (1 - 0.001)                          # 卖 A、买 B
    assert nav.iloc[-1] == pytest.approx(b * close["B"].iloc[-1] / open_["B"].iloc[6])


def test_backtest_untradeable_retries_and_delisting():
    open_, close, amount = frames()
    amount.loc[D[2], "A"] = 0.0          # D[2] A 无成交：不能买，D[3] 重试
    close.loc[D[8]:, "B"] = np.nan       # B 在 D[7] 后摘牌
    open_.loc[D[8]:, "B"] = np.nan
    amount.loc[D[8]:, "B"] = np.nan
    targets = {D[1]: pd.Series({"A": 0.5, "B": 0.5})}
    nav = run_cb_backtest(open_, close, amount, targets, cost=0.0, initial_cash=1.0)
    a_units = 0.5 / open_["A"].iloc[3]
    b_units = 0.5 / open_["B"].iloc[2]
    # 摘牌后 B 按最后收盘价转现金
    expect = a_units * close["A"].iloc[-1] + b_units * close["B"].iloc[7]
    assert nav.iloc[-1] == pytest.approx(expect)
    # D[2] 收盘：A 仍是现金，B 已持有
    assert nav.iloc[2] == pytest.approx(0.5 + b_units * close["B"].iloc[2])
