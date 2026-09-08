"""Authenticated product entry point for both kinds of bounded research."""
from __future__ import annotations

import csv
import json
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.services.engine.auth_context import get_authenticated_identity
from backend.services.engine.research import runtime
from backend.services.engine.research.store import Store, digest

router = APIRouter(prefix="/api/v1/research-runs", tags=["Research workbench"])
store = Store()
DEFAULT_GOALS = {"strategy": "研究现有八因子策略的稳定增量，比较基线、候选和双倍费用表现",
                 "method": "研究动量与量价关系的新因子，验证覆盖率、IC 稳定性与组合增量"}


class NewResearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    node_id: str
    kind: Literal["strategy", "method"]
    goal: str = Field(default="", max_length=1200)
    hours: float = Field(default=2, ge=.1, le=8)
    candidate_limit: int = Field(default=2, ge=1, le=2)
    model: str = Field(default="glm-5.3-flash", max_length=100)
    expression: str = Field(default="", max_length=800)
    source_text: str = Field(default="", max_length=12000)
    source_run_id: str | None = None
    source_experiment_id: str | None = None


class ContinueResearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    node_id: str
    hours: float = Field(default=2, ge=.1, le=8)


def owner(request):
    user, tenant = get_authenticated_identity(request)
    return tenant, user


def configured(request=None):
    try:
        cfg = runtime.settings()
        if request and request.headers.get("x-research-node", cfg["node_id"]) != cfg["node_id"]:
            raise HTTPException(409, "运行节点已改变，请刷新页面")
        return cfg
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(503, "研究运行环境尚未就绪，请配置数据模板与执行服务") from exc


async def owned(request, run_id):
    cfg = configured(request)
    expected = request.headers.get("x-research-node")
    if expected and expected != cfg["node_id"]:
        raise HTTPException(409, "运行节点已改变，请刷新页面")
    rows = await store.get(owner(request), cfg["node_id"], run_id)
    if not rows:
        raise HTTPException(404, "研究任务不存在或不属于当前账户和节点")
    return rows[0]


def public(row, details=False):
    c, s = row["contract"], row["checkpoint"]
    result = {k: row[k] for k in ("run_id", "case_id", "node_id", "kind", "goal", "status", "started_at", "updated_at", "deadline_epoch")}
    result.update({"stage": s.get("stage", "baseline"), "error": s.get("error"),
                   "environment": c["environment"], "snapshot_id": c["snapshot_id"],
                   "model": c["model"], "candidate_limit": c["candidate_limit"],
                   "completed_experiments": sum(e["status"] == "completed" for e in s.get("experiments", [])),
                   "usage": s.get("usage"), "selection": s.get("selection"),
                   "research_status": s.get("research_status", "development_comparison"),
                   "active": {k: s["active"].get(k) for k in ("id", "status", "proposal")} if s.get("active") else None})
    if details:
        result["events"] = s.get("events", [])
        result["base_config"] = c["base_config"]
        result["lineage"] = c.get("lineage")
        result["experiments"] = [{k: e.get(k) for k in ("id", "status", "proposal", "gates", "result")} for e in s.get("experiments", [])]
        curves = []
        directory = runtime.case_directory(row["case_id"])
        from backend.services.engine.research.coordinator import usage
        result["usage"] = usage(directory)
        for exp in s.get("experiments", []):
            if exp["status"] != "completed":
                continue
            names = ("model", "single_factor", "equal_weight") if exp["proposal"]["kind"] == "baseline" else ("model",)
            for name in names:
                file = directory / "experiments" / exp["id"] / f"{name}-equity.csv"
                if runtime.frozen.sha256(file) != exp["result"]["artifacts"][file.name]:
                    raise HTTPException(409, "结果文件发生变化，暂停展示未能核验的曲线")
                with file.open() as stream:
                    values = [{"date": r["date"], "nav": float(r["account"])/c["base_config"]["portfolio"]["initial_capital"]} for r in csv.DictReader(stream)]
                curves.append({"name": exp["id"]+" / "+name, "values": values})
        result["curves"] = curves
        result["report_available"] = bool(s.get("report_sha256"))
    return result


@router.get("/capabilities")
async def capabilities(request: Request):
    who = owner(request)
    try:
        cfg = runtime.settings()
        heartbeat = runtime.frozen.read(runtime.ROOT / "heartbeat.json")
        worker_ready = heartbeat["node_id"] == cfg["node_id"] and time.time()-heartbeat["at"] < 300
        available_models = runtime.models()
        base = runtime.frozen.read(runtime.ROOT / "inputs" / cfg["snapshot_id"] / "snapshot/config.json")
        return {"ready": worker_ready, "reason": None if worker_ready else "研究执行服务尚未在线",
            "node_id": cfg["node_id"], "owner_scope": digest([*who, cfg["node_id"]])[:24], "environment": cfg["label"], "role": cfg["role"],
            "snapshot_id": cfg["snapshot_id"], "models": available_models, "base_config": base,
            "templates": [{"kind": kind, "goal": goal} for kind, goal in DEFAULT_GOALS.items()],
            "max_hours": 8, "method_scope": "原始特征的因果公式、对照与增量验证；论文全文须提供可用内容"}
    except (OSError, ValueError, KeyError):
        return {"ready": False, "reason": "研究数据模板、模型配置或执行服务尚未就绪", "node_id": None, "models": []}


@router.post("")
async def create(req: NewResearch, request: Request):
    cfg = configured(request)
    who = owner(request)
    if req.node_id != cfg["node_id"]:
        raise HTTPException(409, "运行节点已改变，请刷新页面后重新发起")
    try:
        if req.model not in runtime.models():
            raise ValueError("模型未在当前执行节点配置")
        base = runtime.frozen.read(runtime.ROOT / "inputs" / cfg["snapshot_id"] / "snapshot/config.json")
        if req.expression:
            from research_expression import validate
            validate(req.expression, base["features"])
        payload = req.model_dump()
        payload["goal"] = req.goal.strip() or DEFAULT_GOALS[req.kind]
        contract = {"base_config": base, "source": cfg["source"], "image": cfg["image"],
            "manifest_sha256": cfg["manifest_sha256"], "snapshot_id": cfg["snapshot_id"],
            "node_id": cfg["node_id"], "environment": cfg["label"], "candidate_limit": req.candidate_limit,
            "model": req.model, "model_base_url": runtime.credentials()["base_url"],
            "source_text": req.source_text, "expression": req.expression,
            "code_hashes": runtime.code_hashes(), "acceptance": {"min_return_improvement": .005,
                "max_drawdown_degradation": .01, "min_validation_rank_ic": 0, "min_half_excess": -.005}}
        if req.source_run_id:
            parent = await owned(request, req.source_run_id)
            if req.kind != "strategy" or parent["kind"] != "method" or parent["status"] != "completed":
                raise ValueError("只有已完成方法研究的因子可创建关联策略研究")
            if parent["contract"]["manifest_sha256"] != contract["manifest_sha256"]:
                raise ValueError("父研究的数据快照与当前模板不同，需要重新登记")
            exp = next((e for e in parent["checkpoint"]["experiments"] if e["id"] == req.source_experiment_id), None)
            if not exp or exp["status"] != "completed" or not exp["proposal"].get("factor"):
                raise ValueError("请选择已经实际计算并核验的因子")
            artifact = runtime.case_directory(parent["case_id"]) / "experiments" / exp["id"] / "factor-definition.json"
            if runtime.frozen.sha256(artifact) != exp["result"]["artifacts"][artifact.name]:
                raise ValueError("父研究的因子定义未通过完整性检查")
            contract["seed_factor"] = runtime.frozen.read(artifact)
            contract["lineage"] = {"case_id": parent["case_id"], "run_id": parent["run_id"], "experiment_id": exp["id"],
                                   "factor_sha256": exp["result"]["artifacts"][artifact.name]}
        run_id = await store.create(who, cfg["node_id"], req.idempotency_key, payload, contract)
    except (ValueError, SyntaxError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return public((await store.get(who, cfg["node_id"], run_id))[0])


@router.get("")
async def list_research(request: Request):
    return {"runs": [public(row) for row in await store.get(owner(request), configured(request)["node_id"])]}


@router.get("/{run_id}")
async def detail(run_id: str, request: Request):
    return public(await owned(request, run_id), True)


@router.post("/{run_id}/controls/{action}")
async def control(run_id: str, action: Literal["pause", "cancel"], request: Request):
    row = await owned(request, run_id)
    if not await store.control(owner(request), row["node_id"], run_id, action):
        raise HTTPException(409, "任务状态已改变，请刷新后查看")
    return {"requested": action, "run_id": run_id}


@router.post("/{run_id}/continue-window")
async def resume(run_id: str, req: ContinueResearch, request: Request):
    row = await owned(request, run_id)
    if req.node_id != row["node_id"]:
        raise HTTPException(409, "运行节点已改变")
    try:
        new_id = await store.create(owner(request), row["node_id"], req.idempotency_key,
            {**req.model_dump(), "parent": run_id}, row["contract"], parent=run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return public((await store.get(owner(request), row["node_id"], new_id))[0])


@router.get("/{run_id}/report/download")
async def report(run_id: str, request: Request):
    row = await owned(request, run_id)
    path = runtime.case_directory(row["case_id"]) / "REPORT.md"
    expected = row["checkpoint"].get("report_sha256")
    if not expected or not path.exists():
        raise HTTPException(404, "报告尚未完成")
    if runtime.frozen.sha256(path) != expected:
        raise HTTPException(409, "报告内容发生变化")
    return FileResponse(path, media_type="text/markdown", filename=f"research-{run_id}.md")


@router.get("/{run_id}/artifacts/{experiment_id}/{name}")
async def artifact(run_id: str, experiment_id: str, name: str, request: Request):
    row = await owned(request, run_id)
    exp = next((e for e in row["checkpoint"].get("experiments", []) if e["id"] == experiment_id and e["status"] in ("completed", "failed")), None)
    expected = (exp or {}).get("result", {}).get("artifacts", {}).get(name)
    if not expected or "/" in name or "\\" in name:
        raise HTTPException(404, "产物不存在或尚未核验")
    path = runtime.case_directory(row["case_id"]) / "experiments" / experiment_id / name
    if runtime.frozen.sha256(path) != expected:
        raise HTTPException(409, "产物完整性检查失败")
    return FileResponse(path, filename=name)
