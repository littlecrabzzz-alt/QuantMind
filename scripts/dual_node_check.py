#!/usr/bin/env python3
"""Read-only development preflight. Offline/drift is a failure, never a failover."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
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
    if role == "mac":
        require(sys.platform == "darwin", "Run the two-node check on the Mac host")
        require(not os.getenv("DOCKER_HOST"), "Unset DOCKER_HOST for local verification")
        endpoint = output("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        require(endpoint.startswith("unix://" + str(Path.home() / ".docker") + "/")
                or endpoint == "unix:///var/run/docker.sock", "Non-local Docker endpoint")
        require(output("docker", "info", "--format", "{{.OperatingSystem}}") == "Docker Desktop",
                "Expected local Docker Desktop daemon")
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
                require(item["HostConfig"]["PortBindings"] == {
                    "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]},
                    "Internal API port exposure drift")
            if name == "/quantmind-web":
                require(item["HostConfig"]["PortBindings"] == {
                    "80/tcp": [{"HostIp": "", "HostPort": SETTINGS["QM_WEB_PORT"]}]},
                    "Public web port drift")
        volume_names = sorted({m["Name"] for c in containers for m in c["Mounts"] if m["Type"] == "volume"})
        for volume in json.loads(output("docker", "volume", "inspect", *volume_names)):
            device = (volume.get("Options") or {}).get("device", "")
            require(Path(device).is_absolute() and Path(device).resolve().is_relative_to(root / "volumes"),
                    f"Persistent volume is outside the SSD: {volume['Name']}")
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
        mode = "cloud-tunnel"
        probe = subprocess.run(("docker", "inspect", "quantmind-dev"), text=True, capture_output=True)
        development = json.loads(probe.stdout)[0] if probe.returncode == 0 else None
        if development and development["State"]["Running"]:
            env = dict(v.split("=", 1) for v in development["Config"]["Env"] if "=" in v)
            require(env.get("QM_NODE_ROLE") == "sandbox", "Local backend is not marked as a sandbox")
            require(development["HostConfig"]["RestartPolicy"]["Name"] == "no",
                    "Local sandbox can restart automatically")
            sources = {m["Destination"]: m["Source"] for m in development["Mounts"] if m["Type"] == "bind"}
            for destination in ("/data", "/app/db", "/app/models", "/app/logs", "/app/user_pools_local"):
                require(Path(sources[destination]).resolve().is_relative_to(PROJECT / ".local-dev/project"),
                        f"Local sandbox mount escaped isolation: {destination}")
            require(env.get("HOST_RUNTIME_PATH") == str(PROJECT / ".local-dev/project"),
                    "Local child jobs lack the sandbox runtime root; recreate the sandbox containers")
            validate_sandbox_snapshot(PROJECT)
            mode = "local-sandbox"
    require((snapshot / "COMPLETE").is_file(), "No completed offline snapshot")
    return {"role": role, "head": output("git", "-C", str(PROJECT), "rev-parse", "HEAD"),
            "branch": output("git", "-C", str(PROJECT), "branch", "--show-current"),
            "snapshot": snapshot.name, "sync": sync, "mode": mode if role == "mac" else "authority",
            "sandbox_snapshot": (PROJECT / ".local-dev/SNAPSHOT_ID").read_text().strip()
                if role == "mac" and (PROJECT / ".local-dev/SNAPSHOT_ID").is_file() else None}


def validate_sandbox_snapshot(project):
    ident = (project / ".local-dev/SNAPSHOT_ID").read_text().strip()
    require(ident.startswith("snapshot-") and Path(ident).name == ident,
            "Invalid fixed sandbox snapshot ID")
    require((project / "logs/cloud-snapshots" / ident / "COMPLETE").is_file(),
            "The fixed sandbox snapshot is missing or incomplete")
    return ident


def align_git(local, remote, source_role):
    import dual_node_git
    source, destination = (local, remote) if source_role == "mac" else (remote, local)
    require(local["branch"] == remote["branch"], "Branches differ; resolve explicitly before handoff")
    for key in ("contentFiles", "contentDigest"):
        require(local["sync"][key] == remote["sync"][key], "Working trees differ; refusing Git alignment")
    if source["head"] == destination["head"]:
        return
    require(sys.platform == "darwin", "Git handoff is coordinated from the Mac host")
    helper = SETTINGS["QM_REMOTE_PROJECT"] + "/scripts/dual_node_git.py"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SETTINGS["QM_SSH_TARGET"]]
    with tempfile.TemporaryFile() as bundle:
        if source_role == "mac":
            dual_node_git.write_bundle(source["head"], destination["head"], bundle)
        else:
            command = shlex.join(["sudo", "-n", "python3", helper, "bundle", source["head"], destination["head"]])
            subprocess.run([*ssh, command], check=True, stdout=bundle)
        bundle.seek(0)
        args = [destination["head"], destination["branch"], source["head"], local["sync"]["contentDigest"]]
        if source_role == "mac":
            command = shlex.join(["sudo", "-n", "python3", helper, "receive", *args, "cloud"])
            subprocess.run([*ssh, command], check=True, stdin=bundle)
        else:
            dual_node_git.receive_bundle(*args, "mac", bundle)
    print("Git metadata fast-forwarded; synchronized working files retained.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=("mac", "cloud"))
    parser.add_argument("--align-git", choices=("mac", "cloud"), help="Explicit source of a metadata-only fast-forward; never rewrites working files")
    args = parser.parse_args()
    require(not (args.node and args.align_git), "Use --align-git from the Mac two-node entry")
    if args.node:
        print(json.dumps(node(args.node), indent=2))
        return
    local = node("mac")
    command = "sudo -n python3 " + shlex.quote(SETTINGS["QM_REMOTE_PROJECT"] + "/scripts/dual_node_check.py") + " --node cloud"
    remote = json.loads(output("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                               SETTINGS["QM_SSH_TARGET"], command))
    if args.align_git:
        align_git(local, remote, args.align_git)
        local = node("mac")
        remote = json.loads(output("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                                   SETTINGS["QM_SSH_TARGET"], command))
    for key in ("head", "branch", "snapshot"):
        require(local[key] == remote[key], f"Two-node {key} differs; resolve before development")
    for key in ("contentFiles", "contentDigest"):
        require(local["sync"][key] == remote["sync"][key], "Working trees differ; wait for sync or resolve conflicts")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    urls = (("http://127.0.0.1:8000/health",) if local["mode"] == "local-sandbox" else
            ("http://127.0.0.1:18080/health", "http://127.0.0.1:8000/health"))
    for url in urls:
        with opener.open(url, timeout=15) as response:
            require(response.status == 200, "Cloud tunnel is not healthy")
    print(json.dumps({"status": "passed", "head": local["head"],
                      "source_files": local["sync"]["contentFiles"],
                      "source_digest": local["sync"]["contentDigest"],
                      "snapshot": local["snapshot"], "data_authority": "lzy-vm",
                      "mac_mode": local["mode"],
                      "sandbox_snapshot": local["sandbox_snapshot"],
                      "local_writers": "old authority stopped; restart=no"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"PRECHECK FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
