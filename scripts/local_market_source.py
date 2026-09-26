#!/usr/bin/env python3
"""Mac-only vendor collection; checked file releases feed cloud and local research.

This transports market files, never databases, Redis or research results. The
existing QuantDB and Binance collectors and PG/Qlib builders remain authoritative.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dual_node_inventory import stat_key

MARKETS = {"A": ("quantdb", "03:00"), "BC": ("quantbc", "08:15")}
RELEASE = re.compile(r"market-[a-f0-9]{64}")
DEFAULT_ROOT = Path.home() / "Library/Application Support/QuantMind/market-source"
REMOTE_PROJECT = "/root/data/disk/quantmind/project"


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def transfer(*args):
    # Host topology belongs to the Mac transport, not the container receiver.
    from dual_node_snapshot import transfer as send
    return send(*args)


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def collection_day(clock, market):
    # A manual check before today's close must not consume today's later slot.
    return (clock if clock.strftime("%H:%M") >= MARKETS[market][1]
            else clock - timedelta(days=1)).strftime("%Y-%m-%d")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    os.replace(temporary, path)


def read_json(path, default=None):
    return json.loads(path.read_bytes()) if path.exists() else default


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def safe_file(project, name, market):
    part = Path(name)
    prefix = ("data", MARKETS[market][0])
    if (part.is_absolute() or part.parts[:2] != prefix or ".." in part.parts
            or any(ord(c) < 32 for c in name)):
        raise ValueError("Invalid market release path")
    path = project / part
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlinks cannot enter a market release")
    if market == "A" and path.suffix != ".parquet":
        raise ValueError("QuantDB release contains non-Parquet payload")
    return path


def verify_bundle(bundle, market):
    raw = (bundle / "runtime-manifest.jsonl").read_bytes()
    if bundle.name != "market-" + hashlib.sha256(raw).hexdigest():
        raise ValueError("Market release manifest checksum mismatch")
    rows = [json.loads(line) for line in raw.splitlines()]
    if not rows or len({r["path"] for r in rows}) != len(rows):
        raise ValueError("Empty or duplicate release inventory")
    expected = set()
    for row in rows:
        p = safe_file(bundle / "project", row["path"], market)
        if p.stat().st_size != row["bytes"] or digest(p) != row["sha256"]:
            raise ValueError("Market release content checksum mismatch: " + row["path"])
        expected.add(row["path"])
    actual = {p.relative_to(bundle / "project").as_posix()
              for p in (bundle / "project").rglob("*") if p.is_file() or p.is_symlink()}
    if actual != expected:
        raise ValueError("Unlisted or missing market release files")
    return rows


def installed_matches(data_root, rows, market):
    """Recovery only: determine which side of an interrupted rename is live."""
    try:
        for row in rows:
            safe_file(data_root.parent, row["path"], market)
            path = data_root.joinpath(*Path(row["path"]).parts[1:])
            if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                return False
        return True
    except (OSError, ValueError):
        return False


def install_quantdb_files(bundle, live, root, receipt_path, receipt, rows):
    release_id = bundle.name
    source = bundle / "project/data/quantdb"
    backup = root / "backups" / ("quantdb-before-" + release_id)
    recovering = receipt.get("release_id") == release_id and receipt.get("status") == "installing"
    if not (recovering and installed_matches(live.parent, rows, "A")):
        verify_bundle(bundle, "A")
        write_json(receipt_path, {"status": "installing", "release_id": release_id,
                                  "files": rows, "source_node": "mac"})
        if live.exists():
            if backup.exists():
                raise RuntimeError("Conflicting rollback copy; preserve and inspect")
            exchange(source, live)
        else:
            source.rename(live)
    if source.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise RuntimeError("Ambiguous interrupted installation; no data removed")
        source.rename(backup)
    receipt = {"status": "files_applied", "release_id": release_id, "files": rows,
               "installed_at": now(), "source_node": "mac"}
    write_json(receipt_path, receipt)
    return receipt


def retain_transport_copies(directory, *, protected=(), backup=False):
    """Only our completed transport copies rotate; existing archives are untouched."""
    prefix = "quantdb-before-" if backup else ""
    candidates = [p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
                  and p.name.startswith(prefix) and RELEASE.fullmatch(p.name[len(prefix):])
                  and (backup or (p / "VERIFIED").is_file())] if directory.exists() else []
    candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    keep = {p.name for p in candidates[:2]} | set(protected)
    removed = []
    for path in candidates:
        if path.name not in keep:
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


def retain_local_backups(root, project):
    ledger = root / "local-backups.json"
    entries = read_json(ledger, [])
    receipt = read_json(project / ".local-dev/QUANTDB_SYNC.json", {})
    current = {k: receipt[k] for k in ("backup", "qlib_backup") if receipt.get(k)}
    if current and current not in entries:
        entries.append(current)
    removed = []
    for entry in entries[:-2]:
        for value in entry.values():
            path = Path(value)
            if (path.parent == project / ".local-dev" and not path.is_symlink()
                    and re.fullmatch(r"(?:quantdb-before-[0-9TZ]+-[a-f0-9]+|qlib-before-[a-f0-9]+)", path.name)):
                if path.exists():
                    shutil.rmtree(path)
                removed.append(path.name)
            else:
                raise ValueError("Unexpected source-managed backup path")
    write_json(ledger, entries[-2:])
    return removed


def publish(root, market):
    """Freeze an acquisition success using APFS clones; no mutable hard links."""
    project = root / "working/project"
    data = project / "data" / MARKETS[market][0]
    cache_path = root / f"{market}-hash-cache.json"
    old = read_json(cache_path, {})
    if market == "A":
        paths = sorted(data.rglob("*.parquet"))
    else:
        current = read_json(data / "CURRENT.json")
        release = data / "releases" / current["release_id"]
        if (release.parent != data / "releases" or release.name != current["release_id"]
                or digest(release / "manifest.json") != current["manifest_sha256"]):
            raise ValueError("Invalid Binance source pointer")
        paths = [data / "CURRENT.json", *(p for p in sorted(release.rglob("*")) if p.is_file())]
    rows, updated = [], {}
    for path in paths:
        name = path.relative_to(project).as_posix()
        safe_file(project, name, market)
        before = stat_key(path.stat())
        previous = old.get(name, {})
        sha = previous.get("sha256") if previous.get("stat") == list(before) else digest(path)
        if before != stat_key(path.stat()):
            raise RuntimeError("Source changed while publishing")
        rows.append({"path": name, "bytes": path.stat().st_size, "sha256": sha})
        updated[name] = {"stat": before, "sha256": sha}
    if not rows:
        raise RuntimeError("Refusing empty source")
    raw = "".join(json.dumps(row, sort_keys=True) + "\n" for row in sorted(rows, key=lambda r: r["path"]))
    release_id = "market-" + hashlib.sha256(raw.encode()).hexdigest()
    bundle = root / "releases" / market / release_id
    if not (bundle / "VERIFIED").exists():
        bundle.mkdir(parents=True, exist_ok=True)
        target = bundle / "project/data" / MARKETS[market][0]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if market == "A":
                subprocess.run(["cp", "-cR", str(data), str(target)], check=True)
            else:
                for row in rows:
                    src, dst = project / row["path"], bundle / "project" / row["path"]
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        (bundle / "runtime-manifest.jsonl").write_text(raw)
        verify_bundle(bundle, market)
        (bundle / "COMPLETE").touch()
        (bundle / "VERIFIED").touch()
    write_json(cache_path, updated)
    return bundle


def collect(root, market):
    """Runs in an isolated local container with only its source directory writable."""
    if os.getenv("QM_NODE_ROLE") != "archive":
        raise RuntimeError("Collection requires the local archive role")
    os.environ["QUANTDB_STATE_DIR"] = str(root / "sdk-state")
    os.environ["QM_QUANTDB_DATA_DIR"] = str(root / "working/project/data/quantdb")
    os.environ["QM_QUANTBC_DATA_DIR"] = str(root / "working/project/data/quantbc")
    if market == "A":
        from backend.scripts import quantdb_daily_sync as qdb
        if not (root / "A-seeded.json").exists():
            seeded = qdb.reseed_state()
            write_json(root / "A-seeded.json", seeded)
        result = qdb.sync_parquet()
        if result.get("errors") or result.get("cancelled"):
            raise RuntimeError("QuantDB collection incomplete: " + json.dumps(result, ensure_ascii=False))
        from backend.scripts.backfill_l1_ohlcv import backfill_l1_ohlcv
        history_marker = root / "A-history-prepared.json"
        result["l1_ohlcv"] = backfill_l1_ohlcv(
            qdb.QUANTDB_DATA_DIR,
            start=None if not history_marker.exists() else now().date() - timedelta(days=10),
        )
        if not history_marker.exists():
            write_json(history_marker, {"completed_at": now(), "result": result["l1_ohlcv"]})
    else:
        from backend.scripts.quantbc_daily_sync import run
        result = run(days=5, symbols="BTCUSDT,ETHUSDT")
    write_json(root / f"{market}-collection.json", {"completed_at": now(), "result": result})
    return result


def collect_on_mac(root, market, project, secrets):
    if sys.platform != "darwin" or os.getenv("DOCKER_HOST"):
        raise RuntimeError("Collector must run on the Mac with local Docker")
    endpoint = subprocess.check_output(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True).strip()
    if not endpoint.startswith("unix://"):
        raise RuntimeError("Refusing a remote Docker collector")
    image = subprocess.check_output(["docker", "inspect", "quantmind-dev", "--format", "{{.Config.Image}}"], text=True).strip()
    root.mkdir(parents=True, exist_ok=True)
    command = ["docker", "run", "--rm", "--name", "quantmind-local-source-" + market.lower(),
               "--platform", "linux/amd64", "--memory", "2g", "--cpus", "2", "-w", "/app", "--entrypoint", "python",
               "-e", "QM_NODE_ROLE=archive", "-e", "PYTHONDONTWRITEBYTECODE=1",
               "-e", "QM_RUNTIME_ENV_FILE=/run/secrets/runtime.env",
               "-v", str(project) + ":/app:ro", "-v", str(root) + ":/source",
               "-v", str(secrets / "runtime.env") + ":/run/secrets/runtime.env:ro", image,
               "scripts/local_market_source.py", "collect", "--root", "/source", "--market", market]
    with (root / f"{market}-collection.log").open("a") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)


def ssh(host, *args):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
                           shlex.join([str(a) for a in args])], check=True)


def send_cloud(bundle, market, host):
    remote_root = Path(REMOTE_PROJECT) / "data/local-market-source"
    receipt_path = remote_root / (market + "-receipt.json")
    command = "import json,pathlib; p=pathlib.Path(" + repr(str(receipt_path)) + "); print(p.read_text() if p.exists() else '{}')"
    result = subprocess.check_output(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
        shlex.join(["sudo", "-n", "python3", "-c", command])], text=True)
    receipt = json.loads(result)
    # After directory exchange, incoming may contain the OLD rollback files.
    # Redelivery must not overwrite them before recovery finishes.
    resumable = (receipt.get("release_id") == bundle.name and
                 receipt.get("status") in ("installing", "files_applied", "applied"))
    if not resumable:
        remote = remote_root / "incoming" / market / bundle.name
        ssh(host, "sudo", "-n", "mkdir", "-p", str(remote / "project"))
        transfer("rsync", "-a", "--checksum", "--safe-links", "--rsync-path=sudo -n rsync",
                 "--link-dest=" + REMOTE_PROJECT, str(bundle / "project") + "/",
                 host + ":" + str(remote / "project") + "/")
        transfer("rsync", "-a", "--rsync-path=sudo -n rsync", str(bundle / "runtime-manifest.jsonl"),
                 host + ":" + str(remote) + "/")
    ssh(host, "sudo", "-n", "docker", "exec", "quantmind", "python", "scripts/local_market_source.py",
        "receive", "--root", "/data/local-market-source", "--market", market, "--release", bundle.name)


def exchange(left, right):
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        result = libc.renamex_np(os.fsencode(left), os.fsencode(right), 2)
    else:
        result = libc.renameat2(-100, os.fsencode(left), -100, os.fsencode(right), 2)
    if result:
        raise OSError(ctypes.get_errno(), "Atomic market directory exchange failed")


def receive(root, market, release_id, *, data_root=Path("/data")):
    if not RELEASE.fullmatch(release_id):
        raise ValueError("Invalid release identity")
    bundle = root / "incoming" / market / release_id
    receipt_path = root / (market + "-receipt.json")
    with lock(root / (market + ".receive.lock")):
        receipt = read_json(receipt_path, {})
        if receipt.get("release_id") == release_id and receipt.get("status") == "applied":
            return receipt
        if shutil.disk_usage(data_root).free < 100 * 2**30:
            raise RuntimeError("Keep 100 GiB cloud recovery reserve")
        # Resume derivation of the same already-installed source after a failure.
        resumed = receipt.get("release_id") == release_id and receipt.get("status") in ("installing", "files_applied")
        if not resumed:
            rows = verify_bundle(bundle, market)
        else:
            rows = receipt["files"]
        source = bundle / "project/data" / MARKETS[market][0]
        live = data_root / MARKETS[market][0]
        from backend.shared.quantdb_sync_jobs import acquire_lock, release_lock, keep_lock
        import threading
        token = os.urandom(16).hex()
        key = "quantmind:daily_sync:lock" if market == "A" else "quantmind:local_bc_receive:lock"
        if not acquire_lock(key, token, ttl=7200):
            raise RuntimeError("Market data busy; verified incoming version retained")
        stop = threading.Event()
        def renew():
            while not stop.wait(60):
                keep_lock(key, token, ttl=7200)
        keeper = threading.Thread(target=renew, daemon=True)
        keeper.start()
        try:
            if market == "A":
                if receipt.get("release_id") != release_id or receipt.get("status") != "files_applied":
                    receipt = install_quantdb_files(bundle, live, root, receipt_path, receipt, rows)
                from backend.scripts.quantdb_daily_sync import fill_pg_from_parquet, update_qlib_cache, _pg_latest_trade_date
                pg = fill_pg_from_parquet()
                if pg.get("status") not in ("ok", "skipped"):
                    raise RuntimeError("PG derivation incomplete")
                qlib = update_qlib_cache()
                if qlib.get("status") != "ok":
                    raise RuntimeError("Qlib derivation incomplete: " + str(qlib))
                from backend.scripts.market_snapshot.compute import refresh_snapshot
                view = refresh_snapshot(live)
                latest = max(p.name[3:] for p in (live / "1_kline_data/daily_forward").glob("dt=*"))
                from backend.shared.qlib_paths import resolve_qlib_provider_uri
                calendar = (Path(resolve_qlib_provider_uri("CN")) / "calendars/day.txt").read_text().splitlines()[-1]
                if (_pg_latest_trade_date().strftime("%Y%m%d") != latest
                        or calendar.replace("-", "") != latest or view.get("status") != "ok"):
                    raise RuntimeError("Published files, PG, Qlib or market view disagree")
                validation = {"latest_date": latest, "pg": pg, "qlib": qlib, "market_snapshot": view}
            else:
                from backend.services.engine.data_platform.quantbc_hub import load_quantbc_release_manifest
                current = read_json(source / "CURRENT.json")
                raw = source / "releases" / current["release_id"]
                manifest = load_quantbc_release_manifest(raw, verify_files=True)
                if digest(raw / "manifest.json") != current["manifest_sha256"]:
                    raise ValueError("Binance pointer checksum mismatch")
                destination = live / "releases" / raw.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copytree(raw, destination)
                load_quantbc_release_manifest(destination, verify_files=True)
                if digest(destination / "manifest.json") != current["manifest_sha256"]:
                    raise ValueError("Existing Binance release has a different identity")
                from backend.scripts.quantbc_daily_sync import prepare_research_data
                prepared = prepare_research_data(destination)
                write_json(live / "CURRENT.json", current)
                validation = {"latest_date": manifest["data_end"], "research_data": prepared,
                              "raw_release_id": raw.name, "symbols": manifest["symbols"]}
            receipt = {"status": "applied", "release_id": release_id, "source_node": "mac",
                       "completed_at": now(), "files_count": len(rows), "validation": validation}
            write_json(receipt_path, receipt)
            if market == "A":
                retain_transport_copies(root / "backups", backup=True)
            return receipt
        finally:
            stop.set()
            keeper.join(timeout=2)
            release_lock(key, token)


def tick(root, project, secrets, host, market=None, force=False):
    if sys.platform != "darwin":
        raise RuntimeError("Only the Mac schedules vendor collection")
    root.mkdir(parents=True, exist_ok=True)
    with lock(root / ".source.lock"):
        if shutil.disk_usage(root).free < 300 * 2**30:
            raise RuntimeError("Local market source keeps 300 GiB reserve")
        status_path = root / "status.json"
        state = read_json(status_path, {})
        failures = []
        for name in ([market] if market else MARKETS):
            item = state.setdefault(name, {})
            clock = now()
            day = collection_day(clock, name)
            due = force or (clock.strftime("%H:%M") >= MARKETS[name][1] and item.get("collected_day") != day)
            try:
                if due:
                    item.update(status="collecting", started_at=clock.isoformat())
                    write_json(status_path, state)
                    collect_on_mac(root, name, project, secrets)
                    bundle = publish(root, name)
                    item.update(collected_day=day, release_id=bundle.name, status="collected")
                    write_json(status_path, state)
                release_id = item.get("release_id")
                if not release_id:
                    continue
                bundle = root / "releases" / name / release_id
                if item.get("cloud_release") != release_id:
                    send_cloud(bundle, name, host)
                    item.update(cloud_release=release_id, status="cloud_applied")
                    write_json(status_path, state)
                if name == "A" and item.get("local_release") != release_id:
                    from quantdb_refresh import apply
                    apply(project, bundle)
                    item["local_release"] = release_id
                    retain_local_backups(root, project)
                elif name == "BC" and item.get("local_release") != release_id:
                    incoming = project / ".local-dev/project/data/local-market-source/incoming/BC" / release_id
                    if not incoming.exists():
                        incoming.parent.mkdir(parents=True, exist_ok=True)
                        subprocess.run(["cp", "-cR", str(bundle), str(incoming)], check=True)
                    subprocess.run(["docker", "exec", "quantmind-dev", "python", "scripts/local_market_source.py",
                                    "receive", "--root", "/data/local-market-source", "--market", "BC",
                                    "--release", release_id], check=True)
                    item["local_release"] = release_id
                item.update(status="applied", checked_at=now().isoformat())
                item.pop("error", None)
                retain_transport_copies(root / "releases" / name, protected=[release_id, item.get("local_release")])
            except Exception as exc:
                item.update(status="retry_pending", error=str(exc), checked_at=now().isoformat())
                failures.append(name)
            write_json(status_path, state)
        print(json.dumps(state, ensure_ascii=False, default=str), flush=True)
        return 2 if failures else 0


def install(project, root, secrets, host):
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent installation is Mac-only")
    runtime = root.parent / "market-source-client"
    for relative in ("scripts/local_market_source.py", "scripts/dual_node_snapshot.py", "scripts/dual_node_inventory.py",
                     "scripts/dual_node_sync.py", "scripts/dual_node_check.py", "scripts/quantdb_refresh.py", "deploy/dual-node.env"):
        target = runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / relative, target)
    label = "com.quantmind.market-source"
    log = root.parent / "logs"
    log.mkdir(parents=True, exist_ok=True)
    definition = {"Label": label, "RunAtLoad": True, "WorkingDirectory": str(runtime),
                  "StartCalendarInterval": [{"Minute": m} for m in (0, 15, 30, 45)],
                  "ProgramArguments": [sys.executable, str(runtime / "scripts/local_market_source.py"), "tick",
                                       "--root", str(root), "--project", str(project), "--secrets", str(secrets), "--host", host],
                  "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
                  "StandardOutPath": str(log / "market-source.out.log"), "StandardErrorPath": str(log / "market-source.err.log")}
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    target = f"gui/{os.getuid()}/{label}"
    if subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0:
        subprocess.run(["launchctl", "bootout", target], check=True)
    plist.write_bytes(plistlib.dumps(definition))
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "publish", "receive", "tick", "install"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--secrets", type=Path)
    parser.add_argument("--host", default="lzy-vm")
    parser.add_argument("--market", choices=tuple(MARKETS))
    parser.add_argument("--release")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.action in ("collect", "publish", "receive") and not args.market:
        parser.error("market is required")
    if args.action == "collect":
        print(json.dumps(collect(args.root, args.market), default=str))
    elif args.action == "publish":
        print(publish(args.root, args.market))
    elif args.action == "receive":
        print(json.dumps(receive(args.root, args.market, args.release), default=str))
    elif args.action == "install":
        install(args.project, args.root, args.secrets or args.project / "config", args.host)
    else:
        return tick(args.root, args.project, args.secrets or args.project / "config", args.host, args.market, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
