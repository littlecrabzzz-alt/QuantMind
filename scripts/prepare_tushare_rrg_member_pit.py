#!/usr/bin/env python3
"""Reconcile one fixed Tushare release with claimed CITIC membership evidence."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.rrg_member_pit_contract import (  # noqa: E402
    load_evidence_manifest,
    reconcile_members,
    sha256,
)
from backend.shared.tushare_pipeline import manifest_at  # noqa: E402
from backend.shared.tushare_store import read_dataset  # noqa: E402

DATA_FILE = "member-reconciliation.parquet"
REPORT_FILE = "report.json"
MANIFEST_FILE = "manifest.json"
EVIDENCE_DIR = "evidence"
SAFE_BOUNDARIES = {
    "claimed_provider": "CITIC",
    "claimed_taxonomy": "CITIC_L1",
    "revision_semantics": "full_replacement",
    "effective_dates_are_not_publication_times": True,
    "interval_semantics": "half_open_[effective_from,effective_to)",
    "known_at_is_claimed_publication_evidence": True,
    "observation_time_used_as_historical_known_at": False,
    "unverified_rows_keep_null_known_at": True,
    "source_authority_verified": False,
    "historical_known_at_verified": False,
    "signal_date_cutoff_evaluated": False,
    "consumer_must_gate_known_at_and_exit_known_at": True,
    "historical_source_universe_verified": False,
    "rrg_ready": False,
    "rrg_case_changed": False,
    "quantdb_changed": False,
    "upstream_calls": 0,
    "credentials_accessed": False,
}


def _output_path(root, evidence_manifest, output):
    root = Path(root).resolve()
    evidence_dir = Path(evidence_manifest).resolve().parent
    output = Path(output).resolve()
    protected = (root, REPO, evidence_dir)
    if (
        output.exists()
        or any(output == base or base in output.parents for base in protected)
        or any((parent / ".git").exists() for parent in (output, *output.parents))
    ):
        raise ValueError(
            "Output must be new and outside source, evidence and data trees"
        )
    return root, output


def _manifest_file(root, release_id):
    if not isinstance(release_id, str) or not re.fullmatch(
        r"data-[a-f0-9]{64}", release_id
    ):
        raise ValueError("A fixed release id is required")
    path = root / "releases" / release_id / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Fixed release manifest is missing")
    return path


def _require_portable_locators(value):
    if isinstance(value, dict):
        for item in value.values():
            _require_portable_locators(item)
    elif isinstance(value, list):
        for item in value:
            _require_portable_locators(item)
    elif isinstance(value, str) and (
        value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)
    ):
        raise ValueError("Artifact metadata contains an absolute filesystem path")


def _relative_locator(value, label):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or PurePosixPath(value).is_absolute()
        or any(part in ("", ".", "..") for part in PurePosixPath(value).parts)
    ):
        raise ValueError(f"Invalid portable {label}")
    return PurePosixPath(value).as_posix()


def _prepare(root, release_id, evidence_manifest, output):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root, output = _output_path(root, evidence_manifest, output)
    fixed_manifest_path = _manifest_file(root, release_id)
    fixed_manifest = manifest_at(root, release_id)
    if fixed_manifest.get("retained_observations_included") is not True:
        raise ValueError("Fixed release must include retained observations")
    evidence = load_evidence_manifest(evidence_manifest)
    table = read_dataset(root, release_id, "ci_index_member", limit=100000)
    if len(table) >= 100000:
        raise ValueError("ci_index_member reached the explicit reader cap")
    metadata = json.loads(table.schema.metadata[b"tushare"])
    if (
        not isinstance(metadata, dict)
        or metadata.get("release_id") != release_id
        or metadata.get("upstream_calls") != 0
    ):
        raise ValueError("Unexpected fixed reader provenance")
    reader_metadata = {
        key: metadata.get(key)
        for key in (
            "release_id",
            "api_name",
            "source_api_names",
            "historical_versions_complete",
            "history_complete",
            "coverage",
            "as_of_semantics",
            "as_of",
            "upstream_calls",
        )
        if key in metadata
    }

    rows, reconciliation = reconcile_members(table.to_pylist(), evidence)
    gaps = []
    if not evidence["active_announcements"]:
        gaps.append("no_active_claimed_announcements")
    if reconciliation["content_reconciled_rows"] != reconciliation["source_rows"]:
        gaps.append("source_intervals_without_complete_publication_evidence")
    if reconciliation["unmatched_events"]:
        gaps.append("claimed_events_unmatched_to_fixed_source_intervals")
    if reconciliation["source_interval_conflicts"]:
        gaps.append("fixed_source_intervals_conflict")
    if reconciliation["source_identity_missing_rows"]:
        gaps.append("fixed_source_identity_missing")
    gaps.append("source_authority_identity_unverified")
    schema = pa.schema(
        [
            ("source_row_identity", pa.string()),
            ("SectorCode", pa.string()),
            ("Symbol", pa.string()),
            ("source_sector_code", pa.string()),
            ("source_symbol", pa.string()),
            ("effective_from", pa.string()),
            ("effective_to", pa.string()),
            ("known_at", pa.string()),
            ("exit_known_at", pa.string()),
            ("taxonomy_version", pa.string()),
            ("entry_announcement_id", pa.string()),
            ("entry_revision", pa.int64()),
            ("entry_source_url", pa.string()),
            ("entry_source_path", pa.string()),
            ("entry_source_sha256", pa.string()),
            ("exit_announcement_id", pa.string()),
            ("exit_revision", pa.int64()),
            ("exit_source_url", pa.string()),
            ("exit_source_path", pa.string()),
            ("exit_source_sha256", pa.string()),
            ("entry_claimed_evidence_matched", pa.bool_()),
            ("exit_evidence_required", pa.bool_()),
            ("exit_claimed_evidence_matched", pa.bool_()),
            ("source_authority_verified", pa.bool_()),
            ("content_reconciled", pa.bool_()),
            ("historical_known_at_verified", pa.bool_()),
        ]
    )
    result = pa.Table.from_pylist(rows, schema=schema).replace_schema_metadata(
        {
            b"rrg_member_pit": json.dumps(
                {
                    "release_id": release_id,
                    "status": "content_reconciled"
                    if reconciliation["content_complete_for_fixed_source"]
                    else "blocked_data",
                    "claimed_provider": "CITIC",
                    "claimed_taxonomy": "CITIC_L1",
                    "source_authority_verified": False,
                    "historical_known_at_verified": False,
                    "rrg_ready": False,
                    "upstream_calls": 0,
                    "rrg_case_changed": False,
                },
                sort_keys=True,
            ).encode()
        }
    )
    report = {
        "schema_version": 1,
        "status": "content_reconciled"
        if reconciliation["content_complete_for_fixed_source"]
        else "blocked_data",
        "release_id": release_id,
        "fixed_manifest": {
            "locator": fixed_manifest_path.relative_to(root).as_posix(),
            "bytes": fixed_manifest_path.stat().st_size,
            # manifest_at verified these exact content-addressed bytes.
            "sha256": release_id.removeprefix("data-"),
        },
        "evidence_manifest": {
            "locator": f"{EVIDENCE_DIR}/{_relative_locator(evidence['locator'], 'evidence manifest locator')}",
            "bytes": evidence["bytes"],
            "sha256": evidence["sha256"],
            "announcement_revisions": evidence["announcement_revisions"],
            "active_announcements": evidence["active_announcements"],
            "withdrawn_announcements": evidence["withdrawn_announcements"],
            "active_events": len(evidence["events"]),
            "content_verified_sources": evidence["content_verified_sources"],
        },
        "reconciliation": reconciliation,
        "gaps": gaps,
        "reader_metadata": reader_metadata,
        "boundaries": dict(SAFE_BOUNDARIES),
    }

    _require_portable_locators(report)
    _write_artifacts(output, result, report, Path(evidence_manifest).resolve())
    return report


def _artifact_path(directory, locator):
    locator = _relative_locator(locator, "artifact file locator")
    path = directory.joinpath(*PurePosixPath(locator).parts)
    if directory.resolve() not in path.resolve().parents:
        raise ValueError("Artifact file escapes its root")
    return path


def _checked_copy(source, destination, expected, *, source_base):
    source_base = source_base.resolve()
    if (
        source.is_symlink()
        or not source.is_file()
        or source_base not in source.resolve().parents
    ):
        raise ValueError("Evidence bundle source is unsafe")
    raw = source.read_bytes()
    if len(raw) != expected.get("bytes") or sha256_bytes(raw) != expected.get("sha256"):
        raise ValueError("Evidence bundle source changed after validation")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)


def sha256_bytes(raw):
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _bundle_evidence(directory, evidence_manifest, report):
    evidence_meta = report["evidence_manifest"]
    locator = _relative_locator(evidence_meta["locator"], "evidence locator")
    destination = _artifact_path(directory, locator)
    source_base = evidence_manifest.parent.resolve()
    files = {}
    _checked_copy(
        evidence_manifest,
        destination,
        evidence_meta,
        source_base=source_base,
    )
    files[locator] = {
        "bytes": evidence_meta["bytes"],
        "sha256": evidence_meta["sha256"],
    }
    manifest_name = PurePosixPath(locator).name
    for revision in evidence_meta["content_verified_sources"]:
        source_meta = revision["source"]
        relative = _relative_locator(source_meta["path"], "evidence source locator")
        if relative == manifest_name:
            raise ValueError("Evidence source collides with bundled manifest")
        bundled_locator = f"{EVIDENCE_DIR}/{relative}"
        expected = {
            "bytes": source_meta["bytes"],
            "sha256": source_meta["sha256"],
        }
        if bundled_locator in files:
            if files[bundled_locator] != expected:
                raise ValueError("Evidence revisions disagree about source bytes")
            continue
        source = source_base.joinpath(*PurePosixPath(relative).parts)
        bundled = _artifact_path(directory, bundled_locator)
        _checked_copy(source, bundled, expected, source_base=source_base)
        files[bundled_locator] = expected
    return files


def _validate_artifacts(directory, artifact_manifest):
    import pyarrow.parquet as pq

    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Artifact root is unsafe")
    expected_files = artifact_manifest.get("files")
    if not isinstance(expected_files, dict):
        raise ValueError("Artifact file manifest is invalid")
    actual_files = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Artifact bundle contains a symlink")
        if path.is_file():
            actual_files.add(path.relative_to(directory).as_posix())
    if actual_files != set(expected_files) | {MANIFEST_FILE}:
        raise ValueError("Generated artifact set mismatch")
    if json.loads((directory / MANIFEST_FILE).read_bytes()) != artifact_manifest:
        raise ValueError("Generated manifest mismatch")
    for name, expected in expected_files.items():
        path = _artifact_path(directory, name)
        if (
            not isinstance(expected, dict)
            or not isinstance(expected.get("bytes"), int)
            or isinstance(expected.get("bytes"), bool)
            or expected["bytes"] < 0
            or not isinstance(expected.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected["sha256"])
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != expected["bytes"]
            or sha256(path) != expected["sha256"]
        ):
            raise ValueError("Generated artifact checksum mismatch")
    report = json.loads((directory / REPORT_FILE).read_bytes())
    _require_portable_locators(report)
    parquet_table = pq.read_table(directory / DATA_FILE)
    try:
        parquet_metadata = json.loads(parquet_table.schema.metadata[b"rrg_member_pit"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Parquet reconciliation metadata is invalid") from exc
    evidence_meta = artifact_manifest.get("evidence_manifest")
    if not isinstance(evidence_meta, dict):
        raise ValueError("Bundled evidence manifest metadata is invalid")
    evidence_locator = _relative_locator(
        evidence_meta.get("locator"), "evidence manifest locator"
    )
    if PurePosixPath(evidence_locator).parent != PurePosixPath(EVIDENCE_DIR):
        raise ValueError("Bundled evidence manifest must be under evidence/")
    if expected_files.get(evidence_locator) != {
        "bytes": evidence_meta.get("bytes"),
        "sha256": evidence_meta.get("sha256"),
    }:
        raise ValueError("Bundled evidence manifest is not in the file inventory")
    bundled = load_evidence_manifest(_artifact_path(directory, evidence_locator))
    if (
        bundled["bytes"] != evidence_meta["bytes"]
        or bundled["sha256"] != evidence_meta["sha256"]
    ):
        raise ValueError("Bundled evidence manifest identity mismatch")
    for revision in bundled["content_verified_sources"]:
        source = revision["source"]
        source_locator = (
            PurePosixPath(evidence_locator).parent
            / _relative_locator(source["path"], "evidence source locator")
        ).as_posix()
        if expected_files.get(source_locator) != {
            "bytes": source["bytes"],
            "sha256": source["sha256"],
        }:
            raise ValueError("Bundled evidence source is not in the file inventory")
    report_evidence = report.get("evidence_manifest")
    if (
        report.get("release_id") != artifact_manifest.get("release_id")
        or report.get("fixed_manifest") != artifact_manifest.get("fixed_manifest")
        or not isinstance(report_evidence, dict)
        or {key: report_evidence.get(key) for key in ("locator", "bytes", "sha256")}
        != evidence_meta
    ):
        raise ValueError("Artifact report provenance mismatch")
    status = artifact_manifest.get("status")
    if (
        status not in ("content_reconciled", "blocked_data")
        or report.get("status") != status
        or parquet_metadata.get("status") != status
    ):
        raise ValueError("Artifact status mismatch")
    boundaries = report.get("boundaries")
    if boundaries != SAFE_BOUNDARIES:
        raise ValueError("Unsafe artifact safety boundaries")
    for field in (
        "source_authority_verified",
        "historical_known_at_verified",
        "rrg_ready",
    ):
        if (
            artifact_manifest.get(field) is not False
            or parquet_metadata.get(field) is not False
        ):
            raise ValueError(f"Unsafe artifact promotion: {field}")
    for field in (
        "source_authority_verified",
        "historical_known_at_verified",
    ):
        if field not in parquet_table.column_names or any(
            value is not False for value in parquet_table[field].to_pylist()
        ):
            raise ValueError(f"Unsafe Parquet row promotion: {field}")


def verify_artifact(directory, expected_manifest_sha256):
    directory = Path(directory)
    manifest_path = directory / MANIFEST_FILE
    if (
        directory.is_symlink()
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
    ):
        raise ValueError("Artifact manifest is missing or unsafe")
    if not isinstance(expected_manifest_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_manifest_sha256
    ):
        raise ValueError("Expected artifact manifest SHA256 is required")
    raw = manifest_path.read_bytes()
    if sha256_bytes(raw) != expected_manifest_sha256:
        raise ValueError("Artifact manifest SHA256 mismatch")
    artifact_manifest = json.loads(raw)
    if (
        not isinstance(artifact_manifest, dict)
        or artifact_manifest.get("schema_version") != 1
        or artifact_manifest.get("kind") != "citic_member_pit_content_reconciliation"
    ):
        raise ValueError("Unsupported artifact manifest")
    _require_portable_locators(artifact_manifest)
    _validate_artifacts(directory, artifact_manifest)
    return artifact_manifest


def _write_artifacts(output, result, report, evidence_manifest):
    import pyarrow.parquet as pq

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        pq.write_table(result, temporary / DATA_FILE, compression="zstd")
        (temporary / REPORT_FILE).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        files = {}
        for name in (DATA_FILE, REPORT_FILE):
            path = temporary / name
            files[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        files.update(_bundle_evidence(temporary, evidence_manifest, report))
        artifact_manifest = {
            "schema_version": 1,
            "kind": "citic_member_pit_content_reconciliation",
            "status": report["status"],
            "release_id": report["release_id"],
            "source_authority_verified": False,
            "historical_known_at_verified": False,
            "rrg_ready": False,
            "fixed_manifest": report["fixed_manifest"],
            "evidence_manifest": {
                key: report["evidence_manifest"][key]
                for key in ("locator", "bytes", "sha256")
            },
            "files": files,
        }
        (temporary / MANIFEST_FILE).write_text(
            json.dumps(artifact_manifest, indent=2) + "\n"
        )
        manifest_sha256 = sha256(temporary / MANIFEST_FILE)
        verify_artifact(temporary, manifest_sha256)
        if output.exists():
            raise FileExistsError("Output appeared before atomic publish")
        os.rename(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def prepare(*args, **kwargs):
    """Run without sockets, credentials, production writes or state promotion."""
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(
                patch(target, side_effect=AssertionError("Offline PIT boundary"))
            )
        return _prepare(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.root, args.release_id, args.evidence_manifest, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
