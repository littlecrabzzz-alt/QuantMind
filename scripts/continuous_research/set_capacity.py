"""Authenticated local operator adjustment; zero drains without revoking leases.

Run inside the isolated Engine with token/program_id and the adjustment on stdin.
This reuses the existing claim limit and locked store; no scheduler or stop/start.
"""

import asyncio
import json
import re
import sys
import time

from backend.services.research_agent import continuous_state as st


def set_capacity(
    c, *, request_id, expected_concurrency, concurrency, reason, operator
):
    for value in (expected_concurrency, concurrency):
        if type(value) is not int or not 0 <= value <= 6:
            raise ValueError("model_capacity_must_be_integer_0_to_6")
    if not isinstance(request_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{8,100}", request_id
    ):
        raise ValueError("stable_operator_request_id_required")
    if not isinstance(reason, str) or not 20 <= len(reason.strip()) <= 2000:
        raise ValueError("specific_operator_reason_required")
    if (
        c["contract"].get("paper_authorized") is not False
        or c["contract"].get("validation") != "development_only"
        or c.get("runtime")
        != {"provider": "glm", "model": "glm-5.3", "thinking": "max"}
    ):
        raise ValueError("glm_max_development_program_required")
    request_hash = st.fingerprint(
        [expected_concurrency, concurrency, reason.strip(), operator]
    )
    previous = c.get("capacity_changes", {}).get(request_id)
    if previous:
        if previous["request_hash"] != request_hash:
            raise ValueError("operator_request_id_conflict")
        return {**previous, "already_applied": True}
    old = c["contract"].get("concurrency")
    if old != expected_concurrency:
        raise ValueError("model_capacity_changed_since_observation")
    receipt = {
        "request_id": request_id,
        "request_hash": request_hash,
        "old_concurrency": old,
        "concurrency": concurrency,
        "reason": reason.strip(),
        "operator": operator,
        "at": time.time(),
    }
    c["contract"]["concurrency"] = concurrency
    c.setdefault("capacity_changes", {})[request_id] = receipt
    st.record(c, "model_capacity_changed", **receipt)
    return {**receipt, "already_applied": False}


async def apply_request(request):
    from fastapi.security import HTTPAuthorizationCredentials
    from backend.services.trade_shared.deps import get_auth_context
    from backend.services.engine.routers.continuous_research import edit

    request = dict(request)
    auth = await get_auth_context(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=request.pop("token")),
        x_tenant_id=None,
    )
    async with edit(request.pop("program_id"), auth) as (c, _):
        return set_capacity(
            c,
            operator={"user_id": auth.user_id, "tenant_id": auth.tenant_id},
            **request,
        )


async def main():
    receipt = await apply_request(json.load(sys.stdin))
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
