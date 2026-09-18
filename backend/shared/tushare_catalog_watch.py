"""Read-only drift detection for the public Tushare documentation sidebar."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone

import httpx

from backend.shared.tushare_intake import DOC_ROOT, DocParser


def _utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _interval(config):
    value = config.get("catalog_watch_interval_seconds", 86400)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 3600 <= value <= 604800
    ):
        raise ValueError("catalog_watch_interval_seconds must be 3600..604800")
    return float(value)


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def assess_catalog_index(body, baseline, checked_epoch):
    """Compare public sidebar identities without changing the reviewed catalog."""
    if not isinstance(body, bytes):
        raise ValueError("Catalog index body must be bytes")
    parser = DocParser()
    parser.feed(body.decode("utf-8"))
    if not parser.links:
        raise ValueError("Official catalogue links were not found")
    entries = baseline.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Invalid catalog baseline")
    saved = {}
    for entry in entries:
        doc_id, title = entry.get("doc_id"), entry.get("title")
        if not isinstance(doc_id, str) or not isinstance(title, str):
            raise ValueError("Invalid catalog baseline entry")
        saved[doc_id] = title
    current = dict(parser.links)
    added = sorted(set(current) - set(saved), key=int)
    removed = sorted(set(saved) - set(current), key=int)
    retitled = [
        {"doc_id": doc_id, "saved_title": saved[doc_id], "current_title": current[doc_id]}
        for doc_id in sorted(set(saved) & set(current), key=int)
        if saved[doc_id] != current[doc_id]
    ]
    changed = bool(added or removed or retitled)
    interval_hash = hashlib.sha256(body).hexdigest()
    return {
        "schema": "quantmind.tushare.catalog-watch.v1",
        "checked_at": _utc(checked_epoch),
        "checked_epoch": checked_epoch,
        "status": "drift_detected" if changed else "current",
        "source": DOC_ROOT,
        "baseline_entry_count": len(saved),
        "current_entry_count": len(current),
        "baseline_index_sha256": baseline.get("index_sha256"),
        "current_index_sha256": interval_hash,
        "index_content_changed": baseline.get("index_sha256") != interval_hash,
        "added_doc_ids": added,
        "removed_doc_ids": removed,
        "retitled": retitled,
        "change_count": len(added) + len(removed) + len(retitled),
    }


def run_catalog_watch(root, config, *, catalog_path=None, fetch=None, now_epoch=None):
    """Check once per configured interval; all failures stay non-blocking and visible."""
    enabled = config.get("enable_catalog_watch", False)
    if not isinstance(enabled, bool):
        return {"status": "failed", "error_type": "ValueError"}
    if not enabled:
        return {"status": "disabled"}
    now_epoch = time.time() if now_epoch is None else now_epoch
    status_path = Path(root) / "catalog-watch-status.json"
    try:
        interval = _interval(config)
        previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        next_check = previous.get("next_check_epoch", 0)
        if isinstance(next_check, (int, float)) and now_epoch < next_check:
            return {
                "status": "deferred",
                "last_status": previous.get("status"),
                "last_checked_at": previous.get("checked_at"),
                "next_check_epoch": next_check,
            }
        if catalog_path is None:
            catalog_path = Path(__file__).resolve().parents[2] / "config/tushare-catalog.json"
        baseline = json.loads(Path(catalog_path).read_text())
        if fetch is None:
            with httpx.Client(trust_env=False, timeout=10, follow_redirects=False) as client:
                response = client.get(DOC_ROOT)
                response.raise_for_status()
                body = response.content
        else:
            body = fetch()
        report = assess_catalog_index(body, baseline, now_epoch)
        report["next_check_epoch"] = now_epoch + interval
    except Exception as exc:
        report = {
            "schema": "quantmind.tushare.catalog-watch.v1",
            "checked_at": _utc(now_epoch),
            "checked_epoch": now_epoch,
            "status": "failed",
            "error_type": type(exc).__name__,
            "next_check_epoch": now_epoch + 3600,
        }
    _atomic_json(status_path, report)
    return report
