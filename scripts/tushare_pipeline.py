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
    run.add_argument("--max-requests", type=int)
    run.add_argument("--max-seconds", type=int)
    for name in ("verify", "status", "query", "schema", "export"):
        p = commands.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--release-id")
        if name in ("query", "schema", "export"):
            p.add_argument("--api-name", required=True)
        if name in ("query", "export"):
            p.add_argument("--fields", nargs="+")
            p.add_argument("--date-field")
            p.add_argument("--start-date")
            p.add_argument("--end-date")
            p.add_argument("--codes", nargs="+")
            p.add_argument("--keyword")
            p.add_argument("--as-of")
            p.add_argument("--limit", type=int)
        if name == "query":
            p.add_argument("--show-rows", action="store_true")
        if name == "export":
            p.add_argument("--destination", type=Path, required=True)
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
    if args.command in ("query", "schema", "export"):
        from backend.shared.tushare_store import (
            read_dataset,
            dataset_schema,
            export_jsonl,
        )

        if args.command == "schema":
            print(
                json.dumps(
                    dataset_schema(args.root, release, args.api_name),
                    ensure_ascii=False,
                    default=str,
                )
            )
            return
        filters = {
            name: getattr(args, name)
            for name in (
                "fields",
                "date_field",
                "start_date",
                "end_date",
                "codes",
                "keyword",
                "as_of",
                "limit",
            )
            if getattr(args, name) is not None
        }
        if args.command == "export":
            print(
                json.dumps(
                    export_jsonl(
                        args.root, release, args.api_name, args.destination, **filters
                    ),
                    ensure_ascii=False,
                    default=str,
                )
            )
            return

        table = read_dataset(args.root, release, args.api_name, **filters)
        print(
            json.dumps(
                {
                    "release_id": release,
                    "api_name": args.api_name,
                    "rows": table.num_rows,
                    "columns": table.column_names,
                    "upstream_calls": 0,
                    "rrg_status": manifest["rrg_status"],
                    **({"data": table.to_pylist()} if args.show_rows else {}),
                },
                ensure_ascii=False,
                default=str,
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
