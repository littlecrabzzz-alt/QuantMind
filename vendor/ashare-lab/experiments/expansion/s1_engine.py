"""S1 ETF：逐证券引擎回放与分仓净值 overlay 对照。"""

import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/s1_engine"
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ashare_s1_matplotlib")

import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.expansion.etf_market import load_etf_frames, with_etfs
from ashare_lab.expansion.overlay import inverse_vol_weights, run_allocation
from ashare_lab.strategies.allocation import InverseVolAllocation
from ashare_lab.strategies.lowvol_trend import LowVolTrend
from common import plot_nav

START, END = "2013-09-02", "2026-09-30"
SLEEVES = {"bond": "511010.SH", "gold": "518880.SH"}


class RecordedAllocation(InverseVolAllocation):
    def __init__(self):
        super().__init__(LowVolTrend(vol_window=250, top_n=50, timing_index=None), SLEEVES)
        self.signals = []

    def target_weights(self, t, data):
        target = super().target_weights(t, data)
        self.signals.append({"date": t, "name": "engine", **self.last_sleeve_weights.to_dict()})
        return target


def main():
    release = json.loads((ROOT / "data/panel/build_meta.json").read_text())["release_id"]
    print(f"读取历史行情及同 release ETF：{release}", flush=True)
    data = load_market_data(ROOT / "data/panel", "2010-01-01", END, universe="000906.SH")
    data = with_etfs(data, load_etf_frames(SLEEVES.values(), data.calendar, release))
    strategy = RecordedAllocation()
    print(f"引擎回放 {START}..{END}，初始资金 10,000,000 元，默认成本", flush=True)
    result = run_backtest(strategy, data, BacktestConfig(START, END, 1e7, CostModel()))
    stock = pd.read_parquet(ROOT / "reports/b3_full/nav.parquet")["lowvol_W250_N50"].dropna()
    stock.index = pd.to_datetime(stock.index)
    adjusted = data.adj_close()
    prices = pd.DataFrame({"stock": stock.reindex(data.calendar),
                           **{name: adjusted[code] for name, code in SLEEVES.items()}})
    overlay_signals = []

    def weights(t, returns):
        target = inverse_vol_weights(returns, t, window=60)
        overlay_signals.append({"date": t, "name": "overlay", **target.to_dict()})
        return target

    # 使用同一股票调仓日；overlay 在次日收盘执行，引擎在次日开盘执行。
    overlay = run_allocation(prices.loc[START:END], strategy.rebalance_dates(result.nav.index),
                             weights, cost=0.0005, history=prices.loc[prices.index < START])
    nav = pd.DataFrame({"engine": result.nav / 1e7, "overlay": overlay["nav"]})
    rows = []
    periods = {"FULL": (START, END), "IS": (START, "2019-12-31"),
               "OOS": ("2020-01-01", END)}
    for period, (start, end) in periods.items():
        sliced = nav.loc[start:end]
        sliced = sliced / sliced.iloc[0]
        returns = sliced.pct_change(fill_method=None)
        correlation = returns.engine.corr(returns.overlay)
        # 年化跟踪差：引擎减 overlay 的日收益均值×252；另列跟踪误差便于核对。
        difference = returns.engine - returns.overlay
        for name in nav:
            aligned = pd.concat([sliced[name].rename("nav"), stock.loc[start:end].rename("lowvol")],
                                axis=1, join="inner").dropna().pct_change(fill_method=None)
            rows.append({"name": name, "period": period, "start": sliced.index[0],
                         "end": sliced.index[-1],
                         **{key: getattr(metrics, key)(sliced[name]) for key in
                            ("cagr", "ann_vol", "sharpe", "max_drawdown", "calmar")},
                         "corr_lowvol": aligned.nav.corr(aligned.lowvol),
                         "daily_return_corr": correlation,
                         "annual_tracking_difference": difference.mean() * 252,
                         "annual_tracking_error": difference.std(ddof=1) * np.sqrt(252)})
    compare = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    nav.to_parquet(OUT / "nav.parquet")
    compare.to_csv(OUT / "compare.csv", index=False)
    pd.DataFrame([*strategy.signals, *overlay_signals]).sort_values(
        ["date", "name"]).to_csv(OUT / "weights.csv", index=False)
    import matplotlib
    matplotlib.use("Agg")
    plot_nav(nav, OUT / "nav.png", "S1 ETF｜引擎次日开盘与分仓次日收盘对照")
    print(f"compare.csv：{OUT / 'compare.csv'}", flush=True)
    print(compare.to_csv(index=False), end="", flush=True)


if __name__ == "__main__":
    main()
