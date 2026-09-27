"""Only synthetic provider fragments. No Qlib import or real input access."""

import hashlib
import json
import os
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.continuous_research import qlib_provider as provider


@pytest.fixture
def case(tmp_path):
    root = tmp_path.resolve()
    source, destination = root / "source", root / "new-package"
    (source / "calendars").mkdir(parents=True)
    calendar = [
        "2026-03-17",
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
        "2026-03-23",
        "2026-03-24",
    ]
    (source / "calendars/day.txt").write_bytes(
        ("\n".join(calendar) + "\nPOISON_FUTURE_CALENDAR\n").encode()
    )
    for symbol in ("syn_a", "syn_b", "syn_index"):
        directory = source / "features" / symbol
        directory.mkdir(parents=True)
        for field in ("close", "open"):
            # Nonzero header; NaN payload deliberately has noncanonical bits.
            raw = (
                struct.pack("<3f", 2, 11, 12)
                + struct.pack("<I", 0x7FC01234)
                + struct.pack("<3f", 14, 900001, 900002)
            )
            (directory / (field + ".day.bin")).write_bytes(raw)
    kwargs = {
        "calendar_prefix": calendar,
        "cutoff": calendar[-1],
        "symbols": ["syn_a", "syn_b"],
        "fields": ["close", "open"],
        "lifetimes": {
            s: [calendar[2], "2026-03-26"] for s in ("syn_a", "syn_b", "syn_index")
        },
        "benchmark": "syn_index",
        "day_future_endpoint": "2026-03-25",
    }
    return source, destination, kwargs


def no_candidate(destination):
    assert not destination.exists()
    assert not list(destination.parent.glob(".qlib-provider-*.tmp"))


def test_real_helper_prefix_and_complete_publication(case):
    source, destination, kwargs = case
    limits = {}
    for p in source.rglob("*"):
        if p.is_file():
            limits[p.stat().st_ino] = (
                len(("\n".join(kwargs["calendar_prefix"]) + "\n").encode())
                if p.name == "day.txt"
                else 20
            )
    original = os.read
    reads = []

    def guarded(fd, count):
        limit = limits.get(os.fstat(fd).st_ino)
        if limit is not None:
            offset = os.lseek(fd, 0, os.SEEK_CUR)
            assert offset + count <= limit, "source future tail requested"
            reads.append((offset, count))
        return original(fd, count)

    with patch("os.read", guarded):
        manifest = provider.build_provider(source, destination, **kwargs)
    assert reads == [(0, 66)] + [(0, 4), (4, 16)] * 6
    out = Path(manifest["provider_path"])
    assert json.loads((out / "provider_manifest.json").read_text()) == manifest
    assert (out / "calendars/day_future.txt").read_text() == (
        out / "calendars/day.txt"
    ).read_text() + "2026-03-25\n"
    assert "syn_index" not in (out / "instruments/all.txt").read_text()
    assert len(manifest["sources"]) == 7 and len(manifest["outputs"]) == 9
    for identity in manifest["outputs"]:
        payload = (out / identity["path"]).read_bytes()
        assert len(payload) == identity["size"]
        assert hashlib.sha256(payload).hexdigest() == identity["sha256"]
        assert identity["identity_scope"] == "output_whole_file"
    for symbol in ("syn_a", "syn_b", "syn_index"):
        assert (out / f"features/{symbol}/close.day.bin").read_bytes() == (
            source / f"features/{symbol}/close.day.bin"
        ).read_bytes()[:20]
    assert all(
        item["identity_scope"] == "source_byte_range_only"
        for item in manifest["sources"]
    )
    assert (
        not manifest["atomic_source_snapshot"]
        and not manifest["point_in_time_verified"]
        and not manifest["research_admitted"]
    )


def test_short_series_and_lifecycle_end_not_extended(case):
    source, destination, kwargs = case
    raw = struct.pack("<3f", 2, 11, 12)
    (source / "features/syn_a/open.day.bin").write_bytes(raw)
    kwargs["lifetimes"]["syn_b"][1] = "2026-03-20"
    result = provider.build_provider(source, destination, **kwargs)
    out = Path(result["provider_path"])
    assert (out / "features/syn_a/open.day.bin").read_bytes() == raw
    assert len((out / "features/syn_b/close.day.bin").read_bytes()) == 12
    assert result["bounded_lifetimes"]["syn_b"][1] == "2026-03-20"
    assert result["bounded_lifetimes"]["syn_a"][1] == "2026-03-24"


def test_unselected_future_symbol_and_unknown_source_file_never_opened(case):
    source, destination, kwargs = case
    future = source / "features/syn_future"
    future.mkdir()
    (future / "close.day.bin").write_bytes(struct.pack("<2f", 6, 999999))
    (source / "unknown-cache").write_bytes(b"NEVER_READ")
    original = os.open

    def guarded(path, *args, **kw):
        assert "syn_future" not in str(path) and "unknown-cache" not in str(path)
        return original(path, *args, **kw)

    with patch("os.open", guarded):
        result = provider.build_provider(source, destination, **kwargs)
    assert all("syn_future" not in item["path"] for item in result["outputs"])


@pytest.mark.parametrize(
    "change",
    [
        "future",
        "missing-life",
        "extra-life",
        "bad-field",
        "traversal",
        "duplicate",
        "late-endpoint",
        "absent-benchmark",
    ],
)
def test_invalid_declarations_reject_before_sources(case, change):
    source, destination, kwargs = case
    if change == "future":
        kwargs["lifetimes"]["syn_a"] = ["2026-03-25", "2026-03-26"]
    if change == "missing-life":
        del kwargs["lifetimes"]["syn_a"]
    if change == "extra-life":
        kwargs["lifetimes"]["other"] = ["2026-03-17", "2026-03-24"]
    if change == "bad-field":
        kwargs["fields"] = ["unknown"]
    if change == "traversal":
        kwargs["symbols"] = ["../outside"]
    if change == "duplicate":
        kwargs["symbols"] = ["syn_a", "syn_a"]
    if change == "late-endpoint":
        kwargs["day_future_endpoint"] = "2026-03-24"
    if change == "absent-benchmark":
        kwargs["benchmark"] = "unknown"
    with patch("os.open") as spy, pytest.raises(ValueError):
        provider.build_provider(source, destination, **kwargs)
    spy.assert_not_called()
    no_candidate(destination)


@pytest.mark.parametrize(
    "calendar",
    [
        ["2026-3-17", "2026-03-24"],
        ["2026-02-30", "2026-03-24"],
        ["2026-03-24", "2026-03-17"],
        ["2026-03-17", "2026-03-17", "2026-03-24"],
        ["2026-03-17", "2026-03-25"],
    ],
)
def test_bad_calendar_declaration(case, calendar):
    source, destination, kwargs = case
    kwargs["calendar_prefix"] = calendar
    with pytest.raises(ValueError):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)


def test_rebased_calendar_rejected(case):
    source, destination, kwargs = case
    kwargs["calendar_prefix"] = kwargs["calendar_prefix"][2:]
    with pytest.raises(ValueError, match="global calendar"):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "symlink-file",
        "symlink-parent",
        "symlink-calendar",
        "source-link",
        "before-life",
        "future-header",
    ],
)
def test_sources_reject_without_partial_publish(case, kind):
    source, destination, kwargs = case
    binary = source / "features/syn_a/close.day.bin"
    if kind == "missing":
        binary.unlink()
    if kind == "symlink-file":
        moved = source / "outside.bin"
        binary.rename(moved)
        binary.symlink_to(moved)
    if kind == "symlink-parent":
        directory = binary.parent
        moved = source / "outside"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    if kind == "symlink-calendar":
        calendar = source / "calendars/day.txt"
        moved = source / "outside.txt"
        calendar.rename(moved)
        calendar.symlink_to(moved)
    if kind == "source-link":
        moved = source.with_name("moved-source")
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=True)
    if kind == "before-life":
        binary.write_bytes(struct.pack("<2f", 0, 11))
    if kind == "future-header":
        binary.write_bytes(struct.pack("<2f", 6, 999))
    with pytest.raises((ValueError, OSError)):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)


@pytest.mark.parametrize("kind", ["file", "parent", "calendar"])
def test_source_replaced_after_prefix_fails_final_check(case, kind):
    source, destination, kwargs = case
    original = provider.feature_prefix
    count = 0

    def replace(*args, **kw):
        nonlocal count
        result = original(*args, **kw)
        count += 1
        if count == 1:
            target = source / (
                "calendars/day.txt"
                if kind == "calendar"
                else "features/syn_a/close.day.bin"
            )
            if kind == "parent":
                target = target.parent
            moved = target.with_name(target.name + "-old")
            target.rename(moved)
            if kind == "parent":
                target.symlink_to(moved, target_is_directory=True)
            else:
                target.write_bytes(moved.read_bytes())
        return result

    with (
        patch.object(provider, "feature_prefix", replace),
        pytest.raises((ValueError, OSError)),
    ):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)


@pytest.mark.parametrize("kind", ["empty", "full", "symlink", "publish-race"])
def test_destination_never_overwritten(case, kind):
    source, destination, kwargs = case
    sentinel = b"OLD_PACKAGE_KEEP"
    if kind == "symlink":
        old = destination.with_name("old-package")
        old.mkdir()
        destination.symlink_to(old, target_is_directory=True)
    elif kind != "publish-race":
        destination.mkdir()
    if kind in ("full", "symlink"):
        (destination / "old").write_bytes(sentinel)
    original = provider._unchanged
    if kind == "publish-race":

        def race(*args):
            original(*args)
            if not destination.exists():
                destination.mkdir()
                (destination / "old").write_bytes(sentinel)
    else:
        race = original
    with patch.object(provider, "_unchanged", race), pytest.raises(FileExistsError):
        provider.build_provider(source, destination, **kwargs)
    assert destination.exists()
    if kind != "empty":
        assert (destination / "old").read_bytes() == sentinel
    assert not list(destination.parent.glob(".qlib-provider-*.tmp"))


def test_no_endpoint_is_not_invented_and_failed_publish_cleans_shell(case):
    source, destination, kwargs = case
    kwargs["day_future_endpoint"] = None
    with (
        patch("os.rename", side_effect=OSError("publication failed")),
        pytest.raises(OSError),
    ):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)
    result = provider.build_provider(source, destination, **kwargs)
    assert not (Path(result["provider_path"]) / "calendars/day_future.txt").exists()


def test_replacement_between_before_stat_and_helper_is_rejected(case):
    source, destination, kwargs = case
    original = provider.feature_prefix
    replaced = False

    def replace(*args, **kw):
        nonlocal replaced
        if not replaced:
            path = source / "features/syn_a/close.day.bin"
            moved = path.with_suffix(".old")
            path.rename(moved)
            path.write_bytes(moved.read_bytes())
            replaced = True
        return original(*args, **kw)

    with (
        patch.object(provider, "feature_prefix", replace),
        pytest.raises(ValueError, match="changed"),
    ):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)


def test_output_failure_and_output_parent_symlink(case):
    source, destination, kwargs = case
    original = provider._write
    count = 0

    def fail(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("synthetic disk failure")
        return original(*args)

    with (
        patch.object(provider, "_write", fail),
        pytest.raises(OSError, match="disk failure"),
    ):
        provider.build_provider(source, destination, **kwargs)
    no_candidate(destination)
    alias = destination.parent / "output-alias"
    alias.symlink_to(destination.parent, target_is_directory=True)
    with pytest.raises(OSError):
        provider.build_provider(source, alias / destination.name, **kwargs)
    no_candidate(destination)
