"""Reuse the existing frozen stock-factor template; no second factor/backtest engine."""

import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from .continuous_state import fingerprint


def freeze(end_date):
    from backend.services.engine.research import runtime

    cfg = runtime.settings()
    override = runtime.ROOT / "continuous-stock-settings.json"
    if override.exists():
        new = runtime.frozen.read(override)
        source = Path(new["source"])
        if (
            new["role"] != cfg["role"]
            or new["host_data"] != cfg["host_data"]
            or not source.resolve().is_relative_to((runtime.ROOT / "inputs").resolve())
            or runtime.frozen.sha256(source / "manifest.json") != new["manifest_sha256"]
        ):
            raise ValueError("continuous_stock_input_binding_invalid")
        cfg = new
    base = runtime.frozen.read(Path(cfg["source"]) / "snapshot/config.json")
    base = copy.deepcopy(base)
    # Existing snapshot contains later dates. This clips configuration only;
    # it does not prove loader/label enforcement. See stock-boundary-20260927
    # in DEEP-RESEARCH.md; the affected live stock scope is operator-held.
    for dates in base["split"].values():
        dates[1] = min(dates[1], end_date)
        if dates[0] > dates[1]:
            raise ValueError("stock_split_outside_development_boundary")
    base["development_end"] = end_date
    return {
        **cfg,
        "base_config": base,
        "code_hashes": runtime.code_hashes(),
        "boundary": end_date,
        "validation_status": "development_only",
        "segment_semantics": "train=fit; valid=tuning; test=exposed development comparison, never holdout",
    }


def inventory(contract):
    base = contract["base_config"]
    return {
        k: contract[k]
        for k in ("snapshot_id", "manifest_sha256", "boundary", "segment_semantics")
    } | {
        "market": "A股主板",
        "features": base["features"],
        "split": base["split"],
        "universe": base["universe"],
        "portfolio": base["portfolio"],
        "fees": base["exchange"],
        "expression_functions": "rank, abs, log1p_abs, lag, mean, std; + - * /; n=1..60; total lookback<=120",
        "warning": "冻结的100只股票/1000万资金模型实验，用于因子研究；不能视为2–3万元可执行策略。",
    }


async def submit(ident, c, t, action, auth):
    from pydantic import BaseModel, ConfigDict, Field
    from typing import Literal
    from backend.services.engine.research.coordinator import experiment_config
    from backend.services.engine.qlib_app.services.backtest_persistence import (
        BacktestPersistence,
    )
    from backend.services.engine.qlib_app.services.rd_agent_persistence import (
        RDAgentFactorPersistence,
    )
    from backend.services.engine.tasks.continuous_stock_tasks import run_stock_research
    from research_expression import validate

    class StockAction(BaseModel):
        model_config = ConfigDict(extra="forbid")
        action: Literal["stock_factor"]
        name: str = Field(min_length=1, max_length=100)
        hypothesis: str = Field(min_length=1, max_length=4000)
        expression: str = Field(max_length=800)

    a = StockAction.model_validate(action).model_dump()
    contract = c.get("stock_contract")
    if not contract:
        raise ValueError("stock_research_not_enabled")
    if a["expression"]:
        validate(a["expression"], contract["base_config"]["features"])
    if t["kind"] != "stock_factor":
        raise ValueError("stock_action_requires_stock_task")
    proposal = {
        "kind": "factor" if a["expression"] else "baseline",
        "hypothesis": a["hypothesis"],
    }
    if a["expression"]:
        proposal["factor"] = {"expression": a["expression"]}
    cfg = experiment_config(contract, proposal, {})
    key = fingerprint([contract["manifest_sha256"], cfg])
    if key in t["experiments"]:
        return t["experiments"][key]
    for other in c["tasks"].values():
        old = other["experiments"].get(key)
        if old and old.get("kind") == "stock_factor":
            result = {
                **a,
                **{
                    k: old.get(k)
                    for k in (
                        "backtest_id",
                        "factor_id",
                        "kind",
                        "input_manifest_sha256",
                    )
                },
                "reused_from_task": other["id"],
                "note": "复用同输入与配置的公共结果，不是独立重复验证",
            }
            t["experiments"][key] = result
            return result
    if len(t["experiments"]) >= c["contract"]["max_experiments_per_task"]:
        raise ValueError("task_experiment_limit_reached")
    if not t["experiments"] and a["expression"]:
        raise ValueError("run_empty_expression_baseline_first")
    if a["expression"]:
        baseline = next(
            (e for e in t["experiments"].values() if e.get("expression") == ""), None
        )
        row = (
            await BacktestPersistence().get_run(
                baseline["backtest_id"], auth.user_id, auth.tenant_id
            )
            if baseline
            else None
        )
        if not row or row["status"] != "completed":
            raise ValueError("stock_baseline_must_complete_before_factor_research")
    bid = "glmstock-" + fingerprint([ident, t["id"], key])[:32]
    fid = (
        "glm-factor-"
        + fingerprint([ident, a["expression"], contract["manifest_sha256"]])[:32]
        if a["expression"]
        else None
    )
    if fid:
        code = (
            "# QuantMind frozen research_expression v1; executed by the common frozen template.\n"
            "# Only the declared historical QuantDB columns are available.\n"
            "from research_expression import evaluate\n"
            f"EXPRESSION = {a['expression']!r}\nCOLUMNS = {contract['base_config']['features']!r}\n"
            "def calculate_factor(frame):\n    return evaluate(frame, EXPRESSION, COLUMNS)\n"
        )
        await RDAgentFactorPersistence().save_factor(
            fid,
            a["name"],
            code,
            user_id=auth.user_id,
            market="CN",
            factor_formulation=a["expression"],
            data_source=contract["snapshot_id"],
            metadata={
                "research_id": ident,
                "research_task_id": t["id"],
                "research_tenant": auth.tenant_id,
                "research_node": c["node_id"]
                if "node_id" in c
                else "mac-glm-continuous-v1",
                "snapshot_id": contract["snapshot_id"],
                "manifest_sha256": contract["manifest_sha256"],
                "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "description": a["hypothesis"],
                "validation_status": "unvalidated_candidate",
                "evaluator": "frozen_research_expression_v1",
                "evaluation_note": "本候选通过冻结特征模板检验；不使用通用 OHLC 快速验证器。",
            },
        )
    config = {
        "executor_kind": "frozen_stock_research",
        "research_id": ident,
        "research_case_id": ident,
        "research_title": a["name"],
        "research_task_id": t["id"],
        "start_date": cfg["split"]["test"][0],
        "end_date": cfg["split"]["test"][1],
        "initial_capital": cfg["portfolio"]["initial_capital"],
        "strategy_type": "LightGBM+TopkDropout",
        "validation_status": "development_only",
        "factor_id": fid,
        "stock_contract": contract,
        "experiment_config": cfg,
        "proposal": proposal,
        "data_binding": {
            "snapshot_id": contract["snapshot_id"],
            "manifest_sha256": contract["manifest_sha256"],
        },
    }
    bp = BacktestPersistence()
    await bp.reserve_run(bid, auth.user_id, auth.tenant_id, config)
    row = await bp.get_run(bid, auth.user_id, auth.tenant_id)
    if row["status"] in ("pending", "running"):
        import os

        run_stock_research.apply_async(
            args=[bid, auth.user_id, auth.tenant_id],
            queue=os.getenv("R01_TASK_QUEUE", "glm-research"),
        )
    result = dict(
        a,
        backtest_id=bid,
        factor_id=fid,
        kind="stock_factor",
        input_manifest_sha256=contract["manifest_sha256"],
    )
    t["experiments"][key] = result
    return result
