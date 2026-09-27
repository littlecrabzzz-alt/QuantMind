#!/usr/bin/env python3
"""Read-only hourly snapshot; credentials stay in the private runtime config."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import requests
from controller import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home()
        / "Library/Application Support/QuantMind/continuous-research/runtime.json",
    )
    args = parser.parse_args()
    client = Client(args.config)
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        client.cfg["engine_url"] + "/api/v1/continuous-research",
        headers={"Authorization": "Bearer " + client.cfg["access_token"]},
        timeout=30,
    )
    response.raise_for_status()
    state = next(p for p in response.json() if p["id"] == client.program)
    tasks = list(state["tasks"].values())
    experiments = [e for t in tasks for e in t["experiments"].values()]
    reports = [r for t in tasks for r in t["reports"]]
    usage = {
        key: sum(t["usage"].get(key, 0) for t in tasks)
        for key in ("input", "output", "unknown_calls", "calls")
    }
    snapshot = {
        "at": datetime.now(timezone.utc).isoformat(),
        "program_id": client.program,
        "runtime": state.get("runtime"),
        "status": state["status"],
        "desired": state["desired"],
        "heartbeat_stale": state["heartbeat_stale"],
        "quota": state["quota"],
        "counts": {
            "tasks": len(tasks),
            "task_status": dict(Counter(t["status"] for t in tasks)),
            "reports": len(reports),
            "experiment_references": len(experiments),
            "unique_backtests": len({e["backtest_id"] for e in experiments}),
            "strategy_ids": len(
                {e["strategy_id"] for e in experiments if e.get("strategy_id")}
            ),
            "factor_ids": len(
                {e["factor_id"] for e in experiments if e.get("factor_id")}
            ),
            "deferred_followups": sum(
                not f.get("task_id") for r in reports for f in r.get("followups", [])
            ),
        },
        "usage": usage,
        "usage_basis": "Cumulative reported input/output across windows; interrupted calls may be missing. Calls instrumented from 2026-09-27 morning only; task attempts are not model calls.",
        "blocked": [
            {"id": t["id"], "question": t["question"], "reason": t.get("last_error")}
            for t in tasks
            if t["status"] in ("blocked", "failed")
        ],
        "reports": [
            {
                "task_id": t["id"],
                "at": r["at"],
                "question": t["question"],
                "text": r["text"],
                "backtest_ids": [v["backtest_id"] for v in r["results"].values()],
            }
            for t in tasks
            for r in t["reports"]
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    earlier = sorted(args.output.glob("*-snapshot.json"))
    if earlier:
        previous = json.loads(earlier[-1].read_text())
        if previous.get("program_id") == client.program:
            snapshot["delta"] = {
                "since": previous["at"],
                "usage": {k: usage[k] - previous["usage"].get(k, 0) for k in usage},
                "reports": len(reports) - previous["counts"]["reports"],
                "unique_backtests": snapshot["counts"]["unique_backtests"]
                - previous["counts"]["unique_backtests"],
                "quota_window_changed": previous["quota"].get("reset_at")
                != state["quota"].get("reset_at"),
            }
    filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-snapshot.json")
    (args.output / filename).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in snapshot.items() if k not in ("reports", "blocked")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
