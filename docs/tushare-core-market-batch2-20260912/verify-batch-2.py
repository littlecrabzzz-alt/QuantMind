#!/usr/bin/env python3
"""Read-only, exact-scope closure for the 2026-09-12 core-market batch."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

import pyarrow.parquet as pq


ROOT = Path("/data/tushare")
OUT = ROOT / "validation/core-market-batch-20260912"
MANIFEST = OUT / "batch-2-manifest.json"
EXPECTED_MANIFEST_SHA = "50d5a25cba53d30b89c90b2bbcf206c3354ca8d5269ecdbf7290b190e6fc1c77"
EXPECTED_TASK_IDS_SHA = "4b92ab39b4efcbd61c13f958264a9c7eb1b9b24bff954d8a50af5a9848a5560f"
RUNNER_REPORTED_CALLS = 330
RUNNER_REPORTED_SECONDS = 90.282
SERVICE_RESTARTED_AT = "2026-09-12T08:06:28+00:00"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def regular(path: Path):
    if path.is_symlink() or not path.is_file():
        raise AssertionError(f"not a regular file: {path}")
    return path


def file_ref(path: Path):
    regular(path)
    rel = path.relative_to(ROOT).as_posix()
    return {"path": rel, "sha256": sha(path), "bytes": path.stat().st_size}


def main():
    manifest_bytes = regular(MANIFEST).read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == EXPECTED_MANIFEST_SHA
    manifest = json.loads(manifest_bytes)
    task_ids = sorted(row["task_id"] for row in manifest["records"])
    assert hashlib.sha256(canonical(task_ids)).hexdigest() == EXPECTED_TASK_IDS_SHA
    assert len(task_ids) == len(set(task_ids)) == 360

    by_id = {row["task_id"]: row for row in manifest["records"]}
    db = sqlite3.connect(f"file:{ROOT / 'pipeline.sqlite'}?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    states = Counter()
    api_states = Counter()
    tries = Counter()
    attempt_counts = Counter()
    fetched_times = []
    refs = {}
    tasks = []
    blocked = []
    content_checks = Counter()

    try:
        for task_id in task_ids:
            expected = by_id[task_id]
            row = db.execute(
                "SELECT id,logical_key,epoch,job,priority,group_name,state,tries,result "
                "FROM jobs WHERE id=?",
                (task_id,),
            ).fetchone()
            assert row is not None
            job = json.loads(row["job"])
            api = job["api_name"]
            date = job["params"]["trade_date"]
            assert row["id"] == expected["task_id"]
            assert row["logical_key"] == expected["logical_key"]
            assert row["epoch"] == expected["epoch"]
            assert row["priority"] == expected["priority"]
            assert row["group_name"] == expected["group_name"]
            assert job == expected["job"]
            attempts = db.execute(
                "SELECT attempt,result FROM attempts WHERE job_id=? ORDER BY attempt",
                (task_id,),
            ).fetchall()
            states[row["state"]] += 1
            api_states[(api, row["state"])] += 1
            tries[row["tries"]] += 1
            attempt_counts[len(attempts)] += 1
            item = {
                "task_id": task_id,
                "api_name": api,
                "trade_date": date,
                "state": row["state"],
                "tries": row["tries"],
                "attempts": len(attempts),
            }
            if not attempts:
                assert row["state"] == "pending" and row["tries"] == 0 and row["result"] is None
                tasks.append(item)
                continue
            assert len(attempts) == row["tries"] == 1
            assert attempts[0]["attempt"] == 1
            assert attempts[0]["result"] == row["result"]
            result = json.loads(row["result"])
            assert result["api_name"] == api
            assert result["http_status"] == 200
            assert result["response_complete"] is True
            assert result["status"] == "sample_ok"
            assert result["row_count"] > 0
            assert result["supplier_has_more"] is False
            assert result["history_complete"] is False
            assert result["pit_verified"] is False
            assert result["field_coverage"] == "complete_for_explicit_request"
            assert result["missing_fields"] == []
            assert result["requested_missing_fields"] == []
            assert result["unexpected_returned_fields"] == []

            observation_path = ROOT / "observations" / result["observation"]
            observation_ref = file_ref(observation_path)
            assert observation_ref["sha256"] == result["observation_sha256"]
            observation = json.loads(observation_path.read_bytes())
            assert observation["request"] == {
                "api_name": api,
                "fields": job["fields"],
                "params": job["params"],
            }
            for key, value in observation["assessment"].items():
                assert result[key] == value
            fetched = datetime.fromisoformat(observation["fetched_at"])
            fetched_times.append(observation["fetched_at"])
            assert observation["object_sha256"] == result["object_sha256"]
            object_path = ROOT / "objects" / f"{result['object_sha256']}.json"
            object_ref = file_ref(object_path)
            assert object_ref["sha256"] == result["object_sha256"]
            raw = json.loads(object_path.read_bytes())
            assert raw["code"] == 0 and isinstance(raw["data"], dict)
            assert raw["data"]["has_more"] is False
            assert len(raw["data"]["items"]) == result["row_count"]
            assert isinstance(raw["data"].get("count"), int)
            expected_fields = job["fields"].split(",")
            assert raw["data"]["fields"] == expected_fields
            date_index = expected_fields.index("trade_date")
            assert all(values[date_index] == date for values in raw["data"]["items"])
            refs[observation_ref["path"]] = observation_ref
            refs[object_ref["path"]] = object_ref
            content_checks["raw_request_chain"] += 1

            if row["state"] == "done":
                assert set(result) >= {"parquet"}
                parquet_path = ROOT / result["parquet"]["path"]
                parquet_ref = file_ref(parquet_path)
                assert parquet_ref["sha256"] == result["parquet"]["sha256"]
                assert parquet_ref["bytes"] == result["parquet"]["bytes"]
                assert parquet_path.stem == parquet_ref["sha256"]
                table = pq.read_table(parquet_path)
                assert table.num_rows == result["row_count"]
                assert table.column_names[: len(expected_fields)] == expected_fields
                assert set(table.column_names[len(expected_fields) :]) == {
                    "_row_identity",
                    "_source",
                    "_api_name",
                    "source_ts_code",
                    "_fetched_at",
                    "_observation",
                }
                assert set(table.column("trade_date").to_pylist()) == {date}
                refs[parquet_ref["path"]] = parquet_ref
                content_checks["parquet_content"] += 1
            else:
                assert row["state"] == "blocked"
                assert result.get("normalization_error") == "TimeoutError"
                assert "parquet" not in result
                blocked.append(
                    {
                        "task_id": task_id,
                        "api_name": api,
                        "trade_date": date,
                        "reason": "normalization_error:TimeoutError",
                        "raw_response_preserved": True,
                        "fetched_at": observation["fetched_at"],
                    }
                )
            item.update(
                {
                    "fetched_at": observation["fetched_at"],
                    "observation": observation_ref,
                    "object": object_ref,
                    "parquet": result.get("parquet"),
                }
            )
            tasks.append(item)
    finally:
        db.close()

    assert states == Counter({"done": 329, "blocked": 1, "pending": 30})
    assert tries == Counter({1: 330, 0: 30})
    assert attempt_counts == Counter({1: 330, 0: 30})
    assert sum(1 for value in fetched_times if value < SERVICE_RESTARTED_AT) == RUNNER_REPORTED_CALLS
    assert len(refs) == 989
    assert content_checks == Counter({"raw_request_chain": 330, "parquet_content": 329})
    assert len(blocked) == 1 and blocked[0]["api_name"] == "daily_basic"

    inventory = {
        "schema_version": 1,
        "kind": "core_market_batch_2_expected_next_release_refs",
        "source_batch_manifest_sha256": EXPECTED_MANIFEST_SHA,
        "current_release_at_execution": manifest["source"]["release_id"],
        "publication_status": "pending_next_normal_publication",
        "refs": sorted(refs.values(), key=lambda value: value["path"]),
    }
    inventory["refs_sha256"] = hashlib.sha256(canonical(inventory["refs"])).hexdigest()
    inventory["ref_count"] = len(inventory["refs"])
    inventory["bytes"] = sum(ref["bytes"] for ref in inventory["refs"])
    inventory_path = OUT / "batch-2-exact-refs.json"
    with inventory_path.open("xb") as target:
        target.write(canonical(inventory) + b"\n")

    report = {
        "schema_version": 1,
        "kind": "core_market_batch_2_exact_closure",
        "status": "bounded_execution_verified_with_one_preserved_normalization_block",
        "batch_manifest": file_ref(MANIFEST),
        "all_task_ids_sha256": EXPECTED_TASK_IDS_SHA,
        "runner_reported": {
            "upstream_calls": RUNNER_REPORTED_CALLS,
            "elapsed_seconds": RUNNER_REPORTED_SECONDS,
            "hard_limit_calls": 360,
            "hard_limit_seconds": 90,
        },
        "verified_current_state": {
            "states": dict(sorted(states.items())),
            "tries": {str(k): v for k, v in sorted(tries.items())},
            "attempt_counts": {str(k): v for k, v in sorted(attempt_counts.items())},
            "api_states": {
                f"{api}:{state}": count
                for (api, state), count in sorted(api_states.items())
            },
            "earliest_fetched_at": min(fetched_times),
            "latest_fetched_at": max(fetched_times),
            "all_attempts_precede_service_restart": True,
        },
        "content_checks": dict(sorted(content_checks.items())),
        "blocked": blocked,
        "expected_next_release_inventory": file_ref(inventory_path),
        "expected_next_release_refs_sha256": inventory["refs_sha256"],
        "expected_next_release_ref_count": inventory["ref_count"],
        "expected_next_release_bytes": inventory["bytes"],
        "history_complete": False,
        "pit_verified": False,
        "publication_verified": False,
        "mac_mirror_verified": False,
        "tasks": tasks,
    }
    report_path = OUT / "batch-2-exact-closure.json"
    with report_path.open("xb") as target:
        target.write(canonical(report) + b"\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "states": report["verified_current_state"]["states"],
                "refs": inventory["ref_count"],
                "bytes": inventory["bytes"],
                "refs_sha256": inventory["refs_sha256"],
                "inventory_sha256": sha(inventory_path),
                "report_sha256": sha(report_path),
                "blocked": blocked,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
