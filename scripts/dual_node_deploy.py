#!/usr/bin/env python3
"""Run the prepared migration through cutover, access checks, and offline snapshot.

One process owns the deployment lock. Retries only transient preseed transport
errors. A failed cutover stays stopped for inspection rather than risking two masters.
"""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request

from dual_node_sync import PROJECT, topology

SETTINGS = topology()
SSH = SETTINGS["QM_SSH_TARGET"]
ROOT = SETTINGS["QM_REMOTE_ROOT"]
REMOTE_PROJECT = SETTINGS["QM_REMOTE_PROJECT"]
STATE = PROJECT / "logs/dual-node-deploy.json"


def stage(name, **extra):
    value = {"stage": name, "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "pid": os.getpid(), **extra}
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(STATE)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run(*args):
    subprocess.run(args, cwd=PROJECT, check=True)


def remote(command):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SSH, command], cwd=PROJECT)


def ready():
    check = '''import json, subprocess, sys
names = ["quantmind", "quantmind-db", "quantmind-redis", "quantmind-celery",
         "quantmind-celery-beat", "quantmind-data-gateway", "quantmind-huntly",
         "quantmind-rsshub", "qwenpaw", "quantmind-web"]
items = json.loads(subprocess.check_output(["docker", "inspect", *names]))
sys.exit(0 if all(item["State"]["Running"] and
    item["State"].get("Health", {}).get("Status", "healthy") == "healthy"
    for item in items) else 1)
'''
    for attempt in range(60):
        result = remote("sudo -n python3 -c " + shlex.quote(check) + " && "
                        "curl -fsS http://127.0.0.1:18000/health >/dev/null && "
                        "sudo -n docker exec qwenpaw python -c "
                        "'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8088/health\", timeout=10)' >/dev/null")
        if result.returncode == 0:
            return
        time.sleep(5)
    raise RuntimeError("Cloud API or QuantBot did not become healthy; inspect containers")


def deploy(wait_for):
    if wait_for:
        stage("waiting_for_existing_preseed", wait_pid=wait_for)
        def signature():
            return subprocess.run(["ps", "-p", str(wait_for), "-o", "lstart="], text=True, capture_output=True).stdout.strip()
        original = signature()
        while original and signature() == original:
            time.sleep(30)
    authority = remote("sudo -n test -f " + ROOT + "/AUTHORITY")
    while authority.returncode == 255:
        stage("waiting_for_network")
        time.sleep(30)
        authority = remote("sudo -n test -f " + ROOT + "/AUTHORITY")
    if authority.returncode not in (0, 1):
        authority.check_returncode()
    if authority.returncode == 1:
        stage("preseed")
        while True:
            result = subprocess.run(["bash", "scripts/dual-node.sh", "preseed"], cwd=PROJECT)
            if result.returncode in (0, 24):  # vanished live temp files are reconciled at cutover
                break
            if result.returncode not in (12, 30, 35, 255):
                result.check_returncode()
            stage("preseed_waiting_for_network", returncode=result.returncode)
            time.sleep(30)
        stage("cutover")
        while True:
            try:
                run("bash", "scripts/dual-node-cutover.sh")
                break
            except subprocess.CalledProcessError as exc:
                if exc.returncode != 75:
                    raise
                stage("cutover_waiting_for_idle_research")
                time.sleep(30)
    stage("cloud_health")
    ready()
    stage("installing_local_tunnel")
    run("bash", "scripts/dual-node.sh", "install-tunnel")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(30):
        try:
            with opener.open("http://127.0.0.1:18080/health", timeout=5) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(2)
    else:
        raise RuntimeError("Local SSH tunnel is not serving the cloud web entry")
    stage("creating_cloud_snapshot")
    while True:
        # The cloud must finish thawing writers even if the Mac disconnects.
        result = remote("sudo -n systemd-run --unit=quantmind-snapshot-create --wait --collect "
                        "--property=RequiresMountsFor=/root/data/disk /usr/bin/python3 " +
                        REMOTE_PROJECT + "/scripts/dual_node_snapshot.py create")
        if result.returncode != 75:
            result.check_returncode()
            break
        stage("snapshot_waiting_for_idle_research")
        time.sleep(30)
    stage("pulling_verified_offline_snapshot")
    run("python3", "scripts/dual_node_snapshot.py", "pull")
    ready()
    stage("complete", public_url="http://106.54.20.20:" + SETTINGS["QM_WEB_PORT"],
          local_url="http://127.0.0.1:18080")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-for", type=int, help="Existing preseed process to join before proceeding")
    args = parser.parse_args()
    STATE.parent.mkdir(exist_ok=True)
    os.umask(0o077)
    with (STATE.parent / "dual-node-deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            deploy(args.wait_for)
        except Exception as exc:
            stage("failed", error=str(exc))
            raise
