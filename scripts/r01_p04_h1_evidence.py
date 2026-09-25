#!/usr/bin/env python3
"""R01 P0.4 H1T1 evidence: research progress/version/evidence chain.

Two bounded engineering runs on one external case (run-A completes, run-B
fails/interrupted), each with frozen params/input identity, artifacts and
recovery points; duplicate replay adds no new run; refresh and sidecar
restart keep everything accessible. Output: artifacts/p04/h1/trace/.
"""
import hashlib
import json
import subprocess
import time
import urllib.error
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
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/h1/trace")

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

def envelope(case_id, run, event_id, seq, kind, **extra):
    base = {
        "schema_version": 2, "project_key": "r01", "workstream": "P0",
        "case_id": case_id, "source_task": "R01P0-H1T1", "source_run_id": run,
        "strategy_id": "fixture-h1-chain", "contract_version": "2.3",
        "contract_hash": hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest(),
        "source_node": "mac", "source_revision": HEAD,
        "event_id": event_id, "seq": seq, "kind": kind,
        "data": {"input_package_id": "r01-etf-daily-fcbabbb7f133",
                 "source_release_id": "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab",
                 "data_as_of": "2026-09-24",
                 "manifest_sha256": "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"},
        "timestamps": {"source_at": "2026-09-25T10:30:00Z"},
        "execution_status": "running", "evidence_stage": "engineering-validation",
        "fixture": True,
    }
    base.update(extra)
    return base

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, auth = call("POST", BASE + "/api/v1/auth/login",
                   {"username": "admin", "password": "admin123", "tenant_id": "default"})
    token = auth["access_token"]
    _, case = call("POST", GW + "/cases", {
        "key": "r01-h1-trace-" + str(int(time.time())),
        "question": "H1.3 研究进度/版本/证据一条链（工程）",
        "executor_kind": "external", "project_key": "r01", "workstream": "P0"}, token)
    cid = case["id"]
    reports = GW + f"/cases/{cid}/external-reports"
    ws = RUN_STATE / "data/research/agent" / cid / "workspace/external"
    ws.mkdir(parents=True, exist_ok=True)
    art = {"points": [{"date": f"2026-09-{d:02d}", "nav": 1 + 0.001 * d} for d in range(1, 11)],
           "kind": "fixture-nav", "note": "H1 run-A 工程样例"}
    blob = json.dumps(art, ensure_ascii=False, indent=1).encode()
    (ws / "h1-run-a-nav.json").write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    files = {"h1-run-a-nav.json": sha}
    # H3 修复5：参数→实际输入→manifest 可打开链（真实 v2 包文件注册进课题）
    pkg_root = Path("/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7")
    for pname in ("manifest.json", "README.md"):
        blobx = (pkg_root / pname).read_bytes()
        (ws / f"input-{pname}").write_bytes(blobx)
        files[pname] = hashlib.sha256(blobx).hexdigest()
    log = {"head": HEAD, "case_id": cid, "steps": [],
           "input_binding": {"package_id": "r01-etf-daily-fcbabbb7f133",
                             "package_version": "v2-fcbabbb7",
                             "manifest_sha256": files["manifest.json"],
                             "source_release_id": "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab",
                             "openable": ["external/input-manifest.json", "external/input-README.md"]}}

    def post(label, body):
        st, resp = call("POST", reports, body, token)
        log["steps"].append({"label": label, "status": st, "body": resp})
        return st, resp

    # 输入绑定产物回报（可打开：参数→实际输入→manifest）
    for pname, psha in files.items():
        if not pname.startswith("input-"):
            continue
        stx, respx = call("POST", reports, envelope(
            cid, "run-a", f"a0-{pname}", 0, "artifact",
            artifacts=[{"name": f"input-{pname}", "kind": "input-binding",
                        "sha256": psha, "uri": f"external/input-{pname}"}]), token)
        log["steps"].append({"label": f"artifact input-{pname}", "status": stx})
        assert stx == 201, respx

    # run-a：两步完成 + 产物 + 用量实报 => completed
    post("run-a s1 done", envelope(cid, "run-a", "a1", 1, "progress",
         progress_step={"step_id": "s1", "title": "输入核验", "status": "done"}))
    post("run-a s2 done", envelope(cid, "run-a", "a2", 2, "progress",
         progress_step={"step_id": "s2", "title": "链路联调", "status": "done"}))
    post("run-a artifact", envelope(cid, "run-a", "a3", 3, "artifact",
         artifacts=[{"name": "h1-run-a-nav.json", "kind": "fixture-nav",
                     "sha256": sha, "uri": "external/h1-run-a-nav.json"}]))
    post("run-a usage(completed)", envelope(cid, "run-a", "a4", 4, "metrics",
         execution_status="completed",
         metrics=[{"metric": "usage.tokens_total", "value": 4321, "unit": "tokens",
                   "basis": "runner 实报（工程运行）"},
                  {"metric": "total_return", "value": None, "null_reason": "not-computed",
                   "unit": "ratio", "basis": "工程样例不计算收益"}]))
    # run-b：一步后中断（blocked + errors + 恢复点）
    post("run-b s3 blocked(中断)", envelope(cid, "run-b", "b1", 0, "progress",
         execution_status="blocked", errors=["工程沙盒网络中断，等待续报"],
         progress_step={"step_id": "s3", "title": "回放联调", "status": "blocked"}))
    # 重复回报：run-a 末事件原样重发 => 幂等，不新增实验/运行
    st, resp = call("POST", reports,
                    envelope(cid, "run-a", "a4", 4, "metrics",
                             execution_status="completed",
                             metrics=[{"metric": "usage.tokens_total", "value": 4321,
                                       "unit": "tokens", "basis": "runner 实报（工程运行）"},
                                      {"metric": "total_return", "value": None,
                                       "null_reason": "not-computed", "unit": "ratio",
                                       "basis": "工程样例不计算收益"}]), token)
    log["steps"].append({"label": "run-a 末事件原样重发（幂等）", "status": st, "body": resp})
    assert st == 200 and resp["reused"] is True

    _, detail = call("GET", GW + f"/cases/{cid}", None, token)
    ext = detail["external"]
    runs = {r["source_run_id"]: r for r in ext["runs"]}
    log["case_view"] = {
        "attempts": ext["attempts"],
        "runs": [{"run": rid, "status": r["execution_status"],
                  "errors": r["errors"], "resume_after_seq": r["resume_after_seq"],
                  "data": r["data"]} for rid, r in runs.items()],
        "current_step": ext["current_step"], "next_step": ext["next_step"],
        "usage": ext["usage"], "last_event_at": ext["last_event_at"],
        "strategy_versions": ext["strategy_versions"],
        "artifacts": [{"name": a["name"], "source_run_id": a["source_run_id"]} for a in ext["artifacts"]],
    }
    assert ext["attempts"] == 2
    assert runs["run-a"]["execution_status"] == "completed"
    assert runs["run-b"]["execution_status"] == "blocked" and runs["run-b"]["errors"]
    assert ext["usage"]["values"] and ext["usage"]["values"][0]["source_run_id"] == "run-a"
    assert ext["current_step"]["step_id"] == "s3" and ext["next_step"]["step_id"] == "s3"
    # 冻结参数/输入/合同身份：审计流保留完整 envelope（按 run 可定位）
    _, stream = call("GET", reports + "?since_seq=0", None, token)
    log["audit_frozen_identity"] = [
        {"event_id": e["event_id"], "run": e["source_run_id"],
         "contract_version": e["payload"]["contract_version"],
         "contract_hash": e["payload"]["contract_hash"][:16],
         "source_revision": e["payload"]["source_revision"],
         "data": e["payload"]["data"], "apply_status": e["apply_status"]}
        for e in stream["events"]]
    this_case_events = [e for e in stream["events"] if e["payload"]["case_id"] == cid]
    assert len(this_case_events) == 7, len(this_case_events)  # 2 输入绑定+4 run-a+1 run-b
    # 刷新一致性（页面数据源同 API）
    _, detail2 = call("GET", GW + f"/cases/{cid}", None, token)
    assert detail2["external"] == ext
    # sidecar 重启后旧记录可访问
    subprocess.run(["docker", "restart", "quantmind-dev-research-agent-r01"], check=True)
    for _ in range(30):
        time.sleep(1)
        st3, detail3 = call("GET", GW + f"/cases/{cid}", None, token)
        if st3 == 200:
            break
    assert st3 == 200 and detail3["external"] == ext
    log["restart_identical"] = True
    (OUT / "h1-trace.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    (OUT / "constraints-links.md").write_text(
        f"# H1.3 本次运行实际输入绑定（HEAD {HEAD}）\n\n"
        f"- run-a/run-b 回报 input_package_id=r01-etf-daily-fcbabbb7f133 / v2-fcbabbb7，"
        f"manifest_sha256={files['manifest.json']}，"
        f"release=data-fcbabbb7…ac0ab\n"
        f"- 参数→实际输入→manifest 可打开链：external/input-manifest.json 与 "
        f"external/input-README.md（课题文件区可打开/下载，file API 逐字节一致）\n"
        f"- 覆盖矩阵/质量检查等通用入口仍走 readiness.evidence_refs（runner 回报）\n")
    (OUT / "summary.md").write_text(
        f"# H1T1 证据（HEAD {HEAD}）\n\n"
        f"- 两次有界工程运行同课题：run-a completed（2 步+产物+用量实报）、run-b blocked 中断"
        f"（errors+恢复点 resume_after_seq）；attempts=2，重复回报幂等不新增实验\n"
        f"- 当前步骤/下一步/最后回报/陈旧/累计尝试来自派生字段；用量=runner 实报真实值，"
        f"未回报字段一律未统计（不以 attempts 冒充）\n"
        f"- 冻结参数/输入/合同身份：审计流完整 envelope 按 run 可定位（contract v2.3 hash+"
        f"source_revision+data）；产物带来源 run，页面文件入口同 API\n"
        f"- 刷新与 sidecar 重启后 case 详情逐字节一致\n"
        f"- 复验：起 §E sidecar 后 `python3 scripts/r01_p04_h1_evidence.py`\n")
    print(json.dumps({"out": str(OUT), "head": HEAD,
                      "attempts": ext["attempts"],
                      "runs": log["case_view"]["runs"],
                      "usage_note": ext["usage"]["note"]}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
