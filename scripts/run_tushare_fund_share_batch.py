#!/usr/bin/env python3
"""Plan or execute one hash-pinned fund_share history batch."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
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


def _verify_pristine_authority(root, verified):
    source = verified["source"]
    if source.get("semantic_dedup") != preparation.SEMANTIC_DEDUP:
        return
    database = Path(root) / "pipeline.sqlite"
    with closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
    ) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        selected_signatures = {
            preparation._request_signature(record["job"])
            for record in verified["records"]
        }
        for record in verified["records"]:
            saved = db.execute(
                "SELECT state,tries,(SELECT COUNT(*) FROM attempts a "
                "WHERE a.job_id=j.id) attempts FROM jobs j WHERE id=?",
                (record["task_id"],),
            ).fetchone()
            if saved is None:
                raise ValueError("Verified fund_share task is missing from authority")
            if saved["state"] != "pending":
                raise ValueError("Verified fund_share task is no longer pending")
            if saved["tries"] != 0 or saved["attempts"] != 0:
                raise ValueError("Verified fund_share task is no longer pristine")
        other_epochs = [
            row[0]
            for row in db.execute("SELECT DISTINCT epoch FROM jobs ORDER BY epoch")
        ]
        for epoch in other_epochs:
            for row in db.execute(
                "SELECT j.job,j.state,j.tries,EXISTS(SELECT 1 FROM attempts a "
                "WHERE a.job_id=j.id) attempted FROM jobs j "
                "INDEXED BY jobs_partition_lookup WHERE j.epoch=? AND "
                "json_extract(j.job,'$.api_name')=?",
                (epoch, preparation.API),
            ):
                if (
                    preparation._request_signature(json.loads(row["job"]))
                    in selected_signatures
                    and (
                        row["state"] != "pending"
                        or row["tries"] != 0
                        or row["attempted"]
                    )
                ):
                    raise ValueError(
                        "Verified fund_share semantic peer is no longer pristine"
                    )


def _execution_preparation(root):
    class ExecutionPreparation:
        __file__ = preparation.__file__

        @staticmethod
        def verify_manifest(manifest, manifest_sha256):
            verified = preparation.verify_manifest(manifest, manifest_sha256)
            _verify_pristine_authority(root, verified)
            return verified

    return ExecutionPreparation


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
    execution_root = Path(root or pipeline_module.ROOT)
    return exact_runner.run_exact_batch(
        manifest,
        manifest_sha256,
        preparation_module=(
            _execution_preparation(execution_root) if execute else preparation
        ),
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
