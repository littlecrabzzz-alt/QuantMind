"""收盘后生成信号的策略接口。"""

import pandas as pd

from .data.market import MarketData


class Strategy:
    """定义调仓日、基础权重和每日仓位。"""

    name: str = "base"

    def rebalance_dates(self, calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """返回生成基础权重的日期。"""
        raise NotImplementedError

    def target_weights(self, t: pd.Timestamp, data: MarketData) -> pd.Series:
        """返回非负且合计不超过一的基础权重。"""
        raise NotImplementedError

    def exposure(self, t: pd.Timestamp, data: MarketData) -> float:
        """返回每日目标仓位比例。"""
        return 1.0


def month_end_dates(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """取每个自然月最后一个交易日。"""
    return calendar[~calendar.to_period("M").duplicated(keep="last")]
