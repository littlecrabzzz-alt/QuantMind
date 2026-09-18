#!/usr/bin/env python3
"""Reassess retained contract failures without replaying supplier requests."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import fcntl
import hashlib
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
from backend.shared.tushare_pipeline import Pipeline, REPLACEMENT_GAPS  # noqa: E402
from backend.shared.tushare_registry import contract_for  # noqa: E402


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _verified_bytes(path, expected_sha, expected_bytes=None):
    path = _regular(path, "Retained artifact")
    body = path.read_bytes()
    if expected_bytes is not None and len(body) != expected_bytes:
        raise ValueError("Retained artifact size mismatch")
    if digest(body) != expected_sha:
        raise ValueError("Retained artifact checksum mismatch")
    return body


def _contract_sha(job):
    spec = contract_for(job["api_name"])
    return digest(
        json_bytes(
            {
                "version": 1,
                "api_name": job["api_name"],
                "fields": job.get("fields"),
                "row_cap": job.get("row_cap"),
                "required_fields": job.get("required_fields"),
                "nullable_fields": spec.get(
                    "assessment_nullable_fields", job.get("nullable_fields", ())
                ),
                "positive_fields": spec.get(
                    "assessment_positive_fields", job.get("positive_fields", ())
                ),
                "optional_requested_fields": spec.get("optional_requested_fields", ()),
            }
        )
    )


def _legacy_complete_response(job, saved, observation, payload):
    """Validate the pre-transport-metadata capture shape without inventing HTTP facts."""
    if any(
        field in saved
        for field in ("response_complete", "response_format", "http_status")
    ):
        return False
    request = observation.get("request") if isinstance(observation, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    return bool(
        observation.get("schema_version") == 1
        and observation.get("response_redacted") is False
        and observation.get("object_sha256") == saved.get("object_sha256")
        and isinstance(request, dict)
        and request.get("api_name") == job.get("api_name")
        and request.get("params") == job.get("params")
        and request.get("fields") == job.get("fields")
        and payload.get("code") == 0
        and isinstance(data, dict)
        and data.get("has_more") is False
    )


def reassess(pipeline, *, apply=False, apis=None):
    """Promote only artifact-verified results accepted by the current contract."""
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    apis = tuple(dict.fromkeys(apis or ()))
    if any(not isinstance(api, str) or not re.fullmatch(r"[a-z0-9_]+", api) for api in apis):
        raise ValueError("Invalid API reassessment filter")
    attempts_before = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
    promoted = Counter()
    legacy_promoted = Counter()
    unchanged = Counter()
    try:
        db.execute("BEGIN IMMEDIATE")
        api_filter = (
            " AND json_extract(job,'$.api_name') IN ("
            + ",".join("?" for _ in apis)
            + ")"
            if apis
            else ""
        )
        rows = db.execute(
            "SELECT id,state,job,result FROM jobs WHERE ("
            "(state='quality' AND json_extract(result,'$.status') "
            "IN ('schema_gap','invalid_values')) OR "
            "(state='blocked' AND json_extract(result,'$.status')="
            "'possibly_truncated'))"
            + api_filter
            + " ORDER BY rowid",
            apis,
        ).fetchall()
        for row in rows:
            job, saved = json.loads(row["job"]), json.loads(row["result"])
            api = job["api_name"]
            if row["state"] == "blocked":
                split = db.execute(
                    "SELECT status,gap,evidence FROM partition_splits WHERE parent_id=?",
                    (row["id"],),
                ).fetchone()
                evidence = json.loads(split["evidence"]) if split else {}
                replacement_gap = evidence.get("replacement_gap")
                if (
                    split
                    and split["status"] == "blocked"
                    and split["gap"] == replacement_gap
                    and replacement_gap in REPLACEMENT_GAPS
                ):
                    unchanged[(api, "retired_replacement")] += 1
                    continue
            current_response_metadata = (
                saved.get("response_complete") is True
                and saved.get("response_format") == "json"
                and saved.get("http_status") == 200
            )
            legacy_response_metadata = all(
                field not in saved
                for field in ("response_complete", "response_format", "http_status")
            )
            if not current_response_metadata and not legacy_response_metadata:
                unchanged[(api, "ineligible_response")] += 1
                continue
            sha = saved.get("object_sha256")
            observation = saved.get("observation")
            observation_sha = saved.get("observation_sha256")
            parquet = saved.get("parquet")
            if (
                not isinstance(sha, str)
                or not re.fullmatch(r"[a-f0-9]{64}", sha)
                or not isinstance(observation, str)
                or not re.fullmatch(r"[a-f0-9]+\.json", observation)
                or not isinstance(observation_sha, str)
                or not isinstance(parquet, dict)
                or not re.fullmatch(
                    r"parquet/[a-f0-9]{64}\.parquet", str(parquet.get("path"))
                )
                or not isinstance(parquet.get("sha256"), str)
                or type(parquet.get("bytes")) is not int
            ):
                raise ValueError("Quality result has invalid artifact references")
            raw = _verified_bytes(pipeline.root / "objects" / f"{sha}.json", sha)
            observation_body = _verified_bytes(
                pipeline.root / "observations" / observation, observation_sha
            )
            _verified_bytes(
                pipeline.root / parquet["path"], parquet["sha256"], parquet["bytes"]
            )
            payload = json.loads(raw)
            observation_payload = json.loads(observation_body)
            if legacy_response_metadata and not _legacy_complete_response(
                job, saved, observation_payload, payload
            ):
                unchanged[(api, "legacy_response_unverified")] += 1
                continue
            assessment = assess_success_payload(job, payload)
            if assessment.get("row_count") != saved.get("row_count"):
                raise ValueError("Reassessment row count changed")
            if assessment.get("status") != "sample_ok":
                unchanged[(api, assessment.get("status", "unknown"))] += 1
                continue
            marker = {
                "version": 1,
                "previous_state": row["state"],
                "previous_status": saved["status"],
                "reassessed_status": "sample_ok",
                "assessed_at": utc_now(),
                "contract_sha256": _contract_sha(job),
                "source_attempt_preserved": True,
                "upstream_calls": 0,
                "response_evidence": (
                    "recorded_http_200_complete_json"
                    if current_response_metadata
                    else "legacy_code_zero_json_has_more_false"
                ),
            }
            updated = {**saved, **assessment, "contract_reassessment": marker}
            if legacy_response_metadata:
                updated["response_metadata_recovery"] = {
                    "version": 1,
                    "response_format": "json_derived_from_verified_object",
                    "supplier_has_more": False,
                    "http_status": "not_recorded",
                    "upstream_calls": 0,
                }
            encoded = json.dumps(updated, sort_keys=True)
            changed = db.execute(
                "UPDATE jobs SET state='done',result=? WHERE id=? AND state=?",
                (encoded, row["id"], row["state"]),
            ).rowcount
            if changed != 1:
                raise ValueError("Quality job changed during reassessment")
            db.execute(
                "INSERT INTO contract_reassessments "
                "(job_id,reassessed_at,contract_sha256,result) VALUES(?,?,?,?)",
                (
                    row["id"],
                    marker["assessed_at"],
                    marker["contract_sha256"],
                    encoded,
                ),
            )
            promoted[api] += 1
            if legacy_response_metadata:
                legacy_promoted[api] += 1
        if db.execute("SELECT count(*) FROM attempts").fetchone()[0] != attempts_before:
            raise ValueError("Attempt ledger changed during contract reassessment")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "candidate_jobs": len(rows),
            "candidate_states": dict(
                sorted(Counter(row["state"] for row in rows).items())
            ),
            "promoted_jobs": sum(promoted.values()),
            "promoted_by_api": dict(sorted(promoted.items())),
            "legacy_response_promoted_jobs": sum(legacy_promoted.values()),
            "legacy_response_promoted_by_api": dict(sorted(legacy_promoted.items())),
            "unchanged_jobs": sum(unchanged.values()),
            "unchanged_by_api_and_status": [
                {"api_name": api, "status": status, "jobs": count}
                for (api, status), count in sorted(unchanged.items())
            ],
            "attempts_preserved": attempts_before,
            "source_attempt_action": "unchanged",
            "artifact_action": "verified_unchanged",
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
    path = Path(root) / f"contract-reassessment-v1.{sha}.json"
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".contract-reassessment-", dir=root)
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
    parser.add_argument("--api", action="append", default=[])
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
        report = reassess(pipeline, apply=args.apply, apis=args.api)
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
