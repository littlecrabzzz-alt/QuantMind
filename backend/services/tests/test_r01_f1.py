"""R01P0-F1E1 修复验证测试（AC-02/03/04/05，独立验收报告 §AC-02~05）。

- AC-02：缺行情估值冻结政策——沿用最近有效市价+staleness（天数/来源日），
  禁止静默改成本价；连续缺日超阈值标 valuation_reliable=False；公司行动
  日价格/份额口径统一；独立复算独立实现该政策
- AC-03：checkpoint 恢复绑定完整冻结 config（本金/费率/风险参数/合同版本/
  输入包），不匹配显式拒绝；缺绑定字段拒绝；同参数续跑==不间断运行
- AC-04：终态订单执行/入账层幂等——同键重试不改现金/持仓/fills/费用；
  同键异内容冲突；卖光后重试不改写原成交
- AC-05：约定执行时点价格缺失（0/None/NaN/inf）→ MISSING_EXECUTION_PRICE
  拒单，不隐式替代（open 缺失不回退收盘）
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import (
    build_fixture_package,
)
from backend.services.simulation.replay.r01_ledger import (
    CheckpointConfigMismatch,
    LedgerOrderingError,
    R01Ledger,
    R01LedgerConfig,
    SameKeyOrderConflict,
    independent_recompute,
)
from backend.services.simulation.services.ashare_matcher import (
    MatchConfig,
    match_order,
)
from backend.services.simulation.services.local_market_data import DailyBar

REAL_PKG = "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v1-fcbabbb7"
REAL_SHA = "cd8b807e8caf152c8d7e5c024ba518722bb3acad68de73b483b922adf7135245"
real_pkg_needed = pytest.mark.skipif(
    not __import__("pathlib").Path(REAL_PKG, "manifest.json").is_file(),
    reason="真实输入包不在本机",
)


def _config(**kw):
    kw.setdefault("group", "A")
    kw.setdefault("strategy_id", "fixture-f1-demo")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 30000.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


# ---------------------------------------------------------------------------
# AC-02：缺行情估值政策
# ---------------------------------------------------------------------------


class TestMissingQuoteValuation:
    @real_pkg_needed
    def test_real_missing_day_keeps_last_known_mark(self):
        """真实缺行日（159915 2021-02-08）：无交易/事件 → nav 不变，
        mark 沿用上一可得收盘（3.084），不得改用成本价。"""
        from backend.services.simulation.replay.etf_input_package import (
            load_etf_input_package,
        )

        pkg = load_etf_input_package(REAL_PKG, expect_manifest_sha256=REAL_SHA)
        led = R01Ledger(pkg, _config(strategy_id="fixture-f1-missing"))
        led.run_day(date(2021, 2, 5), {"159915.SZ": 0.9}, signal_date=date(2021, 2, 4))
        prior = led.equity[-1]
        led.run_day(date(2021, 2, 8))
        cur = led.equity[-1]
        assert cur["nav"] == pytest.approx(prior["nav"], abs=1e-7)
        pos_out = cur["positions"]["159915.SZ"]
        assert pos_out["close"] == pytest.approx(3.084, abs=1e-6)  # 沿用市价
        assert pos_out["close"] != pytest.approx(led.positions["159915.SZ"].avg_cost, abs=1e-4)
        assert pos_out["mark_source"] == "carry_forward"
        assert pos_out["stale_days"] == 1
        assert pos_out["last_mark_date"] == "2021-02-05"
        assert cur["valuation_reliable"] is True  # 单日缺行未超阈值

    def test_consecutive_missing_days_accumulate_then_unreliable(self, tmp_path):
        """连续缺日：staleness 递增；超过阈值（默认 5）→ 快照不可信。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 9))
        from backend.services.simulation.replay.r01_ledger import DaySummary

        d = date(2025, 9, 11)
        for i in range(1, 8):
            led._eod(d, {}, DaySummary(trade_date=d.isoformat()))  # bars 空=缺行情
            snap = led.equity[-1]
            pos = snap["positions"]["510300.SH"]
            assert pos["stale_days"] == i
            assert pos["mark_source"] == "carry_forward"
            assert snap["valuation_reliable"] == (i <= 5)
            d = date.fromordinal(d.toordinal() + 1)

    def test_carry_mark_preserves_unrealized_pnl(self, tmp_path):
        """已有浮盈场景：缺行情日 mark=最近收盘（非成本），浮盈不被抹零。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 9))
        pos = led.positions["510300.SH"]
        prior_snap = led.equity[-1]
        prior_close = prior_snap["positions"]["510300.SH"]["close"]
        unrealized_before = (prior_close - pos.avg_cost) * pos.qty
        assert unrealized_before > 0  # 前提：fixture 上行漂移 → 有浮盈

        from backend.services.simulation.replay.r01_ledger import DaySummary

        led._eod(date(2025, 9, 11), {}, DaySummary(trade_date="2025-09-11"))
        after = led.equity[-1]
        mark = after["positions"]["510300.SH"]["close"]
        assert mark == pytest.approx(prior_close)  # 沿用市价而非成本
        unrealized_after = (mark - pos.avg_cost) * pos.qty
        assert unrealized_after == pytest.approx(unrealized_before)

    def test_share_adjustment_rescales_carry_mark(self, tmp_path):
        """缺行情且当日份额折算：carry 市价同步换算（qty×m ↔ mark/m），
        nav 不因口径错配漂移。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 15), {"159934.SZ": 0.9}, signal_date=date(2025, 9, 12))
        pos = led.positions["159934.SZ"]
        # 构造：09-18（无行情 bars）+ 09-22 份额折算事件照常应用
        from backend.services.simulation.replay.r01_ledger import DaySummary

        led._eod(date(2025, 9, 17), {}, DaySummary(trade_date="2025-09-17"))
        mark_before = pos.last_mark
        qty_before = pos.qty
        ev = [
            e for e in pkg.events_for("159934.SZ")
            if e.event_type == "share_adjustment"
        ][0]
        led._apply_share_adjustment(ev)
        assert pos.qty == pytest.approx(qty_before * ev.qty_multiplier)
        assert pos.last_mark == pytest.approx(mark_before / ev.qty_multiplier)
        # qty×mark 守恒（份额口径统一）
        assert pos.qty * pos.last_mark == pytest.approx(qty_before * mark_before, rel=1e-9)

    @real_pkg_needed
    def test_independent_recompute_implements_policy_independently(self):
        """独立复算自实现 carry-forward（真实缺行日 159915 2021-02-08）：
        与引擎逐日 nav/cash 对齐，且只观察包行情、不读引擎 last_mark。"""
        from backend.services.simulation.replay.etf_input_package import (
            load_etf_input_package,
        )

        pkg = load_etf_input_package(REAL_PKG, expect_manifest_sha256=REAL_SHA)
        led = R01Ledger(pkg, _config(strategy_id="fixture-f1-recompute"))
        led.run_day(date(2021, 2, 5), {"159915.SZ": 0.9}, signal_date=date(2021, 2, 4))
        led.run_day(date(2021, 2, 8))  # 真实缺行日
        led.run_day(date(2021, 2, 9))
        evidence = led.export_evidence()
        rows = independent_recompute(evidence, package=pkg)
        assert len(rows) == len(led.equity)
        for row, snap in zip(rows, led.equity, strict=True):
            assert row["nav"] == pytest.approx(snap["nav"], abs=0.01), snap["trade_date"]
            assert row["cash"] == pytest.approx(snap["cash"], abs=0.01)


# ---------------------------------------------------------------------------
# AC-03：checkpoint 冻结参数绑定
# ---------------------------------------------------------------------------


class TestCheckpointConfigBinding:
    def _ckpt(self, pkg):
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 9))
        return led, led.export_checkpoint()

    def test_changed_initial_cash_rejected(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p1")
        _, cp = self._ckpt(pkg)
        changed = _config(initial_cash=90000.0)  # 同 run_id，改本金
        with pytest.raises(CheckpointConfigMismatch) as ei:
            R01Ledger.restore(pkg, changed, cp)
        msg = str(ei.value)
        assert "initial_cash" in msg and "90000.0" in msg  # 双方关键字段

    def test_changed_commission_rejected(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p2")
        _, cp = self._ckpt(pkg)
        changed = _config(commission_rate=0.03)
        with pytest.raises(CheckpointConfigMismatch) as ei:
            R01Ledger.restore(pkg, changed, cp)
        assert "commission_rate" in str(ei.value)

    def test_changed_risk_params_rejected(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p3")
        _, cp = self._ckpt(pkg)
        with pytest.raises(CheckpointConfigMismatch):
            R01Ledger.restore(pkg, _config(drawdown_pct=0.5), cp)

    def test_missing_binding_fields_rejected(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p4")
        _, cp = self._ckpt(pkg)
        no_config = dict(cp)
        no_config.pop("config")
        with pytest.raises(CheckpointConfigMismatch, match="缺少冻结 config"):
            R01Ledger.restore(pkg, _config(), no_config)
        no_ct = dict(cp)
        no_ct.pop("contract_versions")
        with pytest.raises(CheckpointConfigMismatch, match="contract_versions"):
            R01Ledger.restore(pkg, _config(), no_ct)

    def test_same_config_resume_matches_uninterrupted(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p5")
        cfg = _config()
        full = R01Ledger(pkg, cfg)
        for d in pkg.trade_dates():
            if d > date(2025, 9, 17):
                break
            w = {"510300.SH": 0.5} if d == date(2025, 9, 10) else None
            full.run_day(d, w)
        part = R01Ledger(pkg, cfg)
        for d in pkg.trade_dates():
            if d > date(2025, 9, 12):
                break
            w = {"510300.SH": 0.5} if d == date(2025, 9, 10) else None
            part.run_day(d, w)
        resumed = R01Ledger.restore(pkg, cfg, part.export_checkpoint())
        for d in pkg.trade_dates():
            if d <= date(2025, 9, 12) or d > date(2025, 9, 17):
                continue
            resumed.run_day(d, None)
        assert [s["nav"] for s in resumed.equity] == pytest.approx(
            [s["nav"] for s in full.equity]
        )

    def test_pg_load_entry_enforced_via_restore(self, tmp_path):
        """持久层入口：state 里的 config 被篡改后 load 路径同样拒绝
        （load_checkpoint 委托 restore，config 比对在其中强制执行）。"""
        pkg = build_fixture_package(tmp_path / "p6")
        _, cp = self._ckpt(pkg)
        cp["config"]["initial_cash"] = 90000.0  # 篡改快照
        with pytest.raises(CheckpointConfigMismatch):
            R01Ledger.restore(pkg, _config(), cp)


# ---------------------------------------------------------------------------
# AC-04：终态订单幂等
# ---------------------------------------------------------------------------


class TestTerminalOrderIdempotency:
    def test_manual_sell_retry_single_fill(self, tmp_path):
        """同键重试：订单同 ID、fills 不变、现金/持仓不变。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 10), {"518880.SH": 0.9}, signal_date=date(2025, 9, 9))
        led.run_day(date(2025, 9, 11), None)
        first = led.manual_sell(date(2025, 9, 11), "518880.SH", 100,
                                reason="r", requested_by="u")
        cash, qty, fills = led.cash, led.positions["518880.SH"].qty, len(first.fills)
        second = led.manual_sell(date(2025, 9, 11), "518880.SH", 100,
                                 reason="r", requested_by="u")
        assert first is second
        assert len(second.fills) == fills
        assert led.cash == pytest.approx(cash)
        assert led.positions["518880.SH"].qty == pytest.approx(qty)

    def test_retry_after_full_exit_preserves_filled_order(self, tmp_path):
        """卖光后的重试：原成交单不得被改写为拒单。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 10), {"518880.SH": 0.9}, signal_date=date(2025, 9, 9))
        led.run_day(date(2025, 9, 11), None)
        pos_qty = led.positions["518880.SH"].available_qty
        first = led.manual_sell(date(2025, 9, 11), "518880.SH", int(pos_qty),
                                reason="exit", requested_by="u")
        assert first.status == "filled"
        cash_after_exit = led.cash
        again = led.manual_sell(date(2025, 9, 11), "518880.SH", int(pos_qty),
                                reason="exit", requested_by="u")
        assert again is first
        assert first.status == "filled"  # 不改写为拒单
        assert len(first.fills) == 1
        assert led.cash == pytest.approx(cash_after_exit)

    def test_same_key_different_qty_conflict(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 10), {"518880.SH": 0.9}, signal_date=date(2025, 9, 9))
        led.run_day(date(2025, 9, 11), None)
        led.manual_sell(date(2025, 9, 11), "518880.SH", 100, reason="r", requested_by="u")
        with pytest.raises(SameKeyOrderConflict):
            led.manual_sell(date(2025, 9, 11), "518880.SH", 200, reason="r", requested_by="u")
        with pytest.raises(SameKeyOrderConflict):
            led.submit_order(date(2025, 9, 11), "518880.SH", "sell", 300)

    def test_retry_idempotent_after_checkpoint_restore(self, tmp_path):
        """checkpoint 恢复后的同键重放：终态幂等持续成立。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        cfg = _config()
        led = R01Ledger(pkg, cfg)
        led.run_day(date(2025, 9, 10), {"518880.SH": 0.9}, signal_date=date(2025, 9, 9))
        led.run_day(date(2025, 9, 11), None)
        led.manual_sell(date(2025, 9, 11), "518880.SH", 100, reason="r", requested_by="u")
        cash, qty = led.cash, led.positions["518880.SH"].qty
        restored = R01Ledger.restore(pkg, cfg, led.export_checkpoint())
        again = restored.manual_sell(date(2025, 9, 11), "518880.SH", 100,
                                     reason="r", requested_by="u")
        assert again.status == "filled"
        assert len(again.fills) == 1
        assert restored.cash == pytest.approx(cash)
        assert restored.positions["518880.SH"].qty == pytest.approx(qty)

    def test_rejected_order_retry_stays_rejected(self, tmp_path):
        """拒单终态重试仍是拒单（不重新执行）。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        led.run_day(date(2025, 9, 16), {"510300.SH": 0.5}, signal_date=date(2025, 9, 15))
        rejected = [
            o for o in led.orders.values()
            if o.trade_date == "2025-09-16" and o.status == "rejected"
        ]
        assert rejected  # fixture 停牌日
        # 再次执行同订单 → 状态不变
        from backend.services.simulation.replay.r01_ledger import DaySummary

        led._validate_and_execute(
            rejected[0], date(2025, 9, 16), pkg.load_date(date(2025, 9, 16)),
            DaySummary(trade_date="2025-09-16"),
        )
        assert rejected[0].status == "rejected"


# ---------------------------------------------------------------------------
# AC-05：执行时点价格缺失拒绝
# ---------------------------------------------------------------------------


def _bar(symbol="510300.SH", open_=4.0, close=4.0, volume=1e7):
    return DailyBar(
        symbol=symbol, trade_date=date(2025, 9, 10),
        open=open_, high=max(open_ or close, close) * 1.01,
        low=min(open_ or close, close) * 0.99, close=close,
        volume=volume, amount=close * volume, vwap=close,
        pre_close=close, limit_up=close * 1.1, limit_down=close * 0.9,
        is_st=False, suspended=False,
    )


class TestMissingExecutionPrice:
    def _cfg(self, **kw):
        kw.setdefault("price_mode", "open")
        kw.setdefault("asset_type", "etf")
        kw.setdefault("allow_partial", True)
        kw.setdefault("slippage_bps", 0.0)
        return MatchConfig(**kw)

    @pytest.mark.parametrize("bad_open", [0.0, None, float("nan"), float("inf"), -1.0])
    def test_open_missing_rejects_not_fills_at_close(self, bad_open):
        bar = replace(_bar(open_=4.0, close=5.5297), open=bad_open)
        res = match_order("buy", 100, bar, self._cfg(), cash_available=30000.0)
        assert not res.success
        assert res.reason == "MISSING_EXECUTION_PRICE"
        assert res.fill_price == 0.0 and res.fill_quantity == 0
        assert res.total_fee == 0.0  # 无成交无费用

    def test_valid_open_still_fills_at_open(self):
        bar = _bar(open_=4.012, close=4.05)  # 涨跌停带内（±10% of close）
        res = match_order("buy", 100, bar, self._cfg(), cash_available=30000.0)
        assert res.success
        assert res.fill_price == pytest.approx(4.012)  # 成交在开盘，不是收盘

    def test_close_mode_invalid_close_rejects(self):
        bar = replace(_bar(), close=0.0)
        res = match_order("buy", 100, bar, self._cfg(price_mode="close"), cash_available=30000.0)
        assert not res.success
        assert res.reason == "MISSING_EXECUTION_PRICE"

    def test_vwap_missing_rejects(self):
        bar = replace(_bar(), vwap=0.0)
        res = match_order("buy", 100, bar, self._cfg(price_mode="vwap"), cash_available=30000.0)
        assert not res.success
        assert res.reason == "MISSING_EXECUTION_PRICE"

    def test_ledger_reject_reason_mapped(self, tmp_path):
        """账本路径：开盘缺失 → 拒单且归一化到合同枚举 stale_price。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        from backend.services.simulation.replay.r01_ledger import DaySummary

        bar = replace(pkg.get_bar("510300.SH", date(2025, 9, 10)), open=0.0)
        order = led.submit_order(date(2025, 9, 10), "510300.SH", "buy", 1000)
        led._validate_and_execute(
            order, date(2025, 9, 10), {"510300.SH": bar},
            DaySummary(trade_date="2025-09-10"),
        )
        assert order.status == "rejected"
        assert order.reject_reason == "stale_price"
        assert math.isclose(led.cash, 30000.0)
