"""Discussion is read/planning work. Only a reviewed version can schedule research."""
from __future__ import annotations

import json
import time
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.shared.database_manager_v2 import get_session
from backend.services.engine.research import runtime
from backend.services.engine.research.drafts import DraftStore
from backend.services.engine.research.planning import admission, inventory
from backend.services.engine.research.store import Store, ACTIVE

router = APIRouter(prefix="/drafts", tags=["Research discussion"])
drafts = DraftStore()


def helpers():
    # Imported on request, after the parent router has finished registering.
    from . import research_runs
    return research_runs


class NewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1200)
    subject: str = Field(default="", max_length=1200)
    material: str = Field(default="", max_length=12000)
    source_run_id: str | None = None
    @field_validator("question")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("先写下想弄清的问题")
        return v.strip()


class Discussion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=8, max_length=128)
    mode: Literal["ask", "plan", "revise"]
    content: str = Field(min_length=1, max_length=6000)
    revision: int = Field(ge=0)
    model: str = Field(default="glm-5.3-flash", max_length=100)
    @field_validator("content")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("消息不能为空")
        return v.strip()


class Execute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    action: Literal["start", "resume"] = "start"
    hours: float = Field(default=2, ge=.1, le=8)
    candidate_limit: int = Field(default=2, ge=1, le=2)
    model: str = Field(default="glm-5.3-flash", max_length=100)
    key: str = Field(min_length=8, max_length=128)
    reviewed: Literal[True]
    parent_run_id: str | None = None


async def owned(request, ident, db=None, lock=False):
    h = helpers()
    cfg = h.configured(request)
    rows = await drafts.get(h.owner(request), cfg["node_id"], ident, db, lock)
    if not rows:
        raise HTTPException(404, "课题不存在或不属于当前账户和节点")
    return rows[0]


def current_inventory(request):
    cfg = helpers().configured(request)
    base = runtime.frozen.read(runtime.ROOT / "inputs" / cfg["snapshot_id"] / "snapshot/config.json")
    return inventory(cfg, base)


async def present(row, detail=False):
    s = row["state"]
    job = s.get("job")
    result = {"draft_id": row["draft_id"], "node_id": row["node_id"], "updated_at": row["updated_at"],
        "input": s["input"], "revision": s["revision"], "run_id": s.get("run_id"), "needs_plan": s.get("needs_plan", False),
        "plan": s["plans"][-1] if s["plans"] else None,
        "job": {k: job.get(k) for k in ("id", "mode", "status", "error", "deadline")} if job else None}
    if detail:
        result.update(messages=s["messages"], plans=s["plans"], inventory=s["inventory"])
        if s.get("run_id"):
            rows = await Store().get((row["tenant_id"], row["user_id"]), row["node_id"], s["run_id"])
            if rows:
                result["run"] = helpers().public(rows[0], True)
        from backend.services.engine.research.coordinator import usage
        result["discussion_usage"] = usage(runtime.ROOT / "drafts" / row["draft_id"])
    return result


@router.get("")
async def list_drafts(request: Request):
    h = helpers()
    return {"drafts": [await present(r) for r in await drafts.get(h.owner(request), h.configured(request)["node_id"])]}


@router.post("")
async def create_draft(req: NewDraft, request: Request):
    h = helpers()
    cfg = h.configured(request)
    if req.source_run_id:
        await h.owned(request, req.source_run_id)
    ident = await drafts.create(h.owner(request), cfg["node_id"], req.model_dump(), current_inventory(request), req.source_run_id)
    return await present(await owned(request, ident), True)


@router.get("/{ident}")
async def detail(ident: str, request: Request):
    return await present(await owned(request, ident), True)


@router.post("/{ident}/messages")
async def message(ident: str, req: Discussion, request: Request):
    row = await owned(request, ident)
    if req.model not in runtime.models():
        raise HTTPException(400, "模型未配置")
    evidence = None
    if row["state"].get("run_id"):
        run = await helpers().owned(request, row["state"]["run_id"])
        evidence = jsonable_encoder(helpers().public(run, True))
        evidence.pop("curves", None)
    try:
        await drafts.message(helpers().owner(request), row["node_id"], ident, req.key, req.mode, req.content,
            req.revision, req.model, runtime.credentials()["base_url"], evidence)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await present(await owned(request, ident), True)


@router.post("/{ident}/messages/cancel")
async def cancel_message(ident: str, request: Request):
    row = await owned(request, ident)
    await drafts.cancel_message(helpers().owner(request), row["node_id"], ident)
    return await present(await owned(request, ident), True)


@router.post("/{ident}/execute")
async def execute(ident: str, req: Execute, request: Request):
    h = helpers()
    async with get_session() as db:
        row = await owned(request, ident, db, True)
        s = row["state"]
        if not s["plans"] or s["plans"][-1]["version"] != req.version:
            raise HTTPException(409, "计划版本已改变，请重新审阅")
        entry = s["plans"][-1]
        p = entry["plan"]
        if s.get("needs_plan") or s.get("job") and s["job"]["status"] in ("queued", "running", "retrying"):
            raise HTTPException(409, "讨论或调整尚未结束，请先查看更新后的计划")
        available = current_inventory(request)
        if available != s["inventory"]:
            raise HTTPException(409, "数据或执行环境已改变，需要重新建立并审阅计划")
        gate = admission(p, available)
        if not gate["ready"]:
            raise HTTPException(409, "计划仍有数据、工具或决策缺项，不能执行")
        who = h.owner(request)
        if req.action == "start" and entry.get("run_id"):
            # One execution per approved plan version, even with another click/key.
            return {"run_id": s["run_id"], "reused": True}
        if s.get("run_id"):
            prior = await h.owned(request, s["run_id"])
            if req.action == "start" and prior["status"] in ACTIVE:
                raise HTTPException(409, "旧计划仍在收尾，请等暂停或取消完成后再启动新版本")
        if req.action == "resume":
            if not entry.get("run_id") or not req.parent_run_id:
                raise HTTPException(409, "没有已确认计划的执行可继续")
            parent = await h.owned(request, req.parent_run_id)
            if parent["contract"].get("draft_id") != ident or parent["contract"].get("plan_version") != req.version:
                raise HTTPException(409, "不能继续另一个计划的执行")
            payload = {"hours": req.hours, "parent": req.parent_run_id}
            try:
                run_id = await Store().create(who, row["node_id"], req.key, payload, parent["contract"], parent=req.parent_run_id, session=db)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if s["run_id"] not in (req.parent_run_id, run_id):
                return {"run_id": s["run_id"], "reused": True}
        else:
            if req.candidate_limit != p["candidate_limit"]:
                raise HTTPException(409, "候选数量与计划不同，请先调整计划并重新确认")
            request_model = h.NewResearch(idempotency_key=f"plan:{ident}:{req.version}", node_id=row["node_id"],
                kind="method" if p["requirements"]["executor"] == "factor_expression" else "strategy",
                goal=p["question"], hours=req.hours, candidate_limit=req.candidate_limit, model=req.model,
                expression=p["expression"], source_text=json.dumps({"original_input": s["input"], "approved_plan": p}, ensure_ascii=False)[:12000])
            payload, contract = await h.prepare_research(request_model, request)
            contract.update(draft_id=ident, plan_version=req.version, approved_plan=p)
            run_id = await Store().create(who, row["node_id"], request_model.idempotency_key, payload, contract, session=db)
            entry["run_id"] = run_id
            entry["approved_at"] = time.time()
            entry["execution"] = {"hours": req.hours, "model": req.model, "candidate_limit": req.candidate_limit}
        s["run_id"] = run_id
        s["revision"] += 1
        await drafts.save(db, ident, s)
    return {"run_id": run_id, "reused": False}
