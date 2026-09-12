#!/usr/bin/env python3
"""Run one controlled private p_list/p_get snapshot and restore config bytes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from datetime import datetime, timezone
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import tushare_portfolio_read_batch as batch  # noqa: E402


ROOT = Path("/data/tushare")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_atomic(path: Path, raw: bytes, mode: int) -> None:
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        os.fchmod(descriptor, mode)
        view = memoryview(raw)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> None:
    config_path = ROOT / "pipeline-config.json"
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError("Authority config must be a regular file")
    original = config_path.read_bytes()
    original_mode = stat.S_IMODE(config_path.stat().st_mode)
    original_sha = sha(original)
    private = ROOT / batch.PRIVATE_DIR
    if private.is_symlink():
        raise ValueError("Private directory must not be a symlink")
    private.mkdir(mode=0o700, exist_ok=True)
    if stat.S_IMODE(private.stat().st_mode) != 0o700:
        raise ValueError("Private directory must have mode 0700")
    snapshot = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"portfolio-snapshot-{snapshot}"
    paths = {
        "config_backup": private / f"{prefix}-config-original.json",
        "list_manifest": private / f"{prefix}-list-manifest.json",
        "list_receipt": private / f"{prefix}-list-receipt.json",
        "members_manifest": private / f"{prefix}-members-manifest.json",
        "members_receipt": private / f"{prefix}-members-receipt.json",
        "summary": private / f"{prefix}-summary.json",
    }
    if any(path.exists() or path.is_symlink() for path in paths.values()):
        raise FileExistsError("Private snapshot artifacts are create-only")
    backup_descriptor = os.open(
        paths["config_backup"],
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(backup_descriptor, 0o600)
        view = memoryview(original)
        while view:
            view = view[os.write(backup_descriptor, view) :]
        os.fsync(backup_descriptor)
    finally:
        os.close(backup_descriptor)

    current = json.loads((ROOT / "CURRENT.json").read_bytes())
    release_id = current["release_id"]
    release_sha = current["manifest_sha256"]
    code_sha = batch.code_sha256()
    summary = {
        "schema_version": 1,
        "status": "started",
        "snapshot_epoch": snapshot,
        "release_id": release_id,
        "release_manifest_sha256": release_sha,
        "code_sha256": code_sha,
        "original_config_sha256": original_sha,
        "config_restored": False,
        "private_values_in_summary": False,
        "release_published": False,
        "current_release_switched": False,
    }
    failure = None
    try:
        enabled = json.loads(original)
        enabled["enable_portfolio_read"] = True
        enabled["portfolio_read_apis"] = ["p_list", "p_get"]
        enabled["portfolio_read_snapshot_epoch"] = snapshot
        enabled_raw = (
            json.dumps(
                enabled, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode()
        enabled_sha = sha(enabled_raw)
        write_atomic(config_path, enabled_raw, original_mode)
        summary["enabled_config_sha256"] = enabled_sha

        list_manifest = batch.prepare_manifest(
            ROOT,
            paths["list_manifest"],
            stage="list",
            release_id=release_id,
            release_manifest_sha256=release_sha,
            authority_config_sha256=enabled_sha,
            code_sha256_pin=code_sha,
            snapshot_epoch=snapshot,
        )
        list_manifest_sha = batch.sha(paths["list_manifest"])
        summary["list_plan"] = batch.run_batch(
            ROOT, paths["list_manifest"], list_manifest_sha
        )
        summary["list_run"] = batch.run_batch(
            ROOT,
            paths["list_manifest"],
            list_manifest_sha,
            expected_task_ids_sha256=list_manifest["all_task_ids_sha256"],
            expected_config_sha256=enabled_sha,
            expected_code_sha256=code_sha,
            expected_release_id=release_id,
            expected_release_manifest_sha256=release_sha,
            receipt_path=paths["list_receipt"],
            execute=True,
        )
        if summary["list_run"].get("after_states") not in (
            {"done": 1},
            {"empty": 1},
        ):
            summary["status"] = "list_terminal_without_verified_members_seed"
        else:
            members = batch.prepare_manifest(
                ROOT,
                paths["members_manifest"],
                stage="members",
                release_id=release_id,
                release_manifest_sha256=release_sha,
                authority_config_sha256=enabled_sha,
                code_sha256_pin=code_sha,
                snapshot_epoch=snapshot,
                source_manifest=paths["list_manifest"],
                source_manifest_sha256=list_manifest_sha,
                source_receipt=paths["list_receipt"],
                source_receipt_sha256=batch.sha(paths["list_receipt"]),
            )
            members_manifest_sha = batch.sha(paths["members_manifest"])
            summary["members_plan"] = batch.run_batch(
                ROOT, paths["members_manifest"], members_manifest_sha
            )
            summary["members_run"] = batch.run_batch(
                ROOT,
                paths["members_manifest"],
                members_manifest_sha,
                expected_task_ids_sha256=members["all_task_ids_sha256"],
                expected_config_sha256=enabled_sha,
                expected_code_sha256=code_sha,
                expected_release_id=release_id,
                expected_release_manifest_sha256=release_sha,
                receipt_path=paths["members_receipt"],
                execute=True,
            )
            summary["status"] = "two_stage_snapshot_executed"
    except BaseException as exc:
        failure = exc
        summary["status"] = "failed_closed"
        summary["failed_stage_error_type"] = type(exc).__name__
    finally:
        write_atomic(config_path, original, original_mode)
        summary["config_restored"] = (
            config_path.read_bytes() == original
            and sha(config_path.read_bytes()) == original_sha
        )
        batch._write_private(ROOT, paths["summary"], summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if failure is not None:
        raise SystemExit(2)
    if not summary["config_restored"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
