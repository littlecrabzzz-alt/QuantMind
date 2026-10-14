"""Resumable PDF transcription, with explicit staging and archive ingestion.

Staging only reads the archive. Capped runs leave page checkpoints, never a
retirement-ready partial extraction. Credentials are obtained lazily in memory.
CLI stage uses document workers and page-workers (both default to 4): at most
workers * page_workers model requests are in flight globally (16 by default).
Quota waits retry only the affected page within its worker; choose both limits
together to fit the model quota. Direct stage_document calls default to one
page worker and require a thread-safe client when page_workers > 1.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from email.utils import parsedate_to_datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from urllib import error, request

from backend.shared import tushare_documents as docs


class QuotaExceeded(Exception):
    def __init__(self, retry_after=600):
        self.retry_after = retry_after
        super().__init__("OCR quota exceeded")


class GLMClient:
    def __init__(
        self,
        model="glm-5.3-flash",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        key_command=("pi", "auth", "print-api-key", "--provider", "glm"),
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.key_command = key_command
        self._key = None
        self._key_lock = threading.Lock()

    def _api_key(self):
        with self._key_lock:
            if self._key is None:
                result = subprocess.run(
                    self.key_command, capture_output=True, text=True, timeout=30
                )
                if result.returncode or not result.stdout.strip():
                    raise RuntimeError("Unable to obtain GLM credential")
                self._key = result.stdout.strip()
            return self._key

    @staticmethod
    def _quota(payload):
        detail = payload.get("error") if isinstance(payload, dict) else None
        if not detail:
            return False
        message = json.dumps(detail, ensure_ascii=False).lower()
        return any(word in message for word in (
            "quota", "rate limit", "rate_limit", "too many requests",
            "balance", "resource exhausted", "额度", "余额", "限流", "频率",
            "1301", "1302", "1303", "1304", "1305", "1308", "1309",
        ))

    @staticmethod
    def _retry_after(headers):
        value = headers.get("Retry-After") if headers else None
        try:
            return max(0, float(value))
        except (TypeError, ValueError):
            try:
                return max(0, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return 600

    def transcribe(self, png_bytes):
        payload = {
            "model": self.model,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": (
                    "请将图片中的全部文字原样转写，保持段落顺序，"
                    "表格列用制表符分隔。只输出转写结果，不解释、不总结。"
                )},
                {"type": "image_url", "image_url": {"url":
                    "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")}},
            ]}],
        }
        req = request.Request(
            self.base_url + "/chat/completions", data=docs._json(payload),
            headers={"Authorization": "Bearer " + self._api_key(),
                     "Content-Type": "application/json"}, method="POST",
        )
        for attempt in range(4):
            try:
                with request.urlopen(req, timeout=180) as response:
                    body = json.loads(response.read())
                    if self._quota(body):
                        raise QuotaExceeded(self._retry_after(response.headers))
                if body.get("error"):
                    raise RuntimeError("GLM API error")
                text = body["choices"][0]["message"]["content"]
                if not isinstance(text, str):
                    raise RuntimeError("Invalid GLM transcription")
                return text
            except error.HTTPError as exc:
                try:
                    body = json.loads(exc.read())
                except (ValueError, OSError):
                    body = {}
                finally:
                    exc.close()
                if exc.code == 429 or self._quota(body):
                    raise QuotaExceeded(self._retry_after(exc.headers)) from None
                if not 500 <= exc.code < 600 or attempt == 3:
                    raise RuntimeError(f"GLM HTTP error {exc.code}") from None
            except (error.URLError, OSError):
                if attempt == 3:
                    raise RuntimeError("GLM network error after retries") from None
            time.sleep(2 ** attempt)


def _root(path):
    path = Path(path).absolute()
    if path.is_symlink():
        raise ValueError("unsafe_path")
    return path.resolve()


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("invalid_document_sha256")
    return value


def _pdf(root, sha):
    path = root / "attachments" / f"{_sha(sha)}.pdf"
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("unsafe_or_missing_pdf")
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("pdf_checksum_mismatch")
    return path


def _has_table(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def ocr_candidates(root, *, limit, after=None):
    root = _root(root)
    if type(limit) is not int or limit < 1:
        raise ValueError("invalid_limit")
    cursor = _sha(after) if after is not None else ""
    path = root / "documents.sqlite"
    if path.is_symlink():
        raise ValueError("unsafe_path")
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        retired = (
            "AND NOT EXISTS (SELECT 1 FROM attachment_retirements r "
            "WHERE r.sha256=json_extract(d.result,'$.document_sha256')) "
            if _has_table(db, "attachment_retirements") else ""
        )
        rows = db.execute(
            "SELECT d.*,json_extract(d.result,'$.document_sha256') AS sha "
            "FROM documents d WHERE download_status='downloaded' "
            "AND parse_status IN ('no_text','encrypted') "
            "AND json_extract(d.result,'$.document_sha256')>? " + retired +
            "ORDER BY sha,d.id", (cursor,),
        )
        items = {}
        for row in rows:
            sha = row["sha"]
            try:
                _sha(sha)
            except ValueError:
                continue
            result = json.loads(row["result"])
            name = f"attachments/{sha}.pdf"
            pdf = root / name
            if (result.get("status") != "downloaded"
                    or result.get("attachment_status") == "retired"
                    or pdf.is_symlink() or pdf.parent.is_symlink() or not pdf.is_file()
                    or not any(f.get("path") == name and f.get("sha256") == sha
                               and f.get("mime") == "application/pdf"
                               for f in result.get("files", []))):
                continue
            if sha not in items:
                if len(items) == limit:
                    break
                items[sha] = {"sha256": sha, "path": name,
                              "document_ids": [], "parse_status": row["parse_status"]}
            items[sha]["document_ids"].append(row["id"])
        return list(items.values())


def _write_json(path, body):
    if path.is_symlink():
        raise ValueError("unsafe_staging_path")
    fd, temporary = tempfile.mkstemp(prefix=".ocr-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(docs._json(body))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate(body, sha):
    pages = body.get("pages")
    if (body.get("document_sha256") != sha
            or type(body.get("page_count")) is not int
            or not isinstance(pages, list) or not pages
            or len(pages) != body["page_count"]
            or body.get("parser") not in ("glm-ocr", "pypdf-decrypted")
            or not isinstance(body.get("parser_version"), str)
            or any(not isinstance(p, dict) or type(p.get("page_number")) is not int
                   or p["page_number"] != n or not isinstance(p.get("text"), str)
                   for n, p in enumerate(pages, 1))):
        raise ValueError("invalid_staged_document")


def stage_document(
    root, staging, item, client, *, sleep=time.sleep, max_pages=None, page_workers=1
):
    """Checkpoint each finished page; retry missing pages with bounded concurrency.

    Each call runs at most page_workers transcriptions at once. Concurrent
    document calls multiply that bound by the number of document workers.
    """
    import pypdf

    root, staging = _root(root), _root(staging)
    sha = _sha(item["sha256"])
    if item["path"] != f"attachments/{sha}.pdf":
        raise ValueError("unsafe_path")
    pdf = _pdf(root, sha)
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise ValueError("invalid_max_pages")
    if type(page_workers) is not int or page_workers < 1:
        raise ValueError("invalid_page_workers")
    staging.mkdir(parents=True, exist_ok=True)
    completed = staging / f"{sha}.json"
    if completed.exists():
        if completed.is_symlink():
            raise ValueError("unsafe_staging_path")
        body = json.loads(completed.read_bytes())
        _validate(body, sha)
        return {"status": "staged" if body["parse_status"] == "parsed" else "empty",
                "pages": body["page_count"]}

    reader = pypdf.PdfReader(pdf)
    decrypted = bool(reader.decrypt("")) if reader.is_encrypted else False
    page_count = len(reader.pages)
    if page_count == 0:
        return {"status": "empty", "pages": 0}
    local_pages = None
    if decrypted:
        try:
            local_pages = [{"page_number": n, "text": page.extract_text() or ""}
                           for n, page in enumerate(reader.pages, 1)]
        except Exception:
            local_pages = None
        if local_pages and not any(p["text"].strip() for p in local_pages):
            local_pages = None
    parser = "pypdf-decrypted" if local_pages else "glm-ocr"
    version = pypdf.__version__ if local_pages else client.model
    progress = staging / sha
    if progress.is_symlink():
        raise ValueError("unsafe_staging_path")
    progress.mkdir(exist_ok=True)
    metadata = {"document_sha256": sha, "page_count": page_count,
                "parser": parser, "parser_version": version}
    meta_path = progress / "metadata.json"
    if meta_path.exists():
        if meta_path.is_symlink() or json.loads(meta_path.read_bytes()) != metadata:
            raise ValueError("staging_configuration_changed")
    else:
        _write_json(meta_path, metadata)
    budget = page_count if max_pages is None else min(page_count, max_pages)
    with tempfile.TemporaryDirectory(prefix="tushare-ocr-") as temporary:
        def transcribe_page(number):
            checkpoint = progress / f"{number}.json"
            if checkpoint.exists():
                if checkpoint.is_symlink():
                    raise ValueError("unsafe_staging_path")
                page = json.loads(checkpoint.read_bytes())
                if (page.get("page_number") != number
                        or not isinstance(page.get("text"), str)):
                    raise ValueError("invalid_page_checkpoint")
            else:
                if local_pages:
                    text = local_pages[number - 1]["text"]
                else:
                    executable = shutil.which("pdftoppm")
                    if executable is None and Path("/opt/homebrew/bin/pdftoppm").is_file():
                        executable = "/opt/homebrew/bin/pdftoppm"
                    if executable is None:
                        raise RuntimeError("pdftoppm is required")
                    prefix = Path(temporary) / f"page-{number}"
                    rendered = subprocess.run(
                        [executable, "-f", str(number), "-l", str(number),
                         "-r", "120", "-png", "-singlefile", str(pdf), str(prefix)],
                        capture_output=True, timeout=180,
                    )
                    if rendered.returncode:
                        raise RuntimeError("PDF page rendering failed")
                    png = prefix.with_suffix(".png").read_bytes()
                    while True:
                        try:
                            text = client.transcribe(png)
                            break
                        except QuotaExceeded as exc:
                            sleep(exc.retry_after)
                    if not isinstance(text, str):
                        raise ValueError("invalid_transcription")
                page = {"page_number": number, "text": text}
                _write_json(checkpoint, page)
            return page

        numbers = range(1, budget + 1)
        if page_workers == 1:
            pages = [transcribe_page(number) for number in numbers]
        else:
            # Workers persist their own checkpoints even if another page fails.
            # Shutdown waits for running pages before removing rendered files.
            with ThreadPoolExecutor(max_workers=page_workers) as pool:
                pages = list(pool.map(transcribe_page, numbers))
    nonempty = any(p["text"].strip() for p in pages)
    if budget == page_count:
        _write_json(completed, {**metadata, "pages": pages,
                               "parse_status": "parsed" if nonempty else "no_text"})
    return {"status": "staged" if nonempty else "empty", "pages": len(pages)}


def _extraction_files(root, files, sha):
    # Keep originals on disk, but supersede unusable extraction references;
    # retirement validates every extraction still referenced by the document.
    kept = []
    for descriptor in files:
        name = descriptor.get("path", "")
        if re.fullmatch(r"extracted/[a-f0-9]{64}\.json", name):
            path = root / name
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("unsafe_path")
            body = json.loads(path.read_bytes())
            if (body.get("document_sha256") == sha
                    and (body.get("parse_status") != "parsed"
                         or not any(p.get("text", "").strip()
                                    for p in body.get("pages", [])))):
                continue
        kept.append(descriptor)
    return kept


def ingest_staged(root, staging):
    root, staging = _root(root), _root(staging)
    paths = sorted(staging.glob("*.json"))
    if not paths:
        return {"ingested": 0}
    ingested = staging / "ingested"
    if ingested.is_symlink():
        raise ValueError("unsafe_staging_path")
    ingested.mkdir(exist_ok=True)
    count = 0
    with closing(docs._document_db(root)) as db:
        for path in paths:
            sha = _sha(path.stem)
            if path.is_symlink():
                raise ValueError("unsafe_staging_path")
            body = json.loads(path.read_bytes())
            _validate(body, sha)
            if (body.get("parse_status") != "parsed"
                    or not any(p["text"].strip() for p in body["pages"])):
                continue
            _pdf(root, sha)
            with db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM attachment_retirements WHERE sha256=?",
                              (sha,)).fetchone():
                    raise ValueError("attachment_retiring")
                rows = db.execute(
                    "SELECT d.* FROM documents d JOIN document_attachment_links l "
                    "ON l.document_id=d.id WHERE l.sha256=? ORDER BY d.id", (sha,),
                ).fetchall()
                if not rows:
                    raise ValueError("unregistered_pdf")
                if _has_table(db, "document_claims") and db.execute(
                    "SELECT 1 FROM document_claims c JOIN document_attachment_links l "
                    "ON l.document_id=c.document_id WHERE l.sha256=?", (sha,),
                ).fetchone():
                    raise ValueError("document_busy")
                extracted = docs._save(root, "extracted", ".json", docs._json(body),
                                       "application/json")
                detail = {k: v for k, v in body.items() if k != "pages"}
                for row in rows:
                    result = json.loads(row["result"])
                    if (row["download_status"] != "downloaded"
                            or result.get("status") != "downloaded"
                            or result.get("document_sha256") != sha):
                        raise ValueError("document_state_changed")
                    files = _extraction_files(root, result.get("files", []), sha)
                    if extracted not in files:
                        files.append(extracted)
                    result.update(files=files, parse_status="parsed",
                                  validation_status="pdf_structure_valid",
                                  parse_detail=detail, ocr=detail)
                    db.execute("UPDATE documents SET parse_status='parsed',result=? WHERE id=?",
                               (docs._json(result).decode(), row["id"]))
                if _has_table(db, "document_index_files"):
                    db.execute("INSERT OR IGNORE INTO document_index_files VALUES(?,?,?,?)",
                               tuple(extracted[k] for k in ("path", "sha256", "bytes", "mime")))
            destination = ingested / path.name
            if destination.is_symlink():
                raise ValueError("unsafe_staging_path")
            if destination.exists() and destination.read_bytes() != path.read_bytes():
                raise ValueError("staging_conflict")
            os.replace(path, destination)
            count += 1
    return {"ingested": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    ingest = commands.add_parser("ingest")
    for command in (stage, ingest):
        command.add_argument("--root", required=True)
        command.add_argument("--staging", required=True)
    stage.add_argument("--workers", type=int, default=4)
    stage.add_argument(
        "--page-workers", type=int, default=4,
        help="pages per document; model concurrency is workers * page-workers",
    )
    stage.add_argument("--model", default="glm-5.3-flash")
    stage.add_argument("--max-pages", type=int)
    stage.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "ingest":
        print(json.dumps(ingest_staged(args.root, args.staging)))
        return
    if (args.workers < 1 or args.page_workers < 1
            or (args.limit is not None and args.limit < 1)
            or (args.max_pages is not None and args.max_pages < 1)):
        parser.error("workers, page-workers, limit and max-pages must be positive")
    client = GLMClient(model=args.model)
    total = completed = attempted = 0
    cursor = None

    def run(item):
        try:
            return stage_document(args.root, args.staging, item, client,
                                  max_pages=args.max_pages,
                                  page_workers=args.page_workers)
        except Exception as exc:
            logging.error("OCR failed sha=%s error=%s", item["sha256"], type(exc).__name__)
            return None

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while args.limit is None or attempted < args.limit:
            budget = args.workers if args.limit is None else min(args.workers, args.limit - attempted)
            items = ocr_candidates(args.root, limit=budget, after=cursor)
            if not items:
                break
            futures = [pool.submit(run, item) for item in items]
            for future in futures:
                report = future.result()
                attempted += 1
                if report is not None:
                    completed += 1
                    total += report["pages"]
                    print(f"document={completed} pages={report['pages']} total_pages={total}", flush=True)
            cursor = items[-1]["sha256"]


if __name__ == "__main__":
    main()
