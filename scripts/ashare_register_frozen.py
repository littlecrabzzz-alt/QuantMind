#!/usr/bin/env python3
"""Export eight frozen observation registrations, or apply via strategy_storage.

Default is read-only JSON export. --apply requires an explicit existing user ID
and the deployment owner's selected DATABASE_URL/environment. No service changes,
config writes, account balances or ledger updates are performed here.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error("--out must be a new immutable binding/export file")
    from backend.shared.ashare_lab_bridge.registry import registrations, register

    if args.apply:
        result = asyncio.run(register(args.user_id, args.tenant_id))
    else:
        result = registrations(args.user_id, args.tenant_id)
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x") as stream:
            stream.write(content)
    print(content, end="")


if __name__ == "__main__":
    main()
