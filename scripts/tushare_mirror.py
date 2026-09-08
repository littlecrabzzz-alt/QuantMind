#!/usr/bin/env python3
"""Pull a pinned cloud release over SSH; publish locally only after verification."""

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_intake import digest
from backend.shared.tushare_pipeline import atomic_json, manifest_at

PROJECT = Path(__file__).resolve().parents[1]


def fingerprint(path):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refusing mirrored symlink")
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def checked_file(path, expected):
    """Hash with bounded memory and reject a file changed during verification."""
    before = fingerprint(path)
    if before[2] != expected["bytes"]:
        return None
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    after = fingerprint(path)
    if before != after:
        raise ValueError("Mirrored file changed during verification")
    return after if sha.hexdigest() == expected["sha256"] else None


def install_schedule(root):
    if sys.platform != "darwin":
        raise ValueError("The mirror schedule belongs on the Mac client")
    label = "com.quantmind.tushare-mirror"
    target = f"gui/{os.getuid()}/{label}"
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    base = Path.home() / "Library/Application Support/QuantMind"
    runtime = base / "tushare-client"
    destination = base / "tushare"
    # Deploy a credential-free client outside protected Documents/Desktop paths.
    # Runtime copies are refreshed by reinstalling, never by the data mirror.
    for name in (
        "scripts/tushare_mirror.py",
        "scripts/tushare_pipeline.py",
        "backend/shared/tushare_store.py",
        "backend/shared/tushare_pipeline.py",
        "backend/shared/tushare_intake.py",
        "backend/shared/tushare_registry.py",
        "backend/shared/tushare_documents.py",
        "backend/shared/tushare_archive.py",
        "backend/shared/tushare_text_contracts.py",
        "backend/shared/tushare_structured_contracts.py",
        "backend/shared/tushare_market_contracts.py",
        "backend/shared/tushare_global_contracts.py",
        "backend/shared/tushare_other_contracts.py",
        "backend/shared/tushare_supplement_contracts.py",
        "backend/shared/tushare_equity_event_contracts.py",
        "backend/shared/tushare_futures_extra_contracts.py",
        "backend/shared/tushare_research_extra_contracts.py",
        "backend/shared/runtime_secrets.py",
        "backend/shared/stock_utils.py",
        "deploy/dual-node.env",
    ):
        target_file = runtime / name
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if (PROJECT / name).resolve() != target_file.resolve():
            shutil.copy2(PROJECT / name, target_file)
    if not destination.exists() and root.exists():
        shutil.copytree(root, destination)
    destination.mkdir(parents=True, exist_ok=True)
    logs = base / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    definition = {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            str(runtime / "scripts/tushare_mirror.py"),
            "--root",
            str(destination),
        ],
        "WorkingDirectory": str(runtime),
        "StartInterval": 900,
        "RunAtLoad": True,
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        },
        "StandardOutPath": str(logs / "tushare-mirror.out.log"),
        "StandardErrorPath": str(logs / "tushare-mirror.err.log"),
    }
    raw = plistlib.dumps(definition)
    installed = (
        subprocess.run(["launchctl", "print", target], capture_output=True).returncode
        == 0
    )
    if installed and plist.exists() and plist.read_bytes() == raw:
        return {"status": "already_installed", "interval_seconds": 900}
    if installed:
        subprocess.run(["launchctl", "bootout", target], check=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(raw)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True
    )
    return {"status": "installed", "interval_seconds": 900, "root": str(destination)}


def mirror(root):
    topology = dict(
        line.split("=", 1)
        for line in (PROJECT / "deploy/dual-node.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    host = topology["QM_SSH_TARGET"]
    source = topology["QM_REMOTE_PROJECT"] + "/data/tushare/"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host]
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".mirror.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running"}
        pointer = json.loads(
            subprocess.check_output(
                ssh + ["sudo -n cat " + shlex.quote(source + "CURRENT.json")],
                timeout=30,
            )
        )
        release = pointer["release_id"]
        # Validate before constructing any remote path.
        import re

        if not re.fullmatch(r"data-[a-f0-9]{64}", release):
            raise ValueError("Invalid remote release")
        raw = subprocess.check_output(
            ssh
            + [
                "sudo -n cat "
                + shlex.quote(source + "releases/" + release + "/manifest.json")
            ],
            timeout=30,
        )
        if digest(raw) != pointer["manifest_sha256"] or digest(
            raw
        ) != release.removeprefix("data-"):
            raise ValueError("Remote manifest mismatch")
        # Storing the pinned manifest is safe before CURRENT is updated.
        manifest_path = root / "releases" / release / "manifest.json"
        atomic_json(manifest_path, json.loads(raw))
        manifest = manifest_at(root, release)
        missing, verified = [], {}
        for name, expected in manifest["files"].items():
            path = root / name
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("Refusing mirrored symlink")
            stamp = checked_file(path, expected) if path.exists() else None
            if stamp is None:
                missing.append(name)
            else:
                verified[name] = stamp
        if missing:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=root, prefix=".files-"
            ) as listing:
                listing.write("\n".join(missing) + "\n")
                listing.flush()
                subprocess.run(
                    [
                        "rsync",
                        "-az",
                        "--compress-level=3",
                        "--checksum",
                        "--timeout=45",
                        "--partial-dir=.rsync-partial",
                        "--rsync-path=sudo -n rsync",
                        "--files-from=" + listing.name,
                        "-e",
                        "ssh -o BatchMode=yes -o ConnectTimeout=15",
                        host + ":" + source,
                        str(root) + "/",
                    ],
                    check=True,
                )
        # Existing immutable files were already hashed above. Recheck their
        # identity after transfer; hash new, repaired or externally changed files.
        for name, expected in manifest["files"].items():
            path = root / name
            if verified.get(name) != fingerprint(path):
                if checked_file(path, expected) is None:
                    raise ValueError("Dataset object checksum mismatch")
        atomic_json(root / "CURRENT.json", pointer)
        result = {
            "status": "verified",
            "release_id": release,
            "downloaded_files": len(missing),
            "files": len(manifest["files"]),
            "coverage": manifest["coverage"],
        }
        atomic_json(root / "mirror-status.json", result)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "Library/Application Support/QuantMind/tushare",
    )
    parser.add_argument("--install-launchagent", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                install_schedule(args.root)
                if args.install_launchagent
                else mirror(args.root)
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
