#!/usr/bin/env python3
"""Verify that an exact-reference inventory is present in a local fixed release."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def verify(root: Path, inventory_path: Path, release_id: str | None = None) -> dict:
    current = json.loads((root / "CURRENT.json").read_text())
    selected_release = release_id or current["release_id"]
    manifest_path = root / "releases" / selected_release / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    inventory = json.loads(inventory_path.read_text())

    missing = []
    metadata_errors = []
    physical_errors = []
    kinds: Counter[str] = Counter()
    verified_bytes = 0
    for relative_path, expected in inventory["refs"].items():
        kinds[expected["kind"]] += 1
        metadata = manifest["files"].get(relative_path)
        if metadata is None:
            missing.append(relative_path)
            continue
        if (
            metadata.get("sha256") != expected["sha256"]
            or int(metadata.get("bytes", -1)) != expected["bytes"]
        ):
            metadata_errors.append(relative_path)
            continue

        path = root / relative_path
        if (
            not path.is_file()
            or path.stat().st_size != expected["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]
        ):
            physical_errors.append(relative_path)
            continue
        verified_bytes += expected["bytes"]

    passed = not missing and not metadata_errors and not physical_errors
    return {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "release_id": selected_release,
        "current_release_id": current["release_id"],
        "release_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "manifest_files": len(manifest["files"]),
        "manifest_datasets": len(manifest["datasets"]),
        "retained_observations_included": manifest.get("retained_observations_included"),
        "expected_references": len(inventory["refs"]),
        "expected_by_kind": dict(sorted(kinds.items())),
        "expected_bytes": inventory["physical_bytes"],
        "missing_from_manifest": len(missing),
        "manifest_metadata_errors": len(metadata_errors),
        "local_physical_errors": len(physical_errors),
        "verified_references": len(inventory["refs"])
        - len(missing)
        - len(metadata_errors)
        - len(physical_errors),
        "verified_bytes": verified_bytes,
        "samples": {
            "missing": missing[:5],
            "metadata": metadata_errors[:5],
            "physical": physical_errors[:5],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--release-id")
    args = parser.parse_args()
    result = verify(args.root, args.inventory, args.release_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
