#!/usr/bin/env python3
"""Freeze pristine pending tasks from an existing financial exact manifest."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from scripts import prepare_tushare_financial_pit_batch as financial  # noqa: E402


SELECTION = "source_manifest_pending_attempt_count_zero"


def sha(path):
    return digest(Path(path).read_bytes())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


@contextmanager
def _read_lock(root):
    path = _regular(Path(root) / "pipeline.lock", "Authority pipeline lock")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def _authority_record(db, task_id):
    row = db.execute(
        "SELECT id,logical_key,epoch,priority,group_name,job,state,"
        "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id) "
        "FROM jobs j WHERE id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Source manifest task is missing from authority")
    return {
        "record": {
            "task_id": row[0],
            "logical_key": row[1],
            "epoch": row[2],
            "priority": row[3],
            "group_name": row[4],
            "job": json.loads(row[5]),
        },
        "state": row[6],
        "attempt_count": row[7],
    }


def prepare(
    root,
    source_manifest,
    source_manifest_sha256,
    output,
    *,
    apis=None,
    exclude_pending_with_attempts=False,
):
    root = Path(root).resolve()
    output = Path(output).resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("Output must not exist")
    if output == root or root in output.parents:
        raise ValueError("Output must be outside authority")
    if not output.parent.is_dir():
        raise ValueError("Output parent must already exist")

    source_manifest = _regular(source_manifest, "Source manifest")
    source = financial.verify_manifest(source_manifest, source_manifest_sha256)
    selected_apis = tuple(dict.fromkeys(apis or financial.ALLOWED_APIS))
    unknown = set(selected_apis) - set(financial.ALLOWED_APIS)
    if unknown:
        raise ValueError("Recovery API filter contains unsupported APIs")

    records = []
    excluded_non_pending = Counter()
    uncertain = []
    database = _regular(root / "pipeline.sqlite", "Authority pipeline database")
    with _read_lock(root):
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            for expected in source["records"]:
                api = expected["job"]["api_name"]
                if api not in selected_apis:
                    continue
                actual = _authority_record(db, expected["task_id"])
                if actual["record"] != expected:
                    raise ValueError("Source manifest task changed in authority")
                if actual["state"] != "pending":
                    excluded_non_pending[actual["state"]] += 1
                elif actual["attempt_count"]:
                    uncertain.append(expected["task_id"])
                else:
                    records.append(expected)
        finally:
            db.close()

    if uncertain and not exclude_pending_with_attempts:
        raise ValueError(
            "Pending source tasks with attempts require explicit exclusion: "
            + str(len(uncertain))
        )
    if not records:
        raise ValueError("No pristine pending source tasks selected")

    counts = Counter(record["job"]["api_name"] for record in records)
    task_ids = sorted(record["task_id"] for record in records)
    uncertain_ids = sorted(uncertain)
    result = {
        "schema_version": 1,
        "kind": "financial_pit_exact_batch",
        "source": {
            "epoch": source["source"]["epoch"],
            "state": "pending",
            "selection": SELECTION,
            "source_manifest_sha256": source_manifest_sha256,
            "source_task_ids_sha256": source["all_task_ids_sha256"],
            "api_filter": list(selected_apis),
            "pending_with_attempts_policy": (
                "excluded_explicitly" if exclude_pending_with_attempts else "reject"
            ),
            "excluded_non_pending": dict(sorted(excluded_non_pending.items())),
            "excluded_pending_with_attempts": len(uncertain_ids),
            "excluded_pending_with_attempts_task_ids_sha256": digest(
                json_bytes(uncertain_ids)
            ),
        },
        "api_counts": dict(sorted(counts.items())),
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "records": records,
    }
    with output.open("xb") as target:
        target.write(json_bytes(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", action="append", choices=financial.ALLOWED_APIS)
    parser.add_argument("--exclude-pending-with-attempts", action="store_true")
    args = parser.parse_args()
    result = prepare(
        args.root,
        args.source_manifest,
        args.source_manifest_sha256,
        args.output,
        apis=args.api,
        exclude_pending_with_attempts=args.exclude_pending_with_attempts,
    )
    print(
        json.dumps(
            {
                "status": "prepared_recovery_not_executed",
                "jobs": len(result["records"]),
                "api_counts": result["api_counts"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "source_manifest_sha256": result["source"][
                    "source_manifest_sha256"
                ],
                "authority_access": "read_only",
                "credentials_read": False,
                "upstream_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
