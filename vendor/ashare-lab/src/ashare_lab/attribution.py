"""日简单收益的单因子 OLS 归因。"""

import numpy as np
import pandas as pd


def alpha_beta(nav, bench_nav) -> dict:
    paired = pd.concat(
        [nav.pct_change(fill_method=None).rename("portfolio"),
         bench_nav.pct_change(fill_method=None).rename("benchmark")],
        axis=1, join="inner",
    ).dropna()
    result = dict(alpha=np.nan, beta=np.nan, r2=np.nan, resid_vol=np.nan,
                  n_obs=len(paired))
    if len(paired) < 20:
        return result
    y, x = paired["portfolio"], paired["benchmark"]
    dx, dy = x - x.mean(), y - y.mean()
    variance = float(dx @ dx)
    if variance == 0:
        return result
    beta = float(dx @ dy / variance)
    intercept = float(y.mean() - beta * x.mean())
    residual = y - intercept - beta * x
    total = float(dy @ dy)
    result.update(alpha=intercept * 252, beta=beta,
                  r2=float(1 - (residual @ residual) / total) if total > 0 else np.nan,
                  resid_vol=float(residual.std(ddof=1) * np.sqrt(252)))
    return result
