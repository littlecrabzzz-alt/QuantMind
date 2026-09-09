#!/usr/bin/env python3
"""Pull a pinned cloud release over SSH; publish locally only after verification."""

import argparse
from contextlib import contextmanager
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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_archive import link_manifest_alias
from backend.shared.tushare_intake import digest
from backend.shared.tushare_pipeline import atomic_bytes, atomic_json, manifest_at

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


# Tested client-only dependencies; do not install the production requirements.
CLIENT_PACKAGES = ("httpx==0.28.1", "pyarrow==25.0.1", "duckdb==1.5.5")
CLIENT_HEALTH = """
import json, sys
from pathlib import Path
import httpx, pyarrow, duckdb
assert pyarrow.table({'value': [1]}).num_rows == 1
with duckdb.connect(':memory:') as db:
    assert db.execute('SELECT 1').fetchone() == (1,)
print(json.dumps({'prefix': sys.prefix, 'base': str(Path(sys._base_executable).resolve())}))
"""


def client_python_ready(python):
    """Offline import/query smoke; reject a venv based on a temporary uv build."""
    if not python.is_file() or python.parent.parent.is_symlink():
        return False
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", CLIENT_HEALTH],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        info = json.loads(result.stdout)
        base = Path(info["base"])
        return Path(
            info["prefix"]
        ).resolve() == python.parent.parent.resolve() and not any(
            part in (".cache", "Caches", "builds-v0", "archive-v0")
            or part.startswith(".tmp")
            for part in base.parts
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return False


def install_client_python(runtime):
    """Reuse a healthy persistent environment without uv or any network access."""
    environment = runtime / ".venv"
    python = environment / "bin/python"
    if client_python_ready(python):
        return python
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(
            "A healthy client .venv or uv is required; schedule unchanged"
        )
    runtime.mkdir(parents=True, exist_ok=True)
    # Stage under the persistent runtime; relocatable entrypoints survive rename.
    # uv-managed Python lives in its standard persistent installation directory.
    with tempfile.TemporaryDirectory(prefix=".venv-install-", dir=runtime) as folder:
        staging = Path(folder) / ".venv"
        subprocess.run(
            [
                uv,
                "venv",
                "--no-project",
                "--managed-python",
                "--python",
                "3.12",
                "--relocatable",
                str(staging),
            ],
            check=True,
        )
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(staging / "bin/python"),
                "--link-mode",
                "copy",
                *CLIENT_PACKAGES,
            ],
            check=True,
        )
        if not client_python_ready(staging / "bin/python"):
            raise RuntimeError(
                "Client environment validation failed; schedule unchanged"
            )
        backup = Path(folder) / "previous"
        if environment.exists() or environment.is_symlink():
            environment.rename(backup)
        try:
            staging.rename(environment)
        except OSError:
            if backup.exists() or backup.is_symlink():
                backup.rename(environment)
            raise
    return python


def install_schedule(root):
    if sys.platform != "darwin":
        raise ValueError("The mirror schedule belongs on the Mac client")
    label = "com.quantmind.tushare-mirror"
    target = f"gui/{os.getuid()}/{label}"
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    base = Path.home() / "Library/Application Support/QuantMind"
    runtime = base / "tushare-client"
    destination = base / "tushare"
    python = install_client_python(runtime)
    # Deploy a credential-free client outside protected Documents/Desktop paths.
    # Runtime copies are refreshed by reinstalling, never by the data mirror.
    for name in (
        "scripts/tushare_mirror.py",
        "scripts/tushare_pipeline.py",
        "backend/shared/tushare_store.py",
        "backend/shared/tushare_pipeline.py",
        "backend/shared/tushare_discovery_cache.py",
        "backend/shared/tushare_intake.py",
        "backend/shared/tushare_registry.py",
        "backend/shared/tushare_documents.py",
        "backend/shared/tushare_archive.py",
        "backend/shared/tushare_text_contracts.py",
        "backend/shared/tushare_structured_contracts.py",
        "backend/shared/tushare_market_contracts.py",
        "backend/shared/tushare_global_contracts.py",
        "backend/shared/tushare_foreign_financial_contracts.py",
        "backend/shared/tushare_cross_asset_extra_contracts.py",
        "backend/shared/tushare_bond_extra_contracts.py",
        "backend/shared/tushare_securities_lending_history_contracts.py",
        "backend/shared/tushare_history_minutes_contracts.py",
        "backend/shared/tushare_calendar_extra_contracts.py",
        "backend/shared/tushare_factor_library_contracts.py",
        "backend/shared/tushare_other_contracts.py",
        "backend/shared/tushare_supplement_contracts.py",
        "backend/shared/tushare_equity_event_contracts.py",
        "backend/shared/tushare_futures_extra_contracts.py",
        "backend/shared/tushare_research_extra_contracts.py",
        "backend/shared/tushare_credit_extra_contracts.py",
        "backend/shared/tushare_etf_basket_contracts.py",
        "backend/shared/tushare_connect_contracts.py",
        "backend/shared/tushare_trading_event_contracts.py",
        "backend/shared/tushare_listing_extra_contracts.py",
        "backend/shared/tushare_limit_extra_contracts.py",
        "backend/shared/tushare_concept_extra_contracts.py",
        "backend/shared/tushare_dc_extra_contracts.py",
        "backend/shared/tushare_risk_event_contracts.py",
        "backend/shared/tushare_technical_extra_contracts.py",
        "backend/shared/tushare_stock_context_contracts.py",
        "backend/shared/tushare_market_sentiment_contracts.py",
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
            str(python),
            "-I",
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
    # Resolve every deployed import before touching the existing LaunchAgent.
    subprocess.run(
        [str(python), "-I", str(runtime / "scripts/tushare_mirror.py"), "--help"],
        check=True,
        capture_output=True,
        timeout=30,
    )
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


@contextmanager
def mirror_stage(name):
    started = time.monotonic()
    try:
        yield
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if not hasattr(exc, "mirror_stage"):
            exc.mirror_stage = name
            exc.mirror_elapsed = round(time.monotonic() - started, 3)
        raise


def failure_report(exc):
    # Never log subprocess commands, output, remote error text or credentials.
    result = {"status": "failed", "error_type": type(exc).__name__}
    if hasattr(exc, "mirror_stage"):
        result.update(stage=exc.mirror_stage, elapsed_seconds=exc.mirror_elapsed)
    if isinstance(exc, subprocess.TimeoutExpired):
        result["timeout_seconds"] = exc.timeout
    elif isinstance(exc, subprocess.CalledProcessError):
        result["returncode"] = exc.returncode
    return result


def fetch_manifest(root, host, source, release, sha):
    """Pin a complete compressed transfer before publishing any local pointer."""
    relative = "releases/" + release + "/manifest.json"
    destination = root / relative
    archive = root / "archives" / (sha + ".json")
    for path in (destination, archive):
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Refusing mirrored manifest symlink")
        if path.exists():
            expected = {"sha256": sha, "bytes": path.stat().st_size}
            if checked_file(path, expected) is None:
                raise ValueError("Existing manifest checksum mismatch")
            if path == archive:
                link_manifest_alias(
                    root, "archives/" + sha + ".json", relative, expected
                )
            return
    # A private directory prevents partially transferred bytes from becoming a
    # releases/*/manifest.json. Every retry pins CURRENT anew and starts safely.
    with tempfile.TemporaryDirectory(prefix=".manifest-", dir=root) as folder:
        staging = Path(folder)
        listing = staging / "files"
        listing.write_text(relative + "\n")
        with mirror_stage("manifest_transfer"):
            subprocess.run(
                [
                    "rsync",
                    "-az",
                    "--compress-level=3",
                    "--checksum",
                    "--timeout=45",
                    "--rsync-path=sudo -n rsync",
                    "--files-from=" + str(listing),
                    "-e",
                    "ssh -o BatchMode=yes -o ConnectTimeout=15",
                    host + ":" + source,
                    str(staging) + "/",
                ],
                check=True,
                timeout=180,
                capture_output=True,
            )
        incoming = staging / relative
        with mirror_stage("manifest_verify"):
            if incoming.is_symlink() or any(
                parent.is_symlink() for parent in incoming.parents
            ):
                raise ValueError("Refusing transferred manifest symlink")
            expected = {"sha256": sha, "bytes": incoming.stat().st_size}
            if checked_file(incoming, expected) is None:
                raise ValueError("Remote manifest mismatch")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(incoming, destination)


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
        with mirror_stage("pointer_fetch"):
            pointer = json.loads(
                subprocess.check_output(
                    ssh + ["sudo -n cat " + shlex.quote(source + "CURRENT.json")],
                    timeout=30,
                    stderr=subprocess.PIPE,
                )
            )
            if not isinstance(pointer, dict) or not all(
                isinstance(pointer.get(key), str)
                for key in ("release_id", "manifest_sha256")
            ):
                raise ValueError("Invalid remote pointer")
        release = pointer["release_id"]
        # Validate before constructing any remote path.
        import re

        if not re.fullmatch(r"data-[a-f0-9]{64}", release):
            raise ValueError("Invalid remote release")
        if pointer["manifest_sha256"] != release.removeprefix("data-"):
            raise ValueError("Remote pointer identity mismatch")
        with mirror_stage("manifest_prepare"):
            fetch_manifest(root, host, source, release, pointer["manifest_sha256"])
        with mirror_stage("manifest_validate"):
            manifest = manifest_at(root, release)
        missing, verified = [], {}
        for name, expected in manifest["files"].items():
            path = root / name
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("Refusing mirrored symlink")
            if not path.exists() and re.fullmatch(r"archives/[a-f0-9]{64}\.json", name):
                link_manifest_alias(
                    root,
                    "releases/data-" + path.stem + "/manifest.json",
                    name,
                    expected,
                )
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
                with mirror_stage("objects_transfer"):
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
        with mirror_stage("objects_verify"):
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
        print(json.dumps(failure_report(exc)))
        raise SystemExit(2) from None
