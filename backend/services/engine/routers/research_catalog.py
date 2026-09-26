"""Research/archive navigation over existing research_drafts, without copying jobs."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from backend.shared.database_manager_v2 import get_session
from backend.services.trade_shared.deps import AuthContext, get_auth_context

router = APIRouter(tags=["Research catalog"])


@router.get("/research-catalog")
async def catalog(auth: AuthContext = Depends(get_auth_context)):
    async with get_session(read_only=True) as db:
        rows = (await db.execute(text("""SELECT draft_id, node_id,
            state->'input' AS input, state->>'engine' AS engine,
            state->>'status' AS status, state->>'workspace_category' AS category,
            state->'external'->>'workstream' AS workstream,
            state->'external'->>'execution_status' AS execution_status
            FROM research_drafts WHERE user_id=:user AND tenant_id=:tenant
              AND state->>'engine' IN ('external','deepagents')
            ORDER BY updated_at DESC LIMIT 2000"""),
            {"user": auth.user_id, "tenant": auth.tenant_id})).mappings().all()
    return [{"id": r["draft_id"], "node_id": r["node_id"], "input": r["input"],
        "status": r["status"], "executor_kind": r["engine"], "workspace_category": r["category"] or "research",
        "external": {"workstream": r["workstream"], "execution_status": r["execution_status"]}} for r in rows]


class Archive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["research", "engineering"]
    reason: str = Field(min_length=1, max_length=500)


@router.post("/research-catalog/{case_id}/category")
async def categorize(case_id: str, body: Archive, auth: AuthContext = Depends(get_auth_context)):
    import json
    metadata = {"workspace_category": body.category, "archive_note": body.reason,
                "archive_updated_at": datetime.now(timezone.utc).isoformat(), "archive_updated_by": auth.user_id}
    async with get_session() as db:
        row = (await db.execute(text("""UPDATE research_drafts
            SET state=state || CAST(:metadata AS jsonb)
            WHERE draft_id=:id AND tenant_id=:tenant AND user_id=:user
              AND state->>'engine' IN ('external','deepagents') RETURNING draft_id"""),
            {"id": case_id, "user": auth.user_id, "tenant": auth.tenant_id,
             "metadata": json.dumps(metadata)})).first()
    if not row:
        raise HTTPException(404, "owned_research_case_not_found")
    return {"id": case_id, **metadata}
