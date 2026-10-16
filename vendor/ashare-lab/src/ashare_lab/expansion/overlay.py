"""月末配置、次日收盘成交，保留分仓价格漂移。"""

import numpy as np
import pandas as pd


def inverse_vol_weights(returns, t, window=60):
    history = returns.loc[:t]
    samples = [history[c].dropna().iloc[-window:] for c in history]
    equal = pd.Series(1 / len(history.columns), index=history.columns)
    if min(map(len, samples)) < 20:
        return equal
    sigma = pd.Series([s.std(ddof=1) for s in samples], index=history.columns)
    # 零波动资产的逆波动率极限：仅在这些资产之间等权。
    zero = sigma <= np.finfo(float).eps
    if zero.any():
        return zero.astype(float) / zero.sum()
    inv = 1 / sigma
    return inv / inv.sum()


def run_allocation(prices, signals, weight_function, cost=0.0005, vol_target=None, history=None):
    """target 记录成交日；exposure 记录收盘信号，下一交易日生效。"""
    prices = prices.sort_index()
    signals = pd.DatetimeIndex(signals).sort_values()
    dates = prices.index
    observed = prices if history is None else pd.concat([history.loc[history.index < dates[0]], prices])
    returns = observed.pct_change(fill_method=None)
    if prices.loc[dates].isna().any().any():
        raise ValueError("配置期间分仓价格缺失")
    holdings = np.zeros(len(prices.columns))
    cash, exposure, traded_total = 1.0, 1.0, 0.0
    weights, pending = None, None
    navs, exposures, targets = [], [], []
    for i, t in enumerate(dates):
        if i:
            holdings *= 1 + returns.loc[t].to_numpy()
        value = cash + holdings.sum()
        if pending is not None:
            allocation = pending[0] * pending[1]
            traded = np.abs(value * allocation.to_numpy() - holdings).sum()
            traded_total += traded
            value -= cost * traded
            holdings = value * allocation.to_numpy()
            cash = value * (1 - allocation.sum())
            targets.append({"date": t, **pending[0].to_dict(), "exposure": pending[1]})
            pending = None
        navs.append(value)
        monthly = t in signals
        if monthly:
            weights = weight_function(t, returns.loc[:t]).reindex(prices.columns)
            if weights.isna().any() or (weights < 0).any() or not np.isclose(weights.sum(), 1):
                raise ValueError("目标权重须非负且合计为 1")
        new_exposure = exposure
        if vol_target is not None and weights is not None:
            history = returns.loc[:t].dropna().iloc[-vol_target.get("window", 60):]
            if len(history) >= 20:
                sigma = history.dot(weights).std(ddof=1) * np.sqrt(252)
                raw = min(1.0, vol_target.get("target_vol", 0.16) / sigma) if sigma > 0 else 1.0
                step = vol_target.get("step", 0.1)
                new_exposure = np.floor((raw + 1e-12) / step) * step
        if weights is not None and (monthly or not np.isclose(new_exposure, exposure)):
            pending = (weights.copy(), new_exposure)
        exposure = new_exposure
        exposures.append(exposure)
    nav = pd.Series(navs, index=dates, name="nav")
    target = pd.DataFrame(targets, columns=["date", *prices.columns, "exposure"]).set_index("date")
    return {"nav": nav, "target": target,
            "exposure": pd.Series(exposures, index=dates, name="exposure"),
            "turnover": traded_total / 2 / nav.mean() * 252 / max(1, len(nav) - 1)}
