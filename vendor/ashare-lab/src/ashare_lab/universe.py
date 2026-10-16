"""历史时点上的可选股票集合。"""

import pandas as pd


def eligible(t, data, universe="000906.SH", min_list_days=250,
             amount_window=20, min_amount=5e7) -> pd.Series:
    t = pd.Timestamp(t)
    stop = data.calendar.searchsorted(t, side="right")
    listed_days = stop - data.calendar.searchsorted(data.list_date)
    amount = data.amount.iloc[max(0, stop - amount_window):stop].fillna(0).mean()
    return (
        (pd.Series(True, index=data.close.columns) if universe == "all"
         else data.members[universe].loc[t])
        & ~data.is_st.loc[t]
        & ~data.suspended.loc[t]
        & data.close.loc[t].notna()
        & data.list_date.notna()
        & (listed_days >= min_list_days)
        & (amount >= min_amount)
    )
