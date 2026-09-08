#!/usr/bin/env python3
"""Explicit, consistent cloud snapshots and non-destructive offline downloads.

No live database file sync, no local database write-back, no automatic pruning.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from dual_node_inventory import inventory, runtime_roots
from dual_node_sync import PROJECT, topology

SETTINGS = topology()
REMOTE = SETTINGS["QM_REMOTE_ROOT"]
WRITERS = ["quantmind-celery-beat", "quantmind", "quantmind-celery",
           "quantmind-huntly", "qwenpaw", "quantmind-redis"]


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
        active = output("docker", "ps", "--format", "{{.Names}}").splitlines()
        if any(n.startswith(("qm-train-", "qm-agent-", "qm-frozen-")) for n in active):
            raise BusyError("Research job active")
        if "quantmind-celery" in active:
            jobs = json.loads(output("docker", "exec", "quantmind-celery", "celery", "-A",
                "backend.services.engine.qlib_app.celery_config:celery_app", "inspect", "active", "--json", "--timeout=15"))
            require(bool(jobs), "No Celery worker response")
            if any(jobs.values()):
                raise BusyError("Celery work active")
        stopped = [name for name in WRITERS if name in active]
        try:
            applications = [name for name in stopped if name != "quantmind-redis"]
            if applications:
                run("docker", "stop", "--time", "120", *applications)
            if "quantmind-redis" in stopped:
                run("docker", "stop", "--time", "60", "quantmind-redis")
            run(*copy, "--checksum", "--delete-delay", *sources, str(target / "project") + "/")
            expected = manifest(PROJECT)
            require(expected == manifest(target / "project"), "Snapshot files do not match")
            (target / "runtime-manifest.jsonl").write_text(expected)
            with (target / "postgres.dump").open("wb") as stream:
                run("docker", "exec", "quantmind-db", "sh", "-c",
                    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner', stdout=stream)
            for volume in ("redis-data", "qwenpaw-data", "qwenpaw-secrets", "qwenpaw-backups", "qwenpaw-shared"):
                run("tar", "-czf", str(target / (volume + ".tar.gz")), "-C", REMOTE + "/volumes/" + volume, ".")
            hashes = {p.name: digest(p) for p in target.iterdir()
                      if p.is_file() and p.name not in {"SHA256.json", "COMPLETE"}}
            (target / "SHA256.json").write_text(json.dumps(hashes, indent=2))
            (target / "COMPLETE").touch()
            published = base / name
            target.rename(published)
            publish_link(base, published)
        finally:
            if stopped:
                ordered = (["quantmind-redis"] if "quantmind-redis" in stopped else [])
                ordered += [name for name in stopped if name != "quantmind-redis"]
                run("docker", "start", *ordered)
        print(published)


def pull_snapshot():
    ssh = SETTINGS["QM_SSH_TARGET"]
    remote_path = output("ssh", "-o", "BatchMode=yes", ssh,
                         "sudo -n realpath -e " + REMOTE + "/snapshots/latest")
    path = Path(remote_path)
    require(str(path.parent) == REMOTE + "/snapshots" and path.name.startswith("snapshot-"), "Invalid snapshot path")
    run("ssh", ssh, "sudo -n test -f " + remote_path + "/COMPLETE")
    base = PROJECT / "logs/cloud-snapshots"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (base / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = base / path.name
        target.mkdir(exist_ok=True)
        rsync = "/opt/homebrew/bin/rsync" if Path("/opt/homebrew/bin/rsync").exists() else "rsync"
        args = [rsync, "-a", "--checksum", "--no-owner", "--no-group", "--compress", "--partial", "--rsync-path=sudo -n rsync"]
        previous = (base / "latest").resolve()
        metadata_args = list(args)
        data_args = list(args)
        if previous.is_dir() and previous != target:
            metadata_args += ["--link-dest=" + str(previous)]
            data_args += ["--link-dest=" + str(previous / "project")]
        else:
            # First download reuses matching local bytes WITHOUT hard-linking live data.
            data_args += ["--copy-dest=" + str(PROJECT)]
            backups = sorted((PROJECT / "logs").glob("dual-node-*/postgres.dump"))
            if backups:
                # PostgreSQL dump headers can change; rsync still reuses matching blocks.
                metadata_args += ["--copy-dest=" + str(backups[-1].parent.resolve())]
        run(*metadata_args, "--exclude=/project/", ssh + ":" + remote_path + "/", str(target) + "/")
        (target / "project").mkdir(exist_ok=True)
        run(*data_args, ssh + ":" + remote_path + "/project/", str(target / "project") + "/")
        hashes = json.loads((target / "SHA256.json").read_text())
        require(all(Path(name).name == name for name in hashes), "Invalid checksum path")
        require(all(digest(target / name) == expected for name, expected in hashes.items()), "Archive checksum mismatch")
        require(manifest(target / "project") == (target / "runtime-manifest.jsonl").read_text(), "Runtime file checksum mismatch")
        if previous != target:
            publish_link(base, target)
        print("Verified offline snapshot (existing local research was not overwritten):", target)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "pull"))
    action = parser.parse_args().action
    try:
        cloud_snapshot() if action == "create" else pull_snapshot()
    except BusyError as exc:
        print(str(exc), flush=True)
        raise SystemExit(75)
