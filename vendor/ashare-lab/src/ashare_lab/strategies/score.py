"""在历史可选集合中按外部打分构建等权组合。"""

from dataclasses import dataclass

import pandas as pd

from ..strategy import Strategy
from ..universe import eligible


@dataclass
class ScoreStrategy(Strategy):
    scores: pd.Series
    top_n: int = 50
    label: str = "score"

    @property
    def name(self):
        return self.label

    def rebalance_dates(self, calendar):
        return pd.DatetimeIndex(self.scores.index.get_level_values(0).unique()).intersection(calendar).sort_values()

    def target_weights(self, t, data):
        if t not in self.scores.index.get_level_values(0):
            return pd.Series(dtype=float)
        mask = eligible(t, data)
        scores = self.scores.loc[t].reindex(mask.index[mask]).dropna().sort_index()
        selected = scores.sort_values(ascending=False, kind="stable").head(self.top_n).index
        return pd.Series(1 / len(selected), index=selected) if len(selected) else pd.Series(dtype=float)
