#!/usr/bin/env python3
"""Freeze local CN research inputs, then execute without network or live mounts."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.continuous_research.qlib_provider import generated_bytes, validate_provider


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def sha256(path, *, expected_size=None):
    if expected_size is not None:
        return hashlib.sha256(generated_bytes(path, expected_size)).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_config(cfg):
    snapshot_date_bounds(cfg)
    if cfg["market"] != "CN" or cfg["factor_source"] != "l1_factors":
        raise ValueError("Frozen baseline currently supports CN L1 only")
    if cfg["model"]["type"] != "lightgbm" or cfg.get("preprocessing", {}).get(
        "enabled"
    ):
        raise ValueError(
            "This runner supports LightGBM with training-median imputation"
        )
    if cfg["label"] != {"target_horizon_days": 1, "target_mode": "return"}:
        raise ValueError(
            "This baseline requires one-day return labels with T+1 execution"
        )
    segments = [cfg["split"][key] for key in ("train", "valid", "test")]
    dates = [date.fromisoformat(value) for segment in segments for value in segment]
    if any(a >= b for a, b in zip(dates, dates[1:], strict=False)):
        raise ValueError(
            "Training, validation and test periods must be ordered and disjoint"
        )
    if cfg["purpose"] != "development_comparison":
        raise ValueError(
            "Previously inspected test dates must be marked development_comparison"
        )
    if cfg["portfolio"]["single_factor"] not in cfg["features"]:
        raise ValueError(
            "Single-factor control must be included in the frozen features"
        )
    p = cfg["portfolio"]
    if not (
        0 < p["risk_degree"] <= 1
        and p["initial_capital"] > 0
        and 0 < p["n_drop"] <= p["topk"] <= cfg["universe"]["size"]
    ):
        raise ValueError("Invalid unlevered portfolio configuration")
    if cfg["exchange"]["deal_price"] != "close":
        raise ValueError("The one-day baseline requires next-day close execution")


def snapshot_date_bounds(cfg):
    """Do not inventory Parquet buffers beyond the requested development window."""
    cutoff = cfg.get("development_end")
    if not isinstance(cutoff, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff):
        raise ValueError("Frozen inputs require explicit ISO development_end")
    cutoff = date.fromisoformat(cutoff)
    segments = [
        [date.fromisoformat(value) for value in segment]
        for segment in cfg["split"].values()
    ]
    if any(
        len(segment) != 2 or segment[0] > segment[1] or segment[1] > cutoff
        for segment in segments
    ):
        raise ValueError("Frozen input split outside development_end")
    # Loading uses a start buffer; universe selection needs 180 days before train end.
    train_start, train_end = map(date.fromisoformat, cfg["split"]["train"])
    start = min(train_start - timedelta(days=30), train_end - timedelta(days=180))
    end = date.fromisoformat(cfg["split"]["test"][1])
    if start > end:
        raise ValueError("Invalid frozen input range")
    return start, end


def snapshot_files(
    root, cfg, data_root=None, *, provider_manifest=None, provider_manifest_sha256=None
):
    data_root = Path(data_root or root).resolve()
    start, end = snapshot_date_bounds(cfg)
    if provider_manifest is None or provider_manifest_sha256 is None:
        raise ValueError(
            "New snapshot requires explicit bounded provider manifest and SHA256"
        )
    provider = validate_provider(
        provider_manifest, provider_manifest_sha256, cutoff=end.isoformat()
    )
    provider_root = Path(provider_manifest).parent
    files = {
        path: Path("qlib") / path.relative_to(provider_root)
        for path in provider["files"]
    }
    for dataset in ("6_ml_datasets/l1_factors", "1_kline_data/daily_backward"):
        selected = []
        for partition in (data_root / "data/quantdb" / dataset).glob("dt=*"):
            raw = partition.name[3:]
            if not re.fullmatch(r"\d{8}", raw):
                raise ValueError(f"Invalid frozen partition date: {partition.name}")
            day = datetime.strptime(raw, "%Y%m%d").date()
            if start <= day <= end:
                if partition.is_symlink():
                    raise RuntimeError(
                        f"Frozen partition must not be a symlink: {partition}"
                    )
                selected.extend(partition.glob("*.parquet"))
        if not selected:
            raise RuntimeError(f"No frozen input partitions: {dataset}")
        for path in selected:
            files[path] = Path("quantdb") / path.relative_to(data_root / "data/quantdb")
    for path in (root / "backend").rglob("*.py"):
        files[path] = Path("code") / path.relative_to(root)
    # train.py imports local data, diagnostics and model_trainers packages.
    # Freeze the complete Python dependency tree, including package markers.
    for path in (root / "docker/training").rglob("*.py"):
        files[path] = Path("code") / path.relative_to(root)
    for name in ("frozen_research_worker.py", "run_frozen_research.py"):
        files[root / "scripts" / name] = Path("code/scripts") / name
    for name in ("qlib_provider.py", "qlib_prefix.py"):
        path = Path("scripts/continuous_research") / name
        files[root / path] = Path("code") / path
    return files


def freeze(
    root,
    out,
    cfg,
    image,
    data_root=None,
    *,
    provider_manifest=None,
    provider_manifest_sha256=None,
):
    validate_config(cfg)
    if (out / "manifest.json").exists():
        manifest = verify(out)
        if read(out / "snapshot/config.json") != cfg:
            raise RuntimeError(
                "Frozen configuration differs; use a new experiment directory"
            )
        if provider_manifest is not None or provider_manifest_sha256 is not None:
            if (
                provider_manifest is None
                or provider_manifest_sha256 is None
                or manifest.get("provider_binding", {}).get("manifest_sha256")
                != provider_manifest_sha256
            ):
                raise ValueError(
                    "Frozen provider identity differs or is unbound; use a new output"
                )
            candidate = validate_provider(
                provider_manifest,
                provider_manifest_sha256,
                cutoff=cfg["split"]["test"][1],
            )
            if candidate["binding"] != manifest["provider_binding"]:
                raise ValueError("Frozen provider binding differs")
        return manifest
    if provider_manifest is None or provider_manifest_sha256 is None:
        raise ValueError(
            "New freeze requires explicit bounded provider manifest and SHA256"
        )
    provider = validate_provider(
        provider_manifest, provider_manifest_sha256, cutoff=cfg["split"]["test"][1]
    )
    provider_files = provider["files"]
    out.mkdir(parents=True, exist_ok=True)
    snapshot = out / "snapshot"
    if snapshot.exists():
        raise RuntimeError("Incomplete snapshot retained; use a new output directory")
    sources = snapshot_files(
        root,
        cfg,
        data_root=data_root,
        provider_manifest=provider_manifest,
        provider_manifest_sha256=provider_manifest_sha256,
    )
    total = sum(path.stat().st_size for path in sources)
    if shutil.disk_usage(out).free < total + 1024**3:
        raise RuntimeError("Insufficient disk space for snapshot and research outputs")
    snapshot.mkdir()
    entries = []
    for source, relative in sorted(sources.items()):
        if source.is_symlink():
            raise RuntimeError(f"Snapshot inputs must be physical files: {source}")
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = provider_files.get(source)
        size = expected["size"] if expected else None
        before = sha256(source, expected_size=size)
        if expected:
            if before != expected["sha256"]:
                raise ValueError("Bounded provider changed before copy")
            target.write_bytes(generated_bytes(source, size))
        else:
            shutil.copyfile(source, target)
        if before != sha256(target) or before != sha256(source, expected_size=size):
            raise RuntimeError(f"Source changed while freezing: {source}")
        entries.append(
            {
                "path": relative.as_posix(),
                "sha256": before,
                "bytes": target.stat().st_size,
            }
        )
    # Detect writes during the whole multi-file copy, not just individual copies.
    for (source, _), entry in zip(sorted(sources.items()), entries, strict=True):
        expected = provider_files.get(source)
        if (
            sha256(source, expected_size=expected["size"] if expected else None)
            != entry["sha256"]
        ):
            raise RuntimeError(f"Source changed during snapshot: {source}")
    validate_provider(
        provider_manifest, provider_manifest_sha256, cutoff=cfg["split"]["test"][1]
    )
    write(snapshot / "config.json", cfg)
    entries.append(
        {
            "path": "config.json",
            "sha256": sha256(snapshot / "config.json"),
            "bytes": (snapshot / "config.json").stat().st_size,
        }
    )
    manifest = {
        "schema_version": 1,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "image": image,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "files": entries,
        "provider_binding": provider["binding"],
        "total_bytes": sum(e["bytes"] for e in entries),
    }
    write(out / "manifest.json", manifest)
    return manifest


def verify(out):
    manifest = read(out / "manifest.json")
    snapshot = out / "snapshot"
    expected = {entry["path"] for entry in manifest["files"]}
    actual = {
        p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()
    }
    if actual != expected:
        raise RuntimeError("Frozen file inventory changed")
    for entry in manifest["files"]:
        path = snapshot / entry["path"]
        if path.is_symlink() or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"Frozen checksum mismatch: {entry['path']}")
    if (
        snapshot / "qlib/provider_manifest.json"
    ).exists() and "provider_binding" not in manifest:
        raise RuntimeError("Frozen provider binding missing for bounded provider")
    if "provider_binding" in manifest:
        provider_path = snapshot / "qlib/provider_manifest.json"
        provider = read(provider_path)
        cfg = read(snapshot / "config.json")
        _, end = snapshot_date_bounds(cfg)
        declaration_sha = hashlib.sha256(
            json.dumps(
                provider["declaration"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        expected_binding = {
            "manifest_sha256": sha256(provider_path),
            "declaration_sha256": declaration_sha,
            "cutoff": end.isoformat(),
            "snapshot_manifest": "qlib/provider_manifest.json",
        }
        if (
            manifest["provider_binding"] != expected_binding
            or provider.get("declaration_sha256") != declaration_sha
            or provider["declaration"].get("cutoff") != end.isoformat()
        ):
            raise RuntimeError(
                "Frozen provider binding inconsistent with stored inputs"
            )
    return manifest


def command(out, manifest, attempt):
    return [
        "docker",
        "run",
        "--name",
        "qm-frozen-" + attempt.name,
        "--platform",
        manifest["image"]["Os"] + "/" + manifest["image"]["Architecture"],
        "--network",
        "none",
        "--read-only",
        "--cpus",
        "4",
        "--memory",
        "8g",
        "--tmpfs",
        "/tmp:rw,size=1g",
        "--workdir",
        "/output",
        "--mount",
        f"type=bind,src={out / 'snapshot'},dst=/frozen,readonly",
        "--mount",
        f"type=bind,src={attempt},dst=/output",
        "--env",
        "PYTHONPATH=/frozen/code:/frozen/code/docker/training:/frozen/code/scripts",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "LITELLM_LOCAL_MODEL_COST_MAP=True",
        "--env",
        "HOME=/tmp",
        "--env",
        "OMP_NUM_THREADS=4",
        "--env",
        "PYTHONHASHSEED=42",
        "--env",
        "QM_QUANTDB_DATA_DIR=/frozen/quantdb",
        "--env",
        "QUANTDB_DATA_DIR=/frozen/quantdb",
        "--env",
        "QLIB_PROVIDER_URI=/frozen/qlib",
        "--entrypoint",
        "python",
        manifest["image"]["Id"],
        "/frozen/code/scripts/frozen_research_worker.py",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["freeze", "run", "verify"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Runtime root containing data/quantdb; raw Qlib is never selected",
    )
    parser.add_argument("--provider-manifest", type=Path)
    parser.add_argument("--provider-manifest-sha256")
    parser.add_argument("--image", help="Defaults to the running QuantMind image ID")
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == "verify":
        verify(out)
        print("Frozen inputs verified:", out)
        return
    cfg_path = args.config or (
        out / "snapshot/config.json"
        if (out / "manifest.json").exists()
        else ROOT / "config/research_controls_cn_l1.json"
    )
    cfg = read(cfg_path)
    if (out / "manifest.json").exists():
        manifest = freeze(
            ROOT,
            out,
            cfg,
            None,
            data_root=args.data_root,
            provider_manifest=args.provider_manifest,
            provider_manifest_sha256=args.provider_manifest_sha256,
        )
    else:
        if args.provider_manifest is None or args.provider_manifest_sha256 is None:
            raise ValueError(
                "New freeze requires --provider-manifest and --provider-manifest-sha256"
            )
        image_id = (
            args.image
            or subprocess.check_output(
                ["docker", "inspect", "quantmind", "--format", "{{.Image}}"], text=True
            ).strip()
        )
        image = json.loads(
            subprocess.check_output(["docker", "image", "inspect", image_id], text=True)
        )[0]
        manifest = freeze(
            ROOT,
            out,
            cfg,
            {key: image[key] for key in ("Id", "Os", "Architecture", "RepoDigests")},
            data_root=args.data_root,
            provider_manifest=args.provider_manifest,
            provider_manifest_sha256=args.provider_manifest_sha256,
        )
    print("Frozen", len(manifest["files"]), "files before execution", flush=True)
    if args.stage == "freeze":
        return
    if (out / "completion.json").exists():
        completion = read(out / "completion.json")
        attempt = out / completion["attempt"]
        for name, digest in completion["artifacts"].items():
            if sha256(attempt / name) != digest:
                raise RuntimeError(f"Completed result changed: {name}")
        print("Existing verified comparison:", attempt / "README.md")
        return
    attempt = out / (
        "attempt-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    )
    attempt.mkdir()
    cmd = command(out, manifest, attempt)
    write(
        attempt / "execution.json",
        {"command": cmd, "manifest_sha256": sha256(out / "manifest.json")},
    )
    with (attempt / "execution.log").open("w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    verify(out)
    if result.returncode:
        raise RuntimeError(
            f"Research failed; inputs, container and logs retained: {attempt}"
        )
    result = read(attempt / "summary.json")
    if not result["checks_passed"]:
        raise RuntimeError("Research checks failed")
    write(
        out / "completion.json",
        {
            "status": "verified",
            "attempt": attempt.name,
            "artifacts": {p.name: sha256(p) for p in attempt.iterdir() if p.is_file()},
        },
    )
    print("Completed frozen comparison:", attempt / "README.md")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
