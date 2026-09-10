#!/usr/bin/env python3
"""Verify an RRG acquisition batch and explicitly enqueue one bounded shard."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import prepare_tushare_rrg_acquisition_batch as preparation  # noqa: E402

MAX_SHARD_JOBS = 1000
JOB_FIELDS = {
    "task_id",
    "logical_key",
    "epoch",
    "priority",
    "group_name",
    "api_name",
    "params",
    "job",
    "source_plan_line",
}


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(label + " must be a regular file")
    return path


def _read_jobs(path):
    rows = []
    with _regular(path, "Shard").open() as source:
        for line in source:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid shard JSONL") from exc
            if not isinstance(row, dict) or set(row) != JOB_FIELDS:
                raise ValueError("Invalid shard job shape")
            if (
                not isinstance(row["job"], dict)
                or row["job"].get("api_name") != row["api_name"]
                or row["job"].get("params") != row["params"]
                or not isinstance(row["source_plan_line"], int)
                or row["source_plan_line"] < 1
            ):
                raise ValueError("Shard job projection mismatch")
            rows.append(row)
    return rows


def _verify_identity(records, catalog, plan_path, expected_plan_jobs):
    plan_rows = {}
    with _regular(plan_path, "Collection plan").open() as source:
        for line_number, line in enumerate(source, 1):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid collection plan JSONL") from exc
            if (
                isinstance(candidate, dict)
                and candidate.get("api_name") in preparation.POLICY
            ):
                api, params = preparation.validate_candidate(candidate)
            else:
                api, params = preparation.validate_dormant(candidate)
            plan_rows[line_number] = (api, params)
    if len(plan_rows) != expected_plan_jobs:
        raise ValueError("Collection plan row count does not match audit report")
    seen = set()
    source_lines = set()
    with tempfile.TemporaryDirectory(prefix="rrg-import-validation-") as temporary:
        pipeline = Pipeline(temporary, catalog)
        try:
            for row in records:
                api, params = plan_rows.get(row["source_plan_line"], (None, None))
                policy = preparation.POLICY.get(row["api_name"], {})
                if (
                    (api, params) != (row["api_name"], row["params"])
                    or row["priority"] != policy.get("priority")
                    or row["epoch"] != policy.get("epoch")
                    or row["source_plan_line"] in source_lines
                ):
                    raise ValueError(
                        "Shard task does not match pinned source plan policy"
                    )
                source_lines.add(row["source_plan_line"])
                task_id = pipeline.enqueue(
                    row["api_name"],
                    row["params"],
                    priority=row["priority"],
                    epoch=row["epoch"],
                )
                saved = pipeline.db.execute(
                    "SELECT logical_key,epoch,job,priority,state,group_name FROM jobs WHERE id=?",
                    (task_id,),
                ).fetchone()
                actual = {
                    "task_id": task_id,
                    "logical_key": saved["logical_key"],
                    "epoch": saved["epoch"],
                    "priority": saved["priority"],
                    "group_name": saved["group_name"],
                    "job": json.loads(saved["job"]),
                }
                expected = {key: row[key] for key in actual}
                if saved["state"] != "pending" or actual != expected:
                    raise ValueError(
                        "Shard task does not match current Pipeline identity"
                    )
                if task_id in seen:
                    raise ValueError("Duplicate task identity across shards")
                seen.add(task_id)
        finally:
            pipeline.close()
    return sorted(seen)


def verify_batch(batch_manifest, manifest_sha256, audit_report, shard=None):
    manifest_path = _regular(batch_manifest, "Batch manifest").resolve()
    if preparation.sha(manifest_path) != manifest_sha256:
        raise ValueError("Batch manifest hash mismatch")
    batch = json.loads(manifest_path.read_bytes())
    if (
        batch.get("schema_version") != 1
        or batch.get("status") != "prepared_not_enqueued"
        or batch.get("activation", {}).get("automatically_enqueued") is not False
        or batch.get("activation", {}).get("upstream_calls") != 0
        or batch.get("activation", {}).get("credentials_accessed") is not False
        or batch.get("activation", {}).get("production_accessed") is not False
    ):
        raise ValueError("Batch is not an inert acquisition preparation")
    source = batch.get("source", {})
    audit_path = _regular(audit_report, "Audit report")
    _regular(audit_path.parent / "manifest.json", "Audit manifest")
    _regular(audit_path.parent / "collection-plan.jsonl", "Collection plan")
    report, plan_path, plan_sha = preparation._source(  # noqa: SLF001
        audit_path, source.get("audit_report_sha256")
    )
    if (
        plan_sha != source.get("collection_plan_sha256")
        or report.get("release_id") != source.get("release_id")
        or report.get("window") != source.get("window")
    ):
        raise ValueError("Batch source hash chain mismatch")

    folder = manifest_path.parent
    shard_folder = folder / "shards"
    if shard_folder.is_symlink() or not shard_folder.is_dir():
        raise ValueError("Shard directory must be a regular directory")
    inventory = batch.get("shards")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("Batch has no shard inventory")
    listed, records_by_path, all_records = set(), {}, []
    for item in inventory:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "api_name",
            "rows",
            "first_task_id",
            "last_task_id",
            "bytes",
            "sha256",
        }:
            raise ValueError("Invalid shard inventory")
        relative = Path(item["path"])
        unresolved = folder / relative
        path = unresolved.resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parent != Path("shards")
            or path.parent != shard_folder.resolve()
            or relative.as_posix() in listed
        ):
            raise ValueError("Unsafe or duplicate shard path")
        listed.add(relative.as_posix())
        rows = _read_jobs(unresolved)
        if (
            not 1 <= len(rows) <= MAX_SHARD_JOBS
            or len(rows) != item["rows"]
            or path.stat().st_size != item["bytes"]
            or preparation.sha(path) != item["sha256"]
            or rows[0]["task_id"] != item["first_task_id"]
            or rows[-1]["task_id"] != item["last_task_id"]
            or any(row["api_name"] != item["api_name"] for row in rows)
        ):
            raise ValueError("Shard inventory or hash mismatch")
        records_by_path[relative.as_posix()] = rows
        all_records.extend(rows)
    actual_files = {
        path.relative_to(folder).as_posix()
        for path in (folder / "shards").iterdir()
        if path.is_file() or path.is_symlink()
    }
    if actual_files != listed:
        raise ValueError("Unlisted or missing shard file")
    counts = Counter(row["api_name"] for row in all_records)
    expected_counts = batch.get("selection", {}).get("prepared_counts")
    if (
        len(all_records) != batch.get("selection", {}).get("prepared_jobs")
        or dict(counts) != expected_counts
    ):
        raise ValueError("Batch job counts do not match manifest")
    catalog = json.loads((REPO / "config/tushare-catalog.json").read_bytes())
    task_ids = _verify_identity(
        all_records,
        catalog,
        plan_path,
        report.get("collection_plan", {}).get("jobs"),
    )
    selected = None if shard is None else Path(shard).as_posix()
    if selected is not None and selected not in records_by_path:
        raise ValueError("Selected shard is absent from manifest")
    return {
        "manifest": batch,
        "manifest_sha256": manifest_sha256,
        "catalog": catalog,
        "records_by_path": records_by_path,
        "selected": selected,
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
    }


def _schema6(root):
    database = root / "pipeline.sqlite"
    if database.is_symlink() or not database.is_file():
        raise ValueError("Authority pipeline database must be a regular file")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    if version != 6:
        raise ValueError("Authority pipeline schema must already be version 6")


def _execute(
    root,
    batch_manifest,
    manifest_sha256,
    audit_report,
    shard,
    expected_shard_sha256,
    max_jobs,
):
    root = Path(root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    root = root.resolve()
    pipeline_module.authority()
    lock_path = root / "pipeline.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe pipeline lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _schema6(root)
        verified = verify_batch(batch_manifest, manifest_sha256, audit_report, shard)
        if verified["selected"] is None:
            raise ValueError("Execute requires one selected shard")
        records = verified["records_by_path"][verified["selected"]]
        shard_meta = next(
            row
            for row in verified["manifest"]["shards"]
            if row["path"] == verified["selected"]
        )
        if expected_shard_sha256 != shard_meta["sha256"]:
            raise ValueError("Explicit shard hash mismatch")
        if (
            type(max_jobs) is not int
            or not 1 <= len(records) <= max_jobs <= MAX_SHARD_JOBS
        ):
            raise ValueError("Selected shard exceeds the explicit bounded import limit")
        pipeline = Pipeline(root, verified["catalog"])
        inserted, existing, states = 0, 0, Counter()
        try:
            pipeline.db.execute("BEGIN IMMEDIATE")
            for expected in records:
                before = pipeline.db.execute(
                    "SELECT 1 FROM jobs WHERE id=?", (expected["task_id"],)
                ).fetchone()
                task_id = pipeline.enqueue(
                    expected["api_name"],
                    expected["params"],
                    priority=expected["priority"],
                    epoch=expected["epoch"],
                )
                saved = pipeline.db.execute(
                    "SELECT logical_key,epoch,job,priority,state,group_name FROM jobs WHERE id=?",
                    (task_id,),
                ).fetchone()
                actual = {
                    "task_id": task_id,
                    "logical_key": saved["logical_key"],
                    "epoch": saved["epoch"],
                    "priority": saved["priority"],
                    "group_name": saved["group_name"],
                    "job": json.loads(saved["job"]),
                }
                if actual != {key: expected[key] for key in actual}:
                    raise ValueError("Authority Pipeline job identity mismatch")
                inserted += int(before is None)
                existing += int(before is not None)
                states[saved["state"]] += 1
            pipeline.db.commit()
        except BaseException:
            pipeline.db.rollback()
            raise
        finally:
            pipeline.close()
    task_ids = sorted(row["task_id"] for row in records)
    receipt = {
        "schema_version": 1,
        "status": "shard_enqueued",
        "batch_manifest_sha256": verified["manifest_sha256"],
        "source_release_id": verified["manifest"]["source"]["release_id"],
        "shard": verified["selected"],
        "shard_sha256": expected_shard_sha256,
        "task_ids_sha256": digest(json_bytes(task_ids)),
        "jobs": len(records),
        "inserted": inserted,
        "already_present": existing,
        "states": dict(sorted(states.items())),
        "transaction_committed": True,
        "credentials_accessed": False,
        "upstream_calls": 0,
        "worker_run": False,
        "release_published": False,
        "current_release_switched": False,
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    return receipt


def import_shard(
    batch_manifest,
    manifest_sha256,
    audit_report,
    *,
    shard=None,
    expected_shard_sha256=None,
    root=None,
    max_jobs=250,
    execute=False,
):
    """Verify the complete batch; mutate only one explicitly selected shard."""
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(
                patch(target, side_effect=AssertionError("Offline shard import"))
            )
        if not execute:
            verified = verify_batch(
                batch_manifest, manifest_sha256, audit_report, shard
            )
            selected_rows = (
                verified["records_by_path"].get(verified["selected"], [])
                if verified["selected"]
                else []
            )
            return {
                "schema_version": 1,
                "status": "plan_only",
                "batch_manifest_sha256": manifest_sha256,
                "source_release_id": verified["manifest"]["source"]["release_id"],
                "verified_shards": len(verified["records_by_path"]),
                "verified_jobs": verified["manifest"]["selection"]["prepared_jobs"],
                "all_task_ids_sha256": verified["all_task_ids_sha256"],
                "selected_shard": verified["selected"],
                "selected_jobs": len(selected_rows),
                "would_enqueue": False,
                "credentials_accessed": False,
                "upstream_calls": 0,
            }
        if root is None:
            raise ValueError("Execute requires authority root")
        return _execute(
            root,
            batch_manifest,
            manifest_sha256,
            audit_report,
            shard,
            expected_shard_sha256,
            max_jobs,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--shard")
    parser.add_argument("--expected-shard-sha256")
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--max-jobs", type=int, default=250)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = import_shard(
        args.batch_manifest,
        args.manifest_sha256,
        args.audit_report,
        shard=args.shard,
        expected_shard_sha256=args.expected_shard_sha256,
        root=args.root,
        max_jobs=args.max_jobs,
        execute=args.execute,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
