"""组合对称交叉验证（CSCV）的回测过拟合概率（PBO）。"""

from itertools import combinations

import numpy as np
import pandas as pd


def cscv_pbo(returns: pd.DataFrame, n_blocks: int = 16) -> dict:
    """用连续时间块的全部对称切分评估样本内选参的样本外排名。"""
    clean = returns.dropna(how="any")
    n_obs, n_configs = clean.shape
    if not isinstance(n_blocks, (int, np.integer)) or n_blocks < 2 or n_blocks % 2:
        raise ValueError("n_blocks 必须为至少 2 的偶数")
    if n_configs < 2:
        raise ValueError("至少需要 2 个配置")
    if n_obs < 2 * n_blocks:
        raise ValueError("每块至少需要 2 行有效观测")

    values = clean.to_numpy(dtype=float)
    blocks = np.array_split(np.arange(n_obs), n_blocks)
    counts = np.array([len(block) for block in blocks])
    sums = np.array([values[block].sum(axis=0) for block in blocks])
    squares = np.array([(values[block] ** 2).sum(axis=0) for block in blocks])
    total_sum, total_square = sums.sum(axis=0), squares.sum(axis=0)

    def sharpe(total, square, count):
        variance = np.maximum((square - total ** 2 / count) / (count - 1), 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return total / count / np.sqrt(variance) * np.sqrt(252)

    splits = list(combinations(range(n_blocks), n_blocks // 2))
    n_splits = len(splits)
    logits = np.empty(n_splits)
    is_metric = np.empty(n_splits)
    oos_metric = np.empty(n_splits)
    selected = np.empty(n_splits, dtype=int)
    for i, split in enumerate(splits):
        indices = list(split)
        count = counts[indices].sum()
        total = sums[indices].sum(axis=0)
        square = squares[indices].sum(axis=0)
        inside = sharpe(total, square, count)
        outside = sharpe(total_sum - total, total_square - square, n_obs - count)
        winner = int(np.nanargmax(inside))  # 平手按原始列顺序选第一列。
        selected[i] = winner
        is_metric[i], oos_metric[i] = inside[winner], outside[winner]
        # 升序平均排名：严格更小者数量 + 平手排名区间的中点。
        rank = (outside < outside[winner]).sum() + ((outside == outside[winner]).sum() + 1) / 2
        omega = rank / (n_configs + 1)
        logits[i] = np.log(omega / (1 - omega))

    centered_is = is_metric - is_metric.mean()
    denominator = centered_is @ centered_is
    slope = (centered_is @ (oos_metric - oos_metric.mean()) / denominator
             if denominator > 0 else np.nan)
    return {
        "pbo": float(np.mean(logits <= 0)),
        "logits": logits,
        "selected": pd.Series(clean.columns.take(selected)),
        "is_metric": is_metric,
        "oos_metric": oos_metric,
        "splits": splits,
        "n_splits": n_splits,
        "n_obs": n_obs,
        "prob_oos_loss": float(np.mean(oos_metric < 0)),
        "degradation_slope": float(slope),
    }
