"""向后滚动计算原始因子，然后提取可选股票的月末截面。"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .data.market import MarketData
from .universe import eligible


FACTOR_NAMES = ["vol_250", "vol_20", "beta_250", "mom_12_1", "rev_20",
                "max_20", "log_mv", "ep", "bp", "dy", "turn_20", "illiq_20", "amt_ratio"]


def compute_factors(data: MarketData, dates: Sequence[pd.Timestamp],
                    market_index="000906.SH") -> pd.DataFrame:
    dates = pd.DatetimeIndex(dates)
    index = pd.MultiIndex.from_product([dates, data.close.columns], names=["date", "code"])
    result = pd.DataFrame(index=index, columns=FACTOR_NAMES, dtype=float)

    def save(name, frame):
        result[name] = frame.loc[dates].to_numpy().reshape(-1)

    adjusted = data.adj_close()
    r = np.log(adjusted).diff().where(data.close.notna())
    save("vol_250", r.rolling(250, min_periods=200).std(ddof=1))
    save("vol_20", r.rolling(20, min_periods=16).std(ddof=1))

    market = np.log(data.index_close[market_index]).diff()
    # Mask the market separately for every stock: covariance and variance must
    # use exactly the same paired observations, including suspension gaps.
    paired_r = r.where(market.notna(), axis=0)
    paired_market = pd.DataFrame(
        np.broadcast_to(market.to_numpy()[:, None], r.shape), index=r.index, columns=r.columns,
    ).where(paired_r.notna())
    cov = paired_r.rolling(250, min_periods=200).cov(paired_market, ddof=1)
    var = paired_market.rolling(250, min_periods=200).var(ddof=1)
    save("beta_250", cov / var.where(var > 0))
    del paired_r, paired_market, cov, var

    save("mom_12_1", np.log(adjusted.shift(20) / adjusted.shift(250)))
    save("rev_20", np.log(adjusted / adjusted.shift(20)))
    simple = np.expm1(r)
    save("max_20", simple.rolling(20, min_periods=16).max())
    save("log_mv", np.log(data.extra["total_mv"].where(data.extra["total_mv"] > 0)))
    for name, source in (("ep", "pe_ttm"), ("bp", "pb")):
        values = data.extra[source]
        save(name, 1 / values.where(values > 0))
    save("dy", data.extra["dv_ttm"].fillna(0))
    save("turn_20", data.extra["turnover_rate_f"].rolling(20, min_periods=1).mean())
    save("illiq_20", (simple.abs() / data.amount.where(data.amount > 0))
         .rolling(20, min_periods=1).mean() * 1e8)
    amount = data.amount.fillna(0)
    save("amt_ratio", amount.rolling(5, min_periods=1).mean()
         / amount.rolling(60, min_periods=1).mean().replace(0, np.nan))
    mask = np.concatenate([eligible(t, data).to_numpy() for t in dates]) if len(dates) else []
    return result.loc[mask]
