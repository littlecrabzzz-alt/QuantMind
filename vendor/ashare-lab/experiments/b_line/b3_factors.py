"""生成 B3 月末 PIT 财务因子及按报告期取数的 naive 对照。"""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ashare_lab.data.fundamentals import Fundamentals
from ashare_lab.data.market import load_market_data
from ashare_lab.multifactor import compute_b3_factors
from ashare_lab.strategy import month_end_dates


def main():
    out = ROOT / "reports/b3"
    out.mkdir(parents=True, exist_ok=True)
    data = load_market_data("data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    fund = Fundamentals.load("data/fundamentals")
    dates = month_end_dates(data.calendar)
    dates = dates[(dates >= "2011-12-01") & (dates <= "2026-09-30")]
    for version in ("pit", "naive"):
        print(f"计算 {version}: {len(dates)} 个月末", flush=True)
        factors = compute_b3_factors(data, fund, dates, naive=version == "naive")
        path = out / f"factors_{version}.parquet"
        factors.to_parquet(path)
        print(f"{path}: {len(factors):,} 行", flush=True)


if __name__ == "__main__":
    main()
