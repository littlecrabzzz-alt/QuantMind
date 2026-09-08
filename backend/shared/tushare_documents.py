"""Public document acquisition with pinned DNS, immutable files, bounded PDF parsing.

No credentials, browser, cookies or proxy configuration is read.
A separate SQLite queue owns document retries; callers enforce authority and publication.
"""

from __future__ import annotations

import hashlib
import fcntl
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import signal
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

MAX_REDIRECTS = 3
MAX_PARSE_PAGES = 5000
MAX_PARSE_TEXT_BYTES = 8 * 1024 * 1024


class DocumentError(ValueError):
    """Stable, non-sensitive failure category for the parent queue."""


def _public(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise DocumentError("invalid_address") from exc
    if (
        "%" in address
        or not ip.is_global
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_loopback
        or ip.is_link_local
        or (
            isinstance(ip, ipaddress.IPv6Address)
            and (
                ip.ipv4_mapped is not None
                or ip.sixtofour is not None
                or ip.teredo is not None
            )
        )
    ):
        raise DocumentError("non_public_address")
    return ip


def _target(url):
    if not isinstance(url, str) or not url or len(url) > 16384:
        raise DocumentError("invalid_url")
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise DocumentError("invalid_url")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise DocumentError("invalid_scheme_or_host")
        if parsed.username is not None or parsed.password is not None:
            raise DocumentError("credentials_in_url")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80):
            raise DocumentError("nonstandard_port")
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if "%" in host or host.rstrip(".") in ("localhost", "localhost.localdomain"):
            raise DocumentError("non_public_address")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9.-]+", host):
                raise DocumentError("invalid_host") from None
        else:
            _public(host)
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses:
            raise DocumentError("dns_empty")
        # Reject mixed public/private answers, then connect to a validated numeric
        # sockaddr directly (no second resolver call and no rebinding window).
        for _, _, _, _, address in addresses:
            _public(address[0])
        family, kind, proto, _, address = addresses[0]
        target = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parsed.query:
            target += "?" + quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
        clean = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        return clean, parsed.scheme, host, port, target, (family, kind, proto, address)
    except DocumentError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise DocumentError("invalid_url") from exc


def _connection(scheme, host, port, address, timeout):
    family, kind, proto, sockaddr = address
    sock = socket.socket(family, kind, proto)
    try:
        sock.settimeout(timeout)
        sock.connect(sockaddr)
        if scheme == "https":
            context = ssl.create_default_context()
            context.set_alpn_protocols(["http/1.1"])
            sock = context.wrap_socket(sock, server_hostname=host)
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.sock = sock
        return connection
    except Exception:
        sock.close()
        raise


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _save(root, directory, suffix, payload, mime):
    sha = hashlib.sha256(payload).hexdigest()
    parent = root / directory
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or parent.resolve().parent != root:
        raise DocumentError("unsafe_storage_path")
    path = parent / (sha + suffix)
    if path.is_symlink():
        raise DocumentError("unsafe_storage_path")
    fd, tmp = tempfile.mkstemp(prefix=".document-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, path)  # Atomic create-only publication; never overwrite.
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                raise DocumentError("immutable_file_conflict") from None
    finally:
        os.unlink(tmp)
    return {
        "path": str(path.relative_to(root)),
        "sha256": sha,
        "bytes": len(payload),
        "mime": mime,
    }


def _parse_worker(path):
    # Untrusted PDF decompression can greatly exceed the compressed download.
    # Limits are process-local and never change the Celery worker's resources.
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    except (ValueError, OSError):
        return {
            "parse_status": "parse_unavailable",
            "reason": "resource_limits_unavailable",
        }
    return _extract_pdf(path)


def _extract_pdf(path):
    """Extraction core; production callers must use the bounded worker."""
    try:
        import pypdf
    except ImportError:
        return {"parse_status": "parse_unavailable", "reason": "pypdf_not_installed"}
    try:
        reader = pypdf.PdfReader(path, strict=True)
        if reader.is_encrypted:
            return {"parse_status": "encrypted", "pages": []}
        page_count = len(reader.pages)
        if page_count > MAX_PARSE_PAGES:
            return {
                "parse_status": "parse_limit",
                "reason": "page_limit",
                "page_count": page_count,
            }
        pages, size = [], 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            size += len(text.encode("utf-8"))
            if size > MAX_PARSE_TEXT_BYTES:
                return {
                    "parse_status": "parse_limit",
                    "reason": "text_limit",
                    "page_count": page_count,
                }
            pages.append({"page_number": number, "text": text})
        return {
            "parse_status": "parsed"
            if any(p["text"].strip() for p in pages)
            else "no_text",
            "page_count": page_count,
            "pages": pages,
            "parser": "pypdf",
            "parser_version": pypdf.__version__,
        }
    except Exception as exc:
        return {"parse_status": "parse_failed", "error_type": type(exc).__name__}


def _parse_pdf(path, timeout):
    try:
        worker = subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--parse-pdf",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        )
        if worker.returncode:
            return {"parse_status": "parse_failed", "reason": "parser_process_failed"}
        return json.loads(worker.stdout)
    except subprocess.TimeoutExpired:
        return {"parse_status": "parse_timeout"}
    except (ValueError, OSError):
        return {"parse_status": "parse_failed", "reason": "parser_process_error"}


def fetch_document(url, root, max_bytes=25 * 1024 * 1024, timeout=20):
    """Download one public PDF/HTML; no redirect, size or parse failure loses state.

    ``status=downloaded`` means immutable bytes saved, not article verification or
    successful PDF extraction. ``files`` contains portable relative inventories.
    Timeout applies to each socket operation and separately to the parser process;
    DNS timing is controlled by the host resolver. Parent job has an overall limit.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be positive integer")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= 120
    ):
        raise ValueError("timeout must be between 0 and 120 seconds")
    result = {
        "status": "pending",
        "parse_status": "not_attempted",
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "redirects": [],
    }
    root = Path(root).resolve()
    current = url
    try:
        for redirects in range(MAX_REDIRECTS + 1):
            current, scheme, host, port, target, address = _target(current)
            result["final_url"] = current
            connection = _connection(scheme, host, port, address, timeout)
            try:
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Accept": "application/pdf,text/html,application/xhtml+xml",
                        "Accept-Encoding": "identity",
                        "User-Agent": "QuantMind-Documents/1",
                        "Connection": "close",
                    },
                )
                response = connection.getresponse()
                result["http_status"] = response.status
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise DocumentError("redirect_without_location")
                    if redirects == MAX_REDIRECTS:
                        raise DocumentError("redirect_limit")
                    current = urljoin(current, location)
                    result["redirects"].append(current)
                    continue
                if response.status != 200:
                    raise DocumentError("http_error")
                encoding = response.getheader("Content-Encoding", "identity").lower()
                if encoding not in ("", "identity"):
                    raise DocumentError("unsupported_content_encoding")
                length = response.getheader("Content-Length")
                if length is not None and (
                    not length.isdecimal() or int(length) > max_bytes
                ):
                    raise DocumentError(
                        "size_limit" if length.isdecimal() else "invalid_content_length"
                    )
                chunks, size = [], 0
                while True:
                    chunk = response.read(min(65536, max_bytes - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise DocumentError("size_limit")
                    chunks.append(chunk)
                if length is not None and size != int(length):
                    raise DocumentError("incomplete_download")
                payload = b"".join(chunks)
                declared = (
                    response.getheader("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                disposition = response.getheader("Content-Disposition", "").lower()
                pdf_expected = (
                    declared == "application/pdf"
                    or ".pdf" in disposition
                    or any(
                        urlsplit(u).path.lower().endswith(".pdf")
                        for u in (url, current)
                    )
                )
                is_pdf = payload.startswith(b"%PDF-") and payload.rstrip().endswith(
                    b"%%EOF"
                )
                is_html = bool(
                    re.search(
                        rb"<(?:!doctype\s+html|html|head|body|div|p)(?:\s|>)",
                        payload[:4096],
                        re.I,
                    )
                )
                if pdf_expected and not is_pdf:
                    raise DocumentError("pdf_content_mismatch")
                if is_pdf and declared in ("text/html", "application/xhtml+xml"):
                    raise DocumentError("mime_content_mismatch")
                if is_pdf:
                    suffix, mime = ".pdf", "application/pdf"
                elif is_html and declared in (
                    "",
                    "text/html",
                    "application/xhtml+xml",
                    "application/octet-stream",
                ):
                    suffix, mime = ".html", "text/html"
                else:
                    raise DocumentError("unsupported_or_invalid_document")
                artifact = _save(root, "attachments", suffix, payload, mime)
                result.update(
                    status="downloaded", mime=mime, document_sha256=artifact["sha256"]
                )
                result["files"].append(artifact)
                if is_pdf:
                    result["validation_status"] = "pdf_envelope_only"
                    parsed = _parse_pdf(root / artifact["path"], timeout)
                    result["parse_status"] = parsed["parse_status"]
                    if parsed["parse_status"] in ("parsed", "no_text", "encrypted"):
                        result["validation_status"] = "pdf_structure_valid"
                    result["parse_detail"] = {
                        k: v for k, v in parsed.items() if k != "pages"
                    }
                    if "pages" in parsed:
                        parsed["document_sha256"] = artifact["sha256"]
                        result["files"].append(
                            _save(
                                root,
                                "extracted",
                                ".json",
                                _json(parsed),
                                "application/json",
                            )
                        )
                else:
                    result["parse_status"] = "not_applicable"
                    result["validation_status"] = "html_content_unverified"
                return result
            finally:
                connection.close()
    except DocumentError as exc:
        result["status"] = str(exc)
    except (OSError, http.client.HTTPException) as exc:
        result["status"] = "download_error" if not result["files"] else "storage_error"
        result["error_type"] = type(exc).__name__
    return result


def _document_db(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "documents.sqlite"
    if path.is_symlink():
        raise DocumentError("unsafe_storage_path")
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2):
        db.close()
        raise ValueError("Unsupported document queue schema version")
    if version == 0:
        db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, observation TEXT NOT NULL, url TEXT NOT NULL,
                expected_mime TEXT, download_status TEXT NOT NULL DEFAULT 'pending',
                parse_status TEXT NOT NULL DEFAULT 'not_attempted',
                download_tries INTEGER NOT NULL DEFAULT 0, parse_tries INTEGER NOT NULL DEFAULT 0,
                retry_after REAL NOT NULL DEFAULT 0, parse_retry_after REAL NOT NULL DEFAULT 0,
                result TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS document_refs (
                id TEXT PRIMARY KEY, observation TEXT NOT NULL, api_name TEXT NOT NULL,
                record_sha256 TEXT, field TEXT, source_url TEXT, document_id TEXT, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS document_attempts (
                id INTEGER PRIMARY KEY, document_id TEXT NOT NULL,
                phase TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS document_download_due ON documents(download_status,retry_after);
            PRAGMA user_version=1;
            COMMIT;
        """)
    if db.execute("PRAGMA user_version").fetchone()[0] == 1:
        # Version 2 only adds a reuse lookup index; old jobs/references stay intact.
        db.executescript("""
            BEGIN IMMEDIATE;
            CREATE INDEX IF NOT EXISTS document_reference_reuse
                ON document_refs(api_name,record_sha256,field,source_url,document_id);
            PRAGMA user_version=2;
            COMMIT;
        """)
    return db


def _reference_hash(value):
    # Parquet readers may expose datetime/Decimal/bytes scalars. Their tagged
    # identity remains stable without changing the stored supplier payload.
    def scalar(item):
        from decimal import Decimal

        if isinstance(item, (date, datetime)):
            return {"$type": type(item).__name__, "value": item.isoformat()}
        if isinstance(item, Decimal):
            return {"$decimal": str(item)}
        if isinstance(item, bytes):
            return {"$bytes_hex": item.hex()}
        raise TypeError("Unsupported document record scalar")

    return hashlib.sha256(
        json.dumps(
            value,
            default=scalar,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def enqueue_documents(root, observation, api_name, records, fields):
    """Register references from saved JSON/Parquet rows; never guess missing URLs.

    Unchanged API/row identity/field/URL/MIME reuses downloaded or pending work.
    Every observation retains its own reference and original download timestamp.
    Metadata or URL changes create work; silent same-URL document revisions need
    a separate periodic validation policy and are not detected by this reuse.
    Empty observations and missing/invalid URL cells remain explicit references.
    """
    if not all(isinstance(v, str) and v for v in (observation, api_name)):
        raise ValueError("observation and api_name are required")
    if not isinstance(fields, (list, tuple)) or any(
        not isinstance(f, str) or not f for f in fields
    ):
        raise ValueError("fields must be attachment field names")
    if len(set(fields)) != len(fields):
        raise ValueError("Duplicate attachment fields")
    count = {"enqueued": 0, "missing": 0, "existing": 0, "references": 0, "reused": 0}
    db = _document_db(root)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            saw_record = False
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("records must contain saved record objects")
                saw_record = True
                known_identity = record.get("_row_identity")
                record_sha = (
                    known_identity
                    if isinstance(known_identity, str)
                    and re.fullmatch(r"[a-f0-9]{64}", known_identity)
                    else _reference_hash(
                        {
                            k: v
                            for k, v in record.items()
                            if k not in ("_fetched_at", "_observation")
                        }
                    )
                )
                for field in fields or ("",):
                    value = record.get(field)
                    valid = isinstance(value, str) and bool(value.strip())
                    status = (
                        "queued"
                        if valid
                        else "not_applicable"
                        if not field
                        else "missing_url"
                        if value is None or value == ""
                        else "invalid_url_value"
                    )
                    expected = (
                        "application/pdf"
                        if field == "pdf_url"
                        or (
                            field == "url" and api_name in ("anns_d", "research_report")
                        )
                        else None
                    )
                    ref_id = _reference_hash(
                        [observation, api_name, record_sha, field, value]
                    )
                    job_id = None
                    if valid:
                        existing = db.execute(
                            "SELECT document_id FROM document_refs WHERE id=?",
                            (ref_id,),
                        ).fetchone()
                        if existing is not None:
                            count["existing"] += 1
                            continue
                        reusable = db.execute(
                            """SELECT d.id,d.download_status FROM document_refs r
                            JOIN documents d ON r.document_id=d.id
                            WHERE r.api_name=? AND r.record_sha256=? AND r.field=? AND r.source_url=?
                              AND d.expected_mime IS ? AND d.download_status IN ('downloaded','pending','retry')
                            ORDER BY CASE WHEN d.download_status='downloaded' THEN 0 ELSE 1 END,d.rowid DESC
                            LIMIT 1""",
                            (api_name, record_sha, field, value, expected),
                        ).fetchone()
                        if reusable is not None:
                            job_id = reusable["id"]
                            status = (
                                "reused"
                                if reusable["download_status"] == "downloaded"
                                else "reused_pending"
                            )
                            count["reused"] += 1
                        else:
                            job_id = _reference_hash(
                                [
                                    observation,
                                    api_name,
                                    record_sha,
                                    field,
                                    value,
                                    expected,
                                ]
                            )
                            inserted = db.execute(
                                "INSERT OR IGNORE INTO documents(id,observation,url,expected_mime) VALUES(?,?,?,?)",
                                (job_id, observation, value, expected),
                            ).rowcount
                            count["enqueued" if inserted else "existing"] += 1
                    else:
                        count["missing"] += 1
                    count["references"] += db.execute(
                        "INSERT OR IGNORE INTO document_refs VALUES(?,?,?,?,?,?,?,?)",
                        (
                            ref_id,
                            observation,
                            api_name,
                            record_sha,
                            field,
                            value if isinstance(value, str) else None,
                            job_id,
                            status,
                        ),
                    ).rowcount
            if not saw_record:
                ref_id = hashlib.sha256(
                    _json([observation, api_name, "no_records", fields])
                ).hexdigest()
                count["references"] += db.execute(
                    "INSERT OR IGNORE INTO document_refs VALUES(?,?,?,?,?,?,?,?)",
                    (
                        ref_id,
                        observation,
                        api_name,
                        None,
                        None,
                        None,
                        None,
                        "no_records",
                    ),
                ).rowcount
        return count
    finally:
        db.close()


def _download_job(url, root, timeout):
    """Bound the complete download (including DNS/redirects and PDF subprocess)."""
    worker = subprocess.Popen(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--fetch-document"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        start_new_session=True,
    )
    try:
        output, _ = worker.communicate(
            _json({"url": url, "root": str(root), "timeout": min(20, timeout)}),
            timeout=timeout,
        )
        if worker.returncode:
            return {
                "status": "download_error",
                "parse_status": "not_attempted",
                "reason": "download_process_failed",
                "files": [],
            }
        return json.loads(output)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        worker.communicate()
        return {
            "status": "download_timeout",
            "parse_status": "not_attempted",
            "files": [],
        }
    except (ValueError, OSError):
        return {
            "status": "download_error",
            "parse_status": "not_attempted",
            "reason": "download_process_error",
            "files": [],
        }
    finally:
        if worker.poll() is None:
            try:
                os.killpg(worker.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            worker.communicate()


def _parse_saved(root, result, timeout):
    result = dict(result)
    files = list(result.get("files", []))
    pdf = next((f for f in files if f.get("mime") == "application/pdf"), None)
    if not pdf or not re.fullmatch(r"attachments/[a-f0-9]{64}\.pdf", pdf["path"]):
        return {
            **result,
            "parse_status": "parse_failed",
            "parse_detail": {"reason": "saved_pdf_missing"},
        }
    path = Path(root) / pdf["path"]
    if (
        path.is_symlink()
        or path.parent.is_symlink()
        or hashlib.sha256(path.read_bytes()).hexdigest() != pdf["sha256"]
    ):
        return {
            **result,
            "parse_status": "parse_failed",
            "parse_detail": {"reason": "saved_pdf_checksum"},
        }
    parsed = _parse_pdf(path, timeout)
    result["parse_status"] = parsed["parse_status"]
    result["parse_detail"] = {k: v for k, v in parsed.items() if k != "pages"}
    if parsed["parse_status"] in ("parsed", "no_text", "encrypted"):
        result["validation_status"] = "pdf_structure_valid"
    if "pages" in parsed:
        parsed["document_sha256"] = pdf["sha256"]
        artifact = _save(
            Path(root).resolve(),
            "extracted",
            ".json",
            _json(parsed),
            "application/json",
        )
        if artifact not in files:
            files.append(artifact)
    result["files"] = files
    return result


def run_documents(root, max_documents=1, max_seconds=30):
    """Advance bounded work; download and local parse retries use separate clocks.

    Five attempts per phase with exponential backoff. Exhausted, encrypted,
    no-text, size/parse-limit and invalid URL outcomes stay visible as gaps.
    This function has no authority check: the production parent must enforce it.
    """
    if (
        isinstance(max_documents, bool)
        or not isinstance(max_documents, int)
        or max_documents < 0
    ):
        raise ValueError("max_documents must be nonnegative")
    if (
        isinstance(max_seconds, bool)
        or not isinstance(max_seconds, (int, float))
        or not 0 < max_seconds <= 300
    ):
        raise ValueError("max_seconds must be between 0 and 300")
    root = Path(root).resolve()
    db = _document_db(root)
    processed, started = 0, time.monotonic()
    try:
        lock_path = root / "documents.lock"
        if lock_path.is_symlink():
            raise DocumentError("unsafe_storage_path")
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "already_running", "processed": 0}
            while (
                processed < max_documents and time.monotonic() - started < max_seconds
            ):
                now = time.time()
                job = db.execute(
                    """SELECT * FROM documents WHERE
                    (download_status IN ('pending','retry') AND retry_after<=?) OR
                    (download_status='downloaded' AND parse_status IN ('parse_unavailable','parse_failed','parse_timeout')
                     AND parse_tries<5 AND parse_retry_after<=?)
                    ORDER BY id LIMIT 1""",
                    (now, now),
                ).fetchone()
                if job is None:
                    break
                remaining = max_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                phase = (
                    "parse" if job["download_status"] == "downloaded" else "download"
                )
                previous = json.loads(job["result"])
                try:
                    result = (
                        _parse_saved(root, previous, remaining)
                        if phase == "parse"
                        else _download_job(job["url"], root, remaining)
                    )
                except Exception as exc:
                    result = {
                        **previous,
                        "status": "download_error"
                        if phase == "download"
                        else "downloaded",
                        "parse_status": "parse_failed"
                        if phase == "parse"
                        else "not_attempted",
                        "error_type": type(exc).__name__,
                    }
                if (
                    phase == "download"
                    and result.get("status") == "downloaded"
                    and job["expected_mime"]
                    and result.get("mime") != job["expected_mime"]
                ):
                    result["status"] = "expected_mime_mismatch"
                dtries = job["download_tries"] + (phase == "download")
                ptries = job["parse_tries"] + (
                    phase == "parse" or result.get("mime") == "application/pdf"
                )
                good = result.get("status") == "downloaded"
                terminal = result.get("status") in {
                    "invalid_url",
                    "invalid_scheme_or_host",
                    "credentials_in_url",
                    "nonstandard_port",
                    "non_public_address",
                    "invalid_host",
                    "size_limit",
                    "unsupported_or_invalid_document",
                }
                state = (
                    "downloaded"
                    if good
                    else "blocked"
                    if terminal or dtries >= 5
                    else "retry"
                )
                delay = min(3600, 60 * 2 ** min(max(dtries, ptries), 6))
                with db:
                    db.execute(
                        "INSERT INTO document_attempts(document_id,phase,result,created_at) VALUES(?,?,?,?)",
                        (job["id"], phase, json.dumps(result), now),
                    )
                    db.execute(
                        "UPDATE documents SET download_status=?,parse_status=?,download_tries=?,parse_tries=?,retry_after=?,parse_retry_after=?,result=? WHERE id=?",
                        (
                            state,
                            result.get("parse_status", "not_attempted"),
                            dtries,
                            ptries,
                            now + delay,
                            now + delay,
                            json.dumps(result),
                            job["id"],
                        ),
                    )
                processed += 1
        return {"status": "ok", "processed": processed, "counts": _document_counts(db)}
    finally:
        db.close()


def _document_counts(db):
    return [
        dict(row)
        for row in db.execute(
            "SELECT download_status,parse_status,count(*) AS documents FROM documents GROUP BY download_status,parse_status"
        )
    ]


def document_inventory(root):
    """Return portable immutable files, all observation mappings and phase status.

    SQLite/locks never belong in a release. Include unreferenced committed files
    left by a killed worker; the parent's release verifier checks their hashes.
    """
    root = Path(root).resolve()
    db = _document_db(root)
    try:
        db.execute("BEGIN")
        mappings = [
            dict(row)
            for row in db.execute("""SELECT r.*,d.observation AS validation_observation,d.expected_mime,d.download_status,d.parse_status,
            d.download_tries,d.parse_tries,d.result AS latest_result FROM document_refs r
            LEFT JOIN documents d ON r.document_id=d.id ORDER BY r.id""")
        ]
        for mapping in mappings:
            mapping["latest_result"] = (
                json.loads(mapping["latest_result"])
                if mapping["latest_result"]
                else None
            )
        attempts = [
            dict(row)
            for row in db.execute(
                "SELECT document_id,phase,result,created_at FROM document_attempts ORDER BY id"
            )
        ]
        for attempt in attempts:
            attempt["result"] = json.loads(attempt["result"])
        counts = _document_counts(db)
        reference_counts = [
            dict(row)
            for row in db.execute(
                "SELECT status,count(*) AS references_count FROM document_refs GROUP BY status"
            )
        ]
        db.commit()
        files = []
        for directory, extensions in (
            ("attachments", {"pdf": "application/pdf", "html": "text/html"}),
            ("extracted", {"json": "application/json"}),
        ):
            parent = root / directory
            if parent.is_symlink():
                raise DocumentError("unsafe_storage_path")
            if parent.exists():
                for path in sorted(parent.iterdir()):
                    if path.name.startswith(".document-"):
                        continue
                    if (
                        path.is_symlink()
                        or not re.fullmatch(r"[a-f0-9]{64}\.(pdf|html|json)", path.name)
                        or path.suffix[1:] not in extensions
                    ):
                        raise DocumentError("unsafe_storage_path")
                    files.append(
                        {
                            "path": str(path.relative_to(root)),
                            "sha256": path.stem,
                            "bytes": path.stat().st_size,
                            "mime": extensions[path.suffix[1:]],
                        }
                    )
        return {
            "schema_version": 1,
            "files": files,
            "mappings": mappings,
            "attempts": attempts,
            "counts": counts,
            "reference_counts": reference_counts,
        }
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--parse-pdf":
        print(_json(_parse_worker(sys.argv[2])).decode("utf-8"))
    elif len(sys.argv) == 2 and sys.argv[1] == "--fetch-document":
        print(
            _json(fetch_document(**json.loads(sys.stdin.buffer.read()))).decode("utf-8")
        )
