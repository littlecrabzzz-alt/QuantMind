"""Existing authenticated gateway and platform persistence bridge for Research Agent."""

import asyncio
import copy
import csv
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text

from backend.services.engine.auth_context import get_authenticated_identity
from backend.services.engine.research import runtime
from backend.services.engine.research.coordinator import experiment_config
from backend.services.engine.research.store import digest
from backend.shared.auth import get_internal_call_secret
from backend.shared.database_manager_v2 import get_session

router = APIRouter(tags=["Research Agent"])


@router.api_route("/api/v1/research-agent/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request):
    user, tenant = get_authenticated_identity(request)
    base = os.environ.get("RESEARCH_AGENT_URL", "http://research-agent:8100")
    headers = {
        "X-Internal-Call": get_internal_call_secret(),
        "X-User-Id": user,
        "X-Tenant-Id": tenant,
    }
    if request.headers.get("x-research-node"):
        headers["X-Research-Node"] = request.headers["x-research-node"]
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    body = await request.body()
    if len(body) > 3_000_000:
        raise HTTPException(413, "材料过大")
    try:
        async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
            result = await client.request(
                request.method,
                f"{base}/{path}",
                params=request.query_params,
                headers=headers,
                content=body,
            )
        return Response(
            result.content,
            status_code=result.status_code,
            media_type=result.headers.get("content-type", "application/json"),
            headers={"X-Content-Type-Options": "nosniff"},
        )
    except httpx.HTTPError:
        if path == "capabilities":
            return {
                "ready": False,
                "reason": "Agent 服务尚未在线；已有研究记录和成果保留",
                "models": [],
                "node_id": None,
            }
        raise HTTPException(
            503, "Agent 服务暂不可用，未确认的操作请查看状态后重试"
        ) from None


async def owned_case(request, ident, execute=False):
    if not hmac.compare_digest(
        request.headers.get("x-internal-call", ""), get_internal_call_secret()
    ):
        raise HTTPException(403, "仅接受Agent服务调用")
    user, tenant = get_authenticated_identity(request)
    cfg = runtime.settings()
    if request.headers.get("x-research-node") != cfg["node_id"]:
        raise HTTPException(409, "研究节点已改变")
    async with get_session(read_only=True) as db:
        row = (
            (
                await db.execute(
                    text("""SELECT state FROM research_drafts WHERE draft_id=:id
            AND tenant_id=:tenant AND user_id=:user AND node_id=:node AND state->>'engine'='deepagents'"""),
                    {
                        "id": ident,
                        "tenant": tenant,
                        "user": user,
                        "node": cfg["node_id"],
                    },
                )
            )
            .mappings()
            .first()
        )
    if not row:
        raise HTTPException(404, "课题不存在")
    s = row["state"]
    if s["inventory"]["manifest_sha256"] != cfg["manifest_sha256"]:
        raise HTTPException(409, "课题输入与当前节点模板不一致")
    if execute and (
        s["status"] == "stopping"
        or not s["approval"]
        or s["approval"]["deadline"] <= time.time()
    ):
        raise HTTPException(409, "执行授权已结束")
    return s, cfg, user, tenant


@router.post("/api/v1/research-agent-tools/{ident}/factor")
async def factor(ident: str, request: Request):
    from backend.services.engine.qlib_app.services.rd_agent_persistence import (
        RDAgentFactorPersistence,
    )

    s, cfg, user, tenant = await owned_case(request, ident, True)
    if "register_factor" not in s["approval"].get("allowed_tools", []):
        raise HTTPException(403, "当前计划没有因子入库权限")
    data = await request.json()
    code = data.get("content", "")
    if (
        not code.strip()
        or len(code.encode()) > 1_000_000
        or hashlib.sha256(code.encode()).hexdigest() != data.get("sha256")
    ):
        raise HTTPException(400, "因子代码或哈希无效")
    if not data.get("name") or len(data["name"]) > 200:
        raise HTTPException(400, "因子名称无效")
    factor_id = "research-" + digest([ident, data["sha256"]])[:32]
    metadata = {
        "research_id": ident,
        "research_node": cfg["node_id"],
        "research_tenant": tenant,
        "plan_version": s["approval"]["version"],
        "snapshot_id": cfg["snapshot_id"],
        "manifest_sha256": cfg["manifest_sha256"],
        "code_sha256": data["sha256"],
        "source_path": data["path"],
        "description": str(data.get("description", ""))[:4000],
        "validation_status": "unvalidated_candidate",
    }
    persistence = RDAgentFactorPersistence()
    await persistence.save_factor(
        factor_id,
        data["name"],
        code,
        user_id=user,
        metadata=metadata,
        market="CN",
        factor_formulation=str(data.get("formulation", ""))[:4000],
        data_source=cfg["snapshot_id"],
    )
    return {
        "id": factor_id,
        "kind": "factor",
        "name": data["name"],
        "status": "待验证候选",
        "sha256": data["sha256"],
        "path": data["path"],
        "href": f"#/alpha-research?page=library&factor={factor_id}&research={ident}",
    }


@router.post("/api/v1/research-agent-tools/{ident}/strategy")
async def strategy(ident: str, request: Request):
    from backend.shared.strategy_storage import (
        get_strategy_storage_service,
        _ensure_int_user_id,
    )

    s, cfg, user, tenant = await owned_case(request, ident, True)
    if "register_strategy" not in s["approval"].get("allowed_tools", []):
        raise HTTPException(403, "当前计划没有策略入库权限")
    data = await request.json()
    code = data.get("content", "")
    if (
        not code.strip()
        or len(code.encode()) > 1_000_000
        or hashlib.sha256(code.encode()).hexdigest() != data.get("sha256")
    ):
        raise HTTPException(400, "策略代码或哈希无效")
    if not data.get("name") or len(data["name"]) > 200:
        raise HTTPException(400, "策略名称无效")
    reference = {
        "research_id": ident,
        "research_tenant": tenant,
        "research_node": cfg["node_id"],
        "code_sha256": data["sha256"],
        "plan_version": s["approval"]["version"],
        "snapshot_id": cfg["snapshot_id"],
        "validation_status": "unvalidated_candidate",
    }
    storage_user_id = await asyncio.to_thread(_ensure_int_user_id, user)
    async with get_session() as db:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": digest([ident, data["sha256"]])},
        )
        existing = (
            await db.execute(
                text("""SELECT id FROM strategies WHERE user_id=:user
            AND config->>'research_id'=:research AND config->>'code_sha256'=:sha"""),
                {"user": storage_user_id, "research": ident, "sha": data["sha256"]},
            )
        ).scalar()
        if existing is None:
            result = await get_strategy_storage_service().save(
                user_id=user,
                name=data["name"],
                code=code,
                metadata={
                    "config": reference,
                    "description": str(data.get("description", ""))[:4000],
                    "tags": ["research", "unvalidated"],
                    "is_public": False,
                    "is_verified": False,
                },
            )
            existing = result["id"]
    return {
        "id": str(existing),
        "kind": "strategy",
        "name": data["name"],
        "status": "待验证策略草稿",
        "sha256": data["sha256"],
        "path": data["path"],
        "href": f"#/ai-ide?strategyId={existing}&research={ident}",
    }


def frozen_spec(ident, s, cfg, job_id):
    job = s["jobs"].get(job_id)
    if not job or job["kind"] != "frozen":
        raise HTTPException(404, "回测作业不存在")
    proposal = {
        "kind": "factor" if job["expression"] else "baseline",
        "hypothesis": job["purpose"],
    }
    if job["expression"]:
        proposal["factor"] = {"expression": job["expression"]}
    contract = {
        **copy.deepcopy(cfg),
        "base_config": runtime.frozen.read(
            runtime.ROOT / "inputs" / cfg["snapshot_id"] / "snapshot/config.json"
        ),
        "code_hashes": runtime.code_hashes(),
    }
    experiment = {
        "id": job_id,
        "container_name": "qm-agent-backtest-" + digest([ident, job_id])[:24],
        "proposal": proposal,
    }
    return job, contract, experiment, experiment_config(contract, proposal, {})


@router.post("/api/v1/research-agent-tools/{ident}/backtest")
async def backtest(ident: str, request: Request):
    s, cfg, _, _ = await owned_case(request, ident, True)
    if "run_frozen_backtest" not in s["approval"].get("allowed_tools", []):
        raise HTTPException(403, "当前计划没有冻结模板回测权限")
    data = await request.json()
    job, contract, experiment, config = frozen_spec(ident, s, cfg, data.get("job_id"))
    directory = runtime.case_directory(ident)
    try:
        container = await asyncio.to_thread(
            runtime.launch, directory, experiment, config, contract, job["deadline"]
        )
        fresh, _, _, _ = await owned_case(request, ident)
        if container and (
            fresh["status"] == "stopping"
            or not fresh["approval"]
            or fresh["approval"]["deadline"] <= time.time()
        ):
            await asyncio.to_thread(
                runtime.observe, directory, experiment, contract, True
            )
            return {"status": "cancelled", "error": None}
    finally:
        async with get_session() as db:
            await db.execute(
                text("""UPDATE research_drafts SET state=jsonb_set(state,
                ARRAY['jobs',:job,'launch_done'], 'true'::jsonb) WHERE draft_id=:id"""),
                {"id": ident, "job": job["id"]},
            )
    if container is None:
        return {
            "status": "blocked",
            "error": "当前节点已有重计算作业，或剩余时间不足；可稍后重新确认计划",
        }
    return {"status": "running", "name": experiment["container_name"], "error": None}


@router.post("/api/v1/research-agent-tools/{ident}/backtest-status")
async def backtest_status(ident: str, request: Request):
    from backend.services.engine.qlib_app.schemas.backtest import QlibBacktestResult
    from backend.services.engine.qlib_app.services.backtest_persistence import (
        BacktestPersistence,
    )

    s, cfg, user, tenant = await owned_case(request, ident)
    data = await request.json()
    job, contract, experiment, config = frozen_spec(ident, s, cfg, data.get("job_id"))
    directory = runtime.case_directory(ident)
    output = directory / "experiments" / job["id"]
    if await asyncio.to_thread(runtime.inspect, experiment["container_name"]) is None:
        if not job.get("launch_done"):
            return {"status": "launching", "error": None}
        return {"status": "missing", "error": "提交结果不明且原容器不存在，不自动重跑"}
    try:
        result = await asyncio.to_thread(
            runtime.observe, directory, experiment, contract, bool(data.get("stop"))
        )
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)[:400]}
    if result is None:
        return {"status": "running", "error": None}
    if data.get("stop"):
        return {"status": "cancelled", "error": "用户已停止回测"}
    metrics = result["summary"]["comparison"]["model"]
    with (output / "model-equity.csv").open() as stream:
        curve = [
            {"date": r["date"], "value": float(r["account"])}
            for r in csv.DictReader(stream)
        ]
    backtest_id = "research-" + digest([ident, job["id"]])[:32]
    reference = {
        "research_id": ident,
        "research_job_id": job["id"],
        "research_node": cfg["node_id"],
        "snapshot_id": cfg["snapshot_id"],
        "manifest_sha256": cfg["manifest_sha256"],
        "artifacts": result["artifacts"],
        "validation_status": "development_comparison",
        "strategy_type": "TopkDropout",
        "initial_capital": config["portfolio"]["initial_capital"],
        "start_date": config["split"]["test"][0],
        "end_date": config["split"]["test"][1],
        "research_title": s["plans"][-1]["plan"]["title"],
    }
    record = QlibBacktestResult(
        backtest_id=backtest_id,
        user_id=user,
        tenant_id=tenant,
        status="completed",
        config=reference,
        annual_return=None,
        sharpe_ratio=None,
        max_drawdown=metrics["max_drawdown"],
        total_return=metrics["total_return"],
        total_trades=metrics["trades"],
        equity_curve=curve,
        factor_metrics=result.get("factor_analysis"),
        advanced_stats={
            "verification": result["verification"],
            "comparison": result["summary"]["comparison"],
        },
    )
    persistence = BacktestPersistence()
    await persistence.save_run(
        backtest_id,
        user,
        tenant,
        "completed",
        datetime.fromtimestamp(job["created_at"], timezone.utc),
        reference,
        record,
        datetime.now(timezone.utc),
    )
    outcome = {
        "id": backtest_id,
        "kind": "backtest",
        "name": job["purpose"][:200],
        "status": "开发区间回测 · 账务已核验",
        "href": f"#/backtest?research={ident}&backtest={backtest_id}",
        "metrics": metrics,
        "curve": curve,
        "comparison": result["summary"]["comparison"],
    }
    return {
        "status": "completed",
        "outcome": outcome,
        "summary": result["summary"],
        "artifacts": result["artifacts"],
    }
