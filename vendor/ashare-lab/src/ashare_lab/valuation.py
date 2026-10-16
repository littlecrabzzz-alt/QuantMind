"""月末估值及只使用当期和历史观测的滚动分位。"""

import numpy as np
import pandas as pd


def monthly_valuation(data, dates):
    """读取指定交易日估值；亏损、非正估值及缺失值不参与排名。"""
    dates = pd.DatetimeIndex(dates)
    result = {}
    for metric, field in (("pe", "pe_ttm"), ("pb", "pb")):
        panel = data.extra[field].reindex(index=dates, columns=data.close.columns)
        result[metric] = panel.where(panel > 0)
    return result


def hist_percentile(panel, window, min_obs):
    """最近 window 期内 ≤ 当期值的有效观测占比，包含当期和平值。"""
    if window < 1 or min_obs < 1:
        raise ValueError("window and min_obs must be positive")
    values = panel.to_numpy(dtype=float)
    result = np.full(values.shape, np.nan)
    for i, current in enumerate(values):
        history = values[max(0, i - window + 1):i + 1]
        count = (~np.isnan(history)).sum(axis=0)
        valid = ~np.isnan(current) & (count >= min_obs)
        result[i, valid] = (history <= current).sum(axis=0)[valid] / count[valid]
    return pd.DataFrame(result, index=panel.index, columns=panel.columns)
