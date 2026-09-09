#!/usr/bin/env python3
"""Compare registered Tushare APIs with one immutable local release."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import CONTRACTS, manifest_at  # noqa: E402
from backend.shared.tushare_registry import EXTENDED_CONTRACTS  # noqa: E402


def _direct_capabilities(manifest):
    """Return only API-level capability rows, excluding planning gap scopes."""
    result = {}
    for row in manifest.get("capabilities", []):
        scope = row.get("scope")
        if not isinstance(scope, str):
            continue
        api = scope[:-1] if scope.endswith(":") and ":" not in scope[:-1] else scope
        if ":" in api:
            continue
        result.setdefault(api, []).append({
            "status": row.get("status"),
            "checked_at": row.get("checked_at"),
        })
    return {api: sorted(rows, key=lambda row: (str(row["status"]), str(row["checked_at"])))
            for api, rows in sorted(result.items())}


def audit(registered, manifest, release_id):
    registered = set(registered)
    planned = set(manifest.get("scope", []))
    datasets = Counter(
        row.get("api_name") for row in manifest.get("datasets", [])
        if isinstance(row, dict) and row.get("api_name")
    )
    coverage = {}
    for row in manifest.get("coverage_by_api", []):
        if not isinstance(row, dict) or not row.get("api_name"):
            continue
        coverage.setdefault(row["api_name"], {})[row.get("state")] = row.get("partitions")
    capabilities = _direct_capabilities(manifest)

    def row(api):
        return {
            "api_name": api,
            "coverage": dict(sorted(coverage.get(api, {}).items())),
            "capabilities": capabilities.get(api, []),
        }

    return {
        "schema_version": 1,
        "release_id": release_id,
        "manifest_file_count": len(manifest.get("files", {})),
        "counts": {
            "registered": len(registered),
            "planned": len(planned),
            "registered_planned": len(registered & planned),
            "registered_with_published_dataset": len(registered & set(datasets)),
            "published_dataset_apis": len(datasets),
        },
        "registered_not_planned": [row(api) for api in sorted(registered - planned)],
        "registered_planned_without_published_dataset": [
            row(api) for api in sorted((registered & planned) - set(datasets))
        ],
        "published_dataset_counts": {
            api: datasets[api] for api in sorted(registered & set(datasets))
        },
        "unregistered_planned": sorted(planned - registered),
        "unregistered_published_dataset_apis": sorted(set(datasets) - registered),
        "limitations": [
            "This is one immutable release, not the current authority database.",
            "Registration, planning and a published dataset are separate states.",
            "A published dataset does not prove complete history, fields, revisions, attachments or point-in-time validity.",
            "An empty or blocked partition can legitimately have no published dataset and remains explicit in coverage.",
            "A registered but unplanned API may be intentionally disabled pending permission or runtime validation.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output.resolve()
    if output == root or output.is_relative_to(root):
        parser.error("output must be outside the immutable mirror root")
    release_id = args.release_id
    if release_id is None:
        pointer = json.loads((root / "CURRENT.json").read_bytes())
        release_id = pointer["release_id"]
    manifest = manifest_at(root, release_id)
    result = audit(set(CONTRACTS) | set(EXTENDED_CONTRACTS), manifest, release_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "release_id": release_id,
        "counts": result["counts"],
        "registered_not_planned": len(result["registered_not_planned"]),
        "registered_planned_without_published_dataset": len(
            result["registered_planned_without_published_dataset"]
        ),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
