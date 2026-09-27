#!/usr/bin/env python3
"""Inject a model quota denial into the real coordinator + HTTP + PG path.
Uses the archived smoke programme; never changes real vendor quota or live programme.
"""

import json
import time
from pathlib import Path
from controller import Client, Controller
from backend.services.research_agent.glm_quota import failure_kind

p = (
    Path.home()
    / "Library/Application Support/QuantMind/continuous-research/runtime.json"
)
evidence = json.loads((p.parent / "smoke-evidence.json").read_text())
api = Client(p)
api.program = evidence["program_id"]
c = Controller(api)


def q(remaining):
    return {
        "status": "known",
        "remaining_percent": remaining,
        "used_percent": 100 - remaining,
        "observed_at": time.time(),
        "reset_at": time.time() + 10000,
        "weekly": None,
    }


api.call("start")
api.call("pulse", data={"quota": q(92)})
t = api.call("claim")["task"]
assert t
original = api.call("context", t)["task"]["experiments"]
assert original
calls = []


def exhausted(ctx, task):
    calls.append("denied")
    return None, failure_kind("1308 已达到5小时使用上限"), {"unknown_calls": 1}


c.model = exhausted
c.work(t)
s = api.call("pulse", data={"quota": q(92)})
assert s["tasks"][t["id"]]["status"] == "waiting_quota"
assert api.call("claim")["task"] is None
api.call("pulse", data={"quota": q(0)})
time.sleep(65)
api.call("pulse", data={"quota": q(92)})
again = api.call("claim")["task"]
assert again["id"] == t["id"]
assert again["lease"] != t["lease"]


def restored(ctx, task):
    calls.append("resumed")
    return (
        {
            "action": "report",
            "text": (
                "本报告仅为工程验收：对协调程序注入额度耗尽响应后，任务进入等待，额度为零与未恢复期间均不派发。"
                "在重试时间到达并收到新的正余额查询后，程序接续同一任务，保持原公共回测编号，没有新增策略与回测。"
                "这不属于真实策略研究，不解释历史收益，也不能作为投资建议或科学验证。"
            ),
            "followups": [],
        },
        None,
        {"input": 0, "output": 0},
    )


c.model = restored
c.work(again)
s = api.call("pulse", data={"quota": q(92)})
done = s["tasks"][t["id"]]
assert done["status"] == "done", done["status"]
assert done["experiments"] == original
assert calls == ["denied", "resumed"]
api.call("stop")
proof = {
    "model_error_injected": "1308",
    "same_task": t["id"],
    "same_backtests": [x["backtest_id"] for x in original.values()],
    "calls": calls,
    "status": done["status"],
    "at": time.time(),
    "test_only": True,
}
(p.parent / "quota-recovery-evidence.json").write_text(
    json.dumps(proof, ensure_ascii=False, indent=2)
)
print(json.dumps(proof, ensure_ascii=False))
