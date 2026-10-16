"""社区观点复现：PE/PB 历史分位的验收测试。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.valuation import hist_percentile, monthly_valuation

from synth import make_data

M = pd.date_range("2015-01-31", periods=8, freq="ME")


def test_percentile_counts_values_at_or_below_current_including_itself():
    p = pd.DataFrame({"A": [5.0, 1.0, 3.0, 2.0, 4.0, 3.0, 6.0, 0.5]}, index=M)
    got = hist_percentile(p, window=4, min_obs=3)["A"]
    assert np.isnan(got.iloc[0]) and np.isnan(got.iloc[1])        # 不足 3 个观测
    assert got.iloc[2] == pytest.approx(2 / 3)                      # [5,1,3]：<=3 有 1,3
    assert got.iloc[3] == pytest.approx(2 / 4)                      # [5,1,3,2]：<=2 有 1,2
    assert got.iloc[4] == pytest.approx(4 / 4)                      # [1,3,2,4]
    assert got.iloc[5] == pytest.approx(3 / 4)                      # [3,2,4,3]：<=3 有 3,2,3
    assert got.iloc[6] == pytest.approx(4 / 4)
    assert got.iloc[7] == pytest.approx(1 / 4)


def test_missing_values_skipped_and_current_missing_gives_nan():
    p = pd.DataFrame({"A": [1.0, np.nan, 3.0, 2.0, np.nan, 5.0, 4.0, 1.5]}, index=M)
    got = hist_percentile(p, window=4, min_obs=3)["A"]
    assert np.isnan(got.iloc[2])                 # 窗口 [1, nan, 3] 只有 2 个有效
    assert got.iloc[3] == pytest.approx(2 / 3)   # [1, nan, 3, 2]
    assert np.isnan(got.iloc[4])                 # 当期缺失
    assert got.iloc[5] == pytest.approx(3 / 3)   # [3, 2, nan, 5]
    assert got.iloc[7] == pytest.approx(1 / 3)   # [nan, 5, 4, 1.5]


def test_no_lookahead_and_columns_independent():
    rng = np.random.default_rng(0)
    p = pd.DataFrame(rng.uniform(1, 10, (8, 3)), index=M, columns=list("ABC"))
    base = hist_percentile(p, window=5, min_obs=3)
    q = p.copy()
    q.iloc[6:] = 100.0
    q["C"] = 1.0
    other = hist_percentile(q, window=5, min_obs=3)
    pd.testing.assert_frame_equal(base.iloc[:6, :2], other.iloc[:6, :2])


def test_monthly_valuation_reads_t_and_drops_nonpositive():
    days = pd.bdate_range("2015-01-01", "2015-04-30")
    data = make_data(days, ["A", "B"])
    pe = pd.DataFrame(10.0, index=days, columns=["A", "B"])
    pe.loc["2015-02-27", "A"] = 12.0
    pe.loc["2015-03-02":, "A"] = 99.0          # t 之后的值不能用
    pe.loc[:, "B"] = np.nan                    # 亏损：Tushare pe_ttm 为空
    pb = pd.DataFrame(1.5, index=days, columns=["A", "B"])
    pb.loc["2015-02-27", "B"] = -0.5
    data.extra.update({"pe_ttm": pe, "pb": pb})
    dates = pd.DatetimeIndex(["2015-01-30", "2015-02-27"])
    v = monthly_valuation(data, dates)
    assert v["pe"].loc["2015-02-27", "A"] == 12.0
    assert np.isnan(v["pe"].loc["2015-02-27", "B"])
    assert np.isnan(v["pb"].loc["2015-02-27", "B"])
    assert v["pb"].loc["2015-01-30", "A"] == 1.5
    assert list(v["pe"].index) == list(dates)
