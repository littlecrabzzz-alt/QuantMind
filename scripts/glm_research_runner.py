#!/usr/bin/env python3
"""Bounded GLM API comparison using the existing frozen experiment tools.

One-shot cloud acceptance runner, not a replacement for the service scheduler.
The model selects candidates; this program controls execution and accounting.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.error
import urllib.request

import agent_research_tool as experiment
import run_frozen_research as frozen
from verify_agent_research import reconcile

MODELS = ("glm-5.3-flash", "glm-5.3")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    frozen.write(path, value)


def read(path):
    return frozen.read(path)


def retry_delay(attempt, header=None):
    if header:
        try:
            return max(1, float(header))
        except ValueError:
            try:
                return max(1, parsedate_to_datetime(header).timestamp() - time.time())
            except (ValueError, TypeError):
                pass
    return min(60, 2 ** min(attempt, 6))


class StopRun(RuntimeError):
    pass


def check_deadline(root, deadline):
    if (root / "STOP").exists():
        raise StopRun("STOP requested")
    if time.time() >= deadline:
        raise StopRun("Deadline reached; no new work")


def pause(root, deadline, seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        check_deadline(root, deadline)
        time.sleep(min(2, max(0, until - time.monotonic())))


def request_tool(root, folder, credentials, model, name, properties, prompt, deadline):
    """Persist before POST; reuse saved responses after restart; only retry 429/503.

    An interrupted/ambiguous transport is retained as uncertain, never silently
    repeated. Unknown provider usage remains unknown. No secret is logged.
    """
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model, "reasoning_effort": "high", "max_tokens": 8192,
        "thinking": {"type": "enabled"},
        "messages": [{"role": "system", "content":
            "You are a quantitative research agent. Call the supplied function exactly once. "
            "Use only provided evidence; distinguish development comparisons from independent "
            "validation. Never infer causality or profitability from a few experiments. "
            "Write explanation strings in Chinese. Do not request other tools."},
            {"role": "user", "content": prompt}],
        "tools": [{"type": "function", "function": {"name": name,
            "description": "Submit a bounded research decision for program validation.",
            "parameters": {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}}}],
        "tool_choice": "auto",
    }
    if (folder / "request.json").exists():
        if read(folder / "request.json") != payload:
            raise ValueError("Saved API request changed; do not reuse this call ID")
    else:
        save(folder / "request.json", payload)
    for attempt in range(1, 13):
        check_deadline(root, deadline)
        attempt_file = folder / f"attempt-{attempt:02d}.json"
        if attempt_file.exists():
            status = read(attempt_file)
            if status["status"] == "completed":
                response = read(folder / "response.json")
                break
            if status["status"] != "retryable":
                raise StopRun("Prior API call uncertain or failed; no automatic duplicate POST")
            pause(root, deadline, status.get("retry_after", 2))
            continue
        save(attempt_file, {"status": "request_intent", "started_epoch": time.time(),
                            "usage": None})
        started = time.monotonic()
        request = urllib.request.Request(credentials["base_url"] + "/chat/completions",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
                "Authorization": "Bearer " + credentials["api_key"]})
        try:
            with urllib.request.urlopen(request, timeout=min(180, max(1, deadline-time.time()))) as stream:
                response = json.load(stream)
            # Save raw model output privately for exact replay, not as verified analysis.
            save(folder / "response.json", response)
            save(attempt_file, {"status": "completed", "seconds": round(time.monotonic()-started, 3),
                "usage": response.get("usage"), "returned_model": response.get("model")})
            break
        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 503)
            delay = retry_delay(attempt, exc.headers.get("Retry-After"))
            raw = exc.read().decode(errors="replace").replace(credentials["api_key"], "[REDACTED_SECRET]")
            save(attempt_file, {"status": "retryable" if retryable else "failed",
                "http_status": exc.code, "retry_after": delay, "usage": None,
                "error": raw[:1200]})
            if not retryable:
                raise StopRun(f"API returned HTTP {exc.code}") from None
            pause(root, deadline, delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            save(attempt_file, {"status": "uncertain", "usage": None, "error_type": type(exc).__name__})
            raise StopRun("API outcome uncertain; retained for review") from None
    else:
        raise StopRun("Retry count exhausted")
    message = response["choices"][0]["message"]
    calls = message.get("tool_calls", [])
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != name:
        raise ValueError("Expected exactly one allowed tool call")
    args = json.loads(calls[0]["function"]["arguments"])
    if not isinstance(args, dict) or set(args) != set(properties):
        raise ValueError("Tool arguments do not match required keys")
    save(folder / "tool-call.json", {"id": calls[0]["id"], "name": name, "arguments": args})
    return args


def evidence(result):
    return {"id": result["id"], "proposal": result["proposal"],
        "comparison": result["summary"]["comparison"],
        "model_metrics": result["model_metrics"],
        "half_returns": result["development_half_returns"],
        "gates": result.get("development_gates")}


def choose(root, folder, credentials, model, kind, prompt, deadline, validator):
    properties = ({"hypothesis": {"type": "string"}, "expected_outcome": {"type": "string"},
        "evidence": {"type": "string"}, "changes": {"type": "object", "properties": {
            "features": {"type": "array", "items": {"type": "string"}},
            "model_params": {"type": "object", "properties": {
                k: {"type": "integer" if k in experiment.INT_PARAMS else "number",
                    "minimum": v[0], "maximum": v[1]} for k,v in experiment.PARAMS.items()},
                "additionalProperties": False}}, "additionalProperties": False}}
        if kind == "candidate" else {"selected": {"type": "string"},
            "reason": {"type": "string"}, "next_question": {"type": "string"}})
    errors = []
    for index in range(3):
        call_dir = folder / f"call-{index+1}"
        if (call_dir / "accepted.json").exists():
            args = read(call_dir / "accepted.json")
            validator(args)
            return args
        try:
            args = request_tool(root, call_dir, credentials, model,
                "propose_experiment" if kind == "candidate" else "select_candidate", properties,
                prompt + ("\nPrior validation errors: " + json.dumps(errors) if errors else ""), deadline)
            validator(args)
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)[:700]
            errors.append(error)
            save(call_dir / "tool-output.json", {"accepted": False, "error": error})
            continue
        save(call_dir / "tool-output.json", {"accepted": True, "arguments": args})
        save(call_dir / "accepted.json", args)
        return args
    raise StopRun("Three invalid decisions; keep evidence and stop this model")


def run_experiment(root, session, proposal, deadline):
    check_deadline(root, deadline)
    existing = [read(p) for p in experiment.experiments(session)]
    ident = None
    for item in existing:
        if item["proposal_sha256"] == experiment.fingerprint(proposal):
            ident = item["id"]
            break
    if ident is None:
        if deadline-time.time() < 600:
            raise StopRun("Less than ten minutes remain; reserve time for cleanup")
        ident = experiment.submit(session, proposal)["id"]
    while True:
        check_deadline(root, deadline)
        result = experiment.refresh(session, ident)
        if result["status"] == "completed":
            print(json.dumps({"model_session": session.name, "experiment": ident, "status": "completed"}), flush=True)
            return result
        if result["status"] != "running":
            raise StopRun(f"Experiment {ident} failed; preserve outputs")
        pause(root, deadline, 10)


def verify_session(session):
    contract, source = experiment.checked_contract(session)
    frozen.verify(source)
    checked = []
    for path in experiment.experiments(session):
        result = experiment.refresh(session, path.parent.name)
        assert result["status"] == "completed"
        config = read(path.parent / "config.json")
        proposal = result["proposal"]
        if result["kind"] == "stress":
            origin = experiment.experiment_dir(session, proposal["origin"])
            expected = read(origin / "config.json")
            for key in ("commission", "min_commission", "stamp_duty", "transfer_fee", "min_transfer_fee", "impact_cost_coefficient"):
                expected["exchange"][key] *= 2
            for name in ("model.lgb", "signals.parquet", "daily-replay.parquet", "universe.csv"):
                assert frozen.sha256(path.parent/name) == frozen.sha256(origin/name)
        else:
            expected = experiment.candidate_config(contract["base_config"], proposal.get("changes", {}))
            if result["kind"] == "candidate":
                for name in ("universe.csv", "single_factor-equity.csv", "equal_weight-equity.csv"):
                    assert frozen.sha256(path.parent/name) == frozen.sha256(session/"experiments/E00"/name)
        assert config == expected
        checked.append({"id": result["id"], "portfolios": {
            name: reconcile(path.parent, name, config["portfolio"]["initial_capital"], metrics)
            for name, metrics in result["summary"]["comparison"].items()}})
    calls = list((session/"api").glob("**/tool-call.json"))
    assert len(calls) >= 3
    for p in calls:
        assert (p.parent/"tool-output.json").exists()
    report = {"verification_passed": True, "experiments": checked,
        "actual_tool_calls": len(calls), "research_status": "needs_independent_validation",
        "automatic_trading_authorized": False,
        "note": "Development workflow acceptance, not independent strategy validation."}
    save(session/"verification.json", report)
    return report


def cancel_owned(session):
    cancelled = []
    for path in experiment.experiments(session):
        state = read(path)
        if state["status"] in ("completed", "failed"):
            continue
        name = state["container_name"]
        expected = "qm-agent-" + experiment.fingerprint(str(session.resolve()))[:8] + "-" + state["id"].lower()
        if name != expected:
            raise ValueError("Container identity mismatch; refuse cancellation")
        proc = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=20)
        if proc.returncode:
            cancelled.append({"id": state["id"], "status": "unknown_container"})
            continue
        info = json.loads(proc.stdout)[0]
        assert any(m.get("Source") == str(path.parent) and m.get("Destination") == "/output" for m in info["Mounts"])
        if info["State"]["Running"]:
            subprocess.run(["docker", "stop", "--time", "10", name], check=True, capture_output=True, timeout=30)
        running = subprocess.check_output(["docker", "inspect", "--format", "{{.State.Running}}", name], text=True).strip()
        cancelled.append({"id": state["id"], "running_after_stop": running})
    save(session/"cleanup.json", cancelled)


def run_model(root, credentials, model, source, deadline):
    session = root/model
    session.mkdir(exist_ok=True)
    if (session/"verification.json").exists():
        return verify_session(session)
    if not (session/"contract.json").exists():
        experiment.initialize(session, source)
    contract, _ = experiment.checked_contract(session)
    # Existing four-hour submission limit is retained; eight hours is an outer cap.
    deadline = min(deadline, contract["deadline_epoch"]-120)
    results = [run_experiment(root, session, {"kind": "baseline",
        "hypothesis": "复现固定八因子基线及两组对照", "expected_outcome": "真实训练推理回测通过数值核验", "changes": {}}, deadline)]
    for index in (1, 2):
        prompt = "Choose the next candidate from prior actual results. Change only one axis: an allowed feature subset OR model parameters. No data/date/cost changes. This is already-observed development data, not independent out-of-sample validation.\n" + json.dumps({
            "contract": contract, "prior_results": [evidence(r) for r in results]}, ensure_ascii=False)
        def validate(args):
            for key in ("hypothesis", "expected_outcome", "evidence"):
                if not isinstance(args.get(key), str) or not args[key].strip():
                    raise ValueError("Explanation and prior-result evidence are required")
            cfg = experiment.candidate_config(contract["base_config"], args["changes"])
            if not args["changes"]:
                raise ValueError("A candidate must change one axis")
            prior = [read(session/"experiments"/r["id"]/"config.json") for r in results]
            if cfg in prior:
                raise ValueError("This configuration was already tried")
        args = choose(root, session/"api"/f"candidate-{index}", credentials, model, "candidate", prompt, deadline, validate)
        results.append(run_experiment(root, session, {"kind": "candidate", **args}, deadline))
    allowed = [r["id"] for r in results if r["kind"] == "baseline" or all(r["development_gates"].values())]
    def validate_selection(args):
        if args["selected"] not in allowed or not args["reason"] or not args["next_question"]:
            raise ValueError(f"Select from {allowed} and provide reason/next_question")
    decision = choose(root, session/"api"/"selection", credentials, model, "selection",
        "Select a candidate passing ALL fixed development gates, or retain baseline. No new experiments after the fixed double-cost stress.\n" +
        json.dumps({"allowed": allowed, "results": [evidence(r) for r in results]}, ensure_ascii=False), deadline, validate_selection)
    results.append(run_experiment(root, session, {"kind": "stress", "origin": decision["selected"],
        "hypothesis": "冻结所选配置后检验双倍费用敏感性", "expected_outcome": "量化成本冲击，不据此追加调参"}, deadline))
    experiment.finish(session, decision)
    lines = [f"# {model} 真实 API 工作流验收", "", "本轮使用已观察开发区间；收益不代表独立验证或投资价值。", "",
        "| 实验 | 类型 | 净收益 | 最大回撤 | 成交笔数 |", "| --- | --- | ---: | ---: | ---: |"]
    for r in results:
        m = r["summary"]["comparison"]["model"]
        lines.append(f"| {r['id']} | {r['kind']} | {m['total_return']:.4%} | {m['max_drawdown']:.4%} | {m['trades']} |")
    lines += ["", "模型选择与解释（不构成机制证明）：", "", json.dumps(decision, ensure_ascii=False, indent=2)]
    (session/"REPORT.md").write_text("\n".join(lines)+"\n")
    return verify_session(session)


def summarize(root):
    summary = {}
    for model in MODELS:
        folder = root/model
        attempts = [read(p) for p in folder.glob("api/**/attempt-*.json")]
        success = [a for a in attempts if a["status"] == "completed"]
        summary[model] = {"status": read(folder/"run-status.json") if (folder/"run-status.json").exists() else None,
            "completed_api_calls": len(success), "retryable_calls": sum(a["status"] == "retryable" for a in attempts),
            "unknown_usage_calls": sum(a.get("usage") is None for a in attempts),
            "api_seconds": round(sum(a.get("seconds", 0) for a in success), 3),
            "prompt_tokens": sum((a.get("usage") or {}).get("prompt_tokens", 0) for a in success),
            "completion_tokens": sum((a.get("usage") or {}).get("completion_tokens", 0) for a in success),
            "cached_tokens": sum(((a.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens", 0) for a in success),
            "billing": "Coding Plan credit consumption not returned by chat API; no monetary estimate claimed"}
    save(root/"summary.json", summary)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, required=True)
    p.add_argument("--frozen", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--credentials", type=Path, required=True)
    p.add_argument("--hours", type=float, default=2)
    args = p.parse_args()
    if not 0 < args.hours <= 8:
        p.error("hours must be within (0, 8]")
    project, root, source = args.project_root.resolve(), args.output.resolve(), args.frozen.resolve()
    if os.uname().sysname != "Linux" or project != Path("/root/data/disk/quantmind/project"):
        p.error("Real execution requires the confirmed cloud authority")
    if not root.is_relative_to(project/"data/agent_research") or not source.is_relative_to(project/"results"):
        p.error("Output/frozen paths escaped designated research locations")
    if "authority=lzy-vm" not in (project.parent/"AUTHORITY").read_text():
        p.error("Wrong data authority")
    if args.credentials.stat().st_mode & 0o077:
        p.error("Credential permissions must be private")
    credentials = read(args.credentials)
    if credentials["base_url"] != "https://open.bigmodel.cn/api/coding/paas/v4":
        p.error("Unexpected credential destination")
    experiment.ROOT = project
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True)
    with (root/"runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        metadata = root/"run.json"
        manifest_hash = frozen.sha256(source/"manifest.json")
        if metadata.exists():
            run = read(metadata)
            if run["manifest_sha256"] != manifest_hash or run["source"] != str(source):
                raise ValueError("Frozen source changed")
        else:
            run = {"started_at": datetime.now(timezone.utc).isoformat(),
                "deadline_epoch": time.time()+args.hours*3600, "source": str(source),
                "manifest_sha256": manifest_hash, "models": list(MODELS),
                "code_sha256": {n: frozen.sha256(Path(__file__).parent/n) for n in
                    ("glm_research_runner.py", "agent_research_tool.py", "run_frozen_research.py", "verify_agent_research.py")},
                "purpose": "real API workflow comparison", "monetary_limit": None}
            save(metadata, run)
        for name, digest in run["code_sha256"].items():
            if frozen.sha256(Path(__file__).parent/name) != digest:
                raise ValueError("Runner code changed; do not resume with new semantics")
        def stop_handler(signum, frame):
            (root/"STOP").touch()
            raise StopRun(f"Signal {signum}")
        signal.signal(signal.SIGTERM, stop_handler)
        signal.signal(signal.SIGINT, stop_handler)
        for model in MODELS:
            session = root/model
            try:
                check_deadline(root, run["deadline_epoch"]-120)
                save(session/"run-status.json", {"status": "running", "started_epoch": time.time()})
                verification = run_model(root, credentials, model, source, run["deadline_epoch"]-120)
                save(session/"run-status.json", {"status": "completed", "verification_passed": verification["verification_passed"]})
            except Exception as exc:
                save(session/"run-status.json", {"status": "blocked", "error_type": type(exc).__name__,
                    "error": str(exc).replace(credentials["api_key"], "[REDACTED_SECRET]")[:1000]})
                cancel_owned(session)
            finally:
                summarize(root)
        summary = summarize(root)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        if any((v["status"] or {}).get("status") != "completed" for v in summary.values()):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
