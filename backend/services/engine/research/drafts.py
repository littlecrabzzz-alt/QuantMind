"""Persistent discussions, immutable plan versions and recoverable model requests."""
from __future__ import annotations

import json
import time
from uuid import uuid4
from sqlalchemy import text
from backend.shared.database_manager_v2 import get_session
from . import runtime
from .store import digest
from .planning import Plan, admission, instructions


class DraftStore:
    async def get(self, owner, node, ident=None, db=None, lock=False):
        if db is None:
            async with get_session(read_only=not lock) as session:
                return await self.get(owner, node, ident, session, lock)
        query = "SELECT * FROM research_drafts WHERE tenant_id=:tenant AND user_id=:user AND node_id=:node"
        params = {"tenant": owner[0], "user": owner[1], "node": node}
        if ident:
            query += " AND draft_id=:id"
            params["id"] = ident
        query += " ORDER BY updated_at DESC LIMIT 100" + (" FOR UPDATE" if lock else "")
        return [dict(r) for r in (await db.execute(text(query), params)).mappings()]

    async def save(self, db, ident, state, release=True):
        await db.execute(text("""UPDATE research_drafts SET state=CAST(:state AS jsonb), updated_at=now(),
            lease_until=CASE WHEN :release THEN 0 ELSE lease_until END,
            lease_owner=CASE WHEN :release THEN NULL ELSE lease_owner END WHERE draft_id=:id"""),
            {"id": ident, "state": json.dumps(state, ensure_ascii=False, allow_nan=False), "release": release})

    async def create(self, owner, node, payload, available, seed=None):
        hashed = digest({"input": payload, "inventory": available})
        async with get_session() as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"draft:{owner}:{node}:{hashed}"})
            old = (await db.execute(text("""SELECT draft_id FROM research_drafts
                WHERE tenant_id=:tenant AND user_id=:user AND node_id=:node AND input_hash=:hash"""),
                {"tenant": owner[0], "user": owner[1], "node": node, "hash": hashed})).scalar()
            if old:
                return old
            ident = uuid4().hex
            state = {"input": payload, "inventory": available, "messages": [], "plans": [],
                     "requests": {}, "run_id": seed, "revision": 0, "job": None}
            await db.execute(text("""INSERT INTO research_drafts(draft_id,tenant_id,user_id,node_id,input_hash,state)
                VALUES(:id,:tenant,:user,:node,:hash,CAST(:state AS jsonb))"""),
                {"id": ident, "tenant": owner[0], "user": owner[1], "node": node, "hash": hashed,
                 "state": json.dumps(state, ensure_ascii=False)})
            return ident

    async def message(self, owner, node, ident, key, mode, content, expected_revision, model, model_url, evidence):
        async with get_session() as db:
            rows = await self.get(owner, node, ident, db, True)
            if not rows:
                raise ValueError("研究草稿不存在或不属于当前账户和节点")
            s = rows[0]["state"]
            hashed = digest([mode, content, expected_revision, model])
            if key in s["requests"]:
                if s["requests"][key] != hashed:
                    raise ValueError("同一消息标识的内容改变")
                return
            if s["revision"] != expected_revision:
                raise ValueError("讨论已有更新，请刷新后再提交")
            if s.get("job") and s["job"]["status"] in ("queued", "running", "retrying"):
                raise ValueError("上一条消息仍在处理，可先停止该讨论请求")
            if len(s["messages"]) >= 80:
                raise ValueError("本课题讨论达到40轮，请保留当前计划后建立新课题")
            if mode != "ask" and s.get("run_id"):
                await db.execute(text("""UPDATE research_windows SET status='pause_requested',updated_at=now()
                    WHERE run_id=:run AND tenant_id=:tenant AND user_id=:user AND node_id=:node
                    AND status IN ('queued','running','pause_requested')"""),
                    {"run": s["run_id"], "tenant": owner[0], "user": owner[1], "node": node})
            job_id = uuid4().hex
            s["messages"].append({"role": "user", "content": content, "mode": mode, "at": time.time(), "job_id": job_id})
            # Capture once: retries must not change a previously submitted model request.
            context = {"instruction": instructions(mode), "original_input": s["input"], "inventory": s["inventory"],
                "current_plan": s["plans"][-1]["plan"] if s["plans"] else None,
                "history": s["messages"][-12:], "execution_evidence": evidence}
            s["job"] = {"id": job_id, "mode": mode, "status": "queued", "prompt": json.dumps(context, ensure_ascii=False),
                        "contract": {"model": model, "model_base_url": model_url}, "deadline": time.time()+900,
                        "corrections": [], "error": None}
            if mode != "ask":
                s["needs_plan"] = True
            s["requests"][key] = hashed
            s["revision"] += 1
            await self.save(db, ident, s)

    async def cancel_message(self, owner, node, ident):
        async with get_session() as db:
            rows = await self.get(owner, node, ident, db, True)
            if not rows:
                raise ValueError("研究草稿不存在")
            s = rows[0]["state"]
            if s.get("job") and s["job"]["status"] in ("queued", "running", "retrying"):
                s["job"]["status"] = "cancelled"
                s["revision"] += 1
                await self.save(db, ident, s)

    async def claim(self, node, lease):
        async with get_session() as db:
            row = (await db.execute(text("""SELECT * FROM research_drafts WHERE node_id=:node
                AND state->'job'->>'status' IN ('queued','running','retrying') AND lease_until<:now
                ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1"""), {"node": node, "now": time.time()})).mappings().first()
            if not row:
                return None
            s = row["state"]
            s["job"]["status"] = "running"
            await db.execute(text("""UPDATE research_drafts SET lease_owner=:lease,lease_until=:until,
                state=CAST(:state AS jsonb) WHERE draft_id=:id"""),
                {"lease": lease, "until": time.time()+300, "state": json.dumps(s), "id": row["draft_id"]})
            return {**dict(row), "state": s}

    async def complete(self, row, lease, reply=None, error=None, retry=False):
        who = (row["tenant_id"], row["user_id"])
        async with get_session() as db:
            current = (await self.get(who, row["node_id"], row["draft_id"], db, True))[0]
            s = current["state"]
            if current["lease_owner"] != lease or s["job"]["id"] != row["state"]["job"]["id"] or s["job"]["status"] == "cancelled":
                return  # A cancelled/replaced request may finish at provider; never resurrect it.
            job = row["state"]["job"]
            job["status"] = "retrying" if retry else "failed" if error else "completed"
            job["error"] = error
            s["job"] = job
            if reply:
                s["messages"].append({"role": "assistant", "content": reply["answer"], "at": time.time(), "job_id": job["id"]})
                if job["mode"] != "ask":
                    plan = Plan.model_validate(reply["plan"]).model_dump()
                    s["plans"].append({"version": len(s["plans"])+1, "plan": plan,
                        "admission": admission(plan, s["inventory"]), "at": time.time(), "run_id": None})
                    s["needs_plan"] = False
            s["revision"] += 1
            await self.save(db, row["draft_id"], s)


async def tick():
    cfg = runtime.settings()
    store, lease = DraftStore(), uuid4().hex
    row = await store.claim(cfg["node_id"], lease)
    if not row:
        return {"status": "idle"}
    job = row["state"]["job"]
    if time.time() >= job["deadline"]:
        await store.complete(row, lease, error="本次讨论请求已到期；内容保留，可重新发送")
        return {"status": "expired"}
    folder = runtime.ROOT / "drafts" / row["draft_id"] / "api" / job["id"] / f"call-{len(job['corrections'])+1}"
    schema = Plan.model_json_schema()
    # Embed definitions at the function root; runtime adapter expects root properties only.
    def inline(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return inline(schema["$defs"][value["$ref"].split("/")[-1]])
            return {k: inline(v) for k, v in value.items() if k != "$defs"}
        return [inline(v) for v in value] if isinstance(value, list) else value
    properties = {"answer": {"type": "string"}, "plan": {"anyOf": [inline(schema), {"type": "null"}]}}
    try:
        prompt = job["prompt"] + "\n格式修正：" + json.dumps(job["corrections"], ensure_ascii=False)
        reply = runtime.model_decision(folder, job["contract"], "research_discussion", properties, prompt, job["deadline"])
        if reply is None:
            await store.complete(row, lease, retry=True)
            return {"status": "retrying"}
        if not isinstance(reply["answer"], str) or not reply["answer"].strip():
            raise ValueError("缺少讨论回答")
        if job["mode"] != "ask":
            Plan.model_validate(reply["plan"])
        await store.complete(row, lease, reply=reply)
    except (runtime.InvalidDecision, ValueError, TypeError, KeyError) as exc:
        job["corrections"].append(str(exc)[:400])
        await store.complete(row, lease, error="计划响应未通过校验，可重试或调整问题", retry=len(job["corrections"]) < 3)
    except Exception:
        await store.complete(row, lease, error="讨论服务暂时不可用，内容已保留")
    return {"draft_id": row["draft_id"]}
