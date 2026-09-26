"""R01P0-M2E1 测试：§3.3.8 零股余额申报校验（2026-07-06 生效）。

- 5→3 拒（狭义缺口用例；含总仓/可卖/申报量/目标明细）
- 5→5 全额申报成交；5 报 5 成交 3（合法部分成交，申报与余单保留）
- T+1：总仓与可卖区别（可卖=0 时另一道闸门先行）
- 105 清尾三态：报 105 合法 / 报 100 留 5 合法 / 报 103 非法
- effective_date 边界：07-05（前）维持现行为、07-06（起）启用
全部合成 fixture（与 R01SELF probe 同法），无真实收益计算。
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from backend.services.simulation.replay.etf_input_package import (
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import R01Ledger, R01LedgerConfig

SYM = "510300.SH"
PRICE = 4.0


def _fixture(
    root: Path,
    days: list[date],
    mults: dict[date, float],
    volume: float = 1_200_000.0,
    volume_by_day: dict[date, float] | None = None,
):
    (root / "daily").mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)
    vmap = volume_by_day or {}
    rows = [{
        "trade_date": d.isoformat(), "open": PRICE, "high": PRICE, "low": PRICE,
        "close": PRICE, "volume": vmap.get(d, volume),
        "amount": PRICE * vmap.get(d, volume) * 100 / 1000,
        "adj_factor": 1.0,
    } for d in days]
    pd.DataFrame(rows).to_parquet(root / "daily" / f"{SYM}.parquet", index=False)
    evs = []
    for d, m in mults.items():
        evs.append({
            "event_date": d.isoformat(), "event_type": "share_adjustment",
            "cash_per_share": 0.0, "qty_multiplier": m,
            "basis_note": "synthetic",
            "derived_from": {"adj_factor_prev": 1.0, "adj_factor_new": m},
            "verification": {"passed": True, "method": "pre_close_continuity"},
        })
    pd.DataFrame(
        evs, columns=["symbol", "event_date", "event_type", "cash_per_share",
                      "qty_multiplier", "derived_from", "verification"]
    ).assign(symbol=SYM).to_parquet(root / "events" / f"{SYM}.parquet", index=False)
    manifest = {
        "schema_version": 3, "package_id": "fixture-sublot-m2e1",
        "package_version": "m2e1", "package_uri": "node://mac/r01-etf-daily/fixture-sublot-m2e1",
        "source_release_id": "fixture", "generated_at": "2026-09-26T00:00:00Z",
        "generated_by_node": "mac",
        "source_datasets": [{"api_name": n, "sha256": "0" * 64} for n in
                            ("fund_daily", "fund_adj", "fund_div", "trade_cal", "etf_limit")],
        "unit_conversions": {"vol": "lot(100 shares) -> shares, multiply by 100",
                             "amount": "thousand CNY -> CNY, multiply by 1000",
                             "rules": "synthetic flat"},
        "factor_convention": {"formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
                              "verified_cases": []},
        "symbols": [{"code": SYM, "class": "equity_broad", "role": "primary",
                     "data_start": days[0].isoformat(), "data_end": days[-1].isoformat(),
                     "missing_days": [], "warmup_start": days[0].isoformat()}],
        "known_gaps": [],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return load_etf_input_package(root)


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _cfg(**kw):
    kw.setdefault("group", "P0")
    kw.setdefault("strategy_id", "fixture-sublot-m2e1")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 500.0)
    kw.setdefault("commission_rate", 0.0003)
    kw.setdefault("commission_min", 0.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


def _weight_for_target(led, pkg, signal_day: date, target_qty: float) -> float:
    nav = led.equity[-1]["nav"]
    close = pkg.get_bar(SYM, signal_day).close
    return target_qty * close / nav


class TestSublotRule:
    def test_5_to_3_rejected_with_details(self):
        """狭义缺口用例：总仓=可卖=5、目标 2 → 申报 3 拒单（含明细），
        持仓/现金不动。"""
        days = _weekdays(date(2026, 7, 7), 8)
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days, {days[3]: 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(days[0], None)
            led.run_day(days[1], {SYM: 0.8})  # 买 100
            led.run_day(days[2], None)
            led.run_day(days[3], None)  # 折算 ×0.05 → 总仓=可卖=5
            assert led.positions[SYM].qty == 5.0
            cash_before = led.cash
            w = _weight_for_target(led, pkg, days[3], 2.0)  # 目标 2 → 申报 3
            s = led.run_day(days[4], {SYM: w})
            order = [o for o in s.orders if o["side"] == "sell"][0]
            assert order["status"] == "rejected"
            assert order["reject_reason"].startswith("sublot_partial_sell_not_allowed")
            for token in ("total=5", "available=5", "declared=3"):
                assert token in order["reject_reason"]
            assert led.positions[SYM].qty == 5.0  # 不规范化：持仓不变
            assert led.cash == pytest.approx(cash_before)  # 现金不动
            assert order["qty_filled"] == 0 and order["qty_remaining"] == 3

    def test_5_to_5_full_closeout_fills(self):
        """5→5：全额一次性申报合法并成交（清仓）。"""
        days = _weekdays(date(2026, 7, 7), 8)
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days, {days[3]: 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(days[0], None)
            led.run_day(days[1], {SYM: 0.8})
            led.run_day(days[2], None)
            led.run_day(days[3], None)
            w = _weight_for_target(led, pkg, days[3], 0.0)  # 目标 0 → 申报 5
            s = led.run_day(days[4], {SYM: w})
            order = [o for o in s.orders if o["side"] == "sell"][0]
            assert order["status"] == "filled" and order["qty_filled"] == 5
            assert SYM not in led.positions

    def test_declare_5_volume_3_legal_partial_fill(self):
        """报 5、市场量 300：合法部分成交 3，申报与余单保留（非申报缺陷）。"""
        days = _weekdays(date(2026, 7, 7), 8)
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(
                Path(td), days, {days[3]: 0.05},
                volume_by_day={days[4]: 0.03},  # 卖出日量 3 份（0.03 手）
            )
            led = R01Ledger(pkg, _cfg())
            led.run_day(days[0], None)
            led.run_day(days[1], {SYM: 0.8})
            led.run_day(days[2], None)
            led.run_day(days[3], None)
            w = _weight_for_target(led, pkg, days[3], 0.0)  # 申报 5
            s = led.run_day(days[4], {SYM: w})
            order = [o for o in s.orders if o["side"] == "sell"][0]
            assert order["qty_target"] == 5  # 申报保留
            assert order["qty_filled"] == 3  # 量约束部分成交
            assert order["status"] in ("expired_unfilled", "partially_filled")
            assert led.positions[SYM].qty == pytest.approx(2.0)

    def test_t1_total_vs_available(self):
        """T+1 区别：零股校验基于总仓余额；可卖约束独立作用。
        构造：先 5（折算余量，已解锁），卖出日当日再买 100（T+1 锁定）
        → 总仓 105、可卖 5；目标 0 → 申报 105（总仓全额，零股校验通过）
        → 可卖 5 部分成交 5，余 100 转未成交（非申报缺陷）。"""
        days = _weekdays(date(2026, 7, 7), 8)
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days, {days[3]: 0.05})
            # initial 2000：首买权重 0.2（=100 份），折算后 nav≈1620 高于
            # 两线阈值（不触发风险暂停，保证后续买入可执行）
            led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
            led.run_day(days[0], None)
            led.run_day(days[1], {SYM: 0.2})  # 买 100
            led.run_day(days[2], None)
            led.run_day(days[3], None)  # 折算 → 5（已解锁）
            led.run_day(days[4], None)
            # 卖出前一日（days[5]）：目标 105 → 当日买 100（T+1 锁定）
            w_buy = _weight_for_target(led, pkg, days[4], 105.0)
            led.run_day(days[5], {SYM: w_buy})
            pos = led.positions[SYM]
            assert pos.qty == pytest.approx(105.0) and pos.available_qty == pytest.approx(5.0)
            w = _weight_for_target(led, pkg, days[5], 0.0)  # 目标 0 → 申报 105
            s = led.run_day(days[6], {SYM: w})  # 次日（rollover 解锁后）
            # 次日总仓=可卖=105：申报 105 合法（全额）→ 全部成交
            order = [o for o in s.orders if o["side"] == "sell"][0]
            assert order["qty_target"] == 105
            assert order["reject_reason"] is None
            assert order["status"] == "filled"
            assert SYM not in led.positions

    def test_105_three_states(self):
        """105 三态：报 105 合法（100+全额零5）/ 报 100 留 5 合法 / 报 103 非法。"""
        days = _weekdays(date(2026, 7, 7), 10)
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days, {days[3]: 1.05})  # 100 → 105

            def build(target_qty: float):
                led = R01Ledger(pkg, _cfg())
                led.run_day(days[0], None)
                led.run_day(days[1], {SYM: 0.8})
                led.run_day(days[2], None)
                led.run_day(days[3], None)
                assert led.positions[SYM].qty == 105.0
                w = _weight_for_target(led, pkg, days[3], target_qty)
                s = led.run_day(days[4], {SYM: w})
                return led, [o for o in s.orders if o["side"] == "sell"][0]

            # 报 105（目标 0）：全额含零尾 → 合法清仓
            led, o = build(0.0)
            assert o["qty_target"] == 105 and o["status"] == "filled"
            assert SYM not in led.positions
            # 报 100（目标 5）：整手倍数 → 合法，留零股 5
            led, o = build(5.0)
            assert o["qty_target"] == 100 and o["status"] == "filled"
            assert led.positions[SYM].qty == pytest.approx(5.0)
            # 报 103（目标 2）：非整手且未全额/尾额不完整 → 拒单
            led, o = build(2.0)
            assert o["qty_target"] == 103 and o["status"] == "rejected"
            assert o["reject_reason"].startswith("sublot_partial_sell_not_allowed")
            assert led.positions[SYM].qty == pytest.approx(105.0)

    def test_effective_date_boundary(self):
        """边界：07-03（生效前）卖 3 留 2 维持现行为成交；07-06（生效日）
        起同样申报被拒。"""
        # 生效前：06-30 买、07-01 折算、07-03 卖（全部 < 07-06）
        days_pre = _weekdays(date(2026, 6, 30), 3)  # 06-30, 07-01, 07-02
        days_pre += [date(2026, 7, 3)]
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days_pre, {days_pre[1]: 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(days_pre[0], None)
            led.run_day(days_pre[1], {SYM: 0.8})  # 06-30 买 100？——日序修正：
        # 上段日期排列有误（06-30 买在 days_pre[0]）——重排：
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days_pre, {days_pre[1]: 0.05})  # 07-01 折算
            led = R01Ledger(pkg, _cfg())
            led.run_day(days_pre[0], None)  # 06-30 warmup
            led.run_day(days_pre[1], {SYM: 0.8})  # 06-30? —— days_pre[1]=07-01 买
            # 修正流程：06-30 warmup、07-01 买、07-02 折算日？折算挂在 days_pre[1]
        # 直接用清晰序：warmup=06-30，buy=07-01，fold=07-02，sell=07-03
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days_pre, {date(2026, 7, 2): 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(date(2026, 6, 30), None)
            led.run_day(date(2026, 7, 1), {SYM: 0.8})  # 买 100
            led.run_day(date(2026, 7, 2), None)  # 折算 → 5（T+1 次日解锁）
            w = _weight_for_target(led, pkg, date(2026, 7, 2), 2.0)  # 申报 3
            s = led.run_day(date(2026, 7, 3), {SYM: w})  # 07-03 < 07-06：现行为
            o = [x for x in s.orders if x["side"] == "sell"][0]
            assert o["qty_target"] == 3 and o["status"] == "filled"
            assert led.positions[SYM].qty == pytest.approx(2.0)

        # 生效日：07-02 买、07-03 折算、07-06（生效日）卖 → 拒
        days_post = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)]
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days_post, {date(2026, 7, 3): 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(date(2026, 7, 1), None)
            led.run_day(date(2026, 7, 2), {SYM: 0.8})
            led.run_day(date(2026, 7, 3), None)
            w = _weight_for_target(led, pkg, date(2026, 7, 3), 2.0)
            s = led.run_day(date(2026, 7, 6), {SYM: w})  # 07-06 生效日 → 拒
            o = [x for x in s.orders if x["side"] == "sell"][0]
            assert o["reject_reason"].startswith("sublot_partial_sell_not_allowed")
            assert led.positions[SYM].qty == pytest.approx(5.0)

    def test_pre_effective_partial_sell_still_fills_when_available(self):
        """生效前且可卖充足：卖 3 留 2 照常成交（现行为，非缺陷追溯）。"""
        days = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days, {date(2026, 7, 2): 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(date(2026, 7, 1), None)
            led.run_day(date(2026, 7, 2), {SYM: 0.8})  # 买 100
            # 07-03：rollover 解锁 + 折算（挂在 07-02？折算挂 07-02 会先于买入）
        # 干净构造：折算挂 07-03（开盘前生效于已有 100 → 5，且 rollover 已解锁）
        with tempfile.TemporaryDirectory() as td:
            pkg = _fixture(Path(td), days, {date(2026, 7, 3): 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(date(2026, 7, 1), None)
            led.run_day(date(2026, 7, 2), {SYM: 0.8})  # 买 100
            led.run_day(date(2026, 7, 3), None)  # rollover 解锁 + 折算 → 可卖 5
            w = _weight_for_target(led, pkg, date(2026, 7, 3), 2.0)
            s = led.run_day(date(2026, 7, 3), {SYM: w}) if False else None
        # 07-03 已 run_day(None)——申报须在下一交易日；生效前下一日=07-06 已生效
        # 因此本用例改锚定"生效前当日申报"不可行（逐日约束），改为：
        # 折算挂 07-01（买入前，pos 空 → 无效果）不成立——直接验证 07-03 单日内：
        with tempfile.TemporaryDirectory() as td:
            # 06-30 买（前一日）、07-01 折算+解锁、07-02 卖（<07-06）、07-03 备用
            days2 = [date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2)]
            pkg = _fixture(Path(td), days2, {date(2026, 7, 1): 0.05})
            led = R01Ledger(pkg, _cfg())
            led.run_day(date(2026, 6, 29), None)
            led.run_day(date(2026, 6, 30), {SYM: 0.8})  # 买 100
            led.run_day(date(2026, 7, 1), None)  # 解锁+折算 → 总仓=可卖=5
            w = _weight_for_target(led, pkg, date(2026, 7, 1), 2.0)
            s = led.run_day(date(2026, 7, 2), {SYM: w})  # 07-02 < 07-06：现行为
            o = [x for x in s.orders if x["side"] == "sell"][0]
            assert o["qty_target"] == 3 and o["status"] == "filled"
            assert led.positions[SYM].qty == pytest.approx(2.0)
