#!/usr/bin/env python3
"""Replay only frozen 05/B2/B3/B5 experiments using preserved inputs.

No grids, choice generation, tuning or new evaluation. Compare all original
numeric output files, not plots/serialization bytes. Writes a fresh run folder;
never writes the preserved reference, vendor data, or old ashare worktrees.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor/ashare-lab"
GROUPS = {
    "05": ("final_is", "final_oos", "final_full"),
    "B2": ("b2_final_is", "b2_final_oos", "b2_final_full", "b2_robust"),
    "B3": ("b3_is", "b3_oos", "b3_full"),
    "B5": ("b5_capacity_full", "b5_capacity_oos", "b5_ref", "b5_sens"),
}
OUTPUTS = ("summary.csv", "annual.csv", "nav.parquet", "trades.parquet", "exposure.parquet")


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_configs(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EXPERIMENTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    parser.add_argument("--archive", type=Path, default=ROOT / "output/ashare-takeover")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--rtol", type=float, default=1e-12)
    parser.add_argument("--atol", type=float, default=1e-12)
    args = parser.parse_args()
    import pandas as pd

    archive = args.archive.resolve()
    reference = archive / "trees/ashare-lab"
    identity_path = archive / "identity.json"
    identity = json.loads(identity_path.read_text())
    main_identity = next(item for item in identity["trees"] if item["name"] == "ashare-lab")
    # Config modules only enumerate existing frozen specs. Nothing selects them.
    original = load_configs(reference / "experiments/configs.py", "original_frozen_configs")
    migrated = load_configs(VENDOR / "experiments/configs.py", "migrated_frozen_configs")
    experiments = [name for group in args.groups for name in GROUPS[group]]
    reference_trees = {name: ("ashare-lab" if group == "05" else "ashare-lab-bline")
                       for group in args.groups for name in GROUPS[group]}
    report_roots = {name: archive / "trees" / reference_trees[name] / "reports" / name
                    for name in experiments}
    bline_configs = load_configs(
        archive / "trees/ashare-lab-bline/experiments/configs.py", "bline_frozen_configs")
    for name in experiments:
        if original[name] != migrated[name]:
            raise RuntimeError(f"Frozen config changed: {name}")
        if reference_trees[name] == "ashare-lab-bline" and original[name] != bline_configs[name]:
            raise RuntimeError(f"Original main/B-line frozen config differs: {name}")
        if not report_roots[name].is_dir():
            raise FileNotFoundError(report_roots[name])
        for filename in OUTPUTS:
            main_file = reference / "reports" / name / filename
            selected = report_roots[name] / filename
            if main_file.exists() and (not selected.exists() or sha256(main_file) != sha256(selected)):
                raise RuntimeError(f"Conflicting original report identity: {name}/{filename}")
    out = args.out or ROOT / "output/ashare-parity" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = out.resolve()
    # No overwrite; references and the data roots remain immutable.
    out.mkdir(parents=True, exist_ok=False)
    work = out / "work"
    work.mkdir()
    (work / "data").symlink_to(reference / "data", target_is_directory=True)
    reports = work / "reports"
    reports.mkdir()
    for path in (reference / "reports").iterdir():
        if path.name != "b3":
            (reports / path.name).symlink_to(path, target_is_directory=path.is_dir())
    (reports / "b3").mkdir()
    for path in (reference / "reports/b3").iterdir():
        (reports / "b3" / path.name).symlink_to(path, target_is_directory=path.is_dir())
    # B-line's ignored factor caches were never present in main. Select the
    # preserved original version explicitly; never regenerate factor inputs.
    frozen_caches = {}
    with sqlite3.connect(archive / "manifest.sqlite") as database:
        for filename in ("factors_naive.parquet", "factors_pit.parquet"):
            relative = "reports/b3/" + filename
            expected_hash = database.execute(
                "SELECT sha256 FROM files WHERE tree=? AND path=?",
                ("ashare-lab-bline", relative)).fetchone()
            source = archive / "trees/ashare-lab-bline" / relative
            if not expected_hash or sha256(source) != expected_hash[0]:
                raise RuntimeError("Preserved frozen factor identity differs: " + relative)
            (reports / "b3" / filename).symlink_to(source)
            frozen_caches[relative] = {
                "tree": "ashare-lab-bline", "sha256": expected_hash[0],
                "path": str(source.relative_to(archive)),
            }
    source_files = {
        str(path.relative_to(VENDOR)): sha256(path)
        for folder in (VENDOR / "src", VENDOR / "experiments")
        for path in sorted(folder.rglob("*.py"))
    }
    result = {"reference_commit": main_identity["commit"],
              "reference_manifest_sha256": main_identity["manifest_sha256"],
              "archive_identity_sha256": sha256(identity_path),
              "source_files": source_files, "rtol": args.rtol, "atol": args.atol,
              "configs": {name: original[name] for name in experiments},
              "frozen_factor_caches": frozen_caches,
              "report_references": {
                  name: {"tree": reference_trees[name],
                         "path": str(report_roots[name].relative_to(archive)),
                         "manifest_sha256": next(item["manifest_sha256"] for item in identity["trees"]
                                                 if item["name"] == reference_trees[name])}
                  for name in experiments},
              "experiments": [], "success": False}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name in experiments:
        target = out / name
        command = [sys.executable, "-B", str(VENDOR / "experiments/run.py"), name, "--out", str(target)]
        row = {"name": name, "command": command, "files": {}, "success": True}
        try:
            with (out / f"{name}.log").open("w") as log:
                subprocess.run(command, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            for filename in OUTPUTS:
                expected = report_roots[name] / filename
                actual = target / filename
                if not expected.exists() and not actual.exists():
                    continue
                if expected.exists() != actual.exists():
                    raise AssertionError(f"Output presence changed: {filename}")
                loader = pd.read_parquet if filename.endswith(".parquet") else pd.read_csv
                left, right = loader(expected), loader(actual)
                metadata_additions = {}
                if filename == "summary.csv":
                    extras = set(right.columns) - set(left.columns)
                    neutral = {"cost_impact_k": 0, "cost_max_participation": None,
                               "cut_delay": 0, "cut_scale": 1, "downside": False}
                    allowed = set(neutral) | {"cost_impact_window"}
                    if extras - allowed:
                        raise AssertionError("Unexplained summary columns: " + str(extras - allowed))
                    for column in extras:
                        values = right[column].dropna()
                        if column == "cost_impact_window":
                            # The window is inactive only when impact is zero.
                            if not right["cost_impact_k"].dropna().eq(0).all():
                                raise AssertionError("Non-neutral market impact")
                        elif neutral[column] is None:
                            if not values.empty:
                                raise AssertionError("Non-neutral added parameter: " + column)
                        elif not values.eq(neutral[column]).all():
                            raise AssertionError("Non-neutral added parameter: " + column)
                        metadata_additions[column] = right[column].fillna("<unset>").tolist()
                    # Every original column and row still participates. Only the
                    # explicitly proven neutral extension metadata is aligned.
                    right = right.loc[:, left.columns]
                pd.testing.assert_frame_equal(left, right, check_exact=False,
                                              rtol=args.rtol, atol=args.atol)
                row["files"][filename] = {"reference_sha256": sha256(expected),
                                          "replay_sha256": sha256(actual), "rows": len(left),
                                          "neutral_metadata_additions": metadata_additions}
        except Exception as exc:
            row.update(success=False, error=f"{type(exc).__name__}: {exc}")
        result["experiments"].append(row)
        (out / "parity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
    result["success"] = all(row["success"] for row in result["experiments"])
    (out / "parity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({"success": result["success"], "report": str(out / "parity.json")}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
