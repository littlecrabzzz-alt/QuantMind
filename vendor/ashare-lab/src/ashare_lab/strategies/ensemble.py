"""月末固定构成的波动率集成，以及只用历史净值的年度重选。"""

import numpy as np
import pandas as pd

from .. import metrics
from ..strategy import Strategy


def neighbourhood(name, coords):
    """自身和仅一个维度相差一档的点，保留网格顺序。"""
    point = coords[name]
    return [key for key, other in coords.items()
            if len(other) == len(point)
            and sum(abs(a - b) for a, b in zip(point, other)) <= 1]


class EnsembleVolTarget(Strategy):
    """基础权重只在共同调仓日更新，每日仓位取成员均值。"""

    name = "ensemble"

    def __init__(self, members):
        self.members = list(members)
        if not self.members:
            raise ValueError("members 不能为空")
        self._weights = {}

    def rebalance_dates(self, calendar):
        schedules = [pd.DatetimeIndex(member.rebalance_dates(calendar))
                     for member in self.members]
        if any(not dates.equals(schedules[0]) for dates in schedules[1:]):
            raise ValueError("集成成员必须具有相同调仓日")
        self._weights.clear()
        return schedules[0]

    def target_weights(self, t, data):
        t = pd.Timestamp(t)
        if t not in self._weights:
            history = data.truncate(t)
            weights = pd.concat([member.target_weights(t, history)
                                 for member in self.members], axis=1).fillna(0.0)
            exposures = np.array([member.exposure(t, history) for member in self.members])
            self._weights[t] = (weights.mul(exposures, axis=1).sum(axis=1) / exposures.sum()
                                if exposures.sum() > 0 else weights.mean(axis=1))
        return self._weights[t].copy()

    def exposure(self, t, data):
        history = data.truncate(t)
        return float(np.mean([member.exposure(t, history) for member in self.members]))


class AnnualReselect(Strategy):
    """年末收盘选参、次日执行；全年委托给选中的成员。"""

    name = "reselect"

    def __init__(self, members, grid_nav, coords, default, lookback=756):
        self.members = dict(members)
        self.grid_nav = grid_nav
        self.coords = coords
        self.default = default
        self.lookback = lookback
        if default not in members or set(grid_nav.columns) != set(members):
            raise ValueError("网格净值、成员和默认配置必须对应")
        if set(coords) != set(members) or lookback < 1:
            raise ValueError("coords 必须覆盖全部成员，lookback 必须为正")
        self._year_ends = None
        self._choices = {}

    def rebalance_dates(self, calendar):
        calendar = pd.DatetimeIndex(calendar)
        self._year_ends = calendar[~calendar.year.duplicated(keep="last")]
        self._choices.clear()
        dates = self._year_ends
        for member in self.members.values():
            dates = dates.union(member.rebalance_dates(calendar))
        return dates.sort_values()

    def selection(self, t):
        if self._year_ends is None:
            raise RuntimeError("必须先用完整日历调用 rebalance_dates")
        ends = self._year_ends[self._year_ends <= pd.Timestamp(t)]
        if ends.empty:
            return self.default
        end = ends[-1]
        if end not in self._choices:
            window = self.grid_nav.loc[:end].tail(self.lookback + 1)
            choice = self.default
            if len(window) >= self.lookback + 1:
                calmars = {name: metrics.calmar(window[name]) for name in window}
                scores = {name: np.mean([calmars[other]
                                        for other in neighbourhood(name, self.coords)])
                          for name in window}
                # 未定义的 Calmar 不参与排名；全未定义时保留固定配置。
                defined = [name for name in window if not np.isnan(scores[name])]
                if defined:
                    choice = max(defined, key=scores.__getitem__)
            self._choices[end] = choice
        return self._choices[end]

    def target_weights(self, t, data):
        return self.members[self.selection(t)].target_weights(t, data.truncate(t))

    def exposure(self, t, data):
        return self.members[self.selection(t)].exposure(t, data.truncate(t))
