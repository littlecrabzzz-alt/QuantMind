"""Run the three preregistered I9 variants once, then slice IS/OOS reports.

Run from repository root: PYTHONPATH=src python3 experiments/ideas/i9_cta.py
Requires a completed tools/fetch_futures.py cache; never substitutes mock data.
"""
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports/ideas/I9"
DATA = ROOT / "data/extra/i9_futures"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / "mpl_cache"))
os.environ.setdefault("MPLBACKEND", "Agg")

from ashare_lab import metrics
from ashare_lab.benchmark import load_benchmarks
from ashare_lab.ideas_cta import (continuous_returns, trend_signal, carry_signal,
                                roll_yield, size_positions, run_futures_portfolio)
from ashare_lab.pbo import cscv_pbo
from experiments.expansion.common import metrics_table, bootstrap_mdd, plot_nav
from tools.fetch_futures import PRODUCTS, SUFFIX

DOUBTS = [
    "组合信号只在趋势与期限结构信号同时有效的品种上取平均，不把缺失信号当作中性信号。",
    "250 个收益门槛按实际有效报价累计；对齐后的缺报价零收益不增加预热样本数。趋势窗口和波动率窗口按上交所交易日计。",
    "期限结构以 d_month 判交割月先后，以 delist_date（最后交易日）之差作为到期天数差；不使用未来持仓量或价格。",
    "期限结构并列按品种代码排序；不足 3 个有效品种时 k=0、全部为零信号。",
    "同日移仓和周调仓先按旧权重计双边移仓成本，再按目标变化计调仓成本，保守地不抵销两者。",
    "N_t 为各变体当期有有效信号且有正波动率的品种数，包含信号为零的品种。",
    "DSR 统一计算：由经理汇总 I1–I9 全部 23 个变体后计算，本任务不估算 DSR。",
    "主力映射的部分早期合约不在固定品种基础表中，未自行补入历史别名；逐品种缺口与归档抽样对照见 data_notes.md。",
]


def load_inputs():
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(
        ROOT / "data/panel/calendar.parquet").date)).sort_values()
    calendar = calendar[(calendar >= "2011-01-01") & (calendar <= "2026-09-30")]
    basic = pd.read_parquet(DATA / "basic.parquet").drop_duplicates("ts_code").set_index("ts_code")
    daily = pd.concat([pd.read_parquet(DATA / "contracts" / f"{code}.parquet")
                       for code in basic.index], ignore_index=True)
    daily["date"] = pd.to_datetime(daily.trade_date, format="%Y%m%d")
    daily = daily.drop_duplicates(["date", "ts_code"], keep="last")
    daily["price"] = daily.close.fillna(daily.settle)
    daily.loc[daily.price <= 0, "price"] = np.nan
    raw = daily.pivot(index="date", columns="ts_code", values="price").reindex(calendar)
    oi = daily.pivot(index="date", columns="ts_code", values="oi").reindex(calendar)
    mappings = pd.read_parquet(DATA / "mapping.parquet")
    mappings["date"] = pd.to_datetime(mappings.trade_date, format="%Y%m%d")
    codes = [f"{p}.{SUFFIX[e]}" for e, products in PRODUCTS.items() for p in products]
    map_raw = mappings.drop_duplicates(["date", "ts_code"]).pivot(
        index="date", columns="ts_code", values="mapping_ts_code").reindex(index=calendar, columns=codes)
    mapping = map_raw.ffill()
    for field in ("list_date", "delist_date"):
        basic[field] = pd.to_datetime(basic[field], format="%Y%m%d", errors="coerce")
    basic["delivery"] = pd.to_datetime(basic.d_month.astype(str).str.replace(
        r"\.0$", "", regex=True), format="%Y%m", errors="coerce")
    ret, rolled, observed, gaps = {}, {}, {}, []
    for code in codes:
        product = code.split(".")[0]
        contracts = basic.index[basic.fut_code == product]
        p = raw.reindex(columns=contracts)
        obs, _ = continuous_returns(p, mapping[code])
        ret[code], rolled[code] = continuous_returns(p.ffill(), mapping[code])
        observed[code] = obs.notna().cumsum()
        valid = obs.dropna()
        active = mapping[code].notna()
        gaps.append({"product": code, "contracts": len(contracts),
                     "contracts_with_daily": int(daily.ts_code.isin(contracts).groupby(daily.ts_code).any().sum()),
                     "first_return": valid.index.min(), "last_return": valid.index.max(),
                     "observed_returns": len(valid),
                     "missing_mapping_after_start": int((active & map_raw[code].isna()).sum()),
                     "missing_return_after_start": int((active & obs.isna()).sum()),
                     "missing_delivery_month": int(basic.loc[contracts, "delivery"].isna().sum()),
                     "mapped_contracts_absent_from_basic": ",".join(sorted(
                         set(mapping[code].dropna()) - set(contracts)))})
    gaps = pd.DataFrame(gaps)
    gaps.to_csv(OUT / "data_coverage.csv", index=False)
    notes = ["# I9 数据说明", "", "来源：Tushare pro.query；合约缓存 data/extra/i9_futures/。",
             f"固定品种数 {len(codes)}；取得有效收益的品种数 {(gaps.observed_returns > 0).sum()}；"
             f"基础表合约数 {len(basic)}；有日线合约数 {daily.ts_code.nunique()}；日线 {len(daily)} 行。",
             f"日线日期范围：{daily.date.min().date()} 至 {daily.date.max().date()}。",
             f"close 缺失而 settle 有效的行数：{int((daily.close.isna() & daily.settle.notna()).sum())}。",
             f"日历外日线行数（丢弃）：{int((~daily.date.isin(calendar)).sum())}。",
             "价格先取 close、缺失取 settle；日历外数据丢弃，日历内缺口前向填充，缺报价日收益为零。"
             "持仓量及期限结构当日报价不填充；主力映射缺口沿用已知映射，不反向填充。",
             "各品种日期范围与缺口见 data_coverage.csv；缺口统计包括首次主力出现当日无法计算收益的一行。",
             "mapped_contracts_absent_from_basic 列列出主力映射中没有对应基础表合约的代码；"
             "未将未列入固定品种清单的历史代码自动改名或拼入，缺价期间不增加有效收益样本数。",
             "", gaps.to_string(index=False), "", "## doubts", *[f"- {d}" for d in DOUBTS]]
    (OUT / "data_notes.md").write_text("\n".join(notes), encoding="utf-8")
    return calendar, basic, raw, oi, mapping, pd.DataFrame(ret), pd.DataFrame(rolled), pd.DataFrame(observed)


def targets_for_variants(calendar, basic, raw, oi, mapping, ret, observed):
    weeks = pd.Series(calendar, index=calendar).groupby(calendar.to_period("W-FRI")).last()
    targets = {name: {} for name in ("trend", "carry", "combined")}
    eligibility = observed.ge(250)
    for t in weeks[weeks >= pd.Timestamp("2012-01-01")]:
        window = ret.loc[:t].tail(60).fillna(0)
        vol = window.std(ddof=1) * np.sqrt(252)
        eligible = eligibility.loc[t] & vol.gt(0)
        trend = trend_signal(ret, t).where(eligible).dropna()
        yields = pd.Series(np.nan, index=ret.columns)
        for product in ret.columns[eligible]:
            near = mapping.at[t, product]
            if near not in basic.index or near not in raw.columns:
                continue
            info = basic.loc[near]
            far = basic[(basic.fut_code == info.fut_code) &
                        (basic.delivery > info.delivery) & (basic.list_date <= t) &
                        (basic.delist_date > t)]
            far = far.loc[oi.loc[t].reindex(far.index).fillna(0).gt(0)]
            if far.empty:
                continue
            far = far.sort_index().sort_values(["delivery", "delist_date"], kind="stable")
            code = far.index[0]
            days = (far.iloc[0].delist_date - info.delist_date).days
            yields[product] = roll_yield(raw.at[t, near], raw.at[t, code], days)
        carry = carry_signal(yields)
        signals = {"trend": trend, "carry": carry, "combined": ((trend + carry) / 2).dropna()}
        for name, signal in signals.items():
            signal = signal[vol.reindex(signal.index).gt(0)]
            raw_weights = signal * 0.10 / vol.reindex(signal.index) / max(len(signal), 1)
            port_vol = window.reindex(columns=signal.index).mul(raw_weights).sum(axis=1).std(ddof=1) * np.sqrt(252)
            targets[name][t] = size_positions(signal, vol, port_vol, 0.10, 3.0)
    return targets, eligibility


def compare_archive(ret):
    """Read-only, reproducible splice diagnostic; never feeds strategy signals."""
    import duckdb
    from ashare_lab.data.build import SOURCE

    sampled = sorted(np.random.default_rng(0).choice(sorted(ret.columns), 3, replace=False))
    archive_codes = {code: code.replace(".", "L.", 1) for code in sampled}
    release = json.loads((SOURCE / "CURRENT.json").read_text())["release_id"]
    path_cache = DATA / "archive_adj_paths.json"
    cached = json.loads(path_cache.read_text()) if path_cache.exists() else {}
    if cached.get("release") != release:
        manifest = json.loads((SOURCE / "releases" / release / "manifest.json").read_text())
        cached = {"release": release, "paths": [str(SOURCE / d["path"])
                  for d in manifest["datasets"] if d["api_name"] == "fut_daily_adj"]}
        path_cache.write_text(json.dumps(cached))
    paths = cached["paths"]
    if not paths:
        raise RuntimeError("CURRENT archive has no fut_daily_adj files")
    parts = []
    print(f"Archive diagnostic: {sampled}; {len(paths)} files", flush=True)
    with duckdb.connect() as con:
        con.execute("SET threads=4")
        con.execute("SET memory_limit='1GB'")
        for offset in range(0, len(paths), 512):
            parts.append(con.execute(
                "SELECT source_ts_code, trade_date, close, "
                "_fetched_at::TIMESTAMPTZ AS fetched_at "
                "FROM read_parquet(?, union_by_name=true, hive_partitioning=false) "
                "WHERE source_ts_code IN (?, ?, ?)",
                [paths[offset:offset + 512], *archive_codes.values()]).df())
            print(f"Archive diagnostic: {min(offset + 512, len(paths))}/{len(paths)} files", flush=True)
    archive = pd.concat(parts, ignore_index=True).sort_values("fetched_at", na_position="first")
    archive = archive.drop_duplicates(["source_ts_code", "trade_date"], keep="last")
    archive["date"] = pd.to_datetime(archive.trade_date, format="%Y%m%d")
    rows, trajectories = [], {}
    for product, code in archive_codes.items():
        available = archive.loc[archive.source_ts_code == code].set_index("date").close.sort_index()
        available = available.loc[available > 0].reindex(ret.index).dropna()
        if len(available) < 2:
            raise RuntimeError(f"Insufficient archived continuous closes for {code}")
        dates = ret.index[(ret.index >= available.index[0]) & (ret.index <= available.index[-1])]
        prices = available.reindex(dates).ffill()
        own = (1 + ret[product].fillna(0)).cumprod().where(ret[product].notna().cummax())
        aligned = pd.concat([own.rename("own"), prices.rename("archive")], axis=1).dropna()
        aligned = aligned / aligned.iloc[0]
        returns = aligned.pct_change(fill_method=None)
        quoted = available.reindex(aligned.index).notna()
        adjacent_quotes = quoted & quoted.shift(fill_value=False)
        missing = ~quoted
        adjacent_returns = returns.loc[adjacent_quotes]
        rows.append({"product": product, "archive_code": code, "start": aligned.index[0],
                     "end": aligned.index[-1], "observations": len(aligned),
                     "archive_missing_days_filled": int(prices.reindex(aligned.index).notna().sum() -
                                                       available.reindex(aligned.index).notna().sum()),
                     "nav_correlation": aligned.own.corr(aligned.archive),
                     "daily_return_correlation": returns.own.corr(returns.archive),
                     "adjacent_quote_return_pairs": int(adjacent_quotes.sum()),
                     "adjacent_quote_return_correlation": adjacent_returns.own.corr(adjacent_returns.archive),
                     "adjacent_quote_return_mae": (adjacent_returns.own - adjacent_returns.archive).abs().mean(),
                     "longest_missing_run": int(missing.groupby(quoted.cumsum()).sum().max()),
                     "own_cagr": metrics.cagr(aligned.own), "archive_cagr": metrics.cagr(aligned.archive),
                     "cagr_difference": metrics.cagr(aligned.own) - metrics.cagr(aligned.archive)})
        trajectories[f"{product}_own"] = aligned.own
        trajectories[f"{code}_archive"] = aligned.archive
    comparison = pd.DataFrame(rows)
    comparison.to_csv(OUT / "continuous_comparison.csv", index=False)
    pd.DataFrame(trajectories).to_parquet(OUT / "continuous_comparison_nav.parquet")
    with (OUT / "data_notes.md").open("a", encoding="utf-8") as f:
        f.write("\n\n## 随机抽样连续合约拼接对照\n\n")
        f.write(f"固定随机种子 0，从按代码排序的全部 45 个品种中无放回抽取 3 个：{', '.join(sampled)}。\n")
        f.write(f"只读归档 CURRENT release：{release}；接口 fut_daily_adj，取 <品种>L.<交易所> 的 close；同代码日期取 _fetched_at 最新记录。\n")
        f.write("两条走势在共同可用区间按上交所日历对齐，归一到首日 1；归档内缺口前向填充，末日之后不延伸。")
        f.write("主力累计净值为不含成本、不含仓位缩放的 (1+r) 累乘。年化收益用 252 日复利，差值为本实现减归档（小数单位）。\n\n")
        f.write(comparison.to_string(index=False, float_format=lambda x: f"{x:.8f}"))
        f.write("\n\n同时报告净值水平与日收益的 Pearson 相关，避免仅用净值水平掩盖拼接差异；")
        f.write("adjacent_quote_return_correlation/mae 仅使用相邻两个上交所交易日都有归档真实报价的收益对，")
        f.write("排除长缺口零收益及跨缺口跳变对逐日相关性的影响；longest_missing_run 为最长连续缺失交易日数。")
        f.write("对比仅作诊断，不更改主力映射、信号或策略参数。归档连续合约的复权及换月规则可能与本任务不同，差异不自动等同于实现错误。\n")
        if (comparison.daily_return_correlation < .9).any():
            f.write("\n检查提示：抽样的全区间日收益相关低于 0.9，存在明显不一致；结合归档缺口及真实相邻报价的对照判断，不能据此宣称拼接已通过独立验证。\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (DATA / "complete.json").exists():
        raise RuntimeError("Commodity cache incomplete: run tools/fetch_futures.py first; no backtest fabricated")
    print("Loading local commodity data", flush=True)
    inputs = load_inputs()
    calendar, _, _, _, _, ret, rolled, _ = inputs
    compare_archive(ret)
    print("Building weekly signals for three variants", flush=True)
    targets, eligibility = targets_for_variants(*inputs[:6], inputs[7])
    dates = calendar[calendar >= "2012-01-01"]
    navs, positions, turnover = {}, {}, {}
    for name, schedule in targets.items():
        print(f"Running {name}", flush=True)
        result = run_futures_portfolio(ret.reindex(dates), schedule, rolled.reindex(dates), .0002)
        positions[name] = result.attrs["weights"]
        turnover[name] = result.attrs["traded_notional"].sum() / 2 / result.mean() * 252 / (len(result) - 1)
        pd.DataFrame({"traded_notional": result.attrs["traded_notional"],
                      "costs": result.attrs["costs"]}).to_parquet(OUT / f"{name}_trading.parquet")
        positions[name].to_parquet(OUT / f"{name}_weights.parquet")
        result.attrs = {}
        navs[name] = result
    nav = pd.DataFrame(navs).reindex(dates).ffill()
    nav.to_parquet(OUT / "nav.parquet")
    lowvol = pd.read_parquet(ROOT / "reports/b3_full/nav.parquet")["lowvol_W250_N50"].reindex(dates)
    benchmarks = load_benchmarks(ROOT / "data/benchmarks")
    summary = metrics_table(nav, benchmarks, lowvol, turnover)
    print("Computing metrics and bootstrap", flush=True)
    boot = bootstrap_mdd(nav.assign(lowvol=lowvol))
    summary = summary.merge(boot, on="name", how="left")
    summary["avg_gross"] = summary.name.map({name: w.abs().sum(axis=1).mean() for name, w in positions.items()})
    summary.to_csv(OUT / "summary.csv", index=False)
    boot.to_csv(OUT / "bootstrap.csv", index=False)
    pd.DataFrame({name: metrics.annual_returns(nav[name]) for name in nav}).to_csv(OUT / "annual.csv", index_label="year")
    rows = []
    for name, w in positions.items():
        for year, group in w.groupby(w.index.year):
            rows.append({"name": name, "year": year,
                         "eligible_products": int(eligibility.reindex(group.index).any().sum()),
                         "participating_products": int(group.ne(0).any().sum()),
                         "mean_active_products": group.ne(0).sum(axis=1).mean(),
                         "avg_gross": group.abs().sum(axis=1).mean()})
    participation = pd.DataFrame(rows)
    participation.to_csv(OUT / "participation.csv", index=False)
    inside = summary[summary.period == "IS"].set_index("name").reindex(nav.columns)
    candidate = inside.calmar.idxmax()
    candidate_rows = summary[summary.name == candidate].set_index("period")
    full = candidate_rows.loc["FULL"]
    pbo = cscv_pbo(nav.pct_change(fill_method=None).dropna(), n_blocks=16)
    (OUT / "pbo.json").write_text(json.dumps({k: pbo[k] for k in ("pbo", "n_splits", "n_obs", "prob_oos_loss", "degradation_slope")}, indent=2))
    low_mdd = metrics.max_drawdown(lowvol)
    low_p05 = boot.set_index("name").at["lowvol", "mdd_p05"]
    rule1 = bool((candidate_rows.loc[["IS", "OOS"], "alpha_000906.SH_TR"] > 0).all())
    rule2 = bool(full.max_drawdown >= low_mdd and full.mdd_p05 >= low_p05)
    rule3 = bool(full.corr_lowvol < .5)
    label = lambda passed: "通过" if passed else "不通过"
    combined = nav[[candidate]].join(benchmarks[["000906.SH"]], how="left")
    monthly = (1 + combined.pct_change(fill_method=None).fillna(0)).groupby(combined.index.to_period("M")).prod() - 1
    crisis = monthly.nsmallest(10, "000906.SH")
    crisis.to_csv(OUT / "crisis_months.csv", index_label="month")
    text = ["# I9 商品期货 CTA", "", f"候选：{candidate}（只按 IS Calmar 选择）。",
            inside[["calmar"]].to_string(), "",
            f"1. α：{label(rule1)}；IS={candidate_rows.at['IS', 'alpha_000906.SH_TR']:.6f}，OOS={candidate_rows.at['OOS', 'alpha_000906.SH_TR']:.6f}，要求均 >0。",
            f"2. 回撤：{label(rule2)}；FULL MDD={full.max_drawdown:.6f}，纯低波={low_mdd:.6f}；bootstrap p05={full.mdd_p05:.6f}，纯低波={low_p05:.6f}。",
            f"3. 相关：{label(rule3)}；全区间日收益对纯低波相关={full.corr_lowvol:.6f}，要求 <0.5。",
            f"4. 过拟合：通过（门槛不适用）；变体数=3，CSCV 16 块 PBO={pbo['pbo']:.6f}，切分数={pbo['n_splits']}。",
            "5. 容量：通过（不适用）；期货按无冲击处理，不适用；模型中资金规模由 1e7 放大到 1e8 的年化收益下降=0。",
            "", f"结论：按预登记五条规则{label(rule1 and rule2 and rule3)}。",
            f"候选 OOS 年化收益={candidate_rows.at['OOS', 'cagr']:.6f}，OOS Calmar={candidate_rows.at['OOS', 'calmar']:.6f}；"
            f"PBO={pbo['pbo']:.6f}，即使规则 4 不适用，仍需结合这些数值判断样本外表现与选优稳定性。",
            "归档抽样对照见 data_notes.md；对照差异只报告，不改变规格及五条规则判定。",
            "DSR 统一计算", "",
            "## 000906.SH 最差 10 个月", crisis.to_string(),
            f"候选在其中 {int((crisis[candidate] > 0).sum())}/10 个月赚钱；这 10 个月收益连乘={(1 + crisis[candidate]).prod() - 1:.6f}（非连续持有期）。",
            "", "## 每年参与品种数与杠杆", participation.to_string(index=False),
            f"候选平均总杠杆={full.avg_gross:.6f}。单边换手含移仓，按总成交名义的一半/平均净值年化；summary 的各切片复用全区间换手及全区间自助法。",
            "", "## doubts", *[f"- {d}" for d in DOUBTS]]
    (OUT / "verdict.md").write_text("\n".join(text), encoding="utf-8")
    plot_nav(nav.join(lowvol.rename("lowvol")), OUT / "nav.png", "I9 commodity CTA")
    print(f"I9 complete: candidate={candidate}, PBO={pbo['pbo']:.6f}", flush=True)


if __name__ == "__main__":
    main()
