#!/usr/bin/env python3
"""R01 P0.4 I2P1 final combined evidence (H1-AC01/AC02/AC03) at the frozen HEAD.

AC01: loss-line-100 ledger — native equity vs export_view per-day risk
      (status switch + HWM) AND the TS adapter on the same window.
AC02: two-path last_mark/qty/market_value/mark_source equality on >=2 dates,
      including the acceptance-cited values (04-24=113.031, 04-29=110.685).
AC03: produced by scripts/r01_p04_i1_evidence.py into the same directory.
Output: artifacts/p04/h1/fixes-i1/final/.
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
NODE = json.load(open(RUN_STATE / "data/research/settings.json"))["node_id"]
HEAD = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE,
                      capture_output=True, text=True).stdout.strip()
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/h1/fixes-i1/final")

def run_ledger(loss_line):
    pkg = load_etf_input_package(PKG_ROOT, expect_manifest_sha256=
        "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622")
    suffix = "-100" if loss_line else ""
    led = R01Ledger(pkg, R01LedgerConfig(
        group="A", strategy_id="acceptance-i2-final" + suffix, strategy_version=1,
        execution_attempt_id=1, initial_cash=20000.0, commission_rate=0.0003,
        commission_min=0.1, slippage_bps=0.0,
        loss_line_amount=loss_line, drawdown_pct=0.99),
        created_at=datetime(2026, 9, 25, 16, 0, tzinfo=timezone.utc), source_node="mac")
    d1 = date(2024, 4, 22)
    bars = pkg.load_date(d1)
    o = led.submit_order(d1, "511090.SH", "buy", 100)
    led._validate_and_execute(o, d1, bars, DaySummary(trade_date="2024-04-22"))
    led._eod(d1, bars, DaySummary(trade_date="2024-04-22"))
    for d in (date(2024, 4, 23), date(2024, 4, 24), date(2024, 4, 25),
              date(2024, 4, 26), date(2024, 4, 29)):
        led.run_day(d, None)
    return led

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
    log = {"head": HEAD, "sections": {}}

    # --- AC01：损失线 100，native vs view 逐日 + TS 适配层同窗对齐 ---
    led = run_ledger(100.0)
    evidence = led.export_evidence()
    view = led.export_view()
    ac01_rows = []
    for day, snap in zip(view["days"], led.equity, strict=True):
        ac01_rows.append({
            "date": day["date"],
            "native_risk_status": snap["risk_status"],
            "view_risk_status": day["risk"]["status"],
            "native_hwm": snap["high_water_mark"],
            "view_hwm": day["risk"]["high_water_mark"],
            "match": day["risk"]["status"] == snap["risk_status"]
            and abs(day["risk"]["high_water_mark"] - snap["high_water_mark"]) < 1e-9,
        })
    assert all(r["match"] for r in ac01_rows)
    assert len({r["native_risk_status"] for r in ac01_rows}) > 1  # 状态切换存在
    (OUT / "ac01-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=1))
    (OUT / "ac01-view.json").write_text(json.dumps(view, ensure_ascii=False, indent=1))
    log["sections"]["ac01"] = {"view_schema": view["view_schema"],
                               "daily": ac01_rows, "all_match": True,
                               "status_switch_present": True}
    # TS 适配层同窗对齐（含当日风险快照）
    subprocess.run(["npx", "tsc",
                    str(WORKTREE / "electron/src/features/alpha-research/components-v2/ledgerAdapter.ts"),
                    "--outDir", "/tmp/i2-adapt", "--module", "commonjs", "--target", "es2020",
                    "--skipLibCheck"], cwd=WORKTREE, check=True, capture_output=True)
    node_script = r'''
const m = require("/tmp/i2-adapt/ledgerAdapter.js");
const fs = require("fs");
const ev = JSON.parse(fs.readFileSync(process.argv[2]));
const vw = JSON.parse(fs.readFileSync(process.argv[3]));
const adapted = m.evidenceToView(ev);
if (m.identifyExportFormat(vw) !== "view") throw "view misclassified";
if (vw.view_schema !== 2) throw "expect v2";
const rows = [];
for (let i = 0; i < vw.days.length; i++) {
  const a = vw.days[i], b = adapted.days[i];
  for (const k of ["cash", "dividend_receivable", "market_value", "nav", "valuation_reliable"])
    if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) throw "mismatch " + a.date + " " + k;
  if (JSON.stringify([a.risk && a.risk.status, a.risk && a.risk.high_water_mark]) !==
      JSON.stringify([b.risk && b.risk.status, b.risk && b.risk.high_water_mark]))
    throw "risk snapshot mismatch " + a.date;
  for (const k of ["last_mark", "mark_source", "qty", "market_value", "available_qty"])
    for (let p = 0; p < a.positions.length; p++)
      if (JSON.stringify(a.positions[p][k]) !== JSON.stringify(b.positions[p][k]))
        throw "position " + k + " mismatch " + a.date;
  rows.push({date: a.date, ok: true});
}
console.log(JSON.stringify({days: rows.length, status: "identical"}));
'''
    (OUT / "adapter-node-check.js").write_text(node_script)
    r = subprocess.run(["node", str(OUT / "adapter-node-check.js"), "x",
                        str(OUT / "ac01-evidence.json"), str(OUT / "ac01-view.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    log["sections"]["ac01"]["adapter_alignment"] = json.loads(r.stdout)

    # --- AC02：两路径 last_mark ≥2 日期全等（含验收引用值）---
    led2 = run_ledger(None)
    view2 = led2.export_view()
    ev2 = led2.export_evidence()
    (OUT / "ac02-view.json").write_text(json.dumps(view2, ensure_ascii=False, indent=1))
    (OUT / "ac02-evidence.json").write_text(json.dumps(ev2, ensure_ascii=False, indent=1))
    close_by_date = {}
    for day, snap in zip(view2["days"], led2.equity, strict=True):
        for p in day["positions"]:
            close_by_date.setdefault(day["date"], {})[p["symbol"]] = {
                "last_mark": p["last_mark"], "native_close": snap["positions"][p["symbol"]]["close"],
                "mark_source": p["mark_source"], "match": abs(
                    p["last_mark"] - snap["positions"][p["symbol"]]["close"]) < 1e-9}
    cited = {"2024-04-24": 113.031, "2024-04-29": 110.685}
    for d, expected in cited.items():
        got = close_by_date[d]["511090.SH"]["last_mark"]
        assert abs(got - expected) < 1e-9, (d, got, expected)
    assert all(v["match"] for day in close_by_date.values() for v in day.values())
    # TS 两路径（适配层 vs view）last_mark/mark_source/数量/市值 ≥2 日期全等
    r2 = subprocess.run(["node", str(OUT / "adapter-node-check.js"), "x",
                         str(OUT / "ac02-evidence.json"), str(OUT / "ac02-view.json")],
                        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr[-400:]
    log["sections"]["ac02"] = {
        "cited_values_verified": cited,
        "per_date_native_close_vs_view_last_mark": close_by_date,
        "two_path_adapter_vs_view": json.loads(r2.stdout)}

    (OUT / "i2-combined.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    (OUT / "summary.md").write_text(
        f"# I2P1 组合证据（冻结 HEAD {HEAD[:12]}）\n\n"
        f"- AC01：损失线 100 逐日 native vs view 全对齐（状态切换存在、HWM 逐日）；"
        f"TS 适配层同窗逐日风险快照/持仓字段全等\n"
        f"- AC02：两路径 last_mark/mark_source/数量/市值 ≥2 日期全等；验收引用值"
        f"04-24=113.031、04-29=110.685 复核一致\n"
        f"- AC03：见同目录 ac03-four-states.json（两轮复用步骤 ID 四态+重放/重启一致）\n"
        f"- 复验：起 §E sidecar 后 `python3 scripts/r01_p04_i2_evidence.py`（AC03 另跑"
        f" `scripts/r01_p04_i1_evidence.py` 指向本目录）\n")
    print(json.dumps({"head": HEAD[:12],
                      "ac01": {"all_match": True, "switch": True,
                               "adapter": log["sections"]["ac01"]["adapter_alignment"]},
                      "ac02": {"cited": cited,
                               "two_path": log["sections"]["ac02"]["two_path_adapter_vs_view"]}},
                     ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
