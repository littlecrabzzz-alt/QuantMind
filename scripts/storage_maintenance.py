"""Plan storage cleanup, then apply only a confirmed, revalidated plan."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _absolute(path):
    # Preserve symlinks so candidate eligibility can reject them.
    return Path(os.path.abspath(Path(path).expanduser()))


def _real_directory(path, app_root):
    """Reject symlinks throughout the managed tree, including its parent."""
    if not path.is_dir():
        return False
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            return False
        if ancestor == app_root.parent:
            break
    return True


def _allocated_bytes(path):
    total = 0

    def fail(error):
        raise error

    for directory, _, files in os.walk(path, followlinks=False, onerror=fail):
        for name in files:
            info = (Path(directory) / name).lstat()
            if stat.S_ISREG(info.st_mode):
                total += info.st_blocks * 512
    return total


def build_plan(app_root: Path, project_root: Path, keep_newest: int = 1) -> dict:
    """Read completed copies and references without changing any files."""
    if not isinstance(keep_newest, int) or keep_newest < 0:
        raise ValueError("keep_newest must be a nonnegative integer")
    app_root, project_root = _absolute(app_root), _absolute(project_root)
    source = app_root / "market-source"
    reference_paths = sorted(source.glob("*.json"))
    reference_paths += [project_root / ".local-dev" / name
                        for name in ("SNAPSHOT_ID", "QUANTDB_SYNC.json")]
    references = [(str(path), path.read_text(encoding="utf-8"))
                  for path in reference_paths if path.is_file()]

    releases = source / "releases"
    groups = []
    if _real_directory(releases, app_root):
        groups.extend((market.name, market, "", True)
                      for market in sorted(releases.iterdir())
                      if _real_directory(market, app_root))
    cloud = app_root / "cloud-snapshots"
    groups += [("cloud-snapshots", cloud, "snapshot-", False),
               ("quantdb", cloud / "quantdb", "snapshot-quantdb-", False)]

    plan = {"created_at": _now(), "keep": [], "delete": [], "total_bytes": 0}
    for group, directory, prefix, verified in groups:
        if not _real_directory(directory, app_root):
            continue
        candidates = [path for path in directory.iterdir()
                      if path.name.startswith(prefix)
                      and _real_directory(path, app_root)
                      and (path / "COMPLETE").is_file()
                      and (not verified or (path / "VERIFIED").is_file())]
        candidates.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
        newest = set(candidates[:keep_newest])
        latest_link = directory / "latest"
        latest = latest_link.resolve() if latest_link.is_symlink() else None
        for path in candidates:
            reasons = [f"Referenced by {reference}"
                       for reference, content in references if path.name in content]
            if latest == path.resolve():
                reasons.append("Target of latest symlink")
            if path in newest:
                reasons.append(f"Among newest {keep_newest} copies in group")
            entry = {"path": str(path), "group": group}
            if reasons:
                entry["reason"] = "; ".join(reasons)
                plan["keep"].append(entry)
            else:
                entry["bytes"] = _allocated_bytes(path)
                plan["delete"].append(entry)
                plan["total_bytes"] += entry["bytes"]
    for key in ("keep", "delete"):
        plan[key].sort(key=lambda entry: entry["path"])
    return plan


def write_plan(plan: dict, out_path: Path) -> str:
    raw = (json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    Path(out_path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def apply_plan(plan_path, confirm_sha, app_root, project_root, receipt_dir,
               keep_newest=1) -> dict:
    raw = Path(plan_path).read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if confirm_sha != actual_sha:
        raise ValueError("Confirmation SHA does not match plan file")
    plan = json.loads(raw)
    current = build_plan(app_root, project_root, keep_newest)
    allowed = {entry["path"]: entry for entry in current["delete"]}
    paths = [entry["path"] for entry in plan["delete"]]
    if len(paths) != len(set(paths)):
        raise ValueError("Plan contains duplicate deletion paths")
    for path in paths:
        if path not in allowed:
            raise ValueError(f"Deletion is no longer eligible: {path}")

    receipt_dir = _absolute(receipt_dir)
    if any(receipt_dir == Path(path) or Path(path) in receipt_dir.parents
           for path in paths):
        raise ValueError("Receipt directory must be outside deleted copies")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {"created_at": _now(), "plan_sha256": actual_sha, "removed": []}
    receipt_path = receipt_dir / f"storage-{uuid.uuid4().hex}.json"
    # Preserve evidence of successful removals even if a later rmtree fails.
    try:
        for path in paths:
            shutil.rmtree(path)
            receipt["removed"].append({"path": path, "bytes": allowed[path]["bytes"]})
    finally:
        write_plan(receipt, receipt_path)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "apply"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--app-root", type=Path,
                               default=Path.home() / "Library/Application Support/QuantMind")
        subparser.add_argument("--project-root", type=Path,
                               default=Path(__file__).resolve().parent.parent)
        subparser.add_argument("--keep-newest", type=int, default=1)
        if command == "plan":
            subparser.add_argument("--out", type=Path, required=True)
        else:
            subparser.add_argument("--plan", type=Path, required=True)
            subparser.add_argument("--confirm", required=True)
            subparser.add_argument("--receipt-dir", type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        plan = build_plan(args.app_root, args.project_root, args.keep_newest)
        sha = write_plan(plan, args.out)
        print(f"sha256={sha} total_bytes={plan['total_bytes']}")
    else:
        receipt_dir = args.receipt_dir or args.app_root / "maintenance/storage-receipts"
        receipt = apply_plan(args.plan, args.confirm, args.app_root,
                             args.project_root, receipt_dir, args.keep_newest)
        print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
