#!/usr/bin/env python3
"""Preserve frozen ashare worktrees without changing their files or Git state.

One content-addressed copy, original-path views, SQLite/JSONL identities, all refs,
working patches, ignored files and symlink identities. This is migration, not a
backtest or a data refresh. A capture destination must not already exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
from datetime import datetime, timezone

NAMES = (
    "ashare-lab", "ashare-lab-aline", "ashare-lab-bline", "ashare-lab-paper",
    "ashare-lab-paper-s1", "ashare-lab-expansion", "ashare-lab-ideas",
    "ashare-lab-ideas-cb", "ashare-lab-ideas-cta",
)
RESEARCH = ("qdii-relative-20261013", "crypto-breakout-20261013")


def git(root, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args])


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def capture(args):
    dest = args.destination.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    blobs = dest / "objects/sha256"
    blobs.mkdir(parents=True)
    db = sqlite3.connect(dest / "manifest.sqlite")
    db.executescript("""
        CREATE TABLE trees(name TEXT PRIMARY KEY, source TEXT NOT NULL,
                           commit_id TEXT, branch TEXT, manifest_sha256 TEXT,
                           files INTEGER, bytes INTEGER);
        CREATE TABLE files(tree TEXT, path TEXT, original_path TEXT, kind TEXT,
                           size INTEGER, sha256 TEXT, mode INTEGER, mtime_ns INTEGER,
                           git_state TEXT, link_target TEXT, object_path TEXT,
                           PRIMARY KEY(tree,path));
        CREATE INDEX files_hash ON files(sha256);
        CREATE INDEX files_kind ON files(kind,git_state);
    """)
    roots = [(name, args.source_parent / name) for name in NAMES]
    roots += [(name, args.research_parent / name) for name in RESEARCH]
    identities = []
    unique_bytes = 0
    unique_files = 0
    # Hash each inode once; links to the same source file retain separate paths.
    hashes = {}
    symlinks = []
    for name, root in roots:
        root = root.absolute()
        if not root.is_dir():
            raise FileNotFoundError(root)
        view = dest / "trees" / name
        view.mkdir(parents=True)
        tracked, ignored = set(), set()
        identity = {"name": name, "source": str(root)}
        if name in NAMES:
            tracked = set(git(root, "ls-files", "-z").decode().split("\0"))
            ignored = set(git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").decode().split("\0"))
            meta = dest / "git" / name
            meta.mkdir(parents=True)
            identity.update(
                commit=git(root, "rev-parse", "HEAD").decode().strip(),
                branch=git(root, "branch", "--show-current").decode().strip(),
                git_dir=git(root, "rev-parse", "--absolute-git-dir").decode().strip(),
                status=git(root, "status", "--porcelain=v1", "--untracked-files=all").decode(),
                refs=git(root, "show-ref").decode(),
            )
            (meta / "working.patch").write_bytes(git(root, "diff", "--binary", "HEAD"))
            (meta / "index.patch").write_bytes(git(root, "diff", "--binary", "--cached"))
            dump(meta / "identity.json", identity)
            if name == NAMES[0]:
                subprocess.run(["git", "-C", str(root), "bundle", "create", str(dest / "git/all-refs.bundle"), "--all"], check=True)
                identity["git_bundle"] = "git/all-refs.bundle"
        count = total = 0
        manifest = dest / "manifests" / f"{name}.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("w") as records:
            for directory, dirs, files in os.walk(root, followlinks=False):
                dirs.sort()
                files.sort()
                # os.walk lists symlink directories separately; preserve them too.
                links = [item for item in dirs if (Path(directory) / item).is_symlink()]
                dirs[:] = [item for item in dirs if item not in links]
                for filename in sorted(files + links):
                    source = Path(directory) / filename
                    rel = source.relative_to(root)
                    out = view / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    info = source.lstat()
                    state = "tracked" if str(rel) in tracked else "ignored" if str(rel) in ignored else "untracked" if name in NAMES else "research-artifact"
                    record = {"tree": name, "path": str(rel), "original_path": str(source),
                              "mode": stat.S_IMODE(info.st_mode), "mtime_ns": info.st_mtime_ns,
                              "git_state": state, "link_target": None, "object_path": None}
                    if source.is_symlink():
                        target = os.readlink(source)
                        record.update(kind="symlink", size=len(os.fsencode(target)),
                                      sha256=hashlib.sha256(os.fsencode(target)).hexdigest(), link_target=target)
                        symlinks.append((source, out, target))
                    elif source.is_file():
                        key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                        sha = hashes.get(key)
                        if sha is None:
                            sha = digest(source)
                            hashes[key] = sha
                        obj = blobs / sha[:2] / sha[2:]
                        if not obj.exists():
                            obj.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, obj)
                            # Hash copied bytes too: changing source cannot silently
                            # publish an object under another file's identity.
                            if digest(obj) != sha:
                                raise RuntimeError(f"Source changed during capture: {source}")
                            obj.chmod(0o444)
                            unique_bytes += info.st_size
                            unique_files += 1
                        # Readonly views share only archive-owned objects, never old trees.
                        os.link(obj, out)
                        record.update(kind="file", size=info.st_size, sha256=sha,
                                      object_path=str(obj.relative_to(dest)))
                    else:
                        raise RuntimeError(f"Unsupported non-file artifact: {source}")
                    records.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(record[k] for k in (
                        "tree", "path", "original_path", "kind", "size", "sha256", "mode", "mtime_ns", "git_state", "link_target", "object_path")))
                    count += 1
                    total += record["size"]
        identity.update(files=count, bytes=total, manifest=str(manifest.relative_to(dest)),
                        manifest_sha256=digest(manifest))
        db.execute("INSERT INTO trees VALUES (?,?,?,?,?,?,?)", (name, str(root), identity.get("commit"), identity.get("branch"), identity["manifest_sha256"], count, total))
        db.commit()
        identities.append(identity)
        print(json.dumps({k: identity[k] for k in ("name", "files", "bytes", "manifest_sha256")}), flush=True)
    # Rewrite only snapshot link destinations, retaining the original link text
    # in the manifest. Links within the nine trees never point back outside.
    for source, out, target in symlinks:
        resolved = source.resolve(strict=False)
        archived = None
        for name, root in roots:
            try:
                archived = dest / "trees" / name / resolved.relative_to(root.resolve())
                break
            except ValueError:
                continue
        out.symlink_to(os.path.relpath(archived, out.parent) if archived else target)
    db.close()
    bundle = dest / "git/all-refs.bundle"
    summary = {"schema": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
               "policy": "frozen research/observation; not strategy-pass or live permission",
               "trees": identities, "unique_objects": unique_files, "unique_bytes": unique_bytes,
               "bundle_sha256": digest(bundle), "manifest_sqlite_sha256": digest(dest / "manifest.sqlite")}
    dump(dest / "identity.json", summary)
    for metadata in (dest / "identity.json", dest / "manifest.sqlite"):
        metadata.chmod(0o444)
    for folder in (dest / "manifests", dest / "git"):
        for metadata in folder.rglob("*"):
            if metadata.is_file():
                metadata.chmod(0o444)
    print(json.dumps({"destination": str(dest), "unique_objects": unique_files,
                      "unique_bytes": unique_bytes, "identity_sha256": digest(dest / "identity.json")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-parent", type=Path, required=True)
    parser.add_argument("--research-parent", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    capture(parser.parse_args())


if __name__ == "__main__":
    main()
