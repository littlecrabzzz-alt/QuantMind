"""指数择时：收盘出信号、次日开盘切换仓位的模拟器与几条固定规则。"""

import numpy as np
import pandas as pd


def simulate(open_, close, signal, cost=0.0005, cash_rate=0.0) -> pd.DataFrame:
    """position_t = signal_{t-1}；隔夜按旧仓位，开盘换仓付费，盘中按新仓位。"""
    o = open_.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    p = np.r_[0.0, signal.to_numpy(dtype=float)[:-1]]
    nav = np.ones(len(c))
    for t in range(1, len(c)):
        overnight = 1 + p[t - 1] * (o[t] / c[t - 1] - 1)
        trade = 1 - cost * abs(p[t] - p[t - 1])
        intraday = 1 + p[t] * (c[t] / o[t] - 1)
        carry = 1 + (1 - p[t]) * cash_rate / 252
        nav[t] = nav[t - 1] * overnight * trade * intraday * carry
    return pd.DataFrame({"nav": nav, "position": p.astype(int)}, index=close.index)


def ma_rule(close, n) -> pd.Series:
    ma = close.rolling(n, min_periods=n).mean()
    return (close > ma).astype(int)


def rule_182_pe(close, pe, n=182, band=0.07, pe_max=20, ma=None) -> pd.Series:
    """空仓时低于均线且 PE 低于阈值买入；持仓时高于均线 (1+band) 卖出。"""
    if ma is None:
        ma = close.rolling(n, min_periods=n).mean()
    c, m, e = (s.to_numpy(dtype=float) for s in (close, ma, pe.reindex(close.index)))
    out = np.zeros(len(c), dtype=int)
    held = 0
    for t in range(len(c)):
        if held == 0 and c[t] < m[t] and e[t] < pe_max:
            held = 1
        elif held == 1 and c[t] > m[t] * (1 + band):
            held = 0
        out[t] = held
    return pd.Series(out, index=close.index)


def _dip(close, a1, a2):
    return ((close / close.shift(1) - 1 <= -a1) | (close / close.shift(2) - 1 <= -a2)).to_numpy()


def rule_ma_dip_exit(close, a1, a2, n=250, trend=None) -> pd.Series:
    trend = ma_rule(close, n) if trend is None else trend
    return pd.Series(((trend.to_numpy() == 1) & ~_dip(close, a1, a2)).astype(int), index=close.index)


def rule_ma_dip_buy(close, a1, a2, n=250, hold=5, trend=None) -> pd.Series:
    trend = ma_rule(close, n) if trend is None else trend
    window = pd.Series(_dip(close, a1, a2).astype(float), index=close.index)
    recent = window.rolling(hold, min_periods=1).max().to_numpy() > 0
    return pd.Series(((trend.to_numpy() == 1) | recent).astype(int), index=close.index)


def trade_stats(position, nav) -> dict:
    """一笔交易 = 连续持仓一段；收益按离场当天（首个空仓日）与入场前一天的净值。"""
    p = position.to_numpy()
    v = nav.to_numpy(dtype=float)
    returns, t = [], 0
    while t < len(p):
        if p[t] == 1:
            start = t
            while t < len(p) and p[t] == 1:
                t += 1
            end = t if t < len(p) else len(p) - 1
            returns.append(v[end] / v[start - 1] - 1 if start > 0 else v[end] / v[start] - 1)
        else:
            t += 1
    r = np.array(returns)
    wins, losses = r[r > 0], r[r <= 0]
    payoff = wins.mean() / abs(losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else np.nan
    return {"n_trades": len(r), "win_rate": float((r > 0).mean()) if len(r) else np.nan,
            "payoff": float(payoff)}


def index_ep(weights, ep) -> float:
    ep = ep.reindex(weights.index)
    valid = ep.notna()
    return float((weights[valid] * ep[valid]).sum() / weights[valid].sum())


def rel_underperf_years(strat_nav, hold_nav) -> float:
    ratio = (strat_nav / hold_nav).to_numpy(dtype=float)
    under = ratio < np.maximum.accumulate(ratio) - 1e-12
    edges = np.flatnonzero(np.r_[True, ~under, True])
    return float(np.max(np.diff(edges) - 1) / 252)
