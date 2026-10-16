"""只读已有 live 行情，重放并追加 S1 ETF 模拟账本。"""

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import pandas as pd

from ashare_lab.data.build import SOURCE
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import CostModel
from ashare_lab.expansion.etf_market import load_etf_frames, with_etfs
from ashare_lab.paper import LedgerMismatch, append_ledger, init_account, simulate
from experiments.paper.accounts_s1 import ETF_NAMES, INITIAL_CASH, SLEEVES, make_accounts
from experiments.paper.update import exchange_days, table


def write_report(root, data, inception, release, strategy, result, pending, names, calendar_note):
    end = result.nav.index[-1]
    nav = result.nav.iloc[-1]
    holdings = result.positions.iloc[-1]
    holdings = holdings[holdings > 0]
    values = holdings * data.close.ffill().loc[end].reindex(holdings.index)
    current = values / nav
    current_sleeves = {name: current.get(code, 0.0) for name, code in SLEEVES.items()}
    current_sleeves["stock"] = current.drop(list(SLEEVES.values()), errors="ignore").sum()
    targets = strategy.base.last_sleeve_weights
    labels = {"stock": "股票（纯低波 W250 N50）", "bond": "债券", "gold": "黄金"}
    lines = [f"# S1 ETF 虚拟盘 · {end:%Y-%m-%d}", "",
             f"开户信号日：{inception}；行情末日：{end:%Y-%m-%d}。", "",
             f"账户金额：{nav:,.2f} 元；单位净值：{nav / INITIAL_CASH:.8f}；现金：{result.cash.iloc[-1]:,.2f} 元。", "",
             f"股票及 ETF 数据 release_id：{release}。", "",
             "信号日收盘决策，下一交易日开盘模拟成交；ETF 受 ±10% 涨跌停、停牌、100份整手约束，卖出按引擎印花税计（保守高估）。", ""]
    if calendar_note:
        lines.extend([calendar_note, ""])
    lines.extend(["## 三分仓权重", "", table(["分仓", "当前持仓权重", "最近信号目标权重"], [
        [labels[name], f"{current_sleeves[name]:.4%}", f"{targets[name]:.4%}"]
        for name in ("stock", "bond", "gold")]), "",
        "## 当前持仓明细", "", table(["代码", "名称", "份/股数", "市值（元）", "权重"], [
            [code, names.get(code, "未知"), repr(float(holdings[code])), f"{values[code]:,.2f}", f"{weight:.4%}"]
            for code, weight in current.sort_values(ascending=False).items()]) if len(current) else "无持仓。", "",
        "## 下一交易日待执行目标", ""])
    if pending is None:
        lines.append("末日未产生新信号；没有新的待执行目标。")
    else:
        rows = [[code, names.get(code, "未知"), f"{weight:.4%}", f"{weight * nav:,.2f}"]
                for code, weight in pending.sort_values(ascending=False).items()]
        lines.extend([table(["代码", "名称", "目标权重", "目标金额（元）"], rows), "",
                      "目标金额按信号收盘账户金额估算，成交以次日开盘、成本及整手约束为准。"])
    (root / "s1_latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--inception", required=True)
    args = parser.parse_args()
    root = args.ledger_root.resolve()
    protected = [(ROOT / "paper").resolve(), (ROOT / "data/live").resolve(), SOURCE.parent.resolve()]
    for destination in (root, (root / "s1_invvol_etf").resolve(), (root / "s1_latest.md").resolve()):
        if any(destination == path or path in destination.parents for path in protected):
            parser.error("--ledger-root 不得写入 paper/、data/live/ 或 QuantMind 归档")
    inception = pd.Timestamp(args.inception).strftime("%Y-%m-%d")
    panel = ROOT / "data/live/panel"
    release = json.loads((panel / "build_meta.json").read_text())["release_id"]
    print(f"只读行情，开户日 {inception}，release_id={release}", flush=True)
    data = load_market_data(panel, start=pd.Timestamp(inception) - pd.DateOffset(years=2),
                            universe="000906.SH")
    if pd.Timestamp(inception) not in data.calendar:
        raise ValueError(f"开户信号日 {inception} 不在现有行情交易日内")
    data = with_etfs(data, load_etf_frames(SLEEVES.values(), data.calendar, release))
    end = data.calendar[-1]
    open_days, calendar_note = exchange_days(release, end)
    names = pd.read_parquet(panel / "stocks.parquet").set_index("code")["name"].to_dict()
    names.update(ETF_NAMES)
    for name, strategy, meta in make_accounts(data, inception, open_days):
        try:
            result, pending = simulate(strategy, data, inception, end, INITIAL_CASH, CostModel())
            init_account(root / name, meta)
            info = append_ledger(root / name, result)
        except LedgerMismatch as exc:
            print(f"账本不一致 {name}（未追加）：{exc}", flush=True)
            return 1
        write_report(root, data, inception, release, strategy, result, pending, names, calendar_note)
        opening = (result.target.iloc[0] if len(result.target) else pending)
        if opening is not None:
            print("开户目标持仓（信号金额估算，次日开盘模拟成交）：", flush=True)
            print(table(["代码", "名称", "权重", "目标金额（元）"], [
                [code, names.get(code, "未知"), f"{weight:.6%}", f"{weight * INITIAL_CASH:,.2f}"]
                for code, weight in opening[opening > 0].sort_values(ascending=False).items()]), flush=True)
        print(f"{name}: 日期 {end:%Y-%m-%d}，金额 {result.nav.iloc[-1]:,.2f} 元，"
              f"单位净值 {result.nav.iloc[-1] / INITIAL_CASH:.8f}，新增 {len(info['new_dates'])} 天", flush=True)
        print(f"报告：{root / 's1_latest.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
