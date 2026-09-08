#!/usr/bin/env python3
"""Install a verified immutable research input on the explicitly selected node."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

import run_frozen_research as frozen


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, required=True)
    p.add_argument("--node", choices=("cloud", "local"), required=True)
    p.add_argument("--frozen", default="frozen-controls-20260907-v3")
    p.add_argument("--apply-migration", action="store_true")
    args = p.parse_args()
    project = args.project_root.resolve()
    if not args.frozen or Path(args.frozen).name != args.frozen:
        p.error("frozen must be a snapshot directory name")
    if args.node == "cloud":
        if platform.system() != "Linux" or project != Path("/root/data/disk/quantmind/project"):
            p.error("Cloud preparation requires the confirmed cloud authority")
        if "authority=lzy-vm" not in (project.parent / "AUTHORITY").read_text():
            p.error("Data authority marker mismatch")
        runtime, role, database = project, "authority", "quantmind-db"
    else:
        if platform.system() != "Darwin" or not (project / ".local-dev/READY").is_file():
            p.error("Initialize the isolated Mac sandbox first")
        context = subprocess.check_output(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True).strip()
        if not context.startswith("unix://") or subprocess.check_output(["docker", "info", "--format", "{{.OperatingSystem}}"], text=True).strip() != "Docker Desktop":
            p.error("Local preparation requires the Mac Docker Desktop daemon")
        runtime, role, database = project / ".local-dev/project", "sandbox", "quantmind-dev-db"
    source = runtime / "results" / args.frozen
    manifest = frozen.verify(source)
    subprocess.run(["docker", "image", "inspect", manifest["image"]["Id"]], check=True, stdout=subprocess.DEVNULL)
    root = runtime / "data/research"
    root.mkdir(parents=True, exist_ok=True)
    output = root / "inputs" / args.frozen
    expected = frozen.sha256(source / "manifest.json")
    if output.exists():
        if frozen.sha256(output / "manifest.json") != expected:
            raise ValueError("Existing snapshot name refers to different input; do not overwrite it")
        frozen.verify(output)
    else:
        temporary = root / "inputs" / (args.frozen+".preparing")
        temporary.mkdir(parents=True, exist_ok=True)
        for entry in manifest["files"]:
            dest = temporary / "snapshot" / entry["path"]
            if not dest.resolve().is_relative_to((temporary / "snapshot").resolve()):
                raise ValueError("Snapshot path escaped its input directory")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or frozen.sha256(dest) != entry["sha256"]:
                shutil.copyfile(source / "snapshot" / entry["path"], dest)
        shutil.copyfile(source / "manifest.json", temporary / "manifest.json")
        frozen.verify(temporary)
        temporary.rename(output)
    data_path = str((runtime / "data").resolve())
    node_id = hashlib.sha256((role+":"+data_path).encode()).hexdigest()[:20]
    cfg = {"version": 1, "role": role, "node_id": node_id, "host_data": data_path,
        "label": "云端研究" if role == "authority" else "本地沙盒研究", "snapshot_id": args.frozen,
        "source": str(Path("/data/research/inputs") / args.frozen), "image": manifest["image"], "manifest_sha256": expected}
    if (root / "settings.json").exists() and frozen.read(root / "settings.json") != cfg:
        raise ValueError("Existing research settings differ; finish active research before switching templates")
    frozen.write(root / "settings.json", cfg)
    if args.apply_migration:
        sql = (Path(__file__).resolve().parents[1] / "data/upgrade_research_workbench_v1.sql").read_bytes()
        subprocess.run(["docker", "exec", "-i", database, "sh", "-c",
            'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], input=sql, check=True)
    print(json.dumps({"prepared": True, "node_id": node_id, "role": role, "snapshot": args.frozen,
                      "output": str(output), "migration_applied": args.apply_migration}, ensure_ascii=False))


if __name__ == "__main__":
    main()
