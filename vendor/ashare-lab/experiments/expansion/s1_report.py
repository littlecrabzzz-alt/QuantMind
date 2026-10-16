"""S1 股债金配置，固定参数及 ETF 替代窗口。"""

from pathlib import Path
import os
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/s1"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import pandas as pd
from ashare_lab import metrics
from ashare_lab.benchmark import load_benchmarks
from ashare_lab.expansion.assets import load_asset, load_calendar
from ashare_lab.expansion.overlay import inverse_vol_weights, run_allocation
from common import metrics_table, bootstrap_mdd, monthly_signals, plot_nav


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    calendar = load_calendar()
    calendar = calendar[calendar <= "2026-09-30"]
    stock = pd.read_parquet(ROOT / "reports/b3_full/nav.parquet")["lowvol_W250_N50"].dropna()
    stock.index = pd.to_datetime(stock.index)
    bond = load_asset("bond_index", calendar)
    gold = load_asset("gold_spot", calendar)
    gold = gold * (1 - 0.006 / 252) ** pd.Series(range(len(gold)), index=gold.index)
    prices = pd.DataFrame({"stock": stock.reindex(calendar), "bond": bond, "gold": gold})
    variants = [("", "2012-01-04", prices)]
    for tag, start, sleeve, code in (("etfbond", "2013-04-01", "bond", "511010.SH"),
                                     ("etfgold", "2013-08-01", "gold", "518880.SH")):
        frame = prices.copy()
        frame[sleeve] = load_asset(f"etf:{code}", calendar)
        variants.append((f"_{tag}", start, frame))
    navs, turnover, targets = {}, {}, []
    for suffix, start, frame in variants:
        dates = calendar[calendar >= start]
        signals = monthly_signals(dates)
        for rule in ("fixed", "invvol", "invvol_vt"):
            name = f"s1_{rule}{suffix}"
            weight_function = (lambda t, r: pd.Series({"stock": 0.6, "bond": 0.3, "gold": 0.1})) if rule == "fixed" else (
                lambda t, r: inverse_vol_weights(r, t, window=60))
            out = run_allocation(frame.loc[start:], signals, weight_function,
                                 history=frame.loc[frame.index < start],
                                 vol_target={"target_vol": 0.16, "window": 60, "step": 0.1}
                                 if rule == "invvol_vt" else None)
            navs[name], turnover[name] = out["nav"], out["turnover"]
            target = out["target"].reset_index().assign(name=name)
            for sleeve in ("stock", "bond", "gold"):
                target[f"position_{sleeve}"] = target[sleeve] * target.exposure
            targets.append(target)
    for sleeve in prices:
        series = prices[sleeve].loc[stock.index[0]:].dropna()
        navs[f"sleeve_{sleeve}"] = series / series.iloc[0]
    nav = pd.DataFrame(navs)
    benchmarks = load_benchmarks(ROOT / "data/benchmarks")
    tables = [metrics_table(nav, benchmarks, stock, turnover)]
    for suffix, start, _ in variants[1:]:
        columns = [f"s1_{rule}{tag}" for rule in ("fixed", "invvol", "invvol_vt") for tag in ("", suffix)]
        window = metrics_table(nav[columns], benchmarks, stock, turnover,
                               periods={"ETF窗口": (start, "2026-09-30")})
        window["comparison"] = suffix.lstrip("_")
        tables.append(window)
    table = pd.concat(tables, ignore_index=True)
    nav.to_parquet(OUT / "nav.parquet")
    pd.concat(targets, ignore_index=True).to_csv(OUT / "weights.csv", index=False)
    table.to_csv(OUT / "metrics.csv", index=False)
    bootstrap_mdd(nav).to_csv(OUT / "bootstrap.csv", index=False)
    pd.DataFrame({name: metrics.annual_returns(nav[name].dropna()) for name in nav}).to_csv(OUT / "annual.csv", index_label="year")
    plot_nav(nav, OUT / "nav.png", "S1 股债金配置｜月末信号、次日收盘成交")
    print(table[table.period.isin(["FULL", "OOS"])].to_string(index=False))


if __name__ == "__main__":
    main()
