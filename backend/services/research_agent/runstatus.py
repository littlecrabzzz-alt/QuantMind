"""R01 持续虚拟运行状态（H2.2-P1，h2-interfaces §4）。

通道：runner 直写 run_status（本模块 POST 入口；PG 表 research_r01_run_status），
平台只读 GET；不改 data-contract envelope。里程碑/异常事件复用既有
kind=state-change/progress 信封，不在此另建事件流。

展示唯一口径 = §4 字段；next_run_at 仅透传 runner 报告的已配置调度
（quantmind:r01:vr:schedule），无配置 ⇒ pending_activation，不推测时间。
停止/恢复三段（requested/received/effective）只读存储值——平台从不自动推进
阶段，effective 仅当执行端确认写入。
"""

from __future__ import annotations

import time

from psycopg.types.json import Jsonb

WORKSTREAMS = ("A", "B1", "B2", "B3", "D", "N")
RUN_STATES = (
    "running",            # 正常（含当日无订单：today_decision.no_trade_reason 有证据）
    "no_trade_needed",    # 无须交易（有效运行）
    "data_blocked",       # 数据受阻（门控 fail/unknown，不陈旧冒充）
    "failed",             # 失败
    "paused_risk",        # 风险暂停（两线之一触发，待确认）
    "paused_job",         # 作业暂停（用户/运维停止，区别于风险暂停）
)
STAGES = ("requested", "received", "effective")
REQUIRED_TOP = ("ledger_run_id", "strategy_id", "strategy_version", "group",
                "run_state", "input_date", "today_decision", "risk_state",
                "schedule")
ALLOWED_TOP = set(REQUIRED_TOP) | {
    "last_success_at", "last_heartbeat", "positions", "cash",
    "dividend_receivable", "orders", "nav", "drawdown", "hwm",
    "anomalies", "pending_actions", "stop_restore", "note",
}
ALLOWED_INPUT_DATE = ("decision_date", "data_as_of", "obtained_at",
                      "package_id", "manifest_sha256", "release_id")
ALLOWED_DECISION = ("action", "reason", "no_trade_reason")
ALLOWED_RISK = ("status", "loss_line", "drawdown_line", "pending_confirmations",
                "blocked_orders", "high_water_mark")
ALLOWED_STAGE_KEYS = ("job_stop", "job_restore")


class RunStatusError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _check_keys(obj, allowed, label):
    unknown = sorted(set(obj) - set(allowed))
    if unknown:
        raise RunStatusError("schema_violation", f"{label} 含未知字段：{unknown}")


def validate_run_status(payload):
    if not isinstance(payload, dict):
        raise RunStatusError("schema_violation", "run_status 必须是 JSON 对象")
    missing = [k for k in REQUIRED_TOP if k not in payload]
    if missing:
        raise RunStatusError("schema_violation", f"缺少必填字段：{missing}")
    _check_keys(payload, ALLOWED_TOP, "run_status")
    if payload["group"] not in WORKSTREAMS:
        raise RunStatusError("schema_violation", f"group 必须是 {WORKSTREAMS}")
    if payload["run_state"] not in RUN_STATES:
        raise RunStatusError("schema_violation", f"run_state 必须是 {RUN_STATES}")
    for field in ("strategy_id", "strategy_version", "ledger_run_id"):
        if not isinstance(payload[field], (str, int)) or payload[field] == "":
            raise RunStatusError("schema_violation", f"{field} 无效")
    input_date = payload["input_date"]
    if not isinstance(input_date, dict) or not input_date.get("decision_date"):
        raise RunStatusError("schema_violation", "input_date.decision_date 必填")
    _check_keys(input_date, ALLOWED_INPUT_DATE, "input_date")
    decision = payload["today_decision"]
    if not isinstance(decision, dict) or "action" not in decision:
        raise RunStatusError("schema_violation", "today_decision.action 必填")
    _check_keys(decision, ALLOWED_DECISION, "today_decision")
    risk = payload["risk_state"]
    if not isinstance(risk, dict) or "status" not in risk:
        raise RunStatusError("schema_violation", "risk_state.status 必填")
    _check_keys(risk, ALLOWED_RISK, "risk_state")
    schedule = payload["schedule"]
    if not isinstance(schedule, dict) or not isinstance(schedule.get("configured"), bool):
        raise RunStatusError("schema_violation", "schedule.configured 必须是布尔")
    if schedule["configured"] is False and schedule.get("next_run_at"):
        raise RunStatusError(
            "schema_violation",
            "未配置调度不得携带 next_run_at（待启用不显示推测时间）",
        )
    stop_restore = payload.get("stop_restore") or {}
    _check_keys(stop_restore, ALLOWED_STAGE_KEYS, "stop_restore")
    for key in ALLOWED_STAGE_KEYS:
        stage = stop_restore.get(key)
        if stage is not None:
            if not isinstance(stage, dict) or stage.get("stage") not in STAGES:
                raise RunStatusError(
                    "schema_violation",
                    f"stop_restore.{key}.stage 必须是 {STAGES} 之一或整段为空",
                )
    return payload


def derive_view(row_payload, now=None, heartbeat_stale_after=900.0):
    """读取侧派生：心跳陈旧/失联不自动判成败；三段只读存储值。"""
    now = now or time.time()
    heartbeat = row_payload.get("last_heartbeat")
    stale = bool(
        heartbeat and now - heartbeat > heartbeat_stale_after
    )
    run_state = row_payload["run_state"]
    if stale and run_state in ("running", "no_trade_needed"):
        display_state = "stale_heartbeat"  # 陈旧心跳：显示过期，不判失败/成功
    else:
        display_state = {
            "running": "正常",
            "no_trade_needed": "无须交易",
            "data_blocked": "数据受阻",
            "failed": "失败",
            "paused_risk": "风险暂停",
            "paused_job": "作业暂停",
        }[run_state]
    schedule = row_payload.get("schedule") or {}
    configured = schedule.get("configured") is True
    next_run_at = schedule.get("next_run_at") if configured else None
    return {
        "display_state": display_state,
        "heartbeat_stale": stale,
        "next_run_at": next_run_at,
        "next_run_at_source": (
            "runner-reported schedule（quantmind:r01:vr:schedule）"
            if configured else None
        ),
        "activation": "configured" if configured else "pending_activation",
        # 三段状态机只读：effective 仅当执行端已确认写入
        "stop_restore": row_payload.get("stop_restore") or {},
    }


class RunStatusStore:
    """research_r01_run_status 持久层（research_agent 域）。"""

    def __init__(self, pool):
        self.pool = pool

    async def upsert(self, owner, node, payload, received_at):
        """直写当前状态；decision_date 回退的迟到写入被忽略（显式返回标志）。"""
        async with self.pool.connection() as db, db.transaction():
            row = await self._select_for_update(
                db, owner, node, payload["ledger_run_id"]
            )
            if row and payload["input_date"]["decision_date"] < row["decision_date"]:
                return {"stored": False, "ignored": "stale_write",
                        "kept_decision_date": row["decision_date"]}
            await db.execute(
                """INSERT INTO research_r01_run_status
                (tenant_id,node_id,ledger_run_id,decision_date,run_state,schedule_configured,
                 payload,received_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(tenant_id,node_id,ledger_run_id) DO UPDATE SET
                decision_date=EXCLUDED.decision_date, run_state=EXCLUDED.run_state,
                schedule_configured=EXCLUDED.schedule_configured,
                payload=EXCLUDED.payload, received_at=EXCLUDED.received_at,
                updated_at=now()""",
                (owner[0], node, payload["ledger_run_id"],
                 payload["input_date"]["decision_date"], payload["run_state"],
                 (payload.get("schedule") or {}).get("configured") is True,
                 Jsonb(payload), received_at),
            )
            return {"stored": True, "ignored": None}

    async def _select_for_update(self, db, owner, node, ledger_run_id):
        return await (
            await db.execute(
                """SELECT decision_date, payload FROM research_r01_run_status
                WHERE tenant_id=%s AND node_id=%s AND ledger_run_id=%s FOR UPDATE""",
                (owner[0], node, ledger_run_id),
            )
        ).fetchone()

    async def list(self, owner, node):
        async with self.pool.connection() as db:
            rows = await (
                await db.execute(
                    """SELECT ledger_run_id, payload, received_at, updated_at
                    FROM research_r01_run_status
                    WHERE tenant_id=%s AND node_id=%s ORDER BY updated_at DESC LIMIT 50""",
                    (owner[0], node),
                )
            ).fetchall()
        return rows
