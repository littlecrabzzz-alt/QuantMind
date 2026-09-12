"""Product metadata around LangGraph checkpoints; reuse the existing topic table."""

import hashlib
import json
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def event(state, kind, **data):
    state["sequence"] += 1
    state["events"].append(
        {"seq": state["sequence"], "at": time.time(), "kind": kind, **data}
    )
    # Full conversation and tool results remain in native LangGraph checkpoints.
    state["events"] = state["events"][-2000:]


class Store:
    def __init__(self, dsn):
        self.pool = AsyncConnectionPool(
            dsn, open=False, min_size=1, max_size=8, kwargs={"row_factory": dict_row}
        )

    async def list(self, owner, node):
        async with self.pool.connection() as db:
            return await (
                await db.execute(
                    """SELECT draft_id, state FROM research_drafts
                WHERE tenant_id=%s AND user_id=%s AND node_id=%s
                  AND state->>'engine'='deepagents' ORDER BY updated_at DESC LIMIT 100""",
                    (*owner, node),
                )
            ).fetchall()

    @asynccontextmanager
    async def edit(self, ident, owner=None, node=None):
        async with self.pool.connection() as db, db.transaction():
            row = await (
                await db.execute(
                    """SELECT * FROM research_drafts WHERE draft_id=%s
                AND state->>'engine'='deepagents' FOR UPDATE""",
                    (ident,),
                )
            ).fetchone()
            if (
                not row
                or (owner and (row["tenant_id"], row["user_id"]) != owner)
                or (node and row["node_id"] != node)
            ):
                raise KeyError("课题不存在")
            yield row["state"]
            await db.execute(
                "UPDATE research_drafts SET state=%s, updated_at=now() WHERE draft_id=%s",
                (Jsonb(row["state"]), ident),
            )

    async def get(self, ident, owner=None, node=None):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT * FROM research_drafts WHERE draft_id=%s AND state->>'engine'='deepagents'",
                    (ident,),
                )
            ).fetchone()
        if (
            not row
            or (owner and (row["tenant_id"], row["user_id"]) != owner)
            or (node and row["node_id"] != node)
        ):
            raise KeyError("课题不存在")
        return row

    async def create(self, owner, node, data, inventory):
        ident = uuid4().hex
        hashed = digest(["deepagents", data["key"]])
        payload_hash = digest(data)
        s = {
            "engine": "deepagents",
            "input": data,
            "payload_hash": payload_hash,
            "node_id": node,
            "inventory": inventory,
            "status": "idle",
            "generation": 0,
            "messages": [],
            "inbox": [],
            "plans": [],
            "approval": None,
            "jobs": {},
            "outcomes": [],
            "events": [],
            "sequence": 0,
            "requests": {},
            "todos": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "created_at": time.time(),
            "error": None,
        }
        async with self.pool.connection() as db, db.transaction():
            await db.execute(
                """INSERT INTO research_drafts(draft_id,tenant_id,user_id,node_id,input_hash,state)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,user_id,node_id,input_hash) DO NOTHING""",
                (ident, *owner, node, hashed, Jsonb(s)),
            )
            row = await (
                await db.execute(
                    """SELECT draft_id,state FROM research_drafts
                WHERE tenant_id=%s AND user_id=%s AND node_id=%s AND input_hash=%s""",
                    (*owner, node, hashed),
                )
            ).fetchone()
            if row["state"]["payload_hash"] != payload_hash:
                raise ValueError("重复请求的内容不同")
            return row["draft_id"]

    async def add_event(self, ident, kind, **data):
        async with self.edit(ident) as s:
            event(s, kind, **data)

    async def active(self, node):
        async with self.pool.connection() as db:
            return await (
                await db.execute(
                    """SELECT draft_id,state FROM research_drafts
                WHERE node_id=%s AND state->>'engine'='deepagents'
                AND (state->>'status' IN ('queued','running','stopping','waiting_job','retrying')
                    OR jsonb_array_length(state->'inbox')>0
                    OR jsonb_path_exists(state, '$.jobs.* ? (@.status == "running" || @.status == "launching")'))
                ORDER BY updated_at LIMIT 100""",
                    (node,),
                )
            ).fetchall()


def enqueue(state, key, content, mode="question"):
    hashed = digest([content, mode])
    if key in state["requests"]:
        if state["requests"][key] != hashed:
            raise ValueError("同一消息标识不能改变内容")
        return
    if len(state["inbox"]) >= 20:
        raise ValueError("待处理消息过多，请等待或打断当前工作")
    item = {
        "id": key,
        "role": "user" if mode != "job" else "system",
        "content": content,
        "mode": mode,
        "at": time.time(),
        "status": "received",
    }
    state["messages"].append(item)
    state["inbox"].append(key)
    state["requests"][key] = hashed
    if state["status"] not in ("running", "stopping"):
        state["status"] = "queued"
    event(state, "message_received", message_id=key)


def stop(state):
    state["generation"] += 1
    state["approval"] = None
    state["status"] = "stopping"
    for m in state["messages"]:
        if m["status"] in ("received", "read"):
            m["status"] = "interrupted"
    state["inbox"] = []
    event(state, "stop_requested", message="正在停止模型和本课题的计算作业")
