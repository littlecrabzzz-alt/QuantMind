"""C6：生成 PE/PB 历史分位与截面估值对照分数。"""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/c6"

import pandas as pd

from ashare_lab.data.market import load_market_data
from ashare_lab.strategy import month_end_dates
from ashare_lab.universe import eligible
from ashare_lab.valuation import hist_percentile, monthly_valuation


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_market_data("data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    dates = month_end_dates(data.calendar)
    valuations = monthly_valuation(data, dates)
    panels = {
        f"{metric}_pct_W{window}": -hist_percentile(panel, window, min_obs)
        for metric, panel in valuations.items()
        for window, min_obs in ((36, 24), (60, 36))
    }
    panels.update(ep_xs=1 / valuations["pe"], bp_xs=1 / valuations["pb"])
    frames = []
    for date in dates:
        mask = eligible(date, data)
        codes = mask.index[mask].rename("code")
        frames.append(pd.DataFrame({name: panel.loc[date].reindex(codes)
                                    for name, panel in panels.items()}, index=codes))
    scores = pd.concat(frames, keys=dates, names=["date", "code"])
    scores.to_parquet(OUT / "scores.parquet")
    print(f"{OUT / 'scores.parquet'}: {len(scores)} rows, {len(dates)} months")


if __name__ == "__main__":
    main()
