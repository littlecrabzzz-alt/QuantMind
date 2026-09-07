#!/usr/bin/env python3
"""Audit/reconcile ONLY quantmind-code; credentials never leave Syncthing config."""
import argparse
import json
import pathlib
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PROJECT = pathlib.Path(__file__).resolve().parents[1]


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
    print(json.dumps({"role": args.role, "drift": drift, "ignore_include_ok": ignore_ok,
        "state": state.get("state"), "errors": state.get("errors", 0),
        "localFiles": state.get("localFiles"), "localBytes": state.get("localBytes"),
        "peerCompletion": completion.get("completion"),
        "peerNeedItems": completion.get("needItems")}, indent=2))
    return 1 if drift or not ignore_ok or state.get("errors", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
