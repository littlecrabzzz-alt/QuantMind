#!/usr/bin/env python3
"""Audit/reconcile ONLY quantmind-code; credentials never leave Syncthing config."""
import argparse
import hashlib
import json
import pathlib
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PROJECT = pathlib.Path(__file__).resolve().parents[1]


def content_digest(project, nodes):
    """Hash the complete advertised sync tree without printing secret contents."""
    records = []

    def walk(items, parent=pathlib.PurePosixPath()):
        for node in items:
            name = node["name"]
            if pathlib.PurePosixPath(name).name != name or name in (".", ".."):
                raise ValueError("Invalid sync path")
            relative = parent / name
            path = project / relative
            if "DIRECTORY" in node["type"]:
                walk(node.get("children", []), relative)
                continue
            before = path.lstat()
            h = hashlib.sha256()
            if path.is_symlink():
                h.update(os.readlink(path).encode())
            else:
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(block)
            after = path.lstat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f"Code changed during verification: {relative}")
            if ".sync-conflict-" in name:
                raise RuntimeError(f"Resolve sync conflict before deployment: {relative}")
            records.append([str(relative), node["type"], h.hexdigest()])

    walk(nodes)
    return {"contentFiles": len(records), "contentDigest": hashlib.sha256(
        json.dumps(sorted(records), ensure_ascii=False).encode()).hexdigest()}


def topology():
    return dict(line.split("=", 1) for line in
                (PROJECT / "deploy/dual-node.env").read_text().splitlines()
                if line and not line.startswith("#"))


def desired(role, settings):
    return {
        "id": settings["QM_CODE_FOLDER"], "label": "QuantMind code",
        "path": str(PROJECT) if role == "mac" else settings["QM_REMOTE_PROJECT"],
        "type": "sendreceive", "rescanIntervalS": 3600,
        "fsWatcherEnabled": True, "fsWatcherDelayS": 10,
        "ignorePerms": False, "paused": False,
        "minDiskFree": {"value": 10, "unit": "%"},
        "versioning": {"type": "simple", "params": {"keep": "10"},
                       "cleanupIntervalS": 3600, "fsPath": "", "fsType": "basic"},
        "maxConflicts": 10,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("mac", "cloud"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--content-hash", action="store_true", help="Hash all indexed source/config files, including ignored Git secrets")
    args = parser.parse_args()
    settings = topology()
    cfg_path = (pathlib.Path.home() / "Library/Application Support/Syncthing/config.xml"
                if args.role == "mac" else
                pathlib.Path("/root/.local/state/syncthing/config.xml"))
    cfg = ET.parse(cfg_path).getroot()
    base = "http://" + cfg.findtext("gui/address")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(endpoint, body=None, method=None):
        request = urllib.request.Request(base + "/rest/" + endpoint,
            data=None if body is None else json.dumps(body).encode(),
            headers={"X-API-Key": cfg.findtext("gui/apikey"),
                     "Content-Type": "application/json"}, method=method)
        with opener.open(request, timeout=30) as response:
            payload = response.read()
            return json.loads(payload) if payload else None

    endpoint = "config/folders/" + settings["QM_CODE_FOLDER"]
    current = api(endpoint)
    expected = desired(args.role, settings)
    # Keep versioning extensions introduced by newer Syncthing versions.
    expected["versioning"] = {**current.get("versioning", {}), **expected["versioning"]}
    drift = {key: {"actual": current.get(key), "expected": value}
             for key, value in expected.items() if current.get(key) != value}
    expected_devices = {settings["QM_MAC_DEVICE"], settings["QM_CLOUD_DEVICE"]}
    if {device["deviceID"] for device in current["devices"]} != expected_devices:
        raise SystemExit("Unexpected devices: refuse automatic sharing changes")
    if args.apply and drift:
        api(endpoint, {**current, **expected}, "PUT")
        current = api(endpoint)
        drift = {key: {"actual": current.get(key), "expected": value}
                 for key, value in expected.items() if current.get(key) != value}
    ignore_ok = (PROJECT / ".stignore").read_text().strip() == "#include .sync-code-ignore"
    state = api("db/status?folder=" + urllib.parse.quote(settings["QM_CODE_FOLDER"]))
    peer = settings["QM_CLOUD_DEVICE" if args.role == "mac" else "QM_MAC_DEVICE"]
    completion = api("db/completion?" + urllib.parse.urlencode(
        {"folder": settings["QM_CODE_FOLDER"], "device": peer}))
    connected = api("system/connections")["connections"].get(peer, {}).get("connected", False)
    fingerprints = content_digest(PROJECT, api("db/browse?" + urllib.parse.urlencode(
        {"folder": settings["QM_CODE_FOLDER"], "levels": -1}))) if args.content_hash else {}
    print(json.dumps({"role": args.role, "drift": drift, "ignore_include_ok": ignore_ok,
        "state": state.get("state"), "errors": state.get("errors", 0),
        "localFiles": state.get("localFiles"), "localBytes": state.get("localBytes"),
        "peerCompletion": completion.get("completion"),
        "peerNeedItems": completion.get("needItems"), "peerConnected": connected,
        **fingerprints}, indent=2))
    return 1 if (drift or not ignore_ok or state.get("errors", 0) or
                 not connected or state.get("state") != "idle" or
                 completion.get("completion") != 100 or completion.get("needItems")) else 0


if __name__ == "__main__":
    sys.exit(main())
