#!/usr/bin/env python3
"""Independently check top10 batch overlap and retained file hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected regular file: {path}")
    return json.loads(path.read_bytes())


def request_id(record: dict) -> str:
    job = record["job"]
    return digest(json_bytes({"api_name": job["api_name"], "params": job["params"]}))


def pair_key(record: dict) -> tuple[str, str, str, str]:
    params = record["job"]["params"]
    return record["epoch"], params["start_date"], params["end_date"], params["ts_code"]


def aggregate(values) -> str:
    return digest(json_bytes(sorted(values)))


def write_new(path: Path, value: dict) -> None:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("xb") as target:
        target.write((raw + "\n").encode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--history-manifest", type=Path, action="append", default=[])
    parser.add_argument("--exact-refs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    current = read_json(args.manifest)
    history = [read_json(path) for path in args.history_manifest]
    records = current["records"]
    old_records = [record for manifest in history for record in manifest["records"]]

    current_sets = {
        "task": {record["task_id"] for record in records},
        "logical": {record["logical_key"] for record in records},
        "canonical_request": {request_id(record) for record in records},
        "pair": {pair_key(record) for record in records},
    }
    old_sets = {
        "task": {record["task_id"] for record in old_records},
        "logical": {record["logical_key"] for record in old_records},
        "canonical_request": {request_id(record) for record in old_records},
        "pair": {pair_key(record) for record in old_records},
    }
    overlaps = {key: len(current_sets[key] & old_sets[key]) for key in current_sets}
    if any(overlaps.values()):
        raise ValueError(f"History overlap: {overlaps}")
    overlap = {
        "schema_version": 1,
        "status": "passed",
        "current_jobs": len(records),
        "history_jobs": len(old_records),
        "history_manifests": len(history),
        "unique": {key: len(value) for key, value in current_sets.items()},
        "sha256": {key: aggregate(value) for key, value in current_sets.items()},
        "overlap": overlaps,
    }

    root = args.root.resolve()
    inventory = read_json(args.exact_refs)
    errors = []
    total_bytes = 0
    kinds: dict[str, int] = {}
    for relative, expected in inventory["refs"].items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append({"path": relative, "error": "missing_or_not_regular"})
            continue
        raw = path.read_bytes()
        total_bytes += len(raw)
        kinds[expected["kind"]] = kinds.get(expected["kind"], 0) + 1
        if len(raw) != expected["bytes"] or digest(raw) != expected["sha256"]:
            errors.append({"path": relative, "error": "size_or_sha256_mismatch"})
    physical = {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "references": len(inventory["refs"]),
        "bytes": total_bytes,
        "by_kind": dict(sorted(kinds.items())),
        "errors": errors,
    }
    if errors or total_bytes != inventory["physical_bytes"]:
        raise ValueError("Physical evidence verification failed")

    write_new(args.output_dir / "overlap-audit.json", overlap)
    write_new(args.output_dir / "physical-audit.json", physical)
    print(json.dumps({"overlap": overlap, "physical": physical}, sort_keys=True))


if __name__ == "__main__":
    main()
