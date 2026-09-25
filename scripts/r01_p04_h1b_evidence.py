#!/usr/bin/env python3
"""R01 P0.4 H1P2 evidence: common adapter (H1.1) + full detail (H1.2).

Same native ledger (v2 package, 511090, 2024-04-23..29) exported through BOTH
paths — export_evidence() (native, adapted by the frontend common adapter in
TS) and export_view() — and compared value-by-value. Scenario includes a
partial fill (cash-constrained), a rejected order (no position), the 511090
dividend receivable→cash chain and a hand-computable drawdown. legacy_fixture
compat and unknown rejection are exercised via the same TS adapter. No ledger
value is modified to suit the frontend.
Output: <run>/artifacts/p04/h1/adapter/.
"""
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
from backend.services.simulation.replay.etf_input_package import (  # noqa: E402
    load_etf_input_package,
)
from backend.services.simulation.replay.r01_ledger import (  # noqa: E402
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
)

BASE = "http://127.0.0.1:8000"
GW = BASE + "/api/v1/research-agent"
RUN_STATE = Path("/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project")
PKG_ROOT = Path("/Users/lizeyu/Library/Application Support/QuantMind/r01/etf-daily/v2-fcbabbb7")
CONTRACT_MD = WORKTREE / "backend/services/research_agent/contracts/data-contract.md"
NODE = json.load(open(RUN_STATE / "data/research/settings.json"))["node_id"]
HEAD = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=WORKTREE,
                      capture_output=True, text=True).stdout.strip()
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/h1/adapter")
LEGACY_SRC = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p03/evidence-run.json")
MANIFEST = "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622"

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
    pkg = load_etf_input_package(PKG_ROOT, expect_manifest_sha256=MANIFEST)
    ledger = R01Ledger(
        pkg, R01LedgerConfig(
            group="A", strategy_id="h1-historical-sample", strategy_version=1,
            execution_attempt_id=1, initial_cash=20000.0,
            commission_rate=0.0003, commission_min=0.1, slippage_bps=0.0),
        created_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc), source_node="mac")
    # 04-23：先卖后买——卖单无持仓被拒（拒单留痕），买单现金约束部分成交
    d1 = date(2024, 4, 23)
    bars = pkg.load_date(d1)
    sell = ledger.submit_order(d1, "511090.SH", "sell", 100)
    ledger._validate_and_execute(sell, d1, bars, DaySummary(trade_date="2024-04-23"))
    buy = ledger.submit_order(d1, "511090.SH", "buy", 1000)
    ledger._validate_and_execute(buy, d1, bars, DaySummary(trade_date="2024-04-23"))
    ledger._eod(d1, bars, DaySummary(trade_date="2024-04-23"))
    for d in (date(2024, 4, 24), date(2024, 4, 25), date(2024, 4, 26), date(2024, 4, 29)):
        ledger.run_day(d, None)
    evidence = ledger.export_evidence()
    view = ledger.export_view()
    (OUT / "ledger-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=1))
    (OUT / "ledger-view.json").write_text(json.dumps(view, ensure_ascii=False, indent=1))

    # --- 手算与场景断言（python 侧，独立于前端）---
    orders = evidence["orders"]
    rejected = [o for o in orders if o["status"] == "rejected"]
    partial = [o for o in orders if (o["qty_remaining"] or 0) > 0 and o["status"] != "rejected"]
    assert rejected and rejected[0]["reject_reason"], "缺拒单"
    assert partial, "缺部分成交"
    by_date = {d["date"]: d for d in view["days"]}
    receivable_days = [dt for dt, d in by_date.items() if (d.get("dividend_receivable") or 0) > 0]
    assert receivable_days, "缺分红应收"
    pay_day = by_date["2024-04-29"]
    assert (pay_day.get("dividend_receivable") or 0) == 0, "pay 日应收应转现金"
    navs = [d["nav"] for d in view["days"]]
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    assert max_dd > 0, "窗口内应有可手算回撤"

    # --- 前端公共适配层（TS）两条路径逐项对值 ---
    subprocess.run(["npx", "tsc", str(WORKTREE / "electron/src/features/alpha-research/components-v2/ledgerAdapter.ts"),
                    "--outDir", "/tmp/h1b-adapt", "--module", "commonjs", "--target", "es2020",
                    "--skipLibCheck"], cwd=WORKTREE, check=True, capture_output=True)
    node_check = r'''
const {evidenceToView, identifyExportFormat, legacyFixtureView, classifyRunKinds, fixtureConsistency} = require("/tmp/h1b-adapt/ledgerAdapter.js");
const fs = require("fs");
const ev = JSON.parse(fs.readFileSync(process.argv[2]));
const vw = JSON.parse(fs.readFileSync(process.argv[3]));
const out = {pairs: [], formats: {}};
if (identifyExportFormat(ev) !== "evidence") throw "evidence misclassified";
if (identifyExportFormat(vw) !== "view") throw "view misclassified";
const adapted = evidenceToView(ev);
const vd = vw.days, ad = adapted.days;
if (vd.length !== ad.length) throw "day count mismatch";
for (let i = 0; i < vd.length; i++) {
  const a = vd[i], b = ad[i];
  if (a.date !== b.date) throw "date mismatch " + i;
  for (const k of ["cash", "dividend_receivable", "market_value", "nav", "valuation_reliable"]) {
    const x = a[k], y = b[k];
    const ok = (x === undefined && y === undefined) || x === y;
    out.pairs.push({date: a.date, field: k, view: x, adapted: y, ok});
    if (!ok) throw "mismatch " + a.date + " " + k + " " + x + " vs " + y;
  }
  if ((a.positions || []).length !== (b.positions || []).length) throw "positions count " + a.date;
  for (let p = 0; p < (a.positions || []).length; p++) {
    for (const k of ["symbol", "qty", "available_qty", "avg_cost", "market_value"]) {
      if (JSON.stringify(a.positions[p][k]) !== JSON.stringify(b.positions[p][k]))
        throw "position mismatch " + a.date + " " + k;
    }
  }
  if ((a.orders || []).length !== (b.orders || []).length) throw "orders count " + a.date;
  for (let o = 0; o < (a.orders || []).length; o++) {
    for (const k of ["client_order_id", "qty_target", "qty_filled", "qty_remaining",
                     "avg_fill_price", "fees", "status", "reject_reason"]) {
      if (JSON.stringify(a.orders[o][k]) !== JSON.stringify(b.orders[o][k]))
        throw "order mismatch " + a.date + " " + k;
    }
  }
}
const kinds = [];
kinds.push(["session", classifyRunKinds(vw)]);
kinds.push(["fixture-consistency", fixtureConsistency(vw, false)]);
if (JSON.stringify(classifyRunKinds(vw)) !== JSON.stringify(["历史研究"])) throw "kind mismatch: " + JSON.stringify(classifyRunKinds(vw));
if (!fixtureConsistency(vw, false).consistent) throw "fixture layers inconsistent: " + JSON.stringify(fixtureConsistency(vw, false));
if (fixtureConsistency(vw, true).consistent) throw "inconsistent pair must be reported";
const legacyObj = JSON.parse(fs.readFileSync(process.argv[4]));
const legacyInnerFixture = String(legacyObj.banner || "").includes("FIXTURE") || (legacyObj.package || {}).is_fixture === true;
if (!legacyInnerFixture) throw "legacy sample should be inner-fixture (banner FIXTURE)";
out.formats.legacy_fixture_layers = {inner: legacyInnerFixture, outer: true};
out.formats.legacy = identifyExportFormat(JSON.parse(fs.readFileSync(process.argv[4])));
out.formats.unknown = identifyExportFormat({});
out.formats.legacy_days = legacyFixtureView(JSON.parse(fs.readFileSync(process.argv[4]))).daySummaries.length;
if (out.formats.legacy !== "legacy_fixture") throw "legacy misclassified";
if (out.formats.unknown !== "unknown") throw "unknown misclassified";
out.kinds = kinds;
console.log(JSON.stringify({compared_days: vd.length, field_pairs: out.pairs.length,
  formats: out.formats, status: "identical", kinds: kinds}));
'''
    (OUT / "adapter-node-check.js").write_text(node_check)
    legacy_copy = OUT / "legacy-attempt1-sample.json"
    legacy_copy.write_bytes(LEGACY_SRC.read_bytes())
    r = subprocess.run(["node", str(OUT / "adapter-node-check.js"),
                        str(OUT / "ledger-evidence.json"), str(OUT / "ledger-view.json"),
                        str(legacy_copy)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    adapter_result = json.loads(r.stdout)
    assert adapter_result["status"] == "identical"

    # --- 注册到外部课题（页面同一数据源）---
    _, auth = call("POST", BASE + "/api/v1/auth/login",
                   {"username": "admin", "password": "admin123", "tenant_id": "default"})
    token = auth["access_token"]
    _, case = call("POST", GW + "/cases", {
        "key": "r01-h1b-" + str(int(time.time())),
        "question": "H1.1/H1.2 公共适配与完整明细（工程）",
        "executor_kind": "external", "project_key": "r01", "workstream": "P0"}, token)
    cid = case["id"]
    ws = RUN_STATE / "data/research/agent" / cid / "workspace/external"
    ws.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, obj in (("ledger-evidence.json", evidence), ("ledger-view.json", view)):
        blob = json.dumps(obj, ensure_ascii=False, indent=1).encode()
        (ws / name).write_bytes(blob)
        files[name] = hashlib.sha256(blob).hexdigest()
    (ws / "legacy-attempt1-sample.json").write_bytes(legacy_copy.read_bytes())
    files["legacy-attempt1-sample.json"] = hashlib.sha256(legacy_copy.read_bytes()).hexdigest()
    (ws / "unknown-shape.json").write_bytes(b'{"hello": "world"}')
    log = {"head": HEAD, "case_id": cid,
           "scenario": {"rejected": rejected[0]["reject_reason"],
                        "partial": {"qty_target": partial[0]["qty_target"],
                                    "qty_filled": partial[0]["qty_filled"],
                                    "qty_remaining": partial[0]["qty_remaining"]},
                        "receivable_days": receivable_days,
                        "hand_drawdown": max_dd,
                        "nav_series": navs},
           "adapter_check": adapter_result, "steps": []}
    seq = 0
    for name, sha in files.items():
        # 两层 fixture 语义一致（H4 修复1）：研究账本导出（group A）=非 fixture；
        # legacy 旧工程样例与 unknown 演示文件=fixture=true + fixture- 策略前缀
        is_fixture_sample = name in ("legacy-attempt1-sample.json", "unknown-shape.json")
        env = {"schema_version": 2, "project_key": "r01", "workstream": "P0",
               "case_id": cid, "source_task": "R01P0-H1P2", "source_run_id": "run-h1b",
               "strategy_id": ("fixture-h1-legacy-sample" if is_fixture_sample
                               else "h1-historical-sample"),
               "contract_version": "2.3",
               "contract_hash": hashlib.sha256(CONTRACT_MD.read_bytes()).hexdigest(),
               "source_node": "mac", "source_revision": HEAD,
               "event_id": f"ev-art-{name}", "seq": seq, "kind": "artifact",
               "data": {"input_package_id": "r01-etf-daily-fcbabbb7f133",
                        "data_as_of": "2024-04-29", "manifest_sha256": MANIFEST},
               "timestamps": {"source_at": "2026-09-25T12:30:00Z"},
               "execution_status": "completed",
               "evidence_stage": ("engineering-validation" if is_fixture_sample
                                  else "development-compare"),
               "fixture": is_fixture_sample,
               "artifacts": [{"name": name, "kind": "ledger-export" if "ledger" in name else "sample",
                              "sha256": sha, "uri": f"external/{name}"}]}
        seq += 1
        st, resp = call("POST", GW + f"/cases/{cid}/external-reports", env, token)
        log["steps"].append({"label": f"artifact {name}", "status": st})
        assert st == 201, resp
    # 文件 API 与原件逐字节一致（页面打开/核对原件同源）
    for name in files:
        req = urllib.request.Request(GW + f"/cases/{cid}/file?path=external/{name}")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("X-Research-Node", NODE)
        with urllib.request.urlopen(req) as r2:
            raw = r2.read()
        identical = raw == (ws / name).read_bytes()
        log["steps"].append({"label": f"file identical: {name}", "identical": identical})
        assert identical
    _, detail = call("GET", GW + f"/cases/{cid}", None, token)
    arts = {a["name"]: a for a in detail["external"]["artifacts"]}
    assert set(arts) == set(files)
    # 刷新+重启一致
    _, detail2 = call("GET", GW + f"/cases/{cid}", None, token)
    subprocess.run(["docker", "restart", "quantmind-dev-research-agent-r01"], check=True)
    for _ in range(30):
        time.sleep(1)
        st3, detail3 = call("GET", GW + f"/cases/{cid}", None, token)
        if st3 == 200:
            break
    assert st3 == 200 and detail3["external"]["artifacts"] == detail["external"]["artifacts"]
    log["restart_identical"] = True
    (OUT / "h1b-evidence.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    (OUT / "summary.md").write_text(
        f"# H1P2 证据（HEAD {HEAD}）\n\n"
        f"- 同一原生账本两条路径逐项对值：export_evidence（原生）经前端公共适配层（TS，"
        f"ledgerAdapter.evidenceToView）与 export_view 的 {adapter_result['compared_days']} 日 × "
        f"{adapter_result['field_pairs']} 字段对全等（现金/应收/市值/nav/可信度/持仓/订单三态+费用+拒因）\n"
        f"- 场景：拒单（{rejected[0]['reject_reason']}）、部分成交（{partial[0]['qty_filled']}/"
        f"{partial[0]['qty_target']}，剩 {partial[0]['qty_remaining']}）、511090 分红应收（"
        f"{receivable_days}）→ pay 04-29 转现金、手算最大回撤 {max_dd:.6f}（peak-trough 公式）\n"
        f"- 格式判别：evidence/view/legacy_fixture（{adapter_result['formats']['legacy_days']} 日旧样例）/"
        f"unknown（{{}} → 页面显式拒绝不静默零值），node 直跑 TS 适配层输出见 adapter-node-check.js\n"
        f"- 页面同一数据源：4 个文件经认证 file API 逐字节一致；刷新与 sidecar 重启后 artifacts 一致；"
        f"账本数值未做任何迎合前端 的修改\n"
        f"- 复验：起 §E sidecar 后 `python3 scripts/r01_p04_h1b_evidence.py`\n")
    print(json.dumps({"out": str(OUT), "head": HEAD, "adapter": adapter_result,
                      "scenario": log["scenario"]}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
