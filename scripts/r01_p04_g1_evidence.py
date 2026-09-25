#!/usr/bin/env python3
"""R01 P0.4 G1P1 evidence: envelope-identity binding at the real ingress.

Replays the F-AC06 re-verification repros (single-field identity changes)
against the isolated sidecar through the engine gateway and captures real
HTTP requests/responses plus aggregate queries into
<run>/artifacts/p04/fixes-g1/. No aggregation may show them as formal.
"""
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
GW = BASE + "/api/v1/research-agent"
RUN_STATE = "/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project"
WORKTREE = Path(__file__).resolve().parents[1]
CONTRACT_MD = WORKTREE / "backend/services/research_agent/contracts/data-contract.md"
P02_MANIFEST = Path(
    "/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p02/fixes-f2/manifest.json"
)
NODE = json.load(open(RUN_STATE + "/data/research/settings.json"))["node_id"]
CONTRACT_NODE = "mac"
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/fixes-g1")
PACKAGE = "r01-etf-daily-fcbabbb7f133"
MANIFEST = hashlib.sha256(P02_MANIFEST.read_bytes()).hexdigest()
COMMIT = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=WORKTREE,
                        capture_output=True, text=True).stdout.strip()

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

def envelope(case_id, event_id, seq, **over):
    base = {
        "schema_version": 2, "project_key": "r01", "workstream": "B1",
        "case_id": case_id, "source_task": "R01P0-G1P1", "source_run_id": "run-g1-ev",
        "strategy_id": "b1-momentum-v1", "contract_version": "2.3",
        "contract_hash": hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest(),
        "source_node": CONTRACT_NODE, "source_revision": COMMIT,
        "event_id": event_id, "seq": seq, "kind": "metrics",
        "data": {"input_package_id": PACKAGE, "data_as_of": "2026-09-24",
                 "manifest_sha256": MANIFEST},
        "timestamps": {"source_at": "2026-09-25T07:30:00Z"},
        "execution_status": "running", "evidence_stage": "development-compare",
        "fixture": False,
        "metrics": [{"metric": "total_return", "value": None, "null_reason": "not-computed",
                     "unit": "ratio", "basis": "30万·未开始"}],
    }
    base.update(over)
    return base

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, auth = call("POST", BASE + "/api/v1/auth/login",
                   {"username": "admin", "password": "admin123", "tenant_id": "default"})
    token = auth["access_token"]
    readiness = {
        "schema_version": 2, "project_key": "r01",
        "data_ready": True, "execution_ready": True, "accounting_verified": True,
        "platform_ready": True, "blocking_gaps": [], "checked_by": "p04-g1p1",
        "evidence_refs": ["node://mac/docs/r01-p0/coverage-matrix.md"],
        "input_manifest": {"package_id": PACKAGE, "sha256": MANIFEST,
                           "release_id": "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab"},
        "etf_input": {"package_id": PACKAGE, "package_version": "v2-fcbabbb7",
                      "manifest_sha256": MANIFEST, "node": CONTRACT_NODE,
                      "uri": f"node://{CONTRACT_NODE}/r01-etf-daily/v2-fcbabbb7"},
        "code_revision": COMMIT, "contract_versions": {"data": 2, "ledger": 3, "report": 2},
        "self_check_at": "2026-09-25T07:30:00Z",
        "independent_acceptance": {"status": "passed", "at": "2026-09-25T07:30:00Z", "by": "w1r-g1"},
    }
    log = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "head_commit": COMMIT, "accepted_identity": {
               "code_revision": COMMIT, "input_package": PACKAGE, "manifest_sha256": MANIFEST},
           "steps": []}
    def record(label, method, url, body, status, resp):
        log["steps"].append({"label": label, "request": {"method": method, "url": url, "body": body},
                             "response": {"status": status, "body": resp}})

    # 前轮绑定属旧验收（如 F3P3 的 77b87c2e）；先翻 pending 清绑定，再 passed 重快照
    pending = {**readiness, "independent_acceptance": {"status": "pending", "at": None, "by": None}}
    call("POST", GW + "/projects/r01/readiness", pending, token)
    st, resp = call("POST", GW + "/projects/r01/readiness", readiness, token)
    record("readiness accepted (binding snapshot at this HEAD)", "POST", "/projects/r01/readiness", readiness, st, resp)
    assert resp["ready_for_research"] is True, resp
    st, case = call("POST", GW + "/cases", {
        "key": "r01-g1-ev-" + str(int(time.time())), "question": "G1P1 身份绑定反例（B1）",
        "executor_kind": "external", "project_key": "r01", "workstream": "B1"}, token)
    case_id = case["id"]
    reports = GW + f"/cases/{case_id}/external-reports"

    seq = 0
    def submit(label, eid, over):
        nonlocal seq
        body = envelope(case_id, eid, seq)
        seq += 1
        body.update(over)
        st, resp = call("POST", reports, body, token)
        record(label, "POST", f"/cases/{case_id}/external-reports", body, st, resp)
        return st, resp

    st, resp = submit("正例：身份一致 => applied", "ev-ok", {})
    assert resp["status"] == "applied", resp
    ok_request = log["steps"][-1]["request"]["body"]
    st, resp = submit("反例①：source_revision 改 40*b", "ev-code", {"source_revision": "b" * 40})
    assert resp["status"] == "not_ready" and "identity_mismatch_code" in resp["not_ready_reason"]
    st, resp = submit("反例②：manifest_sha256 改 64*c", "ev-man",
                      {"data": {"input_package_id": PACKAGE, "data_as_of": "2026-09-24",
                                "manifest_sha256": "c" * 64}})
    assert resp["status"] == "not_ready" and "identity_mismatch_manifest" in resp["not_ready_reason"]
    st, resp = submit("反例③：input_package_id 改 wrong-input-package", "ev-pkg",
                      {"data": {"input_package_id": "wrong-input-package",
                                "data_as_of": "2026-09-24", "manifest_sha256": MANIFEST}})
    assert resp["status"] == "not_ready" and "identity_mismatch_package" in resp["not_ready_reason"]
    st, resp = call("POST", reports, ok_request, token)  # 原样重放（同键同内容）
    record("幂等重放正例（同键同内容原样重发）", "POST",
           f"/cases/{case_id}/external-reports", ok_request, st, resp)
    assert st == 200 and resp["reused"] is True, resp

    st, detail = call("GET", GW + f"/cases/{case_id}", None, token)
    record("课题详情：反例带未准入标记+原因，正例正式", "GET", f"/cases/{case_id}", None, st, detail)
    metrics = detail["external"]["metrics"]
    flagged = [m for m in metrics if m["not_ready"]]
    assert len(flagged) == 3 and all("identity_mismatch" in (m.get("not_ready_reason") or "")
                                     for m in flagged)
    assert sum(1 for m in metrics if not m["not_ready"]) == 1

    st, overview = call("GET", GW + "/projects/r01", None, token)
    record("项目总览聚合", "GET", "/projects/r01", None, st,
           {k: overview[k] for k in ("ready_for_research", "admission_reasons", "groups")})
    case_summary = next(c for c in overview["cases"] if c["case_id"] == case_id)
    case_metrics = case_summary["metrics"]
    assert len(case_metrics) == 4 and sum(1 for m in case_metrics if m["not_ready"]) == 3

    # 重启恢复：sidecar 重启后标记与原因保持
    subprocess.run(["docker", "restart", "quantmind-dev-research-agent-r01"], check=True)
    for _ in range(30):
        time.sleep(1)
        st, detail2 = call("GET", GW + f"/cases/{case_id}", None, token)
        if st == 200:
            break
    assert st == 200
    record("sidecar 重启后课题详情", "GET", f"/cases/{case_id}", None, st, detail2)
    assert detail2["external"]["metrics"] == metrics, "重启后镜像一致"

    (OUT / "repro-http-log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    (OUT / "summary.md").write_text(
        f"# G1P1 证据（HEAD {COMMIT}）\n\n"
        f"- 正例（身份一致）applied；三反例 not_ready 且原因显式（identity_mismatch_code/manifest/package，双方值）\n"
        f"- 课题详情与项目总览聚合：反例仅以未准入证据保留（not_ready 标记+原因），未进入正式指标\n"
        f"- 幂等重放 200 reused；sidecar 重启后标记/原因/镜像逐字节一致\n"
        f"- 复验命令：起 §E sidecar 后 `python3 scripts/r01_p04_g1_evidence.py`\n")
    print(json.dumps({"out": str(OUT), "head": COMMIT,
                      "metrics": [{"not_ready": m["not_ready"],
                                   "reason": (m.get("not_ready_reason") or "")[:52]}
                                  for m in metrics]}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
