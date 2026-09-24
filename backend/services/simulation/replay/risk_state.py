"""R01 研究账本风险状态机（ledger-contract §7 / TG-010）。

两条独立复核线，EOD 口径评估：
- loss_line（本金损失线）：nav ≤ initial_cash − loss_line_amount，
  默认 initial_cash×30%（3 万本金 = 9000 元，2 万 = 6000 元），run 级可配；
- drawdown_line（高点回撤线）：nav ≤ high_water_mark×(1−30%)，
  HWM 随 nav 新高上移，只增不减。

触发语义：
- 任一线触发 ⇒ 暂停：拒绝新增买单（reject_reason=risk_paused），
  既定退出/卖出继续有效；
- 风险事件 risk_event_id = f"{ledger_run_id}:{date}:{risk_line}"，
  同日双线触发记两条（两线独立）；
- 恢复须用户逐线确认（幂等键
  f"{ledger_run_id}:risk-confirm:{risk_event_id}"），净值反弹不自动解除；
- 无未确认的活跃触发时才恢复买入；
- 禁止追加资金掩蔽触发：账本 initial_cash 创建后锁定（deposit 拒绝在
  账本层实现，本模块只维护阈值）。

纯内存确定性实现：同一输入序列结果确定，可序列化导出证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


def make_risk_event_id(ledger_run_id: str, day: date, risk_line: str) -> str:
    return f"{ledger_run_id}:{day.isoformat()}:{risk_line}"


def make_risk_confirm_key(ledger_run_id: str, risk_event_id: str) -> str:
    return f"{ledger_run_id}:risk-confirm:{risk_event_id}"


@dataclass
class RiskEvent:
    """一条已触发的风险事件（含确认状态）。"""

    risk_event_id: str
    date: str  # ISO date
    nav: float
    risk_line: str  # loss_line | drawdown_line
    threshold: float  # 触发阈值（nav ≤ threshold 触发）
    action: str = "pause_buys"
    blocked_orders: list[dict[str, Any]] = field(default_factory=list)
    # 确认信息（用户逐线确认）
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    nav_at_confirm: float | None = None

    @property
    def confirmed(self) -> bool:
        return self.confirmed_by is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_event_id": self.risk_event_id,
            "date": self.date,
            "nav": self.nav,
            "risk_line": self.risk_line,
            "threshold": self.threshold,
            "action": self.action,
            "blocked_orders": list(self.blocked_orders),
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
            "nav_at_confirm": self.nav_at_confirm,
        }


@dataclass
class RiskConfig:
    """run 级风险配置（创建后锁定，随会话元数据固化）。"""

    initial_cash: float
    loss_line_amount: float | None = None  # None → initial_cash×30%
    drawdown_pct: float = 0.30

    def resolved_loss_line_amount(self) -> float:
        if self.loss_line_amount is not None:
            return float(self.loss_line_amount)
        return self.initial_cash * 0.30

    def drawdown_threshold(self, hwm: float) -> float:
        return hwm * (1.0 - self.drawdown_pct)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_cash": self.initial_cash,
            "loss_line_amount": self.resolved_loss_line_amount(),
            "drawdown_pct": self.drawdown_pct,
        }


class RiskStateMachine:
    """两线独立、EOD 评估、逐线确认的风险状态机。"""

    def __init__(
        self,
        ledger_run_id: str,
        config: RiskConfig,
        *,
        high_water_mark: float | None = None,
    ):
        self.ledger_run_id = ledger_run_id
        self.config = config
        # HWM 初值 = initial_cash（净值从本金起算；只增不减）
        self.high_water_mark = (
            high_water_mark
            if high_water_mark is not None
            else float(config.initial_cash)
        )
        self.events: dict[str, RiskEvent] = {}
        self._confirmed_keys: set[str] = set()
        self.status: str = "active"  # active | paused
        self.terminal: bool = False

    # -- 评估 ------------------------------------------------------------

    def on_eod(self, nav: float, day: date) -> list[RiskEvent]:
        """EOD 评估（先更新 HWM，再逐线检查；同日双线可触发两条）。

        每条线按 risk_event_id 幂等：同一 (run, date, line) 只记一次；
        且一条线已有未确认触发时，后续 EOD 即使仍在线下也不再新增该线
        事件（同一持续状态只维持原活跃触发，确认义务不逐日累积；
        确认后若再度跌破则产生新事件）。
        """
        triggered: list[RiskEvent] = []
        if nav > self.high_water_mark:
            self.high_water_mark = nav

        unconfirmed_lines = {
            ev.risk_line for ev in self.events.values() if not ev.confirmed
        }
        checks = (
            (
                "loss_line",
                self.config.initial_cash - self.config.resolved_loss_line_amount(),
            ),
            ("drawdown_line", self.config.drawdown_threshold(self.high_water_mark)),
        )
        for risk_line, threshold in checks:
            if nav <= threshold and risk_line not in unconfirmed_lines:
                event_id = make_risk_event_id(self.ledger_run_id, day, risk_line)
                if event_id in self.events:
                    continue  # 幂等：同日同线不重复
                event = RiskEvent(
                    risk_event_id=event_id,
                    date=day.isoformat(),
                    nav=round(float(nav), 4),
                    risk_line=risk_line,
                    threshold=round(float(threshold), 4),
                )
                self.events[event_id] = event
                triggered.append(event)

        if self.has_unconfirmed_trigger:
            self.status = "paused"
        return triggered

    # -- 确认 ------------------------------------------------------------

    @property
    def has_unconfirmed_trigger(self) -> bool:
        return any(not ev.confirmed for ev in self.events.values())

    @property
    def buys_allowed(self) -> bool:
        """仅当无未确认的活跃触发时才恢复买入（净值反弹不自动解除）。"""
        return (not self.terminal) and not self.has_unconfirmed_trigger

    def confirm(
        self,
        risk_event_id: str,
        *,
        confirmed_by: str,
        confirmed_at: str,
        nav_at_confirm: float,
    ) -> RiskEvent:
        """用户逐线确认（幂等）。同键重放返回原确认记录。"""
        event = self.events.get(risk_event_id)
        if event is None:
            raise KeyError(f"未知风险事件: {risk_event_id}")
        if event.confirmed:
            return event  # 幂等
        event.confirmed_by = confirmed_by
        event.confirmed_at = confirmed_at
        event.nav_at_confirm = round(float(nav_at_confirm), 4)
        if not self.has_unconfirmed_trigger:
            self.status = "active"
        return event

    # -- 审计 ------------------------------------------------------------

    def record_blocked_order(self, risk_event_id: str, order_ref: dict[str, Any]) -> None:
        """risk_paused 拒单计入风险审计 blocked_orders[]。"""
        event = self.events.get(risk_event_id)
        if event is not None:
            event.blocked_orders.append(order_ref)

    def latest_active_risk_event_id(self) -> str | None:
        """当前用于拒单的风险事件（最新未确认触发）。"""
        pending = [ev for ev in self.events.values() if not ev.confirmed]
        if not pending:
            return None
        return sorted(pending, key=lambda e: (e.date, e.risk_line))[-1].risk_event_id

    def terminate(self) -> None:
        self.terminal = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_run_id": self.ledger_run_id,
            "status": self.status,
            "terminal": self.terminal,
            "high_water_mark": round(self.high_water_mark, 4),
            "config": self.config.to_dict(),
            "events": [ev.to_dict() for ev in self.events.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskStateMachine:
        """从 to_dict 快照恢复（W2E3 checkpoint 持久化用）。

        事件含确认状态逐字段还原；status 由未确认触发重算（不信任快照
        字符串，防止快照与事件状态漂移）。
        """
        cfg = data["config"]
        m = cls(
            data["ledger_run_id"],
            RiskConfig(
                initial_cash=float(cfg["initial_cash"]),
                loss_line_amount=float(cfg["loss_line_amount"]),
                drawdown_pct=float(cfg["drawdown_pct"]),
            ),
            high_water_mark=float(data["high_water_mark"]),
        )
        m.terminal = bool(data.get("terminal"))
        for evd in data.get("events", []):
            ev = RiskEvent(
                risk_event_id=evd["risk_event_id"],
                date=evd["date"],
                nav=float(evd["nav"]),
                risk_line=evd["risk_line"],
                threshold=float(evd["threshold"]),
                action=evd.get("action", "pause_buys"),
                blocked_orders=list(evd.get("blocked_orders", [])),
                confirmed_by=evd.get("confirmed_by"),
                confirmed_at=evd.get("confirmed_at"),
                nav_at_confirm=(
                    float(evd["nav_at_confirm"])
                    if evd.get("nav_at_confirm") is not None
                    else None
                ),
            )
            m.events[ev.risk_event_id] = ev
        m.status = "paused" if m.has_unconfirmed_trigger else "active"
        return m
