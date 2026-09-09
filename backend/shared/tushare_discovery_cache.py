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

VERSION = "discovery-projection-v1"
MAX_BYTES = 128 * 1024**2
MAX_PAYLOAD = 2 * 1024**2


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class DiscoveryCache:
    def __init__(self, root, *, enabled=False, max_bytes=MAX_BYTES, admission_seconds=0.5):
        self.path = Path(root) / "discovery-cache.sqlite"
        self.db = None
        self.admission_seconds = admission_seconds
        self.stats = dict(hits=0, misses=0, admitted=0, rejected=0, errors=0,
                          admission_seconds=0.0, bytes=0)
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
            saved = self.db.execute("SELECT payload,sha FROM projections WHERE key=?", (key,)).fetchone()
            if saved:
                obj = zlib.decompressobj()
                raw = obj.decompress(saved[0], MAX_PAYLOAD + 1)
                if len(raw) > MAX_PAYLOAD or not obj.eof or obj.unused_data or hashlib.sha256(raw).hexdigest() != saved[1]:
                    raise ValueError("invalid cache payload")
                rows = json.loads(raw)
                if not isinstance(rows, list) or any(not isinstance(row, dict) or not set(row).issubset(fields) for row in rows):
                    raise ValueError("invalid cache projection")
                stat = source.stat()
                if tuple(source_key[-5:]) != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                    raise ValueError("source changed during lookup")
                self.stats["hits"] += 1
                return rows
        except (OSError, sqlite3.Error, ValueError, zlib.error, UnicodeError, TypeError):
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
                # Scalar source columns dominate discovery. Avoid JSON encoding
                # every duplicate row, while keeping bool/int/float distinct.
                identity = tuple((name, type(value), value) for name, value in row.items())
                try:
                    hash(identity)
                except TypeError:
                    identity = encoded(row)
                if identity not in seen:
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
