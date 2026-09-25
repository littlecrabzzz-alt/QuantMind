"""交易日运行流水线（H2.2-R1/R2/R3，h2-interfaces §3）。

一个决策日（decision_date，收盘后）的阶段链：

``data_check → freeze_input → signal → risk_check → execute → settle → report``

- **R1 交易日运行**：数据就绪 → 冻结输入 → 规则信号/每日风险检查 →
  目标与不交易原因 → 约定时点（次一交易日开盘窗口）虚拟执行 → 账本
  落库（ReplayLedgerCheckpoint）→ 平台回报（run_status 直写）与对账
  （independent_recompute）。收盘信号只用于次一交易日约定时点执行
  （账本层 LedgerOrderingError 强制 signal_date=执行日上一交易日，
  不可倒用当天开盘成交）。
- **R2 月度调仓+每日审查**：信号仅两个来源——月末（日历最后一交易
  日）调仓与冻结配置的首日建仓；其余决策日为"每日审查、无新订单"的
  有效运行（today_decision 含 no_trade_reason）。不存在逐日择时输入，
  不暗中变每日择时。
- **R3 幂等/锁/恢复**：阶段幂等键 ``{run}:{date}:{stage}``（状态记录
  即幂等凭据）；日锁 SET NX+TTL；崩溃后从最后完成阶段续跑，续跑结果
  与相同输入连续运行一致；结果不明（阶段标记与账本权威状态矛盾）
  显式 NeedsManualReview，不自动重跑。**错过窗口按事前冻结策略处理**
  （missed_window_policy），不事后补写"当时已决策"。

时间全部经注入 clock；故障注入用 ``crash_points``（工程验收）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from backend.services.simulation.replay.etf_input_package import EtfInputPackage
from backend.services.simulation.replay.r01_ledger import R01Ledger
from backend.services.simulation.virtual_run.clock import (
    RunClock,
    SystemClock,
    local_wall,
    parse_hhmm,
)
from backend.services.simulation.virtual_run.gating import (
    DailyDataIdentity,
    DailyInputsProvider,
    GateResult,
)
from backend.services.simulation.virtual_run.locks import DayRunLock, LockBackend
from backend.services.simulation.virtual_run.recovery import (
    CheckpointStore,
    NeedsManualReview,
    reconcile,
)
from backend.services.simulation.virtual_run.states import (
    STAGES,
    ControlBoard,
    RunStateStore,
    VirtualRunConfig,
    build_run_status,
    make_task_id,
)

OUTCOME_COMPLETED = "completed"
OUTCOME_PENDING_EXECUTE = "pending_execute"
OUTCOME_PENDING_DECISION = "pending_decision"
OUTCOME_NOT_TRADE_DAY = "not_trade_day"
OUTCOME_DATA_BLOCKED = "data_blocked"
OUTCOME_MISSED_DECISION = "missed_decision_window"
OUTCOME_MISSED_EXECUTION = "missed_execution_window"
OUTCOME_STOPPED = "stopped"
OUTCOME_BUSY = "busy"

_TERMINAL_DATA_CHECK = ("ready", "not_trade_day", "data_blocked")


class CrashInjection(RuntimeError):
    """工程验收故障注入（crash_points 命中点抛出，模拟进程崩溃）。"""


@dataclass
class DayRunResult:
    decision_date: str
    outcome: str
    detail: str = ""
    today_decision: dict | None = None
    stage_states: dict = field(default_factory=dict)
    anomalies: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "outcome": self.outcome,
            "detail": self.detail,
            "today_decision": self.today_decision,
            "anomalies": self.anomalies,
        }


def is_month_last_trade_date(pkg: EtfInputPackage, d: date) -> bool:
    """月末信号日：下一包交易日不存在或跨月。"""
    nxt = pkg.next_trade_date(d)
    return nxt is None or (nxt.year, nxt.month) != (d.year, d.month)


class VirtualRunPipeline:
    """单 run（r01vr-…）的每日运行流水线（线程不安全；由调度串行驱动）。"""

    def __init__(
        self,
        config: VirtualRunConfig,
        provider: DailyInputsProvider,
        *,
        clock: RunClock | None = None,
        lock_backend: LockBackend,
        state_store: RunStateStore,
        checkpoint_store: CheckpointStore,
        schedule_cfg: dict | None = None,
        crash_points: set[str] | None = None,
        platform_reporter=None,
    ):
        self.config = config
        self.provider = provider
        self.clock = clock or SystemClock()
        self.lock_backend = lock_backend
        self.store = state_store
        self.checkpoints = checkpoint_store
        self.control = ControlBoard(state_store)
        self.schedule_cfg = schedule_cfg
        self.crash_points = set(crash_points or ())
        # 平台回报（p04 POST /r01/run-status）：callable(payload) -> dict；
        # 不传=不外报（工程验收/单测）；失败 best-effort 记 anomaly 不中断运行
        self.platform_reporter = platform_reporter
        self._tz = config.tz

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def run_day(self, decision_date: date) -> DayRunResult:
        now = self.clock.now()
        self._beat(now)
        run_id = self.config.ledger_run_id
        day_key = decision_date.isoformat()

        # 停止/恢复三段：requested → received（执行端已读到）
        ctl = self.control.tick(run_id, now)
        if self.control.stop_effective(run_id):
            return DayRunResult(day_key, OUTCOME_STOPPED, "stop 已生效：不推进新决策日")
        # 安全点（新决策日开始前）使 received 的控制命令生效
        if ctl is not None and ctl.state == "received":
            if self.store.get_stage(run_id, day_key, "data_check") is None:
                self.control.mark_effective(run_id, now)
                if self.control.stop_effective(run_id):
                    return DayRunResult(day_key, OUTCOME_STOPPED, "stop 于安全点生效")

        lock = DayRunLock(
            self.lock_backend,
            run_id,
            day_key,
            ttl_seconds=self.config.window_timeout_minutes * 60 + 600,
        )
        if not lock.acquire():
            # 重复调度/双 worker：另一持有者在推进，让出不重入
            return DayRunResult(
                day_key,
                OUTCOME_BUSY,
                "日锁被持有（重复调度/双 worker），本次让出",
            )
        try:
            return self._run_locked(decision_date, now)
        finally:
            lock.release()

    def confirm_risk_events(
        self, event_ids: list[str], *, confirmed_by: str
    ) -> dict[str, Any]:
        """用户逐线确认风险触发（恢复买入；净值反弹不自动恢复）。"""
        run_id = self.config.ledger_run_id
        pkg = self.provider.package
        ledger = self.checkpoints.load(pkg, self.config.to_ledger_config())
        if ledger is None:
            raise NeedsManualReview(f"{run_id} 无账本检查点，无可确认风险事件")
        now = self.clock.now()
        confirmed = []
        for eid in event_ids:
            order = ledger.confirm_risk_event(eid, confirmed_by=confirmed_by)
            confirmed.append({"risk_event_id": eid, **order})
        self.checkpoints.save(ledger)
        self._write_status(ledger, now, extra_note="risk_confirmed")
        return {"confirmed": confirmed, "buys_allowed": ledger.risk.buys_allowed}

    # ------------------------------------------------------------------
    # 阶段机
    # ------------------------------------------------------------------

    def _run_locked(self, decision_date: date, now: datetime) -> DayRunResult:
        run_id = self.config.ledger_run_id
        day_key = decision_date.isoformat()

        # -- 错过决策窗口（R3/R4）：无任何阶段状态且已过截止+超时 ----
        if self.store.get_stage(run_id, day_key, "data_check") is None:
            verdict = self._decision_window_verdict(decision_date, now)
            if verdict == "missed":
                rec = self._record_missed_decision(decision_date, now)
                return DayRunResult(
                    day_key,
                    OUTCOME_MISSED_DECISION,
                    "决策窗口已错过：按事前冻结策略记录，不补写决策",
                    today_decision=rec["today_decision"],
                )
            if verdict == "early":
                return DayRunResult(
                    day_key,
                    OUTCOME_PENDING_DECISION,
                    "未到决策截止（收盘后数据未就绪，不提前决策）",
                )

        # -- data_check -------------------------------------------------
        dc = self._stage_data_check(decision_date, now)
        if dc["status"] == "not_trade_day":
            return self._finish_simple_day(
                decision_date,
                OUTCOME_NOT_TRADE_DAY,
                dc["reason"],
                today_decision={
                    "action": "not_trade_day",
                    "reason": dc["reason"],
                    "no_trade_reason": "休市日/无交易日",
                },
                now=now,
            )
        if dc["status"] == "data_blocked":
            return self._finish_simple_day(
                decision_date,
                OUTCOME_DATA_BLOCKED,
                dc["reason"],
                today_decision={"action": "data_blocked", "reason": dc["reason"]},
                anomalies=[
                    {
                        "kind": "data_blocked",
                        "detail": dc["reason"],
                        "decision_date": day_key,
                    }
                ],
                now=now,
            )
        identity = DailyDataIdentity(**dc["identity"])

        # -- freeze_input ------------------------------------------------
        self._stage_freeze(decision_date, identity, now)

        # -- signal（R2：月末调仓/首日建仓；其余=每日审查无订单） --------
        sig = self._stage_signal(decision_date, identity, now)

        # -- risk_check ---------------------------------------------------
        risk = self._stage_risk_check(decision_date, identity, sig, now)

        # -- execute（约定时点=次一交易日执行窗口）-----------------------
        ex = self._stage_execute(decision_date, identity, sig, now)
        if ex["status"] == "pending_window":
            return DayRunResult(
                day_key,
                OUTCOME_PENDING_EXECUTE,
                ex["detail"],
                today_decision=self._today_decision(sig, risk, ex),
            )
        if ex["status"] == "missed_window":
            return self._finish_day(
                decision_date,
                OUTCOME_MISSED_EXECUTION,
                ex["detail"],
                identity,
                sig,
                risk,
                ex,
                now,
            )

        # -- settle + report ---------------------------------------------
        return self._finish_day(
            decision_date,
            OUTCOME_COMPLETED,
            ex.get("detail", ""),
            identity,
            sig,
            risk,
            ex,
            now,
        )

    # -- 各阶段实现 ------------------------------------------------------

    def _stage_data_check(self, decision_date: date, now: datetime) -> dict:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        cached = self.store.get_stage(run_id, day_key, "data_check")
        if cached is not None:
            return cached
        gate: GateResult = self.provider.resolve(
            decision_date,
            symbols=sorted(self.config.target_weights),
            now=now,
        )
        payload: dict[str, Any] = {
            "task_id": make_task_id(run_id, day_key, "data_check"),
            "status": gate.status,
            "reason": gate.reason,
            "checks": [c.to_dict() for c in gate.checks],
            "completed_at": now.isoformat(),
        }
        if gate.status == "ready":
            payload["identity"] = gate.identity.to_dict()  # type: ignore[union-attr]
        self.store.set_stage(run_id, day_key, "data_check", payload)
        self._crash("after_data_check_state")
        return payload

    def _stage_freeze(
        self, decision_date: date, identity: DailyDataIdentity, now: datetime
    ) -> dict:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        cached = self.store.get_stage(run_id, day_key, "freeze_input")
        frozen = {
            "task_id": make_task_id(run_id, day_key, "freeze_input"),
            "identity": identity.to_dict(),
            "strategy_frozen": self.config.to_dict(),
            "frozen_at": now.isoformat(),
        }
        if cached is not None:
            if cached.get("identity") != frozen["identity"]:
                raise NeedsManualReview(
                    f"{day_key} 冻结输入被要求改为不同身份"
                    f"（{cached.get('identity')} → {frozen['identity']}）："
                    "当日输入已冻结；修订须走修订轨迹，不回填原始决策"
                )
            return cached
        self.store.set_stage(run_id, day_key, "freeze_input", frozen)
        self._crash("after_freeze_state")
        return frozen

    def _stage_signal(
        self, decision_date: date, identity: DailyDataIdentity, now: datetime
    ) -> dict:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        cached = self.store.get_stage(run_id, day_key, "signal")
        if cached is not None:
            return cached
        pkg = self.provider.load(identity)

        action, targets, no_trade_reason, rule = "no_trade", None, None, ""
        is_entry = (
            self.config.entry_policy == "first_decision_day"
            and self.checkpoints.load(pkg, self.config.to_ledger_config()) is None
        )
        forced = self._consume_re_evaluate_flag(pkg, decision_date)
        if is_entry:
            action, targets, rule = (
                "entry",
                dict(self.config.target_weights),
                "entry:first_decision_day（冻结配置的一次性建仓）",
            )
        elif is_month_last_trade_date(pkg, decision_date):
            action, targets, rule = (
                "rebalance",
                dict(self.config.target_weights),
                "monthly:signal_on_last_trade_day_of_month",
            )
        elif forced:
            action, targets, rule = (
                "rebalance",
                dict(self.config.target_weights),
                "missed_window_policy=execute_next_window 的下一窗口重估"
                "（事前冻结策略，不回填旧决策）",
            )
        else:
            no_trade_reason = (
                "monthly_rebalance_not_due：每日审查日，月末调仓规则未触发"
                "（不逐日择时）"
            )
            rule = "daily_review_only"
        payload = {
            "task_id": make_task_id(run_id, day_key, "signal"),
            "action": action,
            "targets": targets,
            "no_trade_reason": no_trade_reason,
            "rule": rule,
            "signal_date": day_key,
            # 收盘信号 → 次一交易日约定时点执行（不可倒用当天开盘成交）
            "execution_semantics": "signal_close_T_execute_next_trade_day_open_window",
            "completed_at": now.isoformat(),
        }
        self.store.set_stage(run_id, day_key, "signal", payload)
        self._crash("after_signal_state")
        return payload

    def _stage_risk_check(
        self, decision_date: date, identity: DailyDataIdentity, sig: dict, now: datetime
    ) -> dict:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        cached = self.store.get_stage(run_id, day_key, "risk_check")
        if cached is not None:
            return cached
        pkg = self.provider.load(identity)
        ledger = self.checkpoints.load(pkg, self.config.to_ledger_config())
        pending_actions: list[dict] = []
        if ledger is None:
            review = {
                "state": "pre_entry",
                "buys_allowed": True,
                "note": "账本未建立（建仓决策日）",
            }
        else:
            risk_state = ledger.export_evidence()["risk_state"]
            unconfirmed = [
                ev for ev in risk_state.get("events", []) if not ev.get("confirmed_by")
            ]
            review = {
                "state": risk_state.get("status"),
                "buys_allowed": ledger.risk.buys_allowed,
                "high_water_mark": risk_state.get("high_water_mark"),
                "unconfirmed_risk_events": [ev["risk_event_id"] for ev in unconfirmed],
            }
            for ev in unconfirmed:
                pending_actions.append(
                    {
                        "kind": "risk_confirm_pending",
                        "risk_event_id": ev["risk_event_id"],
                        "detail": "待用户逐线确认后恢复买入（反弹不自动恢复）",
                    }
                )
        has_buys = bool(sig.get("targets"))
        if has_buys and review.get("buys_allowed") is False:
            review["note"] = (
                "风险暂停新增买入：买入腿将由账本拒单（risk_paused），"
                "既定卖出仍执行；额外减仓/清仓/恢复由用户决定"
            )
        payload = {
            "task_id": make_task_id(run_id, day_key, "risk_check"),
            "review": review,
            "pending_actions": pending_actions,
            "completed_at": now.isoformat(),
        }
        self.store.set_stage(run_id, day_key, "risk_check", payload)
        self._crash("after_risk_state")
        return payload

    def _stage_execute(
        self, decision_date: date, identity: DailyDataIdentity, sig: dict, now: datetime
    ) -> dict:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        cached = self.store.get_stage(run_id, day_key, "execute")
        pkg = self.provider.load(identity)
        exec_date = pkg.next_trade_date(decision_date)
        if cached is not None:
            # 幂等重入：核对账本权威状态（结果不明不盲目续）
            self._verify_executed_consistency(cached, pkg, exec_date)
            return cached
        if exec_date is None:
            payload = {
                "task_id": make_task_id(run_id, day_key, "execute"),
                "status": "no_next_trade_date",
                "detail": "决策日后无下一包交易日（包末尾）：不执行",
                "completed_at": now.isoformat(),
            }
            self.store.set_stage(run_id, day_key, "execute", payload)
            return payload

        win = self._execution_window(exec_date)
        if now < win[0]:
            return {
                "status": "pending_window",
                "detail": f"执行窗口未到（{win[0].isoformat()} 开窗）",
                "window": [win[0].isoformat(), win[1].isoformat()],
            }
        missed = now > win[1]

        ledger = self.checkpoints.load(pkg, self.config.to_ledger_config())
        if missed:
            # 错过执行窗口：按事前冻结策略处理，不补写"当时已成交"
            executed_sessions, orders_summary = [], []
            if ledger is not None:
                executed_sessions = self._catch_up_sessions(
                    ledger, pkg, upto=exec_date, reason="missed_execution_window"
                )
                # 补齐的估值 session 也要落检查点（否则丢 session 破坏日历连续）
                self.checkpoints.save(ledger)
            payload = {
                "task_id": make_task_id(run_id, day_key, "execute"),
                "status": "missed_window",
                "policy": self.config.missed_window_policy,
                "detail": (
                    f"执行窗口 [{win[0].isoformat()}~{win[1].isoformat()}] 已错过："
                    f"policy={self.config.missed_window_policy}；订单未执行、"
                    "不回填（补算走修订轨迹）"
                ),
                "execution": self._four_tuple(decision_date, exec_date, executed=False),
                "executed_sessions": [d.isoformat() for d in executed_sessions],
                "orders": [],
                "completed_at": now.isoformat(),
            }
            self.store.set_stage(run_id, day_key, "execute", payload)
            return payload

        # 窗口内：加载/新建账本 → 补齐缺session → 约定时点执行
        if ledger is None:
            ledger = R01Ledger(pkg, self.config.to_ledger_config())
        catchup = self._catch_up_sessions(
            ledger, pkg, upto=exec_date, reason="no_decision_evidence_that_day"
        )
        last_exec = self._last_executed(ledger)
        if last_exec is None or last_exec < exec_date:
            ledger.run_day(exec_date, sig.get("targets"), signal_date=decision_date)
            self._crash("after_execute_ledger_before_checkpoint")
            orders_summary = self._orders_summary(ledger, exec_date)
        else:
            # 检查点已含执行日（崩溃恢复：checkpoint 先于阶段标记落盘）
            orders_summary = self._orders_summary(ledger, exec_date)
        self._crash("after_execute_ledger")  # 检查点保存前崩溃注入点
        payload = {
            "task_id": make_task_id(run_id, day_key, "execute"),
            "status": "executed",
            "execution": self._four_tuple(decision_date, exec_date, executed=True),
            "executed_sessions": [d.isoformat() for d in catchup]
            + [exec_date.isoformat()],
            "orders": orders_summary,
            "completed_at": now.isoformat(),
        }
        self.checkpoints.save(ledger)
        self._crash("after_execute_checkpoint_before_state")
        self.store.set_stage(run_id, day_key, "execute", payload)
        return payload

    # -- settle + report -------------------------------------------------

    def _finish_day(
        self,
        decision_date: date,
        outcome: str,
        detail: str,
        identity: DailyDataIdentity,
        sig: dict,
        risk: dict,
        ex: dict,
        now: datetime,
    ) -> DayRunResult:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        anomalies: list[dict] = []
        reconciliation = None
        if ex.get("status") in ("executed", "missed_window"):
            ledger = self.checkpoints.load(
                self.provider.load(identity), self.config.to_ledger_config()
            )
            if ledger is not None:
                reconciliation = reconcile(ledger)
                if not reconciliation["ok"]:
                    anomalies.append(
                        {
                            "kind": "reconcile_mismatch",
                            "detail": reconciliation["mismatches"][:5],
                        }
                    )
            settle = {
                "task_id": make_task_id(run_id, day_key, "settle"),
                "checkpoint_saved": True,
                "reconciliation": reconciliation,
                "completed_at": now.isoformat(),
            }
            self.store.set_stage(run_id, day_key, "settle", settle)
        self._crash("after_settle_state")

        today = self._today_decision(sig, risk, ex)
        day_rec = {
            "ledger_run_id": run_id,
            "decision_date": day_key,
            "outcome": outcome,
            "detail": detail,
            "identity": identity.to_dict(),
            "today_decision": today,
            "orders_summary": ex.get("orders", []),
            "execution": ex.get("execution"),
            "anomalies": anomalies,
            "pending_actions": risk.get("pending_actions", []),
            "completed_at": now.isoformat(),
        }
        if (
            outcome == OUTCOME_MISSED_EXECUTION
            and self.config.missed_window_policy == "execute_next_window"
        ):
            day_rec["re_evaluate_next"] = True
        self.store.set_day(run_id, day_key, day_rec)
        self._write_status_from_records(now)
        self.store.set_stage(
            run_id,
            day_key,
            "report",
            {
                "task_id": make_task_id(run_id, day_key, "report"),
                "status": "reported",
                "completed_at": now.isoformat(),
            },
        )
        self._beat(now)
        # settle 完成=安全点：received 的控制命令生效
        ctl = self.control.get(run_id)
        if ctl is not None and ctl.state == "received":
            self.control.mark_effective(run_id, now)
        return DayRunResult(
            day_key, outcome, detail, today_decision=today, anomalies=anomalies
        )

    def _finish_simple_day(
        self,
        decision_date: date,
        outcome: str,
        detail: str,
        *,
        today_decision: dict,
        anomalies: list[dict] | None = None,
        now: datetime,
    ) -> DayRunResult:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        day_rec = {
            "ledger_run_id": run_id,
            "decision_date": day_key,
            "outcome": outcome,
            "detail": detail,
            "today_decision": today_decision,
            "anomalies": anomalies or [],
            "pending_actions": [],
            "completed_at": now.isoformat(),
        }
        self.store.set_day(run_id, day_key, day_rec)
        self._write_status_from_records(now)
        self.store.set_stage(
            run_id,
            day_key,
            "report",
            {
                "task_id": make_task_id(run_id, day_key, "report"),
                "status": "reported",
                "completed_at": now.isoformat(),
            },
        )
        self._beat(now)
        # 简单收尾日（休市/受阻）也是安全点：received 的控制命令生效
        ctl = self.control.get(run_id)
        if ctl is not None and ctl.state == "received":
            self.control.mark_effective(run_id, now)
        return DayRunResult(
            day_key,
            outcome,
            detail,
            today_decision=today_decision,
            anomalies=anomalies or [],
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _beat(self, now: datetime) -> None:
        self.store.beat(self.config.ledger_run_id, now)

    def _crash(self, point: str) -> None:
        if point in self.crash_points:
            raise CrashInjection(f"crash_point={point}")

    def _decision_window_verdict(self, decision_date: date, now: datetime) -> str:
        """early（未到截止）/ open / missed（已过截止+超时）。"""
        cutoff = self._wall_time(decision_date, self.config.decision_cutoff)
        deadline = cutoff + timedelta(minutes=self.config.window_timeout_minutes)
        if now < cutoff:
            return "early"
        if now > deadline:
            return "missed"
        return "open"

    def _record_missed_decision(self, decision_date: date, now: datetime) -> dict:
        run_id, day_key = self.config.ledger_run_id, decision_date.isoformat()
        rec = {
            "ledger_run_id": run_id,
            "decision_date": day_key,
            "outcome": OUTCOME_MISSED_DECISION,
            "detail": (
                "决策窗口错过（休眠/停机/迟到）：按事前冻结策略记录缺失，"
                "不事后补写决策、不用错过后的信息回填旧日交易；"
                "重算须走修订轨迹"
            ),
            "today_decision": {
                "action": "missed_decision",
                "reason": "decision window missed",
                "no_trade_reason": "decision_window_missed",
            },
            "anomalies": [{"kind": "missed_decision_window", "decision_date": day_key}],
            "pending_actions": [],
            "completed_at": now.isoformat(),
        }
        if self.config.missed_window_policy == "execute_next_window":
            rec["re_evaluate_next"] = True
        self.store.set_day(run_id, day_key, rec)
        self.store.set_stage(
            run_id,
            day_key,
            "data_check",
            {
                "task_id": make_task_id(run_id, day_key, "data_check"),
                "status": "missed_decision_window",
                "reason": "决策窗口已过，未做决策（不回填）",
                "completed_at": now.isoformat(),
            },
        )
        self._write_status_from_records(now)
        self._beat(now)
        return rec

    def _consume_re_evaluate_flag(
        self, pkg: EtfInputPackage, decision_date: date
    ) -> bool:
        """execute_next_window 策略：上一交易日记录带 re_evaluate_next → 本日重估。"""
        prev = pkg.prev_trade_date(decision_date)
        if prev is None:
            return False
        rec = self.store.get_day(self.config.ledger_run_id, prev.isoformat())
        return bool(rec and rec.get("re_evaluate_next"))

    def _execution_window(self, exec_date: date) -> tuple[datetime, datetime]:
        start = self._wall_time(exec_date, self.config.execution_time)
        return start, start + timedelta(minutes=self.config.window_timeout_minutes)

    def _wall_time(self, day: date, hhmm: str) -> datetime:
        wall = datetime.combine(day, parse_hhmm(hhmm), tzinfo=self._tz)
        return wall.astimezone(timezone.utc) if wall.tzinfo else wall

    def _last_executed(self, ledger: R01Ledger) -> date | None:
        cp = ledger.export_checkpoint()
        ltd = cp.get("last_trade_date")
        return date.fromisoformat(ltd) if ltd else None

    def _catch_up_sessions(
        self, ledger: R01Ledger, pkg: EtfInputPackage, *, upto: date, reason: str
    ) -> list[date]:
        """补齐 last_executed+1 .. upto-1 的无决策 session（估值/公司行动连续性）。

        这些日期没有决策证据（休眠错过/数据受阻），以"无订单估值日"入账——
        如实记录当日无交易，不补写"当时已决策"。
        """
        out: list[date] = []
        last = self._last_executed(ledger)
        if last is None:
            return out
        nxt = pkg.next_trade_date(last)
        while nxt is not None and nxt < upto:
            ledger.run_day(nxt, None)
            out.append(nxt)
            nxt = pkg.next_trade_date(nxt)
        return out

    def _verify_executed_consistency(
        self, cached: dict, pkg: EtfInputPackage, exec_date: date | None
    ) -> None:
        if cached.get("status") != "executed" or exec_date is None:
            return
        ledger = self.checkpoints.load(pkg, self.config.to_ledger_config())
        last = self._last_executed(ledger) if ledger is not None else None
        if last is None or last < exec_date:
            raise NeedsManualReview(
                f"阶段标记 execute=executed 但账本检查点缺 {exec_date}："
                "阶段状态与权威账本矛盾，先核对再续（不自动重跑）"
            )

    def _orders_summary(self, ledger: R01Ledger, exec_date: date) -> list[dict]:
        key = exec_date.isoformat()
        out = []
        for o in ledger.export_view()["days"]:
            if o.get("date") == key:
                out = o.get("orders", [])
                break
        return out

    def _four_tuple(
        self, decision_date: date, exec_date: date, *, executed: bool
    ) -> dict:
        """信号日/订单决策日/成交日/价格口径四元组证据（收盘信号不倒用当天开盘）。"""
        return {
            "signal_date": decision_date.isoformat(),
            "order_decision_date": decision_date.isoformat(),
            "execution_date": exec_date.isoformat(),
            "price_mode": self.config.price_mode,
            "executed": executed,
        }

    def _today_decision(self, sig: dict, risk: dict, ex: dict) -> dict:
        action = sig.get("action", "no_trade")
        reason = sig.get("rule", "")
        no_trade = sig.get("no_trade_reason")
        review = risk.get("review", {})
        if review.get("buys_allowed") is False and sig.get("targets"):
            action = f"{action}_with_buys_risk_paused"
            reason = (
                reason or ""
            ) + "｜风险暂停买入：买入腿拒单 risk_paused，既定卖出仍执行"
        if ex.get("status") == "missed_window":
            action = f"{action}_missed_window"
            no_trade = "execution_window_missed（按冻结策略跳过，不回填）"
        elif ex.get("status") == "pending_window":
            action = f"{action}_pending_execution"
        return {"action": action, "reason": reason, "no_trade_reason": no_trade}

    def _write_status_from_records(self, now: datetime) -> None:
        ledger = self.checkpoints.load(
            self.provider.package, self.config.to_ledger_config()
        )
        self._write_status(ledger, now)

    def _write_status(
        self, ledger: R01Ledger | None, now: datetime, *, extra_note: str = ""
    ) -> None:
        run_id = self.config.ledger_run_id
        day_records = {
            d: self.store.get_day(run_id, d) for d in self.store.list_days(run_id)
        }
        day_records = {d: r for d, r in day_records.items() if r}
        if ledger is not None:
            view = ledger.export_view()
            ledger_summary = {
                "days": [
                    {
                        **{k: v for k, v in d.items() if k != "date"},
                        "hwm": d.get("risk", {}).get("high_water_mark"),
                        "drawdown": (
                            round(1 - d["nav"] / d["risk"]["high_water_mark"], 6)
                            if d.get("risk", {}).get("high_water_mark") and d.get("nav")
                            else None
                        ),
                    }
                    for d in view["days"]
                ],
                "risk": {
                    "buys_allowed": ledger.risk.buys_allowed,
                    "unconfirmed_events": [
                        ev["risk_event_id"]
                        for ev in ledger.export_evidence()["risk_state"]["events"]
                        if not ev.get("confirmed_by")
                    ],
                    "blocked_orders_count": len(ledger.risk_blocked_orders),
                },
            }
        else:
            ledger_summary = None
        ctl = self.control.get(run_id)
        status = build_run_status(
            self.config,
            store=self.store,
            day_records=day_records,
            ledger_summary=ledger_summary,
            schedule_cfg=self.schedule_cfg,
            now=now,
        )
        status["stop_restore_status"] = ctl.to_dict() if ctl else None
        if extra_note:
            status["notes"] = extra_note
        self.store.set_status(run_id, status)
        if self.platform_reporter is not None:
            from backend.services.simulation.virtual_run.states import (
                to_platform_payload,
            )

            try:
                self.platform_reporter(
                    to_platform_payload(status, control=ctl.to_dict() if ctl else None)
                )
            except Exception as exc:  # noqa: BLE001
                status.setdefault("anomalies", []).append(
                    {"kind": "platform_report_failed", "detail": str(exc)}
                )
                self.store.set_status(run_id, status)
