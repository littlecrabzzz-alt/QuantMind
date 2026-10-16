"""按年份滚动训练，并在训练与验证边界清除重叠标签。"""

from collections.abc import Callable, Iterable
from typing import Protocol

import numpy as np
import pandas as pd

from ..factors import FACTOR_NAMES
from .evaluate import ic_series


class Model(Protocol):
    info: dict

    def fit(self, X_train, y_train, X_valid, y_valid): ...
    def predict(self, X) -> np.ndarray: ...


def walk_forward(ds: pd.DataFrame, make_model: Callable[[], Model],
                 years: Iterable[int], train_years=4, features=FACTOR_NAMES):
    dates = ds.index.get_level_values(0)
    predictions, diagnostics = [], []
    columns = ["year", "n_train", "n_valid", "train_ic", "valid_ic", "train_end", "valid_end"]
    for year in years:
        pred = ds.loc[dates.year == year]
        if pred.empty:
            continue
        t_star = pred.index.get_level_values(0).min()
        known = ds["label_end"].le(t_star) & ds["y"].notna()
        valid = ds.loc[(dates.year == year - 1) & known]
        if valid.empty:
            continue
        valid_start = valid.index.get_level_values(0).min()
        train = ds.loc[(dates.year >= year - 1 - train_years)
                       & (dates.year < year - 1) & known & ds["label_end"].lt(valid_start)]
        if train.empty:
            continue
        model = make_model().fit(train[list(features)], train["y"], valid[list(features)], valid["y"])
        predictions.append(pd.Series(model.predict(pred[list(features)]), index=pred.index, name="score"))
        row = {"year": year, "n_train": len(train), "n_valid": len(valid),
               "train_end": train["label_end"].max(), "valid_end": valid["label_end"].max()}
        for name, subset in (("train", train), ("valid", valid)):
            score = pd.Series(model.predict(subset[list(features)]), index=subset.index)
            row[f"{name}_ic"] = ic_series(score, subset["y"]).mean()
        row.update({key: value for key, value in model.info.items() if np.isscalar(value)})
        diagnostics.append(row)
    scores = (pd.concat(predictions).sort_index() if predictions
              else pd.Series(index=ds.index[:0], dtype=float, name="score"))
    diag = pd.DataFrame(diagnostics) if diagnostics else pd.DataFrame(columns=columns)
    return scores, diag
