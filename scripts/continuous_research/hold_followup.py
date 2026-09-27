"""Operator-only hold of an undispatched proposal using the existing locked store.

Run inside the isolated Engine, with an authenticated request on stdin. No
controller restart or running-task cancellation; original reports are retained.
"""

import asyncio
import copy
import json
import sys
import time

from backend.services.research_agent import continuous_state as st


def hold(c, parent_id, proposal_sha256, review_id, reason):
    if not isinstance(reason, str) or not 20 <= len(reason.strip()) <= 2000:
        raise ValueError("specific_operator_reason_required")
    parent = c["tasks"].get(parent_id)
    review = c["tasks"].get(review_id)
    if not parent or parent["status"] != "done":
        raise ValueError("completed_parent_required")
    if (
        not review
        or review["kind"] != "evidence_review"
        or review["status"] != "done"
        or not review["reports"]
    ):
        raise ValueError("completed_evidence_review_required")
    for report in parent["reports"]:
        for item in report.get("withheld_followups", []):
            if item["proposal_sha256"] == proposal_sha256:
                return {"held": True, "already_held": True, **item}
    matches = [
        (report, proposal)
        for report in parent["reports"]
        for proposal in report.get("followups", [])
        if st.fingerprint({k: v for k, v in proposal.items() if k != "task_id"})
        == proposal_sha256
    ]
    if len(matches) != 1:
        raise ValueError("exact_undispatched_proposal_required")
    report, proposal = matches[0]
    kind = "stock_factor" if proposal["topic"].startswith("stock_") else "research"
    task_id = st.fingerprint([proposal["topic"], proposal["question"].strip(), kind])[
        :24
    ]
    if proposal.get("task_id") or task_id in c["tasks"]:
        raise ValueError("already_dispatched_preserve_active_work")
    item = {
        "proposal_sha256": proposal_sha256,
        "proposal": copy.deepcopy(proposal),
        "review_id": review_id,
        "reason": reason.strip(),
        "at": time.time(),
        "disposition": "operator_held_pending_evidence",
    }
    report.setdefault("withheld_followups", []).append(item)
    report["followups"].remove(proposal)
    st.record(
        c,
        "followup_held",
        task_id=parent_id,
        proposal_sha256=proposal_sha256,
        review_id=review_id,
        reason=reason.strip(),
    )
    return {"held": True, "already_held": False, **item}


async def main():
    from fastapi.security import HTTPAuthorizationCredentials
    from backend.services.trade_shared.deps import get_auth_context
    from backend.services.engine.routers.continuous_research import edit

    request = json.load(sys.stdin)
    auth = await get_auth_context(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=request.pop("token")),
        x_tenant_id=None,
    )
    async with edit(request.pop("program_id"), auth) as (c, _):
        receipt = hold(c, **request)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
