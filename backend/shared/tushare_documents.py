"""Public document acquisition with pinned DNS, immutable files, bounded PDF parsing.

No credentials, queue, database, browser, cookies or proxy configuration is read.
The caller owns retries, authority checks and release publication.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--parse-pdf":
    print(_json(_parse_worker(sys.argv[2])).decode("utf-8"))
