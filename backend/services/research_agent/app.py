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
from fastapi.responses import Response
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

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


def public(ident, state, details=True):
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
    return {
        "cases": [
            public(row["draft_id"], row["state"], False)
            for row in await request.app.state.store.list(
                await identity(request), request.app.state.settings.node
            )
        ]
    }


@app.post("/cases")
async def create(data: Input, request: Request):
    cfg, store = request.app.state.settings, request.app.state.store
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
    result = public(ident, (await owned(request, ident))["state"])
    result["events"] = [e for e in result["events"] if e["seq"] > after]
    result["files"] = await asyncio.to_thread(
        files, request.app.state.settings.workspace(ident)
    )
    return result


@app.post("/cases/{ident}/messages")
async def message(ident: str, data: Message, request: Request):
    await owned(request, ident)
    async with request.app.state.store.edit(ident) as s:
        if data.key not in s["requests"] and data.interrupt:
            stop(s)
        enqueue(s, data.key, data.content, "question")
    return {"status": "received", "message_id": data.key}


@app.post("/cases/{ident}/stop")
async def cancel(ident: str, request: Request):
    await owned(request, ident)
    async with request.app.state.store.edit(ident) as s:
        if s["status"] != "stopping":
            stop(s)
    return {"status": "stopping"}


@app.post("/cases/{ident}/approve")
async def approve(ident: str, data: Approval, request: Request):
    await owned(request, ident)
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
    await owned(request, ident)
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
