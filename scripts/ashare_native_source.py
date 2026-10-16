#!/usr/bin/env python3
"""Finite daily recipe for the existing Mac Tushare Pipeline, not another collector.

Every invocation runs only this recipe's durable task IDs. Launchd supplies a
15-minute/wake trigger; real SSE calendar and Asia/Shanghai determine closed
sessions. No service control, global whitelist/config edits or history planner.
"""
from __future__ import annotations

from collections import Counter
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from ashare_input_supplements import (ETFS, dump, execute, prepare_plan, raw_rows,
                                      sha, source_refs, utc_now)


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def configure(args):
    args.root = args.root.resolve()
    args.client = args.client.resolve()
    args.artifact_root = args.artifact_root.resolve()
    os.environ["QM_NODE_ROLE"] = "archive"
    os.environ["QM_TUSHARE_ARCHIVE_ROOT"] = str(args.root)
    os.environ["QM_RUNTIME_ENV_FILE"] = str(args.client / "config/archive.env")
    sys.path.insert(0, str(args.client))



def finish_export(args, state, state_path, now, supplier_requests=0):
    """Resume only derivation after source publication; no enqueue/run path here."""
    phase = state["export_operation"]
    operation = (args.artifact_root / phase["path"]).resolve()
    if not operation.is_relative_to(args.artifact_root / "ashare-input-supplements"):
        raise ValueError("Export phase escaped immutable artifact subtree")
    evidence_path = operation / "asset-evidence.json"
    from ashare_export_supplement_inputs import current_bundle, export
    export(SimpleNamespace(root=args.root, artifact_root=args.artifact_root,
                           operation=operation, end=phase["window"]["end"]))
    # Only the canonical publication commits the cursor, never epoch fallback.
    evidence = json.loads(evidence_path.read_bytes())
    pointer, _ = current_bundle(args.artifact_root, args.root)
    if evidence["data_identity"] != pointer["data_identity"]:
        raise ValueError("Export phase is not the current canonical source")
    state["canonical_bundle"] = pointer
    outcomes = json.loads((operation / "native-outcomes.json").read_bytes())
    unresolved = [item for item in outcomes["outcomes"] if item["state"] in ("pending", "split_pending")]
    failed = [item for item in outcomes["outcomes"] if item["state"] in ("blocked", "permission_blocked", "quality")]
    if not unresolved:
        state["pending_scope"] = None
        if not phase["calendar_only"]:
            state["last_published_end"] = phase["window"]["end"]
    if phase["calendar_only"]:
        state["calendar_attempt_day"] = now.strftime("%Y%m%d")
    state["last_operation"] = phase["path"]
    state["export_operation"] = None
    atomic(state_path, state)
    missing_calendar = phase["calendar_only"] and not any(
        row.get("exchange") == "SSE" and int(row.get("is_open", 0)) == 1
        and str(row["cal_date"]) > now.strftime("%Y%m%d")
        for row in raw_rows(args.root, state["calendar_refs"]))
    audit = {"wall_clock_utc": utc_now(), "wall_clock_shanghai": now.isoformat(),
             "state": "blocked" if failed else "pending" if unresolved or missing_calendar else "published_evidence",
             "operation": phase["path"], "source_operation_requests": outcomes["requests"],
             "supplier_requests_this_invocation": supplier_requests,
             "unresolved_task_ids": [item["task_id"] for item in unresolved],
             "blocked_task_ids": [item["task_id"] for item in failed],
             "asset_blockers": evidence["errors"],
             "reason": "Asset manifest committed; actual account readiness remains the sole QA decision"}
    atomic(state_path.parent / "last-tick.json", audit)
    print(json.dumps(audit))
    return 1 if failed else 75 if unresolved or missing_calendar else 0


def tick(args):
    configure(args)
    state_path = args.root / "maintenance/ashare-native-source/state.json"
    state = json.loads(state_path.read_bytes()) if state_path.exists() else None
    # An explicitly checkpointed publisher can finish its own canonical commit.
    if state and state.get("export_operation"):
        return finish_export(args, state, state_path, datetime.now(ZoneInfo("Asia/Shanghai")))
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    from ashare_export_supplement_inputs import current_bundle
    try:
        pointer, _ = current_bundle(args.artifact_root, args.root)
        if state is None:
            raise ValueError("Native recipe checkpoint missing; no automatic epoch reconstruction")
        required = {"last_published_end", "calendar_refs", "committed_refs",
                    "pending_scope", "export_operation"}
        if state["schema_version"] != 1 or not required.issubset(state):
            raise ValueError("Unsupported native recipe checkpoint")
        state["canonical_bundle"] = pointer
        atomic(state_path, state)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        audit = {"wall_clock_utc": utc_now(), "wall_clock_shanghai": now.isoformat(),
                 "state": "pending", "supplier_requests_this_invocation": 0,
                 "reason": f"Canonical source unavailable: {type(exc).__name__}: {exc}"}
        atomic(state_path.parent / "last-tick.json", audit)
        print(json.dumps(audit))
        return 75
    audit = {"wall_clock_utc": utc_now(), "wall_clock_shanghai": now.isoformat(),
             "last_published_end": state["last_published_end"]}
    calendar = raw_rows(args.root, state["calendar_refs"])
    # No weekday fallback: sessions come exclusively from observed supplier rows.
    eligible = sorted({str(row["cal_date"]) for row in calendar
                       if row.get("exchange") == "SSE" and int(row.get("is_open", 0)) == 1
                       and (str(row["cal_date"]) < now.strftime("%Y%m%d") or
                            str(row["cal_date"]) == now.strftime("%Y%m%d") and now.hour >= 15)})
    pending = state.get("pending_scope")
    due = [day for day in eligible if day > state["last_published_end"]]
    future_known = any(row.get("exchange") == "SSE" and int(row.get("is_open", 0)) == 1
                       and str(row["cal_date"]) > now.strftime("%Y%m%d") for row in calendar)
    calendar_only = bool(pending.get("calendar_only")) if pending else not due and not future_known
    if not pending and not due and (future_known or state.get("calendar_attempt_day") == now.strftime("%Y%m%d")):
        audit.update(state="not_due" if future_known else "pending",
                     reason="No new observed closed SSE session" if future_known else
                            "Future exchange calendar unconfirmed; native recheck next Shanghai date")
        atomic(state_path.parent / "last-tick.json", audit)
        print(json.dumps(audit))
        return 0 if future_known else 75
    current = json.loads((args.root / "CURRENT.json").read_bytes())
    index = state.get("source_index")
    if index and index["source"] == current:
        cached = (args.artifact_root / index["path"]).resolve()
        if not cached.is_relative_to(args.artifact_root / "ashare-input-supplements") or sha(cached) != index["sha256"]:
            raise ValueError("Immutable source-index cache identity mismatch")
        refs = json.loads(cached.read_bytes())
    else:
        current, refs = source_refs(args.root, "CURRENT.json")
    for api, committed in state["committed_refs"].items():
        refs[api] = list({item["path"]: item for item in [*refs.get(api, []), *committed]}.values())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    operation = args.artifact_root / "ashare-input-supplements" / stamp
    operation.mkdir(parents=True, exist_ok=False)
    # At most seven real sessions per invocation keeps catch-up finite as well.
    window = pending["window"] if pending else (
        {"start": state["last_published_end"], "end": state["last_published_end"]} if calendar_only else {
            "start": (datetime.strptime(state["last_published_end"], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d"),
            "end": due[min(6, len(due) - 1)]})
    native_args = SimpleNamespace(root=args.root, client=args.client,
        artifact_root=args.artifact_root, out=operation, start=window["start"], end=window["end"])
    plan = prepare_plan(native_args, current, refs)
    if pending:
        plan["jobs"], plan["epoch"] = pending["jobs"], pending["epoch"]
    elif calendar_only:
        plan["jobs"] = [{"api": "trade_cal", "params": {
            "exchange": "SSE", "start_date": now.strftime("%Y%m%d"),
            "end_date": f"{now.year + 1}1231"}}]
        plan["epoch"] = "ashare-calendar-" + now.strftime("%Y%m%d")
    else:
        for code in ETFS:
            for api in ("fund_daily", "fund_adj"):
                params = {"ts_code": code, "start_date": window["start"], "end_date": window["end"]}
                if api == "fund_adj":
                    # Existing native expand() uses this reviewed paging shape.
                    params.update(offset=0, limit=1000)
                plan["jobs"].append({"api": api, "params": params})
        plan["epoch"] = stamp
    plan["scope_counts"] = dict(Counter(job["api"] for job in plan["jobs"]))
    if len(plan["jobs"]) > 128:
        raise ValueError("Bounded daily task inventory exceeds 128")
    dump(operation / "plan.json", plan)
    dump(operation / "source-refs.json", refs)
    state["source_index"] = {"source": current,
        "path": str((operation / "source-refs.json").relative_to(args.artifact_root)),
        "sha256": sha(operation / "source-refs.json")}
    state["pending_scope"] = {"window": plan["window"], "jobs": plan["jobs"],
                              "epoch": plan["epoch"], "calendar_only": calendar_only}
    atomic(state_path, state)
    try:
        added = execute(native_args, plan)
    except BlockingIOError:
        audit.update(state="pending", reason="Native pipeline.lock busy; no lock bypass or service restart")
        dump(operation / "blocked.json", audit)
        atomic(state_path.parent / "last-tick.json", audit)
        print(json.dumps(audit))
        return 75
    dump(operation / "new-source-refs.json", added)
    for api, items in added.items():
        prior = state["committed_refs"].get(api, [])
        state["committed_refs"][api] = list({item["path"]: item for item in [*prior, *items]}.values())
    outcomes = json.loads((operation / "native-outcomes.json").read_bytes())
    if added.get("trade_cal"):
        state["calendar_refs"] = added["trade_cal"]
    state["export_operation"] = {"path": str(operation.relative_to(args.artifact_root)),
                                 "window": window, "calendar_only": calendar_only}
    atomic(state_path, state)
    return finish_export(args, state, state_path, now, supplier_requests=outcomes["requests"])


def launchd(args):
    # Render only; the unique deployment owner installs/bootstraps this template.
    script = Path(__file__).resolve()
    command = [str(args.client / ".venv/bin/python"), str(script), "tick",
               "--root", str(args.root), "--client", str(args.client),
               "--artifact-root", str(args.artifact_root)]
    payload = {"Label": "com.quantmind.ashare-native-source", "ProgramArguments": command,
               "StartInterval": 900, "RunAtLoad": True, "WorkingDirectory": str(script.parents[1]),
               "StandardOutPath": str(args.root / "maintenance/ashare-native-source/launchd.stdout.log"),
               "StandardErrorPath": str(args.root / "maintenance/ashare-native-source/launchd.stderr.log")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as stream:
        plistlib.dump(payload, stream)
    print(json.dumps({"rendered": str(args.out), "installed": False, "started": False,
                      "timezone": "Asia/Shanghai internally; host timezone unchanged"}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("tick", "render-launchd"):
        sub = commands.add_parser(name)
        sub.add_argument("--root", type=Path, required=True)
        sub.add_argument("--client", type=Path, required=True)
        sub.add_argument("--artifact-root", type=Path, required=True)
        if name == "render-launchd":
            sub.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return tick(args) if args.command == "tick" else launchd(args)


if __name__ == "__main__":
    raise SystemExit(main())
