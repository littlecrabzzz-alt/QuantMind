"""截面排名特征和次日开盘起算的远期标签。"""

import numpy as np
import pandas as pd

from ..factors import compute_factors


def rank_normalize(df: pd.DataFrame, fill: dict[str, float] | None = None) -> pd.DataFrame:
    defaults = {col: (fill or {}).get(col, 0.5) for col in df.columns}
    return df.groupby(level=0).rank(pct=True, method="average").fillna(defaults)


def make_labels(data, dates, horizon=20) -> pd.DataFrame:
    dates = pd.DatetimeIndex(dates)
    positions = data.calendar.get_indexer(dates)
    if (positions < 0).any():
        raise ValueError("Label dates must be trading dates")
    if horizon < 0:
        raise ValueError("horizon must be nonnegative")
    adjusted = data.open.ffill() * data.adj.ffill()
    returns = (adjusted.shift(-1 - horizon) / adjusted.shift(-1) - 1).loc[dates]
    ends = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = positions + 1 + horizon < len(data.calendar)
    ends[valid] = data.calendar.to_numpy()[positions[valid] + 1 + horizon]
    index = pd.MultiIndex.from_product([dates, data.close.columns], names=["date", "code"])
    return pd.DataFrame({"ret": returns.to_numpy().reshape(-1),
                         "label_end": np.repeat(ends, len(data.close.columns))}, index=index)


def make_dataset(data, dates, horizon=20) -> pd.DataFrame:
    dates = pd.DatetimeIndex(dates)
    ds = rank_normalize(compute_factors(data, dates), fill={"ep": 0.0})
    ds = ds.join(make_labels(data, dates, horizon))
    ds["y"] = ds["ret"].groupby(level=0).rank(pct=True, method="average")
    return ds
