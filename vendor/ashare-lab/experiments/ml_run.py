"""运行月度机器学习选股实验和使用现有撮合引擎的组合回测。"""

import argparse
from dataclasses import replace
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import BacktestConfig, BacktestResult, run_backtest
from ashare_lab.ml.dataset import make_dataset
from ashare_lab.ml.evaluate import ic_series, ic_summary, quantile_returns
from ashare_lab.ml.models import LGBM, Ridge, SignedAverage
from ashare_lab.ml.walkforward import walk_forward
from ashare_lab.strategies.score import ScoreStrategy
from ashare_lab.strategy import month_end_dates


PERIODS = {"2016-2019": ("2016-02-01", "2019-12-31"),
           "2020-2026": ("2020-01-01", "2026-09-30"),
           "全部": ("2016-02-01", "2026-09-30")}


def portfolio_rows(name, result, benchmark=False):
    rows = []
    for period, (start, end) in PERIODS.items():
        trades = result.trades
        if "date" in trades:
            trades = trades.loc[trades.date.between(start, end)]
        # Carry the preceding close into later segments to retain the first
        # day's return; trades/exposure belong strictly to the stated segment.
        nav = result.nav.loc[start:end]
        previous = result.nav.loc[result.nav.index < pd.Timestamp(start)].tail(1)
        subset = replace(result, nav=pd.concat([previous, nav]), trades=trades,
                         exposure=result.exposure.loc[start:end])
        statistics = {key: value for key, value in metrics.summary(subset).items() if np.isscalar(value)}
        if benchmark:
            statistics.update(turnover=np.nan, cost_ratio=np.nan, avg_exposure=np.nan)
        rows.append({"method": name, "period": period, **statistics})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--methods", default="lowvol,signed_avg,ridge,lgbm,random")
    parser.add_argument("--out", type=Path, default=Path("reports/ml"))
    args = parser.parse_args()
    methods = list(dict.fromkeys(args.methods.split(",")))
    factories = {"signed_avg": SignedAverage, "ridge": Ridge, "lgbm": LGBM}
    if not methods or set(methods) - {"lowvol", "random", *factories}:
        parser.error("--methods must contain lowvol,signed_avg,ridge,lgbm,random")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    print("Loading market data", flush=True)
    data = load_market_data("data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    cache = Path("data/cache/ml_dataset.parquet")
    if cache.exists():
        ds = pd.read_parquet(cache)
        print(f"Loaded dataset cache: {len(ds):,} rows", flush=True)
    else:
        dates = month_end_dates(data.calendar)
        dates = dates[dates >= "2011-01-01"]
        print(f"Computing factors for {len(dates)} month ends", flush=True)
        ds = make_dataset(data, dates)
        cache.parent.mkdir(parents=True, exist_ok=True)
        ds.to_parquet(cache)
        print(f"Cached dataset: {len(ds):,} rows", flush=True)

    sample = ds.loc[ds.index.get_level_values(0).year >= 2016]
    ics, summaries, quantiles, portfolios, navs = {}, [], [], [], {}
    for method in methods:
        print(f"Scoring {method}", flush=True)
        models = []
        if method in factories:
            def make_model():
                model = factories[method]()
                models.append(model)
                return model

            scores, diag = walk_forward(ds, make_model, range(2016, 2027))
            diag.to_csv(out / f"diag_{method}.csv", index=False)
            if method == "lgbm":
                importance = []
                for year, model in zip(diag["year"], models):
                    gains = pd.Series(model.info["importance_gain"])
                    shares = gains / gains.sum() if gains.sum() > 0 else gains * 0
                    importance.extend({"year": year, "feature": key, "gain_share": value}
                                      for key, value in shares.items())
                pd.DataFrame(importance).to_csv(out / "importance.csv", index=False)
        else:
            scores = (-sample["vol_250"] if method == "lowvol" else
                      pd.Series(np.random.default_rng(0).random(len(sample)), index=sample.index))
        ics[method] = ic_series(scores, ds["y"])
        for period in PERIODS:
            ic = ics[method]
            if period == "2016-2019":
                ic = ic.loc["2016":"2019"]
            elif period == "2020-2026":
                ic = ic.loc["2020":"2026"]
            summaries.append({"method": method, "period": period, **ic_summary(ic)})
        groups = quantile_returns(scores, ds["ret"])
        means = groups.mean()
        quantiles.append({"method": method, **means.to_dict(), "5-1": (groups[5] - groups[1]).mean()})
        print(f"Backtesting {method}", flush=True)
        result = run_backtest(ScoreStrategy(scores, label=method), data,
                              BacktestConfig(start="2016-02-01", end="2026-09-30"))
        navs[method] = result.nav / result.nav.iloc[0]
        portfolios.extend(portfolio_rows(method, result))

    benchmark = data.index_close["000906.SH"].loc["2016-02-01":"2026-09-30"].dropna()
    result = BacktestResult(nav=benchmark, cash=pd.Series(dtype=float), positions=pd.DataFrame(),
                            trades=pd.DataFrame(columns=["side", "value", "fee"]),
                            exposure=pd.Series(dtype=float), target=pd.DataFrame())
    navs["index:000906.SH"] = benchmark / benchmark.iloc[0]
    portfolios.extend(portfolio_rows("index:000906.SH", result, benchmark=True))
    pd.DataFrame(ics).rename_axis("date").to_csv(out / "ic.csv")
    pd.DataFrame(summaries).to_csv(out / "ic_summary.csv", index=False)
    pd.DataFrame(quantiles).to_csv(out / "quantiles.csv", index=False)
    pd.DataFrame(portfolios).to_csv(out / "portfolio_summary.csv", index=False)

    os.environ.setdefault("MPLCONFIGDIR", str(out.resolve() / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axis = plt.subplots(figsize=(12, 6))
    for name, nav in navs.items():
        axis.plot(nav.index, nav, label=name)
    axis.set_yscale("log")
    axis.set_ylabel("NAV (log)")
    axis.legend()
    axis.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "nav.png", dpi=150)
    plt.close(fig)
    for path in sorted(out.iterdir()):
        if path.is_file():
            print(f"{path}: {path.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
    main()
