"""合成数据工具：构造小型 MarketData 供引擎测试使用。"""
import numpy as np
import pandas as pd

from ashare_lab.data.market import MarketData
from ashare_lab.strategy import Strategy


def make_data(dates, codes, open_=10.0, close=10.0, delist=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    cols = list(codes)

    def full(v):
        return pd.DataFrame(float(v), index=idx, columns=cols)

    df_open, df_close = full(open_), full(close)
    data = MarketData(
        open=df_open,
        close=df_close,
        up_limit=df_close.shift(1).fillna(close) * 1.1,
        down_limit=df_close.shift(1).fillna(close) * 0.9,
        adj=full(1.0),
        volume=full(1e6),
        amount=full(1e7),
        suspended=pd.DataFrame(False, index=idx, columns=cols),
        is_st=pd.DataFrame(False, index=idx, columns=cols),
        list_date=pd.Series(pd.Timestamp("2000-01-01"), index=cols),
        delist_date=pd.Series(pd.NaT, index=cols, dtype="datetime64[ns]"),
        members={"IDX": pd.DataFrame(True, index=idx, columns=cols)},
        index_close=pd.DataFrame({"IDX": np.linspace(100, 110, len(idx))}, index=idx),
    )
    if delist:
        for c, d in delist.items():
            data.delist_date[c] = pd.Timestamp(d)
    return data


def refresh_limits(data):
    """按当前 close 重算 ±10% 涨跌停价（修改 close 后调用）。"""
    prev = data.close.shift(1)
    prev.iloc[0] = data.close.iloc[0]
    data.up_limit = prev * 1.1
    data.down_limit = prev * 0.9
    return data


class FixedStrategy(Strategy):
    """在指定信号日给出固定权重；exposure 按日期字典给出（默认 1）。"""

    name = "fixed"

    def __init__(self, schedule, exposure_map=None):
        # schedule: {date_str: {code: weight}}
        self.schedule = {pd.Timestamp(k): pd.Series(v, dtype=float) for k, v in schedule.items()}
        self.exposure_map = {pd.Timestamp(k): v for k, v in (exposure_map or {}).items()}
        self.seen_max_dates = []
        self.current_exposure = 1.0

    def rebalance_dates(self, calendar):
        return pd.DatetimeIndex(sorted(d for d in self.schedule if d in calendar))

    def target_weights(self, t, data):
        self.seen_max_dates.append((t, data.calendar.max()))
        return self.schedule[t]

    def exposure(self, t, data):
        self.seen_max_dates.append((t, data.calendar.max()))
        if t in self.exposure_map:
            self.current_exposure = self.exposure_map[t]
        return self.current_exposure


ZERO_COST = dict(commission=0.0, transfer=0.0, stamp_before=0.0, stamp_after=0.0, slippage=0.0)
