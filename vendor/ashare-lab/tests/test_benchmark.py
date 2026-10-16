"""全收益基准：合成数据单元测试（见 docs/10-全收益基准约定.md）。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.benchmark import alpha_beta, benchmark_table, dividend_contribution, total_return_close

DATES = pd.bdate_range("2024-01-01", periods=5)


def _snap(rows):
    return pd.DataFrame(rows, columns=["snapshot_date", "code", "weight"]).assign(
        snapshot_date=lambda d: pd.to_datetime(d.snapshot_date))


def _divs(rows):
    return pd.DataFrame(rows, columns=["code", "ex_date", "cash_div_tax"]).assign(
        ex_date=lambda d: pd.to_datetime(d.ex_date))


def _wide(values):
    return pd.DataFrame(values, index=DATES, dtype=float)


def test_weight_drift_and_price_return():
    close = _wide({"A": [10, 11, 11, 11, 11], "B": [20, 20, 18, 18, 18]})
    adj = _wide({"A": [1] * 5, "B": [1] * 5})
    snaps = _snap([(DATES[0], "A", 60.0), (DATES[0], "B", 40.0)])
    out = dividend_contribution(DATES, snaps, close, adj, _divs([]))
    assert list(out.columns) >= ["recon_price_ret", "div_contrib"] or set(out.columns) >= {"recon_price_ret", "div_contrib"}
    assert np.isnan(out.recon_price_ret.iloc[0])
    assert out.recon_price_ret.iloc[1] == pytest.approx(0.6 * 0.1)
    w_a = 0.6 * 1.1 / (0.6 * 1.1 + 0.4)          # 第 1 日收盘后漂移的权重
    assert out.recon_price_ret.iloc[2] == pytest.approx((1 - w_a) * (-0.1))
    assert (out.div_contrib.fillna(0) == 0).all()


def test_dividend_contribution_excluded_from_price_return():
    # A 第 2 日除息 0.5 元，前收 10，收盘 9.5（价格下跌正好等于分红）；后复权因子上调
    close = _wide({"A": [10, 10, 9.5, 9.5, 9.5], "B": [20] * 5})
    adj = _wide({"A": [1, 1, 10 / 9.5, 10 / 9.5, 10 / 9.5], "B": [1] * 5})
    snaps = _snap([(DATES[0], "A", 50.0), (DATES[0], "B", 50.0)])
    out = dividend_contribution(DATES, snaps, close, adj, _divs([("A", DATES[2], 0.5)]))
    assert out.div_contrib.iloc[2] == pytest.approx(0.5 * 0.05)
    assert out.recon_price_ret.iloc[2] == pytest.approx(0.5 * (-0.05))
    assert out.div_contrib.iloc[3] == pytest.approx(0.0)


def test_snapshot_resets_weights_and_non_members_ignored():
    close = _wide({"A": [10, 20, 20, 20, 20], "B": [10, 10, 10, 10, 10], "C": [10] * 5})
    adj = _wide({"A": [1] * 5, "B": [1] * 5, "C": [1] * 5})
    snaps = _snap([(DATES[0], "A", 50.0), (DATES[0], "B", 50.0),
                   (DATES[2], "A", 10.0), (DATES[2], "B", 90.0)])
    divs = _divs([("B", DATES[3], 1.0), ("C", DATES[3], 1.0)])
    out = dividend_contribution(DATES, snaps, close, adj, divs)
    # 第 3 日用第 2 日快照（权重 10/90，自快照日起不再漂移）
    assert out.div_contrib.iloc[3] == pytest.approx(0.9 * 0.1)


def test_suspended_on_ex_date_uses_last_close():
    close = _wide({"A": [10, 10, np.nan, np.nan, 9.0], "B": [10] * 5})
    adj = _wide({"A": [1, 1, np.nan, np.nan, 10 / 9.0], "B": [1] * 5})
    snaps = _snap([(DATES[0], "A", 50.0), (DATES[0], "B", 50.0)])
    out = dividend_contribution(DATES, snaps, close, adj, _divs([("A", DATES[3], 1.0)]))
    assert out.div_contrib.iloc[3] == pytest.approx(0.5 * 0.1)
    assert out.recon_price_ret.iloc[2] == pytest.approx(0.0)


def test_total_return_close_compounds():
    price = pd.Series([100.0, 101.0, 99.99, 99.99], index=DATES[:4])
    div = pd.Series([np.nan, 0.0, 0.01, 0.0], index=DATES[:4])
    tr = total_return_close(price, div)
    assert tr.iloc[0] == 100.0
    assert tr.iloc[1] == pytest.approx(101.0)
    assert tr.iloc[2] == pytest.approx(101.0 * (1 + (99.99 / 101 - 1) + 0.01))
    assert tr.iloc[3] == pytest.approx(tr.iloc[2])


def test_alpha_beta_exact():
    rng = np.random.default_rng(0)
    rb = rng.normal(0.0003, 0.01, 500)
    rp = 0.0002 + 1.2 * rb
    idx = pd.bdate_range("2020-01-01", periods=501)
    bench = pd.Series(np.r_[1.0, np.cumprod(1 + rb)], index=idx)
    nav = pd.Series(np.r_[1e7, 1e7 * np.cumprod(1 + rp)], index=idx)
    ab = alpha_beta(nav, bench)
    assert ab["beta"] == pytest.approx(1.2, abs=1e-9)
    assert ab["alpha_ann"] == pytest.approx(0.0002 * 252, abs=1e-9)
    for k in ("alpha_ann", "beta", "excess_cagr", "tracking_error", "info_ratio", "corr"):
        assert k in ab


def test_alpha_beta_aligns_dates():
    idx = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(1)
    bench = pd.Series(np.cumprod(1 + rng.normal(0, 0.01, 300)), index=idx)
    nav = bench.iloc[50:200] * 3.0
    ab = alpha_beta(nav, bench)
    assert ab["beta"] == pytest.approx(1.0)
    assert ab["alpha_ann"] == pytest.approx(0.0, abs=1e-12)


def test_benchmark_table():
    idx = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(2)
    b = pd.DataFrame({"000906.SH": np.cumprod(1 + rng.normal(0, 0.01, 300))}, index=idx)
    b["000906.SH_TR"] = b["000906.SH"] * np.linspace(1, 1.06, 300)
    nav = b["000906.SH"] * 2
    t = benchmark_table(nav, b)
    assert list(t.index) == ["000906.SH", "000906.SH_TR"]
    assert t.loc["000906.SH", "beta"] == pytest.approx(1.0)
    assert t.loc["000906.SH_TR", "excess_cagr"] < 0
