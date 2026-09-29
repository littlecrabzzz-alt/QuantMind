"""Small state transitions stored in existing research_drafts JSON, not a new queue DB."""

from __future__ import annotations
import copy
import hashlib
import json
import time
import uuid
from .glm_quota import quota_decision, retry_delay

TOPICS = {
    "data_coverage": ("数据覆盖与完整性", "核对固定输入覆盖、缺失与重复。", "D"),
    "data_semantics": ("数据口径与时点", "核对复权、分红、证券池及可用时点。", "D"),
    "research_review": (
        "研究证据复核",
        "检查归因、对照与统计主张是否受证据支持。",
        "R",
    ),
    "method_review": ("研究方法与可行性", "比较新机制与所需数据的可行性。", "R"),
    "trend": ("趋势规则研究", "研究可解释的趋势信号及反弹/震荡失效情境。", "B1"),
    "momentum": (
        "动量与资产轮动",
        "研究相对动量、集中度及绝对趋势条件的独立增量。",
        "B2",
    ),
    "stock_signal": (
        "A股量价与横截面因子",
        "研究动量、反转、成交量确认的增量信息与失效条件。",
        "B1",
    ),
    "stock_risk": (
        "A股风险与流动性因子",
        "研究低波动、流动性与拥挤代理变量的独立信息及成本敏感性。",
        "B3",
    ),
    "risk": ("风险仓位与组合", "研究波动仓位及组合互补性，明确收益与回撤取舍。", "B3"),
}
TERMINAL = {"done", "failed", "blocked", "cancelled"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def add_task(c, topic, question, reason, parent=None, kind="research"):
    if topic not in TOPICS or not question.strip() or len(question) > 2000:
        raise ValueError("invalid_task_scope")
    if topic.startswith("stock_"):
        kind = "stock_factor"
    ancestor = c["tasks"].get(parent, {})
    identity = [topic, question.strip(), kind]
    if ancestor.get("family_id"):
        identity.append(ancestor["family_id"])
    key = fingerprint(identity)[:24]
    if key in c["tasks"]:
        return key
    review = kind == "evidence_review"
    if sum(
        t["status"] not in TERMINAL and (t["kind"] == "evidence_review") == review
        for t in c["tasks"].values()
    ) >= (6 if review else 20):
        raise ValueError("ready_queue_full")
    c["tasks"][key] = {
        "id": key,
        "topic": topic,
        "question": question.strip(),
        "reason": reason[:2000],
        "parent": parent,
        "kind": kind,
        "status": "queued",
        "created_at": time.time(),
        "attempts": 0,
        "retry_at": 0,
        "lease": None,
        "lease_until": 0,
        "last_activity": None,
        "step": "等待领取",
        "experiments": {},
        "reports": [],
        "tool_receipts": {},
        "usage": {"input": 0, "output": 0, "unknown_calls": 0, "calls": 0},
    }
    if ancestor.get("family_id"):
        c["tasks"][key]["family_id"] = ancestor["family_id"]
        # Same-family descendants use explicit trusted references, never a raw
        # parent report containing arbitrary historical evaluation material.
        c["tasks"][key]["reference_backtest_ids"] = list(
            dict.fromkeys(
                [
                    *[
                        e["backtest_id"]
                        for e in ancestor["experiments"].values()
                        if e.get("backtest_id")
                    ],
                    *ancestor.get("reference_backtest_ids", []),
                ]
            )
        )[:6]
        c["tasks"][key]["research_brief"] = copy.deepcopy(
            ancestor.get("research_brief", {})
        )
    return key


def family_budget(c, t):
    family = c.get("research_families", {}).get(t.get("family_id"))
    if not family:
        return None
    spent = sum(
        len(set(x["experiments"]) | set(x.get("experiment_reservations", {})))
        for x in c["tasks"].values()
        if x.get("family_id") == t["family_id"]
    )
    return {
        "family_id": t["family_id"],
        "limit": family["max_new_experiments"],
        "used": spent,
        "remaining": max(0, family["max_new_experiments"] - spent),
    }


def initial(contract):
    c = {
        "version": 1,
        "desired": "stopped",
        "status": "stopped",
        "contract": contract,
        "tasks": {},
        "quota": {"status": "unknown", "remaining_percent": None},
        "quota_blocked_at": 0,
        "quota_retry_at": 0,
        "controller": None,
        "generation": 0,
        "last_heartbeat": None,
        "events": [],
        "sequence": 0,
    }
    for topic in ("trend", "momentum", "risk"):
        _, goal, _ = TOPICS[topic]
        add_task(
            c,
            topic,
            goal + " 先登记假设，采用统一条件，通过公共回测检验并形成结论。",
            "用户授权范围内的首批独立研究；不修改任何已有策略或账户。",
        )
    return c


def promote_followups(c):
    """Persist conclusions even when the bounded execution queue is full."""
    for task in list(c["tasks"].values()):
        for report in task["reports"]:
            for proposal in report.get("followups", []):
                if proposal.get("task_id"):
                    continue
                if proposal.get("kind", "experiment") == "evidence_review":
                    proposal["awaiting_evidence"] = True
                    continue
                budget = family_budget(c, task)
                if budget and budget["remaining"] == 0:
                    proposal["awaiting_family_budget_review"] = True
                    continue
                try:
                    proposal["task_id"] = add_task(
                        c,
                        proposal["topic"],
                        proposal["question"],
                        proposal["reason"],
                        parent=task["id"],
                    )
                except ValueError as exc:
                    if str(exc) != "ready_queue_full":
                        raise
                    return


def record(c, kind, **fields):
    c["sequence"] += 1
    c["events"].append(
        {"seq": c["sequence"], "at": time.time(), "kind": kind, **fields}
    )
    c["events"] = c["events"][-1000:]


def control(c, action):
    if action not in ("start", "stop"):
        raise ValueError("invalid_control")
    desired = "running" if action == "start" else "stopped"
    if c["desired"] == desired:
        return
    c["desired"] = desired
    c["generation"] += 1
    for t in c["tasks"].values():
        if t["status"] == "running":
            t["status"] = "stopping"
        elif action == "start" and t["status"] == "cancelled":
            t.update(status="queued", retry_at=0, step="从已保存的研究步骤继续")
    c["status"] = "starting" if action == "start" else "stopping"
    record(c, "control", action=action)


def quota_update(c, quota, now):
    c["quota"] = quota
    decision, check_at = quota_decision(
        quota, now, c["contract"].get("reserve_percent", 1)
    )
    # A provider denial stays latched until both its retry deadline has passed
    # and a genuinely newer positive quota observation has arrived.
    if c.get("quota_blocked_at"):
        remaining = quota.get("remaining_percent")
        floor = c.get("quota_blocked_floor", 100)
        recovered = isinstance(remaining, (float, int)) and remaining > floor
        reset = c.get("quota_blocked_reset")
        reset_elapsed = reset is not None and now >= reset
        if (
            now < c.get("quota_retry_at", 0)
            or quota.get("observed_at", 0) <= c["quota_blocked_at"]
            or not (recovered or reset_elapsed)
        ):
            decision, check_at = (
                "waiting_quota",
                max(now + 30, c.get("quota_retry_at", 0)),
            )
        if isinstance(remaining, (float, int)):
            c["quota_blocked_floor"] = min(floor, remaining)
    if decision == "available":
        c["quota_blocked_at"] = c["quota_retry_at"] = 0
    c["quota_state"], c["quota_check_at"] = decision, check_at
    return decision


def claim(c, worker, now):
    recover(c, now)
    if c["desired"] != "running":
        return None
    if quota_update(c, c["quota"], now) != "available":
        c["status"] = c["quota_state"]
        return None
    promote_followups(c)
    active = [t for t in c["tasks"].values() if t["status"] in ("running", "stopping")]
    if len(active) >= c["contract"].get("concurrency", 3):
        return None
    for t in sorted(
        c["tasks"].values(), key=lambda t: (t.get("priority", 20), t["created_at"])
    ):
        if (
            t["status"]
            not in (
                "queued",
                "retrying",
                "waiting_quota",
                "quota_unknown",
                "waiting_compute",
            )
            or t.get("retry_at", 0) > now
        ):
            continue
        t.update(
            status="running",
            lease=uuid.uuid4().hex,
            lease_until=now + 120,
            worker=worker,
            started_at=now,
            generation=c["generation"],
            model_config=c.get("runtime"),
            step="启动或接续 GLM 会话",
        )
        t.pop("last_error", None)
        t["attempts"] += 1
        c["status"] = "running"
        record(c, "claimed", task_id=t["id"], attempt=t["attempts"], worker=worker)
        return t
    states = {t["status"] for t in c["tasks"].values()}
    c["status"] = (
        "running"
        if active
        else "waiting_compute"
        if "waiting_compute" in states
        else "retrying"
        if "retrying" in states
        else "needs_attention"
        if states & {"blocked", "failed"}
        else "queued"
        if states - TERMINAL
        else "idle"
    )
    return None


def fence(c, task_id, lease, now=None):
    now = time.time() if now is None else now
    t = c["tasks"].get(task_id)
    if (
        not t
        or t.get("lease") != lease
        or t["status"] != "running"
        or t.get("generation") != c["generation"]
        or c["desired"] != "running"
        or t.get("lease_until", 0) < now
    ):
        raise ValueError("task_lease_revoked")
    return t


def settle(c, task_id, lease, outcome, usage=None, now=None):
    now = time.time() if now is None else now
    t = c["tasks"][task_id]
    if t.get("lease") != lease:
        raise ValueError("stale_task_lease")
    if c["desired"] != "running":
        outcome = "cancelled"
    elif t.get("generation") != c["generation"]:
        outcome = "queued"
    if outcome == "done" and not t["reports"]:
        outcome = "blocked"
    if outcome == "waiting_quota":
        c["quota_blocked_at"], c["quota_retry_at"] = now, now + 60
        c["quota_blocked_floor"] = c["quota"].get("remaining_percent") or 0
        c["quota_blocked_reset"] = c["quota"].get("reset_at")
        t["retry_at"] = now + 60
    elif outcome in ("quota_unknown", "waiting_compute", "queued"):
        t["retry_at"] = now + 60 if outcome != "queued" else now
    elif outcome == "retrying":
        t["transient_errors"] = t.get("transient_errors", 0) + 1
        if t["transient_errors"] >= 8:
            outcome = "blocked"
        else:
            t["retry_at"] = now + retry_delay(t["transient_errors"] - 1)
    elif outcome not in TERMINAL:
        outcome = "blocked"
    t.update(
        status=outcome,
        finished_at=now,
        lease_until=0,
        step={
            "waiting_quota": "额度不足，程序等待恢复后接续",
            "retrying": "临时错误，程序将重试",
            "waiting_compute": "等待公共计算；模型槽可处理其他任务",
            "done": "产物已保存；研究结论仍待独立复核",
            "cancelled": "停止已确认",
        }.get(outcome, outcome),
    )
    if usage:
        for key in ("input", "output", "unknown_calls"):
            t["usage"][key] += max(0, int(usage.get(key, 0)))
    record(c, "settled", task_id=task_id, outcome=outcome)
    return outcome


def recover(c, now):
    for t in c["tasks"].values():
        if t["status"] in ("running", "stopping") and t.get("lease_until", 0) < now:
            t.update(
                status="queued" if c["desired"] == "running" else "cancelled",
                lease=None,
                lease_until=0,
                step="工作进程租约到期，保留步骤等待接续",
            )
            record(c, "lease_expired", task_id=t["id"])
    if c["desired"] == "stopped" and not any(
        t["status"] in ("running", "stopping") for t in c["tasks"].values()
    ):
        c["status"] = "stopped"
