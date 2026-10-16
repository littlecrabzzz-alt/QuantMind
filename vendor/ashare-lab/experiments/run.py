"""运行已登记的实验并输出净值、年度收益及指标。"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, fields
import multiprocessing
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import BacktestConfig, BacktestResult, CostModel, run_backtest
from ashare_lab.multifactor import BufferScoreStrategy, composite
from ashare_lab.strategies import IndustryLowVol, LowVolTrend, VolTarget
from configs import EXPERIMENTS


_DATA = None  # 父进程加载一次，fork 子进程只读共享。
_INDUSTRY = None
_FACTORS = {}
_SCORES = {}
_SAVE_TRADES = False


class _LabeledVolTarget(VolTarget):
    @property
    def name(self):
        return self.base.name


def run_config(config):
    params = dict(config)
    start, end = params.pop("start"), params.pop("end")
    costs = CostModel(**params.pop("cost", {}))
    initial_cash = params.pop("initial_cash", 1e7)
    output_name = params.pop("name", None)
    benchmark = params.pop("benchmark", None)
    strategy_kind = params.pop("strategy", "lowvol")
    if benchmark is not None:
        name = output_name or f"index:{benchmark}"
        nav = _DATA.index_close[benchmark].loc[start:end].dropna()
        if nav.empty:
            raise ValueError(f"No index data for {name} in {start}..{end}")
        result = BacktestResult(
            nav=nav, cash=pd.Series(dtype=float), positions=pd.DataFrame(),
            trades=pd.DataFrame(columns=["side", "value", "fee"]),
            exposure=pd.Series(dtype=float), target=pd.DataFrame(),
        )
        row = {"name": name, "benchmark": benchmark, "start": start, "end": end}
    else:
        if strategy_kind == "industry_lowvol":
            strategy = IndustryLowVol(industry=_INDUSTRY, **params)
        elif strategy_kind == "lowvol":
            strategy = LowVolTrend(**params)
        elif strategy_kind == "score":
            version = params.pop("factors")
            groups = params.pop("groups")
            vol_target = params.pop("vol_target", None)
            params.setdefault("top_n", 50)
            params.setdefault("keep_rank", params["top_n"])
            strategy = BufferScoreStrategy(scores=composite(_FACTORS[version], groups), **params)
            if vol_target is not None:
                strategy = _LabeledVolTarget(base=strategy, **vol_target)
        elif strategy_kind == "raw_score":
            score_file = params.pop("score_file")
            column = params.pop("column")
            params["keep_rank"] = params["top_n"]
            strategy = BufferScoreStrategy(scores=_SCORES[score_file][column], **params)
        elif strategy_kind == "vol_target":
            base_kind = params.pop("base_strategy")
            base_params = params.pop("base")
            if base_kind == "lowvol":
                base = LowVolTrend(**base_params)
            elif base_kind == "industry_lowvol":
                base = IndustryLowVol(industry=_INDUSTRY, **base_params)
            else:
                raise ValueError(f"Unknown base strategy: {base_kind}")
            strategy = VolTarget(base=base, **params)
        else:
            raise ValueError(f"Unknown strategy: {strategy_kind}")
        name = output_name or strategy.name
        result = run_backtest(strategy, _DATA, BacktestConfig(
            start=start, end=end, initial_cash=initial_cash, costs=costs,
        ))
        nav = result.nav
        if nav.empty:
            raise ValueError(f"No trading dates in {start}..{end}")
        parameters = {f.name: getattr(strategy, f.name) for f in fields(strategy)
                      if f.init and f.name not in ("industry", "scores")}
        if isinstance(strategy, VolTarget):
            parameters["base"] = strategy.base.name
        row = {"name": name, **parameters, "start": start, "end": end,
               **{f"cost_{key}": value for key, value in asdict(costs).items()}}
        if strategy_kind == "score":
            row.update(factors=version, groups=groups, **params)
        elif strategy_kind == "raw_score":
            row.update(score_file=score_file, column=column)
        if "initial_cash" in config:
            row["initial_cash"] = initial_cash
    statistics = metrics.summary(result)
    row.update({key: value for key, value in statistics.items() if np.isscalar(value)})
    if benchmark is not None:
        row.update(turnover=np.nan, cost_ratio=np.nan, avg_exposure=np.nan)
    return (row, (nav / nav.iloc[0]).rename(name), statistics["annual_returns"].rename(name),
            result.exposure.rename(name), result.trades if _SAVE_TRADES else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=EXPERIMENTS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = args.out or Path("reports") / args.experiment
    out.mkdir(parents=True, exist_ok=True)
    configs = EXPERIMENTS[args.experiment]

    global _DATA, _INDUSTRY, _FACTORS, _SCORES, _SAVE_TRADES
    _SAVE_TRADES = args.experiment.startswith("b5_")
    _DATA = load_market_data("data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    if any(config.get("strategy") == "industry_lowvol"
           or config.get("base_strategy") == "industry_lowvol" for config in configs):
        _INDUSTRY = pd.read_parquet("data/panel/industry.parquet")
    _FACTORS = {
        version: pd.read_parquet(f"reports/b3/factors_{version}.parquet")
        for version in sorted({config["factors"] for config in configs
                               if config.get("strategy") == "score"})
    }
    _SCORES = {
        filename: pd.read_parquet(filename)
        for filename in sorted({config["score_file"] for config in configs
                                if config.get("strategy") == "raw_score"})
    }
    with ProcessPoolExecutor(
        max_workers=min(len(configs), 8), mp_context=multiprocessing.get_context("fork")
    ) as pool:
        results = list(pool.map(run_config, configs))

    rows, navs, annuals, exposures, trades = zip(*results)
    counts = Counter(row["name"] for row in rows)
    used = {name for name, count in counts.items() if count == 1}
    default_costs = asdict(CostModel())
    default_strategy = LowVolTrend()
    for row, series, yearly, exposure, _ in results:
        name = row["name"]
        if counts[name] == 1:
            continue
        for key, default in default_costs.items():
            value = row.get(f"cost_{key}", default)
            if value != default:
                label = "slip" if key == "slippage" else key
                name += f"__{label}{value}"
        if row.get("rebalance", default_strategy.rebalance) != default_strategy.rebalance:
            name += f"__{row['rebalance']}"
        if row.get("seed", default_strategy.seed) != default_strategy.seed:
            name += f"__seed{row['seed']}"
        candidate = name
        number = 1
        while candidate in used:
            candidate = f"{name}__#{number}"
            number += 1
        used.add(candidate)
        row["name"] = series.name = yearly.name = exposure.name = candidate
    summary = pd.DataFrame(rows)
    nav = pd.concat(navs, axis=1).rename_axis("date")
    annual = pd.concat(annuals, axis=1).rename_axis("year")
    summary.to_csv(out / "summary.csv", index=False)
    nav.to_parquet(out / "nav.parquet")
    annual.to_csv(out / "annual.csv")
    if _SAVE_TRADES:
        pd.concat([frame.assign(name=row["name"]) for row, frame in zip(rows, trades)],
                  ignore_index=True).to_parquet(out / "trades.parquet", index=False)
    if args.experiment.startswith("b2_") or args.experiment == "vtcut":
        pd.concat(exposures, axis=1).rename_axis("date").to_parquet(out / "exposure.parquet")

    if len(configs) <= 12:
        os.environ.setdefault("MPLCONFIGDIR", str(out.resolve() / ".matplotlib"))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        for series in navs:
            axes[0].plot(series.index, series, label=series.name)
            axes[1].plot(series.index, metrics.drawdown_series(series), label=series.name)
        axes[0].set_yscale("log")
        axes[0].set_ylabel("NAV (log)")
        axes[1].set_ylabel("Drawdown")
        axes[0].legend()
        for axis in axes:
            axis.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "nav.png", dpi=150)
        plt.close(fig)

    print(summary[["name", "cagr", "max_drawdown"]].to_string(index=False))
    for filename in ("summary.csv", "nav.parquet", "annual.csv", "nav.png"):
        path = out / filename
        if path.exists():
            print(f"{path}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
