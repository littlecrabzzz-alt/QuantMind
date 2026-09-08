"""Public catalogue audit and bounded, immutable Tushare observations.

Raw supplier codes/units stay untouched here. This is not a QuantDB writer or a
historical-completeness/PIT certificate. No scheduler is registered on import.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx

DOC_ROOT = "https://tushare.pro/document/2"
API_ROOT = "https://api.tushare.pro"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def digest(value: bytes):
    return hashlib.sha256(value).hexdigest()


class DocParser(HTMLParser):
    """Read the catalogue links and article tables, excluding footer/sidebar text."""

    def __init__(self):
        super().__init__()
        self.article_depth = 0
        self.sidebar_depth = 0
        self.links = {}
        self.link = None
        self.article = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.section = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.article_depth:
                self.article_depth += 1
            elif "col-md-9" in attrs.get("class", "").split():
                self.article_depth = 1
            if self.sidebar_depth:
                self.sidebar_depth += 1
            elif attrs.get("id") == "jstree":
                self.sidebar_depth = 1
        if tag == "a" and self.sidebar_depth:
            match = re.fullmatch(r"/document/2\?doc_id=(\d+)", attrs.get("href", ""))
            if match:
                self.link = [match[1], []]
        if not self.article_depth:
            return
        if tag in {"p", "br", "h2", "h3", "table"}:
            self.article.append("\n")
        if tag == "table":
            self.table = {"section": self.section, "rows": []}
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data):
        if self.link:
            self.link[1].append(data)
        if self.article_depth:
            self.article.append(data)
            if self.cell is not None:
                self.cell.append(data)
            if "输入参数" in data:
                self.section = "input"
            elif "输出参数" in data or "输出字段" in data:
                self.section = "output"

    def handle_endtag(self, tag):
        if tag == "a" and self.link:
            self.links[self.link[0]] = "".join(self.link[1]).strip()
            self.link = None
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None:
                self.table["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None
        if tag == "div":
            self.article_depth = max(0, self.article_depth - 1)
            self.sidebar_depth = max(0, self.sidebar_depth - 1)


def parse_document(html, doc_id, title):
    parser = DocParser()
    parser.feed(html)
    article = "".join(parser.article)
    names = re.findall(r"接口[：:]\s*([A-Za-z][A-Za-z0-9_]*)", article)
    schemas = {"input_fields": [], "output_fields": []}
    for table in parser.tables:
        key = table["section"] + "_fields"
        if key not in schemas:
            continue
        for row in table["rows"][1:]:
            if row and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", row[0]):
                if row[0] not in schemas[key]:
                    schemas[key].append(row[0])
    return {
        "doc_id": str(doc_id),
        "title": title,
        "url": f"{DOC_ROOT}?doc_id={doc_id}",
        "html_sha256": digest(html.encode("utf-8")),
        "api_names": sorted(set(names)),
        **schemas,
        "audit_status": "schema_extracted"
        if names and schemas["output_fields"]
        else "manual_review_required",
        "permission_status": "unprobed",
        "coverage_status": "not_ingested",
    }


def assess_response(payload, row_cap, required_fields, nullable_fields=()):
    """A successful sample never certifies the completeness of its history."""
    if not isinstance(payload, dict):
        return {"status": "invalid_response"}
    code = payload.get("code")
    if code != 0:
        return {
            "status": "permission_denied" if code == 2002 else "api_error",
            "code": code,
        }
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"status": "invalid_response"}
    fields, items = data.get("fields"), data.get("items")
    if (
        not isinstance(fields, list)
        or not isinstance(items, list)
        or not all(isinstance(f, str) for f in fields)
        or len(set(fields)) != len(fields)
        or not all(isinstance(row, list) and len(row) == len(fields) for row in items)
    ):
        return {"status": "invalid_response"}
    missing = sorted(set(required_fields) - set(fields))
    nulls = {
        f: sum(row[fields.index(f)] in (None, "") for row in items)
        for f in required_fields
        if f in fields
    }
    status = "sample_ok"
    if not items:
        status = "empty_unverified"
    elif missing or any(n for f, n in nulls.items() if f not in nullable_fields):
        status = "schema_gap"
    # Reaching the documented cap (or conservative threshold) stays unresolved.
    if len(items) >= row_cap:
        status = "possibly_truncated"
    return {
        "status": status,
        "row_count": len(items),
        "missing_fields": missing,
        "null_counts": nulls,
        "history_complete": False,
        "pit_verified": False,
    }


def capture_sample(client, token, job, root: Path):
    """One request, no automatic retry/watermark. Store raw response plus metadata.

    Content objects deduplicate identical responses; observations preserve each
    fetch time. A release consists of immutable observations and object hashes.
    """
    if not token:
        raise ValueError("Missing token")
    request = {k: job[k] for k in ("api_name", "params", "fields")}
    started = utc_now()
    try:
        response = client.post(API_ROOT, json={**request, "token": token})
        response.raise_for_status()
        # Defensive redaction if upstream accidentally echoes the request secret.
        raw = response.content.replace(token.encode(), b"[REDACTED_SECRET]")
        redacted = raw != response.content
        payload = json.loads(raw)
        assessment = assess_response(
            payload,
            job["row_cap"],
            job["required_fields"],
            job.get("nullable_fields", ()),
        )
    except httpx.HTTPError as exc:
        # Do not serialize exception messages/request bodies (could contain token).
        return {
            "api_name": job["api_name"],
            "status": "transport_error",
            "error_type": type(exc).__name__,
        }
    except (ValueError, UnicodeError):
        assessment = {"status": "invalid_response"}
    sha = digest(raw)
    objects = root / "objects"
    observations = root / "observations"
    objects.mkdir(parents=True, exist_ok=True)
    observations.mkdir(parents=True, exist_ok=True)
    obj = objects / (sha + ".json")
    temporary = objects / (uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(raw)
        try:
            os.link(temporary, obj)  # Atomic create, never overwrite published data.
        except FileExistsError:
            if digest(obj.read_bytes()) != sha:
                raise ValueError("Existing object checksum mismatch") from None
    finally:
        temporary.unlink(missing_ok=True)
    observation = {
        "schema_version": 1,
        "request": request,
        "requested_at": started,
        "fetched_at": utc_now(),
        "object_sha256": sha,
        "response_redacted": redacted,
        "assessment": assessment,
    }
    name = uuid4().hex + ".json"
    # Manifest publication happens only after all observation files are complete.
    with (observations / name).open("xb") as stream:
        stream.write(json_bytes(observation))
    return {
        "api_name": job["api_name"],
        "observation": name,
        "observation_sha256": digest(json_bytes(observation)),
        "object_sha256": sha,
        **assessment,
    }


def verify_release(root: Path, release_id: str):
    """Read-only verification after SSH/rsync; rejects incomplete/tampered copies."""
    if not re.fullmatch(r"probe-[a-f0-9]{32}", release_id):
        raise ValueError("Invalid release ID")
    manifest = json.loads(
        (root / "releases" / release_id / "manifest.json").read_bytes()
    )
    results = manifest["results"]
    verified = 0
    for result in results:
        if "observation" not in result:
            continue  # Transport failures have no response body to archive.
        name, sha = result["observation"], result["object_sha256"]
        if not re.fullmatch(r"[a-f0-9]{32}\.json", name):
            raise ValueError("Invalid observation name")
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid object hash")
        observed = (root / "observations" / name).read_bytes()
        if digest(observed) != result["observation_sha256"]:
            raise ValueError("Observation checksum mismatch")
        if json.loads(observed)["object_sha256"] != sha:
            raise ValueError("Observation object reference mismatch")
        if digest((root / "objects" / (sha + ".json")).read_bytes()) != sha:
            raise ValueError("Object checksum mismatch")
        verified += 1
    return {
        "status": "verified",
        "observations": verified,
        "failed_requests": sum(r.get("status") != "sample_ok" for r in results),
        "unarchived_requests": len(results) - verified,
        "rrg_status": "blocked_data",
    }
