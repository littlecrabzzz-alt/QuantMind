#!/usr/bin/env python3
"""Read-only factor month migration preflight; deliberately no apply/rollback mode.

The current worker reads JSON config before its shared lock, and config replace
cannot commit atomically with SQLite. A locked preflight is safe; switching isn't.
"""

import argparse
from contextlib import closing
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import sysconfig
import tempfile
from urllib.parse import quote

STATES = ("history:factor_library", "recent:factor_library")
MAX_BYTES = 16 * 1024 * 1024


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid or oversized preflight input")
    return path.read_bytes()


def coverage(config, state):
    """A Cartesian code x interval proof, without replaying millions of old jobs."""
    from backend.shared.tushare_factor_library_contracts import (
        _starts,
        _stock_codes,
        iter_factor_library_jobs,
    )
    from backend.shared.tushare_market_contracts import _months
    from backend.shared.tushare_pipeline import _planning_inputs, _planning_snapshot

    snapshot = _planning_snapshot(state)
    if snapshot is None:
        raise ValueError("Legacy/unknown snapshot requires separate review")
    ids = snapshot["identifiers"]
    policy, filtered = _planning_inputs("factor_library", config, ids)
    if snapshot["policy"] != policy or filtered != ids:
        raise ValueError(
            "Current daily config does not match frozen policy/dependencies"
        )
    if (
        type(state["offset"]) is not int
        or state["offset"] < 0
        or state["done"] not in (0, 1)
    ):
        raise ValueError("Invalid old planning cursor")
    anchor = datetime.strptime(state["anchor"], "%Y%m%d").date()
    apis = config.get("factor_library_apis", ["factor_list", "factor_value"])
    start = _starts(config, apis)["factor_value"]
    if start is None or start > anchor:
        raise ValueError("Explicit existing factor history scope required")
    codes = _stock_codes(ids)
    if not codes:
        raise ValueError("Missing frozen actual stock discovery")
    recent = max(start, anchor - timedelta(days=6))
    prefix = (anchor - recent).days + 1
    prefix = prefix * len(codes) + int("factor_list" in apis)
    end = anchor - timedelta(days=7)
    windows = []
    cursor = start
    for first, last in _months(start, end):
        if len(windows) >= 12000:
            raise ValueError("Month-proof bound exceeded; no partial certificate")
        if first != cursor or last < first:
            raise ValueError("Month partition discontinuity")
        windows.append(
            {
                "start_date": first.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
            }
        )
        cursor = last + timedelta(days=1)
    historical_days = max(0, (end - start).days + 1)
    if (
        sum(
            (
                datetime.strptime(w["end_date"], "%Y%m%d")
                - datetime.strptime(w["start_date"], "%Y%m%d")
            ).days
            + 1
            for w in windows
        )
        != historical_days
    ):
        raise ValueError("Month proof does not cover full old scope")
    # Check the installed pure planner on one representative actual code. The
    # reviewed planner's only remaining dimension is the frozen code product.
    sample_config = {
        **config,
        "factor_library_apis": ["factor_value"],
        "factor_library_history_window": "month",
    }
    planned = [
        j["params"]
        for j in iter_factor_library_jobs(
            sample_config, anchor, {"factor_library_stocks": codes[:1]}
        )
        if j["epoch"] == "history"
    ]
    if planned != [{**window, "ts_code": codes[0]} for window in windows]:
        raise ValueError("Installed month planner differs from interval proof")
    is_history = state["name"].startswith("history:")
    total = prefix + historical_days * len(codes) if is_history else prefix
    if state["offset"] > total or (state["done"] and state["offset"] != total):
        raise ValueError("Old absolute cursor outside verified daily stream")
    consumed = max(0, state["offset"] - prefix) if is_history else 0
    complete_days, partial_codes = divmod(consumed, len(codes))
    next_day = start + timedelta(days=complete_days)
    return {
        "anchor": state["anchor"],
        "scope_start": start.strftime("%Y%m%d"),
        "historical_end": end.strftime("%Y%m%d") if historical_days else None,
        "frozen_codes": codes,
        "frozen_codes_sha256": sha(encoded(codes)),
        "recent_source_prefix": prefix,
        "old_source_offset": state["offset"],
        "daily_history_requests": historical_days * len(codes),
        "month_history_requests": len(windows) * len(codes),
        "month_windows": windows,
        "all_days_once_per_frozen_code": True,
        "consumed_history_source_items": consumed,
        "unplanned_daily_history_items": historical_days * len(codes) - consumed
        if is_history
        else None,
        "next_unplanned_daily_date": next_day.strftime("%Y%m%d")
        if is_history and next_day <= end
        else None,
        "next_date_already_enumerated_codes": codes[:partial_codes]
        if is_history
        else [],
        "proof_scope": "Logical request range only, includes unenumerated old daily tail; no acquired-data/PIT certificate",
    }


def prepare(root, expected=None):
    """Read two canonical checkpoints under the existing lock, never create DB/state."""
    from backend.shared import tushare_factor_library_contracts as contracts
    from backend.shared import tushare_pipeline as pipeline

    root = Path(root).absolute()
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("Real existing root required")
    for name in ("pipeline.lock", "pipeline-config.json", "pipeline.sqlite"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Existing regular lock/config/database required")
    with (root / "pipeline.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config_bytes = read(root / "pipeline-config.json")
        config = json.loads(config_bytes)
        if not config.get("enable_factor_library") or "factor_value" not in config.get(
            "factor_library_apis", ["factor_list", "factor_value"]
        ):
            raise ValueError("Existing enabled factor_value required")
        if (
            config.get("factor_library_value_mode", "factor_name") != "code_only"
            or config.get("factor_library_history_window", "daily") != "daily"
        ):
            raise ValueError("Only existing code_only daily state is eligible")
        uri = "file:" + quote(str(root / "pipeline.sqlite"), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Expected schema6; no migration is performed")
            states = {
                name: db.execute(
                    "SELECT * FROM planning_state WHERE name=?", (name,)
                ).fetchone()
                for name in STATES
            }
            if any(row is None for row in states.values()):
                raise ValueError("Both frozen history/recent checkpoints are required")
            states = {name: dict(row) for name, row in states.items()}
            proof = {name: coverage(config, row) for name, row in states.items()}
            month_config = {**config, "factor_library_history_window": "month"}
            candidate = {}
            for name, state in states.items():
                snapshot = json.loads(state["signature"])
                new_policy, _ = pipeline._planning_inputs(
                    "factor_library", month_config, snapshot["identifiers"]
                )
                if new_policy == snapshot["policy"]:
                    raise ValueError("Monthly policy support is not installed")
                snapshot["policy"] = new_policy
                candidate[name] = {
                    **state,
                    "signature": pipeline.json_bytes(snapshot).decode(),
                }
                if name.startswith("history:"):
                    candidate[name].update(offset=0, done=0)
            if read(root / "pipeline-config.json") != config_bytes:
                raise ValueError("Config changed during locked preflight")
        result = {
            "schema_version": 1,
            "status": "plan_only_atomic_switch_unavailable",
            "apply_allowed": False,
            "root": str(root),
            "config_sha256": sha(config_bytes),
            "preimage_states": states,
            "preimage_states_sha256": sha(encoded(states)),
            "source_sha256": {
                "factor_contracts": sha(Path(contracts.__file__).read_bytes()),
                "pipeline": sha(Path(pipeline.__file__).read_bytes()),
            },
            "proposed_config_delta": {"factor_library_history_window": "month"},
            "candidate_states_not_applied": candidate,
            "coverage": proof,
            "old_jobs_action": "continue_unchanged",
            "deferred_jobs": 0,
            "upstream_calls": 0,
            "authority_writes": 0,
            "rollback_action": "none_required_no_mutation; never restore an old database over new progress",
            "blocking_reasons": [
                "config_file_and_sqlite_have_no_shared_atomic_commit",
                "tick_reads_config_before_pipeline_lock",
            ],
        }
        if expected is not None and result != expected:
            raise ValueError(
                "Preimage/config/runtime drift; revalidation refused without mutation"
            )
        return result


def save_immutable(path, value):
    """Atomic audit file only; a crash cannot install partial evidence or alter authority."""
    path = Path(path)
    raw = encoded(value) + b"\n"
    if path.exists() or path.is_symlink():
        if read(path) != raw:
            raise ValueError("Existing audit differs; never overwrite evidence")
        return
    fd, temporary = tempfile.mkstemp(prefix=".factor-month-audit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if read(path) != raw:
                raise ValueError("Concurrent audit differs") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revalidate", type=Path)
    parser.add_argument("--expected-audit-sha256")
    args = parser.parse_args()
    if bool(args.revalidate) != bool(args.expected_audit_sha256):
        parser.error("Revalidation requires both audit path and expected SHA")
    if (
        args.output.resolve().is_relative_to(args.root.resolve())
        or args.output.is_symlink()
    ):
        parser.error("Audit output must be outside the authority root")
    sys.path[:0] = [
        str(Path(__file__).resolve().parents[1]),
        str(
            Path(sys.executable).absolute().parent.parent
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        ),
        sysconfig.get_paths()["purelib"],
    ]
    import signal
    from unittest.mock import patch

    def expired(signum, frame):
        raise TimeoutError("Bounded30second preflight")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 30)
    expected = None
    try:
        if args.revalidate:
            body = read(args.revalidate)
            if sha(body) != args.expected_audit_sha256:
                raise ValueError("Expected audit checksum mismatch")
            expected = json.loads(body)
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No network")),
            patch(
                "backend.shared.runtime_secrets.get_secret",
                side_effect=AssertionError("No credentials"),
            ),
            patch(
                "backend.shared.tushare_pipeline.get_secret",
                side_effect=AssertionError("No credentials"),
            ),
        ):
            result = prepare(args.root, expected)
        save_immutable(args.output, result)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    print(
        json.dumps(
            {
                "status": result["status"],
                "audit": str(args.output),
                "audit_sha256": sha(read(args.output)),
                "apply_allowed": False,
                "authority_writes": 0,
                "upstream_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
