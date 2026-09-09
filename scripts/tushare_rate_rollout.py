#!/usr/bin/env python3
"""Reviewed opt-in rollout: dry-run default, no provider calls, durable recovery."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import authority, atomic_bytes
from backend.shared.tushare_rate_policy import POLICY, PURCHASED_RPM, policy_report
from backend.shared.tushare_daily_quota import activate

ENTITLEMENT = {
    "reported_points": 10100,
    "reported_as_of": "2026-09-08",
    "point_tranches": [
        {"points": 8000, "expires": "2027-09-08"},
        {"points": 2000, "expires": "2026-12-05"},
        {"points": 100, "expires": None},
    ],
    "independent_permissions_expiry": "2027-09-08",
    "independent_api_rpm": PURCHASED_RPM,
}
ROOT = Path("/data/tushare")
KEYS = {
    "rate_policy",
    "requests_per_minute",
    "rollout_account_rpm",
    "account_entitlement",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    if path.is_symlink() or path.stat().st_size > 2 * 1024**2:
        raise ValueError("Invalid bounded rollout file")
    return path.read_bytes()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def exclusive(path, raw):
    if path.exists():
        if read(path) != raw:
            raise ValueError("Existing rollout evidence differs")
        return
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_durable(path, raw):
    atomic_bytes(path, raw)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rollout(root, stage, *, execute=False, evidence=None, evidence_sha=None):
    if type(stage) is not int or stage not in (300, 400, 500):
        raise ValueError("Invalid rollout stage")
    root = Path(root)
    if execute:
        authority()
        if root.resolve() != ROOT:
            raise ValueError("Production rollout requires /data/tushare")
    with (root / "pipeline.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config_path = root / "pipeline-config.json"
        before = read(config_path)
        cfg = json.loads(before)
        folder = root / "validation" / "rate-rollout"
        journal = folder / f"{stage}.prepared.json"
        receipt_path = folder / f"{stage}.committed.json"
        if journal.exists():
            saved = json.loads(read(journal))
            old = read(folder / f"{stage}.before.json")
            new = read(folder / f"{stage}.after.json")
            if sha(old) != saved["before_sha256"] or sha(new) != saved["after_sha256"]:
                raise ValueError("Rollout recovery bytes mismatch")
            expected = {
                **json.loads(old),
                "rate_policy": POLICY,
                "requests_per_minute": 500,
                "rollout_account_rpm": stage,
                "account_entitlement": ENTITLEMENT,
            }
            if saved.get("stage") != stage or json.loads(new) != expected:
                raise ValueError("Prepared rollout scope mismatch")
            if sha(before) not in (saved["before_sha256"], saved["after_sha256"]):
                raise ValueError("Config changed outside this rollout; no overwrite")
            if execute:
                activation = activate(root)
                if sha(before) == saved["before_sha256"]:
                    replace_durable(config_path, new)
                committed = {
                    **saved,
                    "phase": "committed",
                    "recovered": True,
                    "daily_quota_activation": activation,
                }
                if not receipt_path.exists():
                    replace_durable(receipt_path, encode(committed))
                else:
                    committed = json.loads(read(receipt_path))
                    if (
                        committed.get("phase") != "committed"
                        or committed.get("before_sha256") != saved["before_sha256"]
                        or committed.get("after_sha256") != saved["after_sha256"]
                    ):
                        raise ValueError("Existing receipt mismatch")
                return committed
            return {**saved, "phase": "recovery_available", "upstream_calls": 0}
        previous = (
            cfg.get("rollout_account_rpm") if cfg.get("rate_policy") == POLICY else None
        )
        if stage == 300 and previous is not None:
            raise ValueError("Tier policy already enabled; do not reset rollout")
        if stage > 300:
            if previous != stage - 100 or not evidence or not evidence_sha:
                raise ValueError(
                    "Previous rollout stage and acceptance evidence required"
                )
            raw = read(Path(evidence))
            proof = json.loads(raw)
            if (
                sha(raw) != evidence_sha
                or proof.get("status") != "passed"
                or proof.get("rollout_account_rpm") != previous
                or proof.get("config_sha256") != sha(before)
            ):
                raise ValueError("Previous stage acceptance mismatch")
        after_cfg = {
            **cfg,
            "rate_policy": POLICY,
            "requests_per_minute": 500,
            "rollout_account_rpm": stage,
            "account_entitlement": ENTITLEMENT,
        }
        if {k: v for k, v in cfg.items() if k not in KEYS} != {
            k: v for k, v in after_cfg.items() if k not in KEYS
        }:
            raise ValueError("Unrelated config changed")
        after = encode(after_cfg)
        summary = {
            "phase": "prepared" if execute else "dry_run",
            "stage": stage,
            "upstream_calls": 0,
            "before_sha256": sha(before),
            "after_sha256": sha(after),
            "old_account_ceiling": cfg.get("requests_per_minute"),
            "new_account_ceiling": 500,
            "old_rollout_account_rpm": cfg.get("rollout_account_rpm"),
            "effective_account_rpm": stage,
            "acceptance_sha256": evidence_sha,
            "unrelated_config_preserved": True,
            "policy": policy_report(after_cfg),
        }
        if execute:
            folder.mkdir(parents=True, exist_ok=True)
            exclusive(folder / f"{stage}.before.json", before)
            exclusive(folder / f"{stage}.after.json", after)
            exclusive(journal, encode(summary))
            summary["daily_quota_activation"] = activate(root)
            replace_durable(config_path, after)
            summary["phase"] = "committed"
            replace_durable(receipt_path, encode(summary))
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/data/tushare"))
    parser.add_argument("--stage", type=int, choices=(300, 400, 500), default=300)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--acceptance-sha256")
    args = parser.parse_args()
    print(
        json.dumps(
            rollout(
                args.root,
                args.stage,
                execute=args.execute,
                evidence=args.acceptance,
                evidence_sha=args.acceptance_sha256,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
