"""账户参数在创建 meta.json 时冻结；行情和 PIT 因子随数据更新。"""

from dataclasses import asdict, fields

import pandas as pd

from ashare_lab.engine import CostModel
from ashare_lab.multifactor import BufferScoreStrategy, GROUPS, composite, compute_b3_factors
from ashare_lab.paper import InceptionRebalance
from ashare_lab.strategies.lowvol_trend import LowVolTrend
from ashare_lab.strategies.vol_target import VolTarget
from ashare_lab.strategy import month_end_dates


INCEPTION = "2026-10-13"
INITIAL_CASH = 1_000_000
NAMES = ("lowvol", "b2_lowvol_vt", "b3_lqv_buf_vt")


def make_accounts(data, fund, inception=INCEPTION, open_days=None):
    """每次重放创建全新策略，避免缓存及排名缓冲状态串用。"""
    inception = pd.Timestamp(inception).strftime("%Y-%m-%d")
    dates = month_end_dates(data.calendar)
    dates = pd.DatetimeIndex([inception]).union(dates[dates > pd.Timestamp(inception)])
    factors = compute_b3_factors(data, fund, dates, naive=False)
    groups = ["lowvol", "quality", "value"]

    def wrap(base):
        return InceptionRebalance(base, inception, open_days)

    def lowvol():
        return LowVolTrend(vol_window=250, top_n=50, timing_index=None)

    strategies = [
        wrap(lowvol()),
        VolTarget(base=wrap(lowvol()), target_vol=0.16, window=60, step=0.1),
        VolTarget(base=wrap(BufferScoreStrategy(
            scores=composite(factors, groups), top_n=50, keep_rank=100,
            label="b3_lqv_buf_vt")), target_vol=0.16, window=60, step=0.1),
    ]

    def specification(strategy):
        if isinstance(strategy, InceptionRebalance):
            parameters = {
                "base": specification(strategy.base), "inception": inception,
                "open_days": "SSE is_open=1; unavailable: weekdays",
                "terminal_month_end": "confirm with next open day",
            }
        else:
            parameters = {field.name: getattr(strategy, field.name)
                          for field in fields(strategy) if field.init and
                          field.name not in ("base", "scores")}
            if isinstance(strategy, VolTarget):
                parameters["base"] = specification(strategy.base)
            if isinstance(strategy, BufferScoreStrategy):
                parameters["scores"] = {
                    "compute": "compute_b3_factors", "naive": False,
                    "universe": "000906.SH", "vol_window": 250, "min_list_days": 250,
                    "dates": "inception plus subsequent month ends",
                    "composite": groups, "directions": GROUPS,
                    "lowvol": asdict(lowvol()),
                    "gm_std": {"n": 8, "min_obs": 4},
                }
        return {"class": type(strategy).__name__, "params": parameters}

    return [(name, strategy, {
        "name": name, "strategy": specification(strategy), "inception": inception,
        "initial_cash": INITIAL_CASH, "costs": asdict(CostModel()),
    }) for name, strategy in zip(NAMES, strategies)]
