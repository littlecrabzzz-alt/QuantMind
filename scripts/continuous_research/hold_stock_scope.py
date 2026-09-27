"""Authenticated incident hold; preserve the frozen stock contract and all results.

Setting stock_contract to None uses the existing submit admission guard. This
operator action does not restart services or rewrite a frozen input package.
"""

import asyncio
import copy
import json
import os
import sys
import time
from contextlib import ExitStack

from backend.services.research_agent import continuous_state as st


def hold(c, incident_id, reason):
    if not isinstance(incident_id, str) or not 8 <= len(incident_id) <= 100:
        raise ValueError("incident_id_required")
    if not isinstance(reason, str) or not 20 <= len(reason) <= 2000:
        raise ValueError("specific_incident_reason_required")
    existing = c.get("stock_scope_hold")
    if existing:
        if existing["incident_id"] != incident_id:
            raise ValueError("another_stock_scope_hold_exists")
        if c.get("stock_contract") is not None:
            raise ValueError("stock_scope_was_restored")
        if existing["reason"] != reason:
            raise ValueError("incident_reason_conflict")
        return {"incident_id": incident_id, "already_held": True}
    stock = [t for t in c["tasks"].values() if t["kind"] == "stock_factor"]
    if any(t["status"] in ("running", "stopping") for t in stock):
        raise ValueError("wait_for_stock_model_calls_to_settle")
    if not c.get("stock_contract"):
        raise ValueError("enabled_stock_contract_required")
    saved = {
        "incident_id": incident_id,
        "reason": reason,
        "at": time.time(),
        "contract": copy.deepcopy(c["stock_contract"]),
        "tasks_before": {},
        "withheld_proposals": [],
        "disposition": "blocked_pending_boundary_acceptance",
    }
    for t in stock:
        if t["status"] not in st.TERMINAL:
            saved["tasks_before"][t["id"]] = {
                k: copy.deepcopy(t.get(k))
                for k in ("status", "step", "retry_at", "lease", "lease_until")
            }
            t.update(
                status="blocked",
                step="股票开发边界待复核，已暂停",
                last_error=reason,
                lease=None,
                lease_until=0,
            )
    for t in c["tasks"].values():
        for report in t["reports"]:
            for proposal in list(report.get("followups", [])):
                if proposal["topic"].startswith("stock_") and not proposal.get(
                    "task_id"
                ):
                    item = {
                        "proposal": copy.deepcopy(proposal),
                        "proposal_sha256": st.fingerprint(proposal),
                        "incident_id": incident_id,
                        "reason": reason,
                        "at": saved["at"],
                        "disposition": "operator_held_pending_evidence",
                    }
                    report.setdefault("withheld_followups", []).append(item)
                    report["followups"].remove(proposal)
                    saved["withheld_proposals"].append({"parent": t["id"], **item})
    c["stock_scope_hold"] = saved
    c["stock_contract"] = None
    st.record(
        c,
        "stock_scope_held",
        incident_id=incident_id,
        reason=reason,
        blocked_tasks=list(saved["tasks_before"]),
    )
    return {
        "incident_id": incident_id,
        "already_held": False,
        "blocked_tasks": list(saved["tasks_before"]),
        "withheld_proposals": len(saved["withheld_proposals"]),
    }


async def apply_request(request):
    import redis
    from fastapi.security import HTTPAuthorizationCredentials
    from sqlalchemy import text
    from backend.services.trade_shared.deps import get_auth_context
    from backend.services.engine.routers.continuous_research import edit
    from backend.services.engine.tasks.continuous_stock_tasks import invalidate_result

    request = dict(request)
    auth = await get_auth_context(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=request.pop("token")),
        x_tenant_id=None,
    )
    program_id = request.pop("program_id")
    client = redis.from_url(os.environ["REDIS_URL"])
    # The worker takes this same per-run Redis lock BEFORE reading pending.
    # Keep acquired locks through the edit transaction's commit, so a worker
    # cannot read pending then overwrite our failed status after commit.
    with ExitStack() as held_locks:
        async with edit(program_id, auth) as (c, db):
            receipt = hold(c, **request)
            rows = (
                await db.execute(
                    text("""
                SELECT backtest_id, status, result_json FROM qlib_backtest_runs
                WHERE user_id=:u AND tenant_id=:t
                  AND config_json->>'research_id'=:p
                  AND config_json->>'executor_kind'='frozen_stock_research'
                  AND status IN ('pending', 'running') FOR UPDATE
            """),
                    {"u": auth.user_id, "t": auth.tenant_id, "p": program_id},
                )
            ).all()
            closed_now, requires_runtime_stop = [], []
            for bid, status, old in rows:
                if status == "running":
                    requires_runtime_stop.append(bid)
                    continue
                lock = client.lock(
                    "quantmind:continuous-stock:" + bid,
                    timeout=7500,
                    blocking_timeout=0,
                )
                if not lock.acquire(blocking=False):
                    # Never wait for Redis while holding the database row:
                    # its worker may already be waiting to write that row.
                    requires_runtime_stop.append(bid)
                    continue
                held_locks.callback(lock.release)
                result = dict(old or {})
                result.update(
                    status="failed",
                    error_message="data_boundary_incident_hold: " + request["reason"],
                )
                await db.execute(
                    text("""
                    UPDATE qlib_backtest_runs SET status='failed',
                    result_json=CAST(:result AS jsonb), completed_at=now()
                    WHERE backtest_id=:bid AND user_id=:u AND tenant_id=:t AND status='pending'
                """),
                    {
                        "bid": bid,
                        "u": auth.user_id,
                        "t": auth.tenant_id,
                        "result": json.dumps(result, ensure_ascii=False),
                    },
                )
                closed_now.append(bid)
            saved_closed = c["stock_scope_hold"].setdefault("pending_runs_closed", [])
            saved_closed.extend(bid for bid in closed_now if bid not in saved_closed)
            receipt.update(
                pending_runs_closed=list(saved_closed),
                closed_now=closed_now,
                requires_runtime_stop=requires_runtime_stop,
            )
    # Retain closed IDs in the incident record so a retry after cache failure
    # invalidates the same entries without modifying a later run status.
    for bid in receipt["pending_runs_closed"]:
        invalidate_result(bid, auth.user_id, auth.tenant_id)
    return receipt


async def main():
    receipt = await apply_request(json.load(sys.stdin))
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
