#!/usr/bin/env python3
"""Explicit, consistent cloud snapshots and non-destructive offline downloads.

No live database file sync or local database write-back.
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
import shlex

from dual_node_inventory import inventory, runtime_roots, runtime_files, stat_key, SNAPSHOT_EXCLUDED
from dual_node_sync import PROJECT, topology
from storage_guard import storage_lock, require_capacity, guarded_run, transfer_bytes, WRITE_MARGIN

SETTINGS = topology()
REMOTE = SETTINGS["QM_REMOTE_ROOT"]
WRITERS = ["quantmind-celery-beat", "quantmind", "quantmind-celery",
           "quantmind-huntly", "quantmind-research-worker", "quantmind-research-agent", "qwenpaw", "quantmind-tushare-worker", "quantmind-tushare-document-worker", "quantmind-redis"]


class BusyError(RuntimeError):
    pass


_guard_root = None
SCOPE = "snapshot-v2"


def run(*args, **kwargs):
    if _guard_root is not None and (args[0] in {"rsync", "tar"} or args[:3] == ("docker", "exec", "quantmind-db")):
        return guarded_run(args, _guard_root, **kwargs)
    return subprocess.run(args, check=True, **kwargs)


def transfer(*args):
    """Resume the same immutable download after a transient network failure."""
    for attempt in range(3):
        try:
            return run(*args)
        except subprocess.CalledProcessError as exc:
            if exc.returncode not in {12, 30, 35, 255} or attempt == 2:
                raise
            print(f"Transfer interrupted; resuming same snapshot (retry {attempt + 1}/2)", flush=True)
            time.sleep(5 * (attempt + 1))


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


def snapshot_scope(target):
    path = target / "snapshot-scope.json"
    return json.loads(path.read_text())["scope"] if path.exists() else "legacy"


def manifest(project, scope="legacy"):
    return "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                   for item in inventory(project, scope=scope))


def publish_link(base, target):
    temporary = base / ".latest.new"
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target.name)
    os.replace(temporary, base / "latest")


def runtime_stats(project, scope="legacy"):
    records = {}
    for path in runtime_files(project, scope, ordered=False):
        relative = path.relative_to(project)
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
        run("rsync", "-aH", "--ignore-times", "--from0", "--files-from=-",
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
    require(manifest(target / "project", scope=snapshot_scope(target)) == (target / "runtime-manifest.jsonl").read_text(),
            "Snapshot files do not match; unpublished staging retained")
    for archive in target.glob("*.tar"):
        with archive.open("rb") as src, gzip.open(str(archive) + ".gz", "wb", compresslevel=1) as dst:
            for block in iter(lambda: src.read(4 * 1024 * 1024), b""):
                if _guard_root is not None:
                    require_capacity(_guard_root, WRITE_MARGIN)
                dst.write(block)
        archive.unlink()
    hashes = {p.name: digest(p) for p in target.iterdir()
              if p.is_file() and p.name not in {"SHA256.json", "COMPLETE"}}
    (target / "SHA256.json").write_text(json.dumps(hashes, indent=2))
    (target / "COMPLETE").touch()


def prune_snapshots(base, apply=False):
    """Keep the current complete recovery point; leave staging and invalid entries alone."""
    latest = base / "latest"
    require(latest.is_symlink(), "Missing latest snapshot link; refusing to prune")
    current = latest.resolve(strict=True)
    require(current.parent == base.resolve() and current.name.startswith("snapshot-")
            and current.is_dir() and (current / "COMPLETE").is_file(),
            "Latest snapshot is not a complete child of the snapshot directory")
    candidates = sorted([p for p in base.glob("snapshot-*")
                         if p.name != current.name and p.is_dir() and not p.is_symlink()
                         and (p / "COMPLETE").is_file()]
                        + [p for p in base.glob(".deleting-snapshot-*")
                           if p.is_dir() and not p.is_symlink()])
    for path in candidates:
        print(json.dumps({"snapshot": path.name, "action": "delete" if apply else "would_delete"}), flush=True)
        if apply:
            deleting = path if path.name.startswith(".deleting-") else base / (".deleting-" + path.name)
            if path != deleting:
                path.rename(deleting)
            shutil.rmtree(deleting)
    return len(candidates)


RESEARCH_PREFIXES = ("qm-train-", "qm-agent-", "qm-frozen-", "qm-ide-run-", "qm-research-", "rdagent-")

AGENT_IDLE_CHECK = """
import asyncio, json, os, sys
from psycopg.conninfo import make_conninfo
from backend.services.research_agent.store import Store
async def check():
    node = json.load(open('/data/research/settings.json'))['node_id']
    store = Store(make_conninfo(host=os.environ.get('DB_HOST', 'db'),
        port=os.environ.get('DB_PORT', '5432'), dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD']))
    await store.pool.open()
    try:
        print(len(await store.active(node)))
    finally:
        await store.pool.close()
try:
    asyncio.run(check())
except Exception as exc:
    print(type(exc).__name__, file=sys.stderr)
    raise SystemExit(2)
"""


def require_agent_idle(active):
    if "quantmind-research-agent" in active:
        count = output("docker", "exec", "quantmind-research-agent", "python", "-c", AGENT_IDLE_CHECK)
        if count != "0":
            raise BusyError("Research agent work active or unreadable; snapshot deferred")


def _freeze_cloud_writers_locked():
    """Final window; caller holds storage lock then snapshot lock throughout."""
    require(os.geteuid() == 0 and (Path(REMOTE) / "AUTHORITY").is_file(),
            "Run only on the existing cloud authority")
    require(output("findmnt", "-n", "-o", "UUID", "-T", REMOTE) ==
            SETTINGS["QM_DISK_UUID"], "Wrong or unmounted SSD")
    require((Path(REMOTE) / "snapshots/latest/COMPLETE").is_file(),
            "Retain a complete recovery point before stopping writers")
    require(subprocess.run(["systemctl", "is-active", "--quiet",
                            "quantmind-snapshot.service"]).returncode != 0,
            "An old snapshot may restore writers; wait for it to finish")
    existing = output("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
    writers = [name for name in WRITERS
               if name in existing and name != "quantmind-redis"]
    # Do not stop the stack unit: its ExecStop also stops backing stores.
    run("systemctl", "disable", "quantmind-stack.service")
    if writers:
        run("docker", "update", "--restart=no", *writers)
    active = output("docker", "ps", "--format", "{{.Names}}").splitlines()
    if "quantmind-celery-beat" in active:
        run("docker", "stop", "--time", "60", "quantmind-celery-beat")
    require_agent_idle(active)
    for worker, app in (("quantmind-celery",
                        "backend.services.engine.qlib_app.celery_config:celery_app"),
                        ("quantmind-research-worker",
                         "backend.services.engine.research.tasks:app")):
        if worker not in active:
            continue
        for kind in ("active", "reserved", "scheduled"):
            jobs = json.loads(output("docker", "exec", worker, "celery", "-A",
                                     app, "inspect", kind, "--json", "--timeout=10"))
            require(bool(jobs) and not any(jobs.values()),
                    worker + " has " + kind + " work; dispatch remains stopped")
    require(not any(name.startswith(RESEARCH_PREFIXES) for name in active),
            "Research child still running; dispatch remains stopped")
    if writers:
        run("docker", "stop", "--time", "240", *writers)
    states = [output("docker", "inspect", "--format",
                     "{{.Name}} running={{.State.Running}} restart={{.HostConfig.RestartPolicy.Name}}",
                     name) for name in writers]
    require(all("running=false restart=no" in state for state in states),
            "Cloud writer did not freeze")
    receipt = {
        "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "previous_snapshot": (Path(REMOTE) / "snapshots/latest").resolve().name,
        "writers": states,
        "units": {unit: subprocess.run(["systemctl", "is-enabled", unit],
                   capture_output=True, text=True).stdout.strip()
                  for unit in ("quantmind-stack.service", "quantmind-snapshot.timer")},
    }
    directory = Path(REMOTE) / "maintenance/local-primary"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("freeze-" + datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"freeze_receipt": str(path), **receipt}), flush=True)


def cloud_snapshot(*, keep_writers_stopped=False):
    global _guard_root
    require(os.geteuid() == 0 and (Path(REMOTE) / "AUTHORITY").is_file(), "Run on the cloud authority after cutover")
    if keep_writers_stopped:
        # Close timer admission before taking the exact old-create lock order.
        run("systemctl", "disable", "--now", "quantmind-snapshot.timer")
    with storage_lock(PROJECT / "data/local-market-source"):
        _guard_root = Path(REMOTE)
        try:
            return _cloud_snapshot(keep_writers_stopped=keep_writers_stopped)
        finally:
            _guard_root = None


def _cloud_snapshot(*, keep_writers_stopped=False):
    require(os.geteuid() == 0 and (Path(REMOTE) / "AUTHORITY").is_file(), "Run on the cloud authority after cutover")
    require(output("findmnt", "-n", "-o", "UUID", "-T", REMOTE) == SETTINGS["QM_DISK_UUID"], "Wrong or unmounted SSD")
    base = Path(REMOTE) / "snapshots"
    base.mkdir(exist_ok=True, mode=0o700)
    with (base / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if keep_writers_stopped:
            _freeze_cloud_writers_locked()
        if not keep_writers_stopped and ((base / "latest").is_symlink() or list(base.glob("snapshot-*"))):
            prune_snapshots(base, apply=True)
        # Fail before creating a snapshot if there is insufficient recovery headroom.
        require(shutil.disk_usage(REMOTE).free > 100 * 1024**3, "Keep 100 GiB free for recovery")
        name = "snapshot-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        # Resume an unpublished attempt rather than creating another full 65 GiB copy.
        target = base / ".building"
        require(not target.exists() or snapshot_scope(target) == SCOPE,
                "Legacy staging exists; preserve and inspect before new scoped snapshot")
        target.mkdir(mode=0o700, exist_ok=True)
        (target / "snapshot-scope.json").write_text(json.dumps({"scope": SCOPE}))
        (target / "COMPLETE").unlink(missing_ok=True)
        (target / "project").mkdir(exist_ok=True)
        previous = (base / "latest").resolve()
        sources = [str(p) for p in runtime_roots(PROJECT)]
        copy = ["rsync", "-aH", "--exclude=.DS_Store", "--exclude=.rsync-partial",
                "--exclude=__pycache__", "--exclude=data/stocks/", "--exclude=data/upgrade_v*.sql",
                "--exclude=db/sql/", *["--exclude=" + path + "/" for path in SNAPSHOT_EXCLUDED]]
        if previous.is_dir():
            # Only link to an earlier IMMUTABLE snapshot, never to the live data tree.
            copy += ["--link-dest=" + str(previous / "project")]
        copy += ["--delete"]
        command = [*copy, *sources, str(target / "project") + "/"]
        estimate = subprocess.check_output([*copy, "--dry-run", "--stats", *sources,
            str(target / "project") + "/"], text=True, env={**os.environ, "LC_ALL": "C"})
        # pg_dump plus cold volumes and compression coexist. Count logical bytes
        # conservatively; postgres physical size also includes WAL and indexes.
        volume_bytes = sum(p.stat().st_size for p in (Path(REMOTE) / "volumes").rglob("*") if p.is_file())
        required = transfer_bytes(estimate) + 2 * volume_bytes + WRITE_MARGIN
        free = require_capacity(REMOTE, required)
        print(json.dumps({"phase": "capacity", "free": free, "required": required, "scope": SCOPE}), flush=True)
        run(*command)
        # Hash while the application is online. The stat cache identifies files
        # that need no delta copy; the finished copy is independently hashed.
        target_cache = {}
        copied = {r["path"]: r for r in inventory(target / "project", cache=target_cache, scope=SCOPE)}
        cache = {}
        list(inventory(PROJECT, cache=cache, tolerate_changes=True, scope=SCOPE))
        active = output("docker", "ps", "--format", "{{.Names}}").splitlines()
        if any(n.startswith(RESEARCH_PREFIXES) for n in active):
            raise BusyError("Research job active")
        require_agent_idle(active)
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
            applications = [name for name in stopped if name not in {"quantmind-redis", "quantmind-research-agent"}]
            if applications:
                run("docker", "stop", "--time", "240", *applications)
            # Stop ingress before rechecking the autonomous coordinator. An
            # active model turn is deferred, never cancelled for a backup.
            require_agent_idle(active)
            if "quantmind-research-agent" in stopped:
                run("docker", "stop", "--time", "60", "quantmind-research-agent")
            if "quantmind-redis" in stopped:
                run("docker", "stop", "--time", "60", "quantmind-redis")
            # Close the admission race: a child may have appeared during shutdown.
            active_now = output("docker", "ps", "--format", "{{.Names}}").splitlines()
            require(not any(n.startswith(RESEARCH_PREFIXES) for n in active_now),
                    "Research job appeared during quiesce; snapshot aborted")
            expected_stats = runtime_stats(PROJECT, scope=SCOPE)
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
            require(runtime_stats(PROJECT, scope=SCOPE) == expected_stats,
                    "Runtime changed during quiesced copy; unpublished staging retained")
        finally:
            # Redis is a backing store, not a business writer; restore it even
            # when the final handover intentionally keeps applications stopped.
            restore = ([name for name in stopped if name == "quantmind-redis"]
                       if keep_writers_stopped else stopped)
            if restore:
                ordered = (["quantmind-redis"] if "quantmind-redis" in restore else [])
                ordered += [name for name in restore if name != "quantmind-redis"]
                run("docker", "start", *ordered)
            print(json.dumps({"phase": ("writers_frozen" if keep_writers_stopped
                                        else "writers_restored"),
                              "pause_seconds": round(time.monotonic() - started_at, 2)}),
                  flush=True)
        # Validate only the frozen copy; final handover never restarts writers.
        expected = list(inventory(target / "project", cache=target_cache, scope=SCOPE))
        (target / "runtime-manifest.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in expected))
        if keep_writers_stopped:
            (target / "COLD_BACKUP.json").write_text(json.dumps({
                "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "source_node": SETTINGS["QM_CLOUD_HOSTNAME"],
                "stopped_writers": [name for name in WRITERS if name != "quantmind-redis"],
                "automatic_writers_disabled": True,
            }, indent=2) + "\n")
        # Independent full validation and compression touch only the frozen copy.
        # Never publish COMPLETE/latest until both have succeeded.
        finish_snapshot(target)
        published = base / name
        target.rename(published)
        publish_link(base, published)
        if not keep_writers_stopped:
            prune_snapshots(base, apply=True)
        print(published)


def dump_data_identity(path):
    """Fingerprint COPY rows and sequence state without logging business data."""
    command = ["docker", "run", "--rm", "-v", str(path.parent) + ":/snapshot:ro",
               "postgres:15-alpine", "pg_restore", "--data-only", "--no-owner",
               "--no-privileges", "--file=-", "/snapshot/" + path.name]
    tables, statements = {}, []
    current = None
    modulus = 1 << 256
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        for line in process.stdout:
            if current is not None:
                if line == b"\\.\n":
                    current = None
                else:
                    record = tables[current]
                    record["rows"] += 1
                    record["row_hash_sum"] = (
                        record["row_hash_sum"] + int.from_bytes(
                            hashlib.sha256(line).digest(), "big")) % modulus
            elif line.startswith(b"COPY "):
                current = line.decode().rstrip()
                require(current not in tables, "Duplicate COPY relation")
                tables[current] = {"rows": 0, "row_hash_sum": 0}
            elif (line.strip() and not line.startswith(
                    (b"--", b"SET ", b"SELECT pg_catalog.set_config(",
                     b"\\restrict ", b"\\unrestrict "))):
                statements.append(hashlib.sha256(line).hexdigest())
        require(process.wait() == 0, "Cannot inspect PostgreSQL dump")
    require(current is None, "Truncated PostgreSQL COPY data")
    return {"tables": tables, "other_data_statements": sorted(statements)}


def verify_restored_database(target, container, receipt):
    """Compare restored table contents/sequence state with the verified dump."""
    target, receipt = Path(target), Path(receipt)
    restored = receipt.parent / ".restore-check.dump"
    require(not restored.exists(), "Previous restore inspection retained; inspect first")
    try:
        with restored.open("xb") as stream:
            run("docker", "exec", container, "sh", "-c",
                'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z0 --no-owner',
                stdout=stream)
        expected = dump_data_identity(target / "postgres.dump")
        actual = dump_data_identity(restored)
        require(expected == actual, "Restored PostgreSQL data differs from snapshot")
        receipt.write_text(json.dumps({
            "snapshot_id": target.name,
            "postgres_dump_sha256": digest(target / "postgres.dump"),
            "restored_data_identity_sha256": hashlib.sha256(
                json.dumps(actual, sort_keys=True).encode()).hexdigest(),
            "table_count": len(actual["tables"]),
            "rows": sum(table["rows"] for table in actual["tables"].values()),
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }, indent=2) + "\n")
    finally:
        restored.unlink(missing_ok=True)


def cloud_prune(apply=False):
    require(os.geteuid() == 0 and (Path(REMOTE) / "AUTHORITY").is_file(), "Run on the cloud authority")
    require(output("findmnt", "-n", "-o", "UUID", "-T", REMOTE) == SETTINGS["QM_DISK_UUID"], "Wrong or unmounted SSD")
    base = Path(REMOTE) / "snapshots"
    with (base / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps({"candidate_count": prune_snapshots(base, apply=apply), "applied": apply}), flush=True)


def verify_snapshot(target, *, require_complete=True):
    """Rehash an offline recovery point; marker files alone prove nothing."""
    target = Path(target).resolve(strict=True)
    require(not require_complete or (target / "COMPLETE").is_file(),
            "Snapshot is incomplete")
    hashes = json.loads((target / "SHA256.json").read_text())
    require(bool(hashes) and all(Path(name).name == name for name in hashes),
            "Invalid checksum paths")
    require("runtime-manifest.jsonl" in hashes, "Missing hashed runtime manifest")
    for name, expected in hashes.items():
        require(digest(target / name) == expected, "Archive checksum mismatch: " + name)
    require(manifest(target / "project", scope=snapshot_scope(target)) ==
            (target / "runtime-manifest.jsonl").read_text(),
            "Runtime file checksum mismatch")
    return {"snapshot_id": target.name, "checksums": hashes,
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}


def verify_cloud_frozen(target):
    """Attest the exact final recovery point and persistent writer shutdown."""
    target = Path(target)
    code = """
import json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
latest = (root / 'snapshots/latest').resolve(strict=True)
assert latest.name == sys.argv[2] and (latest / 'COMPLETE').is_file()
assert (latest / 'COLD_BACKUP.json').is_file()
existing = set(subprocess.check_output(
    ['docker', 'ps', '-a', '--format', '{{.Names}}'], text=True).splitlines())
assert {'quantmind', 'quantmind-celery', 'quantmind-celery-beat'}.issubset(existing)
present = [name for name in sys.argv[3:] if name in existing]
containers = json.loads(subprocess.check_output(
    ['docker', 'inspect', *present], text=True))
writers = [c for c in containers if c['Name'] != '/quantmind-redis']
assert all(not c['State']['Running'] and
           c['HostConfig']['RestartPolicy']['Name'] == 'no' for c in writers)
units = {}
for unit in ('quantmind-stack.service', 'quantmind-snapshot.timer'):
    units[unit] = subprocess.run(['systemctl', 'is-enabled', unit],
        capture_output=True, text=True).stdout.strip()
assert all(state in ('disabled', 'masked') for state in units.values())
assert subprocess.run(['systemctl', 'is-active', '--quiet',
    'quantmind-snapshot.service']).returncode != 0
print(json.dumps({'snapshot_id': latest.name, 'units': units,
    'checksums': json.loads((latest / 'SHA256.json').read_text()),
    'writers': [{'name': c['Name'], 'running': c['State']['Running'],
        'restart': c['HostConfig']['RestartPolicy']['Name']} for c in writers]}))
"""
    # Include only containers present in this deployment; missing historical
    # optional collectors are not an excuse to skip the active writers.
    names = [name for name in WRITERS if name != "quantmind-redis"]
    remote = "sudo -n python3 -c " + shlex.quote(code) + " " + " ".join(
        shlex.quote(value) for value in [REMOTE, target.name, *names])
    receipt = json.loads(output(
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        SETTINGS["QM_SSH_TARGET"], remote))
    require(receipt["checksums"] == json.loads((target / "SHA256.json").read_text()),
            "Local recovery point differs from final cloud snapshot")
    receipt.pop("checksums")
    receipt["verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    return receipt


def pull_snapshot(base=None, only_new=False, remote_base="snapshots", snapshot_id=None):
    require(remote_base in {"snapshots", "quantdb-snapshots"}, "Invalid snapshot collection")
    print(json.dumps({"phase": "resolve_snapshot", "snapshot_id": snapshot_id or "latest",
                      "collection": remote_base}), flush=True)
    ssh = SETTINGS["QM_SSH_TARGET"]
    if snapshot_id is not None:
        require(Path(snapshot_id).name == snapshot_id and snapshot_id.startswith("snapshot-"),
                "Invalid immutable snapshot ID")
    remote_target = REMOTE + "/" + remote_base + "/" + (snapshot_id or "latest")
    remote_path = output("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh,
                         "sudo -n realpath -e " + remote_target)
    path = Path(remote_path)
    require(str(path.parent) == REMOTE + "/" + remote_base and path.name.startswith("snapshot-"), "Invalid snapshot path")
    run("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh, "sudo -n test -f " + remote_path + "/COMPLETE")
    base = base or PROJECT / "logs/cloud-snapshots"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = base.resolve()
    with (base / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = base / path.name
        unverified_resume = (snapshot_id is not None
            and not (target / "VERIFIED").exists()
            and not (target / "COMPLETE").exists()
            and (base / "latest").resolve() != target.resolve())
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
        if rsync != "rsync":
            args.append("--info=progress2")
        previous = (base / "latest").resolve()
        metadata_args = list(args)
        data_args = list(args)
        retained_runtime = None
        if unverified_resume:
            attempt = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            retained_runtime = base / "retained-unverified" / path.name / attempt / "project"
            # Only an explicit, unpublished, unverified destination is ours to
            # reconcile. Preserve removed/overwritten bytes outside its inventory.
            data_args += ["--delete", "--backup", "--backup-dir=" + str(retained_runtime)]
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
        print(json.dumps({"phase": "pull_metadata", "snapshot_id": path.name,
                          "target": str(target)}), flush=True)
        transfer(*metadata_args, "--exclude=/project/", "--exclude=/COMPLETE", ssh + ":" + remote_path + "/", str(target) + "/")
        (target / "project").mkdir(exist_ok=True)
        print(json.dumps({"phase": "pull_runtime", "snapshot_id": path.name,
                          "retained_runtime": str(retained_runtime) if retained_runtime else None}), flush=True)
        transfer(*data_args, ssh + ":" + remote_path + "/project/", str(target / "project") + "/")
        print(json.dumps({"phase": "verify_archive_and_runtime",
                          "snapshot_id": path.name}), flush=True)
        verify_snapshot(target, require_complete=False)
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
                 "scripts/dual_node_sync.py", "scripts/dual_node_check.py", "scripts/storage_guard.py", "scripts/quantdb_refresh.py", "deploy/dual-node.env"):
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
                             "pull", "--root", str(destination), "--only-new", "--quantdb-project", str(PROJECT), "--quantdb-only"],
        "WorkingDirectory": str(runtime), "RunAtLoad": True,
        # Calendar events missed during sleep coalesce into one run on wake.
        "StartCalendarInterval": [{"Minute": minute} for minute in (0, 15, 30, 45)],
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
        # bootout returns before a running job has exited; bootstrap then fails EIO.
        for _ in range(30):
            if subprocess.run(["launchctl", "print", target], capture_output=True).returncode != 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Previous snapshot client is still stopping; retry installation")
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(raw)
    run("launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist))
    print("Installed wake-aware QuantDB pull (every 15 minutes):", destination)


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
    parser.add_argument("action", choices=("create", "pull", "verify", "install-mac-pull", "prune"))
    parser.add_argument("--apply", action="store_true", help="Delete old complete cloud snapshots after a dry run")
    parser.add_argument("--keep-writers-stopped", action="store_true",
                        help="Final handover only: requires disabled cloud auto-start")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--snapshot-id",
                        help="Resume this immutable recovery point instead of following latest")
    parser.add_argument("--quantdb-project", type=Path)
    parser.add_argument("--quantdb-only", action="store_true",
                        help="Keep automatic daily data refresh independent of full backups")
    args = parser.parse_args()
    try:
        if args.action == "create":
            cloud_snapshot(keep_writers_stopped=args.keep_writers_stopped)
        elif args.action == "prune":
            cloud_prune(args.apply)
        elif args.action == "install-mac-pull":
            install_mac_pull()
        elif args.action == "verify":
            require(args.root is not None, "verify requires --root <snapshot_dir>")
            print(json.dumps(verify_snapshot(args.root), sort_keys=True))
        else:
            if args.quantdb_project:
                from quantdb_refresh import refresh
                refresh(args.quantdb_project, args.root / "quantdb")
            if not args.quantdb_only:
                pull_snapshot(args.root, args.only_new, snapshot_id=args.snapshot_id)
    except BusyError as exc:
        print(str(exc), flush=True)
        raise SystemExit(75) from exc
