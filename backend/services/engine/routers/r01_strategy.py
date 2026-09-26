"""Published R01 strategies use the existing strategy store and backtest history."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from backend.services.trade_shared.deps import AuthContext, get_auth_context
from backend.shared.strategy_storage import get_strategy_storage_service
from backend.services.engine.qlib_app.services.backtest_persistence import BacktestPersistence
from backend.services.simulation.replay.etf_input_package import load_etf_input_package, verify_package_files
from backend.services.simulation.replay.strategy_program import compile_program, execution_digest
from backend.shared.stock_utils import StockCodeUtil

router = APIRouter(tags=["Strategy execution"])


def policy() -> dict:
    path = os.environ.get("R01_SPLIT_POLICY")
    if not path:
        raise HTTPException(503, "R01_SPLIT_POLICY is not configured")
    return json.loads(Path(path).read_text())


def package_root() -> Path:
    value = os.environ.get("R01_PACKAGE_ROOT")
    if not value:
        raise HTTPException(503, "R01_PACKAGE_ROOT is not configured")
    return Path(value)


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,120}$")
    content: str = Field(max_length=1_000_000)
    source_revision: str = Field(default="", max_length=100)


class PublishRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    research_case_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    group: Literal["A", "B1", "B2", "B3"]
    parameters: dict
    execution: dict
    source_files: list[SourceFile] = Field(default_factory=list, max_length=20)
    source_revision: str = Field(min_length=1, max_length=100)
    exposure: Literal["already_used", "unseen_pending_inventory", "development_only"]


async def revision_owned(strategy_id: str, revision_id: str, auth: AuthContext) -> dict:
    if not strategy_id.isdigit():
        raise HTTPException(404, "strategy_not_found")
    values = await get_strategy_storage_service().revisions(
        strategy_id, auth.user_id, auth.tenant_id, revision_id)
    if not values:
        raise HTTPException(404, "published_revision_not_found")
    return values[0]


@router.post("/strategies/{strategy_id}/revisions")
async def publish(strategy_id: str, body: PublishRevision,
                  auth: AuthContext = Depends(get_auth_context)):
    if not strategy_id.isdigit():
        raise HTTPException(404, "strategy_not_found")
    svc = get_strategy_storage_service()
    draft = await svc.get(strategy_id, user_id=auth.user_id)
    if not draft:
        raise HTTPException(404, "strategy_not_found")
    from sqlalchemy import text
    from backend.shared.database_manager_v2 import get_session
    async with get_session(read_only=True) as db:
        case = (await db.execute(text("""SELECT draft_id FROM research_drafts
            WHERE draft_id=:id AND tenant_id=:tenant AND user_id=:user"""),
            {"id": body.research_case_id, "tenant": auth.tenant_id,
             "user": auth.user_id})).first()
    if case is None:
        raise HTTPException(404, "owned_research_case_not_found")
    try:
        compile_program(draft["code"])
        pol = policy()
        end = date.fromisoformat(pol["development_end_inclusive"])
        pkg = load_etf_input_package(package_root(),
            expect_manifest_sha256=pol["input_manifest_sha256"], read_through=end)
        sums_sha256 = verify_package_files(pkg.root)
        params = dict(body.parameters)
        if not isinstance(params.get("symbols"), list):
            raise ValueError("symbols must be a list")
        params["symbols"] = sorted({StockCodeUtil.to_suffix(s) for s in params["symbols"]})
        if not params["symbols"] or any(pkg.symbol_meta(s) is None for s in params["symbols"]):
            raise ValueError("universe_not_in_input_package")
        if "target_weights" in params:
            params["target_weights"] = {StockCodeUtil.to_suffix(s): float(w)
                                       for s, w in params["target_weights"].items()}
            weights = params["target_weights"]
            if (set(weights) - set(params["symbols"]) or
                any(not math.isfinite(w) or not 0 <= w <= 1 for w in weights.values()) or
                sum(weights.values()) > 1 + 1e-9):
                raise ValueError("invalid_frozen_weights")
        if not 1 <= int(params.get("lookback", 1)) <= 504:
            raise ValueError("invalid_lookback")
        if not 0 <= int(params.get("monthly_lookback", 0)) <= 24:
            raise ValueError("invalid_monthly_lookback")
        if params.get("frequency", "monthly") not in ("monthly", "quarterly", "band", "buy_hold", "daily"):
            raise ValueError("invalid_frequency")
        from backend.services.simulation.replay.strategy_run import ledger_config
        required_execution = {"initial_cash", "price_mode", "commission_rate", "commission_min",
            "slippage_bps", "loss_line_amount", "drawdown_pct", "stale_mark_limit",
            "sublot_rule_effective", "volume_participation"}
        if required_execution - body.execution.keys():
            raise ValueError("missing_execution_fields: " + ",".join(sorted(required_execution - body.execution.keys())))
        trial = {"group": body.group, "strategy_id": strategy_id,
                 "version": 1, "execution": body.execution}
        cfg = ledger_config(trial, run_key="preflight", read_through=end)
        if cfg.initial_cash not in (20000, 30000) or cfg.price_mode != "open":
            raise ValueError("R01 requires 20000/30000 cash and next-session open execution")
        if not 0 <= cfg.commission_rate <= 0.01 or not 0 <= cfg.commission_min <= 100:
            raise ValueError("invalid_fee_assumptions")
        if (not 0 <= cfg.slippage_bps <= 100 or not 0 < cfg.drawdown_pct <= .30 or
            cfg.loss_line_amount is None or not 0 < cfg.loss_line_amount <= 9000):
            raise ValueError("invalid_frozen_risk_or_slippage")
        if not 0 < cfg.volume_participation <= 1 or not 0 <= cfg.stale_mark_limit <= 20:
            raise ValueError("invalid_participation_or_staleness")
        json.dumps(body.execution, allow_nan=False)
        files = [dict(f.model_dump(), sha256=hashlib.sha256(f.content.encode()).hexdigest())
                 for f in body.source_files]
        if (any(f["name"] in (".", "..", "strategy.py") for f in files) or
            len({f["name"] for f in files}) != len(files) or sum(len(f["content"].encode()) for f in files) > 5_000_000):
            raise ValueError("source_bundle_names_or_size_invalid")
        definition = {
            "executor_kind": "r01_ledger", "group": body.group,
            "engine_sha256": execution_digest(),
            "research_case_id": body.research_case_id,
            "parameters": params, "execution": body.execution,
            "source_files": files, "source_revision": body.source_revision,
            "exposure": body.exposure,
            "data_binding": {"package_id": pkg.package_id,
                "package_sums_sha256": sums_sha256,
                "manifest_sha256": pkg.manifest_sha256,
                "development_end": end.isoformat(),
                "holdout_start": pol["holdout_start_inclusive"],
                "holdout_end": pol["holdout_end_inclusive"], "policy_id": pol["policy_id"]},
        }
        return await svc.publish_revision(strategy_id, auth.user_id, auth.tenant_id,
            expected_code_hash=body.expected_code_sha256, definition=definition)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/strategies/{strategy_id}/revisions")
async def revisions(strategy_id: str, auth: AuthContext = Depends(get_auth_context)):
    if not strategy_id.isdigit():
        raise HTTPException(404, "strategy_not_found")
    values = await get_strategy_storage_service().revisions(strategy_id, auth.user_id, auth.tenant_id)
    # Code is fetched on opening a version, not copied into every list response.
    return [{k: v for k, v in r.items() if k not in ("code", "source_files")}
            | {"source_files": [{k: v for k, v in f.items() if k != "content"}
                                for f in r["source_files"]]} for r in values]


@router.get("/strategies/{strategy_id}/revisions/{revision_id}")
async def revision(strategy_id: str, revision_id: str, auth: AuthContext = Depends(get_auth_context)):
    return await revision_owned(strategy_id, revision_id, auth)


@router.get("/strategies/{strategy_id}/revisions/{revision_id}/source/{name}")
async def source(strategy_id: str, revision_id: str, name: str,
                 auth: AuthContext = Depends(get_auth_context)):
    r = await revision_owned(strategy_id, revision_id, auth)
    file = {"content": r["code"], "sha256": r["code_sha256"]} if name == "strategy.py" else next(
        (f for f in r["source_files"] if f["name"] == name), None)
    if file is None:
        raise HTTPException(404, "source_not_found")
    return Response(file["content"], media_type="text/plain; charset=utf-8",
                    headers={"X-Content-SHA256": file["sha256"]})


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    key: str = Field(min_length=8, max_length=128)
    start_date: date
    end_date: date
    rerun_of: str | None = Field(default=None, max_length=64)


@router.post("/strategies/{strategy_id}/backtests")
async def backtest(strategy_id: str, body: BacktestRequest,
                   auth: AuthContext = Depends(get_auth_context)):
    r = await revision_owned(strategy_id, body.revision_id, auth)
    if r["engine_sha256"] != execution_digest():
        raise HTTPException(409, "execution_engine_changed: publish a new version")
    if body.start_date > body.end_date or body.end_date.isoformat() > r["data_binding"]["development_end"]:
        raise HTTPException(409, "holdout_access_denied: 开发回测不得读取最后半年保留段")
    bp = BacktestPersistence()
    if body.rerun_of:
        prior = await bp.get_run(body.rerun_of, auth.user_id, auth.tenant_id)
        if not prior or prior["config_json"].get("strategy_revision") != body.revision_id:
            raise HTTPException(409, "rerun must use the original owned published version")
        for field in ("start_date", "end_date"):
            if prior["config_json"].get(field) != getattr(body, field).isoformat():
                raise HTTPException(409, "rerun must preserve the original dates")
    identity = json.dumps([auth.tenant_id, auth.user_id, strategy_id, body.key])
    bid = "r01bt-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
    config = {"executor_kind": "r01_ledger", "strategy_id": strategy_id,
              "strategy_revision": body.revision_id, "strategy_version": r["version"],
              "strategy_name": r["name"], "research_title": r["name"],
              "research_id": r["research_case_id"], "research_case_id": r["research_case_id"],
              "start_date": body.start_date.isoformat(), "end_date": body.end_date.isoformat(),
              "initial_cash": r["execution"]["initial_cash"],
              "rerun_of": body.rerun_of, "data_binding": r["data_binding"],
              "code_sha256": r["code_sha256"], "validation_status": "development_only"}
    config["engine_sha256"] = r["engine_sha256"]
    try:
        await bp.reserve_run(bid, auth.user_id, auth.tenant_id, config)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    row = await bp.get_run(bid, auth.user_id, auth.tenant_id)
    from backend.services.engine.qlib_app.cache_manager import get_cache_manager
    get_cache_manager().invalidate_user_history(f"{auth.tenant_id}:{auth.user_id}")
    if row["status"] == "pending":
        from backend.services.engine.tasks.r01_strategy_tasks import run_strategy_backtest
        try:
            run_strategy_backtest.apply_async(args=[bid, auth.user_id, auth.tenant_id],
                queue=os.getenv("R01_TASK_QUEUE", "qlib_backtest_srv"))
        except Exception:
            raise HTTPException(503, "已保留运行请求；任务队列不可用，可用同一请求键重试") from None
    return {"backtest_id": bid, "status": row["status"], "config": config}
