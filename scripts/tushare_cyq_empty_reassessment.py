#!/usr/bin/env python3
"""Reclassify retained exact cyq_chips supplier-empty responses offline."""

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

from backend.shared.tushare_intake import (  # noqa: E402
    assess_success_payload,
    digest,
    json_bytes,
    utc_now,
)
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402

API = "cyq_chips"


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _verified_bytes(path, expected_sha):
    path = _regular(path, "Retained artifact")
    body = path.read_bytes()
    if digest(body) != expected_sha:
        raise ValueError("Retained artifact checksum mismatch")
    return body


def reassess(pipeline, *, apply=False):
    """Promote only the narrow supplier-empty payload accepted by current intake."""
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    attempts_before = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
    results_before = db.execute(
        "SELECT count(*) FROM jobs WHERE result IS NOT NULL"
    ).fetchone()[0]
    promoted = 0
    unchanged = Counter()
    try:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT id,job,result FROM jobs INDEXED BY jobs_pending "
            "WHERE state='blocked' AND json_extract(job,'$.api_name')=? "
            "AND json_extract(result,'$.status')='api_error' "
            "AND json_extract(result,'$.code')=50101 ORDER BY rowid",
            (API,),
        ).fetchall()
        for row in rows:
            job, saved = json.loads(row["job"]), json.loads(row["result"])
            if (
                saved.get("response_complete") is not True
                or saved.get("response_format") != "json"
                or saved.get("http_status") != 200
                or "parquet" in saved
            ):
                unchanged["ineligible_response"] += 1
                continue
            sha = saved.get("object_sha256")
            observation = saved.get("observation")
            observation_sha = saved.get("observation_sha256")
            if (
                not isinstance(sha, str)
                or not re.fullmatch(r"[a-f0-9]{64}", sha)
                or not isinstance(observation, str)
                or not re.fullmatch(r"[a-f0-9]+\.json", observation)
                or not isinstance(observation_sha, str)
                or not re.fullmatch(r"[a-f0-9]{64}", observation_sha)
            ):
                raise ValueError("Blocked result has invalid artifact references")
            raw = _verified_bytes(pipeline.root / "objects" / f"{sha}.json", sha)
            _verified_bytes(
                pipeline.root / "observations" / observation, observation_sha
            )
            assessment = assess_success_payload(job, json.loads(raw))
            if not (
                assessment.get("status") == "empty_unverified"
                and assessment.get("row_count") == 0
                and assessment.get("supplier_empty_hint") is True
                and assessment.get("coverage_proven") is False
                and assessment.get("code") == 50101
            ):
                unchanged[assessment.get("status", "unknown")] += 1
                continue
            assessed_at = utc_now()
            marker = {
                "version": 1,
                "rule": "cyq_chips_exact_supplier_empty",
                "previous_status": saved["status"],
                "reassessed_status": "empty_unverified",
                "assessed_at": assessed_at,
                "source_attempt_preserved": True,
                "upstream_calls": 0,
            }
            updated = {**saved, **assessment, "response_reassessment": marker}
            encoded = json.dumps(updated, sort_keys=True)
            changed = db.execute(
                "UPDATE jobs SET state='empty',result=? WHERE id=? AND state='blocked'",
                (encoded, row["id"]),
            ).rowcount
            if changed != 1:
                raise ValueError("Supplier-empty job changed during reassessment")
            db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,"
                "checked_at=excluded.checked_at,reason=excluded.reason",
                (
                    "reassessment:" + row["id"],
                    "supplier_empty_reassessed",
                    assessed_at,
                    json.dumps(
                        {
                            "api_name": API,
                            "rule": marker["rule"],
                            "coverage_proven": False,
                            "source_attempt_preserved": True,
                            "upstream_calls": 0,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            promoted += 1
        if db.execute("SELECT count(*) FROM attempts").fetchone()[0] != attempts_before:
            raise ValueError(
                "Attempt ledger changed during supplier-empty reassessment"
            )
        if (
            db.execute("SELECT count(*) FROM jobs WHERE result IS NOT NULL").fetchone()[
                0
            ]
            != results_before
        ):
            raise ValueError("Result-bearing job count changed during reassessment")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "api_name": API,
            "candidate_jobs": len(rows),
            "promoted_jobs": promoted,
            "unchanged_jobs": sum(unchanged.values()),
            "unchanged_by_status": dict(sorted(unchanged.items())),
            "capability_evidence_rows": promoted,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "source_attempt_action": "unchanged",
            "artifact_action": "verified_unchanged",
            "coverage_proven": False,
            "upstream_calls": 0,
        }
        if apply:
            db.commit()
        else:
            db.rollback()
        return report
    except BaseException:
        db.rollback()
        raise


def _write_receipt(root, report):
    body = json_bytes(report) + b"\n"
    sha = hashlib.sha256(body).hexdigest()
    path = Path(root) / f"supplier-empty-reassessment-v1.{sha}.json"
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".supplier-empty-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
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
        report = reassess(pipeline, apply=args.apply)
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
