"""按生效日查询历史行业归属，记录空档沿用最近分类。"""

import pandas as pd

UNCLASSIFIED = "未分类"


def industry_at(t, table, codes) -> pd.Series:
    index = pd.Index(codes)
    if table is None or table.empty:
        return pd.Series(UNCLASSIFIED, index=index, name="l1_name")
    dates = pd.to_datetime(table["in_date"])
    latest = (table.assign(in_date=dates).loc[dates <= pd.Timestamp(t)]
              .sort_values("in_date", kind="stable").drop_duplicates("code", keep="last"))
    return latest.set_index("code")["l1_name"].reindex(index).fillna(UNCLASSIFIED)
