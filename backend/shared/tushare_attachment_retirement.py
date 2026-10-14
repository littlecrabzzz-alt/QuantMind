"""Explicit, receipt-backed retirement of successfully extracted PDF originals.

All roots are supplied by the caller. This module never downloads or restores an
original. A prepared intent is durable before unlink and must be resumed before
publishing or scanning the archive.
"""

from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

PDF = re.compile(r"attachments/([a-f0-9]{64})\.pdf")
TEXT = re.compile(r"extracted/([a-f0-9]{64})\.json")
RECEIPT = re.compile(r"documents/([a-f0-9]{64})\.json")
_RECEIPTS = ContextVar("attachment_retirement_receipts", default=None)
_RECEIPT_FIELDS = ("path", "sha256", "bytes", "status", "document_ids", "extracted")


@contextmanager
def receipt_cache():
    """Share verified receipts within one operation, never across later reads.

    Nested publication/index/retention calls reuse the same verification. Only
    membership fingerprints are retained, not entire batch JSON bodies or text.
    The next operation re-reads receipts so corruption cannot hide in a warm cache.
    """
    if _RECEIPTS.get() is not None:
        yield
        return
    token = _RECEIPTS.set({})
    try:
        yield
    finally:
        _RECEIPTS.reset(token)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def setup(db):
    """Additive, independently versioned migration of the existing document DB."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='attachment_retirement_meta'").fetchone():
        if db.execute("SELECT version FROM attachment_retirement_meta").fetchone()[0] != 1:
            raise ValueError("unsupported_retirement_schema")
        db.execute("""CREATE TABLE IF NOT EXISTS attachment_retirement_holds(
            sha256 TEXT PRIMARY KEY, reason TEXT NOT NULL, held_at REAL NOT NULL)""")
        return
    db.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE attachment_retirement_meta(version INTEGER NOT NULL);
        INSERT INTO attachment_retirement_meta VALUES(1);
        CREATE TABLE IF NOT EXISTS attachment_retirement_holds(
            sha256 TEXT PRIMARY KEY, reason TEXT NOT NULL, held_at REAL NOT NULL);
        CREATE TABLE attachment_retirement_plans(
            plan_sha256 TEXT PRIMARY KEY, root_identity TEXT NOT NULL,
            plan_path TEXT NOT NULL, schema_version INTEGER NOT NULL,
            created_at REAL NOT NULL);
        CREATE TABLE attachment_retirements(
            path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
            plan_sha256 TEXT NOT NULL, state TEXT NOT NULL
                CHECK(state IN ('prepared','retired')),
            evidence_json TEXT NOT NULL, prepared_at REAL NOT NULL,
            retired_at REAL, receipt_path TEXT, receipt_sha256 TEXT);
        CREATE INDEX attachment_retirement_sha ON attachment_retirements(sha256);
        CREATE INDEX attachment_retirement_plan ON attachment_retirements(plan_sha256);
        CREATE TABLE document_attachment_links(
            document_id TEXT NOT NULL, sha256 TEXT NOT NULL,
            PRIMARY KEY(document_id,sha256));
        CREATE INDEX document_attachment_sha ON document_attachment_links(sha256);
        INSERT OR IGNORE INTO document_attachment_links
            SELECT id,json_extract(result,'$.document_sha256') FROM documents
            WHERE json_extract(result,'$.document_sha256') IS NOT NULL;
        INSERT OR IGNORE INTO document_attachment_links
            SELECT d.id,substr(json_extract(f.value,'$.path'),13,64)
            FROM documents d,json_each(d.result,'$.files') f
            WHERE json_extract(f.value,'$.path') GLOB 'attachments/*.pdf';
        CREATE TRIGGER document_attachment_insert AFTER INSERT ON documents BEGIN
            INSERT OR IGNORE INTO document_attachment_links
                SELECT NEW.id,json_extract(NEW.result,'$.document_sha256')
                WHERE json_extract(NEW.result,'$.document_sha256') IS NOT NULL;
            INSERT OR IGNORE INTO document_attachment_links
                SELECT NEW.id,substr(json_extract(value,'$.path'),13,64)
                FROM json_each(NEW.result,'$.files')
                WHERE json_extract(value,'$.path') GLOB 'attachments/*.pdf';
        END;
        CREATE TRIGGER document_attachment_update AFTER UPDATE OF result ON documents BEGIN
            DELETE FROM document_attachment_links WHERE document_id=NEW.id;
            INSERT OR IGNORE INTO document_attachment_links
                SELECT NEW.id,json_extract(NEW.result,'$.document_sha256')
                WHERE json_extract(NEW.result,'$.document_sha256') IS NOT NULL;
            INSERT OR IGNORE INTO document_attachment_links
                SELECT NEW.id,substr(json_extract(value,'$.path'),13,64)
                FROM json_each(NEW.result,'$.files')
                WHERE json_extract(value,'$.path') GLOB 'attachments/*.pdf';
        END;
        CREATE TRIGGER document_attachment_delete AFTER DELETE ON documents BEGIN
            DELETE FROM document_attachment_links WHERE document_id=OLD.id;
        END;
        COMMIT;
    """)


def _root(root):
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError("unsafe_path")
    # Match the existing archive/document APIs: canonicalize the supplied root
    # (macOS /var is a system alias), then forbid links inside that pinned root.
    return root.resolve()


@contextmanager
def _db(root):
    path = root / "documents.sqlite"
    if path.is_symlink():
        raise ValueError("unsafe_path")
    if not path.exists():
        yield None
        return
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def _has_ledger(db):
    return db is not None and db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='attachment_retirements'"
    ).fetchone() is not None


def _is_held(db, sha):
    return db is not None and db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='attachment_retirement_holds'"
    ).fetchone() is not None and db.execute(
        "SELECT 1 FROM attachment_retirement_holds WHERE sha256=?", (sha,)
    ).fetchone() is not None


def _hold_shas(sha256_list):
    shas = list(sha256_list)
    if any(not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
           for sha in shas):
        raise ValueError("invalid_sha")
    return shas


@contextmanager
def _hold_db(root):
    from backend.shared.tushare_documents import _document_db

    root = _root(root)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / "documents.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("retirement_busy") from exc
        db = _document_db(root)
        try:
            with db:
                yield db
        finally:
            db.close()


def hold_attachments(root, sha256_list, *, reason):
    shas = _hold_shas(sha256_list)
    with _hold_db(root) as db:
        before = db.total_changes
        db.executemany(
            "INSERT OR IGNORE INTO attachment_retirement_holds VALUES(?,?,?)",
            [(sha, reason, time.time()) for sha in shas],
        )
        return {"held": db.total_changes - before}


def held_attachments(root):
    with _db(_root(root)) as db:
        if db is None or not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='attachment_retirement_holds'"
        ).fetchone():
            return {}
        return dict(db.execute("SELECT sha256,reason FROM attachment_retirement_holds"))


def release_holds(root, sha256_list):
    shas = _hold_shas(sha256_list)
    with _hold_db(root) as db:
        before = db.total_changes
        db.executemany("DELETE FROM attachment_retirement_holds WHERE sha256=?",
                       [(sha,) for sha in shas])
        return {"released": db.total_changes - before}


@contextmanager
def _parent(root, name):
    if not isinstance(name, str) or not re.fullmatch(
        r"(?:attachments|extracted|documents)/[a-f0-9]{64}\.(?:pdf|json)", name
    ):
        raise ValueError("unsafe_path")
    directory, leaf = name.split("/")
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            child = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("unsafe_path") from exc
    try:
        yield child, leaf
    finally:
        os.close(child)


def _identity(info):
    return tuple(getattr(info, key) for key in
                 ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _read(root, item, pattern, reason):
    name = item.get("path")
    match = pattern.fullmatch(name) if isinstance(name, str) else None
    if not match or match[1] != item.get("sha256") or type(item.get("bytes")) is not int:
        raise ValueError("unsafe_path")
    try:
        with _parent(root, name) as (parent, leaf):
            info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("unsafe_path")
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                raw = stream.read()
                after = os.fstat(stream.fileno())
            current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if any(_identity(other) != _identity(info) for other in (before, after, current)):
                raise ValueError(reason)
    except FileNotFoundError as exc:
        raise ValueError(reason) from exc
    if len(raw) != item["bytes"] or _sha(raw) != item["sha256"]:
        raise ValueError(reason)
    return raw


def _text(root, item):
    extracted = item.get("extracted")
    if not isinstance(extracted, list) or not extracted:
        raise ValueError("extracted_checksum_mismatch")
    for descriptor in extracted:
        raw = _read(root, descriptor, TEXT, "extracted_checksum_mismatch")
        try:
            body = json.loads(raw)
            pages = body["pages"]
            if (body.get("parse_status") != "parsed"
                    or body.get("document_sha256") != item["sha256"]
                    or not isinstance(pages, list) or not pages
                    or type(body.get("page_count")) is not int
                    or body["page_count"] != len(pages)
                    or any(not isinstance(page, dict)
                           or type(page.get("page_number")) is not int
                           or page["page_number"] != number
                           or not isinstance(page.get("text"), str)
                           for number, page in enumerate(pages, 1))
                    or not any(page["text"].strip() for page in pages)):
                raise ValueError("extracted_checksum_mismatch")
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("extracted_checksum_mismatch") from exc


def _candidate(root, db, sha, *, missing_ok=False):
    rows = db.execute(
        "SELECT d.* FROM documents d JOIN document_attachment_links l "
        "ON l.document_id=d.id WHERE l.sha256=? ORDER BY d.id",
        (sha,),
    ).fetchall()
    if not rows:
        raise ValueError("unregistered_pdf")
    item = {"path": f"attachments/{sha}.pdf", "sha256": sha,
            "document_ids": [], "extracted": [], "results": {}}
    texts = {}
    for row in rows:
        result = json.loads(row["result"])
        if (row["download_status"] != "downloaded" or row["parse_status"] != "parsed"
                or result.get("status") != "downloaded"
                or result.get("parse_status") != "parsed"
                or result.get("validation_status") != "pdf_structure_valid"
                or result.get("document_sha256") != sha):
            raise ValueError("document_state_changed")
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='document_claims'").fetchone():
            if db.execute("SELECT 1 FROM document_claims WHERE document_id=?", (row["id"],)).fetchone():
                raise ValueError("retirement_busy")
        files = result.get("files", [])
        pdfs = [f for f in files if f.get("path") == item["path"]]
        if len(pdfs) != 1 or pdfs[0].get("sha256") != sha or pdfs[0].get("mime") != "application/pdf":
            raise ValueError("pdf_checksum_mismatch")
        size = pdfs[0].get("bytes")
        if type(size) is not int or size < 0 or item.get("bytes", size) != size:
            raise ValueError("pdf_checksum_mismatch")
        item["bytes"] = size
        extracted = [f for f in files if str(f.get("path", "")).startswith("extracted/")]
        _text(root, {**item, "extracted": extracted})
        for f in extracted:
            if f["path"] in texts and texts[f["path"]] != f:
                raise ValueError("extracted_checksum_mismatch")
            texts[f["path"]] = f
        item["document_ids"].append(row["id"])
        item["results"][row["id"]] = _sha(_json(result))
    item["extracted"] = [texts[name] for name in sorted(texts)]
    path = root / item["path"]
    if not path.exists() and not path.is_symlink():
        if not missing_ok:
            raise ValueError("pdf_missing_without_intent")
    else:
        _read(root, item, PDF, "pdf_checksum_mismatch")
    return item


def _root_identity(root):
    identity = {"path": str(root)}
    authority = root / "ARCHIVE_AUTHORITY.json"
    if authority.is_symlink():
        raise ValueError("unsafe_path")
    if authority.exists():
        identity["authority_sha256"] = _sha(authority.read_bytes())
    return identity


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def build_plan(root, plan_path, *, max_items=10_000, after=None):
    root = _root(root)
    if type(max_items) is not int or not 1 <= max_items <= 10_000:
        raise ValueError("invalid_plan_budget")
    if after is not None and not PDF.fullmatch(after):
        raise ValueError("unsafe_path")
    items, excluded, cursor = [], {}, None
    with _db(root) as db:
        if db is not None:
            # Bound work as well as output; advance even over excluded candidates.
            rows = db.execute(
                "SELECT DISTINCT sha256 FROM document_attachment_links "
                "WHERE sha256>? ORDER BY sha256 LIMIT ?", (Path(after).stem if after else "", max_items + 1)
            ).fetchall()
            for row in rows[:max_items]:
                sha = row[0]
                if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
                    excluded["invalid_sha"] = excluded.get("invalid_sha", 0) + 1
                    continue
                cursor = f"attachments/{sha}.pdf"
                try:
                    if _is_held(db, sha):
                        raise ValueError("held")
                    if _has_ledger(db) and db.execute(
                        "SELECT 1 FROM attachment_retirements WHERE path=?", (cursor,)
                    ).fetchone():
                        raise ValueError("already_retiring")
                    items.append(_candidate(root, db, sha))
                except (ValueError, OSError) as exc:
                    reason = str(exc)
                    excluded[reason] = excluded.get(reason, 0) + 1
            if len(rows) <= max_items:
                cursor = None
    plan = {"schema_version": 1, "root_identity": _root_identity(root),
            "items": items, "excluded": excluded, "next_after": cursor}
    raw = _json(plan)
    path = Path(plan_path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("unsafe_path")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    return {"plan_sha256": _sha(raw), "candidate_count": len(items),
            "candidate_bytes": sum(item["bytes"] for item in items), "next_after": cursor}


def _unlink_verified_pdf(root, item):
    _text(root, item)
    _read(root, item, PDF, "pdf_checksum_mismatch")
    with _parent(root, item["path"]) as (parent, leaf):
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("unsafe_path")
            sha = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(block)
            if info.st_size != item["bytes"] or sha.hexdigest() != item["sha256"]:
                raise ValueError("pdf_checksum_mismatch")
            _text(root, item)
            current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if _identity(info) != _identity(current) or _identity(info) != _identity(os.fstat(stream.fileno())):
                raise ValueError("pdf_checksum_mismatch")
            os.unlink(leaf, dir_fd=parent)
            os.fsync(parent)


def _receipt_fingerprint(item, *, portable=False):
    if portable:
        item = {key: item[key] for key in _RECEIPT_FIELDS}
    return hashlib.sha256(_json(item)).digest()


@receipt_cache()
def _verified_receipt(root, descriptor):
    cache = _RECEIPTS.get()
    key = (str(root), descriptor["path"], descriptor["sha256"])
    cached = cache.get(key)
    if cached is None:
        receipt = {**descriptor, "mime": "application/json"}
        if "bytes" not in receipt:
            receipt["bytes"] = (root / receipt["path"]).stat().st_size
        body = json.loads(_read(
            root, receipt, RECEIPT, "retirement_receipt_checksum_mismatch"
        ))
        if (not isinstance(body, dict) or body.get("schema_version") != 1
                or body.get("kind") != "attachment_retirement_receipt"
                or not isinstance(body.get("items"), list)):
            raise ValueError("retirement_receipt_mismatch")
        members = {}
        for item in body["items"]:
            if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                    or item["path"] in members):
                raise ValueError("retirement_receipt_mismatch")
            members[item["path"]] = (
                _receipt_fingerprint(item),
                _receipt_fingerprint(item, portable=True),
            )
        cached = (receipt, body.get("plan_sha256"), body.get("retired_at"), members)
        cache[key] = cached
    if "bytes" in descriptor and descriptor["bytes"] != cached[0]["bytes"]:
        raise ValueError("retirement_receipt_checksum_mismatch")
    return cached


def _verified_row(root, row, *, check_text=False):
    if row["state"] != "retired":
        raise ValueError("retirement_in_progress")
    receipt, plan_sha, retired_at, members = _verified_receipt(root, {
        "path": row["receipt_path"], "sha256": row["receipt_sha256"],
    })
    evidence = json.loads(row["evidence_json"])
    member = members.get(row["path"])
    if (plan_sha != row["plan_sha256"] or retired_at != row["retired_at"]
            or any(evidence.get(key) != row[key] for key in ("path", "sha256", "bytes"))
            or member is None
            or _receipt_fingerprint({**evidence, "status": "retired"}) != member[0]):
        raise ValueError("retirement_receipt_mismatch")
    if check_text:
        _text(root, evidence)
    return {"sha256": row["sha256"], "bytes": row["bytes"], "status": "retired",
            "document_ids": evidence["document_ids"], "extracted": evidence["extracted"],
            "receipt": receipt}


@receipt_cache()
def retired_files(root, *, path=None, check_text=False):
    root = _root(root)
    with _db(root) as db:
        if not _has_ledger(db):
            return {}
        rows = db.execute(
            "SELECT * FROM attachment_retirements "
            + ("WHERE path=? " if path else "") + "ORDER BY path",
            (path,) if path else (),
        )
        return {row["path"]: _verified_row(root, row, check_text=check_text) for row in rows}


def ensure_ready(root):
    with _db(_root(root)) as db:
        if _has_ledger(db) and db.execute(
            "SELECT 1 FROM attachment_retirements WHERE state='prepared' LIMIT 1"
        ).fetchone():
            raise ValueError("retirement_in_progress")


def match_retired(root, path, expected=None, *, check_text=False):
    item = retired_files(root, path=path, check_text=check_text).get(path)
    if item and expected is not None and (
        item["sha256"] != expected.get("sha256") or item["bytes"] != expected.get("bytes")
    ):
        raise ValueError("retirement_metadata_mismatch")
    return item


def project_files(files, retired):
    """Mutate a publication closure only after strict original-metadata comparison."""
    for path, item in retired.items():
        expected = files.get(path)
        if expected is not None:
            if expected != {k: item[k] for k in ("sha256", "bytes")}:
                raise ValueError("Conflicting inherited file metadata")
            del files[path]
        for descriptor in [*item["extracted"], item["receipt"]]:
            metadata = {k: descriptor[k] for k in ("sha256", "bytes")}
            name = descriptor["path"]
            if name in files and files[name] != metadata:
                raise ValueError("Conflicting inherited file metadata")
            files[name] = metadata


@receipt_cache()
def apply_plan(root, plan_path, *, confirm_sha, max_items=1_000):
    root = _root(root)
    raw = Path(plan_path).read_bytes()
    if _sha(raw) != confirm_sha:
        raise ValueError("confirmation_sha_mismatch")
    if type(max_items) is not int or not 1 <= max_items <= 10_000:
        raise ValueError("invalid_apply_budget")
    plan = json.loads(raw)
    if plan.get("schema_version") != 1 or plan.get("root_identity") != _root_identity(root):
        raise ValueError("root_identity_mismatch")
    items = plan["items"]
    paths = [item["path"] for item in items]
    if paths != sorted(set(paths)) or any(not PDF.fullmatch(path) for path in paths):
        raise ValueError("unsafe_path")
    from backend.shared.tushare_documents import _document_db, _save

    with ExitStack() as stack:
        for name in ("pipeline.lock", "documents.lock", ".archive-worker.lock", ".archive.lock"):
            fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stream = stack.enter_context(os.fdopen(fd, "a+"))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("retirement_busy") from exc
        db = _document_db(root)
        stack.callback(db.close)
        pending = []
        for item in items:
            if _is_held(db, item["sha256"]):
                raise ValueError("attachment_held")
            row = db.execute("SELECT * FROM attachment_retirements WHERE path=?", (item["path"],)).fetchone()
            if row is not None:
                if row["plan_sha256"] != confirm_sha or json.loads(row["evidence_json"]) != item:
                    raise ValueError("document_state_changed")
                if row["state"] == "retired":
                    _verified_row(root, row, check_text=True)
                    continue
            pending.append((item, row))
        batch = pending[:max_items]
        # Revalidate the entire bounded batch before creating any deletion intent.
        for item, row in batch:
            if _candidate(root, db, item["sha256"], missing_ok=row is not None) != item:
                raise ValueError("document_state_changed")
        deleted = 0
        if batch:
            # A resumed prepared batch keeps its original timestamp and membership,
            # making receipt bytes deterministic even after receipt-before-commit death.
            prepared = [row for _, row in batch if row is not None]
            if prepared:
                stamp = prepared[0]["prepared_at"]
                batch = [(item, row) for item, row in pending if row is not None
                         and row["prepared_at"] == stamp]
            else:
                stamp = time.time()
            with db:
                db.execute("INSERT OR IGNORE INTO attachment_retirement_plans VALUES(?,?,?,?,?)",
                           (confirm_sha, _json(plan["root_identity"]).decode(), str(Path(plan_path).absolute()), 1, stamp))
                for item, row in batch:
                    db.execute("INSERT OR IGNORE INTO attachment_retirements "
                               "(path,sha256,bytes,plan_sha256,state,evidence_json,prepared_at) "
                               "VALUES(?,?,?,?,'prepared',?,?)",
                               (item["path"], item["sha256"], item["bytes"], confirm_sha, _json(item).decode(), stamp))
            for item, row in batch:
                target = root / item["path"]
                if target.exists() or target.is_symlink():
                    _unlink_verified_pdf(root, item)
                    deleted += 1
                elif row is None:
                    raise ValueError("pdf_missing_without_intent")
                else:
                    _text(root, item)
            body = {"schema_version": 1, "kind": "attachment_retirement_receipt",
                    "plan_sha256": confirm_sha, "retired_at": stamp,
                    "items": [{**item, "status": "retired"} for item, _ in batch]}
            receipt = _save(root, "documents", ".json", _json(body), "application/json")
            _fsync_directory(root / "documents")
            with db:
                for item, _ in batch:
                    db.execute("UPDATE attachment_retirements SET state='retired',retired_at=?,receipt_path=?,receipt_sha256=? WHERE path=?",
                               (stamp, receipt["path"], receipt["sha256"], item["path"]))
                    for document_id in item["document_ids"]:
                        db.execute("UPDATE documents SET result=json_set(result,'$.attachment_status','retired') WHERE id=?", (document_id,))
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='document_index_files'").fetchone():
                        db.execute("DELETE FROM document_index_files WHERE path=?", (item["path"],))
        receipts = {}
        for row in db.execute("SELECT * FROM attachment_retirements WHERE plan_sha256=? AND state='retired' ORDER BY prepared_at,path", (confirm_sha,)):
            descriptor = _verified_row(root, row, check_text=True)["receipt"]
            receipts[descriptor["path"]] = descriptor
        remaining = len(pending) - len(batch)
        return {"status": "in_progress" if remaining else "complete", "remaining": remaining,
                "deleted_now": deleted, "receipts": list(receipts.values())}


def scan_expectations(root):
    """Queue all evidence, including absent text; verification belongs to scanner."""
    with _db(_root(root)) as db:
        if not _has_ledger(db):
            return []
        entries = []
        for row in db.execute("SELECT * FROM attachment_retirements ORDER BY path"):
            if row["state"] != "retired":
                raise ValueError("retirement_in_progress")
            evidence = json.loads(row["evidence_json"])
            entries.append({"path": row["path"], "sha256": row["sha256"], "bytes": row["bytes"]})
            entries.extend(evidence["extracted"])
            entries.append({"path": row["receipt_path"], "sha256": row["receipt_sha256"]})
        return entries


@receipt_cache()
def validate_manifest(root, manifest, *, check_text=False):
    """Verify portable receipts explicitly bound by this immutable publication."""
    root = _root(root)
    retired = manifest.get("retired_files", {})
    if not isinstance(retired, dict):
        raise ValueError("invalid_retired_inventory")
    for path, item in retired.items():
        if (not PDF.fullmatch(path) or not isinstance(item, dict)
                or item.get("status") != "retired" or path in manifest["files"]
                or Path(path).stem != item.get("sha256")):
            raise ValueError("invalid_retired_inventory")
        receipt = item["receipt"]
        for descriptor in [receipt, *item["extracted"]]:
            if manifest["files"].get(descriptor["path"]) != {
                key: descriptor[key] for key in ("sha256", "bytes")
            }:
                raise ValueError("retirement_evidence_not_in_release")
        _, _, _, members = _verified_receipt(root, receipt)
        member = members.get(path)
        if (member is None or _receipt_fingerprint(
                {"path": path, **{key: item[key] for key in _RECEIPT_FIELDS[1:]}},
                portable=True,
        ) != member[1]):
            raise ValueError("retirement_receipt_mismatch")
        if check_text:
            _text(root, item)
    return retired
