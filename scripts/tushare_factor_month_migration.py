#!/usr/bin/env python3
"""Reviewed plan/execute/recover factor-month transition; no source calls or job edits."""

import argparse
from contextlib import closing
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import sysconfig
import tempfile
from urllib.parse import quote

STATES = ("history:factor_library", "recent:factor_library")
MAX_BYTES = 16 * 1024 * 1024
PENDING = "factor-month-migration.pending.json"


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
    root = Path(root).absolute()
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("Real existing root required")
    for name in ("pipeline.lock", "pipeline-config.json", "pipeline.sqlite"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Existing regular lock/config/database required")
    with (root / "pipeline.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / PENDING).exists() or (root / PENDING).is_symlink():
            raise ValueError("Pending migration requires recover")
        return _snapshot_locked(root, expected)


def _snapshot_locked(root, expected=None):
    from backend.shared import tushare_factor_library_contracts as contracts
    from backend.shared import tushare_pipeline as pipeline

    if PENDING not in pipeline.tick.__code__.co_consts:
        raise ValueError("Pending-gated tick protocol is not installed")
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
        "schema_version": 2,
        "status": "prepared_month_transition",
        "apply_allowed": True,
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
        "blocking_reasons": [],
        "required_protocol": "locked_config_read_and_durable_pending_gate_v1",
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
    _sync_dir(path.parent)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _checkpoint(stage):
    """Named fault-injection boundaries; no production side effect."""


def _safe_config(config):
    # This queue config is nonsecret. Fail closed on credential-like keys/values
    # before creating a journal; never redact a config required for exact recovery.
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if re.search(
                    r"token|secret|password|credential|authorization|api.?key",
                    key,
                    re.I,
                ):
                    raise ValueError(
                        "Credential-like configuration must not enter journal"
                    )
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and (
            len(value) > 200
            or re.search(r"bearer |-----BEGIN|https?://[^ /]+:[^ /]+@", value, re.I)
        ):
            raise ValueError(
                "Credential-like configuration value must not enter journal"
            )

    visit(config)


def _replace_config(path, body):
    fd, name = tempfile.mkstemp(prefix=".factor-month-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _validate_journal(journal, audit, audit_sha, helper_sha, root):
    if set(journal) != {
        "version",
        "root",
        "audit",
        "audit_sha256",
        "helper_sha256",
        "old_config_utf8",
        "new_config_utf8",
        "old_states",
        "new_states",
    }:
        raise ValueError("Unknown journal fields")
    if (
        journal.get("version") != 1
        or journal.get("audit") != audit
        or journal.get("audit_sha256") != audit_sha
        or journal.get("helper_sha256") != helper_sha
        or journal.get("root") != str(root)
    ):
        raise ValueError("Journal does not match reviewed audit/helper/root")
    old = journal["old_config_utf8"].encode()
    new = journal["new_config_utf8"].encode()
    if sha(old) != audit["config_sha256"] or json.loads(new) != {
        **json.loads(old),
        **audit["proposed_config_delta"],
    }:
        raise ValueError("Journal config provenance mismatch")
    _safe_config(json.loads(old))
    _safe_config(json.loads(new))
    if (
        journal["old_states"] != audit["preimage_states"]
        or journal["new_states"] != audit["candidate_states_not_applied"]
    ):
        raise ValueError("Journal state provenance mismatch")
    return old, new


def _require_authority(root):
    from backend.shared import tushare_pipeline as pipeline

    pipeline.authority()
    if root != root.resolve() or root != pipeline.ROOT or root != Path("/data/tushare"):
        raise ValueError("Verified existing cloud authority root required")


def transition(root, audit_path, audit_sha, helper_sha, mode):
    """Explicit authority transition: journal first; recovery accepts exact old/new only."""
    from backend.shared import tushare_pipeline as pipeline
    from backend.shared import tushare_factor_library_contracts as contracts

    if mode not in ("execute", "recover"):
        raise ValueError("Explicit execute or recover required")
    root = Path(root).absolute()
    _require_authority(root)
    if sha(Path(__file__).read_bytes()) != helper_sha:
        raise ValueError("Reviewed helper SHA mismatch")
    audit_body = read(audit_path)
    if sha(audit_body) != audit_sha:
        raise ValueError("Reviewed audit SHA mismatch")
    audit = json.loads(audit_body)
    if (
        audit.get("schema_version") != 2
        or audit.get("required_protocol")
        != "locked_config_read_and_durable_pending_gate_v1"
        or not audit.get("apply_allowed")
        or audit.get("root") != str(root)
    ):
        raise ValueError("Fresh protocol2 audit required")
    if PENDING not in pipeline.tick.__code__.co_consts:
        raise ValueError("Pending-gated tick protocol is not installed")
    sources = {
        "factor_contracts": sha(Path(contracts.__file__).read_bytes()),
        "pipeline": sha(Path(pipeline.__file__).read_bytes()),
    }
    if sources != audit["source_sha256"]:
        raise ValueError(
            "Reviewed source SHA mismatch; do not upgrade during pending migration"
        )
    for name in ("pipeline.lock", "pipeline.sqlite", "pipeline-config.json"):
        if (root / name).is_symlink() or not (root / name).is_file():
            raise ValueError("Existing regular authority files required")
    pending = root / PENDING
    receipt = root / ("factor-month-migration." + audit_sha + ".completed.json")
    with (root / "pipeline.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if receipt.exists() or receipt.is_symlink():
            journal = json.loads(read(receipt))
            _validate_journal(journal, audit, audit_sha, helper_sha, root)
            if pending.exists() or pending.is_symlink():
                raise ValueError("Unexpected pending journal with completed receipt")
            _sync_dir(root)
            return {
                "status": "already_completed_no_changes",
                "receipt": str(receipt),
                "upstream_calls": 0,
            }
        if pending.exists() or pending.is_symlink():
            if mode != "recover":
                raise ValueError("Pending migration requires explicit recover")
            journal = json.loads(read(pending))
        else:
            if mode != "execute":
                raise ValueError("No pending migration to recover")
            _snapshot_locked(root, audit)
            old = read(root / "pipeline-config.json")
            config = json.loads(old)
            _safe_config(config)
            new = encoded({**config, **audit["proposed_config_delta"]}) + b"\n"
            journal = {
                "version": 1,
                "root": str(root),
                "audit": audit,
                "audit_sha256": audit_sha,
                "helper_sha256": helper_sha,
                "old_config_utf8": old.decode(),
                "new_config_utf8": new.decode(),
                "old_states": audit["preimage_states"],
                "new_states": audit["candidate_states_not_applied"],
            }
            _checkpoint("before_journal")
            save_immutable(pending, journal)
            _checkpoint("after_journal")
        old, new = _validate_journal(journal, audit, audit_sha, helper_sha, root)
        _sync_dir(root)  # Also durable after an interrupted initial journal install.
        config_path = root / "pipeline-config.json"
        uri = "file:" + quote(str(root / "pipeline.sqlite"), safe="/") + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Expected schema6; no migration")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            states = {
                name: db.execute(
                    "SELECT * FROM planning_state WHERE name=?", (name,)
                ).fetchone()
                for name in STATES
            }
            states = {
                name: dict(row) if row is not None else None
                for name, row in states.items()
            }
            current = read(config_path)
            if current not in (old, new) or states not in (
                journal["old_states"],
                journal["new_states"],
            ):
                raise ValueError("Pending config/state drift; no recovery mutation")
            if current == old:
                _replace_config(config_path, new)
            _checkpoint("after_config")
            if states == journal["old_states"]:
                for name in STATES:
                    row = journal["new_states"][name]
                    db.execute(
                        "UPDATE planning_state SET anchor=?,signature=?,offset=?,done=? WHERE name=?",
                        (
                            row["anchor"],
                            row["signature"],
                            row["offset"],
                            row["done"],
                            name,
                        ),
                    )
                    if name == STATES[0]:
                        _checkpoint("after_first_state")
            _checkpoint("before_sql_commit")
            db.commit()
            _checkpoint("after_sql_commit")
        _checkpoint("before_receipt_rename")
        # Same directory/FS: removing pending and installing the immutable receipt
        # is one namespace operation, after durable config + FULL SQLite commit.
        os.rename(pending, receipt)
        _checkpoint("after_receipt_rename")
        _sync_dir(root)
        _checkpoint("after_receipt_fsync")
        return {
            "status": "completed",
            "receipt": str(receipt),
            "audit_sha256": audit_sha,
            "upstream_calls": 0,
            "old_jobs_action": "continue_unchanged",
            "deferred_jobs": 0,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revalidate", type=Path)
    parser.add_argument("--expected-audit-sha256")
    parser.add_argument(
        "--mode", choices=("plan", "execute", "recover"), default="plan"
    )
    parser.add_argument("--helper-sha256")
    args = parser.parse_args()
    if args.mode != "plan" and (
        not args.revalidate or not args.expected_audit_sha256 or not args.helper_sha256
    ):
        parser.error(
            "Execute/recover require reviewed audit path, audit SHA and helper SHA"
        )
    if bool(args.revalidate) != bool(args.expected_audit_sha256):
        parser.error("Revalidation requires both audit path and expected SHA")
    if (
        args.output.resolve().is_relative_to(args.root.resolve())
        or args.output.is_symlink()
    ):
        parser.error("Audit output must be outside the authority root")
    if args.mode != "plan" and args.output.resolve() == args.revalidate.resolve():
        parser.error("Execution output must differ from the immutable reviewed audit")
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
            result = (
                prepare(args.root, expected)
                if args.mode == "plan"
                else transition(
                    args.root,
                    args.revalidate,
                    args.expected_audit_sha256,
                    args.helper_sha256,
                    args.mode,
                )
            )
        saved = (
            result
            if args.mode == "plan"
            else {
                "status": "completed_receipt",
                "receipt": result["receipt"],
                "audit_sha256": args.expected_audit_sha256,
                "upstream_calls": 0,
            }
        )
        save_immutable(args.output, saved)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    print(
        json.dumps(
            {
                "status": result["status"],
                "audit": str(args.output),
                "audit_sha256": sha(read(args.output)),
                "apply_allowed": result.get("apply_allowed", False),
                "read_only": args.mode == "plan",
                "mode": args.mode,
                "upstream_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
