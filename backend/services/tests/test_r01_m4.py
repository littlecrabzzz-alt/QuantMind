"""R01P0-M4E1 测试：限界修订四项（R01SELF 独立复验 HOLD 反馈）。

- 项1：零股判定收窄到已证关系（total≈available）；total≠available 放行+审计
- 项2：manual_sell 统一申报入口（截断/撮合前同一校验）
- 项3：checkpoint 订单/成交全精度（JSON 往返：commission 0.12003≠0.12）；
  L901 目标额度取精确 NAV
- 项4：版本绑定 v3.1 / checkpoint schema v6；v5 legacy 接受不补造；边界
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
    CONTRACT_VERSIONS,
    CheckpointConfigMismatch,
    CheckpointPackageMismatch,
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
    """2026-07 生效后窗口的合成包（≥2026-07-06）。"""
    days = _weekdays(date(2026, 7, 7), 8)
    (tmp_path / "daily").mkdir(parents=True)
    (tmp_path / "events").mkdir(parents=True)
    pd.DataFrame([{
        "trade_date": d.isoformat(), "open": PRICE, "high": PRICE, "low": PRICE,
        "close": PRICE, "volume": 1_200_000.0, "amount": PRICE * 1_200_000 * 100 / 1000,
        "adj_factor": 1.0,
    } for d in days]).to_parquet(tmp_path / "daily" / f"{SYM}.parquet", index=False)
    pd.DataFrame(
        [], columns=["symbol", "event_date", "event_type"]
    ).to_parquet(tmp_path / "events" / f"{SYM}.parquet", index=False)
    manifest = {
        "schema_version": 3, "package_id": "fixture-m4", "package_version": "m4",
        "package_uri": "node://mac/r01-etf-daily/fixture-m4", "source_release_id": "fixture",
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
    kw.setdefault("strategy_id", "fixture-m4")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 500.0)
    kw.setdefault("commission_rate", 0.0003)
    kw.setdefault("commission_min", 0.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


def _seed_total5(led, days):
    """买 100 → 折算 ×0.05 → 总仓=可卖=5。"""
    led.run_day(days[0], None)
    led.run_day(days[1], {SYM: 0.8})
    led.run_day(days[2], None)
    # 折算事件需在包内——用合成折算注入（直接调整 pos 更简单且等价）
    pos = led.positions[SYM]
    pos.qty = 5.0
    pos.available_qty = 5.0
    pos.avg_cost = pos.avg_cost * 100 / 5
    return led


class TestItem1NarrowToProvenRelation:
    def test_total_eq_available_partial_rejected(self, pkg_2026):
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        w = 2.0 * PRICE / led.equity[-1]["nav"]
        s = led.run_day(days[3], {SYM: w})  # 申报 3（fold 后次日）
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["status"] == "rejected"
        assert o["reject_reason"].startswith("sublot_partial_sell_not_allowed")
        assert "total=5.0,available=5.0,declared=3" in o["reject_reason"]
        assert led.positions[SYM].qty == 5.0

    def test_locked_period_total_ne_available_small_decl_passes(self, pkg_2026):
        """静态反例（对方报告 §1）：总仓 105、可卖 5、申报 3 ——
        total≠available 无官方依据 → 放行（审计字段保留）。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        pos = led.positions[SYM]
        pos.qty = 105.0      # total ≠ available（如 T+1 锁定 100）
        pos.available_qty = 5.0
        # 目标 = total-3 = 102 → 申报 3（对方静态反例形态）
        w = 102.0 * PRICE / led.equity[-1]["nav"]
        s = led.run_day(days[3], {SYM: w})
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["qty_target"] == 3
        assert o["reject_reason"] is None  # 未证关系不判
        assert o["qty_filled"] == 3        # 成交 3（可卖 5 足量，现状）

    def test_full_declaration_passes(self, pkg_2026):
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        w = 0.0
        s = led.run_day(days[3], {SYM: w})  # 申报 5（全额）
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["status"] == "filled" and o["qty_filled"] == 5
        assert SYM not in led.positions


class TestItem2ManualSellUnified:
    def test_manual_5_to_3_rejected(self, pkg_2026):
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        led.run_day(days[3], None)
        order = led.manual_sell(days[3], SYM, 3, reason="r", requested_by="u")
        assert order.status == "rejected"
        assert order.reject_reason.startswith("sublot_partial_sell_not_allowed")
        assert "manual" in order.reject_reason
        assert led.positions[SYM].qty == 5.0
        assert led.manual_actions[-1]["status"] == "rejected"

    def test_manual_5_to_5_fills(self, pkg_2026):
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        led.run_day(days[3], None)
        order = led.manual_sell(days[3], SYM, 5, reason="r", requested_by="u")
        assert order.status == "filled" and order.qty_filled == 5
        assert SYM not in led.positions

    def test_manual_locked_period_passes(self, pkg_2026):
        """锁定期间（total≠available）manual 小申报放行。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        pos = led.positions[SYM]
        pos.qty, pos.available_qty = 105.0, 5.0
        led.run_day(days[3], None)
        order = led.manual_sell(days[3], SYM, 3, reason="r", requested_by="u")
        assert order.reject_reason is None
        assert order.qty_filled == 3

    def test_manual_pre_effective_boundary(self):
        """生效日边界：manual 在 2026-07-05（前）放行。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pkg = build_fixture_package(Path(td) / "p")
            led = R01Ledger(pkg, _cfg(initial_cash=5000.0))  # fixture 日期 2025-09 < 生效日
            led.run_day(date(2025, 9, 10), {"510300.SH": 0.2}, signal_date=date(2025, 9, 9))
            pos = led.positions[SYM]
            pos.qty = pos.available_qty = 5.0
            order = led.manual_sell(date(2025, 9, 11), SYM, 3, reason="r", requested_by="u")
            assert order.reject_reason is None  # 生效前无校验


class TestItem3CheckpointFullPrecision:
    def test_fill_json_roundtrip_exact_commission(self):
        """对方反例：100 份×4.001、费率 0.0003、min 0 → commission
        = 0.12003（非 0.12）——JSON 往返逐位相等。"""
        from backend.services.simulation.replay.r01_ledger import LedgerFill

        fill = LedgerFill(
            trade_date="2026-07-08", symbol=SYM, side="buy",
            price=4.001, quantity=100,
            commission=100 * 4.001 * 0.0003,
            stamp_duty=0.0, transfer_fee=0.0,
            total_fee=100 * 4.001 * 0.0003,
        )
        assert fill.commission == pytest.approx(0.12003)
        rt = json.loads(json.dumps(fill.to_dict()))
        assert rt["commission"] == fill.commission          # 全精度（非 0.12）
        assert rt["total_fee"] == fill.total_fee
        assert rt["price"] == fill.price
        back = LedgerFill.from_dict(rt)
        assert back.commission == fill.commission
        assert back.total_fee == fill.total_fee

    def test_order_json_roundtrip_exact_fields(self, tmp_path):
        """订单 fees/realized_pnl/avg_fill_price JSON 往返全精度。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = json.loads(json.dumps(led.export_checkpoint()))
        assert cp["schema_version"] == 6
        restored = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        for coid, o in restored.orders.items():
            orig = led.orders[coid]
            assert o.fees == orig.fees
            assert o.avg_fill_price == orig.avg_fill_price
            assert o.realized_pnl == orig.realized_pnl
            for f1, f2 in zip(o.fills, orig.fills, strict=True):
                assert f1.commission == f2.commission
                assert f1.total_fee == f2.total_fee
                assert f1.price == f2.price

    def test_signal_reference_uses_exact_nav(self, tmp_path):
        """L901：目标额度取精确 NAV（nav_exact）——构造 nav 与 nav_exact
        差异（4dp 舍入边缘），验证 sizing 用精确值。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        # 注入小数 NAV（对齐 nav_exact≠round(nav,4) 的边缘）
        snap = led.equity[-1]
        snap["nav_exact"] = snap["nav"] + 0.00004  # 4dp 舍入边缘差异
        nav_ref, _ = led._signal_reference(date(2025, 9, 11), date(2025, 9, 10))
        assert nav_ref == snap["nav_exact"]  # 精确 NAV（非 4dp nav）


class TestItem4VersionBinding:
    def test_contract_version_v31(self):
        assert CONTRACT_VERSIONS["ledger_contract"] == "v3.1"

    def test_checkpoint_schema_v6_full_precision(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        assert cp["schema_version"] == 6
        assert cp["precision_semantics"] == "full_precision"

    def test_v5_legacy_accepted_not_compensated(self, tmp_path):
        """v5（legacy_precision，ledger_contract=v3）接受；不补造已丢精度。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        # 伪装为 v5 时代快照（schema 5 + v3 合同 + 4dp 舍入的订单费用）
        cp["schema_version"] = 5
        cp.pop("precision_semantics", None)
        cp["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        for o in cp["orders"].values():
            o["fees"] = round(o["fees"], 4)
            for f in o.get("fills", []):
                f["commission"] = round(f["commission"], 4)
                f["total_fee"] = round(f["total_fee"], 4)
        restored = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)  # legacy 接受
        o = next(iter(restored.orders.values()))
        assert o.fees == round(o.fees, 4)  # 按原样恢复（4dp），不补造

    def test_v4_rejected_missing_binding(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp["schema_version"] = 4
        cp.pop("input_binding", None)
        with pytest.raises(CheckpointPackageMismatch, match="input_binding"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)

    def test_unknown_schema_rejected(self, tmp_path):
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp["schema_version"] = 7
        with pytest.raises(CheckpointConfigMismatch, match="schema_version"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)

    def test_v5_vs_v6_distinguishable(self, tmp_path):
        """同配置 v5/v6 可区分（schema 字段不同、恢复语义标记不同）。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        v6 = led.export_checkpoint()
        v5 = copy.deepcopy(v6)
        v5["schema_version"] = 5
        v5.pop("precision_semantics", None)
        v5["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        assert v5["schema_version"] != v6["schema_version"]
        assert "precision_semantics" in v6 and "precision_semantics" not in v5


class TestM4E2PassAudit:
    def test_locked_period_pass_leaves_audit_trace(self, pkg_2026):
        """项1：total≠available 放行留痕（skipped_unproven_scope）。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        pos = led.positions[SYM]
        pos.qty, pos.available_qty = 105.0, 5.0
        w = 102.0 * PRICE / led.equity[-1]["nav"]  # 申报 3
        s = led.run_day(days[3], {SYM: w})
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["reject_reason"] is None  # 放行
        # 审计痕迹：summary.sublot_checks + to_dict 留痕
        checks = [c for c in s.sublot_checks if c["symbol"] == SYM]
        assert checks, "放行须留 sublot_check 审计"
        assert checks[0]["sublot_check"] == "skipped_unproven_scope"
        assert checks[0]["total"] == 105.0 and checks[0]["available"] == 5.0
        assert checks[0]["declared"] == 3
        assert "client_order_id" in checks[0]

    def test_balance_ge_100_pass_audit(self, pkg_2026):
        """余额≥100 放行留痕（skipped_balance_ge_100）。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        pos = led.positions[SYM]
        pos.qty = pos.available_qty = 105.0
        w = 103.0 * PRICE / led.equity[-1]["nav"]  # 申报 2
        s = led.run_day(days[3], {SYM: w})
        o = [x for x in s.orders if x["side"] == "sell"][0]
        assert o["reject_reason"] is None
        checks = [c for c in s.sublot_checks if c["symbol"] == SYM]
        assert checks and checks[0]["sublot_check"] == "skipped_balance_ge_100"

    def test_reject_audit_enforced(self, pkg_2026):
        """拒单场景留痕 enforced_reject。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        w = 2.0 * PRICE / led.equity[-1]["nav"]  # 申报 3（总仓=可卖=5）
        s = led.run_day(days[3], {SYM: w})
        checks = [c for c in s.sublot_checks if c["symbol"] == SYM]
        assert checks and checks[0]["sublot_check"] == "enforced_reject"

    def test_manual_pass_leaves_log(self, pkg_2026):
        """manual 放行留痕（sublot_check_log）。"""
        days = pkg_2026.trade_dates()[:6]
        led = _seed_total5(R01Ledger(pkg_2026, _cfg()), days)
        pos = led.positions[SYM]
        pos.qty, pos.available_qty = 105.0, 5.0
        led.run_day(days[3], None)
        order = led.manual_sell(days[3], SYM, 3, reason="r", requested_by="u")
        assert order.reject_reason is None
        entry = [c for c in led.sublot_check_log if c["symbol"] == SYM]
        assert entry and entry[-1]["sublot_check"] == "skipped_unproven_scope"
        assert "manual" in entry[-1].get("context", "")


class TestM4E2PrecisionChain:
    def test_v5_restore_then_reexport_marks_legacy(self, tmp_path):
        """项2：v5→恢复→再导出 schema6 标记 legacy（不冒充 full）。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        # 伪装 v5（legacy：schema 5、v3 合同、4dp 订单费用、无 precision 标记）
        cp["schema_version"] = 5
        cp.pop("precision_semantics", None)
        cp["contract_versions"] = {"ledger_contract": "v3", "etf_input_package_schema": "v3"}
        for o in cp["orders"].values():
            o["fees"] = round(o["fees"], 4)
            for f in o.get("fills", []):
                f["commission"] = round(f["commission"], 4)
                f["total_fee"] = round(f["total_fee"], 4)
        restored = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        assert restored.checkpoint_precision_origin == "legacy_precision"
        # 再导出：schema 6 结构 + legacy 标记（语义链正确传递）
        cp2 = restored.export_checkpoint()
        assert cp2["schema_version"] == 6
        assert cp2["precision_semantics"] == "legacy_precision"
        # legacy 链再次恢复仍正确
        r2 = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp2)
        assert r2.checkpoint_precision_origin == "legacy_precision"
        # 不冒充 full：legacy 恢复的费用保持原样（4dp）
        o = next(iter(r2.orders.values()))
        assert o.fees == round(o.fees, 4)

    def test_v6_missing_precision_rejected(self, tmp_path):
        """schema 6 缺 precision_semantics → 损坏拒绝。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        cp.pop("precision_semantics")
        with pytest.raises(CheckpointConfigMismatch, match="precision_semantics"):
            R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)

    def test_fresh_ledger_marks_full(self, tmp_path):
        """新建账本导出标记 full_precision。"""
        pkg = build_fixture_package(tmp_path / "p")
        led = R01Ledger(pkg, _cfg(initial_cash=2000.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.8}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        assert cp["precision_semantics"] == "full_precision"
        r = R01Ledger.restore(pkg, _cfg(initial_cash=2000.0), cp)
        assert r.checkpoint_precision_origin == "full_precision"
