"""Pure invented provider + actual public freeze; never a market-data package."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import run_frozen_research as frozen
from scripts.continuous_research.qlib_provider import build_provider, validate_provider


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path):
    base = tmp_path.resolve()
    raw, root, runtime = base / "raw", base / "code", base / "runtime"
    calendar = [
        "2026-03-17",
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
        "2026-03-23",
        "2026-03-24",
    ]
    (raw / "calendars").mkdir(parents=True)
    (raw / "calendars/day.txt").write_text("\n".join(calendar) + "\n2026-03-25\nPOISON")
    (raw / "features/syn_a").mkdir(parents=True)
    (raw / "features/syn_a/close.day.bin").write_bytes(
        struct.pack("<7f", 2, 11, 12, 13, 14, 999991, 999992)
    )
    declared = {
        "calendar_prefix": calendar,
        "cutoff": calendar[-1],
        "symbols": ["syn_a"],
        "fields": ["close"],
        "lifetimes": {"syn_a": [calendar[2], calendar[-1]]},
        "benchmark": None,
        "day_future_endpoint": "2026-03-25",
    }
    built = build_provider(raw, base / "generated", **declared)
    manifest = Path(built["provider_path"]) / "provider_manifest.json"
    for dataset in ("6_ml_datasets/l1_factors", "1_kline_data/daily_backward"):
        path = runtime / "data/quantdb" / dataset / "dt=20260324/a.parquet"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic selector only, not Parquet")
    (runtime / "db/qlib_data").mkdir(parents=True)
    (runtime / "db/qlib_data/NEVER_OPEN").write_bytes(b"POISON")
    for rel in (
        "scripts/run_frozen_research.py",
        "scripts/continuous_research/qlib_provider.py",
        "scripts/continuous_research/qlib_prefix.py",
    ):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen.ROOT / rel, target)
    (root / "scripts/frozen_research_worker.py").write_text("# inert, never executed\n")
    cfg = frozen.read(frozen.ROOT / "config/research_controls_cn_l1.json")
    cfg.update(
        development_end="2026-03-24",
        split={
            "train": ["2026-01-01", "2026-01-31"],
            "valid": ["2026-02-01", "2026-02-28"],
            "test": ["2026-03-01", "2026-03-24"],
        },
    )
    return {
        "base": base,
        "raw": raw,
        "root": root,
        "runtime": runtime,
        "manifest": manifest,
        "cfg": cfg,
        "declared": declared,
        "out": base / "frozen",
    }


def args(case):
    return {
        "data_root": case["runtime"],
        "provider_manifest": case["manifest"],
        "provider_manifest_sha256": digest(case["manifest"]),
    }


def freeze(case, **overrides):
    kw = {**args(case), **overrides}
    with patch.object(
        frozen.subprocess, "check_output", return_value="synthetic-code-commit"
    ):
        return frozen.freeze(
            case["root"], case["out"], case["cfg"], {"Id": "synthetic"}, **kw
        )


def edit_manifest(case, edit):
    value = json.loads(case["manifest"].read_text())
    edit(value)
    case["manifest"].write_text(json.dumps(value))


def test_actual_freeze_three_hash_stages_only_generated_and_cli_closure(case):
    original_open, original_sha = os.open, frozen.sha256
    source_calls = []
    provider_root = case["manifest"].parent

    def guarded_open(path, *a, **kw):
        assert str(case["raw"]) not in str(path) and "db/qlib_data" not in str(path)
        return original_open(path, *a, **kw)

    def spy(path, **kw):
        if Path(path).is_relative_to(provider_root):
            source_calls.append((Path(path), kw))
        return original_sha(path, **kw)

    with patch("os.open", guarded_open), patch.object(frozen, "sha256", spy):
        result = freeze(case)
    generated = [p for p in provider_root.rglob("*") if p.is_file()]
    assert len(source_calls) == 3 * len(generated)
    for p in generated:
        assert len([x for x in source_calls if x[0] == p]) == 3
        assert all(
            x[1]["expected_size"] == p.stat().st_size for x in source_calls if x[0] == p
        )
        assert (
            case["out"] / "snapshot/qlib" / p.relative_to(provider_root)
        ).read_bytes() == p.read_bytes()
    assert result["provider_binding"]["manifest_sha256"] == digest(case["manifest"])
    shutil.rmtree(provider_root)
    assert frozen.verify(case["out"]) == result  # external provider is not required
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    script = case["out"] / "snapshot/code/scripts/run_frozen_research.py"
    response = subprocess.run(
        [sys.executable, "-B", str(script), "verify", "--output", str(case["out"])],
        cwd=case["base"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert response.returncode == 0, response.stderr


@pytest.mark.parametrize("kind", ["missing", "one-sided", "wrong-hash", "wrong-cutoff"])
def test_new_freeze_requires_explicit_matching_provider(case, kind):
    kw = args(case)
    if kind == "missing":
        kw.pop("provider_manifest")
        kw.pop("provider_manifest_sha256")
    if kind == "one-sided":
        kw.pop("provider_manifest_sha256")
    if kind == "wrong-hash":
        kw["provider_manifest_sha256"] = "0" * 64
    if kind == "wrong-cutoff":
        case["cfg"]["split"]["test"][1] = "2026-03-23"
    with pytest.raises(ValueError):
        frozen.freeze(case["root"], case["out"], case["cfg"], {}, **kw)
    assert not case["out"].exists()


@pytest.mark.parametrize(
    "kind",
    [
        "tamper",
        "extra",
        "missing",
        "duplicate",
        "traversal",
        "absolute",
        "bad-declaration",
        "bad-size",
        "bad-metadata",
        "future-header",
        "symlink",
        "parent-symlink",
        "manifest-parent-symlink",
    ],
)
def test_provider_rejects_tamper_and_inventory_errors(case, kind):
    p = case["manifest"].parent / "features/syn_a/close.day.bin"
    if kind == "tamper":
        p.write_bytes(b"x" * p.stat().st_size)
    if kind == "extra":
        (p.parent / "unknown.bin").write_bytes(b"never admitted")
    if kind == "missing":
        p.unlink()
    if kind == "duplicate":
        edit_manifest(
            case, lambda m: m["outputs"].append(copy.deepcopy(m["outputs"][0]))
        )
    if kind in ("traversal", "absolute"):
        edit_manifest(
            case,
            lambda m: m["outputs"][0].update(
                path="../outside" if kind == "traversal" else "/outside"
            ),
        )
    if kind == "bad-declaration":
        edit_manifest(case, lambda m: m.update(declaration_sha256="0" * 64))
    if kind == "bad-size":
        edit_manifest(case, lambda m: m["outputs"][0].update(size=99999))
    if kind in ("bad-metadata", "future-header"):
        rel = (
            "calendars/day.txt"
            if kind == "bad-metadata"
            else "features/syn_a/close.day.bin"
        )
        p = case["manifest"].parent / rel
        data = p.read_bytes()
        p.write_bytes(
            data.replace(b"03-17", b"03-16")
            if kind == "bad-metadata"
            else struct.pack("<f", 10) + data[4:]
        )
        edit_manifest(
            case,
            lambda m: [
                i.update(sha256=digest(p)) for i in m["outputs"] if i["path"] == rel
            ],
        )
    if kind == "symlink":
        moved = case["base"] / "outside.bin"
        p.rename(moved)
        p.symlink_to(moved)
    if kind == "parent-symlink":
        moved = case["base"] / "outside-dir"
        p.parent.rename(moved)
        p.parent.symlink_to(moved, target_is_directory=True)
    if kind == "manifest-parent-symlink":
        parent = case["manifest"].parent
        moved = parent.with_name("moved")
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        freeze(case)
    assert not case["out"].exists()


def test_source_provenance_never_opened_and_same_output_different_provider_rejected(
    case,
):
    edit_manifest(
        case,
        lambda m: m.update(
            source_root="/FORBIDDEN_SOURCE",
            sources=[{"path": "/FORBIDDEN_SOURCE", "sha256": "unverified provenance"}],
        ),
    )
    first = freeze(case)
    other = build_provider(
        case["raw"], case["base"] / "other-generated", **case["declared"]
    )
    alternate = Path(other["provider_path"]) / "provider_manifest.json"
    assert digest(alternate) != first["provider_binding"]["manifest_sha256"]
    with pytest.raises(ValueError, match="identity differs"):
        freeze(
            case,
            provider_manifest=alternate,
            provider_manifest_sha256=digest(alternate),
        )
    assert frozen.verify(case["out"]) == first


@pytest.mark.parametrize(
    "key",
    [
        "manifest_sha256",
        "declaration_sha256",
        "cutoff",
        "snapshot_manifest",
        "delete-binding",
    ],
)
def test_new_frozen_binding_verified_against_own_snapshot(case, key):
    result = freeze(case)
    if key == "delete-binding":
        del result["provider_binding"]
    else:
        result["provider_binding"][key] = "tampered"
    frozen.write(case["out"] / "manifest.json", result)
    with pytest.raises(RuntimeError, match="binding"):
        frozen.verify(case["out"])
    with pytest.raises(RuntimeError, match="binding"):
        frozen.freeze(case["root"], case["out"], case["cfg"], None)


def test_old_manifest_verify_and_resume_stay_compatible(case):
    out = case["out"]
    (out / "snapshot").mkdir(parents=True)
    frozen.write(out / "snapshot/config.json", case["cfg"])
    (out / "snapshot/old.txt").write_text("synthetic old snapshot")
    entries = [
        {"path": p.name, "sha256": digest(p), "bytes": p.stat().st_size}
        for p in (out / "snapshot").iterdir()
    ]
    old = {"schema_version": 1, "files": entries}
    frozen.write(out / "manifest.json", old)
    assert frozen.verify(out) == old
    assert frozen.freeze(case["root"], out, case["cfg"], None) == old
    with pytest.raises(ValueError, match="unbound"):
        freeze(case)


def test_same_provider_can_resume_without_changes(case):
    original = freeze(case)
    old_bytes = (case["out"] / "manifest.json").read_bytes()
    assert freeze(case) == original
    assert frozen.freeze(case["root"], case["out"], case["cfg"], None) == original
    assert (case["out"] / "manifest.json").read_bytes() == old_bytes


def test_generated_growth_after_validation_rejected_before_hash_read(case):
    target = case["manifest"].parent / "features/syn_a/close.day.bin"
    original_sha, original_read = frozen.sha256, os.read
    switched = False

    def sha(path, **kw):
        nonlocal switched
        if Path(path) == target and not switched:
            target.write_bytes(target.read_bytes() + struct.pack("<f", 999999))
            switched = True
        return original_sha(path, **kw)

    def guarded(fd, count):
        if switched and os.fstat(fd).st_ino == target.stat().st_ino:
            pytest.fail("grown feature read before declared-size rejection")
        return original_read(fd, count)

    with (
        patch.object(frozen, "sha256", sha),
        patch("os.read", guarded),
        pytest.raises(ValueError, match="size"),
    ):
        freeze(case)
    assert not (case["out"] / "manifest.json").exists()
