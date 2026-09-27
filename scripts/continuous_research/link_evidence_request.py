"""Link a verified evidence packet to its request, using existing auth/row lock.

The operator builds and registers the packet first. This only links identities;
it neither generates evidence nor certifies the model's conclusions.
"""

import asyncio
import json
import sys
import time

from backend.services.research_agent import continuous_state as st


def request_hash(proposal):
    return st.fingerprint(
        {
            k: v
            for k, v in proposal.items()
            if k not in ("task_id", "awaiting_evidence", "evidence_resolution")
        }
    )


def link(c, parent_id, proposal_sha256, review_id):
    parent = c["tasks"].get(parent_id)
    review = c["tasks"].get(review_id)
    if not parent or parent["kind"] != "research" or parent["status"] != "done":
        raise ValueError("completed_etf_parent_required")
    if not review or review["kind"] != "evidence_review":
        raise ValueError("registered_evidence_review_required")
    matches = [
        p
        for r in parent["reports"]
        for p in r.get("followups", [])
        if request_hash(p) == proposal_sha256
    ]
    if len(matches) != 1:
        raise ValueError("exact_evidence_request_required")
    proposal = matches[0]
    if proposal.get("kind") != "evidence_review" or proposal["topic"].startswith(
        "stock_"
    ):
        raise ValueError("etf_evidence_request_required")
    evidence = review.get("evidence", {})
    expected = {
        "parent_id": parent_id,
        "proposal_sha256": proposal_sha256,
        "backtest_ids": sorted(proposal["backtest_ids"]),
    }
    if (
        evidence.get("origin_request") != expected
        or evidence.get("boundary") != c["contract"]["end_date"]
        or evidence.get("id") != evidence.get("sha256", "")[:32]
        or evidence.get("sha256")
        != st.fingerprint(
            {k: v for k, v in evidence.items() if k not in ("id", "sha256")}
        )
    ):
        raise ValueError("registered_packet_request_binding_mismatch")
    if proposal.get("task_id"):
        if proposal["task_id"] != review_id:
            raise ValueError("request_already_linked_to_another_review")
        return {"linked": True, "already_linked": True, "review_id": review_id}
    proposal.update(
        task_id=review_id,
        awaiting_evidence=False,
        evidence_resolution={"at": time.time(), "evidence_id": evidence["id"]},
    )
    st.record(
        c,
        "evidence_request_linked",
        task_id=parent_id,
        proposal_sha256=proposal_sha256,
        review_id=review_id,
        evidence_id=evidence["id"],
    )
    return {"linked": True, "already_linked": False, "review_id": review_id}


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
        receipt = link(c, **request)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
