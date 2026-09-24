"""R01 独立研究账本引擎（ledger-contract v2 的 P0.3 实现）。

在 replay 子系统语义之上实现合同要求的最小执行账本：

- 三层标识：strategy_id+strategy_version / execution_attempt_id /
  ledger_run_id（= replay 会话标识），A/B1/B2/B3/D/N 运行组别参数化；
- 订单幂等键 client_order_id = f"{ledger_run_id}:{trade_date}:{symbol}:{side}"，
  同键重试返回原订单与原成交，不产生第二笔；
- 订单/成交状态机：new→validated→submitted→(partially_)filled /
  rejected / expired_unfilled（部分成交剩余量当日收盘转
  expired_unfilled，不隔日挂单）；
- 现金流政策：ETF 印花税=过户费=0（TG-006 资产类别规则）、佣金可配
  最低收费、现金分红 EOD 入账、份额调整开盘前（不动现金、成本基准
  同比例调整）、残余现金计息 0% 计入 nav；
- 公司行动只消费输入包 typed events，幂等键
  (ledger_run_id, symbol, event_date, event_type)；
- 风险状态机（risk_state.RiskStateMachine）：本金损失线 + 净值高点
  回撤线，独立触发、逐线确认，禁止追加资金掩蔽触发；
- 估值口径：信号=复权序列（包 adjusted_close）、执行=开盘价（未复权，
  含可配滑点与价格档）、净值=收盘未复权价；
- 确定性：同一冻结定义+同一输入包两次运行（不同 attempt）账务结果
  完全一致（时间戳不参与账务）。

纯内存实现（PG 持久化层由 models/replay.py 的 replay_* 表承接，见
db_init.sql + data/upgrade_v1.0.r01replay1.sql）；工程回放为 fixture
样例时显著标注，不进策略收益排行。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from backend.services.simulation.replay.etf_input_package import (
    EtfInputPackage,
    TypedEvent,
)
from backend.services.simulation.replay.risk_state import (
    RiskConfig,
    RiskStateMachine,
    make_risk_confirm_key,
)
from backend.services.simulation.services.ashare_matcher import (
    MatchConfig,
    MatchResult,
    match_order,
)
from backend.services.simulation.services.market_rules import (
    etf_settlement_days_for_symbol,
)
from backend.shared.utc_datetime import utc_now

logger = logging.getLogger(__name__)

GROUPS = ("A", "B1", "B2", "B3", "D", "N", "P0")
CONTRACT_VERSIONS = {
    "ledger_contract": "v2",
    "etf_input_package_schema": "v2",
}

# 订单/成交状态机（ledger-contract §4）
ORDER_STATUS_PARTIALLY_FILLED = "partially_filled"
ORDER_STATUS_EXPIRED_UNFILLED = "expired_unfilled"
ORDER_STATUS_FILLED = "filled"
ORDER_STATUS_REJECTED = "rejected"

_REJECT_REASONS = (
    "no_quote",
    "suspended",
    "limit_hit",
    "insufficient_cash",
    "risk_paused",
    "lot_inexpressible",
    "stale_price",
    "corporate_action_gap",
)


def make_ledger_run_id(group: str, strategy_id: str, version: int, attempt: int) -> str:
    """ledger_run_id = r01-<group>-<strategy_id>-v<version>-a<attempt>。"""
    return f"r01-{group}-{strategy_id}-v{version}-a{attempt:04d}"


def parse_attempt(attempt_id: str) -> int:
    """"a0001" → 1。"""
    return int(str(attempt_id).lstrip("a"))


def make_client_order_id(
    ledger_run_id: str, trade_date: date, symbol: str, side: str
) -> str:
    return f"{ledger_run_id}:{trade_date.isoformat()}:{symbol}:{side.lower()}"


@dataclass
class LedgerFill:
    """一笔成交（未复权价口径）。"""

    trade_date: str
    symbol: str
    side: str
    price: float
    quantity: int
    commission: float
    stamp_duty: float
    transfer_fee: float
    total_fee: float
    signal_date: str | None = None
    slippage_bps: float = 0.0
    price_source: str = "package_open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "symbol": self.symbol,
            "side": self.side,
            "price": round(self.price, 4),
            "quantity": self.quantity,
            "commission": round(self.commission, 4),
            "stamp_duty": round(self.stamp_duty, 4),
            "transfer_fee": round(self.transfer_fee, 4),
            "total_fee": round(self.total_fee, 4),
            "signal_date": self.signal_date,
            "slippage_bps": self.slippage_bps,
            "price_source": self.price_source,
        }


@dataclass
class LedgerOrder:
    """研究账本订单（含状态机字段）。"""

    client_order_id: str
    ledger_run_id: str
    trade_date: str
    signal_date: str | None
    symbol: str
    side: str  # buy | sell
    origin: str  # signal | manual | risk_exit
    qty_target: int
    status: str  # new/validated/submitted/partially_filled/filled/rejected/expired_unfilled
    qty_filled: int = 0
    qty_remaining: int = 0  # = target − filled，恒非负
    avg_fill_price: float = 0.0
    fees: float = 0.0
    realized_pnl: float = 0.0  # 卖出累计（扣费后）；买入为 0
    fills: list[LedgerFill] = field(default_factory=list)
    reject_reason: str | None = None
    ideal_weight: float | None = None
    realized_weight: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "ledger_run_id": self.ledger_run_id,
            "trade_date": self.trade_date,
            "signal_date": self.signal_date,
            "symbol": self.symbol,
            "side": self.side,
            "origin": self.origin,
            "qty_target": self.qty_target,
            "qty_filled": self.qty_filled,
            "qty_remaining": self.qty_remaining,
            "avg_fill_price": round(self.avg_fill_price, 4) if self.avg_fill_price else None,
            "status": self.status,
            "reject_reason": self.reject_reason,
            "fees": round(self.fees, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "ideal_weight": self.ideal_weight,
            "realized_weight": (
                round(self.realized_weight, 6) if self.realized_weight is not None else None
            ),
            "fills": [f.to_dict() for f in self.fills],
        }


@dataclass
class LedgerPosition:
    symbol: str
    qty: float = 0.0
    avg_cost: float = 0.0
    available_qty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": round(self.qty, 4),
            "avg_cost": round(self.avg_cost, 6),
            "available_qty": round(self.available_qty, 4),
        }


@dataclass
class R01LedgerConfig:
    """一次账本运行的冻结定义（创建后锁定）。"""

    group: str
    strategy_id: str
    strategy_version: int
    execution_attempt_id: int  # 单调递增 a0001 起；不靠新窗口重置
    initial_cash: float
    # 风险线（默认 initial_cash×30% 与回撤 30%）
    loss_line_amount: float | None = None
    drawdown_pct: float = 0.30
    # 撮合假设（DG-011 敏感性可配）
    commission_rate: float = 0.0003
    commission_min: float = 0.0
    slippage_bps: float = 5.0
    price_mode: str = "open"

    def __post_init__(self) -> None:
        if self.group not in GROUPS:
            raise ValueError(f"非法运行组别 {self.group}（允许 {GROUPS}）")
        if self.group == "P0" and not self.strategy_id.startswith("fixture-"):
            raise ValueError("P0 工程样例 strategy_id 必须以 fixture- 前缀（不进收益排行）")
        if self.execution_attempt_id < 1:
            raise ValueError("execution_attempt_id 从 1 起（a0001）")

    @property
    def ledger_run_id(self) -> str:
        return make_ledger_run_id(
            self.group, self.strategy_id, self.strategy_version, self.execution_attempt_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "execution_attempt_id": f"a{self.execution_attempt_id:04d}",
            "ledger_run_id": self.ledger_run_id,
            "initial_cash": self.initial_cash,
            "loss_line_amount": self.loss_line_amount,
            "drawdown_pct": self.drawdown_pct,
            "commission_rate": self.commission_rate,
            "commission_min": self.commission_min,
            "slippage_bps": self.slippage_bps,
            "price_mode": self.price_mode,
        }


@dataclass
class DaySummary:
    trade_date: str
    corporate_actions_applied: list[dict[str, Any]] = field(default_factory=list)
    dividends_credited: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    risk_events: list[dict[str, Any]] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "corporate_actions_applied": self.corporate_actions_applied,
            "dividends_credited": self.dividends_credited,
            "orders": self.orders,
            "risk_events": self.risk_events,
            "snapshot": self.snapshot,
        }


class R01Ledger:
    """一个 ledger_run_id 的完整账本（纯内存、确定性）。"""

    def __init__(
        self,
        package: EtfInputPackage,
        config: R01LedgerConfig,
        *,
        created_at: datetime | None = None,
        source_node: str = "mac",
    ):
        self.package = package
        self.config = config
        self.ledger_run_id = config.ledger_run_id
        self.created_at = created_at or utc_now()
        self.source_node = source_node
        self.contract_versions = dict(CONTRACT_VERSIONS)

        self.cash = float(config.initial_cash)
        self.initial_cash_locked = True
        self.positions: dict[str, LedgerPosition] = {}
        self.orders: dict[str, LedgerOrder] = {}
        self.equity: list[dict[str, Any]] = []
        self.risk = RiskStateMachine(
            self.ledger_run_id,
            RiskConfig(
                initial_cash=config.initial_cash,
                loss_line_amount=config.loss_line_amount,
                drawdown_pct=config.drawdown_pct,
            ),
        )
        # 公司行动幂等键 (run, symbol, event_date, event_type)
        self.applied_action_keys: set[tuple[str, str, str, str]] = set()
        self.corporate_action_log: list[dict[str, Any]] = []
        self.dividend_log: list[dict[str, Any]] = []
        self.manual_actions: list[dict[str, Any]] = []
        self.deposit_rejections: list[dict[str, Any]] = []
        self.risk_blocked_orders: list[dict[str, Any]] = []
        # 显式缺口：暂停该标的后续买入直到解决（禁止按零处理）
        self.buy_suspended_symbols: set[str] = set(package.unresolved_gap_symbols())
        self._executed_dates: set[str] = set()
        self._last_trade_date: date | None = None

        self._cfg = MatchConfig(
            price_mode=config.price_mode,
            slippage_bps=config.slippage_bps,
            commission_rate=config.commission_rate,
            commission_min=config.commission_min,
            # 费率字段对 ETF 是结构豁免（印花税/过户费恒 0），
            # 佣金率/最低收费取会话假设
            asset_type="etf",
            allow_partial=True,
        )

    # ------------------------------------------------------------------
    # 元数据
    # ------------------------------------------------------------------

    def session_metadata(self) -> dict[str, Any]:
        return {
            "strategy_id": self.config.strategy_id,
            "strategy_version": self.config.strategy_version,
            "execution_attempt_id": f"a{self.config.execution_attempt_id:04d}",
            "ledger_run_id": self.ledger_run_id,
            "group": self.config.group,
            "input_package_id": self.package.package_id,
            "input_package_uri": self.package.package_uri,
            "manifest_sha256": self.package.manifest_sha256,
            "contract_versions": self.contract_versions,
            "initial_cash": self.config.initial_cash,
            "risk_config": self.risk.config.to_dict(),
            "match_assumptions": {
                "commission_rate": self.config.commission_rate,
                "commission_min": self.config.commission_min,
                "slippage_bps": self.config.slippage_bps,
                "price_mode": self.config.price_mode,
                "asset_type": "etf",
            },
            "created_at": self.created_at.isoformat(),
            "source_node": self.source_node,
            "is_fixture": self.package.is_fixture,
        }

    # ------------------------------------------------------------------
    # 单日推演
    # ------------------------------------------------------------------

    def run_day(
        self,
        trade_date: date,
        target_weights: dict[str, float] | None = None,
        *,
        signal_date: date | None = None,
    ) -> DaySummary:
        """执行一个交易日（顺序是语义的一部分）：

        1. T+1 解锁（settlement 回转按品种）
        2. 份额调整 typed 事件（开盘前、撮合前）
        3. 目标权重 → 订单（先卖后买）
        4. EOD：现金分红入账 → 收盘估值 → nav → 风险评估 → 快照
        """
        key = trade_date.isoformat()
        if key in self._executed_dates:
            raise ValueError(f"{trade_date} 已执行（重放须新 attempt，TG-004/§3）")

        summary = DaySummary(trade_date=key)
        bars = self.package.load_date(trade_date)
        signal_iso = signal_date.isoformat() if signal_date else None

        # 1. 回转解锁：T+1 品种昨日买入今日可卖；T+0 当日即已可卖
        self._rollover_settlement(trade_date)

        # 2. 份额调整（开盘前；不动现金）
        for ev in self.package.events_on(trade_date):
            if ev.event_type == "share_adjustment":
                applied = self._apply_share_adjustment(ev)
                if applied is not None:
                    summary.corporate_actions_applied.append(applied)

        # 3. 目标权重 → 订单
        if target_weights is not None:
            self._rebalance(trade_date, bars, target_weights, signal_iso, summary)

        # 4. EOD
        self._eod(trade_date, bars, summary)

        self._executed_dates.add(key)
        self._last_trade_date = trade_date
        return summary

    # ------------------------------------------------------------------
    # 订单提交（幂等）
    # ------------------------------------------------------------------

    def submit_order(
        self,
        trade_date: date,
        symbol: str,
        side: str,
        qty: int,
        *,
        origin: str = "signal",
        signal_date: date | None = None,
        ideal_weight: float | None = None,
    ) -> LedgerOrder:
        """提交一笔订单。同 client_order_id 重试返回原订单（不重复成交）。"""
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"side 非法: {side}")
        coid = make_client_order_id(self.ledger_run_id, trade_date, symbol, side)
        existing = self.orders.get(coid)
        if existing is not None:
            return existing  # 同键重试：返回原订单与原成交

        order = LedgerOrder(
            client_order_id=coid,
            ledger_run_id=self.ledger_run_id,
            trade_date=trade_date.isoformat(),
            signal_date=signal_date.isoformat() if signal_date else None,
            symbol=symbol,
            side=side,
            origin=origin,
            qty_target=int(qty),
            qty_remaining=int(qty),
            status="new",
            ideal_weight=ideal_weight,
        )
        self.orders[coid] = order
        return order

    def _validate_and_execute(
        self, order: LedgerOrder, trade_date: date, bars: dict, summary: DaySummary
    ) -> None:
        """validated → submitted → fill/reject 状态机（单日内完成）。"""
        order.status = "validated"
        bar = bars.get(order.symbol)

        def _reject(reason: str) -> None:
            order.status = ORDER_STATUS_REJECTED
            order.reject_reason = reason
            order.qty_remaining = order.qty_target

        if bar is None:
            return _reject("no_quote")
        if bar.suspended:
            return _reject("suspended")
        # 风险闸门：仅买方向；既定退出/卖出继续有效
        if order.side == "buy":
            if not self.risk.buys_allowed:
                active = self.risk.latest_active_risk_event_id()
                blocked = {
                    "client_order_id": order.client_order_id,
                    "symbol": order.symbol,
                    "trade_date": order.trade_date,
                    "qty": order.qty_target,
                    "reject_reason": "risk_paused",
                }
                self.risk_blocked_orders.append(blocked)
                if active:
                    self.risk.record_blocked_order(active, blocked)
                return _reject("risk_paused")
            if order.symbol in self.buy_suspended_symbols:
                return _reject("corporate_action_gap")

        order.status = "submitted"
        position = self.positions.get(order.symbol)
        available = (
            position.available_qty
            if (position is not None and order.side == "sell")
            else None
        )
        mr: MatchResult = match_order(
            side=order.side,
            quantity=order.qty_target,
            bar=bar,
            cfg=self._cfg,
            available_volume=available,
            cash_available=self.cash if order.side == "buy" else None,
        )
        if not mr.success:
            reason = mr.reason.split(":", 1)[0].lower()
            return _reject(_normalize_reject_reason(reason))

        self._settle_fill(order, mr, bar, summary)

    def _settle_fill(
        self, order: LedgerOrder, mr: MatchResult, bar, summary: DaySummary
    ) -> None:
        """成交入账（现金/持仓/成本）并推进状态机。"""
        gross = mr.fill_quantity * mr.fill_price
        fill = LedgerFill(
            trade_date=order.trade_date,
            symbol=order.symbol,
            side=order.side,
            price=mr.fill_price,
            quantity=mr.fill_quantity,
            commission=mr.commission,
            stamp_duty=mr.stamp_duty,
            transfer_fee=mr.transfer_fee,
            total_fee=mr.total_fee,
            signal_date=order.signal_date,
            slippage_bps=self.config.slippage_bps,
        )
        pos = self.positions.setdefault(
            order.symbol, LedgerPosition(symbol=order.symbol)
        )
        if order.side == "buy":
            self.cash -= gross + mr.total_fee
            # 移动加权成本
            new_qty = pos.qty + mr.fill_quantity
            pos.avg_cost = (
                (pos.avg_cost * pos.qty + gross + mr.total_fee) / new_qty
                if new_qty > 0
                else 0.0
            )
            pos.qty = new_qty
            # T+0 品种当日可卖；T+1 品种在次日 rollover 解锁
            if etf_settlement_days_for_symbol(order.symbol) == 0:
                pos.available_qty += mr.fill_quantity
        else:
            # 卖出在减仓前抓移动加权成本（清仓后持仓会被删掉）
            avg_cost_before = pos.avg_cost
            self.cash += gross - mr.total_fee
            pos.qty -= mr.fill_quantity
            pos.available_qty = max(0.0, pos.available_qty - mr.fill_quantity)
            realized = (mr.fill_price - avg_cost_before) * mr.fill_quantity - mr.total_fee
            order.realized_pnl += realized
            if pos.qty <= 1e-9:
                self.positions.pop(order.symbol, None)

        order.fills.append(fill)
        total_qty = sum(f.quantity for f in order.fills)
        order.qty_filled = total_qty
        order.qty_remaining = max(0, order.qty_target - total_qty)
        order.avg_fill_price = (
            sum(f.quantity * f.price for f in order.fills) / total_qty
            if total_qty > 0
            else 0.0
        )
        order.fees += mr.total_fee
        # 部分成交：当日有效；剩余量收盘后转 expired_unfilled（_eod 统一收口）
        order.status = (
            ORDER_STATUS_FILLED if order.qty_remaining == 0 else ORDER_STATUS_PARTIALLY_FILLED
        )
        summary.orders.append(order.to_dict())

    def _rebalance(
        self,
        trade_date: date,
        bars: dict,
        target_weights: dict[str, float],
        signal_iso: str | None,
        summary: DaySummary,
    ) -> None:
        """目标权重 → 订单，先卖后买（腾出现金）。

        目标手数 = floor(目标金额 / (开盘价×100))；ideal_weight=信号
        目标权重，realized_weight 在 EOD 按 (qty×close)/nav 回填（DG-001）。
        """
        nav_est = self._nav_with_bars(bars)
        if nav_est <= 0:
            return
        sig_date = date.fromisoformat(signal_iso) if signal_iso else None
        sells: list[LedgerOrder] = []
        buys: list[LedgerOrder] = []
        for symbol, weight in sorted(target_weights.items()):
            symbol = symbol.upper()
            bar = bars.get(symbol)
            price = (bar.open if bar and bar.open > 0 else (bar.close if bar else 0.0)) or 0.0
            target_amount = weight * nav_est
            # 原始目标份额（不预先取整）：整手约束交由撮合器统一执行；
            # 不足一手的买入会以 BELOW_LOT_SIZE→lot_inexpressible 显式拒单
            raw_target = target_amount / price if price > 0 else 0.0
            pos = self.positions.get(symbol)
            current_qty = pos.qty if pos else 0.0
            delta = raw_target - current_qty
            if abs(delta) < 1:
                continue
            side = "buy" if delta > 0 else "sell"
            qty = int(delta) if delta > 0 else int(math.ceil(-delta - 1e-9))
            order = self.submit_order(
                trade_date, symbol, side, qty,
                origin="signal", signal_date=sig_date, ideal_weight=weight,
            )
            if bar is None or bar.suspended:
                # 停牌/无行情日不虚构成交：显式拒单留痕
                order.status = ORDER_STATUS_REJECTED
                order.reject_reason = "no_quote" if bar is None else "suspended"
                summary.orders.append(order.to_dict())
                continue
            (buys if side == "buy" else sells).append(order)
        for order in sells + buys:
            self._validate_and_execute(order, trade_date, bars, summary)

    # ------------------------------------------------------------------
    # 公司行动
    # ------------------------------------------------------------------

    def _apply_share_adjustment(self, ev: TypedEvent) -> dict[str, Any] | None:
        """份额调整：开盘前、撮合前；qty×=multiplier、成本基准同比例调整、
        不动现金。幂等键 (ledger_run_id, symbol, event_date, event_type)。
        """
        key = (self.ledger_run_id, ev.symbol, ev.event_date.isoformat(), ev.event_type)
        if key in self.applied_action_keys:
            return None
        self.applied_action_keys.add(key)
        pos = self.positions.get(ev.symbol)
        record = {
            "idempotency_key": list(key),
            "event_type": ev.event_type,
            "symbol": ev.symbol,
            "event_date": ev.event_date.isoformat(),
            "qty_multiplier": ev.qty_multiplier,
            "qty_before": round(pos.qty, 4) if pos else 0.0,
            "cash_delta": 0.0,
            "applied": pos is not None and pos.qty > 0,
        }
        if pos is not None and pos.qty > 0:
            pos.qty *= ev.qty_multiplier
            pos.available_qty *= ev.qty_multiplier
            pos.avg_cost /= ev.qty_multiplier  # 成本基准同比例调整
            record["qty_after"] = round(pos.qty, 4)
            record["avg_cost_after"] = round(pos.avg_cost, 6)
        self.corporate_action_log.append(record)
        return record

    def _apply_cash_dividend(self, ev: TypedEvent, trade_date: date) -> dict[str, Any] | None:
        """现金分红：EOD、nav 计算前；cash += qty × cash_per_share。"""
        key = (self.ledger_run_id, ev.symbol, ev.event_date.isoformat(), ev.event_type)
        if key in self.applied_action_keys:
            return None
        self.applied_action_keys.add(key)
        pos = self.positions.get(ev.symbol)
        qty = pos.qty if pos else 0.0
        amount = round(qty * ev.cash_per_share, 4)
        if amount:
            self.cash += amount
        record = {
            "idempotency_key": list(key),
            "event_type": ev.event_type,
            "symbol": ev.symbol,
            "event_date": ev.event_date.isoformat(),
            "cash_per_share": ev.cash_per_share,
            "qty": round(qty, 4),
            "cash_delta": amount,
            "applied": qty > 0,
        }
        self.dividend_log.append(record)
        return record

    # ------------------------------------------------------------------
    # EOD
    # ------------------------------------------------------------------

    def _rollover_settlement(self, trade_date: date) -> None:
        """日初回转解锁：T+1 品种全部持仓变为可卖；T+0 已即时可卖。"""
        if self._last_trade_date is None:
            return
        for pos in self.positions.values():
            if etf_settlement_days_for_symbol(pos.symbol) >= 1:
                pos.available_qty = pos.qty

    def _nav_with_bars(self, bars: dict) -> float:
        market_value = 0.0
        for symbol, pos in self.positions.items():
            bar = bars.get(symbol)
            close = bar.close if (bar and bar.close > 0) else pos.avg_cost
            market_value += pos.qty * close
        return self.cash + market_value

    def _eod(self, trade_date: date, bars: dict, summary: DaySummary) -> None:
        # 部分成交剩余量收口：当日收盘后转 expired_unfilled，不隔日挂单
        for order in self.orders.values():
            if order.trade_date == trade_date.isoformat() and (
                order.status == ORDER_STATUS_PARTIALLY_FILLED
            ):
                order.status = ORDER_STATUS_EXPIRED_UNFILLED

        # 现金分红（先于 nav）
        for ev in self.package.events_on(trade_date):
            if ev.event_type == "cash_dividend":
                credited = self._apply_cash_dividend(ev, trade_date)
                if credited is not None:
                    summary.dividends_credited.append(credited)

        # 收盘估值
        market_value = 0.0
        fees_today = 0.0
        realized_pnl_today = 0.0
        positions_out: dict[str, Any] = {}
        for symbol, pos in sorted(self.positions.items()):
            bar = bars.get(symbol)
            close = bar.close if (bar and bar.close > 0) else pos.avg_cost
            market_value += pos.qty * close
            positions_out[symbol] = {
                **pos.to_dict(),
                "close": round(close, 4),
                "market_value": round(pos.qty * close, 4),
            }
        nav = self.cash + market_value
        for order in self.orders.values():
            if order.trade_date == trade_date.isoformat():
                fees_today += order.fees
                realized_pnl_today += order.realized_pnl

        # realized_weight 回填（DG-001）
        for order in self.orders.values():
            if order.trade_date == trade_date.isoformat() and nav > 0:
                bar = bars.get(order.symbol)
                close = bar.close if (bar and bar.close > 0) else 0.0
                pos = self.positions.get(order.symbol)
                qty = pos.qty if pos else 0.0
                order.realized_weight = round(qty * close / nav, 6)

        # 风险评估（HWM 更新 + 两线独立触发）
        triggered = self.risk.on_eod(nav, trade_date)
        summary.risk_events.extend(ev.to_dict() for ev in triggered)

        snapshot = {
            "trade_date": trade_date.isoformat(),
            "cash": round(self.cash, 4),
            "market_value": round(market_value, 4),
            "nav": round(nav, 4),
            "fees_today": round(fees_today, 4),
            "realized_pnl_today": round(realized_pnl_today, 4),
            "high_water_mark": round(self.risk.high_water_mark, 4),
            "risk_status": self.risk.status,
            "positions": positions_out,
        }
        self.equity.append(snapshot)
        summary.snapshot = snapshot

    # ------------------------------------------------------------------
    # 用户操作
    # ------------------------------------------------------------------

    def confirm_risk_event(
        self,
        risk_event_id: str,
        *,
        confirmed_by: str,
        confirmed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """用户逐线确认（幂等键 f"{ledger_run_id}:risk-confirm:{risk_event_id}"）。"""
        ts = (confirmed_at or utc_now()).astimezone(timezone.utc)
        latest_nav = self.equity[-1]["nav"] if self.equity else self.config.initial_cash
        self.risk.confirm(
            risk_event_id,
            confirmed_by=confirmed_by,
            confirmed_at=ts.isoformat(),
            nav_at_confirm=float(latest_nav),
        )
        return {
            "confirm_key": make_risk_confirm_key(self.ledger_run_id, risk_event_id),
            "risk_event_id": risk_event_id,
            "confirmed_by": confirmed_by,
            "confirmed_at": ts.isoformat(),
            "nav_at_confirm": latest_nav,
            "buys_allowed_after": self.risk.buys_allowed,
        }

    def manual_sell(
        self,
        trade_date: date,
        symbol: str,
        qty: int,
        *,
        reason: str,
        requested_by: str,
        bars: dict | None = None,
    ) -> LedgerOrder:
        """用户额外减仓：允许任意时刻（含风险暂停期）；记 manual_action；
        不影响 HWM（HWM 只在 EOD 由 nav 更新）、不解除风险暂停、不计为
        策略行为；nav 影响入账。"""
        bars = bars if bars is not None else self.package.load_date(trade_date)
        order = self.submit_order(
            trade_date, symbol, "sell", qty, origin="manual",
            signal_date=None,
        )
        summary = DaySummary(trade_date=trade_date.isoformat())
        self._validate_and_execute(order, trade_date, bars, summary)
        self.manual_actions.append(
            {
                "date": trade_date.isoformat(),
                "symbol": symbol,
                "qty": qty,
                "reason": reason,
                "requested_by": requested_by,
                "client_order_id": order.client_order_id,
                "status": order.status,
            }
        )
        return order

    def deposit(self, amount: float, *, requested_by: str) -> dict[str, Any]:
        """追加资金：一律拒绝（禁止掩蔽触发），拒绝记录入审计。"""
        record = {
            "requested_by": requested_by,
            "amount": float(amount),
            "accepted": False,
            "reason": "initial_cash_locked（ledger-contract §7：禁止追加资金掩蔽触发）",
            "ledger_run_id": self.ledger_run_id,
        }
        self.deposit_rejections.append(record)
        return record

    # ------------------------------------------------------------------
    # 证据导出
    # ------------------------------------------------------------------

    def export_evidence(self) -> dict[str, Any]:
        evidence = {
            "banner": (
                "FIXTURE 工程样例回放——不进策略收益排行"
                if self.package.is_fixture
                else "正式研究账本"
            ),
            "session": self.session_metadata(),
            "package": self.package.describe(),
            "orders": [o.to_dict() for o in self.orders.values()],
            "equity": list(self.equity),
            "corporate_actions": list(self.corporate_action_log),
            "dividends": list(self.dividend_log),
            "manual_actions": list(self.manual_actions),
            "deposit_rejections": list(self.deposit_rejections),
            "risk_blocked_orders": list(self.risk_blocked_orders),
            "risk_state": self.risk.to_dict(),
        }
        return evidence


# ---------------------------------------------------------------------------
# 独立复算（ledger-contract §9：用输入包原始数据独立重算现金/净值逐日对齐）
# ---------------------------------------------------------------------------


def independent_recompute(
    evidence: dict[str, Any],
    package: EtfInputPackage | None = None,
) -> list[dict[str, Any]]:
    """从导出证据的原始明细（成交/公司行动/分红）独立重建 nav 序列。

    刻意不复用 R01Ledger 的任何记账路径：只读 fills + corporate actions
    + dividends + 收盘价（package 提供时直接从输入包取，不经引擎中间
    结果），逐日重放现金与持仓。返回逐日 (date, cash, nav)，供与
    evidence.equity 对账（ledger-contract §9）。
    """
    session = evidence["session"]
    cash = float(session["initial_cash"])
    positions: dict[str, float] = {}
    fills_by_date: dict[str, list[dict]] = {}
    for order in evidence["orders"]:
        for fill in order.get("fills", []):
            fills_by_date.setdefault(fill["trade_date"], []).append(fill)
    actions_by_date: dict[str, list[dict]] = {}
    for rec in evidence.get("corporate_actions", []) + evidence.get("dividends", []):
        actions_by_date.setdefault(rec["event_date"], []).append(rec)

    out: list[dict[str, Any]] = []
    for snap in evidence["equity"]:
        d = snap["trade_date"]
        day = date.fromisoformat(d)
        # 开盘前：份额调整（同日先份额后现金）
        for rec in actions_by_date.get(d, []):
            sym = rec["symbol"]
            if rec["event_type"] == "share_adjustment" and sym in positions:
                mult = rec["qty_multiplier"]
                positions[sym] *= mult
        # 成交重放
        for fill in fills_by_date.get(d, []):
            sym, side, qty, price = (
                fill["symbol"],
                fill["side"],
                float(fill["quantity"]),
                float(fill["price"]),
            )
            fee = float(fill["total_fee"])
            if side == "buy":
                cash -= qty * price + fee
                positions[sym] = positions.get(sym, 0.0) + qty
            else:
                cash += qty * price - fee
                positions[sym] = positions.get(sym, 0.0) - qty
                if positions[sym] <= 1e-9:
                    positions.pop(sym, None)
        # EOD：现金分红（先于 nav）
        for rec in actions_by_date.get(d, []):
            sym = rec["symbol"]
            if rec["event_type"] == "cash_dividend" and sym in positions:
                cash += positions[sym] * rec["cash_per_share"]
        # nav：cash + Σ qty×close（优先直接从输入包取收盘价，独立于引擎）
        market_value = 0.0
        for sym, qty in positions.items():
            close = 0.0
            if package is not None:
                bar = package.get_bar(sym, day)
                close = bar.close if bar and bar.close > 0 else 0.0
            else:
                close = float(
                    (snap.get("positions") or {}).get(sym, {}).get("close", 0.0)
                )
            market_value += qty * close
        out.append(
            {
                "trade_date": d,
                "cash": round(cash, 4),
                "nav": round(cash + market_value, 4),
            }
        )
    return out


def _normalize_reject_reason(reason: str) -> str:
    mapping = {
        "no_market_data": "no_quote",
        "suspended": "suspended",
        "limit_up": "limit_hit",
        "limit_down": "limit_hit",
        "insufficient_available_volume": "lot_inexpressible",
        "below_lot_size": "lot_inexpressible",
        "insufficient_cash": "insufficient_cash",
        "invalid_price": "stale_price",
        "risk_paused": "risk_paused",
        "corporate_action_gap": "corporate_action_gap",
    }
    return mapping.get(reason, reason)
