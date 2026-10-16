#!/usr/bin/env python3
"""Prepare immutable inputs, run owner-bound paper ledgers, or tick sole-source QA."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.simulation.services.frozen_paper_service import (  # noqa: E402
    ledger_root, paper_runtime, scoped_ledger_root, validate_bindings,
)


def daily_options(parser):
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--market-pointer", default="RESEARCH_CURRENT.json")
    parser.add_argument("--fundamental-pointer", default="CURRENT.json")
    parser.add_argument("--prepared-root", type=Path)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--registry-bindings", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path)
    parser.add_argument("--source-ledgers", type=Path)
    parser.add_argument("--account", action="append")


def install_launchd(args):
    """Render only this paper job; no launchctl, service switching or host dependencies."""
    container = bool(args.container)
    repo = Path(args.container_repo) if container else ROOT
    archive = args.archive_root or (Path("/data/tushare") if container else
                                    Path.home() / "Library/Application Support/QuantMind/tushare")
    artifacts = args.artifact_root or repo / "output"
    base = args.ledger_root or artifacts / "ashare-paper"
    readiness = args.readiness or (Path("/run/quantmind-market-source/paper-readiness.json") if container else
        Path(os.environ.get("ASHARE_PAPER_READINESS", str(Path.home() /
             "Library/Application Support/QuantMind/market-source/paper-readiness.json"))))
    command = [str(repo / "scripts/ashare_paper_daily.py"), "tick",
        "--readiness", str(readiness), "--archive-root", str(archive),
        "--artifact-root", str(artifacts), "--market-pointer", args.market_pointer,
        "--fundamental-pointer", args.fundamental_pointer,
        "--prepared-root", str(args.prepared_root or base / "prepared"),
        "--ledger-root", str(base), "--user-id", args.user_id, "--tenant-id", args.tenant_id,
        "--registry-bindings", str(args.registry_bindings),
        "--source-ledgers", str(args.source_ledgers or artifacts / "ashare-takeover/trees/ashare-lab-paper/paper")]
    for name in args.account or []:
        command.extend(["--account", name])
    if container:
        docker = shutil.which(str(args.docker_executable) if args.docker_executable else "docker")
        if not docker:
            raise ValueError("Docker executable unavailable; supply --docker-executable")
        command = [docker, "exec", args.container, args.container_python, *command]
    else:
        command = [str(args.python or sys.executable), *command]
    template = plistlib.loads((ROOT / "deploy/com.quantmind.ashare-paper.plist").read_bytes())
    template["ProgramArguments"] = command
    template["WorkingDirectory"] = str(ROOT)
    template["StandardOutPath"] = str(ROOT / "logs/ashare-paper.log")
    template["StandardErrorPath"] = str(ROOT / "logs/ashare-paper-error.log")
    out = args.out.expanduser().resolve()
    if out.exists() and plistlib.loads(out.read_bytes()).get("Label") != template["Label"]:
        raise ValueError("Refusing to replace an unrelated launchd job")
    content = plistlib.dumps(template, sort_keys=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    if not out.exists() or out.read_bytes() != content:
        with tempfile.NamedTemporaryFile(dir=out.parent, prefix=".ashare-paper-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, out)
            finally:
                temporary.unlink(missing_ok=True)
    print(json.dumps({"plist": str(out), "program_arguments": command,
                      "activation": "not_started; deployment owner controls launchctl"}, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-release", help="Consume explicit real archive releases")
    prepare.add_argument("--market-manifest", type=Path, required=True)
    prepare.add_argument("--fundamental-manifest", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--usable-date", required=True)
    prepare.add_argument("--replay-start", default="2026-10-14")
    prepare.add_argument("--cb", type=Path, default=ROOT / "output/ashare-takeover/trees/ashare-lab-ideas-cb/data/extra")
    prepare.add_argument("--futures", type=Path, default=ROOT / "output/ashare-takeover/trees/ashare-lab-ideas-cta/data/extra/i9_futures")
    freeze = commands.add_parser("freeze-inputs", help="Hash prebuilt real inputs into a fresh manifest")
    freeze.add_argument("--out", type=Path, required=True)
    freeze.add_argument("--version", required=True)
    freeze.add_argument("--usable-date", required=True)
    freeze.add_argument("--replay-start", default="2026-10-14")
    for name in ("panel", "fundamentals", "calendar"):
        freeze.add_argument(f"--{name}", type=Path, required=True)
    for name in ("etf", "cb", "futures"):
        freeze.add_argument(f"--{name}", type=Path)
    reconcile = commands.add_parser("reconcile-inception", help="Independently prove original pending signals without ledger writes")
    reconcile.add_argument("--source-ledgers", type=Path, default=ROOT / "output/ashare-takeover/trees/ashare-lab-paper/paper")
    reconcile.add_argument("--manifest", type=Path, help="Compare active runtime using this prepared input manifest")
    reconcile.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run", help="Explicit immutable backfill, not the recurring daily scheduler")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--user-id", required=True)
    run.add_argument("--tenant-id", default="default")
    run.add_argument("--registry-bindings", type=Path, required=True)
    run.add_argument("--ledger-root", type=Path, default=ledger_root())
    run.add_argument("--source-ledgers", type=Path, default=ROOT / "output/ashare-takeover/trees/ashare-lab-paper/paper")
    run.add_argument("--account", action="append")
    run.add_argument("--observation-mode", choices=("replay", "daily"), default="replay")
    tick = commands.add_parser("tick", help="Consume sole-source readiness and advance newly ready versions")
    daily_options(tick)
    install = commands.add_parser("install-launchd", help="Render this paper launchd job without activating it")
    daily_options(install)
    install.add_argument("--out", type=Path, default=Path.home() / "Library/LaunchAgents/com.quantmind.ashare-paper.plist")
    install.add_argument("--container")
    install.add_argument("--docker-executable", type=Path)
    install.add_argument("--container-python", default="python")
    install.add_argument("--container-repo", default="/app")
    install.add_argument("--python", type=Path)
    args = parser.parse_args(argv)
    # Installation is standard-library only; the host need not contain pandas,
    # SQLAlchemy or the backend runtime when the actual job uses docker exec.
    if args.command == "install-launchd":
        return install_launchd(args)
    runtime = paper_runtime()
    if args.command == "prepare-release":
        from ashare_lab.paper_inputs import prepare_release
        path = prepare_release(args.market_manifest, args.fundamental_manifest, args.out,
                               args.usable_date, args.replay_start, args.cb, args.futures)
        print(json.dumps({"manifest": str(path), "sha256": runtime.file_hash(path)}))
        return 0
    if args.command == "freeze-inputs":
        import pandas as pd
        pd.Timestamp(args.usable_date)
        pd.Timestamp(args.replay_start)
        spec = {"version": args.version, "usable_date": args.usable_date,
                "replay_start": args.replay_start, "files": {}, "asset_inputs": {},
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        for name in ("panel", "fundamentals", "calendar", "etf", "cb", "futures"):
            path = getattr(args, name)
            if path is None:
                continue
            path = path.resolve(strict=True)
            if name in ("panel", "fundamentals", "calendar"):
                spec[name] = str(path)
            else:
                accounts = {"etf": ("i7_turn_of_month", "s1_invvol_etf"),
                            "cb": ("cb_double_low",), "futures": ("cta_combined", "cta_trend")}[name]
                spec["asset_inputs"].update({account: str(path) for account in accounts})
            files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
            if not files:
                parser.error(f"Empty {name} directory")
            for file in files:
                spec["files"][str(file.resolve())] = runtime.file_hash(file)
        content = runtime.json_bytes(spec)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"manifest": str(args.out.resolve()), "sha256": runtime.digest(content)}))
        return 0
    if args.command == "reconcile-inception":
        from ashare_lab.paper_inception import reconcile_inception
        if args.out.exists():
            raise FileExistsError(f"Refusing to replace inception evidence: {args.out}")
        report = reconcile_inception(args.source_ledgers.resolve().parent,
                                     args.manifest.resolve() if args.manifest else None)
        content = runtime.json_bytes(report)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"evidence": str(args.out.resolve()), "sha256": runtime.digest(content),
                          "matched": report["matched"],
                          "accounts": {name: row["matched"] for name, row in report["accounts"].items()}},
                         ensure_ascii=False, indent=2))
        return int(not report["matched"])
    bindings = json.loads(args.registry_bindings.read_text())
    names = args.account or runtime.ACCOUNTS
    asyncio.run(validate_bindings(bindings, args.user_id, args.tenant_id, names))
    base = args.ledger_root or ledger_root()
    root = scoped_ledger_root(args.user_id, args.tenant_id, base.resolve())
    if args.command == "tick":
        from ashare_lab.paper_tick import tick as tick_once
        archive = args.archive_root or Path.home() / "Library/Application Support/QuantMind/tushare"
        artifacts = args.artifact_root or ROOT / "output"
        readiness = args.readiness or Path(os.environ.get("ASHARE_PAPER_READINESS", str(Path.home() /
            "Library/Application Support/QuantMind/market-source/paper-readiness.json")))
        report = tick_once(readiness, archive, artifacts, args.market_pointer, args.fundamental_pointer,
            args.prepared_root or base / "prepared", root,
            args.source_ledgers or ROOT / "output/ashare-takeover/trees/ashare-lab-paper/paper", bindings, names)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 75 if report["state"] in ("pending", "partial") else int(report["state"] == "blocked")
    reports = runtime.update(root, args.source_ledgers.resolve(), args.manifest.resolve(), names,
                             mode=args.observation_mode, bindings=bindings)
    print(json.dumps({"ledger_root": str(root), "accounts": reports}, ensure_ascii=False, indent=2))
    return int(any(item["state"] == "blocked" for item in reports.values()))


if __name__ == "__main__":
    raise SystemExit(main())
