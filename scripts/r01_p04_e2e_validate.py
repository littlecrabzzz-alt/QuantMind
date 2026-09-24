#!/usr/bin/env python3
"""R01 P0.4 full-chain validation: engine gateway (8000) -> sidecar -> Postgres.

Covers the report-api §9 acceptance path plus persistence-across-restart.
Run from the worktree root against the local dev sandbox.
"""
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8000"
GW = BASE + "/api/v1/research-agent"
NODE = "mac"
RUN_STATE = "/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project"
CONTRACT_MD = Path(__file__).parent.parent / "backend/services/research_agent/contracts/data-contract.md"
CONTRACT_HASH = hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest()
results = []


def call(method, url, body=None, token=None, expect=None, label=""):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Research-Node", NODE)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            payload = json.loads(resp.read() or b"{}")
            status = resp.status
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read() or b"{}")
        status = e.code
    ok = True
    if expect is not None:
        ok = status == expect
    results.append((label or url, status, expect, ok))
    print(f"[{'OK ' if ok else 'FAIL'}] {status} (expect {expect}) {label or url} :: {json.dumps(payload, ensure_ascii=False)[:220]}")
    return status, payload


def envelope(**over):
    base = {
        "schema_version": 2, "project_key": "r01", "workstream": "P0",
        "case_id": CASE_ID[0], "source_task": "R01P0-W2P", "source_run_id": "run-e2e-1",
        "strategy_id": "fixture-risk-line-demo", "contract_version": "2",
        "contract_hash": CONTRACT_HASH, "source_node": NODE, "source_revision": "w2p-e2e",
        "event_id": "ev-0", "seq": 0, "kind": "progress",
        "data": {"input_package_id": "none", "data_as_of": "2026-09-24"},
        "timestamps": {"source_at": "2026-09-25T12:00:00Z"},
        "execution_status": "running", "evidence_stage": "proposal",
        "fixture": True,
        "progress_step": {"step_id": "s1", "title": "external-reports 路由上线", "status": "in_progress"},
    }
    base.update(over)
    return base


CASE_ID = [None]

def main():
    # 0) login through the api gateway
    status, auth = call("POST", BASE + "/api/v1/auth/login",
                        {"username": "admin", "password": "admin123", "tenant_id": "default"}, expect=200, label="login admin")
    token = auth.get("access_token") or (auth.get("data") or {}).get("access_token")
    assert token, f"no token: {auth}"

    # 1) create external case: no model job (TG-001)
    status, case = call("POST", GW + "/cases", {
        "key": "r01-p0-e2e-" + str(int(time.time())),
        "question": "R01 P0 平台通路工程验收（fixture）",
        "subject": "external-reports route", "executor_kind": "external",
        "project_key": "r01", "workstream": "P0",
    }, token, expect=200, label="create external case")
    CASE_ID[0] = case["id"]
    assert case["executor_kind"] == "external"
    assert case["status"] == "registered" and not case.get("messages")
    print("    -> no model job: status=%s messages=%s approval=%s" % (case["status"], case.get("messages"), case.get("approval")))

    # 1b) builtin mode regression: create must still queue model discussion
    status, builtin = call("POST", GW + "/cases", {
        "key": "builtin-regress-" + str(int(time.time())),
        "question": "内置模式回归确认：创建后应排队模型讨论", "model": "glm-5.3-flash",
    }, token, expect=200, label="builtin create (regression)")
    assert builtin["status"] == "queued" and builtin.get("messages"), builtin["status"]

    # 2) external agent places fixture artifact in the node-controlled workspace
    workspace = Path(RUN_STATE) / "data/research/agent" / CASE_ID[0] / "workspace/external"
    workspace.mkdir(parents=True, exist_ok=True)
    points = [{"date": f"2026-09-{d:02d}", "nav": 1.0 + 0.01 * d} for d in range(1, 21)]
    curve = {"kind": "fixture-equity", "note": "工程样例，非真实研究", "points": points}
    curve_bytes = json.dumps(curve, ensure_ascii=False, indent=1).encode()
    curve_file = workspace / "fixture-equity.json"
    curve_file.write_bytes(curve_bytes)
    curve_sha = hashlib.sha256(curve_bytes).hexdigest()

    reports = GW + f"/cases/{CASE_ID[0]}/external-reports"
    def submit(payload, expect, label):
        return call("POST", reports, payload, token, expect=expect, label=label)

    # 3) acceptance path: real dev progress -> gap -> data-check -> artifact+metrics
    submit(envelope(), 201, "progress event applied")
    submit(envelope(event_id="ev-1", seq=1, kind="progress",
                    progress_step={"step_id": "s2", "title": "幂等与乱序校验", "status": "done"}),
           201, "progress step2 done")
    submit(envelope(event_id="ev-2", seq=2, kind="gap-report",
                    execution_status="blocked",
                    gaps=[{"gap_id": "DG-003", "desc": "510500 2015-04-13/14 两日缺行待补采"}]),
           201, "gap report (blocked visible)")
    submit(envelope(event_id="ev-3", seq=3, kind="data-check-report",
                    evidence_stage="data-check",
                    checks=[{"item": "coverage-matrix", "result": "unknown",
                             "evidence_ref": "node://mac/docs/r01-p0/coverage-matrix.md"}]),
           201, "data-check with unknown item (not passed)")
    submit(envelope(event_id="ev-4", seq=4, kind="artifact",
                    evidence_stage="engineering-validation",
                    artifacts=[{"name": "fixture-equity.json", "kind": "fixture-curve",
                                "sha256": curve_sha, "uri": "external/fixture-equity.json"}]),
           201, "fixture artifact registered")
    submit(envelope(event_id="ev-5", seq=5, kind="metrics",
                    execution_status="completed",
                    metrics=[
                        {"metric": "total_return", "value": None, "null_reason": "not-computed",
                         "unit": "ratio", "basis": "工程验收样例，不计算收益"},
                        {"metric": "events_ingested", "value": 6, "unit": "count",
                         "basis": "本课题回报事件数"},
                    ]),
           201, "metrics: null keeps reason, no zero-fabrication")

    # 4) idempotency / ordering / validation semantics
    submit(envelope(), 200, "same key+content => 200 replay")
    submit(envelope(execution_status="completed"), 409, "same key diff content => 409")
    submit(envelope(event_id="ev-late", seq=1), 201, "late seq => stale_event kept")
    s, body = submit(envelope(event_id="ev-node", source_node="cloud"), 409, "wrong node => 409")
    assert body.get("code") == "node_mismatch"
    submit(envelope(event_id="ev-ws", workstream="A"), 422, "workstream mismatch => 422")
    submit(envelope(event_id="ev-hash", contract_hash="0" * 64), 422, "contract hash mismatch => 422")
    submit(envelope(event_id="ev-art", kind="artifact",
                    artifacts=[{"name": "x", "kind": "x", "sha256": "1" * 64,
                                "uri": "external/fixture-equity.json"}]), 422, "artifact hash mismatch => 422 (kept)")
    submit(envelope(event_id="ev-stale", execution_status="stale"), 422, "external stale report => 422")

    # D/N without news_coverage
    status, dcase = call("POST", GW + "/cases", {
        "key": "r01-d-e2e-" + str(int(time.time())),
        "question": "D 组新闻覆盖校验", "executor_kind": "external",
        "project_key": "r01", "workstream": "D",
    }, token, expect=200, label="create D case")
    d_id = dcase["id"]
    dn = dict(envelope(), case_id=d_id, workstream="D", event_id="ev-d1", fixture=False,
              strategy_id="d-news-v1", kind="news-coverage")
    dn.pop("progress_step")
    dn["news_coverage"] = {}  # missing required fields
    call("POST", GW + f"/cases/{d_id}/external-reports", dn, token,
         expect=422, label="D missing news_coverage fields => 422")

    # 5) readiness gating
    readiness_fail = {
        "schema_version": 2, "project_key": "r01",
        "data_ready": False, "execution_ready": True, "accounting_verified": False,
        "platform_ready": True, "blocking_gaps": ["DG-003", "TG-007"], "checked_by": "p02-e2e",
        "evidence_refs": ["node://mac/docs/r01-p0/coverage-matrix.md"],
        "input_manifest": {"package_id": "r01-etf-daily", "sha256": "3" * 64,
                           "release_id": "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab"},
        "etf_input": {"package_id": "r01-etf-daily", "package_version": "v1",
                      "manifest_sha256": "4" * 64, "node": "mac",
                      "uri": "node://mac/r01-etf-daily/v1"},
        "code_revision": "w2p-e2e", "contract_versions": {"data": 2, "ledger": 2, "report": 2},
        "self_check_at": "2026-09-25T12:00:00Z",
        "independent_acceptance": {"status": "pending", "at": None, "by": None},
    }
    call("POST", GW + "/projects/r01/readiness", readiness_fail, token,
         expect=200, label="readiness saved (failing gates)")
    status, b1 = call("POST", GW + "/cases", {
        "key": "r01-b1-e2e-" + str(int(time.time())),
        "question": "B1 对照组回报（准入前）", "executor_kind": "external",
        "project_key": "r01", "workstream": "B1",
    }, token, expect=200, label="create B1 case")
    b1_id = b1["id"]
    m = dict(envelope(), case_id=b1_id, workstream="B1", event_id="ev-b1-1",
             fixture=False, strategy_id="b1-momentum-v1", execution_status="running",
             kind="metrics")
    m.pop("progress_step")
    m["metrics"] = [{"metric": "total_return", "value": None, "null_reason": "not-computed",
                     "unit": "ratio", "basis": "30万·未开始"}]
    status, body = call("POST", GW + f"/cases/{b1_id}/external-reports", m, token,
                        expect=201, label="B1 metrics before readiness => not_ready")
    assert body.get("status") == "not_ready", body
    readiness_pass = dict(readiness_fail, data_ready=True, accounting_verified=True,
                          blocking_gaps=[])
    call("POST", GW + "/projects/r01/readiness", readiness_pass, token,
         expect=200, label="readiness saved (all gates)")
    m2 = dict(m, event_id="ev-b1-2", seq=1)
    status, body = call("POST", GW + f"/cases/{b1_id}/external-reports", m2, token,
                        expect=201, label="B1 metrics after readiness => applied")
    assert body.get("status") == "applied", body

    # 6) risk confirm flow
    r = dict(envelope(), case_id=CASE_ID[0], event_id="ev-risk", seq=6,
             kind="risk-confirm-request", execution_status="blocked")
    r.pop("progress_step")
    r["risk_confirm"] = {"ledger_run_id": "lr-e2e", "risk_line": "loss_line",
                         "risk_event_id": "re-1", "action": "request-confirm"}
    submit(r, 201, "risk-confirm-request stored")
    call("POST", reports + "/ev-risk/confirm-resume", {}, token,
         expect=200, label="user confirm-resume")
    call("POST", reports + "/ev-risk/confirm-resume", {}, token,
         expect=200, label="confirm-resume idempotent")

    # 7) stop request semantics
    status, body = call("POST", GW + f"/cases/{CASE_ID[0]}/stop", None, token,
                        expect=200, label="external stop => stop_requested (not faked)")
    assert body.get("status") == "stop_requested"

    # 8) project overview: refresh consistency (server-side persistence)
    _, ov1 = call("GET", GW + "/projects/r01", None, token, expect=200, label="overview #1")
    _, ov2 = call("GET", GW + "/projects/r01", None, token, expect=200, label="overview #2 (refresh)")
    assert ov1 == ov2, "overview must be identical across reads"
    gaps = {g["gap_id"]: g for g in ov1["gaps"]}
    assert "DG-003" in gaps  # reported gap retained; blocking flag follows current readiness
    groups = ov1["groups"]
    assert groups["B1"]["status"] == "reported" and groups["A"]["status"] == "pending-research"
    assert groups["D"]["status"] == "pending-research" and groups["N"]["status"] == "pending-research"
    b1_metrics = groups["B1"]["metrics"][-1]["metrics"]
    assert b1_metrics[0]["value"] is None and b1_metrics[0]["null_reason"] == "not-computed"
    fixture_artifacts = [a for c in ov1["cases"] for a in c["artifacts"] if a["fixture"]]
    assert any("fixture-equity" in a["name"] for a in fixture_artifacts)
    assert ov1["ready_for_research"] is True and ov1["independently_accepted"] is False

    # 9) durable audit stream
    status, stream = call("GET", reports + "?since_seq=0", None, token,
                          expect=200, label="audit stream (table-backed)")
    kinds = [e["kind"] for e in stream["events"]]
    assert "validation_error" in [e["apply_status"] for e in stream["events"]]
    assert stream["count"] >= 9
    mid = stream["events"][5]["platform_seq"]
    _, tail = call("GET", reports + f"?since_seq={mid}", None, token,
                   expect=200, label="audit stream since_seq")
    assert tail["count"] == stream["count"] - 6, (tail["count"], stream["count"])

    # 10) case detail shows external summary + derived status
    status, detail = call("GET", GW + f"/cases/{CASE_ID[0]}", None, token,
                          expect=200, label="case detail (external summary)")
    ext = detail["external"]
    assert ext["attempts"] >= 1 and ext["gaps"] and ext["risk_pending"] == {}
    assert ext["execution_status"] in ("completed", "blocked")
    print("    -> external summary: attempts=%s events=%s stale=%s data_as_of=%s"
          % (ext["attempts"], ext["events_applied"], ext["stale"], ext["data"]["data_as_of"]))

    # 10b) cross-user access must not leak existence (归属校验).
    # 注：沙盒 /auth/register 因既有 user_profiles.llm_extra_headers 列漂移返回 500
    # （与本任务无关，见 artifacts 说明），故经内部身份头直接探测 sidecar 归属校验。
    import subprocess
    def sidecar(headers, path, body=None):
        cmd = ["docker", "exec", "quantmind-dev-research-agent-r01", "python", "-c",
               "import urllib.request,sys,json;"
               "req=urllib.request.Request('http://127.0.0.1:8100'+sys.argv[1],method='POST' if sys.argv[3]!='GET' else 'GET');"
               "req.add_header('Content-Type','application/json');[req.add_header(*h.split(':',1)) for h in sys.argv[2].split('|')];"
               "d=sys.argv[4].encode() if sys.argv[4] else None\n"
               "try:\n"
               " r=urllib.request.urlopen(req,data=d);print(r.status)\n"
               "except urllib.error.HTTPError as e:print(e.status)"]
        out = subprocess.run(cmd + [path, headers, "POST" if body is not None else "GET",
                                    json.dumps(body or {})], capture_output=True, text=True)
        return int(out.stdout.strip().split()[-1])
    other = "x-internal-call: quantmind-local-dev-internal-only|x-user-id: 99999999|x-tenant-id: default|x-research-node: mac"
    status = sidecar(other, f"/cases/{CASE_ID[0]}")
    results.append(("other user reading case => 404 (existence not leaked)", status, 404, status == 404))
    print(f"[{'OK ' if status == 404 else 'FAIL'}] {status} (expect 404) other user reading case (sidecar ownership)")
    status = sidecar(other, f"/cases/{CASE_ID[0]}/external-reports", envelope(event_id="ev-xuser"))
    results.append(("other user submitting report => 404", status, 404, status == 404))
    print(f"[{'OK ' if status == 404 else 'FAIL'}] {status} (expect 404) other user submitting report")

    # 10c) fixture curve file is fetchable through the authenticated file endpoint
    status, resp = call("GET", GW + f"/cases/{CASE_ID[0]}/file?path=external/fixture-equity.json",
                        None, token, expect=200, label="fixture curve file via file endpoint")
    print("    -> curve file served from node-controlled workspace (frontend CurveCard consumes it)")

    # 11) restart sidecar, persistence must survive (refresh retention)
    import subprocess
    subprocess.run(["docker", "restart", "quantmind-dev-research-agent-r01"], check=True)
    for _ in range(30):
        time.sleep(1)
        status, ov3 = call("GET", GW + "/projects/r01", None, token,
                           label="probe after sidecar restart (503 expected while booting)")
        if status == 200:
            results.append(("overview after sidecar restart", 200, 200, True))
            print("[OK ] 200 (expect 200) overview after sidecar restart :: identical to pre-restart read")
            break
    assert ov3 == ov1, "overview identical after restart"
    status, stream2 = call("GET", reports + "?since_seq=0", None, token,
                           expect=200, label="audit stream after restart")
    assert stream2 == stream, "audit stream identical after restart"

    failed = [r for r in results if not r[3]]
    print("\n==== SUMMARY: %d checks, %d failed ====" % (len(results), len(failed)))
    for f in failed:
        print("FAIL:", f)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
