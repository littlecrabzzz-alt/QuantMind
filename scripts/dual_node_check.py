#!/usr/bin/env python3
"""Read-only development preflight. Offline/drift is a failure, never a failover."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import urllib.request

from dual_node_sync import PROJECT, topology

SETTINGS = topology()
CONTAINERS = ["quantmind", "quantmind-db", "quantmind-redis", "quantmind-celery",
              "quantmind-celery-beat", "quantmind-data-gateway", "quantmind-huntly",
              "quantmind-rsshub", "qwenpaw"]


def output(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def node(role):
    sync = json.loads(output(sys.executable, str(PROJECT / "scripts/dual_node_sync.py"),
                             role, "--content-hash"))
    names = CONTAINERS + (["quantmind-web"] if role == "cloud" else [])
    containers = json.loads(output("docker", "inspect", *names))
    if role == "cloud":
        root = Path(SETTINGS["QM_REMOTE_ROOT"])
        require(os.geteuid() == 0 and PROJECT == Path(SETTINGS["QM_REMOTE_PROJECT"]),
                "Cloud check must run in the configured authority checkout")
        require("authority=lzy-vm" in (root / "AUTHORITY").read_text(), "Wrong data authority")
        require(output("findmnt", "-n", "-o", "UUID", "-T", str(root)) == SETTINGS["QM_DISK_UUID"],
                "Wrong SSD mount")
        require(output("systemctl", "is-active", "quantmind-stack") == "active", "Stack service inactive")
        require(output("systemctl", "is-enabled", "quantmind-stack") == "enabled", "Stack boot entry disabled")
        for item in containers:
            name = item["Name"]
            require(item["State"]["Running"], f"Stopped cloud service: {name}")
            require(item["State"].get("Health", {}).get("Status", "healthy") == "healthy",
                    f"Unhealthy cloud service: {name}")
            env = dict(v.split("=", 1) for v in item["Config"]["Env"] if "=" in v)
            if name in ("/quantmind", "/quantmind-celery", "/qwenpaw"):
                require(env.get("ENABLE_REAL_TRADING") == "false", "Real trading must remain disabled")
            if name not in ("/quantmind", "/quantmind-web"):
                require(not item["HostConfig"].get("PortBindings"), f"Private service published: {name}")
            if name == "/quantmind":
                require(item["HostConfig"]["Memory"] == 12 * 1024**3, "Main memory limit drift")
        output("docker", "exec", "quantmind", "python", "-S", "/app/scripts/check_cloud_health.py")
        snapshot = (root / "snapshots/latest").resolve()
    else:
        require((PROJECT / "docker-compose.override.yml").read_bytes() ==
                (PROJECT / "deploy/compose.mac-client.yml").read_bytes(), "Mac Compose guard missing or changed")
        require(not output("docker", "compose", "--env-file", str(PROJECT / ".env.local"),
                           "--project-directory", str(PROJECT), "config", "--services"),
                "Bare local Compose can still start services")
        for item in containers:
            require(not item["State"]["Running"] and item["HostConfig"]["RestartPolicy"]["Name"] == "no",
                    f"Old local service is running or can auto-restart: {item['Name']}")
        snapshot = (PROJECT / "logs/cloud-snapshots/latest").resolve()
    require((snapshot / "COMPLETE").is_file(), "No completed offline snapshot")
    return {"role": role, "head": output("git", "-C", str(PROJECT), "rev-parse", "HEAD"),
            "branch": output("git", "-C", str(PROJECT), "branch", "--show-current"),
            "snapshot": snapshot.name, "sync": sync}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=("mac", "cloud"))
    args = parser.parse_args()
    if args.node:
        print(json.dumps(node(args.node), indent=2))
        return
    local = node("mac")
    command = "sudo -n python3 " + shlex.quote(SETTINGS["QM_REMOTE_PROJECT"] + "/scripts/dual_node_check.py") + " --node cloud"
    remote = json.loads(output("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                               SETTINGS["QM_SSH_TARGET"], command))
    for key in ("head", "branch", "snapshot"):
        require(local[key] == remote[key], f"Two-node {key} differs; resolve before development")
    for key in ("contentFiles", "contentDigest"):
        require(local["sync"][key] == remote["sync"][key], "Working trees differ; wait for sync or resolve conflicts")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in ("http://127.0.0.1:18080/health", "http://127.0.0.1:8000/health"):
        with opener.open(url, timeout=15) as response:
            require(response.status == 200, "Cloud tunnel is not healthy")
    print(json.dumps({"status": "passed", "head": local["head"],
                      "source_files": local["sync"]["contentFiles"],
                      "source_digest": local["sync"]["contentDigest"],
                      "snapshot": local["snapshot"], "data_authority": "lzy-vm",
                      "local_writers": "stopped; restart=no"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"PRECHECK FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
