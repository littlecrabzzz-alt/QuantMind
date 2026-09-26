"""R01P0-M6E1 测试：read_through 输入上界 + matcher fill<100 修复。

- 项1：上界视图（daily/factors 裁定、现金分红保权、share 只到授权生效日、
  越界 no_quote、actual_max_input_date、同包双视图隔离、config 绑定防放大）
- 项2：量约束部分成交 fill<100 不再错拒（报 200 cap 37 → 37/163；
  报 100 cap 1 → 1/99；买卖两侧；申报量 <lot 仍拒）
真实 v2 包（511090 2024-04 分红三日期）+ 合成 fixture。
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import (
    build_fixture_package,
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import (
    CheckpointConfigMismatch,
    R01Ledger,
    R01LedgerConfig,
)
from backend.services.simulation.services.ashare_matcher import (
    MatchConfig,
    match_order,
)
from backend.services.simulation.services.local_market_data import DailyBar

REAL_PKG = "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7"
REAL_SHA = "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"
real_pkg_needed = pytest.mark.skipif(
    not __import__("pathlib").Path(REAL_PKG, "manifest.json").is_file(),
    reason="真实 v2 包不在本机",
)
SYM = "511090.SH"


def _bounded(rt):
    return load_etf_input_package(
        REAL_PKG, expect_manifest_sha256=REAL_SHA, read_through=rt
    )


def _cfg(**kw):
    kw.setdefault("group", "A")
    kw.setdefault("strategy_id", "acceptance-m6-boundary")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 20000.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


class TestReadThroughDaily:
    @real_pkg_needed
    def test_daily_rows_bounded_before_stats(self):
        """daily 行在统计前裁定：上界后交易日不可见。"""
        v = _bounded(date(2024, 4, 26))
        assert v.actual_max_input_date == date(2024, 4, 26)
        assert not v.is_trade_date(date(2024, 4, 29))
        assert v.is_trade_date(date(2024, 4, 23))
        full = _bounded(None)
        assert full.actual_max_input_date == date(2026, 9, 24)  # 现状整包不变

    @real_pkg_needed
    def test_manifest_intact_and_identity_unchanged(self):
        """完整性按全包哈希：上界视图与整包同 manifest_sha256/package_id。"""
        v = _bounded(date(2024, 12, 31))
        full = _bounded(None)
        assert v.manifest_sha256 == full.manifest_sha256 == REAL_SHA
        assert v.package_id == full.package_id

    @real_pkg_needed
    def test_run_day_beyond_bound_no_quote(self):
        """越界执行日：无行情行 → 显式 no_quote 拒单（不虚构）。"""
        v = _bounded(date(2024, 4, 26))
        led = R01Ledger(v, _cfg(read_through_bound=date(2024, 4, 26)))
        s = led.run_day(date(2024, 4, 23), {SYM: 0.7}, signal_date=date(2024, 4, 22))
        assert led.positions[SYM].qty > 0
        # 04-29 在上界后：is_trade_date False → LedgerOrderingError(not_trade_date)
        from backend.services.simulation.replay.r01_ledger import LedgerOrderingError

        with pytest.raises(LedgerOrderingError, match="not_trade_date"):
            led.run_day(date(2024, 4, 29), None)

    @real_pkg_needed
    def test_two_bounds_isolated_instances(self):
        """同包两上界视图互不污染（缓存按实例隔离）。"""
        v1 = _bounded(date(2024, 4, 26))
        v2 = _bounded(date(2024, 8, 30))
        assert v1.actual_max_input_date == date(2024, 4, 26)
        assert v2.actual_max_input_date == date(2024, 8, 30)
        # 触发缓存后再验证（互不串）
        v1.load_date(date(2024, 4, 23))
        v2.load_date(date(2024, 8, 29))
        assert v1.actual_max_input_date == date(2024, 4, 26)
        assert v2.actual_max_input_date == date(2024, 8, 30)


class TestReadThroughEvents:
    @real_pkg_needed
    def test_record_le_bound_ex_le_bound_pay_gt_bound_keeps_receivable(self):
        """①record 04-23≤bound 04-26、ex 04-24≤bound、pay 04-29>bound →
        应收在 ex 入账不丢（不按 pay 过滤丢权）。"""
        v = _bounded(date(2024, 4, 26))
        evs = [
            e for e in v.events_for(SYM)
            if e.event_type == "cash_dividend" and e.event_date == date(2024, 4, 24)
        ]
        assert evs, "record≤bound 的分红事件必须可见（保权）"
        led = R01Ledger(v, _cfg(read_through_bound=date(2024, 4, 26)))
        led.run_day(date(2024, 4, 23), {SYM: 0.7}, signal_date=date(2024, 4, 22))
        qty = led.positions[SYM].qty
        led.run_day(date(2024, 4, 24), None)  # ex 日：应收入账
        assert led.dividend_receivable == pytest.approx(qty * 1.5)
        assert led.cash < 20000.0  # 未到 pay：现金未增（分红现金不在现金）
        # pay 04-29 在上界后 → 不可执行（not_trade_date），应收保持
        from backend.services.simulation.replay.r01_ledger import LedgerOrderingError

        with pytest.raises(LedgerOrderingError):
            led.run_day(date(2024, 4, 29), None)
        assert led.dividend_receivable == pytest.approx(qty * 1.5)  # 不丢

    @real_pkg_needed
    def test_record_le_bound_lt_ex_entitlement_frozen(self):
        """②record≤bound<ex → 权益在 record 定格、事件可见（ex 越界
        不执行但事件不丢）。"""
        v = _bounded(date(2024, 4, 23))  # bound = record 日
        evs = [
            e for e in v.events_for(SYM)
            if e.event_type == "cash_dividend" and e.record_date == date(2024, 4, 23)
        ]
        assert evs, "record≤bound：事件可见"
        led = R01Ledger(v, _cfg(read_through_bound=date(2024, 4, 23)))
        led.run_day(date(2024, 4, 23), {SYM: 0.7}, signal_date=date(2024, 4, 22))
        # record EOD：权益定格（entitlement 记录存在）
        assert any(
            r["symbol"] == SYM for r in led.dividend_entitlements.values()
        ) or led.equity[-1]["trade_date"] == "2024-04-23"
        recs = [r for r in led.dividend_entitlements.values() if r["symbol"] == SYM]
        assert recs and recs[0]["entitlement_qty"] == pytest.approx(
            led.positions[SYM].qty
        )  # 权益定格

    @real_pkg_needed
    def test_fully_beyond_bound_events_invisible(self):
        """③完全在上界后的事件不加载（record>bound）。"""
        v = _bounded(date(2024, 4, 26))
        evs = [
            e for e in v.events_for(SYM)
            if e.event_type == "cash_dividend" and e.record_date >= date(2024, 8, 20)
        ]
        assert evs == []

    @real_pkg_needed
    def test_share_adjustment_only_to_authorized_date(self):
        """share_adjustment 仅应用到已授权生效日（511010 折算 2026-09-18）。"""
        v = _bounded(date(2026, 9, 17))  # 上界=折算前一日
        evs = [
            e for e in v.events_for("511010.SH")
            if e.event_type == "share_adjustment" and e.event_date == date(2026, 9, 18)
        ]
        assert evs == []  # 生效日在上界后 → 不可见
        v2 = _bounded(date(2026, 9, 18))
        evs2 = [
            e for e in v2.events_for("511010.SH")
            if e.event_type == "share_adjustment" and e.event_date == date(2026, 9, 18)
        ]
        assert evs2  # 生效日=上界 → 可见

    @real_pkg_needed
    def test_max_input_date_output(self):
        """④actual_max_input_date 正确（多档上界）。"""
        for rt, expect in (
            (date(2024, 4, 26), date(2024, 4, 26)),
            (date(2025, 6, 30), date(2025, 6, 30)),
            (date(2026, 9, 24), date(2026, 9, 24)),
            (None, date(2026, 9, 24)),
        ):
            assert _bounded(rt).actual_max_input_date == expect


class TestReadThroughConfigBinding:
    @real_pkg_needed
    def test_cap_bound_checkpoint_prevents_unauthorized_widening(self):
        """上界进冻结 config：同 config 恢复 OK；改上界（放大）→ 新
        version/attempt（config 不一致拒）。"""
        v = _bounded(date(2024, 4, 26))
        cfg = _cfg(read_through_bound=date(2024, 4, 26))
        led = R01Ledger(v, cfg)
        led.run_day(date(2024, 4, 23), {SYM: 0.7}, signal_date=date(2024, 4, 22))
        cp = led.export_checkpoint()
        r = R01Ledger.restore(v, cfg, cp)  # 同上界恢复 OK
        assert r.ledger_run_id == led.ledger_run_id
        wider = _cfg(read_through_bound=date(2024, 8, 31))
        with pytest.raises(CheckpointConfigMismatch):
            R01Ledger.restore(v, wider, cp)  # 放大上界须显式新 config


def _bar(vol):
    return DailyBar(
        symbol="510300.SH", trade_date=date(2026, 7, 10),
        open=4.0, high=4.0, low=4.0, close=4.0,
        volume=vol, amount=4.0 * vol, vwap=4.0, pre_close=4.0,
        limit_up=4.4, limit_down=3.6, is_st=False, suspended=False,
    )


class TestMatcherSmallFill:
    def _cfg(self):
        return MatchConfig(
            price_mode="open", asset_type="etf",
            allow_partial=True, slippage_bps=0.0,
        )

    def test_buy_200_cap_37_fills_37(self):
        """项2：报 200 cap 37 → 成交 37 余 163（fill<100 不再错拒）。"""
        mr = match_order("buy", 200, _bar(37), self._cfg(), cash_available=1e9)
        assert mr.success
        assert mr.fill_quantity == 37
        assert mr.qty_remaining == 163

    def test_buy_100_cap_1_fills_1(self):
        """报 100 cap 1 → 成交 1 余 99。"""
        mr = match_order("buy", 100, _bar(1), self._cfg(), cash_available=1e9)
        assert mr.success
        assert mr.fill_quantity == 1
        assert mr.qty_remaining == 99

    def test_sell_shared_guard_small_fill(self):
        """卖侧同守卫：报 200 量 37 → 成交 37 余 163。"""
        mr = match_order("sell", 200, _bar(37), self._cfg(), available_volume=200)
        assert mr.success
        assert mr.fill_quantity == 37
        assert mr.qty_remaining == 163

    def test_declared_below_lot_still_rejected(self):
        """申报量 <lot 的非法初始申报仍拒（BELOW_LOT_SIZE 只对申报量）。"""
        mr = match_order("buy", 50, _bar(1e6), self._cfg(), cash_available=1e9)
        assert not mr.success and mr.reason == "BELOW_LOT_SIZE"
        assert mr.qty_remaining == 50

    def test_zero_fill_rejected(self):
        """fill=0（量约束 0）仍显式拒（保 fill>0 下限）。"""
        mr = match_order("buy", 200, _bar(0.001), self._cfg(), cash_available=1e9)
        assert not mr.success


class TestM6E2BoundBinding:
    @real_pkg_needed
    def test_narrow_config_wide_view_rejected(self):
        """项2：窄 config（None/早日期）+ 宽视图 → 拒（错误含双方值）。"""
        v = _bounded(date(2024, 8, 30))
        with pytest.raises(ValueError, match="read_through_bound mismatch"):
            R01Ledger(v, _cfg())  # config 无上界 vs 视图 08-30
        with pytest.raises(ValueError, match="2024-04-26"):
            R01Ledger(v, _cfg(read_through_bound=date(2024, 4, 26)))

    @real_pkg_needed
    def test_consistent_bound_passes(self):
        """一致通过：config 上界 == 视图上界。"""
        v = _bounded(date(2024, 4, 26))
        led = R01Ledger(v, _cfg(read_through_bound=date(2024, 4, 26)))
        led.run_day(date(2024, 4, 23), {SYM: 0.7}, signal_date=date(2024, 4, 22))
        assert led.positions[SYM].qty > 0

    @real_pkg_needed
    def test_wide_config_narrow_view_rejected(self):
        """宽 config + 窄视图 → 同样拒（双向一致）。"""
        v = _bounded(date(2024, 4, 26))
        with pytest.raises(ValueError, match="mismatch"):
            R01Ledger(v, _cfg(read_through_bound=date(2024, 8, 30)))

    @real_pkg_needed
    def test_checkpoint_restore_checks_binding(self):
        """恢复路径核对：同 bound 恢复 OK；换视图 bound → 拒。"""
        v = _bounded(date(2024, 4, 26))
        cfg = _cfg(read_through_bound=date(2024, 4, 26))
        led = R01Ledger(v, cfg)
        led.run_day(date(2024, 4, 23), {SYM: 0.7}, signal_date=date(2024, 4, 22))
        cp = led.export_checkpoint()
        r = R01Ledger.restore(v, cfg, cp)  # 一致恢复 OK
        assert r.ledger_run_id == led.ledger_run_id
        v_wide = _bounded(date(2024, 8, 30))
        with pytest.raises(ValueError, match="read_through_bound mismatch"):
            R01Ledger.restore(v_wide, cfg, cp)  # 宽视图恢复窄 config → 拒

    def test_full_package_with_none_config_still_works(self, tmp_path):
        """整包视图（read_through=None）+ config None：现状不变。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg())
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 9))
        assert led.orders


class TestM6E2Prefilter:
    def test_future_garbage_rows_do_not_break_prefix(self, tmp_path):
        """项1：上界后行含非法值（NaN 日期/坏数字）不影响授权前缀加载。"""
        import json

        import pandas as pd

        root = tmp_path / "pkg"
        (root / "daily").mkdir(parents=True)
        (root / "events").mkdir(parents=True)
        rows = [
            {"trade_date": "2026-07-06", "open": 4.0, "high": 4.0, "low": 4.0,
             "close": 4.0, "volume": 1000.0, "amount": 4000.0, "adj_factor": 1.0},
            {"trade_date": "2026-07-07", "open": 4.1, "high": 4.1, "low": 4.1,
             "close": 4.1, "volume": 1000.0, "amount": 4100.0, "adj_factor": 1.0},
            # 上界后的非法行：NaN/None 日期 + NaN 数值（未来行不进解析路径）
            {"trade_date": None, "open": float("nan"), "high": None, "low": float("nan"),
             "close": None, "volume": None, "amount": None, "adj_factor": None},
        ]
        pd.DataFrame(rows).to_parquet(root / "daily" / "510300.SH.parquet", index=False)
        pd.DataFrame([], columns=["event_date", "event_type"]).to_parquet(
            root / "events" / "510300.SH.parquet", index=False
        )
        manifest = {
            "schema_version": 3, "package_id": "fixture-m6e2-garbage",
            "package_version": "m6e2", "package_uri": "node://mac/r01-etf-daily/fixture-m6e2-garbage",
            "source_release_id": "fixture", "generated_at": "2026-09-26T00:00:00Z",
            "generated_by_node": "mac",
            "source_datasets": [{"api_name": n, "sha256": "0" * 64} for n in
                                ("fund_daily", "fund_adj", "fund_div", "trade_cal", "etf_limit")],
            "unit_conversions": {"vol": "lot(100 shares) -> shares, multiply by 100",
                                 "amount": "thousand CNY -> CNY, multiply by 1000", "rules": "s"},
            "factor_convention": {"formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
                                  "verified_cases": []},
            "symbols": [{"code": "510300.SH", "class": "equity_broad", "role": "primary",
                         "data_start": "2026-07-06", "data_end": "2026-07-07",
                         "missing_days": [], "warmup_start": "2026-07-06"}],
            "known_gaps": [],
        }
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
        v = load_etf_input_package(root, read_through=date(2026, 7, 7))
        # 授权前缀加载成功（非法未来行不进解析路径/不影响）
        assert v.actual_max_input_date == date(2026, 7, 7)
        assert v.get_bar("510300.SH", date(2026, 7, 6)).close == 4.0
        led = R01Ledger(v, _cfg(read_through_bound=date(2026, 7, 7)))
        led.run_day(date(2026, 7, 6), None)
        led.run_day(date(2026, 7, 7), {"510300.SH": 0.5})
        assert any(o.side == "buy" for o in led.orders.values())
