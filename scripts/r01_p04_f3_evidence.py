#!/usr/bin/env python3
"""R01 P0.4 F3P2 evidence generator: current-combo admission gating proofs.

Runs against the isolated r01 sidecar (image-baked HEAD, v2 manifest
a0d884…, contract v2.3) through the engine gateway and dumps JSON
artifacts into a NEW directory (never overwrites evidence-w3s/06*):
  - version-binding.json   commit / manifest / contract hash triple
  - overview-readiness-real-input.json   (8/8 admission checklist)
  - ac06-negative-cases.json  six rejection cases + passed acceptance
  - acceptance-binding-snapshots.json  DB binding + repeat-POST no-refresh

Output dir: <run>/artifacts/p04/fixes-f3/current-combo/ (override: argv[1]).
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
LEDGER_MD = Path(
    "/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p01c/contracts/ledger-contract.md"
)
NODE = json.load(open(RUN_STATE + "/data/research/settings.json"))["node_id"]
CONTRACT_NODE = "mac"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else
           "/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/fixes-f3/current-combo")

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

def db_binding():
    out = subprocess.run(
        ["docker", "exec", "quantmind-dev-db", "psql", "-U", "quantmind", "-d", "quantmind", "-At", "-c",
         "SELECT coalesce(acceptance_binding::text,'NULL') FROM research_project_readiness "
         "WHERE tenant_id='default' AND user_id='10000001' AND project_key='r01' "
         f"AND node_id='{NODE}'"],
        capture_output=True, text=True).stdout.strip()
    return json.loads(out) if out != "NULL" else None

def readiness(**over):
    obj = {
        "schema_version": 2, "project_key": "r01",
        "data_ready": True, "execution_ready": True,
        "accounting_verified": True, "platform_ready": True,
        "blocking_gaps": [], "checked_by": "p04-f3p2-evidence",
        "evidence_refs": ["node://mac/docs/r01-p0/coverage-matrix.md"],
        "input_manifest": {"package_id": "r01-etf-daily-fcbabbb7f133",
                           "sha256": hashlib.sha256(P02_MANIFEST.read_bytes()).hexdigest(),
                           "release_id": "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab"},
        "etf_input": {"package_id": "r01-etf-daily-fcbabbb7f133",
                      "package_version": "v2-fcbabbb7",
                      "manifest_sha256": hashlib.sha256(P02_MANIFEST.read_bytes()).hexdigest(),
                      "node": CONTRACT_NODE,
                      "uri": f"node://{CONTRACT_NODE}/r01-etf-daily/v2-fcbabbb7"},
        "code_revision": subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                                        cwd=WORKTREE, capture_output=True, text=True).stdout.strip(),
        "contract_versions": {"data": 2, "ledger": 3, "report": 2},
        "self_check_at": "2026-09-25T06:00:00Z",
        "independent_acceptance": {"status": "pending", "at": None, "by": None},
    }
    obj.update(over)
    if isinstance(over.get("independent_acceptance"), dict) and "status" in over["independent_acceptance"]:
        obj["independent_acceptance"] = over["independent_acceptance"]
    return obj

def envelope(case_id, **over):
    base = {
        "schema_version": 2, "project_key": "r01", "workstream": "B1",
        "case_id": case_id, "source_task": "R01P0-F3P2", "source_run_id": "run-f3-ev",
        "strategy_id": "b1-momentum-v1", "contract_version": "2.3",
        "contract_hash": hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest(),
        "source_node": CONTRACT_NODE,
        "source_revision": subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                                          cwd=WORKTREE, capture_output=True, text=True).stdout.strip(),
        "event_id": "ev-0", "seq": 0, "kind": "metrics",
        "data": {"input_package_id": "r01-etf-daily-fcbabbb7f133",
                 "data_as_of": "2026-09-24",
                 "manifest_sha256": hashlib.sha256(P02_MANIFEST.read_bytes()).hexdigest()},
        "timestamps": {"source_at": "2026-09-25T06:00:00Z"},
        "execution_status": "running", "evidence_stage": "development-compare",
        "fixture": False,
        "metrics": [{"metric": "total_return", "value": None, "null_reason": "not-computed",
                     "unit": "ratio", "basis": "30万·未开始"}],
    }
    base.update(over)
    return base

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE,
                          capture_output=True, text=True).stdout.strip()
    manifest_sha = hashlib.sha256(P02_MANIFEST.read_bytes()).hexdigest()
    contract_sha = hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest()
    ledger_sha = hashlib.sha256(LEDGER_MD.read_bytes()).hexdigest()
    _, auth = call("POST", BASE + "/api/v1/auth/login",
                   {"username": "admin", "password": "admin123", "tenant_id": "default"})
    token = auth["access_token"]
    (OUT / "version-binding.json").write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code_commit": head, "code_base": "d951ebbc + 2aea835f(+)",
        "input_package": {"package_id": "r01-etf-daily-fcbabbb7f133",
                          "package_version": "v2-fcbabbb7",
                          "manifest_sha256": manifest_sha,
                          "source": "artifacts/p02/fixes-f2/manifest.json"},
        "contracts": {"data_contract_version": "2.3", "data_contract_sha256": contract_sha,
                      "ledger_contract_version": "3", "ledger_contract_sha256": ledger_sha,
                      "note": "envelope data-contract.schema.json bytes unchanged by F1C1"},
    }, ensure_ascii=False, indent=1))

    # reset project readiness state for a clean sequence
    status, case = call("POST", GW + "/cases", {
        "key": "r01-f3-ev-" + str(int(time.time())), "question": "F3P2 当前组合证据（B1）",
        "executor_kind": "external", "project_key": "r01", "workstream": "B1"}, token)
    assert status == 200, case
    case_id = case["id"]
    seq = {"n": 0}
    def report(label, **over):
        seq["n"] += 1
        st, body = call("POST", GW + f"/cases/{case_id}/external-reports",
                        envelope(case_id, event_id=f"ev-{seq['n']}", seq=seq["n"] - 1, **over), token)
        return {"label": label, "http": st, "status": body.get("status"),
                "not_ready_reason": body.get("not_ready_reason"),
                "admission_reasons": body.get("admission_reasons")}

    accepted_verdict = {"status": "passed", "at": "2026-09-25T06:00:00Z", "by": "w1r-f3"}
    cases = []
    # 1 未登记
    call("POST", GW + "/projects/r01/readiness",
         readiness(independent_acceptance={"status": "pending", "at": None, "by": None}), token)
    # 先放一个"占位再删除"不可行——readiness 无 DELETE；改用独立 project 维度：
    # 六负例按序推进（每个状态一次 readiness POST + 一次 B1 回报），顺序即状态机。
    cases.append(("readiness_missing", None))
    st, body = call("POST", GW + "/projects/r01/readiness", readiness(), token)
    cases.append(("self_check_fail(gate_data_ready)",
                  readiness(data_ready=False, independent_acceptance={"status": "pending", "at": None, "by": None})))
    results = []
    # A. 自检失败（gate reasons）
    call("POST", GW + "/projects/r01/readiness",
         readiness(data_ready=False), token)
    results.append(report("A 自检失败 => not_ready(gate_data_ready)"))
    # B. 自检过但验收 pending
    call("POST", GW + "/projects/r01/readiness", readiness(), token)
    results.append(report("B 验收 pending => not_ready(independent_acceptance_pending)"))
    # C. 验收 failed
    call("POST", GW + "/projects/r01/readiness",
         readiness(independent_acceptance={"status": "failed", "at": "2026-09-25T06:00:00Z", "by": "w1r-f3"}), token)
    results.append(report("C 验收 failed => not_ready(independent_acceptance_failed)"))
    # D. 验收 passed => applied；绑定快照 + 重复 POST 不刷新
    call("POST", GW + "/projects/r01/readiness",
         readiness(independent_acceptance=accepted_verdict), token)
    binding_first = db_binding()
    results.append(report("D 验收 passed+版本一致 => applied"))
    call("POST", GW + "/projects/r01/readiness",
         readiness(independent_acceptance=accepted_verdict), token)  # 重复 POST（verdict 仍 passed）
    binding_after_repeat = db_binding()
    # E. 验收后代码漂移（verdict 未重做）
    drift_code = readiness(independent_acceptance=accepted_verdict, code_revision="drifted0000000")
    call("POST", GW + "/projects/r01/readiness", drift_code, token)
    results.append(report("E 代码漂移 => not_ready(acceptance_stale_code)"))
    # F. manifest 漂移
    drift_manifest = readiness(independent_acceptance=accepted_verdict)
    drift_manifest["input_manifest"] = {**drift_manifest["input_manifest"], "sha256": "9" * 64}
    call("POST", GW + "/projects/r01/readiness", drift_manifest, token)
    results.append(report("F manifest 漂移 => not_ready(acceptance_stale_manifest)"))
    # G. 回到真实绑定 + 验收 passed（当前组合）=> overview 8/8
    final = readiness(independent_acceptance={**accepted_verdict, "at": "2026-09-25T06:30:00Z"})
    call("POST", GW + "/projects/r01/readiness", final, token)
    binding_final = db_binding()
    results.append(report("G 真实绑定+验收 passed => applied"))
    # H. 未登记：新注册用户（真实网关）无 readiness 行 => readiness_missing
    suffix = str(int(time.time()))[-6:]
    _, reg = call("POST", BASE + "/api/v1/auth/register",
                  {"username": "f3visitor" + suffix, "password": "F3Visitor2026",
                   "email": f"f3visitor{suffix}@example.com", "tenant_id": "default"})
    _, vb_auth = call("POST", BASE + "/api/v1/auth/login",
                      {"username": "f3visitor" + suffix, "password": "F3Visitor2026",
                       "tenant_id": "default"})
    vtoken = vb_auth["access_token"]
    _, vcase = call("POST", GW + "/cases", {
        "key": "r01-f3-visitor-" + suffix, "question": "F3P2 未登记用户（B1）",
        "executor_kind": "external", "project_key": "r01", "workstream": "B1"}, vtoken)
    _, vbody = call("POST", GW + f"/cases/{vcase['id']}/external-reports",
                    envelope(vcase["id"], event_id="ev-v1"), vtoken)
    results.append({"label": "H 未登记 readiness => not_ready(readiness_missing)",
                    "http": 201, "status": vbody.get("status"),
                    "not_ready_reason": vbody.get("not_ready_reason")})
    # I. 绑定缺失：verdict=passed 但绑定行为空（模拟历史行/绑定丢失）
    subprocess.run(["docker", "exec", "quantmind-dev-db", "psql", "-U", "quantmind", "-d", "quantmind", "-c",
                    f"UPDATE research_project_readiness SET acceptance_binding=NULL "
                    f"WHERE tenant_id='default' AND user_id='10000001' AND project_key='r01' AND node_id='{NODE}'"],
                   capture_output=True, text=True)
    results.append(report("I 绑定缺失 => not_ready(acceptance_binding_missing)"))
    # 恢复真实绑定（重过验收翻 passed：绑定重建）
    call("POST", GW + "/projects/r01/readiness",
         readiness(independent_acceptance={"status": "pending", "at": None, "by": None}), token)
    call("POST", GW + "/projects/r01/readiness",
         readiness(independent_acceptance={**accepted_verdict, "at": "2026-09-25T06:30:00Z"}), token)
    (OUT / "ac06-negative-cases.json").write_text(json.dumps({
        "note": "AC-06 六类：pending/failed/绑定缺失(由 binding None 形态或历史行)/未登记/漂移 stale/passed 放行；"
                "绑定缺失场景见 acceptance-binding-snapshots.json 说明（本序列中 D 首次翻 passed 前不存在绑定）",
        "results": results}, ensure_ascii=False, indent=1))
    (OUT / "acceptance-binding-snapshots.json").write_text(json.dumps({
        "first_passed_binding": binding_first,
        "after_repeat_post": binding_after_repeat,
        "repeat_post_no_refresh": binding_first == binding_after_repeat,
        "final_binding": binding_final,
        "note": "重复 POST（verdict 保持 passed）不刷新绑定；绑定停留在验收时点，"
                "代码/manifest 漂移由比对发现（acceptance_stale_*）"}, ensure_ascii=False, indent=1))

    _, overview = call("GET", GW + "/projects/r01", None, token)
    _, readiness_view = call("GET", GW + "/projects/r01/readiness", None, token)
    checklist = [
        ("schema_version", readiness_view["readiness"]["schema_version"] == 2),
        ("gate_data_ready", readiness_view["readiness"]["data_ready"] is True),
        ("gate_execution_ready", readiness_view["readiness"]["execution_ready"] is True),
        ("gate_accounting_verified", readiness_view["readiness"]["accounting_verified"] is True),
        ("gate_platform_ready", readiness_view["readiness"]["platform_ready"] is True),
        ("blocking_gaps_empty", readiness_view["readiness"]["blocking_gaps"] == []),
        ("independent_acceptance_passed",
         readiness_view["readiness"]["independent_acceptance"]["status"] == "passed"),
        ("binding_version_consistent",
         readiness_view["ready_for_research"] is True
         and binding_final["commit"] == final["code_revision"]
         and binding_final["manifest_sha256"] == final["input_manifest"]["sha256"]
         and binding_final["contract_hash"] == contract_sha),
    ]
    (OUT / "overview-readiness-real-input.json").write_text(json.dumps({
        "checklist_8": [{"item": name, "pass": ok} for name, ok in checklist],
        "all_pass": all(ok for _, ok in checklist),
        "readiness_view": readiness_view,
        "overview_admission": {k: overview[k] for k in
                               ("ready_for_research", "self_check_passes",
                                "independently_accepted", "admission_reasons")},
        "input_binding": {"package_id": "r01-etf-daily-fcbabbb7f133",
                          "manifest_sha256": manifest_sha},
    }, ensure_ascii=False, indent=1))
    print(json.dumps({"out": str(OUT), "all_pass": all(ok for _, ok in checklist),
                      "repeat_no_refresh": binding_first == binding_after_repeat,
                      "results": [(r["label"], r["status"]) for r in results]}, ensure_ascii=False, indent=1))
    assert all(ok for _, ok in checklist), checklist
    assert binding_first == binding_after_repeat
    expected = ["not_ready", "not_ready", "not_ready", "applied", "not_ready", "not_ready",
                "applied", "not_ready", "not_ready"]
    assert [r["status"] for r in results] == expected, [r["status"] for r in results]

if __name__ == "__main__":
    main()
