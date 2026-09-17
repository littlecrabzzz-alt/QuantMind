#!/usr/bin/env python3
"""Recover retained successful responses whose local Parquet write timed out."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import fcntl
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import (  # noqa: E402
    assess_success_payload,
    digest,
    json_bytes,
    utc_now,
)
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402

TRANSIENT_ERRORS = ("SoftTimeLimitExceeded", "TimeoutError")


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _verified_bytes(path, expected_sha):
    body = _regular(path, "Retained artifact").read_bytes()
    if digest(body) != expected_sha:
        raise ValueError("Retained artifact checksum mismatch")
    return body


def _normalizer_sha256():
    return digest(inspect.getsource(Pipeline.normalize).encode())


def _stage_normalize(pipeline, result):
    """Exercise normalization during dry-run without writing into the archive."""
    original_root = pipeline.root
    with tempfile.TemporaryDirectory(prefix="tushare-normalization-recovery-") as tmp:
        stage = Path(tmp)
        for family in ("objects", "observations", "parquet"):
            (stage / family).mkdir()
        source_object = original_root / "objects" / (result["object_sha256"] + ".json")
        source_observation = original_root / "observations" / result["observation"]
        os.link(source_object, stage / "objects" / source_object.name)
        os.link(source_observation, stage / "observations" / source_observation.name)
        pipeline.root = stage
        try:
            return pipeline.normalize(dict(result))
        finally:
            pipeline.root = original_root


def recover(pipeline, *, apply=False):
    """Normalize artifact-verified successes locally without another API request."""
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    attempts_before = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
    results_before = db.execute(
        "SELECT count(*) FROM jobs WHERE result IS NOT NULL"
    ).fetchone()[0]
    recovered = Counter()
    unchanged = Counter()
    normalizer_sha = _normalizer_sha256()
    try:
        db.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in TRANSIENT_ERRORS)
        rows = db.execute(
            "SELECT id,job,result FROM jobs INDEXED BY jobs_pending "
            "WHERE state='blocked' "
            "AND json_extract(result,'$.status')='sample_ok' "
            "AND json_extract(result,'$.normalization_error') IN ("
            + placeholders
            + ") ORDER BY rowid",
            TRANSIENT_ERRORS,
        ).fetchall()
        for row in rows:
            job, saved = json.loads(row["job"]), json.loads(row["result"])
            api = job["api_name"]
            if (
                saved.get("response_complete") is not True
                or saved.get("response_format") != "json"
                or saved.get("http_status") != 200
                or "parquet" in saved
            ):
                unchanged[(api, "ineligible_response")] += 1
                continue
            sha = saved.get("object_sha256")
            observation = saved.get("observation")
            observation_sha = saved.get("observation_sha256")
            if (
                not isinstance(sha, str)
                or not re.fullmatch(r"[a-f0-9]{64}", sha)
                or not isinstance(observation, str)
                or not re.fullmatch(r"[a-f0-9]+\.json", observation)
                or not isinstance(observation_sha, str)
                or not re.fullmatch(r"[a-f0-9]{64}", observation_sha)
            ):
                raise ValueError("Blocked result has invalid artifact references")
            raw = _verified_bytes(pipeline.root / "objects" / f"{sha}.json", sha)
            _verified_bytes(
                pipeline.root / "observations" / observation, observation_sha
            )
            assessment = assess_success_payload(job, json.loads(raw))
            if (
                assessment.get("status") != "sample_ok"
                or assessment.get("row_count") != saved.get("row_count")
            ):
                unchanged[(api, assessment.get("status", "unknown"))] += 1
                continue
            previous_error = saved["normalization_error"]
            candidate = {**saved, **assessment}
            candidate.pop("normalization_error", None)
            normalized = (
                pipeline.normalize(candidate)
                if apply
                else _stage_normalize(pipeline, candidate)
            )
            parquet = normalized.get("parquet")
            if not isinstance(parquet, dict):
                raise ValueError("Normalization recovery did not produce Parquet")
            recovered_at = utc_now()
            marker = {
                "version": 1,
                "previous_error": previous_error,
                "recovered_status": "sample_ok",
                "recovered_at": recovered_at,
                "normalizer_sha256": normalizer_sha,
                "source_attempt_preserved": True,
                "upstream_calls": 0,
            }
            normalized["normalization_recovery"] = marker
            encoded = json.dumps(normalized, sort_keys=True)
            changed = db.execute(
                "UPDATE jobs SET state='done',result=? "
                "WHERE id=? AND state='blocked'",
                (encoded, row["id"]),
            ).rowcount
            if changed != 1:
                raise ValueError("Normalization job changed during recovery")
            db.execute(
                "INSERT INTO normalization_recoveries "
                "(job_id,recovered_at,normalizer_sha256,result) VALUES(?,?,?,?)",
                (row["id"], recovered_at, normalizer_sha, encoded),
            )
            db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) "
                "VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET "
                "status=excluded.status,checked_at=excluded.checked_at,"
                "reason=excluded.reason",
                (
                    "normalization:" + row["id"],
                    "normalization_recovered",
                    recovered_at,
                    json.dumps(
                        {
                            "api_name": api,
                            "previous_error": previous_error,
                            "source_attempt_preserved": True,
                            "upstream_calls": 0,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            recovered[api] += 1
        if db.execute("SELECT count(*) FROM attempts").fetchone()[0] != attempts_before:
            raise ValueError("Attempt ledger changed during normalization recovery")
        if (
            db.execute("SELECT count(*) FROM jobs WHERE result IS NOT NULL").fetchone()[
                0
            ]
            != results_before
        ):
            raise ValueError("Result-bearing job count changed during recovery")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "candidate_jobs": len(rows),
            "recovered_jobs": sum(recovered.values()),
            "recovered_by_api": dict(sorted(recovered.items())),
            "unchanged_jobs": sum(unchanged.values()),
            "unchanged_by_api_and_status": [
                {"api_name": api, "status": status, "jobs": count}
                for (api, status), count in sorted(unchanged.items())
            ],
            "normalizer_sha256": normalizer_sha,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "source_attempt_action": "unchanged",
            "artifact_action": "verified_then_normalized",
            "upstream_calls": 0,
        }
        if apply:
            db.commit()
        else:
            db.rollback()
        return report
    except BaseException:
        db.rollback()
        raise


def _write_receipt(root, report):
    body = json_bytes(report) + b"\n"
    sha = hashlib.sha256(body).hexdigest()
    path = Path(root) / f"normalization-recovery-v1.{sha}.json"
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(
        prefix=".normalization-recovery-", dir=root
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = json.loads(_regular(args.catalog, "Catalog").read_bytes())
    for name in ("pipeline.sqlite", "pipeline.lock", ".archive-worker.lock"):
        _regular(root / name, name)
    with ExitStack() as stack:
        for name in (".archive-worker.lock", "pipeline.lock"):
            handle = stack.enter_context((root / name).open("rb"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pipeline = Pipeline(root, catalog)
        stack.callback(pipeline.close)
        report = recover(pipeline, apply=args.apply)
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
