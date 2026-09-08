"""PostgreSQL owns lifecycle state. Files contain immutable experiment evidence."""
from __future__ import annotations

import hashlib
import json
import time
from uuid import uuid4

from sqlalchemy import text

from backend.shared.database_manager_v2 import get_session

ACTIVE = ("queued", "running", "pause_requested", "cancel_requested")
TERMINAL = ("completed", "failed", "blocked", "paused", "cancelled", "expired")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Store:
    async def create(self, owner, node, key, payload, contract, parent=None):
        tenant, user = owner
        request_hash = digest(payload)
        async with get_session() as db:
            # Serializes a user's submits/resumes; the unique index is the final guard.
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                             {"key": f"research:{tenant}:{user}:{node}"})
            old = (await db.execute(text("""SELECT * FROM research_windows WHERE
                tenant_id=:tenant AND user_id=:user AND node_id=:node AND idempotency_key=:key"""),
                {"tenant": tenant, "user": user, "node": node, "key": key})).mappings().first()
            if old:
                if old["request_hash"] != request_hash:
                    raise ValueError("同一提交标识的研究设置发生变化，请重新提交")
                return old["run_id"]
            checkpoint = {"stage": "baseline", "experiments": [], "events": [], "candidate_count": 0}
            case_id = uuid4().hex
            if parent:
                previous = (await db.execute(text("""SELECT * FROM research_windows WHERE
                    run_id=:run AND tenant_id=:tenant AND user_id=:user AND node_id=:node FOR UPDATE"""),
                    {"run": parent, "tenant": tenant, "user": user, "node": node})).mappings().first()
                if not previous or previous["status"] not in ("paused", "expired", "cancelled", "failed", "blocked"):
                    raise ValueError("该任务不能继续，或已在运行")
                case_id = previous["case_id"]
                latest = (await db.execute(text("SELECT run_id FROM research_windows WHERE case_id=:case ORDER BY started_at DESC LIMIT 1"),
                                          {"case": case_id})).scalar()
                if latest != parent:
                    raise ValueError("请从课题的最新运行窗口继续")
                checkpoint = dict(previous["checkpoint"])
                checkpoint.pop("error", None)
                checkpoint["resumed_from"] = parent
                # A stopped experiment may be retried only after this explicit action.
                if checkpoint.get("active") and checkpoint["active"].get("status") in ("failed", "cancelled"):
                    checkpoint["retry_proposal"] = checkpoint["active"]["proposal"]
                    checkpoint["experiments"].append(checkpoint["active"])
                    checkpoint.pop("active")
            else:
                await db.execute(text("""INSERT INTO research_cases(case_id,tenant_id,user_id,node_id,kind,goal,contract)
                    VALUES(:case,:tenant,:user,:node,:kind,:goal,CAST(:contract AS jsonb))"""),
                    {"case": case_id, "tenant": tenant, "user": user, "node": node,
                     "kind": payload["kind"], "goal": payload["goal"], "contract": json.dumps(contract)})
            run_id = uuid4().hex
            await db.execute(text("""INSERT INTO research_windows
                (run_id,case_id,tenant_id,user_id,node_id,idempotency_key,request_hash,checkpoint,deadline_epoch)
                VALUES(:run,:case,:tenant,:user,:node,:key,:hash,CAST(:checkpoint AS jsonb),:deadline)"""),
                {"run": run_id, "case": case_id, "tenant": tenant, "user": user, "node": node,
                 "key": key, "hash": request_hash, "checkpoint": json.dumps(checkpoint),
                 "deadline": time.time()+payload["hours"]*3600})
            return run_id

    async def get(self, owner, node, run_id=None):
        query = """SELECT w.*, c.kind, c.goal, c.contract FROM research_windows w
            JOIN research_cases c ON c.case_id=w.case_id
            WHERE w.tenant_id=:tenant AND w.user_id=:user AND w.node_id=:node"""
        params = {"tenant": owner[0], "user": owner[1], "node": node}
        if run_id:
            query += " AND w.run_id=:run"
            params["run"] = run_id
        query += " ORDER BY w.started_at DESC LIMIT 100"
        async with get_session(read_only=True) as db:
            return [dict(row) for row in (await db.execute(text(query), params)).mappings()]

    async def control(self, owner, node, run_id, action):
        status = {"pause": "pause_requested", "cancel": "cancel_requested"}[action]
        async with get_session() as db:
            result = await db.execute(text("""UPDATE research_windows SET status=:status,updated_at=now()
                WHERE run_id=:run AND tenant_id=:tenant AND user_id=:user AND node_id=:node
                AND status IN ('queued','running','pause_requested','cancel_requested')
                AND NOT (status='cancel_requested' AND :status='pause_requested') RETURNING run_id"""),
                {"run": run_id, "tenant": owner[0], "user": owner[1], "node": node, "status": status})
            return result.scalar() is not None

    async def claim(self, node, lease_owner):
        async with get_session() as db:
            row = (await db.execute(text("""SELECT w.run_id FROM research_windows w WHERE node_id=:node
                AND status IN ('queued','running','pause_requested','cancel_requested') AND lease_until<:now
                ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1"""),
                {"node": node, "now": time.time()})).mappings().first()
            if not row:
                return None
            await db.execute(text("""UPDATE research_windows SET lease_owner=:owner,lease_until=:until,
                status=CASE WHEN status='queued' THEN 'running' ELSE status END WHERE run_id=:run"""),
                {"owner": lease_owner, "until": time.time()+300, "run": row["run_id"]})
            result = (await db.execute(text("""SELECT w.*, c.kind,c.goal,c.contract FROM research_windows w
                JOIN research_cases c ON c.case_id=w.case_id WHERE w.run_id=:run"""), {"run": row["run_id"]})).mappings().one()
            return dict(result)

    async def checkpoint(self, run_id, lease_owner, checkpoint, status=None, release=True):
        async with get_session() as db:
            row = (await db.execute(text("SELECT status FROM research_windows WHERE run_id=:run AND lease_owner=:owner FOR UPDATE"),
                                   {"run": run_id, "owner": lease_owner})).scalar()
            if row is None:
                raise RuntimeError("Research lease no longer belongs to this worker")
            # User controls that arrived during a model call survive checkpoints.
            next_status = row if row in ("cancel_requested", "pause_requested") and status not in ("paused", "cancelled", "expired") else status or row
            await db.execute(text("""UPDATE research_windows SET checkpoint=CAST(:state AS jsonb),status=:status,
                updated_at=now(),lease_until=:until,lease_owner=:new_owner WHERE run_id=:run AND lease_owner=:owner"""),
                {"state": json.dumps(checkpoint, allow_nan=False), "status": next_status,
                 "until": 0 if release else time.time()+300, "new_owner": None if release else lease_owner,
                 "run": run_id, "owner": lease_owner})
            return next_status
