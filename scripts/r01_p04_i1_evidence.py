#!/usr/bin/env python3
"""R01 P0.4 I1P1 evidence: H1-AC03 current-step scoping (live gateway run).

Two runs reusing the same step ids; the second run walks
in_progress -> blocked -> in_progress -> done; current/next step must always
belong to the current run; idempotent replay adds nothing; sidecar restart
keeps the view identical. Output: artifacts/p04/h1/fixes-i1/.
"""
import hashlib
import json
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
GW = BASE + "/api/v1/research-agent"
RUN_STATE = Path("/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project")
WORKTREE = Path(__file__).resolve().parents[1]
CONTRACT_MD = WORKTREE / "backend/services/research_agent/contracts/data-contract.md"
NODE = json.load(open(RUN_STATE / "data/research/settings.json"))["node_id"]
HEAD = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=WORKTREE,
                      capture_output=True, text=True).stdout.strip()
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/h1/fixes-i1")

def call(method, url, body=None, token=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Research-Node", NODE)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def envelope(cid, run, event_id, seq, status, **over):
    base = {
        "schema_version": 2, "project_key": "r01", "workstream": "P0",
        "case_id": cid, "source_task": "R01P0-I1P1", "source_run_id": run,
        "strategy_id": "fixture-i1-ac03", "contract_version": "2.3",
        "contract_hash": hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest(),
        "source_node": "mac", "source_revision": HEAD,
        "event_id": event_id, "seq": seq, "kind": "progress",
        "data": {"input_package_id": "r01-etf-daily-fcbabbb7f133",
                 "source_release_id": "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab",
                 "data_as_of": "2026-09-24",
                 "manifest_sha256": "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"},
        "timestamps": {"source_at": "2026-09-25T15:00:00Z"},
        "execution_status": "running", "evidence_stage": "engineering-validation",
        "fixture": True,
        "progress_step": {"step_id": "input", "title": "输入核验", "status": status},
    }
    base.update(over)
    return base

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, auth = call("POST", BASE + "/api/v1/auth/login",
                   {"username": "admin", "password": "admin123", "tenant_id": "default"})
    token = auth["access_token"]
    _, case = call("POST", GW + "/cases", {
        "key": "r01-i1-ac03-" + str(int(time.time())),
        "question": "I1 H1-AC03 当前步骤跨运行归属（工程）",
        "executor_kind": "external", "project_key": "r01", "workstream": "P0"}, token)
    cid = case["id"]
    reports = GW + f"/cases/{cid}/external-reports"
    log = {"head": HEAD, "case_id": cid, "states": []}

    # run-1：input(done) + replay(done) completed
    call("POST", reports, envelope(cid, "run-1", "r1a", 0, "done"), token)
    call("POST", reports, envelope(cid, "run-1", "r1b", 1, "done",
         progress_step={"step_id": "replay", "title": "回放联调", "status": "done"},
         execution_status="completed"), token)
    def snapshot(label):
        _, detail = call("GET", GW + f"/cases/{cid}", None, token)
        ext = detail["external"]
        row = {"label": label, "current_run_id": ext["current_run_id"],
               "current_step": ext["current_step"], "next_step": ext["next_step"],
               "attempts": ext["attempts"], "events_applied": ext["events_applied"]}
        log["states"].append(row)
        return ext
    ext = snapshot("run-1 completed")
    assert ext["current_step"]["step_id"] == "replay" and ext["next_step"] is None

    # run-2 四态复用 input
    for label, eid, seq, status, over in (
        ("态①启动", "r2a", 0, "in_progress", {}),
        ("态②受阻", "r2b", 1, "blocked", {"errors": ["依赖中断"]}),
        ("态③恢复", "r2c", 2, "in_progress", {}),
        ("态④完成", "r2d", 3, "done", {}),
    ):
        st, resp = call("POST", reports, envelope(cid, "run-2", eid, seq, status, **over), token)
        assert st == 201, resp
        ext = snapshot(label)
        assert ext["current_run_id"] == "run-2"
        assert ext["current_step"]["step_id"] == "input"
        assert ext["current_step"]["source_run_id"] == "run-2"
        assert ext["current_step"]["status"] == status
    assert ext["next_step"] is None  # run-2 内全完成
    runs = {r["source_run_id"]: r for r in ext["runs"]}
    assert set(runs["run-2"]["steps"]) == {"input"}
    assert set(runs["run-1"]["steps"]) == {"input", "replay"}
    # 幂等重放 run-1 旧事件
    st, resp = call("POST", reports, envelope(cid, "run-1", "r1b", 1, "done",
                    progress_step={"step_id": "replay", "title": "回放联调", "status": "done"},
                    execution_status="completed"), token)
    assert st == 200 and resp["reused"] is True
    ext_replay = snapshot("重放后")
    assert ext_replay["attempts"] == ext["attempts"] and ext_replay["events_applied"] == ext["events_applied"]
    # sidecar 重启一致
    subprocess.run(["docker", "restart", "quantmind-dev-research-agent-r01"], check=True)
    for _ in range(30):
        time.sleep(1)
        st2, detail2 = call("GET", GW + f"/cases/{cid}", None, token)
        if st2 == 200:
            break
    assert st2 == 200
    assert detail2["external"]["current_step"] == ext_replay["current_step"]
    assert detail2["external"]["runs"] == ext_replay["runs"]
    log["restart_identical"] = True
    (OUT / "ac03-four-states.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    (OUT / "summary.md").write_text(
        f"# I1P1 H1-AC03 证据（HEAD {HEAD}）\n\n"
        f"- 两轮复用相同步骤 ID：run-1 input/replay 均 done 后，run-2 复用 input 走"
        f" in_progress→blocked→in_progress→done 四态；current_step 始终属 run-2（含 source_run_id），"
        f"next_step 语义同 run 作用域；run-1 独立 steps 与审计事件保留\n"
        f"- 幂等重放 run-1 旧事件 200 reused，attempts/events 不变；sidecar 重启后 current_step 与"
        f"逐 run steps 逐字节一致\n"
        f"- 复验：起 §E sidecar 后 `python3 scripts/r01_p04_i1_evidence.py`\n")
    print(json.dumps({"out": str(OUT), "head": HEAD,
                      "states": [(s["label"], s["current_run_id"],
                                  s["current_step"]["status"]) for s in log["states"]]},
                     ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
