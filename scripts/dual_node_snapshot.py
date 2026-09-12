#!/usr/bin/env python3
"""Explicit, consistent cloud snapshots and non-destructive offline downloads.

No live database file sync, no local database write-back, no automatic pruning.
"""
import argparse
import datetime
import fcntl
import gzip
import time
import hashlib
import json
import os
import plistlib
import stat
import sys
from pathlib import Path
import shutil
import signal
import subprocess

from dual_node_inventory import inventory, runtime_path, runtime_roots, stat_key
from dual_node_sync import PROJECT, topology

SETTINGS = topology()
REMOTE = SETTINGS["QM_REMOTE_ROOT"]
WRITERS = ["quantmind-celery-beat", "quantmind", "quantmind-celery",
           "quantmind-huntly", "qwenpaw", "quantmind-tushare-worker", "quantmind-tushare-document-worker", "quantmind-redis"]


class BusyError(RuntimeError):
    pass


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest(project):
    return "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                   for item in inventory(project))


def publish_link(base, target):
    temporary = base / ".latest.new"
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target.name)
    os.replace(temporary, base / "latest")


def runtime_stats(project):
    records = {}
    for root in runtime_roots(project):
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(project)
            if not runtime_path(relative):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise RuntimeError(f"Review runtime symlink before migration: {relative}")
            if stat.S_ISREG(info.st_mode):
                records[relative.as_posix()] = stat_key(info)
    return records


def copy_runtime_delta(source, target, copied, cache, expected_stats):
    changed = [
        path for path, current_stat in expected_stats.items()
        if path not in cache or cache[path][0] != current_stat
        or copied.get(path) != cache[path][1]
    ]
    removed = copied.keys() - expected_stats.keys()
    started_at = time.monotonic()
    if changed:
        run("rsync", "-a", "--ignore-times", "--from0", "--files-from=-",
            str(source) + "/", str(target) + "/",
            input=b"\0".join(p.encode() for p in changed) + b"\0")
    # Only unpublished staging files are removed, never the live tree or latest.
    for path in removed:
        (target / path).unlink()
    return {
        "changed_files": len(changed),
        "changed_logical_bytes": sum(expected_stats[path][2] for path in changed),
        "removed_files": len(removed),
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def finish_snapshot(target):
    require(manifest(target / "project") == (target / "runtime-manifest.jsonl").read_text(),
            "Snapshot files do not match; unpublished staging retained")
    for archive in target.glob("*.tar"):
        with archive.open("rb") as src, gzip.open(str(archive) + ".gz", "wb", compresslevel=1) as dst:
            shutil.copyfileobj(src, dst, 4 * 1024 * 1024)
        archive.unlink()
    hashes = {p.name: digest(p) for p in target.iterdir()
              if p.is_file() and p.name not in {"SHA256.json", "COMPLETE"}}
    (target / "SHA256.json").write_text(json.dumps(hashes, indent=2))
    (target / "COMPLETE").touch()


def cloud_snapshot():
    require(os.geteuid() == 0 and (Path(REMOTE) / "AUTHORITY").is_file(), "Run on the cloud authority after cutover")
    require(output("findmnt", "-n", "-o", "UUID", "-T", REMOTE) == SETTINGS["QM_DISK_UUID"], "Wrong or unmounted SSD")
    # Fail before creating a snapshot if there is insufficient recovery headroom.
    require(shutil.disk_usage(REMOTE).free > 100 * 1024**3, "Keep 100 GiB free for recovery")
    base = Path(REMOTE) / "snapshots"
    base.mkdir(exist_ok=True, mode=0o700)
    with (base / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        name = "snapshot-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        # Resume an unpublished attempt rather than creating another full 65 GiB copy.
        target = base / ".building"
        target.mkdir(mode=0o700, exist_ok=True)
        (target / "COMPLETE").unlink(missing_ok=True)
        (target / "project").mkdir(exist_ok=True)
        previous = (base / "latest").resolve()
        sources = [str(p) for p in runtime_roots(PROJECT)]
        copy = ["rsync", "-a", "--exclude=.DS_Store", "--exclude=.rsync-partial",
                "--exclude=__pycache__", "--exclude=data/stocks/", "--exclude=data/upgrade_v*.sql",
                "--exclude=db/sql/"]
        if previous.is_dir():
            # Only link to an earlier IMMUTABLE snapshot, never to the live data tree.
            copy += ["--link-dest=" + str(previous / "project")]
        run(*copy, *sources, str(target / "project") + "/")
        # Hash while the application is online. The stat cache identifies files
        # that need no delta copy; the finished copy is independently hashed.
        copied = {r["path"]: r for r in inventory(target / "project")}
        cache = {}
        list(inventory(PROJECT, cache=cache, tolerate_changes=True))
        active = output("docker", "ps", "--format", "{{.Names}}").splitlines()
        if any(n.startswith(("qm-train-", "qm-agent-", "qm-frozen-", "qm-ide-run-", "rdagent-")) for n in active):
            raise BusyError("Research job active")
        if "quantmind-celery" in active:
            jobs = json.loads(output("docker", "exec", "quantmind-celery", "celery", "-A",
                "backend.services.engine.qlib_app.celery_config:celery_app", "inspect", "active", "--json", "--timeout=15"))
            require(bool(jobs), "No Celery worker response")
            if any(task["name"] not in {"engine.tasks.tushare_acquire", "engine.tasks.tushare_documents"}
                   for tasks in jobs.values() for task in tasks):
                raise BusyError("Celery work active")
        stopped = [name for name in WRITERS if name in active]
        started_at = time.monotonic()
        try:
            applications = [name for name in stopped if name != "quantmind-redis"]
            if applications:
                run("docker", "stop", "--time", "240", *applications)
            if "quantmind-redis" in stopped:
                run("docker", "stop", "--time", "60", "quantmind-redis")
            # Close the admission race: a child may have appeared during shutdown.
            active_now = output("docker", "ps", "--format", "{{.Names}}").splitlines()
            require(not any(n.startswith(("qm-train-", "qm-agent-", "qm-frozen-",
                                          "qm-ide-run-", "rdagent-")) for n in active_now),
                    "Research job appeared during quiesce; snapshot aborted")
            expected_stats = runtime_stats(PROJECT)
            delta = copy_runtime_delta(
                PROJECT, target / "project", copied, cache, expected_stats
            )
            print(json.dumps({"phase": "runtime_delta", **delta}), flush=True)
            # Capture database and cold volumes without compression in the outage.
            with (target / "postgres.dump").open("wb") as stream:
                run("docker", "exec", "quantmind-db", "sh", "-c",
                    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z0 --no-owner', stdout=stream)
            for volume in ("redis-data", "qwenpaw-data", "qwenpaw-secrets", "qwenpaw-backups", "qwenpaw-shared"):
                run("tar", "-cf", str(target / (volume + ".tar")), "-C", REMOTE + "/volumes/" + volume, ".")
            # Reject an untracked writer instead of publishing a mixed-time copy.
            require(runtime_stats(PROJECT) == expected_stats,
                    "Runtime changed during quiesced copy; unpublished staging retained")
        finally:
            if stopped:
                ordered = (["quantmind-redis"] if "quantmind-redis" in stopped else [])
                ordered += [name for name in stopped if name != "quantmind-redis"]
                run("docker", "start", *ordered)
            print(json.dumps({"phase": "writers_restored", "pause_seconds": round(time.monotonic() - started_at, 2)}), flush=True)
        # Content hashing and manifest generation happen after writers are restored.
        expected = list(inventory(target / "project"))
        (target / "runtime-manifest.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in expected))
        # Independent full validation and compression touch only the frozen copy.
        # Never publish COMPLETE/latest until both have succeeded.
        finish_snapshot(target)
        published = base / name
        target.rename(published)
        publish_link(base, published)
        print(published)


def pull_snapshot(base=None, only_new=False, remote_base="snapshots"):
    require(remote_base in {"snapshots", "quantdb-snapshots"}, "Invalid snapshot collection")
    ssh = SETTINGS["QM_SSH_TARGET"]
    remote_path = output("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh,
                         "sudo -n realpath -e " + REMOTE + "/" + remote_base + "/latest")
    path = Path(remote_path)
    require(str(path.parent) == REMOTE + "/" + remote_base and path.name.startswith("snapshot-"), "Invalid snapshot path")
    run("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh, "sudo -n test -f " + remote_path + "/COMPLETE")
    base = base or PROJECT / "logs/cloud-snapshots"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = base.resolve()
    with (base / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = base / path.name
        if only_new and (base / "latest").resolve() == target.resolve() and (target / "VERIFIED").is_file() and (target / "COMPLETE").is_file():
            print("Already verified:", target, flush=True)
            return
        target.mkdir(exist_ok=True)
        # A previously published local snapshot stays usable during revalidation.
        if (base / "latest").resolve() != target.resolve():
            (target / "COMPLETE").unlink(missing_ok=True)
        (target / "VERIFIED").unlink(missing_ok=True)
        rsync = "/opt/homebrew/bin/rsync" if Path("/opt/homebrew/bin/rsync").exists() else "rsync"
        args = [rsync, "-a", "--checksum", "--no-owner", "--no-group", "--compress", "--partial", "--stats", "--timeout=120", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30", "--rsync-path=sudo -n rsync"]
        previous = (base / "latest").resolve()
        metadata_args = list(args)
        data_args = list(args)
        if previous.is_dir() and previous != target:
            metadata_args += ["--link-dest=" + str(previous)]
            data_args += ["--link-dest=" + str(previous / "project")]
        else:
            # QuantDB's first limited snapshot can share immutable full-snapshot files.
            # Never hard-link the writable sandbox or the live legacy data tree.
            full_reference = (base.parent / "latest" / "project").resolve()
            if remote_base == "quantdb-snapshots" and full_reference.is_dir():
                data_args += ["--link-dest=" + str(full_reference)]
            else:
                data_args += ["--copy-dest=" + str(PROJECT)]
            backups = sorted((PROJECT / "logs").glob("dual-node-*/postgres.dump"))
            if backups:
                # PostgreSQL dump headers can change; rsync still reuses matching blocks.
                metadata_args += ["--copy-dest=" + str(backups[-1].parent.resolve())]
        run(*metadata_args, "--exclude=/project/", "--exclude=/COMPLETE", ssh + ":" + remote_path + "/", str(target) + "/")
        (target / "project").mkdir(exist_ok=True)
        run(*data_args, ssh + ":" + remote_path + "/project/", str(target / "project") + "/")
        hashes = json.loads((target / "SHA256.json").read_text())
        require(all(Path(name).name == name for name in hashes), "Invalid checksum path")
        require(all(digest(target / name) == expected for name, expected in hashes.items()), "Archive checksum mismatch")
        require(manifest(target / "project") == (target / "runtime-manifest.jsonl").read_text(), "Runtime file checksum mismatch")
        (target / "VERIFIED").touch()
        (target / "COMPLETE").touch()
        if previous != target:
            publish_link(base, target)
        print("Verified offline snapshot (existing local research was not overwritten):", target)


def install_mac_pull():
    require(sys.platform == "darwin", "Install on the Mac host")
    home = Path.home()
    support = home / "Library/Application Support/QuantMind"
    runtime = support / "snapshot-client"
    destination = support / "cloud-snapshots"
    original = PROJECT / "logs/cloud-snapshots"
    require(not destination.exists() or original.resolve() == destination.resolve(),
            "Snapshot destination already exists separately; reconcile manually")
    # Atomic same-filesystem move; no second 68GB copy and no live sandbox change.
    support.mkdir(parents=True, exist_ok=True)
    with (original / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not original.is_symlink():
            original.rename(destination)
            original.symlink_to(destination)
    for name in ("scripts/dual_node_snapshot.py", "scripts/dual_node_inventory.py",
                 "scripts/dual_node_sync.py", "scripts/dual_node_check.py", "scripts/quantdb_refresh.py", "deploy/dual-node.env"):
        target = runtime / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / name, target)
    label = "com.quantmind.snapshot-pull"
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    logs = support / "logs"
    logs.mkdir(exist_ok=True)
    definition = {
        "Label": label,
        "ProgramArguments": [sys.executable, str(runtime / "scripts/dual_node_snapshot.py"),
                             "pull", "--root", str(destination), "--only-new", "--quantdb-project", str(PROJECT)],
        "WorkingDirectory": str(runtime), "RunAtLoad": True, "StartInterval": 3600,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(logs / "snapshot-pull.out.log"),
        "StandardErrorPath": str(logs / "snapshot-pull.err.log"),
    }
    raw = plistlib.dumps(definition)
    target = f"gui/{os.getuid()}/{label}"
    installed = subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0
    if installed and plist.exists() and plist.read_bytes() == raw:
        print("Already installed:", label)
        return
    if installed:
        run("launchctl", "bootout", target)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(raw)
    run("launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist))
    print("Installed hourly snapshot pull:", destination)


def install_signal_handlers():
    def interrupted(signum, frame):
        # Give finally a chance to restore writers even if SSH disconnects or
        # another interrupt arrives while Docker is restarting them.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        raise InterruptedError(f"Snapshot interrupted by signal {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)


if __name__ == "__main__":
    install_signal_handlers()
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "pull", "install-mac-pull"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--quantdb-project", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "create":
            cloud_snapshot()
        elif args.action == "install-mac-pull":
            install_mac_pull()
        else:
            if args.quantdb_project:
                from quantdb_refresh import refresh
                refresh(args.quantdb_project, args.root / "quantdb")
            pull_snapshot(args.root, args.only_new)
    except BusyError as exc:
        print(str(exc), flush=True)
        raise SystemExit(75)
