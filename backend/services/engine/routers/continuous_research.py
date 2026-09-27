"""Unattended Pi research, in existing research_drafts and public strategy APIs.

Only the local coordinator has platform authentication. The model emits one
allowlisted action at a time; it has no shell, files, credentials or paper API.
"""

from __future__ import annotations
import ast
import copy
import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from backend.shared.database_manager_v2 import get_session
from backend.shared.utils import normalize_user_id
from backend.shared.strategy_storage import get_strategy_storage_service
from backend.services.trade_shared.deps import AuthContext, get_auth_context
from backend.services.research_agent import continuous_state as st
from backend.services.simulation.replay.strategy_program import (
    compile_program,
    FIXED_ALLOCATION_SOURCE,
    DYNAMIC_ALLOCATION_SOURCE,
)
from . import r01_strategy as public

router = APIRouter(prefix="/continuous-research", tags=["Continuous research"])
NODE = "mac-glm-continuous-v1"
EXECUTION = {
    "initial_cash": 30000,
    "price_mode": "open",
    "commission_rate": 0.0003,
    "commission_min": 5,
    "slippage_bps": 5,
    "loss_line_amount": 9000,
    "drawdown_pct": 0.30,
    "stale_mark_limit": 5,
    "sublot_rule_effective": "2014-08-01",
    "volume_participation": 0.1,
}


class Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(default="glm-etf-development-v1", min_length=8, max_length=100)
    concurrency: int = Field(default=3, ge=1, le=3)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: str
    worker: str = Field(default="", max_length=100)
    task_id: str = Field(default="", max_length=64)
    lease: str = Field(default="", max_length=64)
    data: dict = Field(default_factory=dict)


class ExperimentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["experiment"]
    name: str = Field(min_length=1, max_length=100)
    hypothesis: str = Field(min_length=1, max_length=4000)
    code: str = Field(min_length=1, max_length=64000)
    parameters: dict
    start_date: date
    end_date: date


class Followup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["experiment", "evidence_review"] = "experiment"
    topic: Literal["trend", "momentum", "risk", "stock_signal", "stock_risk"]
    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
    backtest_ids: list[str] = Field(default_factory=list, max_length=6)


class ReportAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["report"]
    text: str = Field(min_length=100, max_length=20000)
    followups: list[Followup] = Field(default_factory=list, max_length=3)
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)


class EvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal[
        "data_coverage", "data_semantics", "research_review", "method_review"
    ]
    question: str = Field(min_length=10, max_length=1800)
    reason: str = Field(min_length=10, max_length=2000)
    evidence: dict


def reject_quarantined_metric_fields(evidence):
    """Reject known contaminated structured fields, not incident descriptions.

    This key barrier cannot identify contaminated metrics copied into free text.
    """
    forbidden = {"model_metadata_metrics", "test_metrics", "model_metrics"}
    pending = [evidence]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            blocked = forbidden.intersection(item)
            if blocked:
                raise ValueError(
                    "evidence_contains_quarantined_metric_field:" + sorted(blocked)[0]
                )
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


@asynccontextmanager
async def edit(ident, auth):
    async with get_session() as db:
        row = (
            await db.execute(
                text("""SELECT state FROM research_drafts
          WHERE draft_id=:id AND tenant_id=:tenant AND user_id=:user AND node_id=:node FOR UPDATE"""),
                {
                    "id": ident,
                    "tenant": auth.tenant_id,
                    "user": auth.user_id,
                    "node": NODE,
                },
            )
        ).first()
        if not row or not row[0].get("continuous"):
            raise HTTPException(404, "continuous_program_not_found")
        state = row[0]
        try:
            yield state["continuous"], db
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        state["status"] = state["continuous"]["status"]
        if state["continuous"].get("title"):
            state["input"]["title"] = state["continuous"]["title"]
        await db.execute(
            text(
                "UPDATE research_drafts SET state=CAST(:state AS jsonb), updated_at=now() WHERE draft_id=:id"
            ),
            {
                "id": ident,
                "state": json.dumps(state, ensure_ascii=False, allow_nan=False),
            },
        )


def visible(ident, c):
    out = copy.deepcopy(c)
    for t in out["tasks"].values():
        t.pop("lease", None)
    return dict(
        id=ident,
        **out,
        heartbeat_stale=time.time() - (c.get("last_heartbeat") or 0) > 120,
    )


@router.get("")
async def listing(auth: AuthContext = Depends(get_auth_context)):
    async with get_session(read_only=True) as db:
        rows = (
            await db.execute(
                text("""SELECT draft_id,state->'continuous' AS c FROM research_drafts
          WHERE tenant_id=:tenant AND user_id=:user AND node_id=:node AND COALESCE(state->>'workspace_category','research')='research' ORDER BY updated_at DESC LIMIT 20"""),
                {"tenant": auth.tenant_id, "user": auth.user_id, "node": NODE},
            )
        ).all()
    return [visible(r[0], r[1]) for r in rows if r[1]]


@router.post("")
async def create(body: Create, auth: AuthContext = Depends(get_auth_context)):
    pol = public.policy()
    from backend.services.simulation.replay.etf_input_package import (
        load_etf_input_package,
    )

    pkg = load_etf_input_package(
        public.package_root(),
        expect_manifest_sha256=pol["input_manifest_sha256"],
        read_through=date.fromisoformat(pol["development_end_inclusive"]),
    )
    symbols = sorted(x["code"] for x in pkg.manifest["symbols"])
    contract = {
        "concurrency": body.concurrency,
        "reserve_percent": 1,
        "max_experiments_per_task": 6,
        "start_date": "2014-08-01",
        "end_date": pol["development_end_inclusive"],
        "policy_id": pol["policy_id"],
        "input_manifest_sha256": pol["input_manifest_sha256"],
        "execution": EXECUTION,
        "symbols": symbols,
        "validation": "development_only",
        "paper_authorized": False,
    }
    ident = st.fingerprint([auth.tenant_id, auth.user_id, NODE, body.key])[:32]
    s = {
        "engine": "external",
        "node_id": NODE,
        "status": "stopped",
        "workspace_category": "research",
        "input": {
            "key": body.key,
            "title": "GLM 持续研究：趋势、动量、风险仓位",
            "question": "独立研究新策略及信号；不修改已有账户",
        },
        "external": {
            "project": "R01",
            "workstream": "持续研究",
            "execution_status": "stopped",
        },
        "continuous": st.initial(contract),
        "created_at": time.time(),
    }
    async with get_session() as db:
        await db.execute(
            text("""INSERT INTO research_drafts(draft_id,tenant_id,user_id,node_id,input_hash,state)
            VALUES(:id,:tenant,:user,:node,:hash,CAST(:state AS jsonb)) ON CONFLICT DO NOTHING"""),
            {
                "id": ident,
                "tenant": auth.tenant_id,
                "user": auth.user_id,
                "node": NODE,
                "hash": st.fingerprint(body.key),
                "state": json.dumps(s, ensure_ascii=False),
            },
        )
    async with edit(ident, auth) as (c, _):
        if c["contract"] != contract:
            raise ValueError("program_contract_changed_use_new_key")
        return visible(ident, c)


async def results(t, auth):
    found = {}
    for key, exp in t["experiments"].items():
        bid = exp.get("backtest_id")
        if not bid:
            continue
        async with get_session(read_only=True) as db:
            r = (
                await db.execute(
                    text("""SELECT status,result_json,result_json->>'error_message' FROM qlib_backtest_runs
              WHERE backtest_id=:id AND user_id=:user AND tenant_id=:tenant"""),
                    {
                        "id": bid,
                        "user": normalize_user_id(auth.user_id),
                        "tenant": auth.tenant_id,
                    },
                )
            ).first()
        if r:
            payload = r[1] or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            found[key] = {
                "backtest_id": bid,
                "status": r[0],
                "error": r[2],
                "metrics": {
                    k: v
                    for k, v in payload.items()
                    if k
                    in (
                        "annual_return",
                        "total_return",
                        "max_drawdown",
                        "sharpe_ratio",
                        "volatility",
                        "total_trades",
                        "win_rate",
                        "advanced_stats",
                        "error_message",
                    )
                },
            }
    return found


async def act(ident, c, t, action, auth, db):
    """No model-selected object IDs, execution fees, dates beyond contract, or URLs."""
    if not isinstance(action, dict):
        raise ValueError("action must be an object")
    kind = action.get("action")
    if t["kind"] == "evidence_review" and kind != "report":
        raise ValueError("evidence_review_is_read_only")
    if kind == "stock_factor":
        from backend.services.research_agent.continuous_stock import submit

        return await submit(ident, c, t, action, auth)
    if kind == "experiment" and t["kind"] == "stock_factor":
        raise ValueError("stock_task_requires_stock_factor_action")
    if kind == "experiment":
        action = ExperimentAction.model_validate(action).model_dump(mode="json")
    elif kind == "report":
        action = ReportAction.model_validate(action).model_dump(mode="json")
    if kind == "experiment":
        required = {
            "action",
            "name",
            "hypothesis",
            "code",
            "parameters",
            "start_date",
            "end_date",
        }
        if set(action) != required:
            raise ValueError("experiment_fields_invalid")
        start, end = (
            date.fromisoformat(action["start_date"]),
            date.fromisoformat(action["end_date"]),
        )
        if (
            not c["contract"]["start_date"]
            <= start.isoformat()
            <= end.isoformat()
            <= c["contract"]["end_date"]
        ):
            raise ValueError("holdout_or_out_of_contract_dates_denied")
        if (
            not action["hypothesis"].strip()
            or len(action["hypothesis"]) > 4000
            or len(action["name"]) > 100
        ):
            raise ValueError("hypothesis_required")
        compile_program(action["code"])
        key = st.fingerprint(
            [
                ast.dump(ast.parse(action["code"])),
                action["parameters"],
                start.isoformat(),
                end.isoformat(),
            ]
        )
        if key in t["experiments"]:
            old = t["experiments"][key]
            return {k: old[k] for k in ("strategy_id", "revision_id", "backtest_id")}
        if (
            key not in t["experiments"]
            and len(t["experiments"]) >= c["contract"]["max_experiments_per_task"]
        ):
            raise ValueError("task_experiment_limit_reached")
        params = action["parameters"]
        if (
            not isinstance(params, dict)
            or not isinstance(params.get("symbols"), list)
            or not params["symbols"]
        ):
            raise ValueError("parameters.symbols must be a nonempty list of ETF codes")
        if set(params.get("symbols", [])) - set(c["contract"]["symbols"]):
            raise ValueError("symbols_outside_contract")
        # Durable metadata recovers a strategy created before a controller/HTTP
        # crash. Row lock serializes this operation; source revision/backtest
        # keys then make the remaining public calls idempotent.
        marker = st.fingerprint([ident, t["id"], key])
        row = (
            await db.execute(
                text("""SELECT id,code FROM strategies WHERE user_id=:user
            AND config->>'continuous_marker'=:marker ORDER BY id LIMIT 1"""),
                {"user": int(auth.user_id), "marker": marker},
            )
        ).first()
        svc = get_strategy_storage_service()
        if row:
            if row[1] != action["code"]:
                raise ValueError("candidate_recovery_source_mismatch")
            sid = str(row[0])
        else:
            saved = await svc.save(
                auth.user_id,
                "GLM·" + action["name"],
                action["code"],
                metadata={
                    "parameters": {
                        **params,
                        "research_case_id": ident,
                        "validation_status": "development_only",
                    },
                    "config": {
                        "continuous_marker": marker,
                        "continuous_program": ident,
                        "continuous_task": t["id"],
                        "hypothesis": action["hypothesis"],
                        "validation_status": "development_only",
                    },
                },
            )
            sid = str(saved["id"])
        revision = await public.publish(
            sid,
            public.PublishRevision(
                expected_code_sha256=hashlib.sha256(
                    action["code"].encode()
                ).hexdigest(),
                research_case_id=ident,
                group=st.TOPICS[t["topic"]][2],
                parameters=params,
                execution=c["contract"]["execution"],
                source_revision="continuous-" + marker,
                exposure="development_only",
            ),
            auth,
        )
        result = await public.backtest(
            sid,
            public.BacktestRequest(
                revision_id=revision["revision_id"],
                key="continuous-" + marker,
                start_date=start,
                end_date=end,
            ),
            auth,
        )
        t["experiments"][key] = dict(
            action,
            strategy_id=sid,
            revision_id=revision["revision_id"],
            backtest_id=result["backtest_id"],
            created_at=time.time(),
        )
        return dict(strategy_id=sid, revision_id=revision["revision_id"], **result)
    if kind == "report":
        if (
            set(action) - {"action", "text", "followups", "evidence_ids"}
            or not 100 <= len(action.get("text", "")) <= 20000
        ):
            raise ValueError("report_requires_100_to_20000_characters")
        review = t["kind"] == "evidence_review"
        if review:
            evidence = t.get("evidence") or {}
            if action.get("evidence_ids") != [evidence.get("id")]:
                raise ValueError("review_must_cite_bound_evidence")
            if action.get("followups"):
                raise ValueError("review_proposals_require_new_evidence_assignment")
        elif not t["experiments"]:
            raise ValueError("report_requires_public_experiment")
        rs = await results(t, auth)
        if len(rs) != len(t["experiments"]) or any(
            r["status"] in ("pending", "running") for r in rs.values()
        ):
            raise ValueError("experiments_not_terminal")
        # Validate all proposals before saving, independently of queue capacity.
        preview = {"tasks": {}}
        for proposal in action.get("followups", [])[:3]:
            if (
                proposal.get("topic") not in st.TOPICS
                or not proposal.get("reason", "").strip()
            ):
                raise ValueError("followup_scope_or_evidence_missing")
            if proposal["kind"] == "evidence_review":
                ids = proposal["backtest_ids"]
                allowed = {
                    e["backtest_id"]
                    for source in c["tasks"].values()
                    if source["kind"] == "research"
                    for e in source["experiments"].values()
                    if e.get("kind") != "stock_factor" and e.get("backtest_id")
                }
                if (
                    t["kind"] != "research"
                    or proposal["topic"].startswith("stock_")
                    or not proposal["question"].strip()
                    or not ids
                    or len(ids) != len(set(ids))
                    or not set(ids) <= allowed
                ):
                    raise ValueError("evidence_request_requires_programme_etf_results")
                proposal["awaiting_evidence"] = True
                continue
            if proposal["backtest_ids"]:
                raise ValueError("experiment_followup_cannot_request_evidence")
            st.add_task(
                preview,
                proposal["topic"],
                proposal["question"],
                proposal["reason"],
                parent=t["id"],
            )
        report = {
            "text": action["text"],
            "at": time.time(),
            "results": rs,
            "validation": "evidence_review_unverified"
            if review
            else "development_only_unreviewed",
            "followups": copy.deepcopy(action.get("followups", [])),
            "evidence_ids": action.get("evidence_ids", []),
        }
        t["reports"].append(report)
        st.promote_followups(c)
        return {"saved": True, "validation": report["validation"]}
    raise ValueError("action_not_allowed")


@router.post("/{ident}/command")
async def command(
    ident: str, body: Command, auth: AuthContext = Depends(get_auth_context)
):
    if len(json.dumps(body.data)) > (
        450000 if body.op == "add_evidence_review" else 120000
    ):
        raise HTTPException(413, "command_too_large")
    async with edit(ident, auth) as (c, db):
        now = time.time()
        st.recover(c, now)
        if body.op == "add_evidence_review":
            request = EvidenceReview.model_validate(body.data)
            evidence = request.evidence
            reject_quarantined_metric_fields(evidence)
            if evidence.get("boundary") != c["contract"]["end_date"]:
                raise ValueError("evidence_development_boundary_required")
            sources = evidence.get("sources") or []
            if not sources or any(
                not isinstance(s, dict)
                or not s.get("path")
                or not isinstance(s.get("sha256"), str)
                or len(s["sha256"]) != 64
                or any(x not in "0123456789abcdef" for x in s["sha256"])
                for s in sources
            ):
                raise ValueError("evidence_sources_require_sha256")
            digest = st.fingerprint(evidence)
            task_id = st.add_task(
                c,
                request.topic,
                request.question + " 证据版本：" + digest[:12],
                request.reason,
                kind="evidence_review",
            )
            t = c["tasks"][task_id]
            t.setdefault("evidence", dict(evidence, id=digest[:32], sha256=digest))
            t["priority"] = 5
            st.record(
                c, "evidence_review_assigned", task_id=task_id, evidence_sha256=digest
            )
            return {"task_id": task_id, "evidence_id": digest[:32]}
        if body.op in ("expand_stock", "repair_stock_input"):
            if "stock_scope_hold" in c:
                raise ValueError("stock_scope_held_pending_boundary_acceptance")
            if c["desired"] != "stopped":
                raise ValueError("stop_before_expanding_research_scope")
            from backend.services.research_agent.continuous_stock import freeze

            contract = freeze(c["contract"]["end_date"])
            if c.get("stock_contract") and c["stock_contract"] != contract:
                if (
                    body.op != "repair_stock_input"
                    or body.data.get("previous_manifest")
                    != c["stock_contract"]["manifest_sha256"]
                    or not body.data.get("reason")
                ):
                    raise ValueError("stock_contract_drift")
                if any(
                    t["status"] in ("running", "stopping") for t in c["tasks"].values()
                ):
                    raise ValueError("wait_for_stop_confirmation")
                previous = {
                    k: v for k, v in c["tasks"].items() if v["kind"] == "stock_factor"
                }
                c.setdefault("stock_scope_history", []).append(
                    {
                        "contract": c["stock_contract"],
                        "tasks": previous,
                        "reason": body.data["reason"],
                        "at": now,
                        "category": "engineering_input_repair",
                    }
                )
                for key in previous:
                    del c["tasks"][key]
            c["stock_contract"] = contract
            c["title"] = "GLM 持续量化研究：A股因子与资产配置"
            for topic in ("stock_signal", "stock_risk"):
                task_id = st.add_task(
                    c,
                    topic,
                    st.TOPICS[topic][1]
                    + " 先运行冻结基线，再通过公共股票模板检验因子增量。 输入版本："
                    + contract["snapshot_id"],
                    "用户于2026-09-27明确扩展研究范围；复用已有股票数据与因子评估，不局限ETF。",
                    kind="stock_factor",
                )
                c["tasks"][task_id]["priority"] = 10
            st.record(
                c,
                "scope_expanded",
                snapshot_id=contract["snapshot_id"],
                boundary=contract["boundary"],
            )
            return visible(ident, c)
        if body.op in ("start", "stop"):
            st.control(c, body.op)
            return visible(ident, c)
        if body.op == "retry_task":
            t = c["tasks"].get(body.task_id)
            if not t or t["status"] not in ("blocked", "failed", "cancelled"):
                raise ValueError("task_not_retryable")
            t.update(
                status="queued",
                retry_at=0,
                transient_errors=0,
                step="用户重新入队，保留已有成果",
            )
            st.record(c, "manual_retry", task_id=body.task_id)
            return visible(ident, c)
        if body.op == "pulse":
            leader = c.get("controller")
            if leader and leader["id"] != body.worker and leader["until"] > now:
                raise ValueError("another_controller_is_alive")
            c["controller"] = {"id": body.worker, "until": now + 90}
            c["last_heartbeat"] = now
            if "runtime" in body.data:
                c["runtime"] = {
                    k: body.data["runtime"].get(k)
                    for k in ("provider", "model", "thinking")
                }
            if "quota" in body.data:
                st.quota_update(c, body.data["quota"], now)
            for task in c["tasks"].values():
                if task.get("worker") == body.worker and task["status"] == "running":
                    task["lease_until"] = now + 120
            return visible(ident, c)
        leader = c.get("controller") or {}
        if leader.get("id") != body.worker or leader.get("until", 0) <= now:
            raise ValueError("controller_lease_required")
        if body.op == "claim":
            task = st.claim(c, body.worker, now)
            return {"task": task}
        if body.op == "settle":
            c["tasks"][body.task_id]["last_error"] = str(
                body.data.get("reason", body.data["outcome"])
            )[:500]
            outcome = st.settle(
                c,
                body.task_id,
                body.lease,
                body.data["outcome"],
                body.data.get("usage"),
                now,
            )
            return {"outcome": outcome}
        t = st.fence(c, body.task_id, body.lease, now)
        if body.op == "stage":
            t["pending_action"] = body.data["action"]
            return {"saved": True}
        if body.op == "feedback":
            t.pop("pending_action", None)
            t["feedback"] = str(body.data.get("message", ""))[:2000]
            return {"saved": True}
        if body.op == "context":
            rs = await results(t, auth)
            if t["kind"] == "evidence_review":
                return {
                    "task": {
                        k: v
                        for k, v in t.items()
                        if k not in ("lease", "tool_receipts", "rejected_actions")
                    },
                    "results": rs,
                    "quota_state": st.quota_update(c, c["quota"], now),
                    "contract": {
                        "end_date": c["contract"]["end_date"],
                        "validation": "read_only_evidence_review",
                    },
                }
            manifest = json.loads((public.package_root() / "manifest.json").read_text())
            availability = [
                {
                    k: x.get(k)
                    for k in ("code", "class", "role", "data_start", "warmup_start")
                }
                for x in manifest["symbols"]
            ]
            from backend.services.research_agent.continuous_stock import inventory

            return {
                "stock_inventory": inventory(c["stock_contract"])
                if c.get("stock_contract")
                else None,
                "availability": availability,
                "contract": c["contract"],
                "quota_state": st.quota_update(c, c["quota"], now),
                "task": {
                    k: v
                    for k, v in t.items()
                    if k not in ("lease", "tool_receipts", "rejected_actions")
                },
                "results": rs,
                "followup_contract": {
                    "experiment_example": {
                        "kind": "experiment",
                        "topic": "trend",
                        "question": "一个需新实验检验的问题",
                        "reason": "已有结果依据",
                    },
                    "evidence_review_example": {
                        "kind": "evidence_review",
                        "topic": "trend",
                        "question": "复核现有回测的逐日持仓与归因",
                        "reason": "摘要未提供原件",
                        "backtest_ids": [
                            "本 programme 已登记的 ETF backtest_id，可引用父链或其他任务"
                        ],
                    },
                    "rule": "省略 kind 等同 experiment。evidence_review 仅申请本 programme 已登记 ETF 结果，可引用父链或其他任务，最多6个唯一 backtest_ids；保存为 awaiting_evidence，不创建任务、不立即返回原件。由主控校验归属、终态、版本与边界、构建证据包后经 add_evidence_review 派发。",
                },
                "parent_report": c["tasks"]
                .get(t.get("parent"), {})
                .get("reports", [])[-1:],
                "templates": {
                    "fixed": FIXED_ALLOCATION_SOURCE,
                    "dynamic": DYNAMIC_ALLOCATION_SOURCE,
                },
                "signal_runtime_contract": {
                    "builtins": "abs min max sum len float int dict list sorted enumerate zip round all any range sqrt fsum stdev ValueError".split(),
                    "unavailable_builtins": ["str", "isinstance", "Exception"],
                    "history_rule": "history requires lookback > 1; signal_on_month_end=true leaves history and monthly_prices empty on other days. Test availability before indexing; daily re-entry requires daily signal data.",
                    "snapshot_rule": (
                        "First-entry snapshot is empty even when is_month_end is true. "
                        "nav_exact and other account fields are available only after the first ledger day; "
                        "handle is_entry before monthly logic, or use declared initial_cash only for initial sizing. "
                        "snapshot contains account cash/nav/positions/risk, not market quotes. "
                        "Use history/monthly_prices for adjusted prices and respect warmup dates."
                    ),
                    "state_rule": "state must be a small JSON mapping; no unbounded daily history.",
                    "result_artifact_rule": (
                        "The model result summary omits full saved ledger evidence and strategy decisions. "
                        "Missing from this summary means not provided here, not unrecorded by the engine. "
                        "Request an evidence review of existing artifacts for paths, weights and fills; "
                        "do not launch another backtest solely to retrieve them."
                    ),
                },
                "prior_questions": [
                    x["question"] for x in list(c["tasks"].values())[-100:]
                ],
            }
        if body.op == "action":
            action = body.data["action"]
            key = st.fingerprint(action)
            if key in t["tool_receipts"]:
                return t["tool_receipts"][key]
            try:
                result = await act(ident, c, t, action, auth, db)
            except (ValueError, HTTPException) as exc:
                detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                status = exc.status_code if isinstance(exc, HTTPException) else 409
                t.setdefault("rejected_actions", []).append(
                    {"action": action, "reason": detail[:2000], "at": now}
                )
                t["rejected_actions"] = t["rejected_actions"][-20:]
                t["last_error"] = detail[:500]
                st.record(c, "action_rejected", task_id=t["id"], reason=detail[:500])
                return JSONResponse(status_code=status, content={"detail": detail})
            t["tool_receipts"][key] = result
            t.pop("pending_action", None)
            t.pop("feedback", None)
            t["transient_errors"] = 0
            t["last_activity"] = now
            t["step"] = (
                "等待公共回测"
                if action["action"] in ("experiment", "stock_factor")
                else "结论已保存"
            )
            st.record(
                c,
                "action",
                task_id=t["id"],
                action=action["action"],
                strategy_id=result.get("strategy_id"),
                backtest_id=result.get("backtest_id"),
            )
            return result
        if body.op == "usage":
            for k in ("input", "output", "unknown_calls", "calls"):
                t["usage"][k] = t["usage"].get(k, 0) + max(0, int(body.data.get(k, 0)))
            if "step" in body.data:
                t["step"] = str(body.data["step"])[:200]
            t["last_activity"] = now
            return {"saved": True}
        raise ValueError("operation_not_allowed")
