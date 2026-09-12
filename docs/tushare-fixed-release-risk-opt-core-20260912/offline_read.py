#!/usr/bin/env python3
"""Read selected datasets from a pinned fixed release with network and secrets blocked."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

from backend.shared.tushare_store import read_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--apis", nargs="+", required=True)
    args = parser.parse_args()
    token_names = ("TUSHARE_TOKEN", "TUSHARE_PRO_TOKEN")
    if any(os.environ.get(name) for name in token_names):
        raise ValueError("Tushare token variables must be empty")
    reads = []
    guards = (
        patch("socket.socket.connect", side_effect=AssertionError("network blocked")),
        patch(
            "socket.create_connection", side_effect=AssertionError("network blocked")
        ),
        patch("socket.getaddrinfo", side_effect=AssertionError("DNS blocked")),
        patch(
            "backend.shared.tushare_pipeline.get_secret",
            side_effect=AssertionError("secret blocked"),
        ),
        patch(
            "backend.shared.runtime_secrets.get_secret",
            side_effect=AssertionError("secret blocked"),
        ),
    )
    for guard in guards:
        guard.start()
    try:
        for api_name in args.apis:
            table = read_dataset(args.root, args.release_id, api_name, limit=3)
            reads.append(
                {
                    "api_name": api_name,
                    "columns": table.num_columns,
                    "rows": table.num_rows,
                }
            )
    finally:
        for guard in reversed(guards):
            guard.stop()
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "release_id": args.release_id,
                "mirror_read_only": True,
                "network": "container_none_plus_socket_and_dns_guards",
                "token_variables_empty": True,
                "upstream_calls": 0,
                "reads": reads,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
