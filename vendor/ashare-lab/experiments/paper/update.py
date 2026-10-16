"""更新纯模拟账户并生成中文日报；不连接任何券商或下单服务。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from ashare_lab.benchmark import load_benchmarks
from ashare_lab.data.build import SOURCE
from ashare_lab.data.fundamentals import Fundamentals
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import CostModel
from ashare_lab.paper import (LedgerMismatch, account_summary, append_ledger,
                              init_account, simulate)
from experiments.paper.accounts import INCEPTION, INITIAL_CASH, NAMES, make_accounts


def rebuild():
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    for args in [
        ["ashare_lab.data.build", "--out", "data/live/panel", "--start", "2010-01-01"],
        ["ashare_lab.data.fundamentals", "--out", "data/live/fundamentals", "--start", "2014-01-01"],
        ["ashare_lab.benchmark", "--panel", "data/live/panel", "--out", "data/live/benchmarks"],
    ]:
        subprocess.run(["python3", "-m", *args], cwd=ROOT, env=env, check=True)
    # 两个指针都读成功才清理；仅删除仓库本地 cache 的直接子目录。
    active = {json.loads((SOURCE / pointer).read_text())["release_id"]
              for pointer in ("RESEARCH_CURRENT.json", "CURRENT.json")}
    cache = ROOT / "data/cache"
    if cache.is_symlink() or cache.resolve().parent != (ROOT / "data").absolute():
        raise ValueError("data/cache 必须位于仓库本地，不能通过符号链接指向外部")
    for path in cache.iterdir():
        if (path.name.startswith("data-") and path.name not in active
                and path.is_dir() and not path.is_symlink()):
            shutil.rmtree(path)


def exchange_days(release, end):
    try:
        frame = pd.read_parquet(ROOT / "data/cache" / release / "trade_cal.parquet")
        frame = frame.loc[(frame.exchange == "SSE") &
                          (pd.to_numeric(frame.is_open) == 1)]
        column = "date" if "date" in frame else "cal_date"
        dates = pd.to_datetime(frame[column].astype(str))
        dates = pd.DatetimeIndex(dates).drop_duplicates().sort_values()
        if not (dates > end).any():
            return None, "交易所日历只到数据末日，月末按周一至周五规则判断（遇月末节假日可能晚一天确认）。"
        return dates, None
    except (OSError, ValueError, KeyError) as exc:
        return None, f"交易所开市日缓存不可读，月末暂按周一至周五规则判断（{type(exc).__name__}）。"


def next_month_end(end, open_days):
    if open_days is None:
        candidate = end + pd.offsets.BMonthEnd()
        return f"{candidate:%Y-%m-%d}（工作日估计，未核验交易所休市安排）"
    for date, following in zip(open_days[:-1], open_days[1:]):
        if date > end and date.to_period("M") != following.to_period("M"):
            return f"{date:%Y-%m-%d}（交易所日历确认）"
    return "未知（交易所日历尚不足以确认下一个月末）"


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join([
        "| " + " | ".join(map(cell, headers)) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(map(cell, row)) + " |" for row in rows],
    ])


def number(value, percent=False):
    if not np.isfinite(value):
        return "—"
    return f"{value:.2%}" if percent else f"{value:,.4f}"


def write_report(root, end, inception, release, fund_release, data, benchmarks,
                 accounts, errors, open_days, calendar_note):
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    names = pd.read_parquet(ROOT / "data/live/panel/stocks.parquet").set_index("code").name
    industry = pd.read_parquet(ROOT / "data/live/panel/industry.parquet")
    industry["in_date"] = pd.to_datetime(industry.in_date)
    industry["out_date"] = pd.to_datetime(industry.out_date)
    industry = industry.loc[(industry.in_date <= end) &
                            (industry.out_date.isna() | (industry.out_date > end))]
    industries = industry.sort_values("in_date").drop_duplicates("code", keep="last").set_index("code").l1_name
    days = len(data.calendar[data.calendar >= pd.Timestamp(inception)]) - 1
    lines = [f"# 虚拟盘日报 · {end:%Y-%m-%d}", "",
             "纯纸面前向模拟。开户日收盘产生初始信号，下一交易日开盘执行。", "",
             f"数据末日：{end:%Y-%m-%d}；行情 release_id：{release}；"
             f"财务 release_id：{fund_release}。", "",
             f"开户信号日：{inception}；已运行交易日数：{days}（不含开户信号日）。", ""]
    if calendar_note:
        lines.extend([calendar_note, ""])
    if errors:
        lines.extend(["> **账本不一致：以下账户未写入，本次重放结果不用于报告。**", ""])
        for name, error in errors.items():
            lines.extend([f"> **{name}**：{error}", ""])
    summaries, weights = {}, {}
    for name, (result, pending, info) in accounts.items():
        summary = account_summary(result.nav, result.trades, benchmarks)
        last = result.positions.iloc[-1]
        last = last[last > 0]
        current = last * data.close.ffill().loc[end].reindex(last.index) / result.nav.iloc[-1]
        weights[name] = current.sort_values(ascending=False)
        summary.update(current_exposure=1 - result.cash.iloc[-1] / result.nav.iloc[-1],
                       holdings=len(last), cash=result.cash.iloc[-1])
        summaries[name] = summary
    if days < 60:
        lines.extend(["**运行不足 60 个交易日：年化收益、夏普、年化波动、年化换手及 α/β 样本太短，只作记录。**", ""])
    specs = [("累计收益", "total_return", True), ("年化收益", "cagr", True),
             ("最大回撤", "max_drawdown", True), ("夏普", "sharpe", False),
             ("年化波动", "ann_vol", True), ("年化换手", "turnover", True),
             ("累计费用（元）", "cost", False), ("当前仓位比例", "current_exposure", True),
             ("持股数", "holdings", False), ("现金（元）", "cash", False)]
    rows = [[label, *[number(summaries[name][key], pct) if name in summaries else "账本不一致"
                      for name in NAMES]] for label, key, pct in specs]
    lines.extend(["## 账户概览", "", table(["指标", *NAMES], rows), ""])
    for bench in benchmarks:
        label = "价格指数，不含分红" if bench == "000906.SH" else "自建全收益，分红再投资"
        rows = []
        for name, summary in summaries.items():
            rows.append([name, number(summary[f"{bench}:return"], True),
                         number(summary["total_return"] - summary[f"{bench}:return"], True),
                         number(summary[f"{bench}:excess_cagr"], True),
                         number(summary[f"{bench}:alpha_ann"], True),
                         number(summary[f"{bench}:beta"])])
        lines.extend([f"## 基准 {bench}（{label}）", "",
                      table(["账户", "基准同区间收益", "累计超额", "年化超额", "α（年化）", "β"], rows), ""])
    png_name = f"{end:%Y-%m-%d}_nav.png"
    lines.extend([f"![开户信号日起归一化净值](<{reports / png_name}>)", ""])
    for name, (result, pending, info) in accounts.items():
        current = weights[name]
        lines.extend([f"## {name}", "",
                      f"下一次例行调仓信号日：{next_month_end(end, open_days)}；次一交易日开盘执行。", "",
                      "### 当前持仓", "",
                      table(["代码", "名称", "行业 l1_name", "权重"], [
                          [code, names.get(code, "未知"), industries.get(code, "未知"), number(weight, True)]
                          for code, weight in current.items()]) if len(current) else "无", "",
                      "### 下一交易日待执行目标", ""])
        if pending is None:
            lines.append("无")
        else:
            future = (open_days[open_days > end] if open_days is not None else pd.DatetimeIndex([]))
            lines.append(f"执行日：{future[0]:%Y-%m-%d}。" if len(future) else "执行日：下一交易所开市日（日期待确认）。")
            rows = []
            for code in current.index.union(pending.index):
                old, new = current.get(code, 0.0), pending.get(code, 0.0)
                if abs(new - old) <= 1e-12:
                    continue
                action = "买入" if old == 0 else "卖出" if new == 0 else "调整"
                rows.append([action, code, names.get(code, "未知"), number(old, True),
                             number(new, True), number(new - old, True)])
            lines.extend(["", table(["动作", "代码", "名称", "当前权重", "目标权重", "权重变化"], rows)
                          if rows else "目标已生成，权重无变化。"])
        lines.extend(["", "待执行目标仅指末日新生成的收盘信号；实际模拟成交受停牌、涨跌停及整手约束。", ""])
        added = result.trades.loc[result.trades.date.isin(info["new_dates"])]
        lines.extend(["### 本次新增成交", "",
                      f"新增 {len(info['new_dates'])} 天；成交 {len(added)} 笔；"
                      f"买入金额 {added.loc[added.side == 'buy', 'value'].sum():,.2f} 元；"
                      f"卖出金额 {added.loc[added.side == 'sell', 'value'].sum():,.2f} 元；"
                      f"费用 {added.fee.sum():,.2f} 元。", ""])
        if len(added):
            lines.extend([table(["日期", "代码", "方向", "股数", "价格", "金额", "费用"], [
                [f"{row.date:%Y-%m-%d}", row.code, row.side, repr(float(row.shares)),
                 number(row.price), number(row.value), number(row.fee)]
                for row in added.itertuples()]), ""])
    os.environ.setdefault("MPLCONFIGDIR", str(root / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 6))
    for name, (result, _, _) in accounts.items():
        ax.plot(result.nav.index, result.nav / result.nav.iloc[0], label=name)
    for bench in benchmarks:
        series = benchmarks[bench].loc[inception:end]
        ax.plot(series.index, series / series.iloc[0], label=bench, linestyle="--")
    ax.set_ylabel("NAV (inception = 1)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(reports / png_name, dpi=150)
    plt.close(fig)
    report = reports / f"{end:%Y-%m-%d}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    shutil.copyfile(report, root / "latest.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--ledger-root", type=Path, default=Path("paper"))
    parser.add_argument("--inception")
    args = parser.parse_args()
    root = args.ledger_root.resolve()
    if args.inception is not None and root == (ROOT / "paper").resolve():
        parser.error("--inception 仅允许与非默认 --ledger-root 一起使用")
    inception = pd.Timestamp(args.inception or INCEPTION).strftime("%Y-%m-%d")
    if not args.skip_build:
        rebuild()
    panel = ROOT / "data/live/panel"
    release = json.loads((panel / "build_meta.json").read_text())["release_id"]
    fund_release = json.loads((ROOT / "data/live/fundamentals/fin_meta.json").read_text())["release_id"]
    print(f"读取行情和 PIT 财务数据，开户日 {inception}，release_id={release}", flush=True)
    data = load_market_data(panel, start=pd.Timestamp(inception) - pd.DateOffset(years=2),
                            universe="000906.SH")
    if pd.Timestamp(inception) not in data.calendar:
        raise ValueError(f"开户信号日 {inception} 不在现有行情交易日内")
    end = data.calendar[-1]
    fund = Fundamentals.load(ROOT / "data/live/fundamentals")
    benchmarks = load_benchmarks(ROOT / "data/live/benchmarks").reindex(
        data.calendar[data.calendar >= pd.Timestamp(inception)])
    if benchmarks.isna().any().any():
        raise ValueError("基准缺少模拟区间交易日数据")
    open_days, calendar_note = exchange_days(release, end)
    accounts, errors, messages = {}, {}, []
    print("计算开户及月末 PIT 因子并重放三个冻结账户", flush=True)
    for name, strategy, meta in make_accounts(data, fund, inception, open_days):
        try:
            init_account(root / name, meta)
            result, pending = simulate(strategy, data, inception, end, INITIAL_CASH, CostModel())
            info = append_ledger(root / name, result)
            accounts[name] = result, pending, info
            messages.append(f"{name}: 净值 {result.nav.iloc[-1]:,.2f} 元，新增 {len(info['new_dates'])} 天")
        except LedgerMismatch as exc:
            errors[name] = str(exc)
            messages.append(f"{name}: 账本不一致（未写入）")
            print(f"账本不一致 {name}: {exc}", flush=True)
    write_report(root, end, inception, release, fund_release, data, benchmarks,
                 accounts, errors, open_days, calendar_note)
    print("；".join(messages), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
