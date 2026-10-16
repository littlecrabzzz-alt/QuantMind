"""低波动选股与指数均线择时。"""

from dataclasses import dataclass, replace
from math import ceil

import numpy as np
import pandas as pd

from ..data.market import MarketData
from ..strategy import Strategy, month_end_dates
from ..universe import eligible


def _seeded_window(frame, start, stop, codes):
    """只复制窗口；首行缺失时补入窗口之前最后一个有效值。"""
    window = frame.iloc[start:stop].loc[:, codes].copy()
    if start and len(window):
        for code in window.columns[window.iloc[0].isna()]:
            previous = frame[code].iloc[:start]
            last = previous.last_valid_index()
            if last is not None:
                window.loc[window.index[0], code] = previous.loc[last]
    return window


@dataclass
class LowVolTrend(Strategy):
    universe: str = "000906.SH"
    select: str = "lowvol"
    vol_window: int = 120
    min_obs_ratio: float = 0.8
    top_n: int = 50
    min_list_days: int = 250
    amount_window: int = 20
    min_amount: float = 5e7
    timing_index: str | None = "000906.SH"
    ma_window: int = 120
    low_exposure: float = 0.0
    rebalance: str = "month_end"
    seed: int = 0

    @property
    def name(self) -> str:
        name = f"{self.select}_W{self.vol_window}_N{self.top_n}"
        if self.timing_index is not None:
            name += f"_L{self.ma_window}_e{self.low_exposure:g}"
        return name

    def rebalance_dates(self, calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
        if self.rebalance == "month_end":
            return month_end_dates(calendar)
        if self.rebalance == "mid_month":
            eligible = calendar[calendar.day >= 15]
            return eligible[~eligible.to_period("M").duplicated()]
        raise ValueError(f"Unknown rebalance: {self.rebalance}")

    def candidate_volatility(self, t: pd.Timestamp, data: MarketData,
                             codes: pd.Index | None = None) -> pd.Series:
        """返回可选股票的有效波动率，索引按代码排序。"""
        t = pd.Timestamp(t)
        stop = data.calendar.searchsorted(t, side="right")
        if codes is None:
            mask = eligible(t, data, self.universe, self.min_list_days,
                            self.amount_window, self.min_amount)
            codes = mask.index[mask].sort_values()
        if codes.empty:
            return pd.Series(dtype=float)

        start = max(0, stop - self.vol_window - 1)
        close = _seeded_window(data.close, start, stop, codes)
        adj = _seeded_window(data.adj, start, stop, codes)
        adjusted = replace(data, close=close, adj=adj).adj_close()
        returns = np.log(adjusted).diff().where(
            data.close.iloc[start:stop].loc[:, codes].notna()
        ).tail(self.vol_window)
        valid = returns.count() >= ceil(self.min_obs_ratio * self.vol_window)
        return returns.std(ddof=1)[valid].dropna()

    def target_weights(self, t: pd.Timestamp, data: MarketData) -> pd.Series:
        t = pd.Timestamp(t)
        mask = eligible(t, data, self.universe, self.min_list_days,
                        self.amount_window, self.min_amount)
        codes = mask.index[mask].sort_values()
        if codes.empty:
            return pd.Series(dtype=float)
        volatility = self.candidate_volatility(t, data, codes)

        if self.select in ("lowvol", "highvol"):
            selected = volatility.sort_values(
                ascending=self.select == "lowvol", kind="stable"
            ).index[:self.top_n]
        elif self.select == "all":
            selected = volatility.index
        elif self.select == "random":
            rng = np.random.default_rng(self.seed * 100003 + t.toordinal())
            selected = rng.choice(
                volatility.index, size=min(self.top_n, len(volatility)), replace=False
            )
        else:
            raise ValueError(f"Unknown selection: {self.select}")
        if not len(selected):
            return pd.Series(dtype=float)
        return pd.Series(1.0 / len(selected), index=selected)

    def exposure(self, t: pd.Timestamp, data: MarketData) -> float:
        if self.timing_index is None:
            return 1.0
        history = data.index_close[self.timing_index].loc[:t].dropna()
        if len(history) < self.ma_window:
            return 1.0
        return 1.0 if history.iloc[-1] > history.iloc[-self.ma_window:].mean() else self.low_exposure
