"""S1：当前低波股票篮子与 ETF 的逆波动率配置。"""

from dataclasses import replace

import numpy as np
import pandas as pd

from ashare_lab.strategy import Strategy
from ashare_lab.strategies.lowvol_trend import _seeded_window


class InverseVolAllocation(Strategy):
    name = "s1_invvol_etf"

    def __init__(self, stock, sleeves, window=60, min_obs=20):
        if window < 2 or not 2 <= min_obs <= window:
            raise ValueError("需要 2 <= min_obs <= window")
        if "stock" in sleeves or len(set(sleeves.values())) != len(sleeves):
            raise ValueError("分仓名称不能为 stock，ETF 代码不能重复")
        self.stock = stock
        self.sleeves = dict(sleeves)
        self.window = window
        self.min_obs = min_obs
        self.last_sleeve_weights = pd.Series(dtype=float)

    def rebalance_dates(self, calendar):
        return self.stock.rebalance_dates(calendar)

    def target_weights(self, t, data):
        history = data.truncate(t)
        basket = self.stock.target_weights(t, history).astype(float)
        if len(basket) and basket.sum() > 0:
            basket = basket / basket.sum()
        codes = basket.index.union(pd.Index(list(self.sleeves.values())))
        stop = len(history.calendar)
        start = max(0, stop - self.window - 1)
        close = _seeded_window(history.close, start, stop, codes)
        adj = _seeded_window(history.adj, start, stop, codes)
        returns = replace(history, close=close, adj=adj).adj_close().pct_change(
            fill_method=None).tail(self.window)
        stock_returns = returns.reindex(columns=basket.index)
        sleeve_returns = pd.DataFrame({
            "stock": stock_returns.fillna(0).dot(basket).where(stock_returns.notna().any(axis=1)),
            **{name: returns[code] for name, code in self.sleeves.items()},
        })
        equal = pd.Series(1 / len(sleeve_returns.columns), index=sleeve_returns.columns)
        if (sleeve_returns.count() < self.min_obs).any():
            weights = equal
        else:
            sigma = sleeve_returns.std(ddof=1)
            zero = sigma <= np.finfo(float).eps
            if zero.any():
                weights = zero.astype(float) / zero.sum()
            else:
                inv = 1 / sigma
                weights = inv / inv.sum()
        self.last_sleeve_weights = weights.copy()
        return pd.concat([basket * weights["stock"], pd.Series(
            {code: weights[name] for name, code in self.sleeves.items()}, dtype=float)])

    def exposure(self, t, data):
        return 1.0
