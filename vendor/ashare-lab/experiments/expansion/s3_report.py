"""Run the fixed S3 event study, tradable portfolios and acceptance rules."""

import gc
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.benchmark import load_benchmarks
from ashare_lab.data.events import load_events
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.expansion.event_study import event_returns, select_events
from ashare_lab.expansion.event_study import summarize as car_summary
from ashare_lab.pbo import cscv_pbo
from ashare_lab.strategies.event_portfolio import EventPortfolio
from configs import B5_COST
from common import PERIODS, bootstrap_mdd, metrics_table

START, END = "2012-01-01", "2026-09-30"
HORIZONS = (1, 5, 10, 20, 40, 60)
POSITIVE = ("fc_pos", "buyback", "increase")
OUT = ROOT / "reports/s3"


def study(benchmarks):
    print("Loading all A-share market data for the event study", flush=True)
    data = load_market_data("data/panel", "2010-01-01", END, universe=None)
    # Cooldown selection uses all history; only reported entry dates are filtered.
    selected = select_events(load_events("data/events"), data.calendar)
    selected = selected[selected.effective_date.between(START, END)].reset_index(drop=True)
    industry = pd.read_parquet("data/panel/industry.parquet")
    statistics, curves, skips = [], [], []
    for universe in ("csi800", "liquid"):
        print(f"Computing {universe}: {len(selected):,} selected events, horizons 1..60", flush=True)
        per_event = event_returns(selected, data, benchmarks["000906.SH_TR"], industry,
                                  universe, range(1, 61))
        counts = (per_event.assign(skip=per_event.skip.fillna("accepted"))
                  .groupby(["group", "skip"]).agg(n=("code", "size"), delisted=("delisted", "sum"))
                  .reset_index().assign(universe=universe))
        skips.append(counts[["universe", "group", "skip", "n", "delisted"]])
        for benchmark, label in (("bench", "000906.SH_TR"), ("ind", "industry_equal_weight")):
            stats = car_summary(per_event, HORIZONS, benchmark, PERIODS)
            statistics.append(stats.assign(universe=universe, benchmark=label))
            if universe == "csi800":
                curve = car_summary(per_event, range(1, 61), benchmark, {"FULL": (START, END)})
                curves.append(curve.assign(benchmark=label))
        del per_event
        gc.collect()
    stats = pd.concat(statistics, ignore_index=True)
    stats = stats[["universe", "benchmark", "group", "period", "h", "n", "mean", "median", "frac_pos", "t_stat"]]
    stats.to_csv(OUT / "car_stats.csv", index=False)
    pd.concat(skips, ignore_index=True).to_csv(OUT / "skip_counts.csv", index=False)
    plot_car(pd.concat(curves, ignore_index=True))
    print("CAR: CSI800 / 000906.SH_TR / FULL (index previous close vs stock entry open)", flush=True)
    display = stats[(stats.universe == "csi800") & (stats.benchmark == "000906.SH_TR")
                    & (stats.period == "FULL") & stats.h.isin([1, 5, 20, 60])]
    print(display[["group", "h", "n", "mean", "t_stat"]].to_string(index=False), flush=True)
    return selected


def plot_car(curves):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, (benchmark, values) in zip(axes, curves.groupby("benchmark", sort=False)):
        for group, group_values in values.groupby("group", sort=False):
            ax.plot(group_values.h, group_values["mean"], label=group)
        ax.set(title=benchmark, xlabel="Trading-day horizon (entry day = 1)", ylabel="Mean CAR")
        ax.axhline(0, color="black", linewidth=0.7)
        ax.grid(alpha=0.25)
        ax.legend()
    fig.suptitle("FULL / CSI800; index starts at previous close, stocks at entry open")
    fig.tight_layout()
    fig.savefig(OUT / "car_curve.png", dpi=150)
    plt.close(fig)


def portfolios(selected, benchmarks, lowvol):
    print("Loading historical CSI800 universe for 12 full-period engine runs", flush=True)
    data = load_market_data("data/panel", "2010-01-01", END, universe="000906.SH")
    navs, rows, turnover = [], [], {}
    period_turnovers = {}
    for capacity in (False, True):
        for group in POSITIVE:
            events = selected[selected.group == group]
            for hold in (20, 60):
                name = f"s3_{group}_h{hold}" + ("__cap1e8" if capacity else "")
                initial_cash = 1e8 if capacity else 1e7
                costs = CostModel(**B5_COST) if capacity else CostModel()
                print(f"Running {name}", flush=True)
                result = run_backtest(EventPortfolio(events, hold=hold), data, BacktestConfig(
                    start=START, end=END, initial_cash=initial_cash, costs=costs))
                stats = {key: value for key, value in metrics.summary(result).items() if np.isscalar(value)}
                counts = result.positions.gt(0).sum(axis=1)
                rows.append({"name": name, "initial_cash": initial_cash, **stats,
                             "avg_names": float(counts.mean()), "empty_days_frac": float(counts.eq(0).mean())})
                navs.append((result.nav / result.nav.iloc[0]).rename(name))
                turnover[name] = stats["turnover"]
                trades = result.trades[result.trades.side.isin(["buy", "sell"])]
                for period, (start, end) in PERIODS.items():
                    nav_slice = result.nav.loc[start:end]
                    volume = trades.loc[trades.date.between(pd.Timestamp(start), pd.Timestamp(end)), "value"].sum()
                    period_turnovers[name, period] = volume / 2 / nav_slice.mean() * 252 / (len(nav_slice) - 1)
                del result
                gc.collect()
    nav = pd.concat(navs, axis=1).rename_axis("date")
    nav.to_parquet(OUT / "nav.parquet")
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    table = metrics_table(nav, benchmarks, lowvol, turnover=turnover)
    table["turnover"] = [period_turnovers[row.name, row.period] for row in table.itertuples()]
    table.to_csv(OUT / "metrics.csv", index=False)
    bootstrap = bootstrap_mdd(nav.assign(lowvol_W250_N50=lowvol.reindex(nav.index)))
    bootstrap.to_csv(OUT / "bootstrap.csv", index=False)
    plot_portfolios(nav, benchmarks, lowvol)
    base_names = [f"s3_{group}_h{hold}" for group in POSITIVE for hold in (20, 60)]
    print("Six default-cost portfolios: FULL / OOS metrics", flush=True)
    print(table[table.name.isin(base_names) & table.period.isin(["FULL", "OOS"])].to_string(index=False), flush=True)
    acceptance_rules(nav, table, bootstrap, benchmarks, lowvol, base_names)


def plot_portfolios(nav, benchmarks, lowvol):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharex=True)
    for name in nav:
        series = nav[name]
        line, = axes[0].plot(series.index, series, label=name,
                             linestyle="--" if name.endswith("__cap1e8") else "-")
        axes[1].plot(series.index, metrics.drawdown_series(series), color=line.get_color(),
                     linestyle="--" if name.endswith("__cap1e8") else "-")
    for name, series in (("lowvol_W250_N50", lowvol),
                         ("000906.SH_TR", benchmarks["000906.SH_TR"])):
        series = series.reindex(nav.index).dropna()
        axes[0].plot(series.index, series / series.iloc[0], label=name, linewidth=2, alpha=0.7)
    axes[0].set(yscale="log", ylabel="NAV (log)", title="S3 tradable announcement portfolios")
    axes[0].legend(ncol=3, fontsize=8)
    axes[1].set_ylabel("Drawdown")
    for ax in axes:
        ax.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.5)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "nav.png", dpi=150)
    plt.close(fig)


def acceptance_rules(nav, table, bootstrap, benchmarks, lowvol, names):
    # Select strictly by IS Calmar before reading the candidate's OOS results.
    inside = table[(table.period == "IS") & table.name.isin(names)].set_index("name")
    candidate = inside.calmar.reindex(names).idxmax()
    values = table[table.name == candidate].set_index("period")
    boot = bootstrap.set_index("name")
    lowvol_full = lowvol.reindex(nav.index).dropna()
    pbo_rows = []
    returns = nav[names].pct_change(fill_method=None).dropna()
    for blocks in (16, 10):
        result = cscv_pbo(returns, n_blocks=blocks)
        pbo_rows.append({"n_blocks": blocks, **{key: value for key, value in result.items() if np.isscalar(value)}})
    pd.DataFrame(pbo_rows).to_csv(OUT / "pbo.csv", index=False)
    cap = table[(table.name == candidate + "__cap1e8") & (table.period == "FULL")].iloc[0]
    checks = [
        ("alpha_IS", values.loc["IS", "alpha_000906.SH_TR"], 0, ">"),
        ("alpha_OOS", values.loc["OOS", "alpha_000906.SH_TR"], 0, ">"),
        ("bootstrap_mdd_p05", boot.loc[candidate, "mdd_p05"], boot.loc["lowvol_W250_N50", "mdd_p05"], ">="),
        ("full_max_drawdown", values.loc["FULL", "max_drawdown"], metrics.max_drawdown(lowvol_full), ">="),
        ("corr_lowvol", values.loc["FULL", "corr_lowvol"], 0.5, "<"),
        ("pbo_16", pbo_rows[0]["pbo"], 0.3, "<="),
        ("pbo_10", pbo_rows[1]["pbo"], 0.3, "<="),
        ("capacity_cagr_drop", values.loc["FULL", "cagr"] - cap.cagr, 0.01, "<"),
    ]
    rows = []
    for rule, value, threshold, operator in checks:
        passed = {">": value > threshold, ">=": value >= threshold,
                  "<": value < threshold, "<=": value <= threshold}[operator]
        rows.append({"candidate": candidate, "selection": "highest IS Calmar among six default-cost configurations",
                     "rule": rule, "value": value, "operator": operator, "threshold": threshold, "passed": bool(passed)})
    rules = pd.DataFrame(rows)
    rules.to_csv(OUT / "rules.csv", index=False)
    print(f"Fixed acceptance rules; IS-selected candidate: {candidate}", flush=True)
    print(rules[["rule", "value", "operator", "threshold", "passed"]].to_string(index=False), flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    benchmarks = load_benchmarks("data/benchmarks")
    lowvol = pd.read_parquet("reports/b3_full/nav.parquet")["lowvol_W250_N50"]
    selected = study(benchmarks)
    gc.collect()
    portfolios(selected, benchmarks, lowvol)
    print(f"S3 report written to {OUT}", flush=True)


if __name__ == "__main__":
    main()
