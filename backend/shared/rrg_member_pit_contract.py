"""Validate claimed CITIC membership evidence and reconcile source intervals."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"Invalid {label}")
    return value


def _date8(value, label, *, optional=False):
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"Invalid {label}")
    datetime.strptime(value, "%Y%m%d")
    return value


def _instant(value, label):
    if not isinstance(value, str):
        raise ValueError(f"Invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Invalid {label}")
    return parsed.astimezone(timezone.utc).isoformat()


def _source_file(base: Path, source):
    if not isinstance(source, dict):
        raise ValueError("Invalid evidence source")
    relative = source.get("path")
    expected_bytes = source.get("bytes")
    expected_sha = source.get("sha256")
    url = source.get("url")
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
        or not isinstance(expected_sha, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha)
    ):
        raise ValueError("Invalid evidence source")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (
        not parsed
        or parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid evidence source URL")
    path = base / relative
    resolved_base = base.resolve()
    if (
        path.is_symlink()
        or not path.is_file()
        or resolved_base not in path.resolve().parents
        or path.stat().st_size != expected_bytes
        or sha256(path) != expected_sha
    ):
        raise ValueError("Evidence source bytes or SHA256 mismatch")
    return {
        "path": relative,
        "bytes": expected_bytes,
        "sha256": expected_sha,
        "url": url,
    }


def load_evidence_manifest(path):
    """Load a claimed revision chain whose local source bytes are verified."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Evidence manifest is missing or invalid")
    path = path.resolve()
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Evidence manifest is not valid UTF-8 JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("provider") != "CITIC"
        or payload.get("taxonomy") != "CITIC_L1"
        or payload.get("revision_semantics") != "full_replacement"
        or not isinstance(payload.get("announcements"), list)
    ):
        raise ValueError("Unsupported membership evidence contract")

    revisions = {}
    for item in payload["announcements"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid announcement revision")
        announcement_id = _text(item.get("announcement_id"), "announcement_id")
        revision = item.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("Invalid announcement revision")
        key = (announcement_id, revision)
        if key in revisions:
            raise ValueError("Duplicate announcement revision")
        status = item.get("status")
        changes = item.get("changes")
        if status not in ("published", "withdrawn") or not isinstance(changes, list):
            raise ValueError("Invalid announcement status or changes")
        if status == "withdrawn" and changes:
            raise ValueError("Withdrawn revisions cannot retain changes")
        published_at = _instant(item.get("published_at"), "published_at")
        taxonomy_version = _text(item.get("taxonomy_version"), "taxonomy_version")
        source = _source_file(path.parent, item.get("source"))
        normalized_changes = []
        seen = set()
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError("Invalid membership change")
            action = change.get("action")
            if action not in ("add", "remove"):
                raise ValueError("Invalid membership action")
            normalized = {
                "source_sector_code": _text(
                    change.get("source_sector_code"), "source_sector_code"
                ),
                "source_symbol": _text(change.get("source_symbol"), "source_symbol"),
                "effective_date": _date8(
                    change.get("effective_date"), "effective_date"
                ),
                "action": action,
            }
            identity = (
                normalized["source_sector_code"],
                normalized["source_symbol"],
                normalized["effective_date"],
                normalized["action"],
            )
            if identity in seen:
                raise ValueError("Duplicate membership change")
            seen.add(identity)
            normalized_changes.append(normalized)
        revisions[key] = {
            "announcement_id": announcement_id,
            "revision": revision,
            "supersedes_revision": item.get("supersedes_revision"),
            "status": status,
            "published_at": published_at,
            "taxonomy_version": taxonomy_version,
            "source": source,
            "changes": normalized_changes,
        }

    active = []
    for announcement_id in sorted({key[0] for key in revisions}):
        chain = sorted(
            (item for key, item in revisions.items() if key[0] == announcement_id),
            key=lambda item: item["revision"],
        )
        if chain[0]["revision"] != 1:
            raise ValueError("Broken announcement revision chain")
        for position, item in enumerate(chain):
            previous = chain[position - 1] if position else None
            expected = previous["revision"] if previous else None
            if item["supersedes_revision"] != expected:
                raise ValueError("Broken announcement revision chain")
            if previous and item["published_at"] <= previous["published_at"]:
                raise ValueError("Announcement revisions are not chronological")
        if chain[-1]["status"] == "published":
            active.append(chain[-1])

    content_verified_sources = [
        {
            key: item[key]
            for key in (
                "announcement_id",
                "revision",
                "status",
                "published_at",
                "taxonomy_version",
                "source",
            )
        }
        for item in sorted(
            revisions.values(),
            key=lambda item: (item["announcement_id"], item["revision"]),
        )
    ]

    events = {}
    for announcement in active:
        for change in announcement["changes"]:
            key = (
                change["source_sector_code"],
                change["source_symbol"],
                change["effective_date"],
            )
            if key in events:
                raise ValueError("Conflicting membership evidence")
            events[key] = {
                **change,
                **{
                    k: announcement[k]
                    for k in (
                        "announcement_id",
                        "revision",
                        "published_at",
                        "taxonomy_version",
                        "source",
                    )
                },
            }
    return {
        "locator": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "announcement_revisions": len(revisions),
        "active_announcements": len(active),
        "withdrawn_announcements": len({key[0] for key in revisions}) - len(active),
        "content_verified_sources": content_verified_sources,
        "events": events,
    }


def reconcile_members(source_rows, evidence):
    """Match claimed entry/exit events to retained CITIC source intervals."""
    rows = []
    source_keys = set()
    interval_groups = {}
    missing_source_identity_rows = 0
    for source in source_rows:
        source_sector = source.get("source_l1_code")
        source_symbol = source.get("source_ts_code")
        if source_sector not in (None, ""):
            source_sector = _text(source_sector, "source_l1_code")
        if source_symbol not in (None, ""):
            source_symbol = _text(source_symbol, "source_ts_code")
        start = _date8(source.get("in_date"), "source in_date")
        end = _date8(source.get("out_date"), "source out_date", optional=True)
        if end and end < start:
            raise ValueError("Source membership interval is reversed")
        if (
            not source.get("l1_code")
            or not source.get("ts_code")
            or not re.fullmatch(r"[a-f0-9]{64}", str(source.get("_row_identity", "")))
        ):
            raise ValueError("Source membership identity is missing")
        if not source_sector or not source_symbol:
            missing_source_identity_rows += 1
            source_sector = source_sector or ""
            source_symbol = source_symbol or ""
        entry_key = (source_sector, source_symbol, start)
        exit_key = (source_sector, source_symbol, end) if end else None
        entry = evidence["events"].get(entry_key)
        exit_event = evidence["events"].get(exit_key) if exit_key else None
        if entry and entry["action"] != "add":
            raise ValueError("Entry date has remove evidence")
        if exit_event and exit_event["action"] != "remove":
            raise ValueError("Exit date has add evidence")
        source_keys.add((*entry_key, "add"))
        if exit_key:
            source_keys.add((*exit_key, "remove"))
        interval_groups.setdefault(source_symbol, []).append(
            {
                "source_sector_code": source_sector,
                "effective_from": start,
                "effective_to": end,
            }
        )
        content_reconciled = bool(entry and (not end or exit_event))
        rows.append(
            {
                "source_row_identity": source.get("_row_identity"),
                "SectorCode": source.get("l1_code"),
                "Symbol": source.get("ts_code"),
                "source_sector_code": source_sector or None,
                "source_symbol": source_symbol or None,
                "effective_from": start,
                "effective_to": end,
                "known_at": entry["published_at"] if entry else None,
                "exit_known_at": exit_event["published_at"] if exit_event else None,
                "taxonomy_version": entry["taxonomy_version"] if entry else None,
                "entry_announcement_id": entry["announcement_id"] if entry else None,
                "entry_revision": entry["revision"] if entry else None,
                "entry_source_url": entry["source"]["url"] if entry else None,
                "entry_source_path": entry["source"]["path"] if entry else None,
                "entry_source_sha256": entry["source"]["sha256"] if entry else None,
                "exit_announcement_id": (
                    exit_event["announcement_id"] if exit_event else None
                ),
                "exit_revision": exit_event["revision"] if exit_event else None,
                "exit_source_url": exit_event["source"]["url"] if exit_event else None,
                "exit_source_path": exit_event["source"]["path"]
                if exit_event
                else None,
                "exit_source_sha256": (
                    exit_event["source"]["sha256"] if exit_event else None
                ),
                "entry_claimed_evidence_matched": entry is not None,
                "exit_evidence_required": end is not None,
                "exit_claimed_evidence_matched": exit_event is not None,
                "source_authority_verified": False,
                "content_reconciled": content_reconciled,
                "historical_known_at_verified": False,
            }
        )

    conflicts = []
    for symbol, intervals in sorted(interval_groups.items()):
        ordered = sorted(
            intervals,
            key=lambda interval: (
                interval["effective_from"],
                interval["source_sector_code"],
            ),
        )
        previous_end = None
        previous = None
        for position, interval in enumerate(ordered):
            start = interval["effective_from"]
            end = interval["effective_to"]
            if position and (previous_end is None or start < previous_end):
                conflicts.append(
                    {
                        "source_symbol": symbol,
                        "left_source_sector_code": previous["source_sector_code"],
                        "left_effective_from": previous["effective_from"],
                        "left_effective_to": previous["effective_to"],
                        "right_source_sector_code": interval["source_sector_code"],
                        "right_effective_from": start,
                        "right_effective_to": end,
                    }
                )
                break
            previous_end = end
            previous = interval

    unmatched = []
    for event in evidence["events"].values():
        key = (
            event["source_sector_code"],
            event["source_symbol"],
            event["effective_date"],
            event["action"],
        )
        if key not in source_keys:
            unmatched.append(
                {
                    "announcement_id": event["announcement_id"],
                    "revision": event["revision"],
                    **{
                        field: event[field]
                        for field in (
                            "source_sector_code",
                            "source_symbol",
                            "effective_date",
                            "action",
                        )
                    },
                }
            )

    rows.sort(
        key=lambda row: (
            row["SectorCode"] or "",
            row["Symbol"] or "",
            row["effective_from"],
        )
    )
    content_reconciled_rows = sum(row["content_reconciled"] for row in rows)
    content_complete_for_fixed_source = (
        bool(rows)
        and content_reconciled_rows == len(rows)
        and not unmatched
        and not conflicts
        and not missing_source_identity_rows
    )
    return rows, {
        "source_rows": len(rows),
        "content_reconciled_rows": content_reconciled_rows,
        "entry_content_matched_rows": sum(
            row["entry_claimed_evidence_matched"] for row in rows
        ),
        "exit_required_rows": sum(row["exit_evidence_required"] for row in rows),
        "exit_content_matched_rows": sum(
            row["exit_claimed_evidence_matched"] for row in rows
        ),
        "source_identity_missing_rows": missing_source_identity_rows,
        "unmatched_events": unmatched,
        "source_interval_conflicts": conflicts,
        "source_authority_verified": False,
        "historical_known_at_verified_rows": 0,
        "content_complete_for_fixed_source": content_complete_for_fixed_source,
    }
