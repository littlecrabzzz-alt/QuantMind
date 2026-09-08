#!/usr/bin/env python3
"""Run the authority pipeline or inspect immutable data without upstream access."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import manifest_at, tick, verify_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--max-requests", type=int, default=100)
    run.add_argument("--max-seconds", type=int, default=100)
    for name in ("verify", "status", "query"):
        p = commands.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--release-id")
        if name == "query":
            p.add_argument("--api-name", required=True)
    args = parser.parse_args()
    if args.command == "run":
        print(json.dumps(tick(args.max_requests, args.max_seconds)))
        return
    release = (
        args.release_id
        or json.loads((args.root / "CURRENT.json").read_bytes())["release_id"]
    )
    manifest = manifest_at(args.root, release)
    if args.command == "verify":
        verify_data(args.root, release)
    if args.command == "query":
        from backend.shared.tushare_store import read_dataset

        table = read_dataset(args.root, release, args.api_name)
        print(
            json.dumps(
                {
                    "release_id": release,
                    "api_name": args.api_name,
                    "rows": table.num_rows,
                    "columns": table.column_names,
                    "upstream_calls": 0,
                    "rrg_status": manifest["rrg_status"],
                }
            )
        )
    else:
        print(
            json.dumps(
                {
                    "release_id": release,
                    "files": len(manifest["files"]),
                    "coverage": manifest["coverage"],
                    "rrg_status": manifest["rrg_status"],
                }
            )
        )


if __name__ == "__main__":
    main()
