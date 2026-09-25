#!/usr/bin/env python3
"""R01 P0.4 J2P1 evidence: H2.2-P1 run_status 存取 + 日常页数据源（接口 stub）。

p02r runner 未合入：以接口 stub（模拟 runner 写入）经真实网关验证
POST/GET、心跳过期、三段停止/恢复、待启用、风险/作业暂停区别、迟到写保护；
页面数据源=同一 GET。待 p02r runner 联调（标注）。"""
import hashlib
import json
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8000"; GW = BASE + "/api/v1/research-agent"
RUN_STATE = Path("/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project")
NODE = json.load(open(RUN_STATE / "data/research/settings.json"))["node_id"]
WT = Path("/Users/lizeyu/Documents/ChatGPT/投资/QuantMind.worktrees/r01-p0")
HEAD = subprocess.run(["git","rev-parse","--short=12","HEAD"],cwd=WT,capture_output=True,text=True).stdout.strip()
OUT = Path("/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/h2")

def call(method,url,body=None,token=None,headers=None):
    req=urllib.request.Request(url,method=method)
    req.add_header("Content-Type","application/json"); req.add_header("X-Research-Node",NODE)
    if token: req.add_header("Authorization","Bearer "+token)
    for k,v in (headers or {}).items(): req.add_header(k,v)
    data=json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req,data=data) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

def payload(rid,**over):
    base={"ledger_run_id":rid,"strategy_id":"a-demo","strategy_version":1,"group":"A",
          "run_state":"running",
          "input_date":{"decision_date":"2026-09-25","data_as_of":"2026-09-24",
                        "obtained_at":"2026-09-25T15:40:00Z","manifest_sha256":"a"*64,
                        "package_id":"r01-etf-daily-fcbabbb7f133"},
          "today_decision":{"action":"no_trade","reason":"月末调仓未到期","no_trade_reason":"无调仓信号"},
          "risk_state":{"status":"active","high_water_mark":30100.0},
          "schedule":{"configured":False},
          "last_heartbeat":time.time(),"last_success_at":time.time(),
          "positions":[{"symbol":"511090.SH","qty":100,"available_qty":100,
                        "last_mark":110.685,"market_value":11068.5}],
          "cash":18931.5,"dividend_receivable":0.0,"orders":[],
          "nav":30000.0,"drawdown":0.003,"hwm":30100.0,"anomalies":[],"pending_actions":[]}
    base.update(over); return base

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    _,auth=call("POST",BASE+"/api/v1/auth/login",{"username":"admin","password":"admin123","tenant_id":"default"})
    token=auth["access_token"]
    log={"head":HEAD,"mode":"接口 stub（p02r runner 未合入，待联调）","steps":[]}
    def W(label,body,expect=200):
        st,resp=call("POST",GW+"/r01/run-status",body,token,{"x-tenant-id":"default"})
        log["steps"].append({"label":label,"status":st,"resp":resp})
        assert st==expect,(label,st,resp); return resp
    # ① 正常运行 + 未配置调度 => 待启用
    W("正常心跳写入",payload("r01vr-A-demo-v1-a1"))
    _,body=call("GET",GW+"/r01/run-status",None,token)
    run=[r for r in body["runs"] if r["ledger_run_id"]=="r01vr-A-demo-v1-a1"][0]
    assert run["platform_derived"]["display_state"]=="正常"
    assert run["platform_derived"]["activation"]=="pending_activation"
    log["pending_activation"]=run["platform_derived"]
    # ② 心跳过期 => 陈旧不判成败
    W("远古心跳",payload("r01vr-A-demo-v1-a1",last_heartbeat=1000.0))
    _,body=call("GET",GW+"/r01/run-status",None,token)
    run=body["runs"][0]
    assert run["platform_derived"]["display_state"]=="stale_heartbeat"
    assert run["run_state"]=="running"
    log["stale_heartbeat"]=run["platform_derived"]
    # ③ 三段停止：requested→received→effective（仅执行端确认）
    W("停止 requested",payload("r01vr-A-demo-v1-a1",run_state="paused_job",
                               stop_restore={"job_stop":{"stage":"requested"}}))
    W("停止 received",payload("r01vr-A-demo-v1-a1",run_state="paused_job",
                               stop_restore={"job_stop":{"stage":"received"}}))
    W("停止 effective",payload("r01vr-A-demo-v1-a1",run_state="paused_job",
                               stop_restore={"job_stop":{"stage":"effective"},
                                             "job_restore":{"stage":"requested"}}))
    _,body=call("GET",GW+"/r01/run-status",None,token)
    run=body["runs"][0]
    assert run["stop_restore"]["job_stop"]["stage"]=="effective"
    assert run["stop_restore"]["job_restore"]["stage"]=="requested"
    assert run["platform_derived"]["display_state"]=="作业暂停"
    log["three_stage"]=run["stop_restore"]
    # ④ 风险暂停（另一运行）与作业暂停分别展示
    W("风险暂停",payload("r01vr-B1-demo-v1-a1",run_state="paused_risk",
        risk_state={"status":"paused","pending_confirmations":[{"line":"loss_line"}]}))
    _,body=call("GET",GW+"/r01/run-status",None,token)
    by={r["ledger_run_id"]:r for r in body["runs"]}
    assert by["r01vr-B1-demo-v1-a1"]["platform_derived"]["display_state"]=="风险暂停"
    assert by["r01vr-A-demo-v1-a1"]["platform_derived"]["display_state"]=="作业暂停"
    # ⑤ 已配置调度 => next_run_at 透传（来源标注）
    W("配置调度",payload("r01vr-B1-demo-v1-a1",run_state="no_trade_needed",
        schedule={"configured":True,"next_run_at":"2026-09-26T15:40:00+08:00"}))
    _,body=call("GET",GW+"/r01/run-status",None,token)
    run=[r for r in body["runs"] if r["ledger_run_id"]=="r01vr-B1-demo-v1-a1"][0]
    assert run["platform_derived"]["next_run_at"]=="2026-09-26T15:40:00+08:00"
    assert "quantmind:r01:vr:schedule" in run["platform_derived"]["next_run_at_source"]
    assert run["platform_derived"]["display_state"]=="无须交易"
    # ⑥ 数据受阻 + 迟到写保护
    W("数据受阻",payload("r01vr-A-demo-v1-a1",run_state="data_blocked",
        anomalies=[{"kind":"daily_input_gate","detail":"manifest 校验 fail"}]))
    resp=W("迟到旧日写入被忽略",payload("r01vr-A-demo-v1-a1",
        input_date={"decision_date":"2026-09-24","data_as_of":"2026-09-23"}))
    assert resp["ignored"]=="stale_write"
    _,body=call("GET",GW+"/r01/run-status",None,token)
    run=[r for r in body["runs"] if r["ledger_run_id"]=="r01vr-A-demo-v1-a1"][0]
    assert run["platform_derived"]["display_state"]=="数据受阻" and run["anomalies"]
    # ⑦ 无交易也有效（今日决策证据）已在 ①⑤ 覆盖；⑧ 未配置带 next_run_at 拒绝
    st,resp=call("POST",GW+"/r01/run-status",
                 payload("r01vr-D-demo-v1-a1",schedule={"configured":False,"next_run_at":"x"}),
                 token,{"x-tenant-id":"default"})
    assert st==422
    (OUT/"run-status-stub-evidence.json").write_text(json.dumps(log,ensure_ascii=False,indent=1))
    (OUT/"summary.md").write_text(
        f"# J2P1 证据（HEAD {HEAD}）——接口 stub（p02r runner 未合入，待联调）\n\n"
        f"- POST/GET /r01/run-status 经 engine 网关真链路：正常/无须交易/数据受阻/风险暂停/作业暂停/心跳陈旧/待启用 全状态可分辨\n"
        f"- 三段停止 requested→received→effective 仅执行端确认后显示生效；恢复 requested 并列展示\n"
        f"- next_run_at 仅透传已配置调度（来源标注 quantmind:r01:vr:schedule），未配置=pending_activation，未配置带值 422\n"
        f"- 迟到旧 decision_date 写入被忽略（显式返回）；页面数据源=同一 GET\n"
        f"- 待联调：p02r runner（virtual_run/）合入后以真实心跳/三段回执复跑本序列\n")
    print(json.dumps({"head":HEAD,"steps":len(log["steps"]),"out":str(OUT)},ensure_ascii=False))

if __name__=="__main__": main()
