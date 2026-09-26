"""Owned published strategy versions on the existing H2 virtual-run pipeline."""
import asyncio
from datetime import datetime, timedelta
import json
import os
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from backend.services.trade_shared.deps import AuthContext, get_auth_context
from backend.shared.database_manager_v2 import get_session
from backend.services.engine.routers.r01_strategy import revision_owned, package_root
from backend.services.simulation.models.replay import R01VirtualRunConfig, ReplayLedgerCheckpoint
from backend.services.simulation.virtual_run.states import VirtualRunConfig, RedisRunStateStore, ControlBoard
from backend.services.engine.tasks.r01_virtual_run_scheduler import _redis, save_run_config
from backend.services.simulation.replay.strategy_program import execution_digest

router = APIRouter(tags=["Strategy paper execution"])


class Freeze(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str = Field(pattern=r"^[a-f0-9]{64}$")


async def owned(run_id, auth):
    async with get_session(read_only=True) as db:
        row = await db.get(R01VirtualRunConfig, run_id)
        if not row or row.execution_window.get("owner") != [auth.tenant_id, auth.user_id]:
            raise HTTPException(404, "owned_paper_account_not_found")
        return row


@router.post("/strategies/{strategy_id}/paper-runs")
async def freeze(strategy_id: str, body: Freeze, auth: AuthContext = Depends(get_auth_context)):
    r = await revision_owned(strategy_id, body.revision_id, auth)
    if r["engine_sha256"] != execution_digest():
        raise HTTPException(409, "execution_engine_changed: publish and test a new version")
    async with get_session(read_only=True) as db:
        tested = (await db.execute(text("""SELECT backtest_id FROM qlib_backtest_runs
            WHERE user_id=:user AND tenant_id=:tenant AND status='completed'
              AND config_json->>'strategy_revision'=:revision
            ORDER BY completed_at DESC LIMIT 1"""),
            {"user": auth.user_id, "tenant": auth.tenant_id, "revision": body.revision_id})).scalar()
    if not tested:
        raise HTTPException(409, "先完成此版本的公共回测，再冻结到虚拟账户")
    x = r["execution"]
    cfg = VirtualRunConfig(group=r["group"], strategy_id=f"platform-s{strategy_id}-{body.revision_id[:12]}",
        strategy_version=r["version"], initial_cash=x["initial_cash"],
        target_weights={s: r["parameters"].get("target_weights", {}).get(s, 0.) for s in r["parameters"]["symbols"]},
        **{k: x[k] for k in ("commission_rate", "commission_min", "slippage_bps", "price_mode",
             "loss_line_amount", "drawdown_pct", "stale_mark_limit", "sublot_rule_effective")},
        volume_participation=x.get("volume_participation", 1.),
        program={k: r[k] for k in ("revision_id", "code", "code_sha256", "parameters", "engine_sha256", "data_binding")},
        execution_mode="post_close_next_open_accounting", decision_cutoff="16:15", execution_time="15:45",
        decision_deadline_time="09:25", window_timeout_minutes=1050,
        start_date=(datetime.now(ZoneInfo("Asia/Shanghai")).date()+timedelta(days=1)).isoformat(),
        package_root=str(package_root()), manifest_sha256=r["data_binding"]["manifest_sha256"],
        notes="Forward paper observation; prior frozen decisions, next-session open assumption booked after close; no real trades")
    payload = {"owner": [auth.tenant_id, auth.user_id], "strategy_id": strategy_id,
        "strategy_name": r["name"], "revision_id": body.revision_id,
        "research_case_id": r["research_case_id"], "backtest_id": tested,
        "config": cfg.to_dict(), "observation_status": "experimental_forward"}
    async with get_session() as db:
        await db.execute(insert(R01VirtualRunConfig).values(
            ledger_run_id=cfg.ledger_run_id, enabled=True, strategy_id=cfg.strategy_id,
            strategy_version=cfg.strategy_version, group=cfg.group, initial_cash=cfg.initial_cash,
            risk_config=x, data_source=r["data_binding"], execution_window=payload,
            source_plan_ref=f"strategy:{strategy_id}:revision:{body.revision_id}",
            schedule_key=f"quantmind:r01:vr:schedule:{cfg.ledger_run_id}",
        ).on_conflict_do_nothing(index_elements=["ledger_run_id"]))
    row = await owned(cfg.ledger_run_id, auth)
    # Repeating freeze uses the original start/date/config; never resets a ledger.
    saved = VirtualRunConfig.from_dict(row.execution_window["config"])
    await asyncio.to_thread(save_run_config, saved.ledger_run_id, saved, enabled=row.enabled)
    return {"ledger_run_id": saved.ledger_run_id, "status": "scheduled" if row.enabled else "archived", "start_date": saved.start_date}


async def run_view(row):
    meta = row.execution_window
    store = RedisRunStateStore(os.environ["REDIS_URL"])
    status = await asyncio.to_thread(store.get_status, row.ledger_run_id) or {}
    control = await asyncio.to_thread(ControlBoard(store).get, row.ledger_run_id)
    async with get_session(read_only=True) as db:
        cp = await db.get(ReplayLedgerCheckpoint, row.ledger_run_id)
    state = cp.state if cp else {}
    snaps = state.get("equity") or []
    latest = snaps[-1] if snaps else {}
    heartbeat = await asyncio.to_thread(store.last_heartbeat, row.ledger_run_id)
    day_keys = await asyncio.to_thread(store.list_days, row.ledger_run_id)
    records = [await asyncio.to_thread(store.get_day, row.ledger_run_id, d) for d in day_keys[-20:] if d != "_control"]
    last = next((d for d in reversed(records) if d), {})
    engine_ok = meta["config"]["program"]["engine_sha256"] == execution_digest()
    dispatcher = await asyncio.to_thread(_redis().get, "quantmind:r01:vr:dispatcher_heartbeat")
    publisher = await asyncio.to_thread(_redis().get, "quantmind:r01:vr:publisher_status")
    return {"ledger_run_id": row.ledger_run_id, **{k: meta[k] for k in
        ("strategy_id", "strategy_name", "revision_id", "research_case_id", "backtest_id", "observation_status")},
        "enabled": row.enabled, "strategy_version": row.strategy_version,
        "start_date": meta["config"]["start_date"],
        "initial_cash": row.initial_cash, "status": status, "last_day": last,
        "positions": latest.get("positions"), "cash": latest.get("cash"),
        "nav": latest.get("nav_exact"), "data_date": latest.get("trade_date"),
        "latest_decision": status.get("today_decision") or last.get("today_decision"),
        "risk": state.get("risk_state"), "last_heartbeat": heartbeat,
        "dispatcher_heartbeat": dispatcher.decode() if dispatcher else None,
        "publisher": json.loads(publisher) if publisher else None,
        "control": control.to_dict() if control else None, "engine_matches": engine_ok,
        "execution_mode": meta["config"]["execution_mode"],
        "decision_time": meta["config"]["decision_cutoff"], "accounting_time": meta["config"]["execution_time"],
        "decision_deadline_time": meta["config"].get("decision_deadline_time"),
        "error": status.get("error") or (None if engine_ok else "published_execution_engine_changed"),
        "orders": state.get("orders"), "recent_days": records}


@router.get("/strategy-paper-runs")
async def runs(auth: AuthContext = Depends(get_auth_context)):
    async with get_session(read_only=True) as db:
        rows = (await db.execute(select(R01VirtualRunConfig).where(
            R01VirtualRunConfig.execution_window["owner"] == [auth.tenant_id, auth.user_id]
        ))).scalars().all()
    return [await run_view(row) for row in rows]


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(pattern=r"^(stop|resume|archive)$")


@router.post("/strategy-paper-runs/{run_id}/control")
async def control(run_id: str, body: Control, auth: AuthContext = Depends(get_auth_context)):
    row = await owned(run_id, auth)
    from backend.services.simulation.virtual_run.clock import SystemClock
    store = RedisRunStateStore(os.environ["REDIS_URL"])
    if body.command == "archive":
        ctl = await asyncio.to_thread(ControlBoard(store).get, run_id)
        if not ctl or ctl.command != "stop" or ctl.state != "effective":
            raise HTTPException(409, "先停止并等待执行端确认生效，再归档账户")
        async with get_session() as db:
            saved = await db.get(R01VirtualRunConfig, run_id)
            saved.enabled = False
            saved.execution_window = {**saved.execution_window, "observation_status": "archived"}
        config = VirtualRunConfig.from_dict(row.execution_window["config"])
        await asyncio.to_thread(save_run_config, run_id, config, enabled=False)
        return {"archived": True, "ledger_run_id": run_id}
    if not row.enabled:
        if body.command != "resume":
            raise HTTPException(409, "账户已归档；可恢复原账户，账本不会重置")
        async with get_session() as db:
            saved = await db.get(R01VirtualRunConfig, run_id)
            saved.enabled = True
            saved.execution_window = {**saved.execution_window, "observation_status": "experimental_forward"}
        config = VirtualRunConfig.from_dict(row.execution_window["config"])
        await asyncio.to_thread(save_run_config, run_id, config, enabled=True)
    try:
        result = await asyncio.to_thread(ControlBoard(store).request, run_id, body.command,
            requested_by=auth.user_id, now=SystemClock().now())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    from backend.services.engine.tasks.r01_virtual_run_scheduler import _send
    await asyncio.to_thread(_send, run_id, datetime.now(ZoneInfo("Asia/Shanghai")).date())
    return result.to_dict()
