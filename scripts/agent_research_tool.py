#!/usr/bin/env python3
"""Bounded experiment tools for a real QuantBot research session.

Reuse the frozen CN worker/engine. The agent chooses hypotheses and permitted
changes; this program fixes data, labels, costs and comparison rules. It is an
experiment API, not an autonomous planner or a replacement backtest engine.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import run_frozen_research as frozen

ROOT = Path(__file__).resolve().parents[1]
PARAMS = {"num_leaves": (4, 31), "max_depth": (2, 6),
          "min_data_in_leaf": (100, 1000), "lambda_l2": (0, 50),
          "learning_rate": (0.01, 0.1)}
INT_PARAMS = {"num_leaves", "max_depth", "min_data_in_leaf"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def candidate_config(base, changes):
    if not isinstance(changes, dict) or set(changes) - {"features", "model_params"}:
        raise ValueError("Only features OR model_params may change; data/splits/costs are fixed")
    if len(changes) > 1:
        raise ValueError("Change one experimental axis per candidate")
    cfg = copy.deepcopy(base)
    if "features" in changes:
        features = changes["features"]
        if (not isinstance(features, list) or not all(isinstance(x, str) for x in features)
                or len(features) != len(set(features)) or not 2 <= len(features) <= len(base["features"])
                or not set(features) <= set(base["features"])
                or base["portfolio"]["single_factor"] not in features):
            raise ValueError("Use a unique subset of existing factors, including the momentum control")
        cfg["features"] = features
    if "model_params" in changes:
        params = changes["model_params"]
        if not isinstance(params, dict) or not params or set(params) - set(PARAMS):
            raise ValueError("Unknown or empty model parameter changes")
        for key, value in params.items():
            lo, hi = PARAMS[key]
            if (type(value) not in (int, float) or not lo <= value <= hi
                    or key in INT_PARAMS and type(value) is not int):
                raise ValueError(f"Invalid {key}: expected {lo}..{hi}")
        cfg["model"]["params"].update(params)
    frozen.validate_config(cfg)
    return cfg


def run_process(command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def experiments(session):
    return sorted((session / "experiments").glob("E*/state.json"))


def experiment_dir(session, ident):
    if not re.fullmatch(r"E\d{2}", ident):
        raise ValueError("Invalid experiment ID")
    directory = session / "experiments" / ident
    if not (directory / "state.json").is_file():
        raise ValueError("Unknown experiment")
    return directory


def initialize(session, source):
    if (session / "contract.json").exists():
        raise ValueError("Session already initialized; use its existing contract")
    source = source.resolve()
    relative = source.relative_to(ROOT)
    manifest = frozen.verify(source)
    base = frozen.read(source / "snapshot/config.json")
    now = time.time()
    contract = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "deadline_epoch": now + 4 * 3600, "host_session": str(session.resolve()),
        "frozen_relative": str(relative), "host_frozen": str(source),
        "manifest_sha256": frozen.sha256(source / "manifest.json"),
        "base_config": base, "image": manifest["image"],
        "maximum_candidates": 2,
        "research_purpose": "workflow_validation using development comparisons; no independent holdout or live trading",
        "acceptance": {"min_return_improvement": 0.005, "max_drawdown_degradation": 0.01,
                       "min_validation_rank_ic": 0, "min_half_excess": -0.005},
        "allowed_changes": {"features": "subset of base features; keep mom_ret_20d",
                            "model_params": PARAMS},
    }
    (session / "experiments").mkdir(parents=True, exist_ok=True)
    frozen.write(session / "contract.json", contract)
    return contract


def checked_contract(session):
    c = frozen.read(session / "contract.json")
    source = ROOT / c["frozen_relative"]
    if frozen.sha256(source / "manifest.json") != c["manifest_sha256"]:
        raise ValueError("Input manifest changed")
    return c, source


def submit(session, proposal):
    c, source = checked_contract(session)
    if time.time() > c["deadline_epoch"] or (session / "decision.json").exists():
        raise ValueError("Research submission window is closed")
    states = [frozen.read(p) for p in experiments(session)]
    if any(s["status"] not in ("completed", "failed") for s in states):
        raise ValueError("An experiment is active or uncertain; inspect it before submitting")
    kind = proposal.get("kind")
    if kind not in ("baseline", "candidate", "stress"):
        raise ValueError("kind must be baseline, candidate or stress")
    if not proposal.get("hypothesis") or not proposal.get("expected_outcome"):
        raise ValueError("Record hypothesis and falsifiable expected_outcome before execution")
    changes = proposal.get("changes", {})
    if kind == "baseline":
        if states or changes:
            raise ValueError("Baseline must be first and unchanged")
        cfg = copy.deepcopy(c["base_config"])
    elif kind == "candidate":
        if not states or states[0]["status"] != "completed":
            raise ValueError("Complete baseline first")
        if any(s["kind"] == "stress" for s in states):
            raise ValueError("Do not tune after final stress validation")
        if sum(s["kind"] == "candidate" for s in states) >= c["maximum_candidates"]:
            raise ValueError("Candidate budget exhausted")
        if not proposal.get("evidence") or not changes:
            raise ValueError("Candidate needs evidence from preceding experiments and a change")
        cfg = candidate_config(c["base_config"], changes)
        if fingerprint(cfg) in {s["config_sha256"] for s in states}:
            raise ValueError("Duplicate configuration; explain existing results instead")
    else:
        if changes or any(s["kind"] == "stress" for s in states):
            raise ValueError("Exactly one frozen stress run; no parameter changes")
        origin = frozen.read(experiment_dir(session, proposal.get("origin", "")) / "state.json")
        if origin["status"] != "completed" or origin["kind"] not in ("baseline", "candidate"):
            raise ValueError("Stress origin must be a completed baseline or candidate")
        if origin["kind"] == "candidate":
            gates = candidate_gates(refresh(session, origin["id"]), refresh(session, "E00"), c)
            if not all(gates.values()):
                raise ValueError(f"Stress origin fails fixed candidate gates: {gates}; retain baseline")
        cfg = frozen.read(experiment_dir(session, origin["id"]) / "config.json")
        for key in ("commission", "min_commission", "stamp_duty", "transfer_fee",
                    "min_transfer_fee", "impact_cost_coefficient"):
            cfg["exchange"][key] *= 2
    frozen.verify(source)
    ident = f"E{len(states):02d}"
    directory = session / "experiments" / ident
    directory.mkdir()
    frozen.write(directory / "proposal.json", proposal)
    frozen.write(directory / "config.json", cfg)
    host_directory = Path(c["host_session"]) / "experiments" / ident
    cmd = frozen.command(Path(c["host_frozen"]), {"image": c["image"]}, host_directory)
    name = "qm-agent-" + fingerprint(c["host_session"])[:8] + "-" + ident.lower()
    cmd[cmd.index("--name") + 1] = name
    cmd.insert(2, "--detach")
    at = cmd.index("--entrypoint")
    cmd[at:at] = ["--mount", f"type=bind,src={host_directory / 'config.json'},dst=/frozen/config.json,readonly"]
    state = {"id": ident, "kind": kind, "status": "submission_intent", "container_name": name,
             "config_sha256": fingerprint(cfg), "proposal_sha256": fingerprint(proposal),
             "started_epoch": time.time(), "command": cmd}
    frozen.write(directory / "state.json", state)
    try:
        state["container_id"] = run_process(cmd)
        state["status"] = "running"
    except subprocess.CalledProcessError as exc:
        state["status"] = "submission_uncertain"
        state["error"] = exc.output[-1500:]
        raise RuntimeError("Docker submission failed/uncertain; inspect the recorded container, do not resubmit") from exc
    finally:
        frozen.write(directory / "state.json", state)
    return {"id": ident, "status": state["status"], "hypothesis": proposal["hypothesis"]}


def half_returns(directory, capital):
    with (directory / "model-equity.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    mid = len(rows) // 2
    split_value = float(rows[mid - 1]["account"])
    return [split_value / capital - 1, float(rows[-1]["account"]) / split_value - 1]


def candidate_gates(result, baseline, contract):
    b = baseline["summary"]["comparison"]["model"]
    m = result["summary"]["comparison"]["model"]
    ic = result["model_metrics"]["validation_metrics"].get("rank_ic")
    limits = contract["acceptance"]
    return {
        "return_improved": m["total_return"] - b["total_return"] >= limits["min_return_improvement"],
        "drawdown_acceptable": m["max_drawdown"] >= b["max_drawdown"] - limits["max_drawdown_degradation"],
        "positive_validation_ic": ic is not None and ic > limits.get("min_validation_rank_ic", 0),
        "half_periods_acceptable": all(x-y >= limits["min_half_excess"] for x,y in zip(
            result["development_half_returns"], baseline["development_half_returns"])),
    }


def refresh(session, ident):
    c, source = checked_contract(session)
    directory = experiment_dir(session, ident)
    state = frozen.read(directory / "state.json")
    if state["status"] not in ("completed", "failed"):
        raw = run_process(["docker", "inspect", "--format", "{{json .State}}", state["container_name"]])
        runtime = json.loads(raw)
        if runtime["Running"]:
            return {"id": ident, "status": "running", "elapsed_seconds": round(time.time() - state["started_epoch"]),
                    "log_tail": run_process(["docker", "logs", "--tail", "5", state["container_name"]])}
        (directory / "execution.log").write_text(run_process(["docker", "logs", state["container_name"]]))
        state["exit_code"] = runtime["ExitCode"]
        state["elapsed_seconds"] = round(time.time() - state["started_epoch"])
        if runtime["ExitCode"] != 0:
            state["status"] = "failed"
        else:
            frozen.verify(source)
            if not frozen.read(directory / "summary.json")["checks_passed"]:
                raise ValueError("Experiment returned unverified results")
            if fingerprint(frozen.read(directory / "config.json")) != state["config_sha256"]:
                raise ValueError("Experiment configuration was modified")
            state["artifacts"] = {p.name: frozen.sha256(p) for p in directory.iterdir()
                                  if p.is_file() and p.name != "state.json"}
            state["status"] = "completed"
        frozen.write(directory / "state.json", state)
    if state["status"] == "failed":
        return {"id": ident, "status": "failed", "log_tail": (directory / "execution.log").read_text()[-2500:]}
    for name, digest in state["artifacts"].items():
        if frozen.sha256(directory / name) != digest:
            raise ValueError(f"Experiment artifact changed: {ident}/{name}")
    summary = frozen.read(directory / "summary.json")
    metadata = frozen.read(directory / "model-metadata.json")
    result = {"id": ident, "status": "completed", "kind": state["kind"],
              "proposal": frozen.read(directory / "proposal.json"), "summary": summary,
              "model_metrics": metadata,
              "development_half_returns": half_returns(directory, c["base_config"]["portfolio"]["initial_capital"])}
    if state["kind"] == "candidate":
        result["development_gates"] = candidate_gates(result, refresh(session, "E00"), c)
    return result


def finish(session, decision):
    c, _ = checked_contract(session)
    results = [refresh(session, p.parent.name) for p in experiments(session)]
    if any(r["status"] != "completed" for r in results):
        raise ValueError("All submitted experiments must finish and pass verification")
    by_id = {r["id"]: r for r in results}
    baseline = by_id["E00"]
    winner = by_id[decision["selected"]]
    if winner["kind"] not in ("baseline", "candidate"):
        raise ValueError("Select a baseline or candidate, never the stress run")
    stress = [r for r in results if r["kind"] == "stress"]
    if len(stress) != 1 or stress[0]["proposal"]["origin"] != winner["id"]:
        raise ValueError("Run fixed double-cost stress on the selected configuration")
    if sum(r["kind"] == "candidate" for r in results) < 2:
        raise ValueError("Need at least two feedback-driven candidate experiments")
    gates = {}
    for r in results:
        if r["kind"] != "candidate":
            continue
        gates[r["id"]] = candidate_gates(r, baseline, c)
    if winner["kind"] == "candidate" and not all(gates[winner["id"]].values()):
        raise ValueError("Selected candidate fails fixed development gates; retain baseline")
    if not decision.get("reason") or not decision.get("next_question"):
        raise ValueError("Record selection evidence and the next question for human review")
    output = {"agent_decision": decision, "candidate_gates": gates,
              "research_status": "needs_independent_validation", "automatic_trading_authorized": False,
              "results": results}
    frozen.write(session / "decision.json", output)
    return {k: v for k, v in output.items() if k != "results"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["init", "describe", "submit", "status", "finish"])
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--frozen", type=Path)
    p.add_argument("--proposal", type=Path)
    p.add_argument("--id")
    p.add_argument("--wait-seconds", type=int, default=0)
    args = p.parse_args()
    session = args.session.resolve()
    session.mkdir(parents=True, exist_ok=True)
    with (session / ".tool.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "init":
            result = initialize(session, args.frozen)
        elif args.action == "describe":
            result = {"contract": checked_contract(session)[0],
                      "experiments": [frozen.read(p) for p in experiments(session)]}
        elif args.action == "submit":
            result = submit(session, frozen.read(args.proposal))
        elif args.action == "finish":
            result = finish(session, frozen.read(args.proposal))
        else:
            deadline = time.monotonic() + min(max(args.wait_seconds, 0), 55)
            while True:
                ids = [args.id] if args.id else [p.parent.name for p in experiments(session)]
                result = [refresh(session, ident) for ident in ids]
                if not any(r["status"] == "running" for r in result) or time.monotonic() >= deadline:
                    break
                time.sleep(3)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
