"""月度 Rank IC 和分组收益。"""

import numpy as np
import pandas as pd


def ic_series(scores: pd.Series, y: pd.Series) -> pd.Series:
    aligned = pd.concat([scores.rename("score"), y.rename("y")], axis=1).reindex(scores.index)
    values = {}
    for date, group in aligned.groupby(level=0, sort=True):
        group = group.dropna()
        ranks = group.rank(method="average")
        values[date] = (ranks["score"].corr(ranks["y"])
                        if len(group) >= 10 and ranks.nunique().min() > 1 else np.nan)
    return pd.Series(values, dtype=float, name="ic").rename_axis("date")


def ic_summary(ic) -> dict:
    ic = ic.dropna()
    mean, std, n = ic.mean(), ic.std(ddof=1), len(ic)
    return {"mean": mean, "std": std,
            "icir": mean / std * np.sqrt(12) if std > 0 else np.nan,
            "t": mean / std * np.sqrt(n) if std > 0 else np.nan,
            "hit": (ic > 0).mean(), "n": n}


def quantile_returns(scores, ret, q=5) -> pd.DataFrame:
    aligned = pd.concat([scores.rename("score"), ret.rename("ret")], axis=1).reindex(scores.index)
    rows = {}
    for date, group in aligned.groupby(level=0, sort=True):
        group = group.dropna(subset=["score"]).sort_index()
        # Stable code order breaks ties without letting future returns influence bins.
        bins = np.ceil(group["score"].rank(method="first", pct=True) * q).astype(int)
        rows[date] = group["ret"].groupby(bins).mean().reindex(range(1, q + 1))
    return pd.DataFrame.from_dict(rows, orient="index", columns=range(1, q + 1)).rename_axis("date")
