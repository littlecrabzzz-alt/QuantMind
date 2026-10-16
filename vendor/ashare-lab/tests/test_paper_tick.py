"""Pure consumer tests: readiness comes from QA, never from a second classifier."""
import json
from pathlib import Path

import pandas as pd
import pytest

from ashare_lab import paper_runtime as runtime
from ashare_lab import paper_tick as tick


def publish_asset_bundle(qa, artifacts):
    inputs = {name: {field: qa["asset_inputs"][name].get(field) for field in
              ("path", "version", "manifest_path", "manifest_sha256")} for name in runtime.ACCOUNTS[3:]}
    identity = runtime.digest(runtime.json_bytes(inputs))
    bundle = artifacts / "ashare-input-supplements" / f"assets-{identity}" / "bundle.json"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_bytes(runtime.json_bytes({"data_identity": identity,
        "evidence": {"schema_version": 1, "data_identity": identity, "inputs": inputs}}))
    pointer = {"schema_version": 1, "data_identity": identity,
               "bundle_path": str(bundle.relative_to(artifacts)),
               "bundle_sha256": runtime.file_hash(bundle)}
    (artifacts / tick.ASSET_POINTER).write_bytes(runtime.json_bytes(pointer))
    qa["asset_bundle"] = {"pointer_path": tick.ASSET_POINTER, **pointer}
    return bundle


def fixture_qa(tmp_path):
    archive, artifacts = tmp_path / "archive", tmp_path / "output"
    archive.mkdir()
    artifacts.mkdir()
    entries = {}
    for role, pointer, release in (("market", "RESEARCH_CURRENT.json", "data-market"),
                                    ("fundamentals", "CURRENT.json", "data-full")):
        manifest = archive / "releases" / release / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"datasets": [], "fixture": role}))
        entry = {"pointer_path": pointer, "release_id": release,
                 "manifest_path": str(manifest.relative_to(archive)),
                 "manifest_sha256": runtime.file_hash(manifest)}
        (archive / pointer).write_text(json.dumps({"release_id": release,
                                                  "manifest_sha256": entry["manifest_sha256"]}))
        entries[role] = entry
    entries["fundamentals"]["mode"] = "managed"
    calendar = archive / "calendar.parquet"
    pd.DataFrame({"exchange": ["SSE", "SSE"], "cal_date": ["20261015", "20261016"],
                  "is_open": [1, 1]}).to_parquet(calendar)
    assets = {name: {"state": "blocked", "reasons": ["actual source field absent"],
              "path": None, "version": None, "manifest_path": None, "manifest_sha256": None}
              for name in runtime.ACCOUNTS[3:]}
    accounts = {name: {"state": "ready" if name in runtime.ORIGINAL else "blocked",
                       "reasons": [] if name in runtime.ORIGINAL else ["actual source field absent"]}
                for name in runtime.ACCOUNTS}
    qa = {"schema_version": 1, "state": "ready", "checked_at": "2026-10-16T11:00:00Z",
          "usable_date": "2026-10-15", "reasons": [], **entries,
          "calendar": {"path": "calendar.parquet", "sha256": runtime.file_hash(calendar),
                       "confirmed_next_session": "2026-10-16"},
          "per_api_cutoffs": {"daily": "2026-10-15", "index_weight": "2026-10-13"},
          "accounts": accounts, "asset_inputs": assets}
    publish_asset_bundle(qa, artifacts)
    readiness = tmp_path / "paper-readiness.json"
    readiness.write_text(json.dumps(qa))
    bindings = {"user_id": "10000001", "tenant_id": "default", "accounts": {}}
    return qa, readiness, archive, artifacts, bindings


def test_periodic_checked_at_refresh_reuses_prepared_identity(tmp_path, monkeypatch):
    qa, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    prepared_paths, calls = [], []
    def prepare(market, fundamental, directory, cutoff, **kwargs):
        prepared_paths.append(Path(directory))
        assert kwargs["calendar_path"] == archive / "calendar.parquet"
        assert kwargs["account_assets"] == {}
        return Path(directory) / "inputs.json"
    def update(root, source, manifest, names, **kwargs):
        calls.append((tuple(names), kwargs))
        return {name: {"state": "reconciled", "last_date": "2026-10-15", "new_sessions": 0}
                for name in names}
    monkeypatch.setattr(tick, "prepare_release", prepare)
    monkeypatch.setattr(runtime, "update", update)
    monkeypatch.setattr(tick, "due_status", lambda *args, **kwargs: {"due": True, "observation_date": qa["usable_date"]})
    kwargs = dict(readiness_path=readiness, archive_root=archive, artifact_root=artifacts,
        market_pointer="RESEARCH_CURRENT.json", fundamental_pointer="CURRENT.json",
        prepared_root=artifacts / "prepared", ledger_root=artifacts / "owner",
        preserved_source=artifacts / "preserved", bindings=bindings)
    first = tick.tick(**kwargs)
    qa["checked_at"] = "2026-10-16T11:15:00Z"
    qa["reasons"] = ["periodic audit, identical source bytes"]
    readiness.write_text(json.dumps(qa))
    second = tick.tick(**kwargs)
    assert first["state"] == second["state"] == "partial"
    assert prepared_paths[0] == prepared_paths[1]
    assert calls[0][0] == runtime.ORIGINAL
    assert calls[0][1]["mode"] == "daily"
    assert calls[0][1]["bindings"] == bindings
    view = runtime.snapshot(artifacts / "owner")
    assert view["scheduler"]["source_checked_at"] == qa["checked_at"]
    assert view["accounts"][3]["schedule"]["state"] == "blocked"
    assert not (artifacts / "owner" / "lowvol" / "nav.csv").exists()


def test_pending_or_advanced_pointer_never_touches_account_ledger(tmp_path, monkeypatch):
    qa, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("pending must not prepare or update account ledgers")
    monkeypatch.setattr(tick, "prepare_release", forbidden)
    monkeypatch.setattr(runtime, "update", forbidden)
    qa["state"] = "pending"
    qa["reasons"] = ["source calendar not ready"]
    readiness.write_text(json.dumps(qa))
    kwargs = dict(readiness_path=readiness, archive_root=archive, artifact_root=artifacts,
        market_pointer="RESEARCH_CURRENT.json", fundamental_pointer="CURRENT.json",
        prepared_root=artifacts / "prepared", ledger_root=artifacts / "owner",
        preserved_source=artifacts / "preserved", bindings=bindings)
    assert tick.tick(**kwargs)["state"] == "pending"
    qa["state"] = "ready"
    readiness.write_text(json.dumps(qa))
    (archive / "RESEARCH_CURRENT.json").write_text(json.dumps({"release_id": "new-release",
                                                              "manifest_sha256": "new-hash"}))
    report = tick.tick(**kwargs)
    assert report["state"] == "pending"
    assert "differs" in report["reasons"][0]
    assert not (artifacts / "owner" / "lowvol").exists()


def test_pinned_pit_and_two_root_path_boundaries(tmp_path):
    qa, _, archive, artifacts, _ = fixture_qa(tmp_path)
    qa["fundamentals"].update(mode="pinned", pointer_path=None, as_of="2026-10-13",
                               lag_note="Frozen source PIT version, explicitly lagging")
    (archive / "CURRENT.json").write_text(json.dumps({"release_id": "advanced", "manifest_sha256": "new"}))
    selected = tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)
    assert selected[3] == runtime.ORIGINAL
    qa["fundamentals"]["lag_note"] = "Audited again, same immutable PIT data"
    assert tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)[5] == selected[5]
    qa["calendar"]["path"] = "/Users/private/calendar.parquet"
    with pytest.raises(tick.PendingReadiness, match="relative path"):
        tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)
    with pytest.raises(tick.PendingReadiness, match="escapes"):
        tick._relative(artifacts, "../outside", "asset")
    with pytest.raises(tick.PendingReadiness, match="read-only"):
        tick._relative(artifacts, "ashare-paper/owner/nav.csv", "asset", asset=True)


def test_pointer_advance_during_preparation_keeps_old_ledgers(tmp_path, monkeypatch):
    qa, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    def prepare(*args, **kwargs):
        (archive / "RESEARCH_CURRENT.json").write_text(json.dumps({"release_id": "new",
                                                                 "manifest_sha256": "new"}))
        return artifacts / "prepared/inputs.json"
    monkeypatch.setattr(tick, "prepare_release", prepare)
    monkeypatch.setattr(runtime, "update", lambda *args, **kwargs: pytest.fail("superseded QA cannot append"))
    monkeypatch.setattr(tick, "due_status", lambda *args, **kwargs: {"due": True, "observation_date": qa["usable_date"]})
    report = tick.tick(readiness, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json",
                       artifacts / "prepared", artifacts / "owner", artifacts / "preserved", bindings)
    assert report["state"] == "pending"
    assert not (artifacts / "owner/lowvol").exists()


def test_asset_account_keys_and_stable_ready_transition(tmp_path):
    qa, _, archive, artifacts, _ = fixture_qa(tmp_path)
    asset = artifacts / "ashare-input-supplements" / "etf.parquet"
    asset.parent.mkdir(exist_ok=True)
    pd.DataFrame({"date": ["2026-10-15"], "code": ["510300.SH"], "close": [4.]}).to_parquet(asset)
    manifest = asset.parent / "manifest.json"
    manifest.write_text(json.dumps({"files": {asset.name: runtime.file_hash(asset)}}))
    entry = {"state": "pending", "reasons": ["QA review pending"],
             "path": str(asset.relative_to(artifacts)), "version": "immutable-etf-v1",
             "manifest_path": str(manifest.relative_to(artifacts)),
             "manifest_sha256": runtime.file_hash(manifest)}
    qa["asset_inputs"]["i7_turn_of_month"] = entry
    qa["accounts"]["i7_turn_of_month"] = {"state": "pending", "reasons": entry["reasons"]}
    publish_asset_bundle(qa, artifacts)
    before = tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)
    entry.update(state="ready", reasons=[])
    qa["accounts"]["i7_turn_of_month"] = {"state": "ready", "reasons": []}
    after = tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)
    assert before[5] == after[5]
    assert before[6] == after[6] == {"i7_turn_of_month": asset}
    assert "i7_turn_of_month" not in before[3] and "i7_turn_of_month" in after[3]
    qa["asset_inputs"]["cb"] = qa["asset_inputs"].pop("cb_double_low")
    with pytest.raises(tick.PendingReadiness, match="five authorized"):
        tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)


def test_pending_i7_month_context_is_exposed_without_blocking_other_ready_accounts(tmp_path):
    qa, _, archive, artifacts, _ = fixture_qa(tmp_path)
    context = {"exchange": "SSE", "replay_start": "2026-10-14", "usable_date": "2026-10-15",
        "calendar_through": "2026-10-16", "required_month_end": "2026-10-31",
        "next_month_first_session": None, "next_two_sessions": ["2026-10-16"],
        "complete": False, "state": "pending", "reason": "Incomplete real month context",
        "calendar_sha256": qa["calendar"]["sha256"]}
    qa["accounts"]["i7_turn_of_month"].update(state="pending", calendar_context=context)
    qa["asset_inputs"]["i7_turn_of_month"]["state"] = "pending"
    selected = tick._selection(qa, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json", runtime.ACCOUNTS)
    assert selected[3] == runtime.ORIGINAL
    assert selected[4]["i7_turn_of_month"]["state"] == "pending"
    assert selected[4]["i7_turn_of_month"]["calendar_context"] == context


def test_shanghai_due_is_independent_of_host_timezone_and_never_guesses_weekdays(tmp_path):
    from datetime import datetime, timedelta, timezone
    calendar = tmp_path / "calendar.parquet"
    pd.DataFrame({"exchange": ["SSE"] * 3, "cal_date": ["20261015", "20261016", "20261017"],
                  "is_open": [1, 1, 0]}).to_parquet(calendar)
    pacific = timezone(timedelta(hours=-7))
    # 03:30 PDT is the SAME instant as 18:30 Shanghai, not a mocked production clock.
    due = tick.due_status(calendar, datetime(2026, 10, 15, 3, 30, tzinfo=pacific))
    assert due["due"] is True
    assert due["wall_clock_shanghai"].startswith("2026-10-15T18:30")
    before = tick.due_status(calendar, datetime(2026, 10, 15, 2, 30, tzinfo=pacific))
    assert before["due"] is False
    closed = tick.due_status(calendar, datetime(2026, 10, 17, 11, tzinfo=timezone.utc))
    assert closed["due"] is False and closed["due_reason"] == "shanghai_exchange_closed"
    missing = tick.due_status(calendar, datetime(2026, 10, 19, 11, tzinfo=timezone.utc))
    assert missing["due"] is None


def test_not_due_does_not_prepare_or_append(tmp_path, monkeypatch):
    _, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    monkeypatch.setattr(tick, "due_status", lambda *args, **kwargs: {
        "due": False, "due_reason": "before_shanghai_18_settlement_window"})
    monkeypatch.setattr(tick, "prepare_release", lambda *args, **kwargs: pytest.fail("not due cannot prepare"))
    monkeypatch.setattr(runtime, "update", lambda *args, **kwargs: pytest.fail("not due cannot append"))
    report = tick.tick(readiness, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json",
                       artifacts / "prepared", artifacts / "owner", artifacts / "preserved", bindings)
    assert report["state"] == "not_due"
    assert not (artifacts / "owner/lowvol").exists()


def test_real_closed_session_is_due_on_weekend_and_before_next_close(tmp_path):
    from datetime import datetime, timezone
    calendar = tmp_path / "calendar.parquet"
    pd.DataFrame({"exchange": ["SSE"] * 4,
                  "cal_date": ["20261015", "20261016", "20261017", "20261019"],
                  "is_open": [1, 1, 0, 1]}).to_parquet(calendar)
    saturday = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)
    friday = tick.due_status(calendar, saturday, usable_date="2026-10-16")
    assert friday["due"] is True and friday["catch_up"] is True
    assert friday["due_reason"] == "closed_session_catch_up"
    assert friday["observation_date"] == "2026-10-17"
    assert friday["usable_session_date"] == "2026-10-16"
    assert tick.due_status(calendar, saturday, usable_date="2026-10-15")["due"] is True
    assert tick.due_status(calendar, saturday, usable_date="2026-10-17")["due"] is False
    assert tick.due_status(calendar, saturday, usable_date="2026-10-19")["due"] is False
    before_friday_close = datetime(2026, 10, 16, 1, tzinfo=timezone.utc)
    assert tick.due_status(calendar, before_friday_close, usable_date="2026-10-15")["due"] is True
    assert tick.due_status(calendar, before_friday_close, usable_date="2026-10-16")["due"] is False


def test_friday_data_arriving_saturday_uses_same_daily_entry_idempotently_as_replay(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    qa, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    calendar = archive / "calendar.parquet"
    days = pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"])
    pd.DataFrame({"exchange": ["SSE"] * 4,
                  "cal_date": ["20261015", "20261016", "20261017", "20261019"],
                  "is_open": [1, 1, 0, 1]}).to_parquet(calendar)
    qa.update(usable_date="2026-10-16", checked_at="2026-10-17T01:00:00Z")
    qa["calendar"].update(sha256=runtime.file_hash(calendar), confirmed_next_session="2026-10-19")
    qa["per_api_cutoffs"]["daily"] = "2026-10-16"
    readiness.write_text(json.dumps(qa))
    saturday = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)
    real_due = tick.due_status
    monkeypatch.setattr(tick, "due_status",
        lambda path, now=None, **kwargs: real_due(path, saturday, **kwargs))
    prepared, observed, calls = [], [], []
    def prepare(market, fundamental, directory, cutoff, **kwargs):
        prepared.append(Path(directory))
        assert cutoff == "2026-10-16"
        return Path(directory) / "inputs.json"
    def update(root, source, manifest, names, **kwargs):
        calls.append(kwargs)
        assert tuple(names) == ("lowvol",)
        assert kwargs == {"mode": "daily", "bindings": bindings}
        added = not observed
        if added:
            identity = {"created_at": "2026-10-14T00:00:00Z", "code_sha256": "fixture"}
            previous = [{"date": "2026-10-15", "recorded_at": "2026-10-15T11:00:00Z"}]
            observed.extend(runtime.observation_records(identity, days[1:2], days, previous,
                {"version": "fixture", "identity_sha256": "fixture"}, "daily", saturday))
        return {"lowvol": {"state": "reconciled", "last_date": "2026-10-16",
                           "new_sessions": int(added)}}
    monkeypatch.setattr(tick, "prepare_release", prepare)
    monkeypatch.setattr(runtime, "update", update)
    args = (readiness, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json",
            artifacts / "prepared", artifacts / "owner", artifacts / "preserved", bindings)
    first = tick.tick(*args, names=("lowvol",))
    second = tick.tick(*args, names=("lowvol",))
    assert first["state"] == "applied" and first["new_sessions"] == 1
    assert second["state"] == "up_to_date" and second["new_sessions"] == 0
    assert first["due_reason"] == second["due_reason"] == "closed_session_catch_up"
    assert prepared[0] == prepared[1] and len(calls) == 2
    assert len(observed) == 1 and observed[0]["kind"] == "replay"
    assert observed[0]["historical_forward_evidence"] is False


@pytest.mark.parametrize("change", [
    "missing_current", "legacy_current", "missing_binding", "advanced_current",
    "missing_bundle", "corrupt_bundle", "wrong_bundle_identity",
    "wrong_bundle_keys", "different_asset_identity",
])
def test_canonical_bundle_mismatch_is_pending_before_preparing_or_appending(tmp_path, monkeypatch, change):
    qa, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    current = artifacts / tick.ASSET_POINTER
    bundle = artifacts / qa["asset_bundle"]["bundle_path"]
    pointer = json.loads(current.read_text())
    if change == "missing_current":
        current.unlink()
    elif change == "legacy_current":
        current.write_text(json.dumps({"seed_state": "legacy must not be consumed"}))
    elif change == "missing_binding":
        del qa["asset_bundle"]
    elif change == "advanced_current":
        pointer["data_identity"] = "f" * 64
        current.write_text(json.dumps(pointer))
    elif change == "missing_bundle":
        bundle.unlink()
    elif change == "corrupt_bundle":
        bundle.write_bytes(bundle.read_bytes() + b"\n")
    elif change in ("wrong_bundle_identity", "wrong_bundle_keys"):
        payload = json.loads(bundle.read_text())
        if change == "wrong_bundle_identity":
            payload["data_identity"] = "f" * 64
        else:
            payload["evidence"]["inputs"]["futures"] = payload["evidence"]["inputs"].pop("cta_trend")
        bundle.write_text(json.dumps(payload))
        pointer["bundle_sha256"] = runtime.file_hash(bundle)
        current.write_text(json.dumps(pointer))
        qa["asset_bundle"]["bundle_sha256"] = pointer["bundle_sha256"]
    else:
        qa["asset_inputs"]["i7_turn_of_month"]["version"] = "stale-asset-version"
    readiness.write_text(json.dumps(qa))
    def forbidden(*args, **kwargs):
        pytest.fail("unbound/stale canonical asset identities must not prepare or append")
    monkeypatch.setattr(tick, "prepare_release", forbidden)
    monkeypatch.setattr(runtime, "update", forbidden)
    monkeypatch.setattr(tick, "due_status", lambda *args, **kwargs: {"due": True})
    old_nav = artifacts / "owner" / "lowvol" / "nav.csv"
    old_nav.parent.mkdir(parents=True)
    old_nav.write_bytes(b"existing ledger bytes must remain untouched\n")
    report = tick.tick(readiness, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json",
                       artifacts / "prepared", artifacts / "owner", artifacts / "preserved", bindings)
    assert report["state"] == "pending"
    assert all(item["state"] == "pending" for item in report["accounts"].values())
    assert old_nav.read_bytes() == b"existing ledger bytes must remain untouched\n"


@pytest.mark.parametrize("qa_advances", [False, True])
def test_asset_current_advance_during_preparation_does_not_append_old_inputs(tmp_path, monkeypatch, qa_advances):
    qa, readiness, archive, artifacts, bindings = fixture_qa(tmp_path)
    def prepare(*args, **kwargs):
        old = json.loads((artifacts / qa["asset_bundle"]["bundle_path"]).read_text())
        identity = "a" * 64
        old["data_identity"] = identity
        old["evidence"]["data_identity"] = identity
        bundle = artifacts / "ashare-input-supplements" / f"assets-{identity}" / "bundle.json"
        bundle.parent.mkdir()
        bundle.write_bytes(runtime.json_bytes(old))
        pointer = {"schema_version": 1, "data_identity": identity,
                   "bundle_path": str(bundle.relative_to(artifacts)),
                   "bundle_sha256": runtime.file_hash(bundle)}
        (artifacts / tick.ASSET_POINTER).write_bytes(runtime.json_bytes(pointer))
        if qa_advances:
            qa["asset_bundle"] = {"pointer_path": tick.ASSET_POINTER, **pointer}
            readiness.write_text(json.dumps(qa))
        return artifacts / "prepared" / "inputs.json"
    monkeypatch.setattr(tick, "prepare_release", prepare)
    monkeypatch.setattr(runtime, "update", lambda *a, **k: pytest.fail("superseded bundle cannot append"))
    monkeypatch.setattr(tick, "due_status", lambda *args, **kwargs: {"due": True})
    report = tick.tick(readiness, archive, artifacts, "RESEARCH_CURRENT.json", "CURRENT.json",
                       artifacts / "prepared", artifacts / "owner", artifacts / "preserved", bindings)
    assert report["state"] == "pending"
    assert not (artifacts / "owner" / "lowvol").exists()
