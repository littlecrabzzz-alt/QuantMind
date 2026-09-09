"""Recover existing immutable Tushare evidence into a resumable local index.

No provider calls, credentials or Pipeline dependency. Publication is the caller's
responsibility. Recovery completeness is never upstream historical completeness.
"""

from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time

DIRECTORIES = (
    "objects",
    "observations",
    "parquet",
    "attachments",
    "extracted",
    "schemas",
    "documents",
    "archives",
)
FILE_PATTERN = re.compile(
    r"(?:objects/[a-f0-9]{64}\.json|observations/[a-f0-9]{32,64}\.json|"
    r"parquet/[a-f0-9]{64}\.parquet|attachments/[a-f0-9]{64}\.(?:pdf|html|bin)|"
    r"extracted/[a-f0-9]{64}\.json|"
    r"(?:archives|schemas|documents)/[a-f0-9]{64}\.json)"
)
RELEASE_PATTERN = re.compile(r"(?:data-[a-f0-9]{64}|probe-[a-f0-9]{32})")


class ArchiveError(ValueError):
    pass


class Deadline(Exception):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _safe(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ArchiveError("invalid_path")
    path = Path(relative)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ArchiveError("path_escape")
    target = root
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ArchiveError("symlink")
    if not stat.S_ISREG(target.stat().st_mode):
        raise ArchiveError("not_regular_file")
    return target


def _fingerprint(path, deadline):
    if time.monotonic() >= deadline:
        raise Deadline
    sha, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
            size += len(block)
    return sha.hexdigest(), size


def _db(root):
    if (root / "archive.sqlite").is_symlink():
        raise ArchiveError("unsafe_archive_database")
    db = sqlite3.connect(root / "archive.sqlite", timeout=10)
    db.row_factory = sqlite3.Row
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        db.close()
        raise ArchiveError("unsupported_archive_schema")
    if version == 0:
        db.executescript("""
            BEGIN;
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE tasks(id TEXT PRIMARY KEY,kind TEXT NOT NULL,path TEXT NOT NULL,
                expected TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',cursor INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX tasks_pending ON tasks(state);
            CREATE TABLE files(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
                dataset TEXT,valid INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE archived_releases(release_id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT NOT NULL);
            CREATE TABLE gaps(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,payload TEXT NOT NULL,resolved INTEGER NOT NULL DEFAULT 0);
            PRAGMA user_version=1;
            COMMIT;
        """)
    return db


def _task(db, kind, path, expected=None):
    expected = expected or {}
    identity = {
        k: v for k, v in expected.items() if k not in ("release_id", "observation")
    }
    key = _hash(_json([kind, path, identity]).encode())
    db.execute(
        "INSERT OR IGNORE INTO tasks(id,kind,path,expected) VALUES(?,?,?,?)",
        (key, kind, path, _json(expected)),
    )


def _gap(db, row, code, detail=None):
    payload = {"path": row["path"], "kind": row["kind"], "reason": code}
    source = json.loads(row["expected"]).get("release_id")
    if source:
        payload["source_release_id"] = source
    if detail:
        payload["detail"] = detail
    key = _hash(_json([row["id"], payload]).encode())
    db.execute(
        "INSERT INTO gaps(id,task_id,payload,resolved) VALUES(?,?,?,0) ON CONFLICT(id) DO UPDATE SET resolved=0",
        (key, row["id"], _json(payload)),
    )


def _queue_releases(root, db):
    release_root = root / "releases"
    if release_root.exists() or release_root.is_symlink():
        if release_root.is_symlink() or not release_root.is_dir():
            _task(db, "invalid", "releases")
        else:
            for entry in sorted(release_root.iterdir()):
                if not entry.name.startswith("."):
                    _task(db, "manifest", f"releases/{entry.name}/manifest.json")
    db.execute("INSERT OR REPLACE INTO meta VALUES('release_catchup','1')")


def _snapshot(root, db, rescan):
    if db.execute("SELECT 1 FROM meta WHERE key='snapshot'").fetchone() and not rescan:
        return
    if rescan:
        db.execute("UPDATE tasks SET state='pending',cursor=0")
        db.execute("UPDATE files SET valid=0")
        for saved in db.execute("SELECT path FROM files").fetchall():
            _task(db, "file", saved[0])
    _queue_releases(root, db)
    for directory in DIRECTORIES:
        parent = root / directory
        if not parent.exists() and not parent.is_symlink():
            continue
        if parent.is_symlink() or not parent.is_dir():
            _task(db, "invalid", directory)
            continue
        for entry in sorted(parent.iterdir()):
            # Temporary writes are not committed immutable evidence.
            if entry.name.startswith(".") or entry.name.endswith(".tmp"):
                continue
            _task(db, "file", f"{directory}/{entry.name}")
    db.execute(
        "INSERT INTO meta(key,value) VALUES('snapshot','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
    )
    db.commit()  # Freeze membership once; interrupted initialization rolls back.


def _register(db, path, sha, size, dataset=None):
    existing = db.execute(
        "SELECT sha256,bytes,dataset FROM files WHERE path=?", (path,)
    ).fetchone()
    if existing and (existing["sha256"] != sha or existing["bytes"] != size):
        raise ArchiveError("immutable_file_conflict")
    if existing and existing["dataset"] and dataset:
        if json.loads(existing["dataset"]).get("api_name") != dataset.get("api_name"):
            raise ArchiveError("dataset_identity_conflict")
    db.execute(
        "INSERT INTO files(path,sha256,bytes,dataset,valid) VALUES(?,?,?,?,1) ON CONFLICT(path) DO UPDATE SET dataset=COALESCE(excluded.dataset,files.dataset),valid=1",
        (path, sha, size, _json(dataset) if dataset else None),
    )


@contextmanager
def _alias_parent(root, relative, *, create=False):
    """Pin each directory without following symlinks during alias publication."""
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ArchiveError("symlink")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in Path(relative).parent.parts:
            if create:
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def link_manifest_alias(root, source, destination, expected):
    """Create only a verified release/archive alias; preserve every existing file.

    Directory descriptors and O_NOFOLLOW pin source identity against path swaps.
    Same-filesystem files share an inode; EXDEV copies exact verified bytes.
    Missing source returns False, allowing the mirror's normal transfer path.
    """
    pattern = r"(?:archives/([a-f0-9]{64})\.json|releases/(data-[a-f0-9]{64}|probe-[a-f0-9]{32})/manifest\.json)"
    matches = [
        re.fullmatch(pattern, name) if isinstance(name, str) else None
        for name in (source, destination)
    ]
    if not all(matches) or source.startswith("archives/") == destination.startswith(
        "archives/"
    ):
        raise ArchiveError("invalid_manifest_alias")
    sha, size = expected.get("sha256"), expected.get("bytes")
    if (
        not isinstance(sha, str)
        or not re.fullmatch(r"[a-f0-9]{64}", sha)
        or type(size) is not int
        or size < 0
    ):
        raise ArchiveError("invalid_manifest_metadata")
    for match in matches:
        named_sha = match[1] or (match[2][5:] if match[2].startswith("data-") else sha)
        if named_sha != sha:
            raise ArchiveError("manifest_alias_hash_identity_mismatch")
    root = Path(root).absolute()
    source_name, target_name = Path(source).name, Path(destination).name
    try:
        with _alias_parent(root, source) as source_dir:
            source_fd = os.open(
                source_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=source_dir,
            )
            try:
                before = os.fstat(source_fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                    raise ArchiveError("manifest_alias_source_mismatch")

                def verify(fd):
                    initial = os.fstat(fd)
                    if not stat.S_ISREG(initial.st_mode) or initial.st_size != size:
                        raise ArchiveError("manifest_alias_not_regular_file")
                    os.lseek(fd, 0, os.SEEK_SET)
                    digest = hashlib.sha256()
                    while block := os.read(fd, 1024 * 1024):
                        digest.update(block)
                    final = os.fstat(fd)
                    if (initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns) != (
                        final.st_size,
                        final.st_mtime_ns,
                        final.st_ctime_ns,
                    ):
                        raise ArchiveError("manifest_alias_file_changed")
                    if digest.hexdigest() != sha:
                        raise ArchiveError("manifest_alias_checksum_mismatch")

                verify(source_fd)
                after = os.fstat(source_fd)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise ArchiveError("manifest_alias_source_changed")
                with _alias_parent(root, destination, create=True) as target_dir:
                    temporary = ".archive-alias-" + os.urandom(12).hex()
                    try:
                        try:
                            os.link(
                                source_name,
                                temporary,
                                src_dir_fd=source_dir,
                                dst_dir_fd=target_dir,
                                follow_symlinks=False,
                            )
                        except OSError as error:
                            if error.errno != errno.EXDEV:
                                raise
                            fd = os.open(
                                temporary,
                                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                0o600,
                                dir_fd=target_dir,
                            )
                            with os.fdopen(fd, "wb") as stream:
                                os.lseek(source_fd, 0, os.SEEK_SET)
                                while block := os.read(source_fd, 1024 * 1024):
                                    stream.write(block)
                                stream.flush()
                                os.fsync(stream.fileno())
                        else:
                            linked = os.stat(
                                temporary, dir_fd=target_dir, follow_symlinks=False
                            )
                            if (linked.st_dev, linked.st_ino) != (
                                before.st_dev,
                                before.st_ino,
                            ):
                                raise ArchiveError("manifest_alias_source_replaced")
                        fd = os.open(
                            temporary,
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=target_dir,
                        )
                        try:
                            if os.fstat(fd).st_size != size:
                                raise ArchiveError("manifest_alias_source_changed")
                            verify(fd)
                        finally:
                            os.close(fd)
                        try:
                            os.link(
                                temporary,
                                target_name,
                                src_dir_fd=target_dir,
                                dst_dir_fd=target_dir,
                                follow_symlinks=False,
                            )
                        except FileExistsError:
                            fd = os.open(
                                target_name,
                                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=target_dir,
                            )
                            try:
                                if os.fstat(fd).st_size != size:
                                    raise ArchiveError(
                                        "manifest_alias_destination_mismatch"
                                    )
                                verify(fd)
                            finally:
                                os.close(fd)
                        published = _safe(root, destination).stat()
                        pinned = os.stat(
                            target_name, dir_fd=target_dir, follow_symlinks=False
                        )
                        if (published.st_dev, published.st_ino) != (
                            pinned.st_dev,
                            pinned.st_ino,
                        ):
                            raise ArchiveError("manifest_alias_directory_changed")
                        os.fsync(target_dir)
                    finally:
                        try:
                            os.unlink(temporary, dir_fd=target_dir)
                        except FileNotFoundError:
                            pass
            finally:
                os.close(source_fd)
    except FileNotFoundError:
        return False
    return True


def _copy_manifest(root, raw, release=None):
    sha = _hash(raw)
    directory = root / "archives"
    if directory.is_symlink():
        raise ArchiveError("symlink")
    directory.mkdir(exist_ok=True)
    destination = directory / (sha + ".json")
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or destination.read_bytes() != raw:
            raise ArchiveError("archive_copy_conflict")
    elif release is not None and link_manifest_alias(
        root,
        f"releases/{release}/manifest.json",
        f"archives/{sha}.json",
        {"sha256": sha, "bytes": len(raw)},
    ):
        pass
    else:
        fd, temporary = tempfile.mkstemp(prefix=".archive-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
        finally:
            os.unlink(temporary)
    return "archives/" + destination.name, sha


def _record_release(root, db, release, raw, *, source_metadata=None):
    # The publisher already decoded this SHA-pinned predecessor. Reuse that
    # document, but reverify actual source/archive bytes with the existing safe
    # streaming alias implementation instead of allocating another raw body.
    if source_metadata is None:
        sha, size = _hash(raw), len(raw)
    else:
        if not re.fullmatch(r"data-[a-f0-9]{64}", release):
            raise ArchiveError("invalid_predecessor_identity")
        sha, size = source_metadata["sha256"], source_metadata["bytes"]
        if sha != release[5:]:
            raise ArchiveError("manifest_checksum_mismatch")
    old = db.execute(
        "SELECT sha256 FROM archived_releases WHERE release_id=?", (release,)
    ).fetchone()
    if old and old[0] != sha:
        raise ArchiveError("immutable_release_conflict")
    if source_metadata is None:
        path, sha = _copy_manifest(root, raw, release)
    else:
        path = "archives/" + sha + ".json"
        if (root / path).is_symlink():
            raise ArchiveError("archive_copy_conflict")
        if not link_manifest_alias(
            root, f"releases/{release}/manifest.json", path, source_metadata
        ):
            raise ArchiveError("missing_predecessor_manifest")
    _register(db, path, sha, size)
    db.execute(
        "INSERT OR IGNORE INTO archived_releases VALUES(?,?,?)", (release, path, sha)
    )
    return path, {"sha256": sha, "bytes": size}


def _manifest_document(root, release):
    if not isinstance(release, str) or not RELEASE_PATTERN.fullmatch(release):
        raise ArchiveError("invalid_release_id")
    raw = _safe(root, f"releases/{release}/manifest.json").read_bytes()
    if release.startswith("data-") and release[5:] != _hash(raw):
        raise ArchiveError("manifest_checksum_mismatch")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ArchiveError("invalid_manifest")
    return raw, document


def _expected_files(root, release, document, *, collect=True):
    """Supplier manifest expectations, NOT a fresh referenced-object validation."""
    files = document.get("files")
    if release.startswith("data-"):
        if not isinstance(files, dict):
            raise ArchiveError("invalid_file_inventory")
        entries = files.items()
    elif isinstance(files, list):
        entries = [
            (item.get("path"), item) if isinstance(item, dict) else (item, {})
            for item in files
        ]
    elif isinstance(document.get("results"), list):
        entries = []
        for result in document["results"]:
            if not isinstance(result, dict) or "observation" not in result:
                continue
            entries.extend(
                [
                    (
                        "observations/" + str(result["observation"]),
                        {"sha256": result.get("observation_sha256")},
                    ),
                    (
                        "objects/" + str(result.get("object_sha256")) + ".json",
                        {"sha256": result.get("object_sha256")},
                    ),
                ]
            )
    else:
        raise ArchiveError("invalid_probe_results")
    # Data inventories are dicts (unique keys). The publisher already owns
    # their closure, so validate every entry without cloning the entire map.
    if not collect and not release.startswith("data-"):
        raise ArchiveError("legacy_inventory_requires_collection")
    output = {} if collect else None
    for name, metadata in entries:
        if not isinstance(name, str) or not FILE_PATTERN.fullmatch(name):
            raise ArchiveError("invalid_immutable_path")
        if not isinstance(metadata, dict):
            raise ArchiveError("invalid_file_metadata")
        sha, size = metadata.get("sha256"), metadata.get("bytes")
        if not release.startswith("data-") and (sha is None or size is None):
            target = _safe(root, name)
            if sha is None:
                sha, measured = _fingerprint(target, float("inf"))
                size = measured if size is None else size
            elif size is None:
                size = target.stat().st_size
        if (
            not isinstance(sha, str)
            or not re.fullmatch(r"[a-f0-9]{64}", sha)
            or type(size) is not int
            or size < 0
        ):
            raise ArchiveError("invalid_file_metadata")
        if not name.startswith("observations/") and Path(name).stem != sha:
            raise ArchiveError("referenced_file_mismatch")
        expected = {"sha256": sha, "bytes": size}
        if output is not None:
            if name in output and output[name] != expected:
                raise ArchiveError("conflicting_file_metadata")
            output[name] = expected
    return output


def retain_release(root, release_id, *, _verified_predecessor=None, timing=None):
    """Retain one predecessor; default callers receive its complete expectations.

    The private publisher fast path accepts ONLY its unchanged manifest_at result
    for this SHA-pinned data release. It already inherited that document's files,
    so returns archive additions only. Every inherited metadata entry is still
    validated; the safe alias rechecks source/archive SHA and stat under the lock.
    General and legacy-probe callers retain their original read/parse/return path.
    Referenced objects are expectations, never freshly verified by retention.
    """
    started = time.monotonic()
    timing = {} if timing is None else timing
    timing.update(stage_seconds={}, completed_stages=[], failed_stage=None)

    @contextmanager
    def measure(name):
        begin = time.monotonic()
        try:
            yield
        except BaseException:
            timing["failed_stage"] = name
            raise
        else:
            timing["completed_stages"].append(name)
        finally:
            now = time.monotonic()
            timing["stage_seconds"][name] = max(0.0, now - begin)
            timing["total_elapsed_seconds"] = max(0.0, now - started)

    root = Path(root).resolve()
    reuse = _verified_predecessor is not None and isinstance(release_id, str) and bool(
        re.fullmatch(r"data-[a-f0-9]{64}", release_id)
    )
    timing["reused_predecessor"] = reuse
    source_metadata = None
    with measure("reuse_stat" if reuse else "manifest_read_parse"):
        if reuse:
            document, raw = _verified_predecessor, None
            source = _safe(root, f"releases/{release_id}/manifest.json")
            source_metadata = {"sha256": release_id[5:], "bytes": source.stat().st_size}
            if not isinstance(document, dict):
                raise ArchiveError("invalid_manifest")
        else:
            raw, document = _manifest_document(root, release_id)
    with measure("expected_files"):
        inherited = document.get("files") if reuse else None
        files = _expected_files(root, release_id, document, collect=not reuse)
        if reuse:
            files = {}
    with (root / ".archive.lock").open("a") as lock:
        with measure("lock_wait"):
            fcntl.flock(lock, fcntl.LOCK_EX)
        with measure("archive_open"):
            db = _db(root)
        try:
            with measure("archive_record"):
                if reuse:
                    path, metadata = _record_release(
                        root, db, release_id, raw, source_metadata=source_metadata
                    )
                else:
                    path, metadata = _record_release(root, db, release_id, raw)
                files[path] = metadata
                db.commit()
            with measure("known_archives"):
                releases = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM archived_releases ORDER BY release_id"
                    )
                ]
                # The delta includes all known archive mappings, including older
                # legacy catch-up. The publisher still carries all original files.
                for saved in db.execute(
                    "SELECT f.path,f.sha256,f.bytes FROM files f JOIN archived_releases r ON r.path=f.path"
                ):
                    metadata = {"sha256": saved["sha256"], "bytes": saved["bytes"]}
                    for inventory in (files, inherited or {}):
                        if saved["path"] in inventory and inventory[saved["path"]] != metadata:
                            raise ArchiveError("conflicting_file_metadata")
                    files[saved["path"]] = metadata
                return {
                    "files": files,
                    "archived_releases": releases,
                    "verification": "manifest_verified_references_expected",
                }
        finally:
            db.close()


def _manifest(root, db, row, deadline):
    parts = Path(row["path"]).parts
    if (
        len(parts) != 3
        or parts[0] != "releases"
        or parts[2] != "manifest.json"
        or not RELEASE_PATTERN.fullmatch(parts[1])
    ):
        raise ArchiveError("invalid_release_path")
    raw = _safe(root, row["path"]).read_bytes()
    release = parts[1]
    sha = _hash(raw)
    if release.startswith("data-") and release[5:] != sha:
        raise ArchiveError("manifest_checksum_mismatch")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ArchiveError("invalid_manifest")
    _record_release(root, db, release, raw)
    references = []
    if release.startswith("data-"):
        files = document.get("files")
        datasets = document.get("datasets", [])
        if not isinstance(files, dict) or not isinstance(datasets, list):
            raise ArchiveError("invalid_file_inventory")
        by_path = {}
        for dataset in datasets:
            if not isinstance(dataset, dict) or not isinstance(
                dataset.get("path"), str
            ):
                _gap(db, row, "invalid_dataset")
                continue
            name = dataset["path"]
            if name not in files or not re.fullmatch(
                r"parquet/[a-f0-9]{64}\.parquet", name
            ):
                _gap(db, row, "dataset_not_in_inventory", {"dataset_path": name})
                continue
            if not re.fullmatch(r"[a-z][a-z0-9_]*", str(dataset.get("api_name", ""))):
                _gap(db, row, "unknown_dataset_identity", {"dataset_path": name})
                continue
            by_path[name] = dataset
        for name, metadata in files.items():
            references.append(
                (
                    name,
                    {
                        "metadata": metadata,
                        "dataset": by_path.get(name),
                        "release_id": release,
                    },
                )
            )
    elif isinstance(document.get("files"), list):
        if any(
            not isinstance(item, dict) or "sha256" not in item or "bytes" not in item
            for item in document["files"]
        ):
            _gap(db, row, "legacy_file_metadata_observed_without_manifest_anchor")
        for name, metadata in _expected_files(root, release, document).items():
            references.append((name, {"metadata": metadata, "release_id": release}))
    else:
        results = document.get("results")
        if not isinstance(results, list):
            raise ArchiveError("invalid_probe_results")
        for result in results:
            if not isinstance(result, dict):
                _gap(db, row, "invalid_probe_result")
                continue
            # Transport errors can legitimately have no persisted response.
            if "observation" not in result:
                continue
            references.extend(
                [
                    (
                        "observations/" + str(result["observation"]),
                        {
                            "metadata": {"sha256": result.get("observation_sha256")},
                            "release_id": release,
                        },
                    ),
                    (
                        "objects/" + str(result.get("object_sha256")) + ".json",
                        {
                            "metadata": {"sha256": result.get("object_sha256")},
                            "release_id": release,
                        },
                    ),
                ]
            )
    for position in range(row["cursor"], len(references)):
        if time.monotonic() >= deadline:
            db.execute("UPDATE tasks SET cursor=? WHERE id=?", (position, row["id"]))
            raise Deadline
        name, expected = references[position]
        _task(db, "file", str(name), expected)
    db.execute("UPDATE tasks SET cursor=? WHERE id=?", (len(references), row["id"]))


def _file(root, db, row, deadline):
    name = row["path"]
    if not FILE_PATTERN.fullmatch(name):
        raise ArchiveError("invalid_immutable_path")
    target = _safe(root, name)
    cached = db.execute(
        "SELECT sha256,bytes FROM files WHERE path=? AND valid=1", (name,)
    ).fetchone()
    already_verified = cached is not None and cached["bytes"] == target.stat().st_size
    # A frozen scan hashes each immutable path once, even when thousands of old
    # releases reference it. Explicit rescan invalidates this verification cache.
    sha, size = (
        (cached["sha256"], cached["bytes"])
        if already_verified
        else _fingerprint(target, deadline)
    )
    if not name.startswith("observations/") and target.stem != sha:
        raise ArchiveError("filename_checksum_mismatch")
    expected = json.loads(row["expected"])
    metadata = expected.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ArchiveError("invalid_file_metadata")
    if expected and (
        metadata.get("sha256") != sha
        or ("bytes" in metadata and metadata["bytes"] != size)
    ):
        raise ArchiveError("referenced_file_mismatch")
    dataset = expected.get("dataset")
    if dataset and (
        dataset.get("sha256", sha) != sha or dataset.get("bytes", size) != size
    ):
        raise ArchiveError("dataset_file_mismatch")
    _register(db, name, sha, size, dataset)
    if name.startswith("observations/") and not already_verified:
        observed = json.loads(target.read_bytes())
        if not isinstance(observed, dict) or not re.fullmatch(
            r"[a-f0-9]{64}", str(observed.get("object_sha256", ""))
        ):
            raise ArchiveError("invalid_observation_reference")
        _task(
            db,
            "file",
            "objects/" + observed["object_sha256"] + ".json",
            {"metadata": {"sha256": observed["object_sha256"]}, "observation": name},
        )


def _progress(db):
    pending = db.execute("SELECT COUNT(*) FROM tasks WHERE state='pending'").fetchone()[
        0
    ]
    gaps = db.execute("SELECT COUNT(*) FROM gaps WHERE resolved=0").fetchone()[0]
    snapshot = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
    return {
        "status": "not_started"
        if snapshot is None
        else "recovering"
        if pending
        else "complete_with_gaps"
        if gaps
        else "complete",
        "remaining": pending,
        "tasks": db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        "files": db.execute("SELECT COUNT(*) FROM files WHERE valid=1").fetchone()[0],
        "open_gaps": gaps,
        "scan_count": int(snapshot[0]) if snapshot else 0,
        "historical_complete": False,
        "archived_releases": [
            dict(row)
            for row in db.execute("SELECT * FROM archived_releases ORDER BY release_id")
        ],
    }


def recover_archive(
    root, max_items=200, max_seconds=5, *, rescan=False, rescan_releases=False
):
    """Freeze initial inputs, verify a bounded batch; explicit rescan rechecks all.

    max_seconds is checked between artifacts and manifest-reference chunks. One
    artifact hash, JSON parse or initial directory snapshot may exceed the soft
    limit; a large file must not be restarted forever. No old data is replaced.
    A legacy frozen scan gets one release-directory-only catch-up; explicit
    rescan_releases repeats only that discovery, without resetting object tasks.
    Finished calls read SQLite only. Failure gaps persist, including resolved gaps
    in the DB after a later successful explicit rescan.
    """
    if (
        not isinstance(max_items, int)
        or not 1 <= max_items <= 10000
        or not 0 < max_seconds <= 300
    ):
        raise ValueError("Invalid archive recovery budget")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".archive.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running", "historical_complete": False}
        db = _db(root)
        processed = 0
        try:
            _snapshot(root, db, rescan)
            if (
                rescan_releases
                or not db.execute(
                    "SELECT 1 FROM meta WHERE key='release_catchup'"
                ).fetchone()
            ):
                if rescan_releases:
                    db.execute(
                        "UPDATE tasks SET state='pending',cursor=0 WHERE kind='manifest'"
                    )
                _queue_releases(root, db)
                db.commit()
            deadline = time.monotonic() + max_seconds
            while processed < max_items and time.monotonic() < deadline:
                row = db.execute(
                    "SELECT * FROM tasks WHERE state='pending' ORDER BY rowid LIMIT 1"
                ).fetchone()
                if row is None:
                    break
                db.execute("UPDATE gaps SET resolved=1 WHERE task_id=?", (row["id"],))
                try:
                    if row["kind"] == "manifest":
                        _manifest(root, db, row, deadline)
                    elif row["kind"] == "file":
                        _file(root, db, row, deadline)
                    else:
                        raise ArchiveError("unsafe_directory_layout")
                except Deadline:
                    db.commit()  # Keep reference-enqueue cursor; verify file again later.
                    break
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    code = (
                        str(exc)
                        if isinstance(exc, ArchiveError)
                        else type(exc).__name__
                    )
                    _gap(db, row, code)
                    db.execute("UPDATE tasks SET state='gap' WHERE id=?", (row["id"],))
                    if code in (
                        "filename_checksum_mismatch",
                        "symlink",
                        "FileNotFoundError",
                        "immutable_file_conflict",
                    ):
                        db.execute(
                            "UPDATE files SET valid=0 WHERE path=?", (row["path"],)
                        )
                else:
                    db.execute("UPDATE tasks SET state='done' WHERE id=?", (row["id"],))
                db.commit()
                processed += 1
            return {**_progress(db), "processed": processed}
        finally:
            db.close()


def archive_inventory(root):
    """Return only verified files/known datasets plus persistent recovery gaps."""
    path = Path(root).resolve() / "archive.sqlite"
    if path.is_symlink():
        raise ArchiveError("unsafe_archive_database")
    if not path.exists():
        return {
            "files": {},
            "datasets": [],
            "gaps": [],
            "recovery": {"status": "not_started", "historical_complete": False},
        }
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ArchiveError("unsupported_archive_schema")
        files, datasets = {}, []
        for row in db.execute("SELECT * FROM files WHERE valid=1 ORDER BY path"):
            files[row["path"]] = {"sha256": row["sha256"], "bytes": row["bytes"]}
            if row["dataset"]:
                datasets.append(json.loads(row["dataset"]))
        return {
            "files": files,
            "datasets": datasets,
            "gaps": [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM gaps WHERE resolved=0 ORDER BY id"
                )
            ],
            "recovery": _progress(db),
        }
    finally:
        db.close()
