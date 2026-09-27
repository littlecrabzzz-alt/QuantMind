#!/usr/bin/env python3
"""Manage the local coordinator; never prints credentials or full configuration."""

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from controller import Client

p = argparse.ArgumentParser()
p.add_argument("action", choices=["install", "status", "start", "stop", "uninstall"])
p.add_argument(
    "--config",
    type=Path,
    default=Path.home()
    / "Library/Application Support/QuantMind/continuous-research/runtime.json",
)
a = p.parse_args()
label = "com.quantmind.glm-continuous-research"
target = f"gui/{os.getuid()}"
plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
if a.action == "install":
    a.config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            str(Path(__file__).with_name("controller.py")),
            "--config",
            str(a.config),
        ],
        "WorkingDirectory": str(a.config.parent),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(a.config.parent / "controller.log"),
        "StandardErrorPath": str(a.config.parent / "controller-error.log"),
    }
    if plist.exists() and plistlib.loads(plist.read_bytes()) != values:
        raise SystemExit(
            "existing launch configuration differs; inspect it before replacement"
        )
    plist.write_bytes(plistlib.dumps(values))
    os.chmod(plist, 0o600)
    existing = subprocess.run(
        ["launchctl", "print", target + "/" + label], capture_output=True
    )
    if existing.returncode:
        subprocess.run(["launchctl", "bootstrap", target, str(plist)], check=True)
    print("Local coordinator installed; programme start/stop is controlled separately.")
elif a.action == "uninstall":
    subprocess.run(["launchctl", "bootout", target + "/" + label], check=False)
    if plist.exists():
        plist.unlink()
    print("Coordinator removed; platform research records and strategies retained.")
else:
    api = Client(a.config)
    if a.action in ("start", "stop"):
        state = api.call(a.action)
        print(
            json.dumps(
                {
                    "id": state["id"],
                    "desired": state["desired"],
                    "status": state["status"],
                },
                ensure_ascii=False,
            )
        )
    else:
        import requests

        s = requests.Session()
        s.trust_env = False
        r = s.get(
            api.cfg["engine_url"] + "/api/v1/continuous-research",
            headers={"Authorization": "Bearer " + api.cfg["access_token"]},
            timeout=20,
        )
        r.raise_for_status()
        v = next(x for x in r.json() if x["id"] == api.program)
        print(
            json.dumps(
                {
                    "id": v["id"],
                    "status": v["status"],
                    "desired": v["desired"],
                    "heartbeat_stale": v["heartbeat_stale"],
                    "quota": v["quota"],
                    "tasks": [
                        {
                            "id": t["id"],
                            "topic": t["topic"],
                            "status": t["status"],
                            "step": t["step"],
                            "attempts": t["attempts"],
                            "experiments": len(t["experiments"]),
                            "reports": len(t["reports"]),
                            "usage": t["usage"],
                        }
                        for t in v["tasks"].values()
                    ],
                },
                ensure_ascii=False,
            )
        )
