#!/usr/bin/env python3
"""Close one exact index_daily batch from immutable raw and Parquet evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pyarrow.parquet as pq


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def checked(path: Path, expected: str | None = None) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected immutable regular file")
    raw = path.read_bytes()
    if expected is not None and digest(raw) != expected:
        raise ValueError("Immutable file SHA-256 mismatch")
    return raw


def add_ref(refs: dict, root: Path, relative: str, kind: str, expected: str) -> None:
    path = root / relative
    raw = checked(path, expected)
    value = {"kind": kind, "sha256": expected, "bytes": len(raw)}
    prior = refs.setdefault(relative, value)
    if prior != value:
        raise ValueError("Conflicting physical reference")


def write_new(path: Path, value: dict) -> None:
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    with path.open("xb") as target:
        target.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--prepare", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output_dir.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output directory is create-only")
    output.mkdir(parents=True)
    sources = {
        "manifest.json": args.manifest,
        "prepare.json": args.prepare,
        "plan.json": args.plan,
        "receipt.json": args.receipt,
    }
    for name, source in sources.items():
        with (output / name).open("xb") as target:
            with source.open("rb") as original:
                shutil.copyfileobj(original, target)
    manifest_raw = checked(output / "manifest.json")
    manifest = json.loads(manifest_raw)
    receipt = json.loads(checked(output / "receipt.json"))
    if (
        receipt.get("batch_manifest_sha256") != digest(manifest_raw)
        or receipt.get("status") != "exact_batch_executed"
        or receipt.get("upstream_calls") != len(manifest["records"])
        or receipt.get("verified_jobs") != len(manifest["records"])
        or receipt.get("current_release_switched") is not False
        or receipt.get("release_published") is not False
    ):
        raise ValueError("Runner receipt does not close the pinned manifest")
    database = root / "pipeline.sqlite"
    refs: dict[str, dict] = {}
    states: Counter[str] = Counter()
    apis: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    rows = 0
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        for record in manifest["records"]:
            row = db.execute(
                "SELECT id,logical_key,epoch,job,priority,group_name,state,tries,result "
                "FROM jobs WHERE id=?",
                (record["task_id"],),
            ).fetchone()
            if row is None:
                raise ValueError("Pinned task is missing")
            actual = {
                "task_id": row["id"],
                "logical_key": row["logical_key"],
                "epoch": row["epoch"],
                "priority": row["priority"],
                "group_name": row["group_name"],
                "job": json.loads(row["job"]),
            }
            if (
                actual != record
                or row["state"] not in ("done", "empty")
                or row["tries"] != 1
            ):
                raise ValueError("Pinned task identity or terminal state mismatch")
            attempts = db.execute(
                "SELECT attempt,result FROM attempts WHERE job_id=? ORDER BY attempt",
                (record["task_id"],),
            ).fetchall()
            result = json.loads(row["result"])
            if (
                len(attempts) != 1
                or attempts[0]["attempt"] != 1
                or json.loads(attempts[0]["result"]) != result
            ):
                raise ValueError("Attempt history does not match terminal result")
            expected_status = (
                "sample_ok" if row["state"] == "done" else "empty_unverified"
            )
            if (
                result.get("api_name") != record["job"]["api_name"]
                or result.get("status") != expected_status
                or result.get("http_status") != 200
                or result.get("response_complete") is not True
                or result.get("response_format") != "json"
                or result.get("field_coverage") != "complete_for_explicit_request"
                or result.get("supplier_has_more") is True
                or result.get("missing_fields") not in (None, [])
                or result.get("requested_missing_fields") not in (None, [])
            ):
                raise ValueError("Terminal result contract mismatch")
            object_sha = result["object_sha256"]
            observation = result["observation"]
            observation_sha = result["observation_sha256"]
            object_relative = f"objects/{object_sha}.json"
            observation_relative = f"observations/{observation}"
            add_ref(refs, root, object_relative, "object", object_sha)
            add_ref(refs, root, observation_relative, "observation", observation_sha)
            payload = json.loads(checked(root / object_relative, object_sha))
            observed = json.loads(checked(root / observation_relative, observation_sha))
            request = {
                key: record["job"][key] for key in ("api_name", "params", "fields")
            }
            data = payload.get("data") if isinstance(payload, dict) else None
            fields = data.get("fields") if isinstance(data, dict) else None
            items = data.get("items") if isinstance(data, dict) else None
            if (
                payload.get("code") != 0
                or observed.get("request") != request
                or observed.get("object_sha256") != object_sha
                or not isinstance(fields, list)
                or not isinstance(items, list)
                or any(
                    not isinstance(item, list) or len(item) != len(fields)
                    for item in items
                )
                or len(items) != result["row_count"]
            ):
                raise ValueError("Raw response and observation chain mismatch")
            parquet = result.get("parquet")
            if row["state"] == "empty":
                if result["row_count"] != 0 or parquet is not None:
                    raise ValueError("Empty task unexpectedly has retained rows")
            else:
                if not isinstance(parquet, dict) or result["row_count"] <= 0:
                    raise ValueError("Done task lacks Parquet evidence")
                add_ref(refs, root, parquet["path"], "parquet", parquet["sha256"])
                if (root / parquet["path"]).stat().st_size != parquet[
                    "bytes"
                ] or pq.read_metadata(root / parquet["path"]).num_rows != result[
                    "row_count"
                ]:
                    raise ValueError("Parquet size or row count mismatch")
            states[row["state"]] += 1
            apis[result["api_name"]] += 1
            status_counts[result["status"]] += 1
            rows += result["row_count"]
    finally:
        db.close()
    inventory = {
        "schema_version": 1,
        "kind": "fund_share_batch17_exact_refs",
        "refs": dict(sorted(refs.items())),
        "physical_bytes": sum(item["bytes"] for item in refs.values()),
        "history_complete": False,
        "pit_verified": False,
    }
    write_new(output / "exact-refs.json", inventory)
    closure = {
        "schema_version": 1,
        "status": "exact_batch_closed",
        "manifest_sha256": digest(manifest_raw),
        "task_ids_sha256": manifest["all_task_ids_sha256"],
        "jobs": len(manifest["records"]),
        "states": dict(sorted(states.items())),
        "api_counts": dict(sorted(apis.items())),
        "attempt_status_counts": dict(sorted(status_counts.items())),
        "rows": rows,
        "upstream_calls": receipt["upstream_calls"],
        "elapsed_seconds": receipt["elapsed_seconds"],
        "unique_references": len(refs),
        "physical_bytes": inventory["physical_bytes"],
        "exact_refs_sha256": digest((output / "exact-refs.json").read_bytes()),
        "release_published": False,
        "current_release_switched": False,
        "history_complete": False,
        "pit_verified": False,
    }
    write_new(output / "closure.json", closure)
    print(json.dumps(closure, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
