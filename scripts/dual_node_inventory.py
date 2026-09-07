#!/usr/bin/env python3
"""Content inventory for runtime files, excluding code and transient sync files.

Run on quiesced data. SHA256 is streamed; filenames are JSON encoded.
"""
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path


def runtime_roots(project):
    return [p for p in [project / "data", project / "db", project / "models",
            project / "user_pools_local", *sorted(project.glob("results*"))] if p.is_dir()]


def runtime_path(relative):
    parts = relative.parts
    if any(part in {".DS_Store", ".rsync-partial", "__pycache__"} for part in parts):
        return False
    if len(parts) > 1 and (parts[:2] in (("data", "stocks"), ("db", "sql")) or
                          (parts[0] == "data" and fnmatch.fnmatch(parts[1], "upgrade_v*.sql"))):
        return False
    return True


def inventory(project):
    for root in runtime_roots(project):
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(project)
            if not runtime_path(relative):
                continue
            if path.is_symlink():
                raise RuntimeError(f"Review runtime symlink before migration: {relative}")
            if not path.is_file():
                continue
            before = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                    digest.update(block)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f"File changed during inventory: {relative}")
            yield {"path": relative.as_posix(), "bytes": after.st_size,
                   "sha256": digest.hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    for item in inventory(args.project.resolve()):
        print(json.dumps(item, ensure_ascii=False, sort_keys=True))
