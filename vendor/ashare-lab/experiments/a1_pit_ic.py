"""Monthly ROE rank IC: announcement-date PIT versus final report-period data."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ashare_lab.data.fundamentals import Fundamentals
from ashare_lab.data.market import load_market_data
from ashare_lab.strategy import month_end_dates
from ashare_lab.universe import eligible


def rank_ic(factor, returns):
    valid = np.isfinite(factor) & np.isfinite(returns)
    x, y = factor[valid], returns[valid]
    n = int(valid.sum())
    if n < 100 or x.nunique() < 2 or y.nunique() < 2:
        return np.nan, n
    return float(spearmanr(x, y).statistic), n


def statistics(values):
    values = values.dropna()
    n = len(values)
    mean, std = values.mean(), values.std(ddof=1)
    ratio = mean / std if std > 0 else np.nan
    return {"有效月份": n, "IC 均值": mean, "IC 标准差": std,
            "ICIR": ratio * np.sqrt(12), "t 值": ratio * np.sqrt(n),
            "IC > 0 比例": (values > 0).mean() if n else np.nan}


def number(value):
    return "NaN" if pd.isna(value) else f"{value:.8f}"


def report(result, release_id):
    lines = [
        "# A1 ROE TTM 月度 rank IC", "",
        f"财务归档 release_id：`{release_id}`。", "",
        "行情：data/panel，load_market_data(start=2010-01-01, universe=000906.SH)。"
        "信号日为 2011-01 至 2026-08 各自然月最后一个交易日；收益终点至 2026-09。"
        "股票池使用 eligible(d, data) 默认参数。", "",
        "PIT：effective_date ≤ d，每个报告期取最新已公告版本；"
        "naive：end_date ≤ d，每个报告期取归档最终版本。"
        "同日版本均按 report_type 5 > 1 > 4，再按 update_flag 降序。"
        "非年末 TTM = 当期累计值 + 上年年报 − 上年同期累计值；年末取当期值。"
        "ROE = TTM 归母净利润 / 同一最新报告期的归母净资产，净资产须大于 0。", "",
        "下期收益 = adj_close(下月末) / adj_close(d) − 1；"
        "adj_close = close.ffill() × adj.ffill()。"
        "IC 为因子与下期收益的截面 Spearman 相关，平秩取平均秩。"
        "两版各自使用因子与收益均有限的股票；n 为其数量，n < 100 或任一变量恒定则 IC 为 NaN。", "",
        "IC 标准差使用 ddof=1；ICIR = 均值 / 标准差 × sqrt(12)；"
        "t = 均值 / 标准差 × sqrt(有效月份)，未作自相关调整。"
        "IC > 0 比例以各自非空 IC 月份为分母。"
        "统计差值列 = naive 统计值 − PIT 统计值。"
        "配对统计仅用两版 IC 均非空的月份，ΔIC = IC_naive − IC_PIT，"
        "配对 t = mean(ΔIC) / std(ΔIC, ddof=1) × sqrt(配对月份数)。", "",
        "share_diff 分母为当日股票池内两版因子均非空的股票数；"
        "相对差 = abs(naive − PIT) / abs(PIT)，阈值严格大于 1e-9；"
        "PIT 为 0 时，两值都为 0 计相同，否则计不同。"
        "share_naive_only = 股票池内 naive 非空且 PIT 为空的股票数 / 当日股票池股票数。"
        "这两个比例不要求下期收益非空，区间均值对非空月份等权。", "",
    ]
    for label, start, end in (("全区间", "2011-01-01", "2026-08-31"),
                              ("2011–2019", "2011-01-01", "2019-12-31"),
                              ("2020–2026", "2020-01-01", "2026-08-31")):
        part = result.loc[result.date.between(start, end)]
        pit, naive = statistics(part.ic_pit), statistics(part.ic_naive)
        lines += [f"## {label}", "", "| 指标 | PIT | naive | naive − PIT |",
                  "|---|---:|---:|---:|"]
        for metric in pit:
            lines.append(f"| {metric} | {number(pit[metric])} | {number(naive[metric])} | "
                         f"{number(naive[metric] - pit[metric])} |")
        paired = part[["ic_pit", "ic_naive"]].dropna()
        delta = statistics(paired.ic_naive - paired.ic_pit)
        lines += ["", "| 配对指标 | 数值 |", "|---|---:|",
                  f"| 配对月份数 | {len(paired)} |",
                  f"| ΔIC 均值 | {number(delta['IC 均值'])} |",
                  f"| 配对 t 值 | {number(delta['t 值'])} |", "",
                  "| 覆盖差异指标 | 月均值 |", "|---|---:|",
                  f"| share_diff | {number(part.share_diff.mean())} |",
                  f"| share_naive_only | {number(part.share_naive_only.mean())} |", ""]
    return "\n".join(lines)


def main():
    started = perf_counter()
    print("Loading market data", flush=True)
    data = load_market_data("data/panel", start="2010-01-01", universe="000906.SH")
    print("Loading financial versions", flush=True)
    fundamentals = Fundamentals.load("data/fundamentals")
    months = pd.period_range("2011-01", "2026-09", freq="M")
    month_ends = month_end_dates(data.calendar)
    month_map = pd.Series(month_ends, index=month_ends.to_period("M"))
    endpoints = pd.DatetimeIndex(month_map.reindex(months))
    if endpoints.isna().any():
        raise ValueError("Market calendar does not cover every required month through 2026-09")
    adjusted = data.adj_close().loc[endpoints]
    rows = []
    query_seconds = 0.0
    for i, (d, next_d) in enumerate(zip(endpoints[:-1], endpoints[1:])):
        mask = eligible(d, data)
        codes = mask.index[mask]
        before = perf_counter()
        # Query the full financial universe before restricting to eligible stocks.
        pit = fundamentals.roe_ttm(d).reindex(codes)
        naive = fundamentals.roe_ttm(d, naive=True).reindex(codes)
        query_seconds += perf_counter() - before
        returns = (adjusted.loc[next_d] / adjusted.loc[d] - 1).reindex(codes)
        ic_pit, n_pit = rank_ic(pit, returns)
        ic_naive, n_naive = rank_ic(naive, returns)
        both = pit.notna() & naive.notna()
        different = (naive[both] - pit[both]).abs() > 1e-9 * pit[both].abs()
        rows.append({"date": d, "ic_pit": ic_pit, "ic_naive": ic_naive,
                     "n_pit": n_pit, "n_naive": n_naive,
                     "share_diff": different.mean() if both.any() else np.nan,
                     "share_naive_only": (naive.notna() & pit.isna()).mean()
                     if len(codes) else np.nan})
        if (i + 1) % 24 == 0 or i == len(endpoints) - 2:
            print(f"Months {i + 1}/{len(endpoints) - 1}; "
                  f"factor queries {query_seconds:.2f}s", flush=True)
    result = pd.DataFrame(rows)
    output = Path("reports/a1")
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "pit_ic.csv.tmp"
    result.to_csv(temporary, index=False, date_format="%Y-%m-%d")
    temporary.replace(output / "pit_ic.csv")
    meta = json.loads(Path("data/fundamentals/fin_meta.json").read_text())
    temporary = output / "pit_ic.md.tmp"
    temporary.write_text(report(result, meta["release_id"]), encoding="utf-8")
    temporary.replace(output / "pit_ic.md")
    print(f"Wrote {len(result)} months to {output}/pit_ic.csv and pit_ic.md; "
          f"factor queries {query_seconds:.2f}s; total {perf_counter() - started:.2f}s", flush=True)


if __name__ == "__main__":
    main()
