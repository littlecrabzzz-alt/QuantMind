"""S2 期货对冲：合约选择、移仓、保证金账户、成本、基差与无未来函数。"""

import numpy as np
import pandas as pd
import pytest

from ashare_lab.expansion.hedge import simulate_hedge, target_contracts

CAL = pd.bdate_range("2020-01-01", periods=30)


def _basic():
    return pd.DataFrame({
        "ts_code": ["IFA.CFX", "IFB.CFX", "ICA.CFX"],
        "list_date": [CAL[0], CAL[0], CAL[0]],
        "delist_date": [CAL[10], CAL[25], CAL[29]],
    })


def test_target_contract_rolls_five_days_before_expiry():
    mapping = pd.Series("IFA.CFX", index=CAL[:10])
    out = target_contracts(mapping, _basic(), CAL, roll_days=5)
    # CAL[4] 之后到 CAL[10]（含）还有 6 个交易日；CAL[5] 之后只剩 5 个 → 换下一个合约。
    assert out[CAL[4]] == "IFA.CFX"
    assert out[CAL[5]] == "IFB.CFX"
    assert (out[CAL[5]:CAL[9]] == "IFB.CFX").all()


def test_target_contract_next_must_be_listed_and_same_product():
    basic = _basic()
    basic.loc[basic.ts_code == "IFB.CFX", "list_date"] = CAL[7]
    basic = pd.concat([basic, pd.DataFrame({"ts_code": ["IFC.CFX"], "list_date": [CAL[0]],
                                            "delist_date": [CAL[28]]})])
    mapping = pd.Series("IFA.CFX", index=CAL[:10])
    out = target_contracts(mapping, basic, CAL, roll_days=5)
    assert out[CAL[5]] == "IFC.CFX"  # IFB 尚未上市；ICA 品种不同
    assert out[CAL[7]] == "IFB.CFX"


def _setup(n=6, fut=None, long=None):
    dates = CAL[:n]
    long_nav = pd.Series(long if long is not None else np.ones(n), index=dates, dtype=float)
    prices = pd.DataFrame({"IFA.CFX": fut if fut is not None else np.full(n, 100.0),
                           "IFB.CFX": np.full(n, 200.0)}, index=dates, dtype=float)
    contracts = pd.Series("IFA.CFX", index=dates)
    ratio = pd.Series([1.0], index=dates[:1])
    index_close = {"IF": pd.Series(100.0, index=dates)}
    return long_nav, prices, contracts, ratio, index_close


def test_initial_split_and_long_growth():
    long_nav, prices, contracts, ratio, index_close = _setup(long=1.01 ** np.arange(6))
    out = simulate_hedge(long_nav, prices, contracts, ratio, index_close,
                         margin=0.15, fut_cost=1.23e-4, transfer_cost=0.0015)
    nav = out["nav"]
    assert nav.iloc[0] == pytest.approx(1.0)
    # 第 1 日收盘成交：L = 1/1.15，划转成本 0.15%·L，期货开仓成本 1.23bp·L。
    L = 1 / 1.15
    cost = 0.0015 * L + 1.23e-4 * L
    assert nav.iloc[1] == pytest.approx(1 - cost)
    C = 1 - L - cost
    for k in range(2, 6):
        L *= 1.01
        assert nav.iloc[k] == pytest.approx(L + C)


def test_futures_loss_hits_cash():
    fut = np.array([100, 100, 100, 101, 101, 101.0])
    long_nav, prices, contracts, ratio, index_close = _setup(fut=fut)
    out = simulate_hedge(long_nav, prices, contracts, ratio, index_close,
                         fut_cost=0.0, transfer_cost=0.0)
    L = 1 / 1.15
    assert out["nav"].iloc[2] == pytest.approx(1.0)
    assert out["nav"].iloc[3] == pytest.approx(1.0 - L * 0.01)
    # 期货涨幅等于现货？此处现货不动 → 全部是基差。
    assert out["basis"].iloc[3] == pytest.approx(-L * 0.01)


def test_roll_keeps_notional_and_charges_two_legs():
    long_nav, prices, contracts, ratio, index_close = _setup()
    contracts.iloc[3:] = "IFB.CFX"  # 第 3 日收盘决定，第 4 日收盘移仓
    out = simulate_hedge(long_nav, prices, contracts, ratio, index_close,
                         fut_cost=1e-4, transfer_cost=0.0)
    L = 1 / 1.15
    v1 = 1 - 1e-4 * L
    assert out["nav"].iloc[3] == pytest.approx(v1)
    assert out["nav"].iloc[4] == pytest.approx(v1 - 2e-4 * L)
    assert out["held"].iloc[3] == "IFA.CFX"
    assert out["held"].iloc[4] == "IFB.CFX"
    # 移仓后按新合约计盈亏：IFB 上涨 1% → 亏损 L × 1%。
    prices2 = prices.copy()
    prices2.iloc[5, 1] = 202.0
    out2 = simulate_hedge(long_nav, prices2, contracts, ratio, index_close,
                          fut_cost=1e-4, transfer_cost=0.0)
    assert out2["nav"].iloc[5] == pytest.approx(v1 - 2e-4 * L - L * 0.01)


def test_monthly_rebalance_resets_split_and_hedge_ratio():
    long_nav, prices, contracts, ratio, index_close = _setup(long=[1, 1, 1.1, 1.1, 1.1, 1.1])
    ratio = pd.Series([1.0, 0.5], index=CAL[[0, 3]])
    out = simulate_hedge(long_nav, prices, contracts, ratio, index_close,
                         fut_cost=0.0, transfer_cost=0.0)
    V = out["nav"].iloc[4]
    assert out["L"].iloc[4] == pytest.approx(V / (1 + 0.15 * 0.5))
    assert out["hedge_notional"].iloc[4] == pytest.approx(0.5 * out["L"].iloc[4])


def test_basis_zero_when_futures_track_index_and_cash_return():
    n = 6
    fut = 100 * 1.01 ** np.arange(n)
    long_nav, prices, contracts, ratio, _ = _setup(fut=fut)
    index_close = {"IF": pd.Series(fut, index=CAL[:n])}
    cash = pd.Series(0.001, index=CAL[:n])
    cash.iloc[:2] = 0.0  # 第 1 日收盘建仓前全为现金；此处不计息以简化手算
    out = simulate_hedge(long_nav, prices, contracts, ratio, index_close, cash_return=cash,
                         fut_cost=0.0, transfer_cost=0.0)
    assert np.allclose(out["basis"].iloc[2:], 0.0)
    L = 1 / 1.15
    C = 1 - L
    q = L / fut[1]
    for k in range(2, n):
        C = C * 1.001 - q * (fut[k] - fut[k - 1])
        assert out["nav"].iloc[k] == pytest.approx(L + C)
    assert set(out["basis_annual"].index) == {2020}


def test_excess_series_is_long_minus_futures():
    fut = np.array([100, 100, 101, 101, 103, 103.0])
    long = np.array([1, 1, 1.02, 1.02, 1.02, 1.03])
    long_nav, prices, contracts, ratio, index_close = _setup(fut=fut, long=long)
    out = simulate_hedge(long_nav, prices, contracts, ratio, index_close,
                         fut_cost=0.0, transfer_cost=0.0)
    ex = out["excess_nav"]
    L1 = 1 / 1.15
    q = L1 / 100
    L2 = L1 * 1.02
    r2 = (L2 - L1 - q * 1) / L1
    assert ex.iloc[2] / ex.iloc[1] - 1 == pytest.approx(r2)
    r4 = (0 - q * 2) / L2
    assert ex.iloc[4] / ex.iloc[3] - 1 == pytest.approx(r4)


def test_no_lookahead():
    rng = np.random.default_rng(3)
    n = 25
    dates = CAL[:n]
    long_nav = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=dates)
    prices = pd.DataFrame({"IFA.CFX": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))),
                           "IFB.CFX": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))},
                          index=dates)
    contracts = target_contracts(pd.Series("IFA.CFX", index=dates), _basic(), CAL)
    ratio = pd.Series([1.0, 0.8, 1.2], index=dates[[0, 8, 16]])
    index_close = {"IF": pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=dates)}
    base = simulate_hedge(long_nav, prices, contracts, ratio, index_close)
    k = 12
    long2, prices2, index2 = long_nav.copy(), prices.copy(), {"IF": index_close["IF"].copy()}
    long2.iloc[k + 1:] *= 1.5
    prices2.iloc[k + 1:] *= 0.7
    index2["IF"].iloc[k + 1:] *= 1.3
    other = simulate_hedge(long2, prices2, contracts, ratio, index2)
    for key in ("nav", "excess_nav", "basis"):
        pd.testing.assert_series_equal(base[key].iloc[:k + 1], other[key].iloc[:k + 1])
