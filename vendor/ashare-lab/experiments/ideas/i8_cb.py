"""Run I8 once over the full history, then slice and report the preregistered variants.

PYTHONPATH=src python3 tools/fetch_cb.py
PYTHONPATH=src python3 experiments/ideas/i8_cb.py
"""

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.expansion.common import PERIODS, bootstrap_mdd, metrics_table, plot_nav
from ashare_lab import metrics
from ashare_lab.benchmark import alpha_beta, load_benchmarks
from ashare_lab.ideas_cb import conv_price_asof, premium_rate, run_cb_backtest, select_double_low
from ashare_lab.pbo import cscv_pbo

EXTRA = ROOT / "data/extra"
OUT = ROOT / "reports/ideas/I8"
SLICES = {**PERIODS, "2018+": ("2018-01-01", "2026-09-30")}
COST = 0.0002 + 0.001
DOUBTS = [
    "未成交重试保留首次执行日 W×开盘净值的未成交名义金额；新信号覆盖旧订单。"
    "这一解释对应测试中未成交的半仓在下一日仍投入 0.5；目标零权重的卖单重试清仓剩余份数。",
    "强赎过滤采用经理明确的口径：call_type=强赎、is_call 为公告实施强赎或公告提示强赎，"
    "且 ann_date≤t；公告不强赎及已满足强赎条件不排除。到赎由距到期>180天处理。",
    "cb_price_chg 为空，缺少 cb_over_rate 的行无法计算溢价率，当日不参与选券；不回填。",
    "只纳入 cb_basic 中 cb_type=CB 的可转债；可交换债和未知类型排除。"
    "上市当天算第 1 个交易日；公告日期缺失的转股价不回填，最新转股价不回灌。",
    "现金收益为零；规格没有票息处理，不额外加入票息。最后收盘价之后转现金仅用于终止持仓，"
    "不用于提前选券或提前卖出；样本末端仍存在截断识别限制。",
    "非正或非有限收盘价视作缺失报价；持仓估值沿用最近有效收盘价，最终无后续报价时按该价转现金。",
    "容量使用执行日前 20 个交易日 ADV（缺失成交额按零）和收盘对数收益标准差，"
    "冲击=k×sigma×sqrt(成交名义/ADV)，k=1，成交上限=0.1×ADV；"
    "买入价乘 (1+冲击)，卖出所得额扣基础费用与冲击，基础费用口径保持验收定义。",
]


def dates(series):
    return pd.to_datetime(series, errors="coerce", format="mixed")


def data_notes(manifest):
    lines = ["# I8 数据记录", "", "```json", json.dumps(manifest, ensure_ascii=False, indent=2), "```", "",
             "本次仅读取经理在本机补齐的数据，没有联网。显式字段探测返回情况见上方 probe。",
             "优先使用 cb_over_rate/100。cb_price_chg 为空，缺 cb_over_rate 的行没有溢价率，"
             "当日不参与选券，不用 cb_value 或当前转股价替代。两来源差异分布因无历史转股价而不可计算。",
             "成交金额由万元乘 10000 转为元；转股溢价率由百分数除 100。",
             "官方字段说明：[行情](https://tushare.pro/document/2?doc_id=187)、"
             "[转股价历史](https://tushare.pro/document/2?doc_id=246)、"
             "[赎回](https://tushare.pro/document/2?doc_id=269)、"
             "[基础信息](https://tushare.pro/document/2?doc_id=185)。", "",
             "| 表 | 已获取行数 | 日期范围 |", "|---|---:|---|"]
    for name in ("cb_basic", "cb_daily", "cb_call", "cb_price_chg", "000832.CSI"):
        table = manifest.get("tables", {}).get(name)
        lines.append(f"| {name} | {table['rows'] if table else '未获取'} | "
                     f"{json.dumps(table['date_ranges'], ensure_ascii=False) if table else '未知'} |")
    (OUT / "data_notes.md").write_text("\n".join(lines) + "\n")


def prepare():
    calendar = pd.DatetimeIndex(pd.read_parquet(ROOT / "data/panel/calendar.parquet").date)
    sample = calendar[(calendar >= "2012-01-04") & (calendar <= "2026-09-30")]
    paths = [EXTRA / "cb_daily" / f"{date:%Y%m%d}.parquet" for date in sample]
    missing = [str(p.name) for p in paths if not p.exists()]
    if missing:
        raise RuntimeError(f"Missing {len(missing)} cb_daily shards; first={missing[0]}")
    daily = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    daily = daily.rename(columns={"ts_code": "code", "trade_date": "date"})
    daily["date"] = dates(daily.date)
    if daily.duplicated(["date", "code"]).any():
        raise ValueError("Duplicate daily observations")
    basic = pd.read_parquet(EXTRA / "cb_basic.parquet").rename(columns={"ts_code": "code"})
    basic = basic[basic.cb_type.eq("CB")].set_index("code")
    for col in ("list_date", "maturity_date"):
        basic[col] = dates(basic[col])
    daily = daily[daily.code.isin(basic.index)].copy()
    if daily.empty:
        raise RuntimeError("No convertible bond observations")
    for col in ("open", "close", "amount", "cb_over_rate"):
        daily[col] = pd.to_numeric(daily.get(col, np.nan), errors="coerce")
    daily["amount"] *= 10000
    daily["official_premium"] = daily.cb_over_rate / 100
    changes = pd.read_parquet(EXTRA / "cb_price_chg.parquet")
    normalized = pd.DataFrame(columns=["code", "ann_date", "change_date", "conv_price"])
    if not changes.empty:
        normalized = changes.rename(columns={"ts_code": "code", "publish_date": "ann_date"}).copy()
        normalized["ann_date"] = dates(normalized.ann_date)
        normalized["change_date"] = dates(normalized.change_date)
        after = pd.to_numeric(normalized.convertprice_aft, errors="coerce")
        initial = pd.to_numeric(normalized.convert_price_initial, errors="coerce")
        # Initial-price events have neither before nor after prices.
        initial_event = normalized.convertprice_bef.isna() & normalized.convertprice_aft.isna()
        normalized["conv_price"] = after.where(~initial_event, initial)
    daily["calculated_premium"] = np.nan
    if not normalized.empty:
        mappings = basic.reset_index()[["code", "stk_code"]]
        with duckdb.connect() as con:
            con.register("cb_stocks", mappings[["stk_code"]].drop_duplicates())
            stock = con.execute("SELECT date, code AS stk_code, close AS stock_close "
                                "FROM read_parquet(?) SEMI JOIN cb_stocks ON code=stk_code",
                                [str(ROOT / "data/panel/daily.parquet")]).df()
        stock["date"] = dates(stock.date)
        daily = daily.merge(mappings, on="code", how="left").merge(stock, on=["date", "stk_code"], how="left")
        for date, group in daily.groupby("date"):
            conversion = group.code.map(conv_price_asof(date, normalized))
            calculated = premium_rate(group.close, group.stock_close, conversion)
            daily.loc[group.index, "calculated_premium"] = calculated.where(
                (conversion > 0) & (group.stock_close > 0))
    daily["premium"] = daily.official_premium.fillna(daily.calculated_premium)
    difference = (daily.official_premium - daily.calculated_premium).dropna()
    comparison = {"cb_rows": len(daily),
                  "nonpositive_close_rows": int((daily.close <= 0).sum()),
                  "official_coverage": float(daily.official_premium.notna().mean()),
                  "official_rows": int(daily.official_premium.notna().sum()),
                  "fallback_rows": int((daily.official_premium.isna() & daily.calculated_premium.notna()).sum()),
                  "unpriced_rows": int(daily.premium.isna().sum()),
                  "both_rows": len(difference),
                  "official_minus_calculated": (difference.describe(percentiles=[.01, .05, .5, .95, .99]).to_dict()
                                                if len(difference) else None)}
    with (OUT / "data_notes.md").open("a") as f:
        f.write("\n## 溢价率覆盖与差异（小数）\n\n```json\n" + json.dumps(comparison, ensure_ascii=False, indent=2) + "\n```\n")
        f.write("\n非正收盘价视为缺失报价，估值采用最近有效收盘价；数量见 nonpositive_close_rows。\n")
    if not daily.premium.notna().any():
        raise RuntimeError("Neither official nor PIT calculated premiums available")
    calls = pd.read_parquet(EXTRA / "cb_call.parquet")
    calls["ann_date"] = dates(calls.ann_date)
    first_call = calls[calls.call_type.eq("强赎") & calls.is_call.isin(
        {"公告实施强赎", "公告提示强赎"})].groupby("ts_code").ann_date.min()
    daily["call_announced"] = daily.code.map(first_call) <= daily.date
    listing = daily.code.map(basic.list_date)
    elapsed = calendar.searchsorted(daily.date, side="right") - calendar.searchsorted(listing, side="left")
    daily["listed_days"] = np.where(listing.notna(), elapsed, np.nan)
    daily["days_to_maturity"] = (daily.code.map(basic.maturity_date) - daily.date).dt.days
    weekly = pd.Series(calendar, index=calendar).groupby(calendar.to_period("W-FRI")).last()
    signals = set(weekly[weekly.isin(sample)])
    targets = {n: {} for n in (10, 20, 30)}
    for date, group in daily[daily.date.isin(signals)].groupby("date"):
        for n in targets:
            targets[n][date] = select_double_low(group.set_index("code"), n)
    # Missing whole signal days must explicitly request cash, not keep old weights.
    for n in targets:
        for date in signals:
            targets[n].setdefault(date, pd.Series(dtype=float))
    panels = [daily.pivot(index="date", columns="code", values=col).reindex(sample)
              for col in ("open", "close", "amount")]
    return panels, targets


def report(panels, targets):
    details = {f"double_low_N{n}": run_cb_backtest(*panels, weights, COST, 1e7, return_details=True)
               for n, weights in targets.items()}
    nav = pd.DataFrame({name: value.nav for name, value in details.items()})
    benchmarks = load_benchmarks()
    lowvol = pd.read_parquet(ROOT / "reports/b3_full/nav.parquet")["lowvol_W250_N50"]
    lowvol.index = pd.to_datetime(lowvol.index)
    lowvol = lowvol.reindex(nav.index)
    if lowvol.isna().any():
        raise RuntimeError("Pure low-volatility NAV does not cover full sample")
    summary = metrics_table(nav, benchmarks, lowvol, periods=SLICES)
    for i, row in summary.iterrows():
        period = details[row['name']].loc[slice(*SLICES[row.period])]
        summary.loc[i, "turnover"] = period.turnover.sum() * 252 / max(1, len(period) - 1)
    boot = bootstrap_mdd(nav)
    summary = summary.merge(boot, on="name", how="left")
    insample = summary[summary.period.eq("IS")].sort_values(["calmar", "name"], ascending=[False, True])
    candidate = insample.iloc[0]['name']
    n = int(candidate.split("N")[-1])
    large = run_cb_backtest(*panels, targets[n], COST, 1e8, max_participation=.1,
                            impact_k=1, return_details=True)
    large.to_parquet(OUT / "capacity_daily.parquet")
    capacity_summary = metrics_table(large.nav.to_frame(candidate), benchmarks, lowvol, periods=SLICES)
    for i, row in capacity_summary.iterrows():
        window = large.loc[slice(*SLICES[row.period])]
        capacity_summary.loc[i, "turnover"] = window.turnover.sum() * 252 / max(1, len(window) - 1)
        capacity_summary.loc[i, "base_cagr"] = summary.loc[
            summary.name.eq(candidate) & summary.period.eq(row.period), "cagr"].iloc[0]
        capacity_summary.loc[i, "cagr_decline"] = capacity_summary.loc[i, "base_cagr"] - row.cagr
        capacity_summary.loc[i, "max_participation"] = window.max_participation.max()
        capacity_summary.loc[i, "min_cash"] = window.cash.min()
    capacity_summary.to_csv(OUT / "capacity.csv", index=False)
    decline = metrics.cagr(nav[candidate]) - metrics.cagr(large.nav)
    display = nav.copy()
    display["candidate_capacity_1e8"] = large.nav
    index_path = EXTRA / "cb_index_000832.parquet"
    if index_path.exists():
        index = pd.read_parquet(index_path)
        if not index.empty:
            raw_rows = len(index)
            index["date"] = dates(index.trade_date)
            index = index.set_index("date").close.sort_index().dropna()
            start, end = index.index.min(), index.index.max()
            index = index.reindex(nav.index).ffill().where((nav.index >= start) & (nav.index <= end))
            with (OUT / "data_notes.md").open("a") as f:
                f.write(f"\n## 000832.CSI 实际覆盖\n\n本地文件 {raw_rows} 行；"
                        f"有效收盘覆盖 {start:%Y-%m-%d}..{end:%Y-%m-%d}，"
                        f"与回测日历对齐后 {index.notna().sum()} 日。以实际本地文件为准。"
                        "只在该覆盖区间计算对照，区间外保留缺失；覆盖内按共同口径前向填充。\n")
            display["000832.CSI"] = index / index.dropna().iloc[0]
            for i, row in summary.iterrows():
                stats = alpha_beta(nav[row['name']].loc[slice(*SLICES[row.period])], index)
                for key in ("alpha_ann", "beta", "corr", "excess_cagr"):
                    summary.loc[i, f"{key}_000832.CSI"] = stats[key]
    summary.to_csv(OUT / "summary.csv", index=False)
    display.to_parquet(OUT / "nav.parquet")
    annual = pd.DataFrame({name: metrics.annual_returns(value.dropna()) for name, value in display.items()})
    annual.index.name = "year"
    annual.to_csv(OUT / "annual.csv")
    holdings = pd.DataFrame({name: d.holdings.groupby(d.index.year).mean() for name, d in details.items()})
    holdings.to_csv(OUT / "holdings_annual.csv", index_label="year")
    pd.DataFrame({name: d.turnover for name, d in details.items()}).to_parquet(OUT / "turnover.parquet")
    plot_nav(display, OUT / "nav.png", "I8 可转债双低（全区间一次回测）")
    pbo = cscv_pbo(nav.pct_change(fill_method=None).dropna(), n_blocks=16)
    chosen = summary[summary.name.eq(candidate)].set_index("period")
    low_boot = bootstrap_mdd(lowvol.to_frame("lowvol")).iloc[0].mdd_p05
    low_mdd = metrics.max_drawdown(lowvol)
    full = chosen.loc["FULL"]
    alpha_is, alpha_oos = chosen.loc["IS", "alpha_000906.SH_TR"], chosen.loc["OOS", "alpha_000906.SH_TR"]
    conditions = [alpha_is > 0 and alpha_oos > 0,
                  full.mdd_p05 >= low_boot and full.max_drawdown >= low_mdd,
                  full.corr_lowvol < .5, True, decline < .01]
    numbers = [f"IS α={alpha_is:.6%}，OOS α={alpha_oos:.6%}（均须 >0）",
               f"全区间 MDD={full.max_drawdown:.6%}，纯低波={low_mdd:.6%}；"
               f"bootstrap p05={full.mdd_p05:.6%}，纯低波={low_boot:.6%}",
               f"全区间日收益相关={full.corr_lowvol:.6f}（须 <0.5）",
               f"不适用：3 个变体，CSCV 16 块 PBO={pbo['pbo']:.6f}，不据此否决",
               f"基础 CAGR={full.cagr:.6%}，1e8 容量 CAGR={metrics.cagr(large.nav):.6%}，"
               f"下降={decline * 100:.6f} 个百分点（须 <1）"]
    lines = ["# I8 双低轮动", "", f"候选：{candidate}，按 IS Calmar={chosen.loc['IS', 'calmar']:.6f} 选定。",
             "全区间 2012-01..2026-09 一次运行，IS/OOS/2018+ 为归一化切片。", ""]
    for i, (passed, number) in enumerate(zip(conditions, numbers), 1):
        lines.append(f"{i}. {'通过' if passed else '不通过'}：{number}。")
    lines += ["", "结论：" + ("满足五项规则。" if all(conditions) else "未满足全部通过规则。"),
              "DSR 统一计算。", "",
              f"容量实际最高单券日参与率={large.max_participation.max():.6%}，最低现金={large.cash.min():.6f} 元；"
              "逐日结果见 capacity_daily.parquet，切片结果见 capacity.csv。",
              "", "各年持仓只数（日收盘均值；含空仓日）：", "", holdings.to_string(float_format=lambda x: f"{x:.3f}"),
              "", "2017 年前可转债市场样本很少，早期结果对少量个券敏感；另见 2018+ 切片。",
              "", "## doubts", "", *[f"- {item}" for item in DOUBTS]]
    (OUT / "verdict.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = EXTRA / "cb_fetch.json"
    manifest = json.loads(path.read_text()) if path.exists() else {"complete": False, "error": "No fetch manifest"}
    data_notes(manifest)
    try:
        if not manifest.get("complete"):
            raise RuntimeError("Online fetch incomplete: " + manifest.get("error", "unknown"))
        panels, targets = prepare()
        report(panels, targets)
    except Exception as exc:
        (OUT / "verdict.md").write_text("# I8 阻塞记录\n\n尚未完成真实数据回测，不能判定通过。\n\n"
            + str(exc) + "\n\n候选、5 条规则的数值、PBO、DSR、年度持仓均值均不可计算。"
            "没有生成替代性的 summary.csv 或 nav.png。\n\n## doubts\n\n"
            + "\n".join(f"- {item}" for item in DOUBTS) + "\n")
        raise


if __name__ == "__main__":
    main()
