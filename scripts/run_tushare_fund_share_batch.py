#!/usr/bin/env python3
"""Plan or execute one hash-pinned fund_share history batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import prepare_tushare_fund_share_batch as preparation
from scripts import run_tushare_fund_nav_batch as exact_runner


MAX_UPSTREAM_REQUESTS = exact_runner.MAX_UPSTREAM_REQUESTS
MAX_SECONDS = exact_runner.MAX_SECONDS
pipeline_module = exact_runner.pipeline_module
httpx = exact_runner.httpx
sha = exact_runner.sha
json_bytes = exact_runner.json_bytes


def _helper_paths():
    return (__file__, exact_runner.__file__)


def helper_sha256():
    """Pin this entry point and the shared exact-runner implementation."""
    return exact_runner.helper_sha256(_helper_paths())


def preparation_sha256():
    return exact_runner.preparation_sha256(preparation)


def run_batch(
    manifest,
    manifest_sha256,
    *,
    expected_task_ids_sha256=None,
    expected_config_sha256=None,
    expected_helper_sha256=None,
    expected_preparation_sha256=None,
    root=None,
    max_requests=MAX_UPSTREAM_REQUESTS,
    max_seconds=MAX_SECONDS,
    execute=False,
):
    return exact_runner.run_exact_batch(
        manifest,
        manifest_sha256,
        preparation_module=preparation,
        helper_path=_helper_paths(),
        api_name=preparation.API,
        expected_task_ids_sha256=expected_task_ids_sha256,
        expected_config_sha256=expected_config_sha256,
        expected_helper_sha256=expected_helper_sha256,
        expected_preparation_sha256=expected_preparation_sha256,
        root=root,
        max_requests=max_requests,
        max_seconds=max_seconds,
        execute=execute,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-task-ids-sha256")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--expected-preparation-sha256")
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--max-requests", type=int, default=MAX_UPSTREAM_REQUESTS)
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_batch(
                args.manifest,
                args.manifest_sha256,
                expected_task_ids_sha256=args.expected_task_ids_sha256,
                expected_config_sha256=args.expected_config_sha256,
                expected_helper_sha256=args.expected_helper_sha256,
                expected_preparation_sha256=args.expected_preparation_sha256,
                root=args.root,
                max_requests=args.max_requests,
                max_seconds=args.max_seconds,
                execute=args.execute,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
