"""Advance one durable research stage. No task requires a connected browser."""
from __future__ import annotations

import copy
import csv
import json
import time
import subprocess
from uuid import uuid4

from . import runtime
from .store import Store, digest

from agent_research_tool import PARAMS, INT_PARAMS, candidate_config, candidate_gates, half_returns
from research_expression import validate as validate_expression


def event(state, message):
    events = state.setdefault("events", [])
    if not events or events[-1]["message"] != message:
        events.append({"at": time.time(), "message": message})
        state["events"] = events[-100:]


def experiment_config(contract, proposal, state):
    cfg = copy.deepcopy(contract["base_config"])
    if proposal["kind"] == "stress":
        origin = next(e for e in state["experiments"] if e["id"] == proposal["origin"])
        cfg = copy.deepcopy(origin["config"])
        for key in ("commission", "min_commission", "stamp_duty", "transfer_fee", "min_transfer_fee", "impact_cost_coefficient"):
            cfg["exchange"][key] *= 2
    elif proposal.get("factor"):
        factor = proposal["factor"]
        validate_expression(factor["expression"], cfg["features"])
        cfg["source_features"] = list(cfg["features"])
        cfg["features"] += ["research_signal"]
        cfg["derived_factor"] = {"name": "research_signal", "expression": factor["expression"]}
    elif proposal.get("changes"):
        cfg = candidate_config(cfg, proposal["changes"])
    return cfg


def evidence(state):
    return [{"id": e["id"], "kind": e["proposal"]["kind"], "proposal": e["proposal"],
        "status": e["status"], "summary": e.get("result", {}).get("summary", {}).get("comparison"),
        "model_metrics": e.get("result", {}).get("model_metrics"),
        "half_returns": e.get("result", {}).get("development_half_returns"),
        "gates": e.get("gates"),
        "factor_validation": (e.get("result", {}).get("factor_analysis") or {}).get("splits", {}).get("valid")}
        for e in state["experiments"]]


def allowed_candidates(state):
    return [e["id"] for e in state["experiments"] if e["status"] == "completed"
            and (e["proposal"]["kind"] == "baseline" or all(e.get("gates", {}).values()) and e.get("gates"))]


def usage(case_dir):
    attempts = [runtime.frozen.read(p) for p in (case_dir / "api").glob("**/attempt-*.json")]
    done = [a for a in attempts if a["status"] == "completed"]
    return {"calls": len(done), "retryable": sum(a["status"] == "retryable" for a in attempts),
        "unknown_usage": sum(a.get("usage") is None for a in attempts),
        "input_tokens": sum((a.get("usage") or {}).get("prompt_tokens", 0) for a in done),
        "output_tokens": sum((a.get("usage") or {}).get("completion_tokens", 0) for a in done),
        "amount": None, "amount_note": "模型接口未返回账单金额"}


async def advance(row, store, lease):
    state, contract = row["checkpoint"], row["contract"]
    case_dir = runtime.case_directory(row["case_id"])
    deadline = row["deadline_epoch"]
    active = state.get("active")
    expired = time.time() >= deadline-30
    if expired or row["status"] == "cancel_requested":
        if active:
            info = runtime.inspect(active["container_name"])
            if info:
                runtime.observe(case_dir, active, contract, stop=True)
            else:
                active["status"] = "cancelled"
        event(state, "运行时间到期，计算已停止，证据已保存" if expired else "当前研究已取消，计算已停止")
        await store.checkpoint(row["run_id"], lease, state, "expired" if expired else "cancelled")
        return
    if row["status"] == "pause_requested" and (not active or not active.get("container_id") and not runtime.inspect(active["container_name"])):
        event(state, "已暂停后续推进，继续时创建新的运行窗口")
        await store.checkpoint(row["run_id"], lease, state, "paused")
        return

    if active:
        if not active.get("container_id"):
            active["container_id"] = runtime.launch(case_dir, active, active["config"], contract, deadline)
            event(state, "正在训练、逐日推理与回测" if active["container_id"] else "等待本节点的计算资源")
        else:
            try:
                result = runtime.observe(case_dir, active, contract)
            except ValueError:
                if active.get("status") != "failed" or active["proposal"]["kind"] != "candidate":
                    raise
                result = {"failed": True}
                event(state, "候选计算失败，保留失败记录并推进剩余候选")
            if result:
                if not result.get("failed"):
                    directory = case_dir / "experiments" / active["id"]
                    if digest(runtime.frozen.read(directory / "config.json")) != active["config_hash"]:
                        raise ValueError("实际实验配置与提交时的配置不一致")
                    result["development_half_returns"] = half_returns(directory, contract["base_config"]["portfolio"]["initial_capital"])
                    active["result"] = result
                    kind = active["proposal"]["kind"]
                    if kind == "candidate":
                        baseline = next(e["result"] for e in state["experiments"] if e["proposal"]["kind"] == "baseline" and e["status"] == "completed")
                        active["gates"] = candidate_gates(result, baseline, contract)
                        for name in ("universe.csv", "single_factor-equity.csv", "equal_weight-equity.csv"):
                            if result["artifacts"][name] != baseline["artifacts"][name]:
                                raise ValueError("候选的股票池或固定对照发生变化")
                    if kind == "stress":
                        origin = next(e for e in state["experiments"] if e["id"] == active["proposal"]["origin"])
                        for name in ("model.lgb", "signals.parquet", "daily-replay.parquet", "universe.csv"):
                            if result["artifacts"][name] != origin["result"]["artifacts"][name]:
                                raise ValueError("压力实验改变了冻结模型或信号")
                    event(state, f"{active['id']} 已完成独立账务核验")
                state["experiments"].append(active)
                state.pop("active")
                kind = active["proposal"]["kind"]
                state["stage"] = ("finish" if kind == "stress" else "select" if state["candidate_count"] >= contract["candidate_limit"] else "propose")
        state["usage"] = usage(case_dir)
        await store.checkpoint(row["run_id"], lease, state)
        return

    proposal = None
    if state.get("retry_proposal"):
        proposal = state.pop("retry_proposal")
    elif state["stage"] == "baseline":
        proposal = {"kind": "baseline", "hypothesis": "复现冻结基线与两组固定对照", "changes": {}}
    elif state["stage"] in ("propose", "select"):
        selecting = state["stage"] == "select"
        index = state["candidate_count"] + 1
        label = "selection" if selecting else f"candidate-{index}"
        correction = state.setdefault("corrections", {}).get(label, [])
        call_dir = case_dir / "api" / label / f"call-{len(correction)+1}"
        call_dir.mkdir(parents=True, exist_ok=True)
        if selecting:
            properties = {"selected": {"type": "string", "enum": allowed_candidates(state)},
                          "reason": {"type": "string"}, "next_question": {"type": "string"}}
        elif row["kind"] == "method":
            properties = {"hypothesis": {"type": "string"}, "expected_outcome": {"type": "string"},
                          "evidence": {"type": "string"}, "expression": {"type": "string"}}
        else:
            properties = {"hypothesis": {"type": "string"}, "expected_outcome": {"type": "string"},
                "evidence": {"type": "string"}, "changes": {"type": "object", "properties": {
                    "features": {"type": "array", "items": {"type": "string"}},
                    "model_params": {"type": "object", "properties": {
                        k: {"type": "integer" if k in INT_PARAMS else "number", "minimum": v[0], "maximum": v[1]}
                        for k, v in PARAMS.items()}, "additionalProperties": False}}, "additionalProperties": False}}
        prompt = json.dumps({"task": row["goal"], "source_material": contract.get("source_text", ""),
            "contract": {k: contract[k] for k in ("base_config", "candidate_limit", "acceptance")},
            "prior_experiments": evidence(state), "allowed_selection": allowed_candidates(state),
            "instruction": ("选择满足全部门槛的候选或保留基线；压力实验尚未运行，不能宣称已经完成。" if selecting else
                "提出一个新的可证伪候选。策略只改变一个轴：原特征子集或模型参数。因子研究只返回受限公式，名称固定 research_signal。"),
            "expression_functions": "rank(x), abs(x), log1p_abs(x), lag(x,n), mean(x,n), std(x,n); + - * /; n=1..60; total lookback<=120",
            "expression_columns": contract["base_config"]["features"], "validation_errors": correction}, ensure_ascii=False)
        # Explicit supplied factor/formula is executed, not silently replaced by a model.
        supplied = contract.get("expression") or (contract.get("seed_factor") or {}).get("expression")
        if not selecting and index == 1 and supplied:
            decision = {"hypothesis": row["goal"], "expected_outcome": "检验给定公式的覆盖、稳定性与组合增量",
                        "evidence": "用户公式或已核验的父课题因子", "expression": supplied}
            runtime.frozen.write(call_dir.parent / "supplied-decision.json", decision)
        else:
            try:
                decision = runtime.model_decision(call_dir, contract, "select_candidate" if selecting else "propose_experiment", properties, prompt, deadline)
            except runtime.InvalidDecision as exc:
                decision = {"response_error": str(exc)}
        if decision is None:
            event(state, "等待模型服务恢复或可用额度，保留当前阶段")
            state["usage"] = usage(case_dir)
            await store.checkpoint(row["run_id"], lease, state)
            return
        try:
            if "response_error" in decision:
                raise ValueError(decision["response_error"])
            if selecting:
                if decision["selected"] not in allowed_candidates(state):
                    raise ValueError("所选候选没有通过固定门槛")
                if not all(isinstance(decision[k], str) and decision[k].strip() for k in ("reason", "next_question")):
                    raise ValueError("选择需要说明依据与下一步")
                state["selection"] = decision
                proposal = {"kind": "stress", "origin": decision["selected"], "hypothesis": "固定所选配置并将费用翻倍"}
            else:
                for key in ("hypothesis", "expected_outcome", "evidence"):
                    if not isinstance(decision.get(key), str) or not decision[key].strip():
                        raise ValueError("候选必须提供假设、可检验预期与已有证据")
                proposal = {"kind": "candidate", **decision}
                if "expression" in proposal:
                    proposal["factor"] = {"expression": proposal.pop("expression")}
                cfg = experiment_config(contract, proposal, state)
                if digest(cfg) in {e["config_hash"] for e in state["experiments"]}:
                    raise ValueError("配置已经实验过，不重复同一候选")
                state["candidate_count"] += 1
            runtime.frozen.write(call_dir / "tool-output.json", {"accepted": True, "arguments": decision})
        except (ValueError, KeyError, TypeError) as exc:
            correction.append(str(exc))
            state["corrections"][label] = correction
            runtime.frozen.write(call_dir / "tool-output.json", {"accepted": False, "error": str(exc)})
            if len(correction) >= 3 or supplied and not selecting and index == 1:
                raise ValueError("候选连续校验失败："+str(exc)) from None
            event(state, "候选未通过合同检查，要求模型修正")
            await store.checkpoint(row["run_id"], lease, state)
            return
    elif state["stage"] == "finish":
        finish(case_dir, state, row)
        event(state, "研究已完成，报告和可核验产物已保存")
        await store.checkpoint(row["run_id"], lease, state, "completed")
        return
    if proposal:
        attempts = len(list((case_dir / "experiments").glob("*/launch-intent.json")))
        if attempts >= 12:
            raise ValueError("课题累计计算尝试达到 12 次上限，保留全部证据")
        cfg = experiment_config(contract, proposal, state)
        ident = f"E{attempts:02d}"
        state["active"] = {"id": ident, "container_name": f"qm-research-{row['case_id'][:12]}-{ident.lower()}",
            "status": "planned", "proposal": proposal, "config": cfg, "config_hash": digest(cfg)}
        event(state, "实验方案已落盘，等待受限计算")
    state["usage"] = usage(case_dir)
    await store.checkpoint(row["run_id"], lease, state)


def finish(case_dir, state, row):
    for exp in state["experiments"]:
        if exp["status"] != "completed":
            continue
        for name, expected in exp["result"]["artifacts"].items():
            if runtime.frozen.sha256(case_dir / "experiments" / exp["id"] / name) != expected:
                raise ValueError("已核验实验的产物发生变化")
    lines = [f"# {row['goal']}", "", "本报告使用已观察的开发区间，不构成独立验证或交易授权。", "",
             "|实验|类型|净收益|最大回撤|状态|", "|---|---|---:|---:|---|"]
    for exp in state["experiments"]:
        m = exp.get("result", {}).get("summary", {}).get("comparison", {}).get("model")
        lines.append(f"|{exp['id']}|{exp['proposal']['kind']}|{m['total_return']:.4%}|{m['max_drawdown']:.4%}|已核验|" if m else
                     f"|{exp['id']}|{exp['proposal']['kind']}|—|—|失败，证据保留|")
    lines += ["", "## 模型选择说明（解释，不代表数值已被模型核验）", "", json.dumps(state["selection"], ensure_ascii=False, indent=2)]
    (case_dir / "REPORT.md").write_text("\n".join(lines)+"\n")
    state["report_sha256"] = runtime.frozen.sha256(case_dir / "REPORT.md")
    state["research_status"] = "needs_independent_validation"
    state["usage"] = usage(case_dir)


async def tick():
    cfg, store, lease = runtime.settings(), Store(), uuid4().hex
    row = await store.claim(cfg["node_id"], lease)
    if not row:
        return {"status": "idle"}
    try:
        await advance(row, store, lease)
    except (RuntimeError, subprocess.SubprocessError):
        # Keep polling the same container after a Docker transport failure,
        # including after deadline/cancel; stopped requires observed evidence.
        state = row["checkpoint"]
        state["error"] = "执行服务暂时不可达，保留原容器标识并自动重试"
        event(state, state["error"])
        await store.checkpoint(row["run_id"], lease, state)
    except Exception as exc:
        # Transport/worker uncertainty keeps existing handles; never fabricate success.
        state = row["checkpoint"]
        message = str(exc)
        try:
            message = message.replace(runtime.credentials()["api_key"], "[REDACTED_SECRET]")
        except Exception:
            pass
        state["error"] = message[:700]
        event(state, "需要检查："+state["error"])
        await store.checkpoint(row["run_id"], lease, state, "blocked")
    return {"run_id": row["run_id"]}
