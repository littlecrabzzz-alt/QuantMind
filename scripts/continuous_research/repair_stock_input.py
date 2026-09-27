#!/usr/bin/env python3
"""Create an immutable derivative of a stock snapshot with missing Python packages.

Original data/config/code files are verified and never changed. Existing Python
files must match this checkout before missing siblings may be added.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_frozen_research as frozen


def require_parent_files(original, derived):
    actual = {e["path"]: e["sha256"] for e in derived["files"]}
    if any(actual.get(e["path"]) != e["sha256"] for e in original["files"]):
        raise ValueError("parent_data_or_code_changed_during_clone")


def repair(source, target, root):
    original = frozen.verify(source)
    parent_hash = frozen.sha256(source / "manifest.json")
    if target.exists():
        result = frozen.verify(target)
        if result.get("parent_manifest_sha256") != parent_hash:
            raise ValueError("different_parent_snapshot")
        require_parent_files(original, result)
        return result
    additions = []
    for file in sorted((root / "docker/training").rglob("*.py")):
        relative = Path("code") / file.relative_to(root)
        old = source / "snapshot" / relative
        if old.exists():
            if frozen.sha256(file) != frozen.sha256(old):
                raise ValueError("existing_training_source_mismatch: " + str(relative))
        else:
            additions.append((file, relative))
    if not additions:
        raise ValueError("no_missing_dependencies")
    if sys.platform == "darwin":
        subprocess.run(["cp", "-cR", str(source), str(target)], check=True)
    else:
        shutil.copytree(source, target)
    for file, relative in additions:
        dest = target / "snapshot" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, dest)
    files = [
        {
            "path": p.relative_to(target / "snapshot").as_posix(),
            "sha256": frozen.sha256(p),
            "bytes": p.stat().st_size,
        }
        for p in sorted((target / "snapshot").rglob("*"))
        if p.is_file()
    ]
    result = {
        **original,
        "files": files,
        "total_bytes": sum(x["bytes"] for x in files),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "parent_manifest_sha256": parent_hash,
        "repair": {
            "kind": "missing_training_python_dependencies",
            "added_files": [p.as_posix() for _, p in additions],
            "dependency_source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    }
    require_parent_files(original, result)
    frozen.write(target / "manifest.json", result)
    frozen.verify(target)
    if frozen.sha256(source / "manifest.json") != parent_hash:
        raise ValueError("parent_changed")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--snapshot", default="research-data-priority-20260925-deps-v2")
    a = p.parse_args()
    if Path(a.snapshot).name != a.snapshot:
        raise ValueError("invalid_snapshot_id")
    root = Path(__file__).resolve().parents[2]
    data = a.runtime / "data/research"
    settings = frozen.read(data / "settings.json")
    source = a.runtime / "data" / Path(settings["source"]).relative_to("/data")
    target = data / "inputs" / a.snapshot
    result = repair(source, target, root)
    override = {
        **settings,
        "snapshot_id": a.snapshot,
        "source": "/data/research/inputs/" + a.snapshot,
        "manifest_sha256": frozen.sha256(target / "manifest.json"),
    }
    frozen.write(data / "continuous-stock-settings.json", override)
    print(
        json.dumps(
            {
                "snapshot_id": a.snapshot,
                "manifest_sha256": override["manifest_sha256"],
                "files": len(result["files"]),
                "added": len(result["repair"]["added_files"]),
                "parent_manifest_sha256": result["parent_manifest_sha256"],
            },
            ensure_ascii=False,
        )
    )
