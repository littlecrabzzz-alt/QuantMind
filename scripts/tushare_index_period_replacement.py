#!/usr/bin/env python3
"""Retire one unlinked legacy index_weekly parent after period-plan proof."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_pipeline import (  # noqa: E402
    INDEX_PERIOD_REPLACEMENT_GAP,
    Pipeline,
)

API = "index_weekly"
GAP = INDEX_PERIOD_REPLACEMENT_GAP
USABLE_REPLACEMENT_STATES = {
    "pending",
    "split_pending",
    "done",
    "empty",
    "quality",
    "resolved",
}


def _encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _validate_date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"Invalid {label}")


def retire(
    pipeline,
    parent_id,
    replacement_epoch,
    trade_date,
    expected_jobs,
    *,
    apply=False,
):
    """Mark a legacy parent blocked while preserving its supplier evidence."""
    if not isinstance(expected_jobs, int) or isinstance(expected_jobs, bool):
        raise ValueError("Expected replacement count must be an integer")
    if expected_jobs < 1:
        raise ValueError("Expected replacement count must be positive")
    _validate_date(trade_date, "trade date")
    if not isinstance(replacement_epoch, str) or not replacement_epoch:
        raise ValueError("Replacement epoch is required")
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    parent = db.execute("SELECT * FROM jobs WHERE id=?", (parent_id,)).fetchone()
    if parent is None:
        raise ValueError("Legacy parent not found")
    job = json.loads(parent["job"])
    result = json.loads(parent["result"] or "{}")
    if (
        parent["state"] not in ("split_pending", "blocked")
        or job.get("api_name") != API
        or job.get("params") != {"trade_date": trade_date}
        or result.get("api_name") != API
        or result.get("status") != "possibly_truncated"
        or result.get("row_count") != job.get("row_cap")
        or result.get("split", {}).get("method") != "identifier_fanout"
        or result.get("split", {}).get("universe_complete") is not False
    ):
        raise ValueError("Legacy parent evidence does not match the reviewed shape")
    split = db.execute(
        "SELECT * FROM partition_splits WHERE parent_id=?", (parent_id,)
    ).fetchone()
    if (
        split is None
        or split["method"] != "identifier_fanout"
        or split["expected_children"] != 0
        or split["coverage_proven"] != 0
        or json.loads(split["evidence"]).get("origin") != "legacy_unverified"
        or db.execute(
            "SELECT 1 FROM partition_children WHERE parent_id=?", (parent_id,)
        ).fetchone()
    ):
        raise ValueError("Legacy split is not the reviewed zero-child marker")

    replacements = db.execute(
        "SELECT id,state,job FROM jobs INDEXED BY jobs_partition_lookup "
        "WHERE epoch=? AND json_extract(job,'$.api_name')=? "
        "AND json_extract(job,'$.params.start_date')<=? "
        "AND json_extract(job,'$.params.end_date')>=?",
        (replacement_epoch, API, trade_date, trade_date),
    ).fetchall()
    codes = set()
    states = Counter()
    parent_contract = {key: value for key, value in job.items() if key != "params"}
    for replacement in replacements:
        replacement_job = json.loads(replacement["job"])
        params = replacement_job.get("params")
        if (
            not isinstance(params, dict)
            or set(params) != {"ts_code", "start_date", "end_date"}
            or not isinstance(params["ts_code"], str)
            or {key: value for key, value in replacement_job.items() if key != "params"}
            != parent_contract
            or replacement["state"] not in USABLE_REPLACEMENT_STATES
        ):
            raise ValueError("Replacement job does not match the reviewed contract")
        codes.add(params["ts_code"])
        states[replacement["state"]] += 1
    if len(replacements) != expected_jobs or len(codes) != expected_jobs:
        raise ValueError(
            f"Expected {expected_jobs} unique replacement jobs, found "
            f"{len(replacements)} jobs and {len(codes)} codes"
        )
    replacement_ids = [row["id"] for row in replacements]
    placeholders = ",".join("?" for _ in replacement_ids)
    linked = db.execute(
        f"SELECT count(*) FROM partition_children WHERE child_id IN ({placeholders})",
        replacement_ids,
    ).fetchone()[0]
    if linked:
        raise ValueError("Replacement period jobs must be independent roots")

    attempts_before = db.execute(
        "SELECT count(*) FROM attempts WHERE job_id=?", (parent_id,)
    ).fetchone()[0]
    parent_before = (parent["state"], parent["tries"], parent["result"])
    evidence = json.loads(split["evidence"])
    marker = evidence.get("replacement_gap")
    if marker not in (None, GAP):
        raise ValueError("Conflicting replacement marker")
    needs_update = (
        parent["state"] != "blocked"
        or split["status"] != "blocked"
        or split["gap"] != GAP
        or marker != GAP
    )
    try:
        db.execute("BEGIN IMMEDIATE")
        if needs_update:
            evidence.update(
                {
                    "replacement_gap": GAP,
                    "replacement_epoch": replacement_epoch,
                    "replacement_jobs": expected_jobs,
                    "trade_date": trade_date,
                }
            )
            db.execute("UPDATE jobs SET state='blocked' WHERE id=?", (parent_id,))
            db.execute(
                "UPDATE partition_splits SET evidence=?,status='blocked',gap=? "
                "WHERE parent_id=?",
                (json.dumps(evidence, sort_keys=True), GAP, parent_id),
            )
        after = db.execute(
            "SELECT state,tries,result FROM jobs WHERE id=?", (parent_id,)
        ).fetchone()
        if (after["tries"], after["result"]) != parent_before[1:]:
            raise ValueError("Legacy supplier evidence changed")
        attempts_after = db.execute(
            "SELECT count(*) FROM attempts WHERE job_id=?", (parent_id,)
        ).fetchone()[0]
        if attempts_after != attempts_before:
            raise ValueError("Legacy attempt ledger changed")
        if apply:
            db.commit()
        else:
            db.rollback()
    except BaseException:
        db.rollback()
        raise
    return {
        "status": "applied" if apply and needs_update else "no_action" if apply else "planned_rollback",
        "schema_version": 1,
        "parent_id": parent_id,
        "trade_date": trade_date,
        "replacement_epoch": replacement_epoch,
        "replacement_jobs": len(replacements),
        "replacement_codes": len(codes),
        "replacement_states": dict(sorted(states.items())),
        "replacement_data_complete": not (
            set(states) - {"done", "empty", "resolved"}
        ),
        "legacy_result_preserved": parent["result"] is not None,
        "legacy_attempts_preserved": attempts_before,
        "coverage_proven": False,
        "upstream_calls": 0,
    }


def _write_receipt(root, report):
    body = _encoded(report) + b"\n"
    name = "index-period-replacement-v1." + _sha(body) + ".json"
    path = Path(root) / name
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".index-period-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--parent-id", required=True)
    parser.add_argument("--replacement-epoch", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--expected-jobs", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = json.loads(_regular(args.catalog, "Catalog").read_bytes())
    for name in ("pipeline.sqlite", "pipeline.lock", ".archive-worker.lock"):
        _regular(root / name, name)
    with ExitStack() as stack:
        for name in (".archive-worker.lock", "pipeline.lock"):
            handle = stack.enter_context((root / name).open("rb"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pipeline = Pipeline(root, catalog)
        stack.callback(pipeline.close)
        report = retire(
            pipeline,
            args.parent_id,
            args.replacement_epoch,
            args.trade_date,
            args.expected_jobs,
            apply=args.apply,
        )
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
