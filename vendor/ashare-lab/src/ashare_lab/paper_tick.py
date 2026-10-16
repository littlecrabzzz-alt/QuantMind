"""Consume sole-source paper-readiness v1; never calculate another QA verdict."""
from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from . import paper_runtime as runtime
from .paper_inputs import prepare_release
from .paper_assets import require_columns

ASSET_ACCOUNTS = runtime.ACCOUNTS[3:]
ASSET_POINTER = "ashare-input-supplements/CURRENT.json"
ASSET_IDENTITY_FIELDS = ("path", "version", "manifest_path", "manifest_sha256")


class PendingReadiness(ValueError):
    """The authority has not published matching ready identities yet."""


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise PendingReadiness(f"Source readiness input unavailable: {path}: {exc}") from exc


def _relative(root, value, label, *, asset=False):
    if not value or Path(value).is_absolute():
        raise PendingReadiness(f"{label} must be a nonempty managed relative path")
    root = Path(root).resolve()
    target = (root / value).resolve()
    if not target.is_relative_to(root):
        raise PendingReadiness(f"{label} escapes its managed root")
    if asset and target.relative_to(root).parts[:1] not in (
            ("ashare-takeover",), ("ashare-input-supplements",)):
        raise PendingReadiness(f"{label} must stay in read-only archive/supplement subdirectories")
    return target


def _release(entry, archive_root, pointer_name, *, fundamental=False):
    mode = entry.get("mode") if fundamental else "managed"
    if mode not in ("managed", "pinned"):
        raise PendingReadiness("Fundamental mode must be managed or pinned")
    manifest = _relative(archive_root, entry["manifest_path"], "release manifest")
    if mode == "pinned":
        if not (entry.get("release_id") or entry.get("data_id")):
            raise PendingReadiness("Pinned PIT requires a release_id or data_id")
        if entry.get("pointer_path") is not None or not entry.get("as_of") or not entry.get("lag_note"):
            raise PendingReadiness("Pinned PIT requires null pointer_path, as_of and lag_note")
    else:
        if not entry.get("release_id") or manifest.parent.name != entry["release_id"]:
            raise PendingReadiness("QA immutable manifest release_id mismatch")
        pointer_path = _relative(archive_root, entry["pointer_path"], "release pointer")
        configured = _relative(archive_root, pointer_name, "configured release pointer")
        if pointer_path != configured:
            raise PendingReadiness("QA pointer differs from the configured sole-source pointer")
        pointer = _json(pointer_path)
        for field in ("release_id", "manifest_sha256"):
            if pointer.get(field) != entry.get(field):
                raise PendingReadiness(f"QA awaits {pointer_path.name}: {field} differs")
        if manifest != pointer_path.parent / "releases" / entry["release_id"] / "manifest.json":
            raise PendingReadiness("Manifest is not the immutable release named by its managed pointer")
    if runtime.file_hash(manifest) != entry["manifest_sha256"]:
        raise PendingReadiness(f"Immutable source manifest hash mismatch: {manifest}")
    return manifest


def _asset_bundle(qa, artifact_root):
    """Bind the QA verdict to the sole published bundle, without redoing QA."""
    bound = qa.get("asset_bundle")
    if not isinstance(bound, dict) or bound.get("pointer_path") != ASSET_POINTER:
        raise PendingReadiness("QA has not bound the canonical asset CURRENT/bundle identity")
    pointer_path = _relative(artifact_root, ASSET_POINTER, "asset bundle pointer", asset=True)
    pointer = _json(pointer_path)
    fields = ("schema_version", "data_identity", "bundle_path", "bundle_sha256")
    if (not isinstance(pointer, dict) or pointer.get("schema_version") != 1 or
            bound.get("schema_version") != 1):
        raise PendingReadiness("Unsupported canonical asset pointer schema_version")
    for field in fields:
        if pointer.get(field) != bound.get(field):
            raise PendingReadiness(f"QA awaits canonical asset CURRENT: {field} differs")
    identity = pointer.get("data_identity")
    if (not isinstance(identity, str) or len(identity) != 64 or
            any(c not in "0123456789abcdef" for c in identity)):
        raise PendingReadiness("Canonical asset pointer lacks a valid data_identity")
    bundle = _relative(artifact_root, pointer.get("bundle_path"), "asset bundle", asset=True)
    if bundle != pointer_path.parent / f"assets-{identity}" / "bundle.json":
        raise PendingReadiness("Asset bundle is not the immutable bundle named by CURRENT")
    try:
        actual_hash = runtime.file_hash(bundle)
    except OSError as exc:
        raise PendingReadiness(f"Canonical asset bundle unavailable: {bundle}: {exc}") from exc
    if actual_hash != pointer.get("bundle_sha256"):
        raise PendingReadiness("Canonical asset bundle byte hash mismatch")
    payload = _json(bundle)
    evidence = payload.get("evidence") if isinstance(payload, dict) else None
    if (not isinstance(evidence, dict) or payload.get("data_identity") != identity or
            evidence.get("schema_version") != 1 or evidence.get("data_identity") != identity):
        raise PendingReadiness("Canonical asset bundle/evidence identity mismatch")
    inputs = evidence.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(ASSET_ACCOUNTS):
        raise PendingReadiness("Canonical bundle must name exactly the five asset account inputs")
    return {"pointer_path": ASSET_POINTER, **{field: pointer[field] for field in fields}}, inputs


def _selection(qa, archive_root, artifact_root, market_pointer, fundamental_pointer, names):
    if qa.get("schema_version") != 1:
        raise PendingReadiness("Unsupported sole-source paper-readiness schema_version")
    if qa.get("state") != "ready":
        raise PendingReadiness("; ".join(qa.get("reasons") or [f"source state={qa.get('state')}"]))
    checked = datetime.fromisoformat(qa["checked_at"].replace("Z", "+00:00"))
    if checked.tzinfo is None or checked.utcoffset().total_seconds() != 0:
        raise PendingReadiness("QA checked_at must be aware UTC")
    market = _release(qa["market"], archive_root, market_pointer)
    fundamental = _release(qa["fundamentals"], archive_root, fundamental_pointer, fundamental=True)
    calendar = qa["calendar"]
    calendar_path = _relative(archive_root, calendar["path"], "real exchange calendar")
    if runtime.file_hash(calendar_path) != calendar["sha256"]:
        raise PendingReadiness("QA real-calendar identity mismatch")
    if not calendar.get("confirmed_next_session"):
        raise PendingReadiness("QA has not confirmed the next real exchange session")
    assets = qa.get("asset_inputs", {})
    if set(assets) != set(ASSET_ACCOUNTS):
        raise PendingReadiness("asset_inputs must contain exactly the five authorized asset account keys")
    if set(qa.get("accounts", {})) != set(runtime.ACCOUNTS):
        raise PendingReadiness("accounts must contain exactly the eight authorized identities")
    asset_bundle, bundle_inputs = _asset_bundle(qa, artifact_root)
    accounts, ready, asset_paths = {}, [], {}
    for name in runtime.ACCOUNTS:
        verdict = qa["accounts"][name]
        if verdict.get("state") not in ("ready", "pending", "blocked"):
            raise PendingReadiness(f"Sole-source account readiness missing for {name}")
        if name in ASSET_ACCOUNTS:
            asset = assets[name]
            entry = bundle_inputs[name]
            if (not isinstance(entry, dict) or
                    any(asset.get(field) != entry.get(field) for field in ASSET_IDENTITY_FIELDS)):
                raise PendingReadiness(f"QA {name} input identity differs from canonical asset bundle")
            if asset.get("state") != verdict["state"]:
                raise PendingReadiness(f"Account/asset readiness disagrees for {name}")
            path = (_relative(artifact_root, asset["path"], f"{name} input", asset=True)
                    if asset.get("path") is not None else None)
            manifest = (_relative(artifact_root, asset["manifest_path"], f"{name} manifest", asset=True)
                        if asset.get("manifest_path") is not None else None)
            if path is not None and manifest is not None and asset.get("manifest_sha256"):
                valid = (path.exists() and manifest.is_file() and asset.get("version") and
                         runtime.file_hash(manifest) == asset["manifest_sha256"])
                if valid:
                    asset_paths[name] = path
                elif verdict["state"] == "ready":
                    raise PendingReadiness(f"{name} immutable asset manifest mismatch")
            elif verdict["state"] == "ready":
                raise PendingReadiness(f"{name} ready without immutable asset paths")
        if name in names:
            accounts[name] = {"state": verdict["state"], "reasons": verdict.get("reasons", [])}
            if name == "i7_turn_of_month" and "calendar_context" in verdict:
                accounts[name]["calendar_context"] = verdict["calendar_context"]
            if verdict["state"] == "ready":
                ready.append(name)
    if set(names) - set(runtime.ACCOUNTS):
        raise ValueError("Unauthorized account requested")
    # checked_at, temporary QA file hash, verdicts/reasons are audit metadata,
    # never a prepared-data version. Identical data reuses the expensive panel.
    identity = {"market": {key: qa["market"].get(key) for key in
                    ("release_id", "manifest_sha256", "mode", "pointer_path")},
                "fundamentals": {key: qa["fundamentals"].get(key) for key in
                    ("release_id", "data_id", "manifest_sha256", "mode", "pointer_path", "as_of")},
                "usable_date": qa["usable_date"],
                "calendar": {key: calendar[key] for key in ("path", "sha256", "confirmed_next_session")},
                "asset_bundle": asset_bundle,
                "asset_inputs": {name: {key: assets[name].get(key) for key in
                    ASSET_IDENTITY_FIELDS} for name in ASSET_ACCOUNTS},
                "account_rules_sha256": runtime.digest(runtime.json_bytes(runtime.frozen_specs()))}
    return market, fundamental, calendar_path, tuple(ready), accounts, identity, asset_paths


def due_status(calendar_path, now=None, *, usable_date=None):
    """Allow a real closed source session, including delayed/weekend catch-up."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    result = {"wall_clock_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
              "wall_clock_shanghai": local.isoformat(), "due": None,
              "due_reason": "real_calendar_does_not_cover_shanghai_date",
              "observation_date": str(local.date())}
    session = pd.Timestamp(usable_date).date() if usable_date is not None else local.date()
    result.update(usable_session_date=str(session), catch_up=session < local.date())
    if usable_date is not None:
        result["due_reason"] = "real_calendar_does_not_cover_usable_session"
    if session > local.date():
        result.update(due=False, due_reason="usable_session_is_future")
        return result
    frame = pd.read_parquet(calendar_path)
    column = "cal_date" if "cal_date" in frame else "date"
    require_columns(frame, ("exchange", "is_open", column), "QA trade_cal")
    date = pd.to_datetime(frame[column].astype(str), format="mixed")
    rows = frame.loc[frame.exchange.eq("SSE") & date.eq(pd.Timestamp(session))]
    opened = pd.to_numeric(rows.is_open, errors="raise").drop_duplicates()
    if len(opened) != 1 or opened.iloc[0] not in (0, 1):
        return result
    if opened.iloc[0] == 0:
        result.update(due=False, due_reason=("usable_date_not_exchange_session" if usable_date is not None
                                            else "shanghai_exchange_closed"))
    elif session < local.date():
        result.update(due=True, due_reason="closed_session_catch_up")
    elif local.hour < 18:
        result.update(due=False, due_reason="before_shanghai_18_settlement_window")
    else:
        result.update(due=True, due_reason="shanghai_session_after_18")
    return result


def tick(readiness_path, archive_root, artifact_root, market_pointer, fundamental_pointer,
         prepared_root, ledger_root, preserved_source, bindings, names=runtime.ACCOUNTS):
    """Resolve the QA's immutable version and invoke the sole owner-bound ledger."""
    root = Path(ledger_root)
    now = datetime.now(timezone.utc)
    report = {"owner": {"user_id": str(bindings["user_id"]), "tenant_id": str(bindings["tenant_id"])},
              "checked_at": now.isoformat().replace("+00:00", "Z"), "state": "pending", "due": None,
              "wall_clock_utc": now.isoformat().replace("+00:00", "Z"),
              "wall_clock_shanghai": now.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
              "due_reason": "source_identity_not_ready",
              "readiness_path": str(Path(readiness_path)), "accounts": {}}

    def publish():
        with runtime.ledger_lock(root):
            bound = root / "bindings.json"
            if bound.exists() and json.loads(bound.read_text()) != bindings:
                raise runtime.LedgerMismatch("Tick root belongs to another owner/registered version")
            contents = {root / "tick.json": runtime.json_bytes(report)}
            if not bound.exists():
                contents[bound] = runtime.json_bytes(bindings)
            runtime._publish(contents)
        return report

    try:
        qa = _json(readiness_path)
        report["source_state"] = qa.get("state")
        selected = _selection(qa, archive_root, artifact_root, market_pointer, fundamental_pointer, names)
        market, fundamental, calendar, ready, accounts, identity, asset_paths = selected
        source_checked = datetime.fromisoformat(qa["checked_at"].replace("Z", "+00:00"))
        report.update(accounts=accounts, usable_date=qa["usable_date"],
                      source_checked_at=source_checked.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                      source_identity=identity, per_api_cutoffs=qa["per_api_cutoffs"],
                      fundamentals=qa["fundamentals"], reasons=qa.get("reasons", []))
        report.update(due_status(calendar, now, usable_date=qa["usable_date"]))
        if not ready:
            report["reasons"] = ["No requested account has a sole-source ready verdict"]
            if all(item["state"] == "blocked" for item in accounts.values()):
                report["state"] = "blocked"
            return publish()
        if report["due"] is not True:
            report["state"] = "not_due" if report["due"] is False else "pending"
            report["reasons"] = [report["due_reason"]]
            return publish()
        token = runtime.digest(runtime.json_bytes(identity))
        prepared = Path(prepared_root) / token
        manifest = prepare_release(market, fundamental, prepared, qa["usable_date"],
            calendar_path=calendar, calendar_sha256=qa["calendar"]["sha256"],
            readiness_identity=identity, account_assets=asset_paths)
        # If publishing advances during derivation, retain that immutable prepared
        # version but append nothing until QA matches the managed pointers again.
        again = _selection(_json(readiness_path), archive_root, artifact_root,
                           market_pointer, fundamental_pointer, names)
        if again[5] != identity or again[3] != ready:
            raise PendingReadiness("Sole-source identity/account verdict changed during preparation")
        reports = runtime.update(root, preserved_source, manifest, ready, mode="daily", bindings=bindings)
        report["accounts"].update({name: {**result, "source_state": "ready"}
                                   for name, result in reports.items()})
        report.update(state="applied", prepared_manifest=str(manifest), prepared_identity=token,
                      new_sessions=sum(row.get("new_sessions", 0) for row in reports.values()))
        if any(row["state"] == "blocked" for row in reports.values()):
            report["state"] = "blocked"
        elif any(row["state"] in ("pending", "blocked") for row in report["accounts"].values()):
            report["state"] = "partial"
        elif report["new_sessions"] == 0:
            report["state"] = "up_to_date"
        return publish()
    except PendingReadiness as exc:
        state = "blocked" if report.get("source_state") == "blocked" else "pending"
        report.update(state=state, reasons=[str(exc)])
        report["accounts"] = {name: {"state": state, "reasons": [str(exc)]} for name in names}
        return publish()
    except (OSError, KeyError, ValueError, duckdb.Error, runtime.LedgerMismatch) as exc:
        report.update(state="blocked", reasons=[str(exc)])
        return publish()
