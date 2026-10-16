"""S1 ETF 冻结账户规格；每次重放创建全新策略。"""

from dataclasses import asdict

import pandas as pd

from ashare_lab.engine import CostModel
from ashare_lab.paper import InceptionRebalance
from ashare_lab.strategies.allocation import InverseVolAllocation
from ashare_lab.strategies.lowvol_trend import LowVolTrend


INITIAL_CASH = 1_000_000
NAMES = ("s1_invvol_etf",)
SLEEVES = {"bond": "511010.SH", "gold": "518880.SH"}
ETF_NAMES = {"511010.SH": "国泰上证5年期国债ETF", "518880.SH": "华安黄金ETF"}


def make_accounts(data, inception, open_days=None):
    inception = pd.Timestamp(inception).strftime("%Y-%m-%d")
    stock = LowVolTrend(vol_window=250, top_n=50, timing_index=None)
    allocation = InverseVolAllocation(stock, SLEEVES, window=60, min_obs=20)
    strategy = InceptionRebalance(allocation, inception, open_days)
    meta = {
        "name": NAMES[0], "inception": inception, "initial_cash": INITIAL_CASH,
        "costs": asdict(CostModel()),
        "strategy": {"class": "InceptionRebalance", "params": {
            "inception": inception, "open_days": "SSE is_open=1; unavailable: weekdays",
            "terminal_month_end": "confirm with next open day",
            "base": {"class": "InverseVolAllocation", "params": {
                "stock": {"class": "LowVolTrend", "params": asdict(stock)},
                "sleeves": dict(SLEEVES), "window": 60, "min_obs": 20,
                "returns": "截至信号日含当日的最近60个日简单收益；样本标准差；当前归一化股票篮子后复权收益，缺失按0；ETF后复权收益",
                "fallback": "任一分仓有效收益少于20个时三者等权；零波动分仓之间等权",
                "exposure": 1.0,
            }},
        }},
        "etf_data": {
            "release_rule": "与 data/live/panel/build_meta.json 的 release_id 相同，读取 SOURCE/releases/<release_id>/manifest.json，禁止使用 CURRENT 替代",
            "daily": "fund_daily 按 source_ts_code 过滤，同代码日期取 _fetched_at 最新；amount千元×1000，vol手×100",
            "adjustment": "fund_adj.adj_factor 同键取最新，close×adj为后复权价格",
            "calendar": "对齐股票日历；日历外丢弃；缺失行情NaN，open不前填，open或close缺失为停牌",
        },
        "execution": {
            "signal": "开户日及之后月末收盘信号，次一交易日开盘成交",
            "etf_limits": "前一有效收盘价×1.1/0.9（±10%），停牌及涨跌停约束与股票相同",
            "lot": "股票100股、ETF100份整手，清仓沿用引擎规则",
            "tax": "ETF卖出仍按引擎印花税计，保守高估；默认CostModel费用及滑点",
        },
    }
    return [(NAMES[0], strategy, meta)]
