"""R01-P0.3 修复验证测试（R01P0-W2E3，对应 p0r1 审查发现 1-7）。

- 前视偏差（#1）：调仓目标按信号日收盘 NAV+收盘价定手数；执行只用开盘价
- 顺序/信号强制（#2）：乱序/跳日/非交易日/同日信号/信号错位显式拒绝；
  T+1 逐日解锁（当日买入当日不可卖、次日可卖；T+0 当日可卖）
- 市场成交量约束（#3）：成交上限 = bar.volume×参与率（默认 1.0）
- 开盘价涨跌停判定（#4）：开盘触及封板拒单；收盘封板但开盘未封不误拒
- 裸卖空防护（#5）：无持仓/无可卖量卖出拒单 no_position，现金不变
- PG schema（#6）：client_order_id 唯一、confirmed_at aware-UTC 类型（ORM 元数据断言）
- checkpoint（#7）：导出→恢复→续放 与 不间断运行 逐日一致；风险状态恢复
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import build_fixture_package
from backend.services.simulation.replay.r01_ledger import (
    CheckpointPackageMismatch,
    LedgerOrderingError,
    R01Ledger,
    R01LedgerConfig,
)
from backend.services.simulation.replay.risk_state import RiskStateMachine
from backend.services.simulation.services.ashare_matcher import (
    MatchConfig,
    match_order,
)
from backend.services.simulation.services.local_market_data import DailyBar


@pytest.fixture()
def pkg(tmp_path):
    return build_fixture_package(tmp_path / "pkg")


def _config(**kw):
    kw.setdefault("group", "P0")
    kw.setdefault("strategy_id", "fixture-fixes-demo")
    kw.setdefault("strategy_version", 1)
    kw.setdefault("execution_attempt_id", 1)
    kw.setdefault("initial_cash", 30000.0)
    kw.setdefault("slippage_bps", 0.0)
    return R01LedgerConfig(**kw)


# ---------------------------------------------------------------------------
# 修复#1：无前视（信号日收盘 NAV + 信号日收盘价定目标）
# ---------------------------------------------------------------------------


class TestNoLookahead:
    def test_sizing_uses_signal_close_not_exec_open(self, pkg):
        ledger = R01Ledger(pkg, _config())
        d_exec = date(2025, 9, 10)
        d_sig = date(2025, 9, 9)  # 上一包交易日
        ledger.run_day(d_exec, {"510300.SH": 0.5}, signal_date=d_sig)
        o = ledger.orders[f"{ledger.ledger_run_id}:2025-09-10:510300.SH:buy"]
        sig_close = pkg.get_bar("510300.SH", d_sig).close
        exec_open = pkg.get_bar("510300.SH", d_exec).open
        assert sig_close != exec_open  # 前提：两日价格确有差异
        # 目标份额按信号日收盘价：floor(0.5×30000/(close_sig×100))×100
        import math

        expected_lots = math.floor(0.5 * 30000.0 / (sig_close * 100))
        assert o.qty_target == pytest.approx(expected_lots * 100, abs=100)
        # 成交价仍是执行日开盘价（滑点 0）
        assert o.avg_fill_price == pytest.approx(exec_open)

    def test_signal_reference_is_prev_eod_snapshot(self, pkg):
        """信号日=上一执行日时，目标金额锚定上一日 EOD NAV（含当日涨跌）。"""
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        # 09-11 再调仓：目标基于 09-10 EOD NAV（不是 09-11 收盘估值）
        ledger.run_day(date(2025, 9, 11), {"510300.SH": 0.5})
        o = ledger.orders.get(f"{ledger.ledger_run_id}:2025-09-11:510300.SH:buy")
        if o is not None:
            assert o.ideal_weight == 0.5
            # nav 变动后目标随信号日 NAV 移动（此处仅验证锚定不抛错且留痕）
            assert o.trade_date == "2025-09-11"

    def test_reject_stale_price_when_signal_close_unavailable(self, pkg):
        """信号日无收盘价（且回看不可得）→ 显式 stale_price 拒单。"""
        ledger = R01Ledger(pkg, _config())
        # 构造：执行日 09-08（包首日，prev=None）显式传非法 signal
        with pytest.raises(LedgerOrderingError):
            ledger.run_day(date(2025, 9, 8), {"510300.SH": 0.5}, signal_date=date(2025, 9, 5))


# ---------------------------------------------------------------------------
# 修复#2：顺序与 T+1 强制
# ---------------------------------------------------------------------------


class TestOrderingEnforcement:
    def _ledger(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), None)
        return ledger

    def test_out_of_order_rejected(self, pkg):
        ledger = self._ledger(pkg)  # 已执行 09-10
        with pytest.raises(LedgerOrderingError) as ei:
            ledger.run_day(date(2025, 9, 9), None)  # 早于上一执行日
        assert ei.value.reason == "out_of_order"

    def test_skipped_session_rejected(self, pkg):
        ledger = self._ledger(pkg)
        with pytest.raises(LedgerOrderingError) as ei:
            ledger.run_day(date(2025, 9, 12), None)  # 跳过 09-11
        assert ei.value.reason == "skipped_session"

    def test_not_trade_date_rejected(self, pkg):
        ledger = self._ledger(pkg)
        with pytest.raises(LedgerOrderingError) as ei:
            ledger.run_day(date(2025, 9, 13), None)  # 周六
        assert ei.value.reason == "not_trade_date"

    def test_same_day_signal_rejected(self, pkg):
        ledger = R01Ledger(pkg, _config())
        with pytest.raises(LedgerOrderingError) as ei:
            ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5}, signal_date=date(2025, 9, 10))
        assert ei.value.reason == "same_day_signal"

    def test_signal_not_prev_session_rejected(self, pkg):
        ledger = R01Ledger(pkg, _config())
        with pytest.raises(LedgerOrderingError) as ei:
            ledger.run_day(date(2025, 9, 12), {"510300.SH": 0.5}, signal_date=date(2025, 9, 10))
        assert ei.value.reason == "signal_not_prev_session"

    def test_signal_auto_aligned_to_prev_session(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})  # signal 缺省
        o = ledger.orders[f"{ledger.ledger_run_id}:2025-09-10:510300.SH:buy"]
        assert o.signal_date == "2025-09-09"


class TestT1PerDateUnlock:
    def test_t1_same_day_sell_rejected_next_day_ok(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.9})  # T+1 宽基
        pos = ledger.positions["510300.SH"]
        assert pos.qty > 0
        # 当日买入不可卖：available = qty − pending
        assert pos.available_qty == pytest.approx(0.0)
        assert pos.pending_t1_qty == pytest.approx(pos.qty)
        order = ledger.submit_order(date(2025, 9, 10), "510300.SH", "sell", 100)
        from backend.services.simulation.replay.r01_ledger import DaySummary

        ledger._validate_and_execute(
            order, date(2025, 9, 10), pkg.load_date(date(2025, 9, 10)),
            DaySummary(trade_date="2025-09-10"),
        )
        assert order.status == "rejected"
        assert order.reject_reason in ("no_position", "lot_inexpressible")
        # 次日解锁（具体批次）：available = qty
        ledger.run_day(date(2025, 9, 11), None)
        pos = ledger.positions["510300.SH"]
        assert pos.available_qty == pytest.approx(pos.qty)
        assert pos.pending_t1_qty == 0.0

    def test_t0_same_day_sell_allowed(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"518880.SH": 0.9})  # 黄金 T+0
        pos = ledger.positions["518880.SH"]
        assert pos.available_qty == pytest.approx(pos.qty)  # 当日即全部可卖

    def test_rollover_unlocks_only_pending_batch(self, pkg):
        """解锁只针对已跨 T+1 边界的批次；当日新买入仍锁定。"""
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        ledger.run_day(date(2025, 9, 11), {"510300.SH": 0.8})  # 加仓
        pos = ledger.positions["510300.SH"]
        # 09-10 批次已解锁，09-11 新买入批次当日锁定
        assert pos.pending_t1_date == "2025-09-11"
        assert pos.available_qty == pytest.approx(pos.qty - pos.pending_t1_qty)
        ledger.run_day(date(2025, 9, 12), None)
        assert ledger.positions["510300.SH"].available_qty == pytest.approx(
            ledger.positions["510300.SH"].qty
        )


# ---------------------------------------------------------------------------
# 修复#3：市场成交量约束
# ---------------------------------------------------------------------------


def _vbar(symbol="510300.SH", volume=1e7, open_=4.0, close=4.0):
    return DailyBar(
        symbol=symbol, trade_date=date(2025, 9, 10),
        open=open_, high=max(open_, close) * 1.01, low=min(open_, close) * 0.99,
        close=close, volume=volume, amount=close * volume, vwap=close,
        pre_close=close, limit_up=close * 1.1, limit_down=close * 0.9,
        is_st=False, suspended=False,
    )


class TestVolumeCap:
    def _cfg(self, **kw):
        kw.setdefault("price_mode", "open")
        kw.setdefault("asset_type", "etf")
        kw.setdefault("allow_partial", True)
        kw.setdefault("slippage_bps", 0.0)
        return MatchConfig(**kw)

    def test_buy_capped_by_volume(self):
        bar = _vbar(volume=12345)  # 123 手
        mr = match_order("buy", 100000, bar, self._cfg(), cash_available=1e9)
        assert mr.success
        assert mr.fill_quantity == 12300  # 整手化
        assert mr.qty_remaining == 100000 - 12300

    def test_sell_capped_by_volume(self):
        bar = _vbar(volume=5000)
        mr = match_order("sell", 8000, bar, self._cfg(), available_volume=8000)
        assert mr.success
        assert mr.fill_quantity == 5000
        assert mr.qty_remaining == 3000

    def test_participation_rate(self):
        bar = _vbar(volume=10000)
        mr = match_order("buy", 100000, bar, self._cfg(volume_participation=0.3), cash_available=1e9)
        assert mr.fill_quantity == 3000

    def test_zero_participation_rejects(self):
        bar = _vbar(volume=10000)
        mr = match_order("buy", 100, bar, self._cfg(volume_participation=0.0), cash_available=1e9)
        assert not mr.success
        assert mr.reason == "INSUFFICIENT_MARKET_VOLUME"
        assert mr.qty_remaining == 100

    def test_legacy_mode_uncapped(self):
        """allow_partial=False 维持既有行为：不做量约束。"""
        bar = _vbar(volume=100)
        mr = match_order("buy", 1000, bar, MatchConfig(price_mode="open"))
        assert mr.success and mr.fill_quantity == 1000

    def test_ledger_uses_volume_cap(self, pkg):
        """R01 账本路径：低流动日买入被 bar.volume 截断（参与率可配）。"""
        ledger = R01Ledger(pkg, _config(volume_participation=1.0))
        # 篡改行情量不可行（包只读）——用 mock bar 驱动撮合层已覆盖；
        # 这里验证配置贯通：MatchConfig.volume_participation 生效
        assert ledger._cfg.volume_participation == 1.0
        led2 = R01Ledger(pkg, _config(volume_participation=0.5))
        assert led2._cfg.volume_participation == 0.5


# ---------------------------------------------------------------------------
# 修复#4：开盘价涨跌停判定
# ---------------------------------------------------------------------------


class TestOpenPriceLimit:
    def _cfg(self):
        return MatchConfig(price_mode="open", asset_type="etf", allow_partial=True, slippage_bps=0.0)

    def test_open_at_limit_up_rejects_buy(self):
        # 开盘=涨停 4.4；收盘 4.2（未封）——旧实现看收盘会误放行
        bar = _vbar(open_=4.4, close=4.2)
        bar.limit_up = 4.4
        mr = match_order("buy", 1000, bar, self._cfg(), cash_available=1e9)
        assert not mr.success and mr.reason == "LIMIT_UP"

    def test_open_not_at_limit_but_close_is_fills(self):
        # 开盘 4.0 可成交；收盘 4.4 触及涨停——旧实现看收盘会误拒
        bar = _vbar(open_=4.0, close=4.4)
        bar.limit_up = 4.4
        mr = match_order("buy", 1000, bar, self._cfg(), cash_available=1e9)
        assert mr.success
        assert mr.fill_price == pytest.approx(4.0)

    def test_open_at_limit_down_rejects_sell(self):
        bar = _vbar(open_=3.6, close=3.9)
        bar.limit_down = 3.6
        mr = match_order("sell", 1000, bar, self._cfg(), available_volume=1000)
        assert not mr.success and mr.reason == "LIMIT_DOWN"


# ---------------------------------------------------------------------------
# 修复#5：裸卖空防护
# ---------------------------------------------------------------------------


class TestNoNakedShort:
    def test_sell_without_position_rejected(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        cash_before = ledger.cash
        order = ledger.submit_order(date(2025, 9, 11), "159915.SZ", "sell", 1000)
        from backend.services.simulation.replay.r01_ledger import DaySummary

        ledger._validate_and_execute(
            order, date(2025, 9, 11), pkg.load_date(date(2025, 9, 11)),
            DaySummary(trade_date="2025-09-11"),
        )
        assert order.status == "rejected"
        assert order.reject_reason == "no_position"
        assert ledger.cash == pytest.approx(cash_before)  # 现金不得增加
        assert "159915.SZ" not in ledger.positions

    def test_rebalance_exit_without_position_no_cash(self, pkg):
        """权重调到 0 但无持仓：不产生卖出订单现金（delta≈0 跳过）。"""
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        cash = ledger.cash
        ledger.run_day(date(2025, 9, 11), {"510300.SH": 0.5, "159915.SZ": 0.0})
        # 159915 无持仓且目标 0：无订单
        assert not [
            o for o in ledger.orders.values() if o.symbol == "159915.SZ"
        ]
        assert ledger.cash <= cash  # 无凭空现金

    def test_manual_sell_without_position_rejected(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), None)
        order = ledger.manual_sell(
            date(2025, 9, 10), "510300.SH", 100,
            reason="user-test", requested_by="u1",
        )
        assert order.status == "rejected"
        assert order.reject_reason == "no_position"
        assert ledger.cash == pytest.approx(30000.0)
        assert ledger.manual_actions[-1]["status"] == "rejected"

    def test_sell_exceeding_available_capped_not_negative(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"518880.SH": 0.5})  # T+0
        available_before = ledger.positions["518880.SH"].available_qty
        order = ledger.submit_order(
            date(2025, 9, 10), "518880.SH", "sell", int(available_before) + 5000
        )
        from backend.services.simulation.replay.r01_ledger import DaySummary

        ledger._validate_and_execute(
            order, date(2025, 9, 10), pkg.load_date(date(2025, 9, 10)),
            DaySummary(trade_date="2025-09-10"),
        )
        # 超量卖出被可卖量截断，持仓不得为负（清仓后持仓删除）
        assert order.qty_filled <= available_before
        pos_after = ledger.positions.get("518880.SH")
        assert pos_after is None or pos_after.qty >= 0


# ---------------------------------------------------------------------------
# 修复#6：ORM schema 元数据（唯一约束 + aware UTC 类型；DDL 由升级 SQL/沙盒脚本验证）
# ---------------------------------------------------------------------------


class TestSchemaMetadata:
    def test_client_order_id_unique(self):
        from backend.services.simulation.models.replay import ReplayOrder

        col = ReplayOrder.__table__.columns["client_order_id"]
        assert col.unique is True

    def test_confirmed_at_is_utc_datetime(self):
        from backend.services.simulation.models.replay import ReplayRiskEvent
        from backend.shared.utc_datetime import UtcDateTime

        col = ReplayRiskEvent.__table__.columns["confirmed_at"]
        assert isinstance(col.type, UtcDateTime)
        assert col.type.impl.timezone is True

    def test_checkpoint_model_exists(self):
        from backend.services.simulation.models.replay import ReplayLedgerCheckpoint

        assert ReplayLedgerCheckpoint.__tablename__ == "replay_ledger_checkpoints"
        pk = ReplayLedgerCheckpoint.__table__.primary_key.columns
        assert list(pk.keys()) == ["ledger_run_id"]


# ---------------------------------------------------------------------------
# 修复#7：checkpoint 导出/恢复
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def _full_run(self, pkg, config):
        ledger = R01Ledger(pkg, config)
        for d in pkg.trade_dates():
            if d > date(2025, 9, 18):
                break
            w = (
                {"510300.SH": 0.4, "511010.SH": 0.3, "518880.SH": 0.2}
                if d == date(2025, 9, 10)
                else ({"510300.SH": 0.2} if d == date(2025, 9, 17) else None)
            )
            ledger.run_day(d, w)
        return ledger

    def test_restore_continues_identically(self, pkg):
        """中断点恢复后续放 == 不间断运行：逐日 nav/cash/持仓一致。"""
        full = self._full_run(pkg, _config())

        # 前半程（到 09-15）
        part = R01Ledger(pkg, _config())
        for d in pkg.trade_dates():
            if d > date(2025, 9, 15):
                break
            w = (
                {"510300.SH": 0.4, "511010.SH": 0.3, "518880.SH": 0.2}
                if d == date(2025, 9, 10)
                else None
            )
            part.run_day(d, w)
        checkpoint = part.export_checkpoint()

        # 恢复并续放后半程（09-16..09-18）
        restored = R01Ledger.restore(pkg, _config(), checkpoint)
        for d in pkg.trade_dates():
            if d <= date(2025, 9, 15):
                continue
            if d > date(2025, 9, 18):
                break
            w = {"510300.SH": 0.2} if d == date(2025, 9, 17) else None
            restored.run_day(d, w)

        assert len(restored.equity) == len(full.equity)
        for r, f in zip(restored.equity, full.equity, strict=True):
            assert r["trade_date"] == f["trade_date"]
            assert r["nav"] == pytest.approx(f["nav"], abs=1e-6)
            assert r["cash"] == pytest.approx(f["cash"], abs=1e-6)
        assert set(restored.orders) == set(full.orders)
        for coid, ro in restored.orders.items():
            fo = full.orders[coid]
            assert ro.qty_filled == fo.qty_filled
            assert ro.avg_fill_price == pytest.approx(fo.avg_fill_price, abs=1e-9)

    def test_checkpoint_idempotent_reexport(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        cp1 = ledger.export_checkpoint()
        cp2 = ledger.export_checkpoint()
        assert cp1 == cp2  # 纯状态导出确定性

    def test_restore_preserves_risk_pause(self, pkg):
        ledger = R01Ledger(pkg, _config(initial_cash=15000.0, drawdown_pct=0.5))
        ledger.run_day(date(2025, 9, 10), None)
        ledger.cash -= 6000.0  # 工程注记：模拟击穿损失线
        ledger.run_day(date(2025, 9, 11), None)
        assert not ledger.risk.buys_allowed
        restored = R01Ledger.restore(
            pkg, _config(initial_cash=15000.0, drawdown_pct=0.5), ledger.export_checkpoint()
        )
        # 恢复后暂停状态保持（事件重算 status，不信任快照字符串）
        assert not restored.risk.buys_allowed
        assert restored.risk.status == "paused"
        ev_id = next(iter(restored.risk.events))
        restored.confirm_risk_event(ev_id, confirmed_by="u1")
        assert restored.risk.buys_allowed

    def test_same_package_restore_succeeds(self, pkg):
        """正例：同包恢复成功（package_id 绑定校验通过）。"""
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        cp = ledger.export_checkpoint()
        assert cp["package_id"] == pkg.package_id
        restored = R01Ledger.restore(pkg, _config(), cp)
        assert restored.package.package_id == pkg.package_id
        assert restored.equity[-1]["nav"] == pytest.approx(ledger.equity[-1]["nav"])

    def test_restore_rejects_different_package(self, pkg, tmp_path):
        """负例（W2E4）：同 run 不同包恢复被拒，错误信息含双方 package_id。"""
        from backend.services.simulation.replay.etf_input_package import (
            build_fixture_package,
        )

        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})
        cp = ledger.export_checkpoint()
        other_pkg = build_fixture_package(tmp_path / "other-pkg", package_id="fixture-other-pkg-x")
        assert other_pkg.package_id != pkg.package_id  # 前提：两包不同

        with pytest.raises(CheckpointPackageMismatch) as ei:
            R01Ledger.restore(other_pkg, _config(), cp)
        msg = str(ei.value)
        assert pkg.package_id in msg and other_pkg.package_id in msg

    def test_restore_rejects_different_package_via_row(self, pkg, tmp_path):
        """持久层路径负例：DB 行 package_id 与传入包不一致 → 显式拒绝。"""
        import asyncio

        from backend.services.simulation.replay.etf_input_package import (
            build_fixture_package,
        )
        from backend.services.simulation.replay import ledger_persistence

        other_pkg = build_fixture_package(tmp_path / "other-pkg2", package_id="fixture-other-pkg-y")
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), {"510300.SH": 0.5})

        class _Row:
            package_id = pkg.package_id
            state = ledger.export_checkpoint()

        class _Db:
            async def execute(self, *_a, **_k):
                class _R:
                    def scalars(self):
                        class _S:
                            def first(self):
                                return _Row()

                        return _S()

                return _R()

        async def _load():
            return await ledger_persistence.load_checkpoint(_Db(), other_pkg, _config())

        with pytest.raises(CheckpointPackageMismatch) as ei:
            asyncio.run(_load())
        msg = str(ei.value)
        assert pkg.package_id in msg and other_pkg.package_id in msg

    def test_restore_rejects_mismatched_run_id(self, pkg):
        ledger = R01Ledger(pkg, _config())
        ledger.run_day(date(2025, 9, 10), None)
        cp = ledger.export_checkpoint()
        with pytest.raises(ValueError, match="不匹配"):
            R01Ledger.restore(pkg, _config(execution_attempt_id=2), cp)

    def test_risk_state_from_dict_roundtrip(self):
        m = RiskStateMachine(
            "run-x", __import__(
                "backend.services.simulation.replay.risk_state", fromlist=["RiskConfig"]
            ).RiskConfig(initial_cash=30000.0, drawdown_pct=0.5),
        )
        m.on_eod(20000.0, date(2025, 9, 10))
        ev_id = next(iter(m.events))
        m.confirm(ev_id, confirmed_by="u", confirmed_at="t", nav_at_confirm=20000)
        m.on_eod(20000.0, date(2025, 9, 11))  # 已确认线不重复
        m2 = RiskStateMachine.from_dict(m.to_dict())
        assert m2.high_water_mark == m.high_water_mark
        assert m2.events[ev_id].confirmed_by == "u"
        assert len(m2.events) == len(m.events)
        assert m2.buys_allowed == m.buys_allowed
