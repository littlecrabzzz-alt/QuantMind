"""行业中性低波动选股，以及保留低波动行业配置的组合。"""

from dataclasses import dataclass, field
from math import floor

import pandas as pd

from ..data.market import MarketData
from ..industry import industry_at
from .lowvol_trend import LowVolTrend


@dataclass
class IndustryLowVol(LowVolTrend):
    industry: pd.DataFrame | None = field(default=None, repr=False, compare=False)
    weighting: str = "count"
    mode: str = "neutral"
    timing_index: str | None = None

    @property
    def name(self) -> str:
        prefix = f"indneutral_{self.weighting}" if self.mode == "neutral" else "indtilt"
        return f"{prefix}_W{self.vol_window}_N{self.top_n}"

    def target_weights(self, t: pd.Timestamp, data: MarketData) -> pd.Series:
        if self.mode not in ("neutral", "tilt"):
            raise ValueError(f"Unknown mode: {self.mode}")
        if self.weighting not in ("count", "cap"):
            raise ValueError(f"Unknown weighting: {self.weighting}")
        volatility = self.candidate_volatility(t, data)
        if volatility.empty:
            return pd.Series(dtype=float)
        groups = industry_at(t, self.industry, volatility.index)
        if self.mode == "tilt":
            selected = volatility.sort_values(kind="stable").index[:self.top_n]
            shares = groups.loc[selected].value_counts(normalize=True)
        elif self.weighting == "count":
            shares = groups.value_counts(normalize=True)
        else:
            history = data.extra["circ_mv"].loc[:pd.Timestamp(t)]
            cap = (history.iloc[-1].reindex(volatility.index).fillna(0)
                   if len(history) else pd.Series(0.0, index=volatility.index))
            shares = cap.groupby(groups).sum()
            if shares.sum() <= 0:
                return pd.Series(dtype=float)
            shares = shares / shares.sum()
        weights = []
        for group, share in shares.items():
            if share <= 0:
                continue
            members = volatility[groups == group]
            if self.mode == "neutral":
                count = min(len(members), max(1, floor(self.top_n * share + 0.5)))
                selected = members.sort_values(kind="stable").index[:count]
            else:
                selected = members.index
            weights.append(pd.Series(share / len(selected), index=selected))
        return pd.concat(weights) if weights else pd.Series(dtype=float)
