"""Offline checks for the cloud Tushare worker drain guard."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = "celery@aaaaaaaaaaaa"

FAKE = r"""#!PYTHON
import json, os, pathlib, sys
p = pathlib.Path(os.environ["FAKE_STATE"])
s = json.loads(p.read_text())
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
s["calls"].append([name, *args])
out, rc = "", 0
if name == "id":
    out = "0"
elif name == "hostname":
    out = s.get("host", "VM-0-5-ubuntu")
elif name == "findmnt":
    out = "fixture-disk"
elif name == "docker":
    if args[0] == "compose":
        if "ps" in args and "--status" not in args:
            out = "aaaaaaaaaaaa"
        elif "ps" in args and "--status" in args:
            out = "" if s.get("worker_stopped") else "aaaaaaaaaaaa"
        elif "stop" in args and args[-1] == "celery-beat":
            s["beat_stopped"] = True
        elif "stop" in args and args[-1] == "tushare-worker":
            s["worker_stopped"] = True
    elif args[0] == "inspect":
        out = "/quantmind-tushare-worker"
    elif args[:2] == ["exec", "aaaaaaaaaaaa"] and args[2:] == ["hostname"]:
        out = "aaaaaaaaaaaa"
    elif "cancel_consumer" in args:
        s["cancelled"] = True
    elif "inspect" in args:
        kind = args[args.index("inspect") + 1]
        index = s.setdefault("indexes", {}).get(kind, 0)
        values = s.get(kind, [0])
        count = values[min(index, len(values) - 1)]
        s["indexes"][kind] = index + 1
        if kind == "active_queues":
            items = [{"name": "tushare_acquire"}] if count else []
        else:
            items = [{} for _ in range(count)]
        out = json.dumps({"celery@aaaaaaaaaaaa": items})
p.write_text(json.dumps(s))
if out:
    print(out)
raise SystemExit(rc)
"""


class Drain(unittest.TestCase):
    def invoke(self, state, timeout=8):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "deploy").mkdir()
            (root / "bin").mkdir()
            for name in ("dual-node.sh", "tushare-worker-drain.sh"):
                target = root / "scripts" / name
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o700)
            (root / "deploy/dual-node.env").write_text(
                "QM_CLOUD_HOSTNAME=VM-0-5-ubuntu\n"
                "QM_REMOTE_ROOT=/fixture\n"
                f"QM_REMOTE_PROJECT={root.resolve()}\n"
                "QM_DISK_UUID=fixture-disk\n"
            )
            (root / ".env.local").touch()
            (root / "docker-compose.yml").touch()
            (root / "deploy/compose.cloud.yml").touch()
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"calls": [], **state}))
            for name in ("docker", "findmnt", "hostname", "id"):
                target = root / "bin" / name
                target.write_text(FAKE.replace("PYTHON", sys.executable, 1))
                target.chmod(0o700)
            env = {
                **os.environ,
                "PATH": str(root / "bin") + ":" + os.environ["PATH"],
                "FAKE_STATE": str(state_path),
                "QM_TUSHARE_DRAIN_POLL_SECONDS": "1",
            }
            env.pop("QM_SCRIPT_TEXT", None)
            env.pop("QM_TUSHARE_DRAIN_SCRIPT_TEXT", None)
            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts/tushare-worker-drain.sh"),
                    "--timeout",
                    str(timeout),
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout + 5,
            )
            return result, json.loads(state_path.read_text())

    def test_reserved_to_active_race_requires_two_stable_idle_rounds(self):
        result, state = self.invoke(
            {
                "active_queues": [0, 0, 0, 0],
                "active": [0, 1, 0, 0],
                "reserved": [0, 0, 0, 0],
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(state["beat_stopped"])
        self.assertTrue(state["cancelled"])
        self.assertTrue(state["worker_stopped"])
        self.assertEqual(state["indexes"]["active"], 4)
        cancel = next(call for call in state["calls"] if "cancel_consumer" in call)
        self.assertIn(NODE, cancel)

    def test_timeout_never_stops_or_revokes_worker(self):
        result, state = self.invoke(
            {"active_queues": [0], "active": [1], "reserved": [0]}, timeout=2
        )
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertTrue(state["beat_stopped"])
        self.assertTrue(state["cancelled"])
        self.assertFalse(state.get("worker_stopped", False))
        self.assertFalse(
            any("revoke" in part for call in state["calls"] for part in call)
        )

    def test_wrong_cloud_hostname_fails_before_docker(self):
        result, state = self.invoke({"host": "wrong-host"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == "docker" for call in state["calls"]))


if __name__ == "__main__":
    unittest.main()
