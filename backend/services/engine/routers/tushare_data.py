"""Authenticated, fixed-release offline data reads; no provider fallback.

ROOT is deliberately not user/env configurable. Sandbox tests patch this module
constant. Register the router behind the engine's existing identity middleware.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.services.engine.auth_context import get_authenticated_identity
from backend.shared import tushare_store

ROOT = Path("/data/tushare")
RELEASE = r"^data-[a-f0-9]{64}$"
OBJECT = r"(?:documents|attachments|extracted)/[a-f0-9]{64}\.(?:json|pdf|html)"
router = APIRouter(
    prefix="/api/v1/tushare-data",
    tags=["Tushare offline data"],
    dependencies=[Depends(get_authenticated_identity)],
)


class DatasetQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str = Field(pattern=RELEASE)
    api_name: str = Field(min_length=1, max_length=100)
    fields: list[str] | None = Field(default=None, max_length=500)
    date_field: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    codes: list[str] | None = Field(default=None, max_length=2000)
    code_field: str = "ts_code"
    keyword: str | None = Field(default=None, max_length=2000)
    keyword_fields: list[str] | None = Field(default=None, max_length=100)
    as_of: str | None = None
    limit: int = Field(default=100, ge=1, le=2000, strict=True)


@contextmanager
def _errors():
    try:
        yield
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(404, "Fixed-release artifact unavailable") from None
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(400, "Invalid stored data or query parameters") from None
    except OSError:
        raise HTTPException(409, "Stored artifact could not be read") from None


def _path(relative):
    path = ROOT / relative
    # Check ancestors as well as the leaf: resolve() alone hides symlinks.
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise HTTPException(409, "Symlink artifacts are not readable")
    return path


def _manifest(release_id):
    if not re.fullmatch(RELEASE, release_id):
        raise HTTPException(422, "Invalid release ID")
    _path(f"releases/{release_id}/manifest.json")
    return tushare_store.manifest_at(ROOT, release_id)


def _artifact(manifest, path):
    if not re.fullmatch(OBJECT, path):
        raise HTTPException(422, "Invalid document object path")
    expected = manifest["files"].get(path)
    if not expected:
        raise HTTPException(404, "Object is not in this release")
    raw = _path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if (
        len(raw) != expected["bytes"]
        or sha != expected["sha256"]
        or sha != Path(path).stem
    ):
        raise HTTPException(409, "Document object checksum mismatch")
    return raw


def _documents(manifest):
    reference = manifest.get("documents")
    if not reference:
        return {"files": [], "mappings": [], "status": "not_registered"}
    path = reference["path"]
    if not re.fullmatch(r"documents/[a-f0-9]{64}\.json", path):
        raise HTTPException(409, "Invalid document inventory path")
    return json.loads(_artifact(manifest, path))


def _response(value):
    # Same lossless date/decimal/binary serialization as the offline JSONL store.
    encoded = json.loads(
        json.dumps(value, default=tushare_store._json_default, allow_nan=False)
    )
    return JSONResponse(
        encoded,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/current")
def current():
    """Discover a release; queries never implicitly follow this pointer."""
    with _errors():
        pointer = json.loads(_path("CURRENT.json").read_bytes())
        release_id = pointer["release_id"]
        _manifest(release_id)
        if pointer.get("manifest_sha256") != release_id.removeprefix("data-"):
            raise HTTPException(409, "CURRENT checksum mismatch")
        return {"release_id": release_id, "upstream_calls": 0}


@router.get("/datasets")
def datasets(release_id: str = Query(pattern=RELEASE)):
    with _errors():
        manifest = _manifest(release_id)
        grouped = {}
        for item in manifest["datasets"]:
            entry = grouped.setdefault(
                item["api_name"],
                {
                    "api_name": item["api_name"],
                    "partitions": 0,
                    "bytes": 0,
                },
            )
            entry["partitions"] += 1
            entry["bytes"] += manifest["files"][item["path"]]["bytes"]
        return {
            "release_id": release_id,
            "datasets": list(grouped.values()),
            "history_complete": manifest.get("history_complete") is True,
            "historical_versions_complete": manifest.get("historical_versions_complete")
            is True,
            "coverage": manifest.get("coverage_by_api", []),
            "upstream_calls": 0,
        }


@router.get("/datasets/{api_name}/schema")
def schema(api_name: str, release_id: str = Query(pattern=RELEASE)):
    with _errors():
        _manifest(release_id)
        return tushare_store.dataset_schema(ROOT, release_id, api_name)


@router.post("/query")
def query(body: DatasetQuery):
    with _errors():
        _manifest(body.release_id)
        table = tushare_store.read_dataset(ROOT, **body.model_dump())
        metadata = json.loads(table.schema.metadata[b"tushare"])
        return _response(
            {
                "metadata": metadata,
                "rows": table.to_pylist(),
                "returned_rows": table.num_rows,
                "limit": body.limit,
            }
        )


@router.get("/documents")
def documents(
    release_id: str = Query(pattern=RELEASE),
    view: Literal["mappings", "files"] = "mappings",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=2000),
):
    """Page frozen document metadata, including parse/download failure states."""
    with _errors():
        inventory = _documents(_manifest(release_id))
        items = inventory.get(view, [])
        stop = min(len(items), offset + limit)
        return _response(
            {
                "release_id": release_id,
                "view": view,
                "items": items[offset:stop],
                "total": len(items),
                "next_offset": stop if stop < len(items) else None,
                "status": inventory.get("status", "registered"),
                "counts": inventory.get("counts", []),
                "upstream_calls": 0,
            }
        )


@router.get("/documents/text")
def document_text(
    release_id: str = Query(pattern=RELEASE),
    path: str = Query(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=20),
    char_offset: int = Query(0, ge=0),
    max_chars: int = Query(20000, ge=1, le=100000),
):
    """Read inert HTML source or extracted pages, with explicit truncation cursors.

    char_offset applies to each selected page; use page_size=1 to continue one
    long page. Original PDFs stay evidence files, never synthesized as text.
    """
    with _errors():
        manifest = _manifest(release_id)
        raw = _artifact(manifest, path)
        if re.fullmatch(r"attachments/[a-f0-9]{64}\.html", path):
            pages = [{"page_number": 1, "text": raw.decode("utf-8")}]
            status = "html_source"
        elif re.fullmatch(r"extracted/[a-f0-9]{64}\.json", path):
            parsed = json.loads(raw)
            pages = parsed.get("pages", [])
            status = parsed.get("parse_status", "unknown")
        else:
            raise HTTPException(415, "Text requires extracted JSON or HTML source")
        selected = []
        for item in pages[page - 1 : page - 1 + page_size]:
            text = item["text"]
            end = min(len(text), char_offset + max_chars)
            selected.append(
                {
                    "page_number": item["page_number"],
                    "text": text[char_offset:end],
                    "total_chars": len(text),
                    "next_char_offset": end if end < len(text) else None,
                }
            )
        next_page = page + page_size
        return _response(
            {
                "release_id": release_id,
                "path": path,
                "sha256": manifest["files"][path]["sha256"],
                "parse_status": status,
                "pages": selected,
                "page_count": len(pages),
                "char_offset": char_offset,
                "next_page": next_page if next_page <= len(pages) else None,
                "upstream_calls": 0,
            }
        )
