#!/usr/bin/env python3
"""Bounded real sandbox acceptance; creates an archived engineering programme.
Never starts the unattended research programme or touches a paper account.
"""

import hashlib
import json
import sys
import time
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.services.simulation.replay.strategy_program import FIXED_ALLOCATION_SOURCE

p = (
    Path.home()
    / "Library/Application Support/QuantMind/continuous-research/runtime.json"
)
cfg = json.loads(p.read_text())
s = requests.Session()
s.trust_env = False
s.headers["Authorization"] = "Bearer " + cfg["access_token"]
base = cfg["engine_url"] + "/api/v1"


def request(path, body=None, status=200):
    r = (
        s.get(base + path, timeout=90)
        if body is None
        else s.post(base + path, json=body, timeout=90)
    )
    assert r.status_code == status, (path, r.status_code, r.text[:500])
    return r.json()


proof = {}
proof["a_before"] = hashlib.sha256(
    json.dumps(request("/strategies/61/revisions"), sort_keys=True).encode()
).hexdigest()
v = request(
    "/continuous-research",
    {"key": "continuous-engineering-smoke-" + str(int(time.time())), "concurrency": 1},
)
ident = v["id"]
request(
    "/research-catalog/" + ident + "/category",
    {
        "category": "engineering",
        "reason": "持续研究额度与公共回测链路验收，不属于投资研究成果",
    },
)
worker = "smoke-worker"
task = None


def cmd(op, data=None, expect=200):
    body = {"op": op, "worker": worker, "data": data or {}}
    if task:
        body.update(task_id=task["id"], lease=task["lease"])
    return request("/continuous-research/" + ident + "/command", body, expect)


def q(rem):
    return {
        "status": "known",
        "observed_at": time.time(),
        "remaining_percent": rem,
        "used_percent": 100 - rem,
        "reset_at": time.time() + 10000,
        "weekly": None,
    }


cmd("start")
cmd("pulse", {"quota": q(0)})
assert cmd("claim")["task"] is None
proof["exhausted_no_dispatch"] = True
cmd("pulse", {"quota": {"status": "unknown", "observed_at": time.time()}})
assert cmd("claim")["task"] is None
proof["unknown_no_dispatch"] = True
cmd("pulse", {"quota": q(92)})
task = cmd("claim")["task"]
assert task
proof["restored_dispatch"] = True
act = {
    "action": "experiment",
    "name": "工程验收·公共固定配置五日",
    "hypothesis": "验收幂等恢复；不用于策略选择或收益结论",
    "code": FIXED_ALLOCATION_SOURCE,
    "parameters": {
        "symbols": ["510300.SH", "518880.SH", "511010.SH"],
        "target_weights": {"510300.SH": 0.4, "518880.SH": 0.1, "511010.SH": 0.5},
        "frequency": "monthly",
        "lookback": 1,
    },
    "start_date": "2014-08-01",
    "end_date": "2014-08-08",
}
for label, bad in [
    ("holdout", {**act, "end_date": "2026-03-25"}),
    ("existing_strategy", {**act, "strategy_id": "61"}),
    ("shell", {**act, "code": "import os\ndef on_signal(ctx): return {}"}),
]:
    cmd("action", {"action": bad}, 409)
    proof[label + "_denied"] = True
cmd("stage", {"action": act})
a = cmd("action", {"action": act})
b = cmd("action", {"action": act})
assert a == b
proof["idempotent_public_run"] = {
    "strategy_id": a["strategy_id"],
    "backtest_id": a["backtest_id"],
    "revision_id": a["revision_id"],
}
for _ in range(90):
    cmd("pulse", {"quota": q(92)})
    ctx = cmd("context")
    rs = ctx["results"]
    statuses = [x["status"] for x in rs.values()]
    if statuses and not any(x in ("pending", "running") for x in statuses):
        break
    time.sleep(2)
assert statuses and all(x in ("success", "completed") for x in statuses), statuses
proof["public_result"] = rs
old_lease = task["lease"]
cmd("stop")
cmd("action", {"action": act}, 409)
cmd("settle", {"outcome": "done"})
cmd("start")
cmd("pulse", {"quota": q(92)})
task = cmd("claim")["task"]
assert task["lease"] != old_lease
again = cmd("action", {"action": act})
assert again == a
proof["stop_resume_keeps_backtest"] = True
cmd("stop")
cmd("settle", {"outcome": "cancelled"})
proof["a_after"] = hashlib.sha256(
    json.dumps(request("/strategies/61/revisions"), sort_keys=True).encode()
).hexdigest()
assert proof["a_before"] == proof["a_after"]
proof["program_id"] = ident
proof["at"] = time.time()
path = p.parent / "smoke-evidence.json"
path.write_text(json.dumps(proof, ensure_ascii=False, indent=2))
print(
    json.dumps(
        {k: v for k, v in proof.items() if k != "public_result"}, ensure_ascii=False
    )
)
