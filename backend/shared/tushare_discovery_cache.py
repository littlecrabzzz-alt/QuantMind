"""Discardable, bounded projected-row cache; never a source of membership.

Callers rescan all authoritative result metadata and stat every eligible object.
Only the existing identifier projection is cached, never full dataset reads.
"""
import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path

VERSION = "discovery-projection-v2"
MAX_BYTES = 128 * 1024**2
MAX_PAYLOAD = 2 * 1024**2
MAX_ROWS = 8192
MAX_COMPRESSED = MAX_PAYLOAD + 65536


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class DiscoveryCache:
    def __init__(self, root, *, enabled=False, max_bytes=MAX_BYTES, admission_seconds=0.5):
        self.path = Path(root) / "discovery-cache.sqlite"
        self.db = None
        self.admission_seconds = admission_seconds
        self.stats = {"hits": 0, "misses": 0, "admitted": 0, "rejected": 0,
                      "errors": 0, "admission_seconds": 0.0, "bytes": 0}
        if not enabled:
            return
        try:
            if self.path.is_symlink():
                raise ValueError("symlink cache")
            self.db = sqlite3.connect(self.path, timeout=0)
            self.db.execute("PRAGMA cache_size=-256")
            self.db.execute("PRAGMA mmap_size=0")
            self.db.execute("PRAGMA synchronous=OFF")
            self.db.execute("PRAGMA journal_mode=MEMORY")
            # MEMORY rollback is bounded by small per-entry transactions; the
            # cache is disposable after a crash, not an authoritative database.
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            pages = self.db.execute("PRAGMA page_count").fetchone()[0]
            if pages * page_size > max_bytes:
                raise ValueError("oversized cache")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0, 1) or (version == 0 and tables):
                raise ValueError("foreign cache schema")
            self.db.execute(f"PRAGMA max_page_count={max(2, max_bytes // page_size)}")
            self.db.execute("CREATE TABLE IF NOT EXISTS projections (key TEXT PRIMARY KEY, payload BLOB NOT NULL, sha TEXT NOT NULL)")
            self.db.execute("PRAGMA user_version=1")
            self.db.commit()
        except (OSError, ValueError, sqlite3.Error):
            self.stats["errors"] += 1
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                self.stats["errors"] += 1
            self.db = None
        try:
            self.stats["bytes"] = self.path.stat().st_size
        except OSError:
            pass

    def read(self, source, source_key, fields, loader):
        # source_key=None means request-sensitive/ineligible: always original.
        if self.db is None or source_key is None:
            return loader()
        key = hashlib.sha256(encoded((VERSION, str(source.absolute()), source_key, sorted(fields)))).hexdigest()
        try:
            saved = self.db.execute(
                "SELECT CASE WHEN length(payload)<=? THEN payload END, "
                "CASE WHEN length(sha)=64 THEN sha END FROM projections WHERE key=?",
                (MAX_COMPRESSED, key),
            ).fetchone()
            if saved:
                if not isinstance(saved[0], bytes) or not isinstance(saved[1], str):
                    raise ValueError("oversized or invalid stored projection")
                obj = zlib.decompressobj()
                raw = obj.decompress(saved[0], MAX_PAYLOAD + 1)
                if len(raw) > MAX_PAYLOAD or not obj.eof or obj.unused_data or hashlib.sha256(raw).hexdigest() != saved[1]:
                    raise ValueError("invalid cache payload")
                # Conservative lexical bound before allocating decoded row objects.
                # Braces inside strings may reject caching; raw semantics are unchanged.
                if raw.count(b"{") > MAX_ROWS:
                    raise ValueError("too many cached row objects")
                rows = json.loads(raw)
                if not isinstance(rows, list) or any(not isinstance(row, dict) or not set(row).issubset(fields) for row in rows):
                    raise ValueError("invalid cache projection")
                stat = source.stat()
                if tuple(source_key[-5:]) != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                    raise ValueError("source changed during lookup")
                self.stats["hits"] += 1
                return rows
        except (OSError, sqlite3.Error, ValueError, zlib.error, UnicodeError, TypeError, RecursionError):
            self.stats["errors"] += 1
            # Never trust a damaged cache again during this invocation.
            self.close()
        self.stats["misses"] += 1
        rows = loader()  # Source failures deliberately retain their old behavior.
        if self.db is None or self.stats["admission_seconds"] >= self.admission_seconds:
            self.stats["rejected"] += 1
            return rows
        started = time.monotonic()
        try:
            seen, unique, length = set(), [], 2
            for row in rows:
                # Reject costly cache admission before encoding. Never truncate or
                # reject the authoritative rows returned to discovery. Six bytes per
                # Unicode character bounds JSON escapes and UTF-8; large integers and
                # nested values retain the original raw path instead of extra copies.
                bound = 2
                for name, value in row.items():
                    bound += 6 * len(name) + 6
                    if isinstance(value, str):
                        bound += 6 * len(value) + 2
                    elif value is None or type(value) in (bool, float):
                        bound += 32
                    elif type(value) is int and value.bit_length() <= 64:
                        bound += 32
                    else:
                        bound = MAX_PAYLOAD + 1
                    if bound > MAX_PAYLOAD:
                        self.stats["rejected"] += 1
                        return rows
                identity = tuple((name, type(value), value) for name, value in row.items())
                if identity not in seen:
                    if len(unique) >= MAX_ROWS:
                        self.stats["rejected"] += 1
                        return rows
                    length += len(encoded(row)) + 1
                    if length > MAX_PAYLOAD:
                        self.stats["rejected"] += 1
                        return rows
                    seen.add(identity)
                    unique.append(row)
            stat = source.stat()
            if tuple(source_key[-5:]) != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                return rows  # Changed while read: do not persist this projection.
            raw = encoded(unique)
            self.db.execute("INSERT OR REPLACE INTO projections VALUES(?,?,?)", (key, zlib.compress(raw, 1), hashlib.sha256(raw).hexdigest()))
            self.db.commit()
            self.stats["admitted"] += 1
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self.stats["errors"] += 1
            self.close()  # Full/locked/broken: raw fallback, no repeated admission.
        finally:
            self.stats["admission_seconds"] += time.monotonic() - started
        return rows
