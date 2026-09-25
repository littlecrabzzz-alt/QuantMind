"""R01P0-F3E3 修复验证（F3R 必修 1/2 归 p03 部分）。

- 必修1：缺行情估值回退残留——首持仓日即缺行情（无任何有效市价）时
  禁止回退成本价：mark=0+unavailable+快照不可信；连续缺日 staleness
  下风险线按 carry nav 评估且快照携带不可信旗标
- 必修2：版本身份统一——CONTRACT_VERSIONS=v3/v3；旧 v2 checkpoint
  读取显式拒绝（不静默混用）
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import build_fixture_package
from backend.services.simulation.replay.r01_ledger import (
    CONTRACT_VERSIONS,
    CheckpointConfigMismatch,
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
)


def _config(**kw):
    kw.setdefault("group", "P0")
    kw.setdefault("strategy_id", "fixture-f3-demo")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 30000.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


class TestNoCostFallbackResidue:
    def test_first_held_day_missing_quote_never_uses_cost(self, tmp_path):
        """首持仓日即缺行情：无任何有效市价 → mark=0（非成本）、
        mark_source=unavailable、快照 valuation_reliable=False。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config())
        d = date(2025, 9, 10)
        bars = pkg.load_date(d)
        # 买入成交（当日有行情），但 EOD 传空 bars：首持仓日即缺行情
        order = led.submit_order(d, "510300.SH", "buy", 1000)
        led._validate_and_execute(order, d, bars, DaySummary(trade_date=d.isoformat()))
        led._eod(d, {}, DaySummary(trade_date=d.isoformat()))
        snap = led.equity[-1]
        pos_out = snap["positions"]["510300.SH"]
        assert pos_out["mark_source"] == "unavailable"
        assert pos_out["close"] == 0.0
        assert pos_out["close"] != pytest.approx(led.positions["510300.SH"].avg_cost)
        assert pos_out["stale_days"] == 1
        assert snap["valuation_reliable"] is False
        # nav 不含该持仓估值（cash-only），且不可信旗标显式暴露
        assert snap["market_value"] == pytest.approx(0.0)
        assert snap["nav"] == pytest.approx(snap["cash"])

    def test_consecutive_missing_days_carry_and_risk_line(self, tmp_path):
        """连续缺日：mark 沿用最近收盘；超阈值快照不可信；风险线仍按
        carry nav 评估（事件可触发），但快照携旗标供上层判 blocked。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        led = R01Ledger(pkg, _config(initial_cash=15000.0, drawdown_pct=0.99))
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.95}, signal_date=date(2025, 9, 9))
        led.cash -= 4800.0  # 工程注记：模拟亏损贴近损失线（阈 10500）
        d = date(2025, 9, 11)
        for _ in range(6):
            led._eod(d, {}, DaySummary(trade_date=d.isoformat()))  # 连续缺行情
            d = date.fromordinal(d.toordinal() + 1)
        snaps = led.equity[-6:]
        # carry nav 逐日一致（无行情变化），staleness 递增
        assert all(s["positions"]["510300.SH"]["mark_source"] == "carry_forward" for s in snaps)
        assert snaps[0]["positions"]["510300.SH"]["stale_days"] == 1
        assert snaps[-1]["positions"]["510300.SH"]["stale_days"] == 6
        # 超 stale_mark_limit(5) 后快照不可信
        assert [s["valuation_reliable"] for s in snaps] == [True, True, True, True, True, False]
        # 风险线在 carry nav 上评估：若 carry nav 在阈下则触发（事件含日期）
        nav_last = snaps[-1]["nav"]
        if nav_last <= 10500.0:
            assert led.risk.status == "paused"
            assert any(
                e.date == snaps[-1]["trade_date"] for e in led.risk.events.values()
            ) or led.risk.has_unconfirmed_trigger

    def test_no_avg_cost_valuation_fallback_in_owns_files(self):
        """grep 级断言：owns 文件中不存在 avg_cost 估值回退残留
        （合法用途=移动加权成本计算/记录字段/成交归因，非估值）。"""
        import re
        from pathlib import Path

        base = Path(__file__).resolve().parents[1] / "simulation" / "replay"
        allowed_patterns = (
            "avg_cost =(",  # 移动加权成本计算
            "avg_cost_before",  # 卖出归因
            "avg_cost_after",  # 事件记录
            '"avg_cost"',  # dict 字段
            "avg_cost=float(",  # from_dict
            "avg_cost: float = 0.0",  # dataclass 字段
            "self.avg_cost, 6)",  # to_dict
            "round(self.avg_cost",  # to_dict
            "pos.avg_cost /= ",  # 份额调整成本基准
            "costs[sym]",  # 复算成本表
            "cost = costs",  # 复算
        )
        for f in base.glob("*.py"):
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if "avg_cost" in line and "fallback" not in line:
                    if any(p in line for p in allowed_patterns):
                        continue
                    if re.search(r"close\s*=.*avg_cost|mark\s*=.*avg_cost|nav.*avg_cost", line):
                        pytest.fail(f"估值回退残留: {f.name}:{i}: {line.strip()}")


class TestVersionIdentity:
    def test_contract_versions_are_v3(self):
        assert CONTRACT_VERSIONS == {
            "ledger_contract": "v3",
            "etf_input_package_schema": "v3",
        }

    def test_v2_checkpoint_rejected_not_silently_mixed(self, tmp_path):
        """旧 v2 checkpoint（合同版本 v2）：显式拒绝，错误信息含双方版本。"""
        pkg = build_fixture_package(tmp_path / "pkg")
        cfg = _config()
        led = R01Ledger(pkg, cfg)
        led.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 9))
        cp = led.export_checkpoint()
        # 篡改为旧 v2 版本身份（模拟 F2 时代 checkpoint）
        cp["contract_versions"] = {
            "ledger_contract": "v2",
            "etf_input_package_schema": "v2",
        }
        with pytest.raises(CheckpointConfigMismatch) as ei:
            R01Ledger.restore(pkg, cfg, cp)
        msg = str(ei.value)
        assert "v2" in msg and "v3" in msg  # 双方版本都在错误信息
        # 缺失字段路径（更旧快照）同样拒绝
        cp2 = led.export_checkpoint()
        cp2.pop("contract_versions")
        with pytest.raises(CheckpointConfigMismatch, match="contract_versions"):
            R01Ledger.restore(pkg, cfg, cp2)
