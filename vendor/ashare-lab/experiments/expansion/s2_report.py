"""S2 两个多头分仓 × 四种期货对冲配置。"""

from pathlib import Path
import os
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/s2"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd
from ashare_lab.benchmark import load_benchmarks
from ashare_lab.expansion.assets import load_asset, load_calendar, load_futures, load_indexes
from ashare_lab.expansion.hedge import target_contracts, simulate_hedge
from common import metrics_table, bootstrap_mdd, monthly_signals, plot_nav


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    calendar = load_calendar()
    prices, mapping, basic = load_futures(calendar)
    indexes = load_indexes(calendar)
    longs = pd.read_parquet(ROOT / "reports/b3_full/nav.parquet")[["lowvol_W250_N50", "b3_lv_q_v_buf"]]
    longs.index = pd.to_datetime(longs.index)
    longs = longs.loc["2012-01-01":"2026-09-30"]
    summary = pd.read_csv(ROOT / "reports/b3_full/summary.csv").set_index("name")
    cash = load_asset("etf:511880.SH", calendar).pct_change(fill_method=None).fillna(0)
    cash.loc[cash.index < "2013-04-18"] = 0.0
    signals = monthly_signals(longs.index)
    targets = {p: target_contracts(mapping[f"{p}.CFX"].dropna(), basic, calendar).reindex(longs.index)
               for p in ("IF", "IC")}
    switching = targets["IF"].where(longs.index <= "2015-04-30", targets["IC"])
    navs, turnover, results = {}, {}, {}
    for label, column in (("lowvol", "lowvol_W250_N50"), ("b3", "b3_lv_q_v_buf")):
        long_nav = longs[column]
        long_returns = long_nav.pct_change(fill_method=None)
        for mode in ("base", "beta", "ifonly", "cash"):
            name = f"{label}_{mode}"
            ratios = pd.Series(1.0, index=signals)
            if mode == "beta":
                for t in signals:
                    product = "IF" if t <= pd.Timestamp("2015-04-30") else "IC"
                    returns = pd.concat([long_returns.rename("long"),
                                         indexes[product].pct_change(fill_method=None).rename("index")], axis=1)
                    sample = returns.loc[:t].dropna().iloc[-250:]
                    if len(sample) == 250 and sample["index"].var(ddof=1) > 0:
                        ratios.loc[t] = np.clip(sample["long"].cov(sample["index"]) /
                                                sample["index"].var(ddof=1), 0, 1.5)
            result = simulate_hedge(long_nav, prices, targets["IF"] if mode == "ifonly" else switching,
                                    ratios, indexes, cash_return=cash if mode == "cash" else None)
            navs[name], navs[f"{name}__excess"] = result["nav"], result["excess_nav"]
            turnover[name] = summary.loc[column, "turnover"] * (result["L"] / result["nav"]).mean()
            results[name] = result
    nav = pd.DataFrame({**navs, **{c: longs[c] for c in longs}})
    for column in longs:
        turnover[column] = summary.loc[column, "turnover"]
    table = metrics_table(nav, load_benchmarks(ROOT / "data/benchmarks"), longs.lowvol_W250_N50, turnover)
    table["fut_turnover"] = table.name.map({name: r["fut_turnover"] for name, r in results.items()})
    table["min_cash_ratio"] = table.name.map({name: r["min_cash_ratio"] for name, r in results.items()})
    basis = pd.DataFrame({name: r["basis_annual"] for name, r in results.items()})
    nav.to_parquet(OUT / "nav.parquet")
    table.to_csv(OUT / "metrics.csv", index=False)
    basis.to_csv(OUT / "basis_annual.csv", index_label="year")
    bootstrap_mdd(nav).to_csv(OUT / "bootstrap.csv", index=False)
    plot_nav(nav[[*results, *longs.columns]], OUT / "nav.png", "S2 期货对冲低波｜组合净值与回撤")
    print(table[table.period.isin(["FULL", "OOS"])].to_string(index=False))
    print("年度基差拖累")
    print(basis.to_string())


if __name__ == "__main__":
    main()
