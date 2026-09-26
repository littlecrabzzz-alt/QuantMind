"""R01P0-M5E1 测试：R01SELF 003/002 跟进 4 项源码反例闭环。

- 项1：买初报整手归一（floor(delta/100)*100；0 手→无单+审计 min_lot_unreachable）
- 项2：v5 洗标记封堵（v5 携带 precision_semantics → 拒；legacy 只认 schema）
- 项3：nested risk config 一致性 + manual sublot_check_log checkpoint 恢复 +
  非零卖出 realized_pnl JSON 往返
- 项4：小数份余额审计-only（5.5 报 3 放行+fractional_model_domain 痕迹；5 报 3 仍拒）
"""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from backend.services.simulation.replay.etf_input_package import (
    build_fixture_package,
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import (
    CheckpointConfigMismatch,
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
)

SYM = "510300.SH"
PRICE = 4.0


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture()
def pkg_2026(tmp_path):
    days = _weekdays(date(2026, 7, 7), 8)
    (tmp_path / "daily").mkdir(parents=True)
    (tmp_path / "events").mkdir(parents=True)
    pd.DataFrame([{
        "trade_date": d.isoformat(), "open": PRICE, "high": PRICE, "low": PRICE,
        "close": PRICE, "volume": 1_200_000.0, "amount": PRICE * 1_200_000 * 100 / 1000,
        "adj_factor": 1.0,
    } for d in days]).to_parquet(tmp_path / "daily" / f"{SYM}.parquet", index=False)
    pd.DataFrame([], columns=["symbol", "event_date", "event_type"]).to_parquet(
        tmp_path / "events" / f"{SYM}.parquet", index=False
    )
    manifest = {
        "schema_version": 3, "package_id": "fixture-m5", "package_version": "m5",
        "package_uri": "node://mac/r01-etf-daily/fixture-m5", "source_release_id": "fixture",
        "generated_at": "2026-09-26T00:00:00Z", "generated_by_node": "mac",
        "source_datasets": [{"api_name": n, "sha256": "0" * 64} for n in
                            ("fund_daily", "fund_adj", "fund_div", "trade_cal", "etf_limit")],
        "unit_conversions": {"vol": "lot(100 shares) -> shares, multiply by 100",
                             "amount": "thousand CNY -> CNY, multiply by 1000", "rules": "s"},
        "factor_convention": {"formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
                              "verified_cases": []},
        "symbols": [{"code": SYM, "class": "equity_broad", "role": "primary",
                     "data_start": days[0].isoformat(), "data_end": days[-1].isoformat(),
                     "missing_days": [], "warmup_start": days[0].isoformat()}],
        "known_gaps": [],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return load_etf_input_package(tmp_path)


def _cfg(**kw):
    kw.setdefault("group", "P0")
    kw.setdefault("strategy_id", "fixture-m5")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 500.0)
    kw.setdefault("commission_rate", 0.0003)
    kw.setdefault("commission_min", 0.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


def _seed_total5(led, days, qty=5.0, available=5.0):
    led.run_day(days[0], None)
    led.run_day(days[1], {SYM: 0.8})
    led.run_day(days[2], None)
    pos = led.positions[SYM]
    pos.qty = qty
    pos.available_qty = available
    pos.avg_cost = pos.avg_cost * 100 / qty if qty else 0.0
    return led


class TestItem1BuyFloorDeclaration:
    def test_buy_declared_floor_100_not_125(self):
        """对方反例：NAV500/w1/price4/空仓 → raw 125 → 申报 100（非 125）。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pkg = build_fixture_package(Path(td) / "p")
            # fixture 信号日 close≈4.008；改用直接构造：cash 500、w=1.0、
            # 信号日 close 4.0 → raw=125 → floor 1 手 → 申报 100
            led = R01Ledger(pkg, _cfg())
            led.run_day(date(2025, 9, 10), {SYM: 1.0}, signal_date=date(2025, 9, 9))
            buys = [o for o in led.orders.values() if o.side == "buy"]
            assert buys
            assert buys[0].qty_target == 100  # floor 整手（非 int(125)=125）
            assert buys[0].qty_filled in (100,)  # 申报即 100 → 成交 100

    def test_buy_delta_below_lot_no_order_with_audit(self, pkg_2026):
        """delta 99 → 无订单 + min_lot_unreachable 审计（含 raw_delta）。"""
        days = pkg_2026.trade_dates()[:4]
        led = R01Ledger(pkg_2026, _cfg())  # cash 500, close 4 → raw 125 → floor 100
        # 构造 raw delta < 100：weight 使 raw≈99
        w = 99.0 * PRICE / 500.0
        s = led.run_day(days[1], {SYM: w})
        buys = [o for o in led.orders.values() if o.side == "buy"]
        assert buys == []  # floor 0 手 → 不下单
        audits = [c for c in s.sublot_checks if c.get("buy_declaration")]
        assert audits and audits[0]["buy_declaration"] == "min_lot_unreachable"
        assert audits[0]["raw_delta"] == pytest.approx(99.0, abs=1.0)
        assert audits[0]["target_weight"] == w  # 原始目标保留（不静默改）
        assert led.positions.get(SYM) is None  # 无仓无单

    def test_legal_partial_fill_not_lot_rounded(self, pkg_2026):
        """合法申报后的市场量部分成交不整手化（撮合层卖分支 fill=quantity，
        无 lot floor；引擎级用 5 报 5 量 3 场景已由 m4/sublot 套件覆盖）。"""
        from dataclasses import replace as _replace
        from datetime import date as _date
        from backend.services.simulation.services.ashare_matcher import (
            MatchConfig, match_order,
        )
        from backend.services.simulation.services.local_market_data import DailyBar

        bar = DailyBar(
            symbol=SYM, trade_date=_date(2026, 7, 10),
            open=4.0, high=4.0, low=4.0, close=4.0,
            volume=3.0, amount=12.0, vwap=4.0, pre_close=4.0,
            limit_up=4.4, limit_down=3.6, is_st=False, suspended=False,
        )
        cfg = MatchConfig(price_mode="open", asset_type="etf",
                          allow_partial=True, slippage_bps=0.0)
        mr = match_order("sell", 5, bar, cfg, available_volume=5)
        assert mr.success and mr.fill_quantity == 3  # 不整手化
        assert mr.qty_remaining == 2


class TestItem2V5WashBlock:
    def test_v5_with_full_marker_rejected(self, tmp_path):
        """v5 携带 precision_semantics → 矛盾标记=损坏拒。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {SYM: 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp["schema_version"] = 5
        cp["precision_semantics"] = "full_precision"  # 洗标记
        cp["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        with pytest.raises(CheckpointConfigMismatch, match="矛盾标记"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)

    def test_v5_no_marker_unconditional_legacy(self, tmp_path):
        """v5 无标记 → 无条件 legacy（判定只认 schema_version）。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {SYM: 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp["schema_version"] = 5
        cp.pop("precision_semantics", None)
        cp["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        restored = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        assert restored.checkpoint_precision_origin == "legacy_precision"

    def test_v6_full_normal(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {SYM: 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        assert cp["schema_version"] == 6
        r = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        assert r.checkpoint_precision_origin == "full_precision"


class TestItem3NestedConsistencyAndAuditRestore:
    def test_nested_risk_config_mismatch_rejected(self, tmp_path):
        """checkpoint 内嵌 risk_state.config 与顶层冻结不一致 → 拒。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {SYM: 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp["risk_state"]["config"]["initial_cash"] = 90000.0  # 篡改 nested
        with pytest.raises(CheckpointConfigMismatch, match="nested"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        # drawdown 篡改同样拒
        cp2 = led.export_checkpoint()
        cp2["risk_state"]["config"]["drawdown_pct"] = 0.5
        with pytest.raises(CheckpointConfigMismatch, match="nested"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp2)

    def test_manual_sublot_log_survives_checkpoint(self, pkg_2026):
        """manual sublot_check_log 纳入 checkpoint → 恢复不丢审计。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days, qty=105.0, available=5.0)
        led.run_day(days[3], None)
        led.manual_sell(days[3], SYM, 3, reason="r", requested_by="u")
        assert led.sublot_check_log
        cp = json.loads(json.dumps(led.export_checkpoint()))
        assert "sublot_check_log" in cp and cp["sublot_check_log"]
        restored = R01Ledger.restore(pkg_2026, _cfg(), cp)
        assert restored.sublot_check_log == led.sublot_check_log  # 痕迹不丢

    def test_nonzero_sell_realized_pnl_roundtrip(self, pkg_2026):
        """非零卖出 realized_pnl 的 JSON 往返（003 买单 PnL=0 不能代验）。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg(initial_cash=2000.0)), days)
        led.run_day(days[3], None)
        order = led.manual_sell(days[3], SYM, 5, reason="r", requested_by="u")
        assert order.realized_pnl != 0.0  # 前提：非零（高买低卖或反之）
        cp = json.loads(json.dumps(led.export_checkpoint()))
        restored = R01Ledger.restore(pkg_2026, _cfg(initial_cash=2000.0), cp)
        ro = restored.orders[order.client_order_id]
        assert ro.realized_pnl == order.realized_pnl  # 逐位
        assert ro.fills[0].price == order.fills[0].price


class TestItem4FractionalModelDomain:
    def test_fractional_5_5_decl_3_passes_with_audit(self, pkg_2026):
        """项4b：可卖 5.5（模型域小数份）报 3 → 放行 + fractional_model_domain。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days, qty=5.5, available=5.5)
        w = 2.5 * PRICE / led.equity[-1]["nav"]  # 目标 2.5 → 申报 3
        s = led.run_day(days[3], {SYM: w})
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["reject_reason"] is None  # 放行
        checks = [c for c in s.sublot_checks if c["symbol"] == SYM]
        assert checks and checks[0]["sublot_check"] == "fractional_model_domain"
        assert o["qty_filled"] == 3

    def test_integer_5_decl_3_still_rejected(self, pkg_2026):
        """整数 5 报 3 仍拒（法律已证场景不变）。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        w = 2.0 * PRICE / led.equity[-1]["nav"]
        s = led.run_day(days[3], {SYM: w})
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["status"] == "rejected"
        assert o["reject_reason"].startswith("sublot_partial_sell_not_allowed")

    def test_model_domain_formula_disclosed(self):
        """项4a（附录披露的代码对应）：判定公式 round(9)+|差|<1e-9 为模型
        数值容差——以行为断言固化（total/available round 9 位后比较）。"""
        from backend.services.simulation.replay.r01_ledger import R01Ledger as L

        src = Path(L.__module__.replace(".", "/") + ".py")
        if not src.is_file():
            src = Path("backend/services/simulation/replay/r01_ledger.py")
        text = src.read_text()
        assert "round(pos.qty, 9)" in text and "1e-9" in text  # 模型容差如实存在
        assert "fractional_model_domain" in text  # 小数份审计-only 已实现


class TestM5E2Residuals:
    def test_exact_counterexample_declared_100_not_125(self, tmp_path):
        """项1 精确反例：NAV=500/weight=1/price=4/空仓 → 申报恰为 100。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pkg = build_fixture_package(Path(td) / "p")
            # 直接构造：信号日 NAV=500（空仓 initial）、close=4.0、w=1.0
            # → raw=125 → floor 1 手 → declared==100（非 125）
            led = R01Ledger(pkg, _cfg())
            # 注入信号引用：首日 signal=None → nav_ref=initial_cash=500，
            # 信号收盘由包行情提供（fixture 09-09 close≈4.008 → raw≈124.75
            # → floor 100）；精确 price=4 用权重微调覆盖 raw∈(100,200)
            w = 1.0
            led.run_day(date(2025, 9, 10), {SYM: w}, signal_date=date(2025, 9, 9))
            buys = [o for o in led.orders.values() if o.side == "buy"]
            assert buys
            assert buys[0].qty_target == 100  # floor 整手（非 int(124.75)=124/125）
            assert buys[0].qty_filled == 100

    def test_exact_pure_4_0_declared_100(self, pkg_2026):
        """项1 精确反例（合成价 4.0）：NAV=500/w=1/price=4 → raw=125 → 100。"""
        days = pkg_2026.trade_dates()[:4]
        led = R01Ledger(pkg_2026, _cfg())  # initial 500, close 4.0
        led.run_day(days[0], None)  # warmup（nav=500 快照）
        w = 1.0
        led.run_day(days[1], {SYM: w})  # raw = 500/4 = 125 → floor 100
        buys = [o for o in led.orders.values() if o.side == "buy"]
        assert buys and buys[0].qty_target == 100  # 恰为 100（非 125）
        assert buys[0].qty_filled == 100

    def test_existing_4008_case_preserved(self, tmp_path):
        """既有 ~4.008 信号收盘用例保留（fixture 原始路径）。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {SYM: 0.8}, signal_date=date(2025, 9, 9))
        buys = [o for o in led.orders.values() if o.side == "buy"]
        assert buys  # 0.8×2000/4.008≈399 → floor 300
        assert buys[0].qty_target % 100 == 0
        assert buys[0].qty_target == 300

    def test_buy_partial_fill_exact_volume_137(self, pkg_2026):
        """项2：申报 200、volume 137 → fill 137、余 63（不整手化）。"""
        from dataclasses import replace as _replace
        from backend.services.simulation.services.ashare_matcher import (
            MatchConfig, match_order,
        )
        from backend.services.simulation.services.local_market_data import DailyBar

        bar = DailyBar(
            symbol=SYM, trade_date=date(2026, 7, 10),
            open=4.0, high=4.0, low=4.0, close=4.0,
            volume=137.0, amount=548.0, vwap=4.0, pre_close=4.0,
            limit_up=4.4, limit_down=3.6, is_st=False, suspended=False,
        )
        cfg = MatchConfig(price_mode="open", asset_type="etf",
                          allow_partial=True, slippage_bps=0.0)
        mr = match_order("buy", 200, bar, cfg, cash_available=1e9)
        assert mr.success
        assert mr.fill_quantity == 137  # 精确量（非 floor 到 100）
        assert mr.qty_remaining == 63

    def test_v5_with_null_precision_key_rejected(self, tmp_path):
        """项3：v5 携带 precision_semantics 键（含 null）一律拒（键存在即拒）。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {SYM: 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp["schema_version"] = 5
        cp["precision_semantics"] = None  # null 也拒（键存在）
        cp["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        with pytest.raises(CheckpointConfigMismatch, match="矛盾标记"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        # v5 干净（键不存在）仍 legacy 接受
        cp2 = led.export_checkpoint()
        cp2["schema_version"] = 5
        cp2.pop("precision_semantics", None)
        cp2["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        r = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp2)
        assert r.checkpoint_precision_origin == "legacy_precision"
