"""运行配置、阶段状态、心跳、run_status 与停止/恢复三段状态机。

（h2-interfaces §3/§4；Redis 键全部在 ``quantmind:r01:vr:*`` db0 专用
前缀内，遵守 AGENTS Redis 库分配，不占用活盘键空间。）

- 任务幂等键 ``r01vr_task_id = f"{ledger_run_id}:{decision_date}:{stage}"``，
  stage 状态记录即幂等凭据：同键重试返回该阶段既有结果；
- 阶段恢复点落 ``quantmind:r01:vr:state:{run}:{date}:{stage}``（长 TTL），
  账本权威状态落 ReplayLedgerCheckpoint（recovery.py）；
- 心跳 ``quantmind:r01:vr:heartbeat:{run}``；状态快照
  ``quantmind:r01:vr:status:{run}``（p04 只读 GET 消费口径，见 §4）；
- 停止/恢复三段 ``quantmind:r01:vr:control:{run}``：
  requested → received → effective，仅执行端确认后 effective。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.services.simulation.replay.r01_ledger import make_virtual_run_id
from backend.services.simulation.virtual_run.clock import parse_hhmm

STAGES = (
    "data_check",
    "freeze_input",
    "signal",
    "risk_check",
    "execute",
    "settle",
    "report",
)


def make_task_id(ledger_run_id: str, decision_date: date | str, stage: str) -> str:
    """任务幂等键（h2-interfaces §3）：``{run}:{date}:{stage}``。"""
    d = (
        decision_date.isoformat()
        if isinstance(decision_date, date)
        else str(decision_date)
    )
    if stage not in STAGES:
        raise ValueError(f"非法 stage {stage!r}（允许 {STAGES}）")
    return f"{ledger_run_id}:{d}:{stage}"


# ---------------------------------------------------------------------------
# 冻结运行配置（启用候选来自研究冻结方案；未配置=待启用，不自动跑）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VirtualRunConfig:
    """一个 r01vr 持续虚拟运行的冻结定义。

    - ledger_run_id = ``r01vr-<group>-<strategy_id>-v<version>``（p03 已合入）；
    - 策略语义=月度调仓+每日审查（R2）：目标权重与规则参数冻结在配置里，
      不存在逐日择时输入；无新订单的决策日也是有证据的有效运行；
    - 错过窗口策略（R3/R4）事前冻结：``missed_window_policy``；
    - 启用与否由调度配置（Redis schedule 键）决定，代码无内置默认开启。
    """

    group: str
    strategy_id: str
    strategy_version: int
    initial_cash: float = 30000.0  # 默认 3 万情景（2 万粒度检查属校验项）
    target_weights: dict[str, float] = field(default_factory=dict)
    # 账本引擎假设（与 R01LedgerConfig 同口径）
    commission_rate: float = 0.0003
    commission_min: float = 0.0
    slippage_bps: float = 5.0
    price_mode: str = "open"
    loss_line_amount: float | None = None  # None=initial×30%（3 万=9000）
    drawdown_pct: float = 0.30
    stale_mark_limit: int = 5
    # 调度语义（冻结；未配置调度=待启用不运行）
    timezone_name: str = "Asia/Shanghai"
    decision_cutoff: str = "15:10"  # 决策截止（收盘后）
    execution_time: str = "09:31"  # 约定执行时点（次一交易日开盘）
    window_timeout_minutes: int = 30  # 决策/执行窗口超时
    max_retries: int = 2
    missed_window_policy: str = "skip_and_record"  # | execute_next_window
    # 建仓语义：首个决策日一次性建仓（月度调仓之外的一次性入口，冻结配置）
    entry_policy: str = "first_decision_day"
    # 数据源（v2 固定包 + 日增量包；p02 D1 合入前由 fixture stub 供数）
    package_root: str = ""
    manifest_sha256: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.missed_window_policy not in ("skip_and_record", "execute_next_window"):
            raise ValueError(
                "missed_window_policy ∈ {skip_and_record, execute_next_window}"
            )
        if self.initial_cash not in (20000.0, 30000.0):
            # 粒度检查：情景本金限定 2 万/3 万档（研究比较口径）
            raise ValueError("initial_cash 限定 20000/30000 情景档")
        parse_hhmm(self.decision_cutoff)
        parse_hhmm(self.execution_time)
        object.__setattr__(
            self, "target_weights", dict(sorted(self.target_weights.items()))
        )

    @property
    def ledger_run_id(self) -> str:
        return make_virtual_run_id(self.group, self.strategy_id, self.strategy_version)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def to_ledger_config(self):
        """映射为 p03 R01LedgerConfig（run_kind=virtual，r01vr- 身份）。"""
        from backend.services.simulation.replay.r01_ledger import R01LedgerConfig

        return R01LedgerConfig(
            group=self.group,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            execution_attempt_id=1,  # virtual 无 attempt 段（身份由 run_kind 决定）
            initial_cash=self.initial_cash,
            run_kind="virtual",
            loss_line_amount=self.loss_line_amount,
            drawdown_pct=self.drawdown_pct,
            commission_rate=self.commission_rate,
            commission_min=self.commission_min,
            slippage_bps=self.slippage_bps,
            price_mode=self.price_mode,
            stale_mark_limit=self.stale_mark_limit,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_run_id": self.ledger_run_id,
            "group": self.group,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "initial_cash": self.initial_cash,
            "target_weights": dict(self.target_weights),
            "commission_rate": self.commission_rate,
            "commission_min": self.commission_min,
            "slippage_bps": self.slippage_bps,
            "price_mode": self.price_mode,
            "loss_line_amount": self.loss_line_amount,
            "drawdown_pct": self.drawdown_pct,
            "timezone_name": self.timezone_name,
            "decision_cutoff": self.decision_cutoff,
            "execution_time": self.execution_time,
            "window_timeout_minutes": self.window_timeout_minutes,
            "max_retries": self.max_retries,
            "missed_window_policy": self.missed_window_policy,
            "entry_policy": self.entry_policy,
            "package_root": self.package_root,
            "manifest_sha256": self.manifest_sha256,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VirtualRunConfig:
        return cls(
            group=d["group"],
            strategy_id=d["strategy_id"],
            strategy_version=int(d["strategy_version"]),
            initial_cash=float(d.get("initial_cash", 30000.0)),
            target_weights=dict(d.get("target_weights") or {}),
            commission_rate=float(d.get("commission_rate", 0.0003)),
            commission_min=float(d.get("commission_min", 0.0)),
            slippage_bps=float(d.get("slippage_bps", 5.0)),
            price_mode=str(d.get("price_mode", "open")),
            loss_line_amount=d.get("loss_line_amount"),
            drawdown_pct=float(d.get("drawdown_pct", 0.30)),
            timezone_name=str(d.get("timezone_name", "Asia/Shanghai")),
            decision_cutoff=str(d.get("decision_cutoff", "15:10")),
            execution_time=str(d.get("execution_time", "09:31")),
            window_timeout_minutes=int(d.get("window_timeout_minutes", 30)),
            max_retries=int(d.get("max_retries", 2)),
            missed_window_policy=str(d.get("missed_window_policy", "skip_and_record")),
            entry_policy=str(d.get("entry_policy", "first_decision_day")),
            package_root=str(d.get("package_root", "")),
            manifest_sha256=str(d.get("manifest_sha256", "")),
            notes=str(d.get("notes", "")),
        )


# ---------------------------------------------------------------------------
# 阶段状态 / 日记录 / 心跳 / 状态快照 存储
# ---------------------------------------------------------------------------

_STATE_KEY = "quantmind:r01:vr:state:{run}:{date}:{stage}"
_DAY_KEY = "quantmind:r01:vr:day:{run}:{date}"
_HEARTBEAT_KEY = "quantmind:r01:vr:heartbeat:{run}"
_STATUS_KEY = "quantmind:r01:vr:status:{run}"
_CONTROL_KEY = "quantmind:r01:vr:control:{run}"
_SCHEDULE_KEY = "quantmind:r01:vr:schedule:{run}"

DEFAULT_STATE_TTL = 400 * 24 * 3600  # 恢复点长保留（约 13 个月）


class RunStateStore(Protocol):
    """阶段恢复点 + 日记录 + 心跳 + run_status 的存取协议。"""

    def get_stage(self, run_id: str, decision_date: str, stage: str) -> dict | None: ...
    def set_stage(
        self, run_id: str, decision_date: str, stage: str, payload: dict
    ) -> None: ...
    def get_day(self, run_id: str, decision_date: str) -> dict | None: ...
    def set_day(self, run_id: str, decision_date: str, payload: dict) -> None: ...
    def beat(self, run_id: str, ts: datetime, ttl: int = 7 * 24 * 3600) -> None: ...
    def last_heartbeat(self, run_id: str) -> str | None: ...
    def set_status(self, run_id: str, status: dict) -> None: ...
    def get_status(self, run_id: str) -> dict | None: ...
    def list_days(self, run_id: str) -> list[str]: ...


class InMemoryRunStateStore:
    """确定性验收/单测后端（进程内，无 Redis 依赖）。"""

    def __init__(self) -> None:
        self._stages: dict[tuple[str, str, str], dict] = {}
        self._days: dict[tuple[str, str], dict] = {}
        self._beats: dict[str, datetime] = {}
        self._status: dict[str, dict] = {}

    def get_stage(self, run_id, decision_date, stage):
        return self._stages.get((run_id, decision_date, stage))

    def set_stage(self, run_id, decision_date, stage, payload):
        self._stages[(run_id, decision_date, stage)] = dict(payload)

    def get_day(self, run_id, decision_date):
        return self._days.get((run_id, decision_date))

    def set_day(self, run_id, decision_date, payload):
        self._days[(run_id, decision_date)] = dict(payload)

    def beat(self, run_id, ts, ttl=7 * 24 * 3600):
        self._beats[run_id] = ts

    def last_heartbeat(self, run_id):
        ts = self._beats.get(run_id)
        return ts.isoformat() if ts else None

    def set_status(self, run_id, status):
        self._status[run_id] = dict(status)

    def get_status(self, run_id):
        return self._status.get(run_id)

    def list_days(self, run_id):
        return sorted(d for r, d in self._days if r == run_id)


class RedisRunStateStore:
    """Redis db0 后端（生产/沙盒；键见模块 docstring）。"""

    def __init__(self, redis_url: str, *, state_ttl: int = DEFAULT_STATE_TTL):
        import redis

        self._r = redis.from_url(redis_url, socket_timeout=3)
        self._ttl = state_ttl

    def _k_state(self, run_id, decision_date, stage):
        return _STATE_KEY.format(run=run_id, date=decision_date, stage=stage)

    def get_stage(self, run_id, decision_date, stage):
        raw = self._r.get(self._k_state(run_id, decision_date, stage))
        return json.loads(raw) if raw else None

    def set_stage(self, run_id, decision_date, stage, payload):
        self._r.set(
            self._k_state(run_id, decision_date, stage),
            json.dumps(payload, ensure_ascii=False, default=str),
            ex=self._ttl,
        )

    def get_day(self, run_id, decision_date):
        raw = self._r.get(_DAY_KEY.format(run=run_id, date=decision_date))
        return json.loads(raw) if raw else None

    def set_day(self, run_id, decision_date, payload):
        self._r.set(
            _DAY_KEY.format(run=run_id, date=decision_date),
            json.dumps(payload, ensure_ascii=False, default=str),
            ex=self._ttl,
        )

    def beat(self, run_id, ts, ttl=7 * 24 * 3600):
        self._r.set(_HEARTBEAT_KEY.format(run=run_id), ts.isoformat(), ex=ttl)

    def last_heartbeat(self, run_id):
        v = self._r.get(_HEARTBEAT_KEY.format(run=run_id))
        return v.decode() if v else None

    def set_status(self, run_id, status):
        self._r.set(
            _STATUS_KEY.format(run=run_id),
            json.dumps(status, ensure_ascii=False, default=str),
        )

    def get_status(self, run_id):
        raw = self._r.get(_STATUS_KEY.format(run=run_id))
        return json.loads(raw) if raw else None

    def list_days(self, run_id):
        keys = self._r.scan_iter(match=_DAY_KEY.format(run=run_id, date="*"), count=200)
        out = []
        for k in keys:
            key = k.decode() if isinstance(k, bytes) else str(k)
            out.append(key.rsplit(":", 1)[1])
        return sorted(out)


# ---------------------------------------------------------------------------
# 停止/恢复三段状态机（H2.2-R6：requested → received → effective）
# ---------------------------------------------------------------------------


@dataclass
class ControlState:
    command: str  # stop | resume
    state: str  # requested | received | effective
    requested_by: str
    requested_at: str
    received_at: str | None = None
    effective_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "state": self.state,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "received_at": self.received_at,
            "effective_at": self.effective_at,
        }


class ControlBoard:
    """三段控制面。用户/平台 request；执行端（runner tick）确认。

    - ``request``：写入 requested（新请求覆盖旧请求的 command 时须先生效
      或显式取消——简化：仅允许在非 effective 状态改写为反向命令）；
    - runner ``tick``：requested → received（执行端已读到）；
    - runner ``mark_effective``：安全点（当日 settle 完成后 / 新决策日开始前）
      才置 effective；对外展示以 effective 为准。
    """

    def __init__(self, store: RunStateStore):
        self._store = store

    def request(
        self, run_id: str, command: str, *, requested_by: str, now: datetime
    ) -> ControlState:
        if command not in ("stop", "resume"):
            raise ValueError("command ∈ {stop, resume}")
        cur = self.get(run_id)
        if cur is not None and cur.state != "effective" and cur.command != command:
            # 反向命令须等待当前命令生效（避免 requested 覆盖语义混乱）
            raise ValueError(
                f"当前控制 {cur.command}:{cur.state} 未生效，不能直接改请求 {command}"
            )
        st = ControlState(
            command=command,
            state="requested",
            requested_by=requested_by,
            requested_at=now.isoformat(),
        )
        self._put(run_id, st)
        return st

    def get(self, run_id: str) -> ControlState | None:
        st = self._store.get_stage(run_id, "_control", "control")
        if st is None:
            return None
        return ControlState(
            command=st["command"],
            state=st["state"],
            requested_by=st["requested_by"],
            requested_at=st["requested_at"],
            received_at=st.get("received_at"),
            effective_at=st.get("effective_at"),
        )

    def _put(self, run_id: str, st: ControlState) -> None:
        self._store.set_stage(run_id, "_control", "control", st.to_dict())

    def tick(self, run_id: str, now: datetime) -> ControlState | None:
        """runner 每次运行开始时调用：requested → received。"""
        st = self.get(run_id)
        if st is not None and st.state == "requested":
            st.state = "received"
            st.received_at = now.isoformat()
            self._put(run_id, st)
        return self.get(run_id)

    def mark_effective(self, run_id: str, now: datetime) -> ControlState | None:
        st = self.get(run_id)
        if st is not None and st.state == "received":
            st.state = "effective"
            st.effective_at = now.isoformat()
            self._put(run_id, st)
        return self.get(run_id)

    def stop_effective(self, run_id: str) -> bool:
        st = self.get(run_id)
        return st is not None and st.command == "stop" and st.state == "effective"


# ---------------------------------------------------------------------------
# 调度配置（Redis db0；无内置默认调度——未配置即不运行）
# ---------------------------------------------------------------------------


DEFAULT_SCHEDULE_CFG = {
    "enabled": False,  # 未显式启用一律不派发（对齐 market_sync_scheduler 模式）
}


def schedule_key(ledger_run_id: str) -> str:
    return _SCHEDULE_KEY.format(run=ledger_run_id)


def get_redis_schedule(r, ledger_run_id: str) -> dict | None:
    """读调度配置；返回 None=未配置（待启用）。r=redis client。"""
    raw = r.get(schedule_key(ledger_run_id))
    return json.loads(raw) if raw else None


def list_redis_schedules(r) -> dict[str, dict]:
    """列出全部已配置调度（SCAN，只读）。"""
    out: dict[str, dict] = {}
    for k in r.scan_iter(match=_SCHEDULE_KEY.format(run="*"), count=200):
        key = k.decode() if isinstance(k, bytes) else str(k)
        run_id = key.rsplit(":", 1)[1]
        raw = r.get(key)
        if raw:
            cfg = json.loads(raw)
            out[run_id] = cfg if isinstance(cfg, dict) else json.loads(cfg)
    return out


def save_redis_schedule(r, ledger_run_id: str, cfg: dict) -> dict:
    normalized = {**DEFAULT_SCHEDULE_CFG, **cfg}
    normalized["enabled"] = bool(normalized.get("enabled"))
    r.set(schedule_key(ledger_run_id), json.dumps(normalized, ensure_ascii=False))
    return normalized


# ---------------------------------------------------------------------------
# run_status 构建（h2-interfaces §4 字段口径；p04 只读消费）
# ---------------------------------------------------------------------------


def build_run_status(
    config: VirtualRunConfig,
    *,
    store: RunStateStore,
    day_records: dict[str, dict],
    ledger_summary: dict | None,
    schedule_cfg: dict | None,
    now: datetime,
    anomalies: list[dict] | None = None,
    pending_actions: list[dict] | None = None,
) -> dict[str, Any]:
    """组装 run_status 对象（§4 表格字段逐一对应）。

    ``ledger_summary`` 来自账本公共导出（export_view/evidence 同源），本
    模块不另写展示账本；``schedule_cfg`` 为 None ⇒ next_run_at=pending_activation
    （仅来自实际已配置调度，不显示推测时间）。
    """
    last_date = max(day_records) if day_records else None
    last_rec = day_records.get(last_date) if last_date else None
    identity = (last_rec or {}).get("identity") or {}
    ls = ledger_summary or {}

    if schedule_cfg is None:
        next_run_at = "pending_activation"
    elif not schedule_cfg.get("enabled"):
        next_run_at = "pending_activation"
    else:
        next_run_at = (
            f"schedule: cutoff {schedule_cfg.get('decision_cutoff', config.decision_cutoff)}"
            f" @ {schedule_cfg.get('timezone_name', config.timezone_name)}"
        )

    days = ls.get("days") or []
    latest_day = days[-1] if days else {}
    risk = ls.get("risk") or {}

    return {
        # 身份
        "ledger_run_id": config.ledger_run_id,
        "strategy_id": config.strategy_id,
        "strategy_version": config.strategy_version,
        "group": config.group,
        # 输入
        "input_date": {
            "decision_date": last_rec.get("decision_date") if last_rec else None,
            "daily_data_identity": identity or None,
        },
        # 心跳/成功
        "last_heartbeat": store.last_heartbeat(config.ledger_run_id),
        "last_success_at": max(
            (
                r.get("completed_at")
                for r in day_records.values()
                if r.get("completed_at")
            ),
            default=None,
        ),
        # 今日决策（无订单也是有证据的有效运行）
        "today_decision": (last_rec or {}).get("today_decision"),
        # 账本导出（H1 公共出口同源）
        "positions": latest_day.get("positions"),
        "cash": latest_day.get("cash"),
        "dividend_receivable": latest_day.get("dividend_receivable"),
        "orders": (last_rec or {}).get("orders_summary"),
        "nav": latest_day.get("nav"),
        "drawdown": latest_day.get("drawdown"),
        "hwm": latest_day.get("hwm"),
        # 风险
        "risk_state": {
            "buys_allowed": risk.get("buys_allowed"),
            "unconfirmed_events": risk.get("unconfirmed_events"),
            "blocked_orders_count": risk.get("blocked_orders_count", 0),
        },
        # 异常/待处置
        "anomalies": anomalies or (last_rec or {}).get("anomalies", []),
        "pending_actions": pending_actions
        or (last_rec or {}).get("pending_actions", []),
        # 调度
        "next_run_at": next_run_at,
        "stop_restore_status": None,
        "generated_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# p04 平台回报适配（POST /r01/run-status；h2-interfaces §4 通道）
# ---------------------------------------------------------------------------


def _to_epoch(value) -> float | None:
    """ISO 时间 → epoch 秒（p04 derive_view 心跳陈旧判断用算术比较）。"""
    if value is None:
        return None
    try:
        from datetime import datetime as _dt

        return _dt.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def to_platform_payload(
    status: dict[str, Any],
    *,
    control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """内部 run_status → p04 runstatus.validate_run_status 的 POST 载荷。

    - run_state 映射：running / no_trade_needed / data_blocked / paused_risk /
      paused_job / failed（无订单的有效运行=no_trade_needed）；
    - schedule.configured 仅当存在已启用调度；未配置不带 next_run_at
      （待启用不显示推测时间，平台侧强校验）；
    - 三段停止/恢复按平台字段（job_stop/job_restore）只读透传。
    """
    today = status.get("today_decision") or {}
    action = str(today.get("action") or "")
    risk = status.get("risk_state") or {}
    anomalies = status.get("anomalies") or []

    if (
        control
        and control.get("command") == "stop"
        and control.get("state") == "effective"
    ):
        run_state = "paused_job"
    elif risk.get("buys_allowed") is False:
        run_state = "paused_risk"
    elif status.get("input_date", {}).get("decision_date") is None:
        run_state = "no_trade_needed"  # 尚无任何决策日（待启用后首日）
    elif action.startswith("data_blocked"):
        run_state = "data_blocked"
    elif any(a.get("kind") == "data_blocked" for a in anomalies):
        run_state = "data_blocked"
    elif action in ("", "no_trade", "not_trade_day", "entry", "rebalance") or (
        action.startswith(("no_trade", "entry", "rebalance", "missed"))
    ):
        run_state = (
            "no_trade_needed"
            if "rebalance" not in action and "entry" not in action
            else "running"
        )
    else:
        run_state = "running"

    identity = status.get("input_date", {}).get("daily_data_identity") or {}
    schedule = status.get("next_run_at")
    configured = isinstance(schedule, str) and schedule.startswith("schedule:")
    sched_obj: dict[str, Any] = {"configured": configured}
    if configured:
        sched_obj["next_run_at"] = schedule

    stop_restore: dict[str, Any] = {}
    if control:
        key = "job_stop" if control.get("command") == "stop" else "job_restore"
        stop_restore[key] = {
            "stage": control.get("state"),
            "requested_at": control.get("requested_at"),
            "requested_by": control.get("requested_by"),
        }

    return {
        "ledger_run_id": status["ledger_run_id"],
        "strategy_id": status["strategy_id"],
        "strategy_version": status["strategy_version"],
        "group": status["group"],
        "run_state": run_state,
        "input_date": {
            "decision_date": status.get("input_date", {}).get("decision_date"),
            "data_as_of": identity.get("data_as_of"),
            "obtained_at": identity.get("obtained_at"),
            "package_id": identity.get("package_id"),
            "manifest_sha256": identity.get("manifest_sha256"),
            "release_id": identity.get("source_release_id"),
        },
        "today_decision": {
            k: v
            for k, v in (
                {
                    "action": today.get("action") or "pending",
                    "reason": today.get("reason") or "",
                    "no_trade_reason": today.get("no_trade_reason"),
                }.items()
            )
            if v is not None
        },
        "risk_state": {
            "status": ("paused" if risk.get("buys_allowed") is False else "active"),
            "pending_confirmations": risk.get("unconfirmed_events") or [],
            "blocked_orders": risk.get("blocked_orders_count", 0),
            "high_water_mark": status.get("hwm"),
        },
        "schedule": sched_obj,
        "last_success_at": status.get("last_success_at"),
        "last_heartbeat": _to_epoch(status.get("last_heartbeat")),
        "positions": status.get("positions"),
        "cash": status.get("cash"),
        "dividend_receivable": status.get("dividend_receivable"),
        "orders": status.get("orders"),
        "nav": status.get("nav"),
        "drawdown": status.get("drawdown"),
        "hwm": status.get("hwm"),
        "anomalies": anomalies,
        "pending_actions": status.get("pending_actions") or [],
        "stop_restore": stop_restore or None,
    }


def post_platform_status(
    payload: dict[str, Any],
    *,
    base_url: str,
    internal_secret: str,
    node: str | None = None,
    tenant_id: str = "default",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """POST /r01/run-status（研究 agent 网关；best-effort 由调用方决定）。"""
    import json as _json
    import urllib.request

    url = base_url.rstrip("/") + "/r01/run-status"
    req = urllib.request.Request(
        url,
        data=_json.dumps(payload, ensure_ascii=False, default=str).encode(),
        headers={
            "Content-Type": "application/json",
            "x-internal-call": internal_secret,
            "x-tenant-id": tenant_id,
            **({"x-research-node": node} if node else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode())
