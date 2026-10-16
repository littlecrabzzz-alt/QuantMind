"""预登记的股票因子；信号仅使用截至 t 收盘的数据。"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..industry import UNCLASSIFIED, industry_at
from ..strategy import Strategy, month_end_dates
from ..universe import eligible
from .lowvol_trend import LowVolTrend


def week_end_dates(calendar):
    return calendar[~calendar.to_period("W-FRI").duplicated(keep="last")]


@dataclass
class FactorTopN(Strategy):
    factor: str = "ret"
    universe: str = "000906.SH"
    lookback: int = 63
    skip: int = 0
    highest: bool = True
    top_n: int = 50
    min_list_days: int = 250
    amount_window: int = 20
    min_amount: float = 5e7
    rebalance: str = "month_end"
    div_top: int = 100
    vol_window: int = 250
    top_k: int = 3
    industry_table: pd.DataFrame | None = None

    @property
    def name(self):
        return (f"{self.factor}_J{self.lookback}_skip{self.skip}_"
                f"{'high' if self.highest else 'low'}_N{self.top_n}_"
                f"{self.universe}_{self.rebalance}_D{self.div_top}_"
                f"W{self.vol_window}_K{self.top_k}")

    def rebalance_dates(self, calendar):
        if self.rebalance == "week_end":
            return week_end_dates(calendar)
        if self.rebalance == "month_end":
            return month_end_dates(calendar)
        raise ValueError(f"Unknown rebalance: {self.rebalance}")

    def scores(self, t, data):
        stop = data.calendar.searchsorted(pd.Timestamp(t), side="right")
        if self.factor in ("ret", "industry_ret"):
            end = stop - 1 - self.skip
            begin = end - self.lookback
            if begin < 0:
                return pd.Series(np.nan, index=data.close.columns)
            close = data.close.iloc[begin:end + 1]
            valid = (close.iloc[0].notna() & close.iloc[-1].notna()
                     & (close.iloc[1:].count() >= 0.8 * self.lookback))
            # close 两端有效；只需截至各端点的最近复权因子。
            def adjustment(row):
                values = data.adj.iloc[row].copy()
                missing = values.index[values.isna()]
                if len(missing):
                    values.loc[missing] = data.adj.loc[:, missing].iloc[:row + 1].ffill().iloc[-1]
                return values
            adj_end = adjustment(end)
            adj_begin = adjustment(begin)
            return (close.iloc[-1] * adj_end / (close.iloc[0] * adj_begin) - 1).where(valid)
        if self.factor == "total_mv":
            return data.extra["total_mv"].loc[t]
        if self.factor == "moneyflow":
            flow = data.extra["net_mf_amount"].loc[:t].tail(20)
            amount = data.amount.iloc[max(0, stop - 20):stop].sum()
            return (flow.sum() * 1e4 / amount).where((flow.count() >= 16) & (amount > 0))
        if self.factor == "div_lowvol":
            return data.extra["dv_ttm"].loc[t].where(data.extra["dv_ttm"].loc[t] > 0)
        raise ValueError(f"Unknown factor: {self.factor}")

    def target_weights(self, t, data):
        mask = eligible(t, data, self.universe, self.min_list_days,
                        self.amount_window, self.min_amount)
        codes = mask.index[mask].sort_values()
        if codes.empty:
            return pd.Series(dtype=float)
        score = self.scores(t, data).reindex(codes).replace([np.inf, -np.inf], np.nan).dropna()
        if self.factor == "industry_ret":
            groups = industry_at(t, self.industry_table, codes)
            means = score.groupby(groups.reindex(score.index)).mean()
            counts = groups.value_counts()
            means = means[(counts.reindex(means.index) >= 5) & (means.index != UNCLASSIFIED)]
            sectors = means.sort_index().sort_values(ascending=False, kind="stable").head(self.top_k).index
            if not len(sectors):
                return pd.Series(dtype=float)
            return pd.concat([pd.Series(1 / len(sectors) / (groups == sector).sum(),
                                        index=groups.index[groups == sector]) for sector in sectors])
        if self.factor == "div_lowvol":
            dividend = score.sort_values(ascending=False, kind="stable").head(self.div_top).index
            lowvol = LowVolTrend(vol_window=self.vol_window)
            score = lowvol.candidate_volatility(t, data, dividend).sort_index()
            ascending = True
        else:
            ascending = not self.highest
        selected = score.sort_values(ascending=ascending, kind="stable").head(self.top_n).index
        return pd.Series(1 / len(selected), index=selected) if len(selected) else pd.Series(dtype=float)
