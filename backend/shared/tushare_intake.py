"""Public catalogue audit and bounded, immutable Tushare observations.

Raw supplier codes/units stay untouched here. This is not a QuantDB writer or a
historical-completeness/PIT certificate. No scheduler is registered on import.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx

DOC_ROOT = "https://tushare.pro/document/2"
API_ROOT = "https://api.tushare.pro"
CYQ_CHIPS_EMPTY_MESSAGE = "指定数据不存在，请确认参数！"


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
        rows = table["rows"]
        # Section labels persist through examples/category tables. Only the
        # documented field-name header identifies a schema (also compact ones).
        if (
            not rows
            or not rows[0]
            or rows[0][0] != "名称"
            or (len(rows[0]) > 1 and rows[0][1] not in {"类型", "默认显示", "默认输出"})
        ):
            continue
        for row in rows[1:]:
            # Supplier fields include rate tenors (1w) and returns (3day).
            # They are quoted data columns, not Python/API identifiers.
            if row and re.fullmatch(r"[A-Za-z0-9_]+", row[0]):
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


def assess_response(
    payload, row_cap, required_fields, nullable_fields=(), positive_fields=()
):
    """A successful sample never certifies the completeness of its history."""
    if not isinstance(payload, dict):
        return {"status": "invalid_response"}
    code = payload.get("code")
    if code != 0:
        assessment = {
            "status": "rate_limited"
            if re.search(
                r"每分钟|每小时|频率|频次|too many|rate.limit",
                str(payload.get("msg", "")),
                re.I,
            )
            else "permission_denied"
            if code in (2002, 40203)
            or re.search(
                r"没有.{0,12}权限|无权访问|permission.denied|not.authorized",
                str(payload.get("msg", "")),
                re.I,
            )
            else "api_error",
            "code": code,
        }
        # Only an explicit named interface quota can isolate its cooldown.
        # Ambiguous/provider-wide errors retain the shared account backoff.
        quota = re.search(
            r"接口\(([A-Za-z0-9_]+)\)频率超限\(([1-9][0-9]*)次/(秒|分钟|小时|天)\)",
            str(payload.get("msg", "")),
        )
        if assessment["status"] == "rate_limited" and quota:
            assessment.update(
                rate_limit_api=quota[1],
                rate_limit_requests=int(quota[2]),
                rate_limit_window_seconds={
                    "秒": 1,
                    "分钟": 60,
                    "小时": 3600,
                    "天": 86400,
                }[quota[3]],
            )
        return assessment
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
    invalid = {}
    for field in positive_fields:
        if field in fields:
            index = fields.index(field)
            invalid[field] = sum(
                not (
                    isinstance(row[index], (int, float))
                    and not isinstance(row[index], bool)
                    and math.isfinite(row[index])
                    and row[index] > 0
                )
                for row in items
            )
    status = "sample_ok"
    if not items:
        status = "empty_unverified"
    elif missing or any(n for f, n in nulls.items() if f not in nullable_fields):
        status = "schema_gap"
    elif any(invalid.values()):
        status = "invalid_values"
    # An explicit upstream continuation flag is authoritative even below our
    # conservative row threshold. count=0 does not override retained rows.
    if len(items) >= row_cap or data.get("has_more") is True:
        status = "possibly_truncated"
    return {
        "status": status,
        "row_count": len(items),
        "supplier_has_more": data.get("has_more")
        if isinstance(data.get("has_more"), bool)
        else None,
        "missing_fields": missing,
        "null_counts": nulls,
        "invalid_positive_counts": invalid,
        "history_complete": False,
        "pit_verified": False,
    }


def _cyq_chips_supplier_empty(job, payload):
    if (
        job.get("api_name") != "cyq_chips"
        or not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 50101
        or payload.get("msg") != CYQ_CHIPS_EMPTY_MESSAGE
        or "data" not in payload
        or payload["data"] is not None
    ):
        return False
    params = job.get("params")
    if not isinstance(params, dict) or set(params) != {"ts_code", "trade_date"}:
        return False
    if not isinstance(params["ts_code"], str) or not re.fullmatch(
        r"T?[0-9]{6}\.(?:SH|SZ|BJ)", params["ts_code"]
    ):
        return False
    trade_date = params["trade_date"]
    if not isinstance(trade_date, str) or not re.fullmatch(r"[0-9]{8}", trade_date):
        return False
    try:
        datetime.strptime(trade_date, "%Y%m%d")
    except (TypeError, ValueError):
        return False
    return True


def validate_request_shape(job):
    """Enforce the four observed minimum contracts for every acquisition caller."""
    api = job["api_name"]
    if api == "fut_index_daily":
        from backend.shared.tushare_futures_extra_contracts import (
            validate_futures_index_request,
        )

        validate_futures_index_request(job["params"])
    elif api in ("idx_factor_pro", "fund_factor_pro", "cb_factor_pro"):
        from backend.shared.tushare_cross_asset_extra_contracts import (
            validate_cross_asset_request,
        )

        validate_cross_asset_request(api, job["params"])


def capture_sample(client, token, job, root: Path):
    """One request, no automatic retry/watermark. Store raw response plus metadata.

    Content objects deduplicate identical responses; observations preserve each
    fetch time. A release consists of immutable observations and object hashes.
    """
    validate_request_shape(job)
    if not token:
        raise ValueError("Missing token")
    # All callers, including finite probes, share this pre-HTTP reservation.
    from backend.shared.tushare_daily_quota import reserve

    daily = reserve(root, job["api_name"])
    if daily is not None and not daily["reserved"]:
        return {"api_name": job["api_name"], "status": "rate_limited",
                "local_daily_quota": daily, "upstream_calls": 0}
    request = {k: job[k] for k in ("api_name", "params", "fields")}
    started = utc_now()
    field_coverage = {
        "field_coverage": "unverified_default_or_invalid",
        "requested_missing_fields": None,
        "unexpected_returned_fields": None,
    }
    try:
        # httpx.post reads the complete response before returning. Do not call
        # raise_for_status first: HTTP failures still have original evidence.
        response = client.post(API_ROOT, json={**request, "token": token})
        content = response.content
    except httpx.HTTPStatusError as exc:
        # A caller's response hook may raise early; archive only an already-read
        # body and keep the HTTP classification when no complete body exists.
        response = exc.response
        try:
            content = response.content
        except httpx.ResponseNotRead:
            return {
                "api_name": job["api_name"],
                "status": "rate_limited"
                if response.status_code == 429
                else "transport_error",
                "error_type": type(exc).__name__,
                "http_status": response.status_code,
                "response_complete": False,
                **field_coverage,
            }
    except httpx.HTTPError as exc:
        # No complete response body is available. Exception messages/request
        # bodies may contain the token and must never be serialized.
        return {
            "api_name": job["api_name"],
            "status": "transport_error",
            "error_type": type(exc).__name__,
            "response_complete": False,
            **field_coverage,
        }
    # Preserve the existing raw-object contract, with defensive token redaction.
    raw = content.replace(token.encode(), b"[REDACTED_SECRET]")
    redacted = raw != content
    try:
        payload = json.loads(raw)
        response_format = "json"
    except (ValueError, UnicodeError):
        payload = None
        response_format = "non_json"
    if not response.is_success:
        assessment = {
            "status": "rate_limited"
            if response.status_code == 429
            else "transport_error",
            "error_type": "HTTPStatusError",
        }
    elif response_format == "non_json":
        assessment = {"status": "invalid_response"}
    else:
        assessment = assess_response(
            payload,
            job["row_cap"],
            job["required_fields"],
            job.get("nullable_fields", ()),
            job.get("positive_fields", ()),
        )
        if response.status_code == 200 and _cyq_chips_supplier_empty(job, payload):
            assessment = {
                "status": "empty_unverified",
                "code": 50101,
                "row_count": 0,
                "supplier_empty_hint": True,
                "coverage_proven": False,
                "history_complete": False,
                "pit_verified": False,
            }
    requested = request["fields"]
    requested = requested.split(",") if isinstance(requested, str) else []
    requested = [field.strip() for field in requested]
    # row_count is emitted only after successful response structure validation.
    # Presence is independent of null values and never proves undocumented fields.
    if (
        "row_count" in assessment
        and isinstance(payload.get("data"), dict)
        and requested
        and all(re.fullmatch(r"[A-Za-z0-9_]+", f) for f in requested)
    ):
        returned = set(payload["data"]["fields"])
        missing = sorted(set(requested) - returned)
        field_coverage.update(
            field_coverage="gap" if missing else "complete_for_explicit_request",
            requested_missing_fields=missing,
            unexpected_returned_fields=sorted(returned - set(requested)),
        )
        if missing and assessment["status"] == "sample_ok":
            assessment["status"] = "schema_gap"
    assessment.update(field_coverage)
    assessment.update(
        http_status=response.status_code,
        response_complete=True,
        response_format=response_format,
    )
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


def read_samples(root: Path, release_id: str, api_name: str):
    """Read a fixed release without credentials, refresh, or upstream fallback.

    Observations stay separate: current/historical members and ETF listing states
    must not be silently merged. Raw supplier codes, units and fields survive.
    """
    verify_release(root, release_id)
    manifest = json.loads(
        (root / "releases" / release_id / "manifest.json").read_bytes()
    )
    samples = []
    for result in manifest["results"]:
        if result["api_name"] != api_name:
            continue
        if "observation" not in result:
            samples.append({"assessment": result, "data": None})
            continue
        observed = json.loads(
            (root / "observations" / result["observation"]).read_bytes()
        )
        # An archived HTTP error is evidence, even when it contains valid JSON
        # resembling a successful API response. Keep it out of consumer data.
        assessment = observed["assessment"]
        payload = None
        if (
            assessment.get("status")
            not in (
                "transport_error",
                "rate_limited",
                "permission_denied",
                "api_error",
                "invalid_response",
            )
            and assessment.get("response_format") != "non_json"
        ):
            payload = json.loads(
                (root / "objects" / (result["object_sha256"] + ".json")).read_bytes()
            )
        samples.append(
            {
                "request": observed["request"],
                "fetched_at": observed["fetched_at"],
                "assessment": observed["assessment"],
                "data": payload.get("data") if isinstance(payload, dict) else None,
            }
        )
    if not samples:
        raise ValueError("Dataset absent from selected release; no upstream fallback")
    return samples
