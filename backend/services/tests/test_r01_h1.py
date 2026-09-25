"""R01P0-H1E1 测试：公共展示导出 export_view（view_schema=1）。

场景全部使用 v2 包 511090 五日窗口（2024-04-23/24/25/26/29，与 G 轮验收
同源；分红 record 04-23 / ex 04-24 / pay 04-29，cps 1.5）。
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import load_etf_input_package
from backend.services.simulation.replay.r01_ledger import (
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
    ViewBuildError,
    build_view_from_evidence,
    identify_export_format,
)

REAL_PKG = "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7"
REAL_SHA = "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"
real_pkg_needed = pytest.mark.skipif(
    not __import__("pathlib").Path(REAL_PKG, "manifest.json").is_file(),
    reason="真实输入包 v2 不在本机",
)
SYM = "511090.SH"


@pytest.fixture(scope="module")
def pkg():
    return load_etf_input_package(REAL_PKG, expect_manifest_sha256=REAL_SHA)


def _cfg(name, **kw):
    d = {
        "group": "A", "strategy_id": "acceptance-" + name, "strategy_version": 1,
        "execution_attempt_id": 1, "initial_cash": 20000.0,
        "commission_rate": 0.0003, "commission_min": 0.1, "slippage_bps": 0.0,
    }
    d.update(kw)
    return R01LedgerConfig(**d)


def _run_window(pkg, cfg, weights_by_day=None, buy_qty=100):
    """五日窗口：04-22 买入（record 前一交易日），04-23..04-29 逐日。"""
    led = R01Ledger(pkg, cfg)
    o = led.submit_order(date(2024, 4, 22), SYM, "buy", buy_qty)
    bars = pkg.load_date(date(2024, 4, 22))
    led._validate_and_execute(o, date(2024, 4, 22), bars, DaySummary(trade_date="2024-04-22"))
    led._eod(date(2024, 4, 22), bars, DaySummary(trade_date="2024-04-22"))
    weights_by_day = weights_by_day or {}
    for d in [date(2024, 4, 23), date(2024, 4, 24), date(2024, 4, 25), date(2024, 4, 26), date(2024, 4, 29)]:
        led.run_day(d, weights_by_day.get(d))
    return led


class TestViewBasics:
    @real_pkg_needed
    def test_view_schema_and_invariants(self, pkg):
        led = _run_window(pkg, _cfg("h1-view"))
        view = led.export_view()
        assert view["view_schema"] == 2
        assert view["derived_from"] == "R01Ledger.export_evidence"
        assert view["session"]["ledger_run_id"] == led.ledger_run_id
        assert view["package"]["package_id"] == pkg.package_id
        # 五日窗口 + 建仓日 = 6 天，逐日有序
        dates = [d["date"] for d in view["days"]]
        assert dates == [
            "2024-04-22", "2024-04-23", "2024-04-24", "2024-04-25",
            "2024-04-26", "2024-04-29",
        ]
        for day in view["days"]:
            assert day["nav"] == pytest.approx(
                day["cash"] + day["dividend_receivable"] + day["market_value"],
                rel=1e-6,
            )
            assert isinstance(day["valuation_reliable"], bool)
            assert isinstance(day["risk"]["status"], str)

    @real_pkg_needed
    def test_export_evidence_untouched(self, pkg):
        """审计原件保持不动：view 派生不改变 export_evidence 输出。"""
        led = _run_window(pkg, _cfg("h1-audit"))
        before = copy.deepcopy(led.export_evidence())
        led.export_view()
        assert led.export_evidence() == before

    @real_pkg_needed
    def test_view_matches_evidence_builder(self, pkg):
        """export_view == build_view_from_evidence(export_evidence())（同一入口）。"""
        led = _run_window(pkg, _cfg("h1-same-entry"))
        assert led.export_view() == build_view_from_evidence(led.export_evidence())


class TestViewScenarios:
    @real_pkg_needed
    def test_no_order_day(self, pkg):
        """无订单日：days[].orders 为空列表（04-25/26 持有日无交易）。"""
        view = _run_window(pkg, _cfg("h1-noorder")).export_view()
        by_date = {d["date"]: d for d in view["days"]}
        assert by_date["2024-04-25"]["orders"] == []
        assert by_date["2024-04-26"]["orders"] == []
        assert by_date["2024-04-22"]["orders"]  # 建仓日有单

    @real_pkg_needed
    def test_partial_fill_three_state_qty(self, pkg):
        """部分成交：qty 三态 target/filled/remaining 精确呈现（现金约束）。"""
        # 04-22 开盘 ≈114.9：1 手 ≈11491 元。现金 12000 → 目标 200 份
        # （2 手）可负担 1 手：成交 100、剩余 100 转 expired_unfilled
        led = _run_window(pkg, _cfg("h1-partial", initial_cash=12000.0), buy_qty=200)
        view = led.export_view()
        o = view["days"][0]["orders"][0]
        assert o["status"] == "expired_unfilled"
        assert o["qty_target"] == 200
        assert o["qty_filled"] == 100
        assert o["qty_remaining"] == 100
        assert o["fills"] and o["fills"][0]["quantity"] == 100
        assert o["fills"][0]["price"] == pytest.approx(o["avg_fill_price"])
        assert o["fees"] > 0

    @real_pkg_needed
    def test_rejected_order_reason(self, pkg):
        """拒单：status=rejected + reject_reason 呈现（同窗口无持仓卖出）。"""
        led = _run_window(pkg, _cfg("h1-reject"))
        led.manual_sell(date(2024, 4, 23), "510300.SH", 100,
                        reason="r", requested_by="u")  # 无持仓 → no_position
        view = led.export_view()
        rejects = [
            o for d in view["days"] for o in d["orders"]
            if o["status"] == "rejected"
        ]
        assert rejects
        assert rejects[0]["reject_reason"] == "no_position"
        assert rejects[0]["qty_filled"] == 0
        assert rejects[0]["qty_remaining"] == rejects[0]["qty_target"]

    @real_pkg_needed
    def test_dividend_receivable_to_paid(self, pkg):
        """分红应收→到账逐日呈现（G 轮同源窗口）：04-24 应收 150（现金不动）、
        04-29 应收归零现金 +150。"""
        led = _run_window(pkg, _cfg("h1-div"))
        view = led.export_view()
        by_date = {d["date"]: d for d in view["days"]}
        assert by_date["2024-04-23"]["dividend_receivable"] == 0.0  # record 日
        ex = by_date["2024-04-24"]
        assert ex["dividend_receivable"] == pytest.approx(150.0)
        pay = by_date["2024-04-29"]
        assert pay["dividend_receivable"] == pytest.approx(0.0)
        assert pay["cash"] == pytest.approx(
            by_date["2024-04-26"]["cash"] + 150.0
        )
        # 顶层三段式分红记录
        rec = view["dividends"][0]
        assert rec["stage"] == "paid"
        assert rec["entitlement_amount"] == pytest.approx(150.0)
        assert rec["record_date"] == "2024-04-23"

    @real_pkg_needed
    def test_positions_fields(self, pkg):
        """逐日持仓字段：数量/成本/可卖/标记/市值/陈旧度。"""
        view = _run_window(pkg, _cfg("h1-pos")).export_view()
        by_date = {d["date"]: d for d in view["days"]}
        pos_ex = by_date["2024-04-24"]["positions"]
        assert len(pos_ex) == 1 and pos_ex[0]["symbol"] == SYM
        p = pos_ex[0]
        assert p["qty"] == 100.0
        assert p["avg_cost"] > 0
        assert p["last_mark"] > 0 and p["mark_source"] == "eod_close"
        assert p["market_value"] == pytest.approx(p["qty"] * p["last_mark"], rel=1e-6)
        assert p["stale_days"] == 0
        assert p["available_qty"] == 100.0  # 04-22 买入，T+0 国债 ETF


class TestViewStrictnessAndFormat:
    @real_pkg_needed
    def test_missing_field_raises_no_silent_zero(self, pkg):
        """字段缺失 → ViewBuildError 显式报错（含 day/字段），不静默填零。"""
        led = _run_window(pkg, _cfg("h1-strict"))
        evidence = led.export_evidence()
        tampered = copy.deepcopy(evidence)
        tampered["equity"][1].pop("dividend_receivable")
        with pytest.raises(ViewBuildError, match="dividend_receivable"):
            build_view_from_evidence(tampered)
        tampered2 = copy.deepcopy(evidence)
        tampered2["equity"][2]["positions"][SYM].pop("stale_days")
        with pytest.raises(ViewBuildError, match="stale_days"):
            build_view_from_evidence(tampered2)
        with pytest.raises(ViewBuildError):
            build_view_from_evidence({"session": {}})  # 缺 orders/equity

    def test_identify_export_format_rules(self, pkg):
        """判别规则：view / evidence / legacy_fixture / unknown。"""
        led = _run_window(pkg, _cfg("h1-format"))
        assert identify_export_format(led.export_view()) == "view"
        assert identify_export_format(led.export_evidence()) == "evidence"
        assert identify_export_format({"day_summaries": [], "equity": []}) == "legacy_fixture"
        assert identify_export_format({"foo": 1}) == "unknown"
        assert identify_export_format([1, 2]) == "unknown"

    @real_pkg_needed
    def test_risk_fields_present(self, pkg):
        """风险字段：逐日 status/HWM/当日触发 + 顶层 risk_events（最终态）。"""
        # 逐日走到 04-26 后注入亏损，04-29 触发损失线（20000×30% → 阈 14000）
        led = R01Ledger(pkg, _cfg("h1-risk"))
        o = led.submit_order(date(2024, 4, 22), SYM, "buy", 100)
        bars = pkg.load_date(date(2024, 4, 22))
        led._validate_and_execute(o, date(2024, 4, 22), bars, DaySummary(trade_date="2024-04-22"))
        led._eod(date(2024, 4, 22), bars, DaySummary(trade_date="2024-04-22"))
        for d in [date(2024, 4, 23), date(2024, 4, 24), date(2024, 4, 25), date(2024, 4, 26)]:
            led.run_day(d, None)
        led.cash -= 12000.0  # 工程注记：模拟击穿损失线
        led.run_day(date(2024, 4, 29), None)
        view = led.export_view()
        by_date = {d["date"]: d for d in view["days"]}
        assert by_date["2024-04-29"]["risk"]["status"] == "paused"
        assert by_date["2024-04-29"]["risk"]["triggered_today"]
        assert view["risk_events"]
        assert view["risk_state"]["status"] == "paused"

    @real_pkg_needed
    def test_h1ac01_daily_risk_from_snapshot(self, pkg):
        """H1-AC01：逐日风险态/HWM 取当日快照，禁止最终态补历史。

        验收场景复现：损失线设 100 元（独立工程探针口径，不改 30% 规则），
        五日窗口内触发——触发前/触发日/触发后逐日断言 view 与原生 equity
        逐日一致；HWM 只在新高日上移。
        """
        cfg = _cfg("h1-ac01", loss_line_amount=100.0, drawdown_pct=0.99)
        led = R01Ledger(pkg, cfg)
        o = led.submit_order(date(2024, 4, 22), SYM, "buy", 100)
        bars = pkg.load_date(date(2024, 4, 22))
        led._validate_and_execute(o, date(2024, 4, 22), bars, DaySummary(trade_date="2024-04-22"))
        led._eod(date(2024, 4, 22), bars, DaySummary(trade_date="2024-04-22"))
        for d in [date(2024, 4, 23), date(2024, 4, 24), date(2024, 4, 25), date(2024, 4, 26), date(2024, 4, 29)]:
            led.run_day(d, None)
        view = led.export_view()
        # 逐日：view risk == 原生 equity 快照（status + HWM），非最终态
        for day, snap in zip(view["days"], led.equity, strict=True):
            assert day["risk"]["status"] == snap["risk_status"], day["date"]
            assert day["risk"]["high_water_mark"] == pytest.approx(
                snap["high_water_mark"], abs=1e-6
            ), day["date"]
        # 存在状态切换（验收：触发前 active → 触发后 paused）
        statuses = [d["risk"]["status"] for d in view["days"]]
        assert "active" in statuses and "paused" in statuses
        first_paused = statuses.index("paused")
        assert statuses[:first_paused] == ["active"] * first_paused
        # 触发日有 triggered_today；触发前无
        assert not view["days"][first_paused - 1]["risk"]["triggered_today"]
        assert view["days"][first_paused]["risk"]["triggered_today"]
        # HWM 只增不减（逐日单调非降）
        hwms = [d["risk"]["high_water_mark"] for d in view["days"]]
        assert hwms == sorted(hwms)
        # 顶层仍是最终态
        assert view["risk_state"]["status"] == statuses[-1]

    @real_pkg_needed
    def test_h1ac01_missing_snapshot_fields_rejected(self, pkg):
        """快照缺 risk_status/high_water_mark → 显式拒绝，不用最终态补历史。"""
        view_src = _run_window(pkg, _cfg("h1-ac01-strict"))
        evidence = view_src.export_evidence()
        tampered = copy.deepcopy(evidence)
        tampered["equity"][1].pop("risk_status")
        with pytest.raises(Exception, match="risk_status"):
            from backend.services.simulation.replay.r01_ledger import (
                build_view_from_evidence,
            )
            build_view_from_evidence(tampered)
        tampered2 = copy.deepcopy(evidence)
        tampered2["equity"][1].pop("high_water_mark")
        with pytest.raises(Exception, match="high_water_mark"):
            build_view_from_evidence(tampered2)

    @real_pkg_needed
    def test_h1ac02_last_mark_matches_native(self, pkg):
        """H1-AC02：持仓收盘标记字段=last_mark，两日期与原生一致
        （验收用例 04-24=113.031、04-29=110.685），页面消费字段直接断言。"""
        view = _run_window(pkg, _cfg("h1-ac02")).export_view()
        by_date = {d["date"]: d for d in view["days"]}
        # 验收引用的两个日期（与原生 evidence 收盘一致，不"缺失"）
        p24 = by_date["2024-04-24"]["positions"][0]
        p29 = by_date["2024-04-29"]["positions"][0]
        assert "last_mark" in p24 and "mark" not in p24  # 字段合同统一
        assert p24["last_mark"] == pytest.approx(113.031, abs=1e-3)
        assert p29["last_mark"] == pytest.approx(110.685, abs=1e-3)
        assert p24["mark_source"] == "eod_close" and p29["mark_source"] == "eod_close"
        # 全窗口逐日：view last_mark == 原生快照 close
        native = _run_window(pkg, _cfg("h1-ac02-native")).equity
        for day, snap in zip(view["days"], native, strict=True):
            for p in day["positions"]:
                assert p["last_mark"] == pytest.approx(
                    snap["positions"][p["symbol"]]["close"], abs=1e-9
                ), day["date"]

    def test_h1ac02_stale_missing_semantics_preserved(self, tmp_path):
        """陈旧/缺失收盘标记语义保留：carry_forward/unavailable 不伪造。"""
        from backend.services.simulation.replay.etf_input_package import (
            build_fixture_package,
        )
        from backend.services.simulation.replay.r01_ledger import R01Ledger, R01LedgerConfig

        fx = build_fixture_package(tmp_path / "fx")
        led = R01Ledger(fx, R01LedgerConfig(
            group="P0", strategy_id="fixture-h1-ac02-stale", strategy_version=1,
            execution_attempt_id=1, initial_cash=30000.0, slippage_bps=0.0))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 9))
        # 缺行情日：bars 空 → carry_forward
        led._eod(date(2025, 9, 11), {}, DaySummary(trade_date="2025-09-11"))
        view = led.export_view()
        by_date = {d["date"]: d for d in view["days"]}
        p_carry = by_date["2025-09-11"]["positions"][0]
        assert p_carry["mark_source"] == "carry_forward"
        assert p_carry["stale_days"] == 1
        assert p_carry["last_mark"] == pytest.approx(
            by_date["2025-09-10"]["positions"][0]["last_mark"]
        )  # 沿用最近有效市价
