"""净值回撤、收益及交易成本指标。"""

import numpy as np
import pandas as pd

from .engine import BacktestResult


def drawdown_series(nav: pd.Series) -> pd.Series:
    """返回相对历史最高净值的回撤。"""
    return nav / nav.cummax() - 1


def max_drawdown(nav: pd.Series) -> float:
    """返回最大回撤，取负数。"""
    return float(drawdown_series(nav).min())


def max_drawdown_duration(nav: pd.Series) -> int:
    """返回低于前高的最长连续交易日数。"""
    underwater = drawdown_series(nav).to_numpy() < 0
    boundaries = np.flatnonzero(np.r_[True, ~underwater, True])
    return int(np.max(np.diff(boundaries) - 1))


def ulcer_index(nav: pd.Series) -> float:
    """返回小数口径的回撤均方根。"""
    return float(np.sqrt(drawdown_series(nav).pow(2).mean()))


def cagr(nav: pd.Series) -> float:
    """按每年 252 个交易日计算复合收益。"""
    if len(nav) < 2:
        return float("nan")
    return float((nav.iloc[-1] / nav.iloc[0]) ** (252 / (len(nav) - 1)) - 1)


def ann_vol(nav: pd.Series) -> float:
    """返回日简单收益的年化样本标准差。"""
    return float(nav.pct_change(fill_method=None).std(ddof=1) * np.sqrt(252))


def sharpe(nav: pd.Series) -> float:
    """返回无风险利率为零的夏普比率。"""
    returns = nav.pct_change(fill_method=None).dropna()
    std = returns.std(ddof=1)
    return float(returns.mean() / std * np.sqrt(252)) if std > 0 else float("nan")


def calmar(nav: pd.Series) -> float:
    """返回年化收益与最大回撤绝对值之比。"""
    mdd = max_drawdown(nav)
    return cagr(nav) / abs(mdd) if mdd != 0 else float("nan")


def annual_returns(nav: pd.Series) -> pd.Series:
    """按自然年计算收益，首年以首日净值为基准。"""
    year_end = nav.groupby(nav.index.year).last()
    previous = year_end.shift(1)
    if len(previous):
        previous.iloc[0] = nav.iloc[0]
    return year_end / previous - 1


def worst_month(nav: pd.Series) -> float:
    """丢弃空月份后，取月末净值收益的最小值。"""
    month_end = nav.groupby(nav.index.to_period("M")).last().dropna()
    return float(month_end.pct_change(fill_method=None).min())


def summary(result: BacktestResult) -> dict:
    """汇总净值指标和年化单边换手、费用、平均仓位。"""
    nav = result.nav
    scale = 252 / (len(nav) - 1) if len(nav) > 1 else float("nan")
    traded = result.trades.loc[result.trades["side"].isin(["buy", "sell"])]
    return {
        "max_drawdown": max_drawdown(nav),
        "drawdown_series": drawdown_series(nav),
        "max_drawdown_duration": max_drawdown_duration(nav),
        "ulcer_index": ulcer_index(nav),
        "cagr": cagr(nav),
        "ann_vol": ann_vol(nav),
        "sharpe": sharpe(nav),
        "calmar": calmar(nav),
        "annual_returns": annual_returns(nav),
        "worst_month": worst_month(nav),
        "turnover": float(traded["value"].sum() / 2 / nav.mean() * scale),
        "cost_ratio": float(traded["fee"].sum() / nav.mean() * scale),
        "avg_exposure": float(result.exposure.mean()),
    }
