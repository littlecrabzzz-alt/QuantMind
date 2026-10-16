"""公告日 PIT 多因子打分与带排名缓冲的等权选股。"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .strategies.lowvol_trend import LowVolTrend
from .strategy import Strategy
from .universe import eligible


GROUPS = {
    "lowvol": {"vol_250": -1},
    "quality": {"roe_ttm": 1, "gm_std": -1},
    "value": {"ep": 1, "bp": 1, "dy": 1},
}


def gm_std(fund, d, naive=False, n=8, min_obs=4):
    """同一可见快照内，最近 n 个有效 TTM 毛利率的样本标准差。"""
    snapshot = fund.asof("income", d, naive=naive)
    snapshot["revenue"] = snapshot.revenue.fillna(snapshot.total_revenue)
    # _ttm 的 lookup 同时支持所有报告期，避免逐股票、逐报告期循环。
    periods = snapshot.reset_index("end_date")
    revenue = fund._ttm(snapshot, periods, "revenue")
    cost = fund._ttm(snapshot, periods, "oper_cost")
    margins = ((revenue - cost) / revenue.where(revenue > 0)).replace(
        [np.inf, -np.inf], np.nan
    )
    recent = margins.dropna().groupby(level="code", sort=False).tail(n)
    grouped = recent.groupby(level="code", sort=False)
    result = grouped.std(ddof=1).where(grouped.count() >= min_obs)
    return result.reindex(periods.index.unique()).rename("gm_std")


def value_factors(fund, d, total_mv, naive=False):
    """市值从万元转元；保留负盈利、负净资产对应的估值因子。"""
    mv = total_mv[(total_mv > 0) & np.isfinite(total_mv)] * 1e4
    earnings = fund.ttm("n_income_attr_p", d, naive=naive).reindex(mv.index)
    equity = fund.latest("balance", d, naive=naive).total_hldr_eqy_exc_min_int
    return pd.DataFrame({"ep": earnings / mv, "bp": equity.reindex(mv.index) / mv})


def compute_b3_factors(data, fund, dates, universe="000906.SH", vol_window=250,
                       min_list_days=250, naive=False):
    lowvol = LowVolTrend(universe=universe, vol_window=vol_window,
                        min_list_days=min_list_days, timing_index=None)
    frames = []
    dates = pd.DatetimeIndex(dates)
    for t in dates:
        history = data.truncate(t)
        mask = eligible(t, history, universe, min_list_days,
                        lowvol.amount_window, lowvol.min_amount)
        codes = mask.index[mask].sort_values().rename("code")
        frame = pd.DataFrame(index=codes)
        frame["vol_250"] = lowvol.candidate_volatility(t, history)
        frame["roe_ttm"] = fund.roe_ttm(t, naive=naive)
        frame["gm_std"] = gm_std(fund, t, naive=naive)
        values = value_factors(fund, t, history.extra["total_mv"].loc[t], naive=naive)
        frame[["ep", "bp"]] = values.reindex(codes)
        frame["dy"] = history.extra["dv_ttm"].loc[t].reindex(codes).fillna(0)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(index=pd.MultiIndex.from_arrays([[], []], names=["date", "code"]),
                            columns=["vol_250", "roe_ttm", "gm_std", "ep", "bp", "dy"],
                            dtype=float)
    return pd.concat(frames, keys=dates, names=["date", "code"])


def composite(factors, groups):
    """截面内定向排名，先组内均值再组间均值；所有组必须有值。"""
    scores = {}
    for group in groups:
        directions = pd.Series(GROUPS[group])
        ranked = factors[directions.index].mul(directions).groupby(level="date").rank(
            pct=True, method="average"
        )
        scores[group] = ranked.mean(axis=1)
    return pd.DataFrame(scores, index=factors.index).mean(axis=1, skipna=False).rename("score")


@dataclass
class BufferScoreStrategy(Strategy):
    scores: pd.Series
    top_n: int = 50
    keep_rank: int = 100
    universe: str = "000906.SH"
    min_list_days: int = 250
    label: str = "buffer"
    _selected: pd.Index = field(default_factory=lambda: pd.Index([]), init=False, repr=False)

    @property
    def name(self):
        return self.label

    def rebalance_dates(self, calendar):
        return pd.DatetimeIndex(self.scores.index.get_level_values("date").unique()).intersection(
            calendar
        ).sort_values()

    def target_weights(self, t, data):
        t = pd.Timestamp(t)
        if t not in self.scores.index.get_level_values("date"):
            return pd.Series(dtype=float)
        mask = eligible(t, data, self.universe, self.min_list_days)
        ranked = self.scores.loc[t].reindex(mask.index[mask]).dropna().sort_index().sort_values(
            ascending=False, kind="stable"
        ).index
        kept = ranked[:self.keep_rank]
        kept = kept[kept.isin(self._selected)][:self.top_n]
        fill = ranked[~ranked.isin(kept)][:max(0, self.top_n - len(kept))]
        self._selected = kept.append(fill)
        if self._selected.empty:
            return pd.Series(dtype=float)
        return pd.Series(1.0 / len(self._selected), index=self._selected)
