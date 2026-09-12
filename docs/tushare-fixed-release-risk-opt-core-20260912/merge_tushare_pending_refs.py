#!/usr/bin/env python3
"""Merge the three reviewed pending-ref inventories for one fixed-release check."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


INPUTS = (
    "validation/risk2-official-sample-20260912-exact-refs.json",
    "validation/opt-daily-fixed-row-sample-independent-20260912T081416183184Z/exact-refs-pending-next-release.json",
    "validation/core-market-batch-20260912/batch-2-exact-refs.json",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def kind(path):
    return {
        "objects": "object",
        "observations": "observation",
        "parquet": "parquet",
    }[path.split("/", 1)[0]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, refs, sources = args.root.resolve(), {}, []
    for relative in INPUTS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("Pending-ref inventory must be a regular file")
        payload = json.loads(path.read_bytes())
        items = payload["refs"]
        if isinstance(items, dict):
            items = [{"path": key, **value} for key, value in items.items()]
        for item in items:
            normalized = {
                "kind": kind(item["path"]),
                "sha256": item["sha256"],
                "bytes": item["bytes"],
            }
            prior = refs.setdefault(item["path"], normalized)
            if prior != normalized:
                raise ValueError("Conflicting pending-ref inventory")
        sources.append(
            {
                "path": relative,
                "sha256": sha(path),
                "references": len(items),
            }
        )
    result = {
        "schema_version": 1,
        "kind": "risk2_opt_daily_core_market_batch2_pending_refs",
        "sources": sources,
        "refs": dict(sorted(refs.items())),
        "physical_bytes": sum(item["bytes"] for item in refs.values()),
        "history_complete": False,
        "pit_verified": False,
    }
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("Output must be create-only")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "merged",
                "references": len(refs),
                "physical_bytes": result["physical_bytes"],
                "output_sha256": sha(args.output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
