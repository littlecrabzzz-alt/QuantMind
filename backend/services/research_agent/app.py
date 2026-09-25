"""Private Agent sidecar. Public authentication stays in the existing engine gateway."""

import asyncio
import base64
import hmac
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from . import external
from .external import Contracts, ExternalStore
from .runtime import Runner
from .sandbox import Sandbox, files, read_file
from .settings import Settings
from .store import Store, digest, enqueue, event, stop


@asynccontextmanager
async def lifespan(app):
    cfg = Settings()
    store = Store(cfg.dsn)
    await store.pool.open()
    lock = await AsyncConnection.connect(cfg.dsn, autocommit=True)
    locked = (
        await (
            await lock.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
                ("research-agent:" + cfg.node,),
            )
        ).fetchone()
    )[0]
    if not locked:
        await lock.close()
        await store.pool.close()
        raise RuntimeError("本节点已有Agent服务持有运行锁")
    async with store.pool.connection() as db:
        await db.execute(
            Path(__file__)
            .resolve()
            .parents[3]
            .joinpath("scripts/research_workbench_v2.sql")
            .read_text()
        )
    async with AsyncPostgresSaver.from_conn_string(cfg.dsn) as saver:
        await saver.setup()
    app.state.settings, app.state.store = cfg, store
    app.state.external, app.state.contracts = ExternalStore(store.pool), Contracts()
    app.state.runner = Runner(cfg, store)
    # Ambiguous in-flight model/tool calls are not blindly replayed after a crash.
    for row in await store.active(cfg.node):
        if row["state"]["status"] == "running":
            async with store.edit(row["draft_id"]) as s:
                stop(s)
                event(
                    s,
                    "recovered",
                    message="服务已恢复；上次模型调用结果不明，停止遗留计算并保留检查点，等待继续确认",
                )
    task = asyncio.create_task(app.state.runner.supervise())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await lock.close()
        await store.pool.close()


async def identity(request: Request):
    cfg = request.app.state.settings
    if not hmac.compare_digest(
        request.headers.get("x-internal-call", ""), cfg.internal_secret
    ):
        raise HTTPException(401, "仅接受平台认证网关请求")
    user, tenant = request.headers.get("x-user-id"), request.headers.get("x-tenant-id")
    if not user or not tenant:
        raise HTTPException(401, "缺少账户身份")
    if request.headers.get("x-research-node", cfg.node) != cfg.node:
        raise HTTPException(409, "研究节点已改变，请刷新页面")
    return tenant, user


app = FastAPI(
    title="QuantMind Research Agent",
    lifespan=lifespan,
    dependencies=[Depends(identity)],
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=8, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    subject: str = Field(default="", max_length=1200)
    material: str = Field(default="", max_length=16000)
    model: str = Field(default="glm-5.3-flash", max_length=80)
    executor_kind: Literal["builtin", "external"] = "builtin"
    project_key: str | None = Field(default=None, max_length=32)
    workstream: str | None = Field(default=None, max_length=8)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=8, max_length=128)
    content: str = Field(min_length=1, max_length=16000)
    interrupt: bool = False


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=8, max_length=128)
    version: int = Field(ge=1)
    reviewed: Literal[True]
    hours: float = Field(default=2, ge=0.05, le=8)
    max_jobs: int = Field(default=4, ge=1, le=20)


class Upload(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    base64: str = Field(max_length=2_800_000)


def public(ident, state, details=True, stale_after=21600.0):
    result = {
        "id": ident,
        **{
            k: state[k]
            for k in (
                "input",
                "status",
                "node_id",
                "created_at",
                "error",
                "sequence",
                "usage",
            )
        },
    }
    result["executor_kind"] = state.get("engine") or "builtin"
    if state.get("engine") == "external":
        result["external"] = external.derive_summary(
            state["external"], stale_after=stale_after
        )
    result["plan"] = state["plans"][-1] if state["plans"] else None
    result["approval"] = state["approval"]
    if details:
        result.update(
            {
                k: state[k]
                for k in (
                    "messages",
                    "events",
                    "jobs",
                    "outcomes",
                    "todos",
                    "inventory",
                    "plans",
                )
            }
        )
    return result


async def owned(request, ident):
    try:
        return await request.app.state.store.get(
            ident, await identity(request), request.app.state.settings.node
        )
    except KeyError:
        raise HTTPException(404, "课题不存在") from None


async def builtin_case(request, ident):
    """Model-driven routes stay builtin-only; external cases reject early."""

    row = await owned(request, ident)
    if row["state"].get("engine") != "deepagents":
        raise HTTPException(
            409, "外部执行课题由外部 runner 驱动，不支持内置模型消息或审批窗口"
        )
    return row


@app.exception_handler(ValueError)
async def invalid(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": str(exc)[:500]})


@app.get("/capabilities")
async def capabilities(request: Request):
    cfg = request.app.state.settings
    return {
        "ready": True,
        "node_id": cfg.node,
        "owner_scope": digest([*(await identity(request)), cfg.node])[:24],
        "environment": cfg.cfg["label"],
        "models": cfg.models,
        "inventory": cfg.inventory(),
        "framework": "Deep Agents / LangGraph",
        "max_hours": 8,
    }


@app.get("/cases")
async def cases(request: Request):
    window = request.app.state.settings.external_stale_after
    return {
        "cases": [
            public(row["draft_id"], row["state"], False, stale_after=window)
            for row in await request.app.state.store.list(
                await identity(request), request.app.state.settings.node
            )
        ]
    }


@app.post("/cases")
async def create(data: Input, request: Request):
    cfg, store = request.app.state.settings, request.app.state.store
    if data.executor_kind == "external":
        project = (data.project_key or "").strip().lower()
        if project != "r01":
            raise HTTPException(400, "外部执行课题当前仅支持 project_key=r01")
        if data.workstream not in external.WORKSTREAMS:
            raise HTTPException(400, "workstream 必须是 P0/A/B1/B2/B3/D/N")
        if not cfg.external_contract_node:
            return _contract_response(
                409,
                "node_not_contract_named",
                "本节点 node_id 不在合同 source_node 枚举（mac|cloud）内，且未配置 "
                "RESEARCH_EXTERNAL_CONTRACT_NODE；外部回报无法绑定节点，拒绝登记外部课题",
            )
        ident = await store.create(
            await identity(request),
            cfg.node,
            data.model_dump(),
            {"note": "外部执行课题：输入与产物由外部 runner 按数据合同回报登记"},
            engine="external",
            external=external.initial_external_state(project, data.workstream),
        )
        cfg.workspace(ident)
        async with store.edit(ident, await identity(request), cfg.node) as s:
            event(
                s,
                "external_case_registered",
                project_key=project,
                workstream=data.workstream,
                message="外部执行课题已登记：不排内置模型作业，回报经 external-reports 接收",
            )
        row = await owned(request, ident)
        return public(ident, row["state"], stale_after=cfg.external_stale_after)
    if data.model not in cfg.models:
        raise HTTPException(400, "模型不可用")
    ident = await store.create(
        await identity(request), cfg.node, data.model_dump(), cfg.inventory()
    )
    cfg.workspace(ident)
    async with store.edit(ident, await identity(request), cfg.node) as s:
        enqueue(
            s,
            "initial:" + data.key,
            data.question
            + "\n研究对象："
            + (data.subject or "待一起确定")
            + "\n材料："
            + data.material,
        )
    return public(ident, (await owned(request, ident))["state"])


@app.get("/cases/{ident}")
async def detail(ident: str, request: Request, after: int = 0):
    cfg = request.app.state.settings
    result = public(
        ident,
        (await owned(request, ident))["state"],
        stale_after=cfg.external_stale_after,
    )
    result["events"] = [e for e in result["events"] if e["seq"] > after]
    result["files"] = await asyncio.to_thread(files, cfg.workspace(ident))
    return result


@app.post("/cases/{ident}/messages")
async def message(ident: str, data: Message, request: Request):
    await builtin_case(request, ident)
    async with request.app.state.store.edit(ident) as s:
        if data.key not in s["requests"] and data.interrupt:
            stop(s)
        enqueue(s, data.key, data.content, "question")
    return {"status": "received", "message_id": data.key}


@app.post("/cases/{ident}/stop")
async def cancel(ident: str, request: Request):
    row = await owned(request, ident)
    if row["state"].get("engine") == "external":
        async with request.app.state.store.edit(ident) as s:
            if not s["external"].get("stop_requested"):
                s["external"]["stop_requested"] = external._utc_now_iso()
                event(
                    s,
                    "external_stop_requested",
                    message="已请求外部停止：平台不伪造已停止状态，等待外部 runner 确认",
                )
        return {
            "status": "stop_requested",
            "note": "已记录停止请求；外部 runner 从事件流读取后确认，平台不假装已控制外部进程",
        }
    async with request.app.state.store.edit(ident) as s:
        if s["status"] != "stopping":
            stop(s)
    return {"status": "stopping"}


@app.post("/cases/{ident}/approve")
async def approve(ident: str, data: Approval, request: Request):
    await builtin_case(request, ident)
    async with request.app.state.store.edit(ident) as s:
        hashed = digest(data.model_dump())
        if s.get("approval_requests", {}).get(data.key) == hashed:
            return {"status": "accepted", "reused": True}
        if data.key in s.get("approval_requests", {}):
            raise ValueError("重复确认的内容不同")
        if s["status"] in ("running", "queued", "retrying", "stopping", "waiting_job"):
            raise ValueError("请等待当前讨论结束，或先打断正在运行的工作")
        plan = s["plans"][-1] if s["plans"] else None
        if not plan or plan["version"] != data.version:
            raise ValueError("计划版本已改变，请重新查看")
        if plan["plan"]["missing"]:
            raise ValueError("计划还有待准备事项，请先讨论并修订计划")
        if not plan["plan"].get("allowed_tools"):
            raise ValueError("请让Agent补充计划使用的工具范围，再确认执行")
        s["approval"] = {
            "allowed_tools": plan["plan"]["allowed_tools"],
            "version": data.version,
            "deadline": time.time() + data.hours * 3600,
            "max_jobs": data.max_jobs,
            "initial_jobs": len(s["jobs"]),
            "at": time.time(),
        }
        s.setdefault("approval_requests", {})[data.key] = hashed
        s["retry_at"], s["retry_attempts"] = 0, 0
        enqueue(
            s,
            data.key,
            f"我已查看并确认第{data.version}版计划。请在本次批准范围内执行，保存真实产物并登记平台成果。",
            "execute",
        )
        event(s, "approved", **s["approval"])
    return {"status": "accepted"}


@app.get("/cases/{ident}/file")
async def file(ident: str, path: str, request: Request):
    await owned(request, ident)
    try:
        data = await asyncio.to_thread(
            read_file, request.app.state.settings.workspace(ident), path, 20_000_000
        )
    except (OSError, ValueError):
        raise HTTPException(404, "文件不存在、超出大小限制或不是普通文件") from None
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.post("/cases/{ident}/files")
async def upload(ident: str, data: Upload, request: Request):
    await builtin_case(request, ident)
    if "/" in data.path or "\\" in data.path or data.path in (".", ".."):
        raise HTTPException(400, "材料只接受文件名")
    try:
        content = base64.b64decode(data.base64, validate=True)
    except ValueError:
        raise HTTPException(400, "文件内容无效") from None
    if len(content) > 2_000_000:
        raise HTTPException(400, "单个材料最多2MB")
    sandbox = Sandbox(request.app.state.settings, ident)
    name = digest(content.hex())[:12] + "-" + data.path
    result = await asyncio.to_thread(
        sandbox.upload_files, [("/workspace/materials/" + name, content)]
    )
    if result[0].error:
        raise HTTPException(503, "材料未保存，请检查沙盒状态")
    await request.app.state.store.add_event(
        ident, "material", path="materials/" + name, size=len(content)
    )
    return {"path": "materials/" + name}


def _contract_response(status, code, detail, **extra):
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail, **extra}
    )


@app.post("/cases/{ident}/external-reports")
async def submit_external_report(ident: str, request: Request):
    """Receive one external report envelope (report-api v2 §1).

    Guarantees: schema+contract validation, three-level idempotency key
    (source_task + source_run_id + event_id), no-regression ordering,
    platform-owned received_at, hash-verified artifacts kept as raw evidence
    on failure, readiness gating marks non-P0 outcomes not_ready.
    """

    cfg = request.app.state.settings
    store, xstore = request.app.state.store, request.app.state.external
    contracts = request.app.state.contracts
    owner = await identity(request)
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(400, "请求体不是合法 JSON") from None
    try:
        envelope, payload_hash, received_at = external.normalize_submission(raw)
        contracts.validate_envelope(envelope)
        contracts.check_contract_hash(
            envelope["contract_version"], envelope["contract_hash"]
        )
    except external.ContractError as exc:
        return _contract_response(422, exc.code, exc.detail)
    if envelope["execution_status"] == "stale":
        return _contract_response(
            422,
            "stale_is_platform_judged",
            "断联（stale）状态由平台判定，外部回报不能申报 stale",
        )
    row = await owned(request, ident)
    state = row["state"]
    if state.get("engine") != "external":
        return _contract_response(
            409, "not_external_case", "课题不是外部执行模式，不能接收外部回报"
        )
    if not cfg.external_contract_node:
        return _contract_response(
            409,
            "node_not_contract_named",
            "本节点 node_id 不在合同 source_node 枚举（mac|cloud）内，且未配置 "
            "RESEARCH_EXTERNAL_CONTRACT_NODE；拒绝外部回报（显式拒绝，不做静默映射）",
        )
    try:
        external.check_case_binding(
            envelope, ident, state["external"], cfg.external_contract_node
        )
    except external.NodeMismatch:
        return _contract_response(
            409, "node_mismatch", "信封 source_node 与课题登记节点不一致"
        )
    except external.ContractError as exc:
        return _contract_response(422, exc.code, exc.detail)

    async def keep_rejected(code, detail):
        """Store the verbatim envelope with validation_error, then raise 422."""

        async with store.pool.connection() as db, db.transaction():
            existing = await xstore.find_event(
                db,
                ident,
                envelope["source_task"],
                envelope["source_run_id"],
                envelope["event_id"],
            )
            if existing is None:
                fresh = await (
                    await db.execute(
                        "SELECT * FROM research_drafts WHERE draft_id=%s FOR UPDATE",
                        (ident,),
                    )
                ).fetchone()
                s = fresh["state"]
                s["external"]["events_error"] = (
                    s["external"].get("events_error", 0) + 1
                )
                event(
                    s,
                    "external_report_rejected",
                    event_id=envelope["event_id"],
                    message=f"{code}: {detail[:300]}",
                )
                await xstore.insert_event(
                    db,
                    owner,
                    cfg.node,
                    ident,
                    envelope,
                    payload_hash,
                    received_at,
                    "validation_error",
                    f"{code}: {detail[:400]}",
                )
                await db.execute(
                    "UPDATE research_drafts SET state=%s, updated_at=now() WHERE draft_id=%s",
                    (Jsonb(s), ident),
                )

    if envelope.get("artifacts"):
        try:
            external.verify_artifacts(envelope, cfg.workspace(ident))
        except external.ContractError as exc:
            await keep_rejected(exc.code, exc.detail)
            return _contract_response(422, exc.code, exc.detail)

    readiness = await xstore.get_readiness(owner, cfg.node, envelope["project_key"])
    binding = await xstore.get_acceptance_binding(
        owner, cfg.node, envelope["project_key"]
    )
    formal_ready, admission_reasons = external.evaluate_formal_admission(
        readiness, binding, contracts.contract_hashes["2.3"]
    )
    # G1P1: the envelope's own identity (code/manifest/package) must match the
    # accepted binding; mismatched reports stay as raw not_ready evidence.
    identity_ok, identity_reasons = external.envelope_identity_vs_binding(
        envelope, readiness, binding
    )
    reasons = admission_reasons + identity_reasons
    not_ready = envelope["workstream"] != "P0" and bool(reasons)
    not_ready_reason = (", ".join(reasons)) if not_ready else None

    async with store.pool.connection() as db, db.transaction():
        existing = await xstore.find_event(
            db,
            ident,
            envelope["source_task"],
            envelope["source_run_id"],
            envelope["event_id"],
        )
        if existing is not None:
            if existing["payload_hash"] == payload_hash:
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "duplicate",
                        "reused": True,
                        "note": "幂等重放：返回已存状态，不重复入账",
                        "event": external.event_row_public(existing),
                    },
                )
            return _contract_response(
                409,
                "idempotency_conflict",
                "同一幂等键（source_task+source_run_id+event_id）已存在不同内容，保留首次内容",
            )
        fresh = await (
            await db.execute(
                "SELECT * FROM research_drafts WHERE draft_id=%s FOR UPDATE", (ident,)
            )
        ).fetchone()
        s = fresh["state"]
        decision, note = external.apply_event(
            s["external"], envelope, received_at, not_ready, not_ready_reason
        )
        apply_status = "not_ready" if not_ready else decision
        platform_seq = await xstore.insert_event(
            db,
            owner,
            cfg.node,
            ident,
            envelope,
            payload_hash,
            received_at,
            apply_status,
            note,
        )
        event(
            s,
            "external_report",
            platform_seq=platform_seq,
            event_id=envelope["event_id"],
            report_kind=envelope["kind"],
            execution_status=s["external"]["execution_status"],
            evidence_stage=s["external"]["evidence_stage"],
            apply_status=apply_status,
        )
        await db.execute(
            "UPDATE research_drafts SET state=%s, updated_at=now() WHERE draft_id=%s",
            (Jsonb(s), ident),
        )
    return JSONResponse(
        status_code=201,
        content={
            "status": apply_status,
            "platform_seq": platform_seq,
            "received_at": received_at,
            "apply_note": note,
            "not_ready": not_ready,
            "not_ready_reason": not_ready_reason,
        },
    )


@app.get("/cases/{ident}/external-reports")
async def read_external_reports(
    ident: str, request: Request, since_seq: int = 0, limit: int = 500
):
    """Durable event stream (audit-grade; state.events mirror is capped)."""

    cfg = request.app.state.settings
    await owned(request, ident)
    limit = max(1, min(limit, 2000))
    rows = await request.app.state.external.stream(
        await identity(request), cfg.node, ident, since_seq, limit
    )
    return {"events": rows, "count": len(rows)}


@app.post("/cases/{ident}/external-reports/{event_id}/confirm-resume")
async def confirm_resume(ident: str, event_id: str, request: Request):
    """User confirmation for an external risk-pause resume request."""

    cfg = request.app.state.settings
    owner = await identity(request)
    row = await owned(request, ident)
    if row["state"].get("engine") != "external":
        return _contract_response(
            409, "not_external_case", "课题不是外部执行模式"
        )
    target = await request.app.state.external.find_event_by_event_id(
        owner, cfg.node, ident, event_id
    )
    if target is None:
        raise HTTPException(404, "确认对象不存在")
    if target["kind"] != "risk-confirm-request":
        return _contract_response(
            400, "not_risk_confirm", "仅风险确认请求事件可以确认恢复"
        )
    result = await request.app.state.external.confirm_resume(
        owner, cfg.node, ident, event_id, owner[1]
    )
    confirmed, reused = result
    if not reused:
        async with request.app.state.store.edit(ident) as s:
            pending = s["external"]["risk_pending"].pop(event_id, None) or {}
            s["external"]["risk_history"] = (
                s["external"].get("risk_history", [])
                + [
                    {
                        **pending,
                        "event_id": event_id,
                        "confirmed_at": confirmed["confirmed_at"],
                        "confirmed_by": owner[1],
                    }
                ]
            )[-100:]
            event(
                s,
                "risk_confirm_accepted",
                event_id=event_id,
                risk_line=pending.get("risk_line"),
                message="用户已确认风险恢复；外部 runner 从事件流读取确认后自行恢复，平台不代为执行",
            )
    return {"status": "confirmed", "reused": reused, "event": confirmed}


@app.get("/projects/{project_key}/readiness")
async def get_readiness(project_key: str, request: Request):
    cfg, xstore, contracts = (
        request.app.state.settings,
        request.app.state.external,
        request.app.state.contracts,
    )
    owner = await identity(request)
    obj = await xstore.get_readiness(owner, cfg.node, project_key.lower())
    if obj is None:
        raise HTTPException(404, "该项目的准入对象尚未登记")
    binding = await xstore.get_acceptance_binding(owner, cfg.node, project_key.lower())
    formal_ready, reasons = external.evaluate_formal_admission(
        obj, binding, contracts.contract_hashes["2.3"]
    )
    return {
        "readiness": obj,
        "self_check_passes": external.self_check_passes(obj),
        "ready_for_research": formal_ready,
        "independently_accepted": external.independently_accepted(obj),
        "admission_reasons": reasons,
    }


@app.post("/projects/{project_key}/readiness")
async def save_readiness(project_key: str, request: Request):
    cfg = request.app.state.settings
    try:
        obj = await request.json()
    except Exception:
        raise HTTPException(400, "请求体不是合法 JSON") from None
    try:
        request.app.state.contracts.validate_readiness(obj)
    except external.ContractError as exc:
        return _contract_response(422, exc.code, exc.detail)
    if obj["project_key"] != project_key.lower():
        return _contract_response(
            422, "project_mismatch", "对象内 project_key 与路径不一致"
        )
    owner = await identity(request)
    await request.app.state.external.save_readiness(
        owner,
        cfg.node,
        project_key.lower(),
        obj,
        contract_hash=request.app.state.contracts.contract_hashes["2.3"],
    )
    binding = await request.app.state.external.get_acceptance_binding(
        owner, cfg.node, project_key.lower()
    )
    formal_ready, reasons = external.evaluate_formal_admission(
        obj, binding, request.app.state.contracts.contract_hashes["2.3"]
    )
    return {
        "readiness": obj,
        "self_check_passes": external.self_check_passes(obj),
        "ready_for_research": formal_ready,
        "independently_accepted": external.independently_accepted(obj),
        "admission_reasons": reasons,
    }


@app.get("/projects/{project_key}")
async def project_overview(project_key: str, request: Request):
    """R01 project aggregate for the workbench view (TG-003)."""

    cfg = request.app.state.settings
    owner = await identity(request)
    key = project_key.lower()
    async with request.app.state.store.pool.connection() as db:
        rows = await (
            await db.execute(
                """SELECT draft_id, state FROM research_drafts
                WHERE tenant_id=%s AND user_id=%s AND node_id=%s
                  AND state->>'engine'='external'
                  AND state->'external'->>'project_key'=%s
                ORDER BY updated_at DESC LIMIT 100""",
                (*owner, cfg.node, key),
            )
        ).fetchall()
    summaries = []
    for r in rows:
        case = public(
            r["draft_id"], r["state"], False, stale_after=cfg.external_stale_after
        )
        summaries.append({**case["external"], "case_id": r["draft_id"], "input": case["input"]})
    readiness = await request.app.state.external.get_readiness(owner, cfg.node, key)
    binding = await request.app.state.external.get_acceptance_binding(
        owner, cfg.node, key
    )
    formal_ready, admission_reasons = external.evaluate_formal_admission(
        readiness, binding, request.app.state.contracts.contract_hashes["2.3"]
    )
    blocking = readiness.get("blocking_gaps", []) if readiness else []
    reported_gaps = {}
    for s in summaries:
        for gap in s["gaps"]:
            reported_gaps.setdefault(gap["gap_id"], gap)
    return {
        "project_key": key,
        "readiness": readiness,
        "ready_for_research": formal_ready,
        "self_check_passes": external.self_check_passes(readiness),
        "independently_accepted": external.independently_accepted(readiness),
        "admission_reasons": admission_reasons,
        "cases": summaries,
        "gaps": [
            {**g, "blocking": g["gap_id"] in blocking} for g in reported_gaps.values()
        ],
        "blocking_gaps": blocking,
        "groups": external.project_groups(summaries),
        "progress": [p for s in summaries for p in s["progress"]],
        "checks": [c for s in summaries for c in s["checks"]],
        "last_event_at": max(
            (s["last_event_at"] for s in summaries if s.get("last_event_at")),
            default=None,
        ),
    }
