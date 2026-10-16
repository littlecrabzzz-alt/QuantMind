"""按基础组合实现波动率调节仓位，收盘信号由引擎次日执行。"""

from dataclasses import dataclass, field, replace
from math import floor, sqrt

import numpy as np
import pandas as pd

from ..data.market import MarketData
from ..strategy import Strategy
from .lowvol_trend import _seeded_window


@dataclass
class VolTarget(Strategy):
    base: Strategy
    target_vol: float = 0.10
    window: int = 20
    step: float = 0.1
    max_exposure: float = 1.0
    cut_delay: int = 0
    cut_scale: float = 1.0
    downside: bool = False
    _weights: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _raw: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _dates: pd.DatetimeIndex | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        if not self.target_vol > 0 or not self.window >= 2:
            raise ValueError("target_vol 必须 > 0，window 必须 >= 2")
        if not self.step >= 0 or not 0 < self.max_exposure <= 1:
            raise ValueError("step 必须 >= 0，max_exposure 必须在 (0, 1] 内")
        if self.cut_delay < 0 or not 0 < self.cut_scale <= 1:
            raise ValueError("cut_delay 必须 >= 0，cut_scale 必须在 (0, 1] 内")

    @property
    def name(self) -> str:
        name = f"{self.base.name}_vt{self.target_vol*100:g}_L{self.window}_s{self.step:g}"
        if self.cut_delay:
            name += f"_d{self.cut_delay}"
        if self.cut_scale != 1.0:
            name += f"_h{self.cut_scale:g}"
        if self.downside:
            name += "_dn"
        return name

    def rebalance_dates(self, calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
        # 引擎先提供完整交易日程；截断日历的最后一天不一定是真正月末。
        self._dates = self.base.rebalance_dates(calendar)
        return self._dates

    def target_weights(self, t: pd.Timestamp, data: MarketData) -> pd.Series:
        t = pd.Timestamp(t)
        if t not in self._weights:
            self._weights[t] = self.base.target_weights(t, data.truncate(t))
        return self._weights[t]

    def exposure(self, t: pd.Timestamp, data: MarketData) -> float:
        t = pd.Timestamp(t)
        stop = data.calendar.searchsorted(t, side="right")
        days = data.calendar[max(0, stop - self.cut_delay - 1):stop]
        for day in days:
            if day not in self._raw:
                self._raw[day] = self._raw_exposure(day, data.truncate(day))
        raw = max((self._raw[day] for day in days), default=self.max_exposure)
        if self.cut_scale != 1.0:
            raw = self.max_exposure - self.cut_scale * (self.max_exposure - raw)
        return floor(raw / self.step + 1e-9) * self.step if self.step > 0 else raw

    def _raw_exposure(self, t: pd.Timestamp, data: MarketData) -> float:
        dates = self._dates
        if dates is None:
            dates = self.base.rebalance_dates(data.calendar)
        dates = dates[dates <= t]
        if dates.empty:
            return self.max_exposure
        weights = self.target_weights(dates.max(), data)
        total = weights.sum()
        if weights.empty or total <= 0:
            return self.max_exposure
        stop = data.calendar.searchsorted(t, side="right")
        if stop < self.window + 1:
            return self.max_exposure
        start = stop - self.window - 1
        # 仅复制篮子成员的短窗口，并从此前历史补齐窗口首日的缺失值。
        close = _seeded_window(data.close, start, stop, weights.index)
        adj = _seeded_window(data.adj, start, stop, weights.index)
        prices = replace(data, close=close, adj=adj).adj_close()
        returns = np.log(prices).diff().iloc[1:].fillna(0.0)
        portfolio = returns.to_numpy() @ (weights / total).to_numpy()
        sigma = float(
            sqrt(2) * sqrt(np.mean(np.minimum(portfolio, 0) ** 2)) * sqrt(252)
            if self.downside else np.std(portfolio, ddof=1) * sqrt(252)
        )
        if sigma == 0:
            return self.max_exposure
        return min(self.max_exposure, self.target_vol / sigma)
