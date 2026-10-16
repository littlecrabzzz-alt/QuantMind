"""510300 日历规则。holdings[d] 表示持有前收盘至 d 收盘的收益。"""

import pandas as pd


def calendar_holdings(calendar, rule):
    calendar = pd.DatetimeIndex(calendar)
    tom = pd.Series(False, index=calendar)
    holiday = tom.copy()
    for month in calendar.to_period("M").unique():
        days = calendar[calendar.to_period("M") == month]
        if len(days) >= 2:
            tom.loc[days[-1]] = True
        tom.loc[days[:3]] = True
    # 首月前 3 日没有可观察的上月收盘入场，不能凭空持仓。
    if len(calendar):
        tom.loc[calendar[calendar.to_period("M") == calendar[0].to_period("M")][:3]] = False
    for i in range(2, len(calendar) - 1):
        if (calendar[i + 1] - calendar[i]).days >= 4:
            holiday.iloc[i - 1:i + 1] = True
    if rule == "tom":
        return tom
    if rule == "preholiday":
        return holiday
    if rule == "union":
        return tom | holiday
    raise ValueError(f"Unknown calendar rule: {rule}")


def calendar_nav(open_, close, holdings, cost=0.00075, overnight=False):
    if not 0 <= cost < 1:
        raise ValueError("cost 必须在 [0,1) 内")
    close = close.astype(float)
    if close.isna().any() or (close <= 0).any():
        raise ValueError("缺少有效复权收盘价")
    if overnight:
        open_ = open_.reindex(close.index)
        if open_.isna().any() or (open_ <= 0).any():
            raise ValueError("缺少有效复权开盘价")
        growth = open_ / close.shift(1) * (1 - cost) ** 2
        growth.iloc[0] = 1.0
        return growth.cumprod().rename("nav")
    hold = holdings.reindex(close.index).fillna(False).astype(bool).copy()
    hold.iloc[0] = False
    following = hold.shift(-1, fill_value=False)
    transitions = (hold != following).astype(int)
    growth = (1 + close.pct_change(fill_method=None).fillna(0).where(hold, 0)) * (1 - cost) ** transitions
    return growth.cumprod().rename("nav")
