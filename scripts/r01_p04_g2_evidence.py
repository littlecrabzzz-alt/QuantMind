#!/usr/bin/env python3
"""R01 P0.4 G2P1 evidence: real-replay results viewable through the platform.

Deterministic replay of 5 trade days (2024-04-23..) on the REAL v2 input
package (a0d884…) via the shared R01Ledger.run_day channel, then:
  - evidence + derived nav files registered into an external case workspace
    and reported through the engine gateway (artifact/metrics events,
    fixture=false)
  - byte-identity check of the file API vs originals
  - page data-source equivalence: case detail + overview aggregate show the
    artifacts/curves with 未准入 flags (no formal admission at this HEAD)
  - sidecar restart persistence

Output: <run>/artifacts/p04/fixes-g2/.
"""
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

from backend.services.simulation.replay.etf_input_package import (  # noqa: E402
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import R01Ledger, R01LedgerConfig  # noqa: E402

BASE = "http://127.0.0.1:8000"
GW = BASE + "/api/v1/research-agent"
RUN_STATE = Path("/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project")
PKG_ROOT = Path(
    "/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7"
)
CONTRACT_MD = WORKTREE / "backend/services/research_agent/contracts/data-contract.md"
NODE = json.load(open(RUN_STATE / "data/research/settings.json"))["node_id"]
CONTRACT_NODE = "mac"
PACKAGE = "r01-etf-daily-fcbabbb7f133"
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/fixes-g2")

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

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=WORKTREE,
                          capture_output=True, text=True).stdout.strip()
    manifest_sha = hashlib.sha256((PKG_ROOT / "manifest.json").read_bytes()).hexdigest()
    pkg = load_etf_input_package(PKG_ROOT, expect_manifest_sha256=manifest_sha)
    # 确定性窗口：2024-04-23 起的 5 个包交易日（复验口径 04-23~04-29）
    days, d = [], date(2024, 4, 23)
    for _ in range(5):
        days.append(d)
        d = pkg.next_trade_date(d)
    ledger = R01Ledger(
        pkg,
        R01LedgerConfig(
            group="B1", strategy_id="b1-momentum-v1", strategy_version=1,
            execution_attempt_id=1, initial_cash=30000.0,
            slippage_bps=5.0, commission_rate=0.0003, commission_min=0.0,
        ),
        created_at=datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
        source_node="mac",
    )
    day_records = []
    for i, d in enumerate(days):
        weights = {"510300.SH": 0.4, "511010.SH": 0.3, "518880.SH": 0.2} if i == 0 else None
        summary = ledger.run_day(d, weights)
        snap = summary.snapshot
        # 原值派生净值：现金+应收+持仓收盘市值 独立重算并与账本 nav 对齐
        derived = snap["cash"] + snap["dividend_receivable"] + sum(
            p["qty"] * p["close"] for p in snap["positions"]
        )
        assert abs(derived - snap["nav"]) < 0.01, (d, derived, snap["nav"])
        day_records.append({
            "date": d.isoformat(),
            "cash": snap["cash"],
            "dividend_receivable": snap["dividend_receivable"],
            "market_value": snap["market_value"],
            "nav": snap["nav"],
            "positions": snap["positions"],
            "orders": [
                {"symbol": o["symbol"], "side": o["side"], "qty": o["quantity"],
                 "price": o["price"], "total_fee": o["total_fee"],
                 "status": "filled", "trade_date": o["trade_date"]}
                for o in summary.orders
            ],
            "corporate_actions_applied": summary.corporate_actions_applied,
            "dividends_credited": summary.dividends_credited,
        })
    evidence = {
        "kind": "real-replay-evidence",
        "package": {"package_id": PACKAGE, "package_version": "v2-fcbabbb7",
                    "manifest_sha256": manifest_sha},
        "code_revision": head,
        "window": [days[0].isoformat(), days[-1].isoformat()],
        "initial_cash": 30000.0,
        "days": day_records,
        "nav_derivation": "nav = cash + dividend_receivable + Σ(qty×close)，逐日独立重算对齐（误差<0.01）",
    }
    nav_file = {
        "kind": "real-nav", "note": "真实 v2 输入包确定性回放派生净值（非 fixture）",
        "points": [{"date": r["date"], "nav": r["nav"]} for r in day_records],
    }

    _, auth = call("POST", BASE + "/api/v1/auth/login",
                   {"username": "admin", "password": "admin123", "tenant_id": "default"})
    token = auth["access_token"]
    _, case = call("POST", GW + "/cases", {
        "key": "r01-g2-real-" + str(int(time.time())),
        "question": "G2P1 真实回放结果展示（B1·非 fixture）",
        "executor_kind": "external", "project_key": "r01", "workstream": "B1"}, token)
    case_id = case["id"]
    external_dir = RUN_STATE / "data/research/agent" / case_id / "workspace/external"
    external_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, obj in (("real-replay-evidence.json", evidence), ("real-nav.json", nav_file)):
        blob = json.dumps(obj, ensure_ascii=False, indent=1).encode()
        (external_dir / name).write_bytes(blob)
        files[name] = {"sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob)}

    def envelope(event_id, seq, kind, **extra):
        base = {
            "schema_version": 2, "project_key": "r01", "workstream": "B1",
            "case_id": case_id, "source_task": "R01P0-G2P1",
            "source_run_id": "run-g2-real", "strategy_id": "b1-momentum-v1",
            "contract_version": "2.3",
            "contract_hash": hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest(),
            "source_node": CONTRACT_NODE, "source_revision": head,
            "event_id": event_id, "seq": seq, "kind": kind,
            "data": {"input_package_id": PACKAGE, "data_as_of": "2024-04-29",
                     "manifest_sha256": manifest_sha},
            "timestamps": {"source_at": "2026-09-25T08:30:00Z"},
            "execution_status": "completed",
            "evidence_stage": "development-compare", "fixture": False,
        }
        base.update(extra)
        return base

    log = {"head": head, "case_id": case_id, "files": files, "steps": []}
    seq = 0
    for name in files:
        ev = envelope(f"ev-art-{name}", seq, "artifact",
                      artifacts=[{"name": name, "kind": "real-replay" if "evidence" in name else "real-nav",
                                  "sha256": files[name]["sha256"],
                                  "uri": f"external/{name}"}])
        seq += 1
        st, resp = call("POST", GW + f"/cases/{case_id}/external-reports", ev, token)
        log["steps"].append({"label": f"artifact {name}", "status": st, "body": resp})
        assert st == 201, resp
    met = envelope("ev-met", seq, "metrics", metrics=[
        {"metric": "total_return", "value": None, "null_reason": "not-computed",
         "unit": "ratio", "basis": "30万·真实回放·未研究"}])
    st, resp = call("POST", GW + f"/cases/{case_id}/external-reports", met, token)
    log["steps"].append({"label": "metrics null+reason", "status": st, "body": resp})
    assert st == 201

    # 打开原件核对一致（页面“文件/证据”与曲线卡的数据源同为此 API）
    for name in files:
        st, raw = None, None
        req = urllib.request.Request(GW + f"/cases/{case_id}/file?path=external/{name}")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("X-Research-Node", NODE)
        with urllib.request.urlopen(req) as r:
            st, raw = r.status, r.read()
        identical = raw == (external_dir / name).read_bytes()
        log["steps"].append({"label": f"file API byte-identical: {name}",
                             "status": st, "identical": identical,
                             "sha256": hashlib.sha256(raw).hexdigest()})
        assert st == 200 and identical

    _, detail = call("GET", GW + f"/cases/{case_id}", None, token)
    arts = detail["external"]["artifacts"]
    log["detail_check"] = {
        "artifacts": [{"name": a["name"], "fixture": a["fixture"], "not_ready": a["not_ready"]}
                      for a in arts],
        "metrics_flagged": [m["not_ready"] for m in detail["external"]["metrics"]],
    }
    assert all(a["fixture"] is False for a in arts)
    _, overview = call("GET", GW + "/projects/r01", None, token)
    ov_case = next(c for c in overview["cases"] if c["case_id"] == case_id)
    log["overview_check"] = {
        "admission_reasons": overview["admission_reasons"],
        "real_curve_artifacts": [a["name"] for a in ov_case["artifacts"]
                                 if not a["fixture"]
                                 and re.search(r"nav|curve|equity", a["name"] + a["kind"], re.I)],
        "metrics_not_ready": [m["not_ready"] for m in ov_case["metrics"]],
    }
    assert "real-nav.json" in log["overview_check"]["real_curve_artifacts"]

    # sidecar 重建（restart）后仍可查看
    subprocess.run(["docker", "restart", "quantmind-dev-research-agent-r01"], check=True)
    for _ in range(30):
        time.sleep(1)
        st2, detail2 = call("GET", GW + f"/cases/{case_id}", None, token)
        if st2 == 200:
            break
    assert st2 == 200
    log["restart_check"] = {"artifacts_identical":
                            detail2["external"]["artifacts"] == detail["external"]["artifacts"]}
    assert log["restart_check"]["artifacts_identical"]

    (OUT / "real-replay-evidence.json").write_bytes((external_dir / "real-replay-evidence.json").read_bytes())
    (OUT / "real-nav.json").write_bytes((external_dir / "real-nav.json").read_bytes())
    (OUT / "g2-http-log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    (OUT / "summary.md").write_text(
        f"# G2P1 证据（HEAD {head}）\n\n"
        f"- 真实 v2 包（manifest {manifest_sha[:12]}…）R01Ledger.run_day 确定性回放 "
        f"{days[0]}~{days[-1]} 共 5 个交易日；nav 原值独立派生逐日对齐（误差<0.01）\n"
        f"- real-replay-evidence.json（持仓/现金/订单/公司行动/逐日 nav）与 real-nav.json 经文件 API"
        f"逐字节一致；页面文件/证据、真实曲线卡、回放明细共用同一数据源\n"
        f"- 详情/总览：非 fixture 产物带真实标注；本轮 HEAD 未重验收 ⇒ not_ready 显式"
        f"（{overview['admission_reasons']}），未冒充正式结果\n"
        f"- sidecar 重启后 artifacts 逐字节一致\n"
        f"- 复验命令：起 §E sidecar 后 `python3 scripts/r01_p04_g2_evidence.py`\n")
    print(json.dumps({"out": str(OUT), "head": head, "days": [str(d) for d in days],
                      "nav": [r["nav"] for r in day_records],
                      "orders_total": sum(len(r["orders"]) for r in day_records),
                      "overview_reasons": overview["admission_reasons"]},
                     ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
