"""Old transport copies rotate even while local apply keeps failing."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import local_market_source as source


def _release(parent, n, age):
    name = "market-" + f"{n:x}" * 64
    name = name[:7 + 64]
    path = parent / name
    path.mkdir(parents=True)
    (path / "COMPLETE").write_text("")
    (path / "VERIFIED").write_text("")
    stamp = time.time() - age * 3600
    os.utime(path, (stamp, stamp))
    return name


class Usage:
    free = 10 * 2**40


class Rotation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "market-source"
        self.project = base / "project"
        self.project.mkdir()
        (self.project / ".local-primary").mkdir()
        (self.project / ".local-primary/READY").touch()
        self.dir = {m: self.root / "releases" / m for m in ("A", "BC")}
        self.ids = {m: [_release(self.dir[m], i + (0 if m == "A" else 6), age)
                        for i, age in enumerate((40, 30, 20, 10), start=1)]
                    for m in ("A", "BC")}
        clock = source.now()
        state = {}
        for m in ("A", "BC"):
            first, second, third, newest = self.ids[m]
            state[m] = {"collected_day": source.collection_day(clock, m), "release_id": newest,
                        "cloud_release": newest, "local_release": first,
                        "primary_release": first, "status": "retry_pending"}
        (self.root / "status.json").write_text(json.dumps(state))

    def tearDown(self):
        self._tmp.cleanup()

    def tick(self):
        def fail_apply(*args, **kwargs):
            raise RuntimeError("Local backend stopped; downloaded version retained for next start")


        with patch("shutil.disk_usage", return_value=Usage()), \
                patch.object(source.sys, "platform", "darwin"), \
                patch("quantdb_refresh.primary_wait_reason", return_value=None), \
                patch("quantdb_refresh.apply", side_effect=fail_apply), \
                patch("quantdb_refresh.apply_bc", side_effect=fail_apply), \
                patch("subprocess.run", side_effect=AssertionError("no direct Docker or cloud fallback")), \
                patch.object(source, "collect_on_mac", side_effect=AssertionError("not due")):
            return source.tick(self.root, self.project, Path("/nonexistent"), "approved-image")

    def remaining(self, market):
        return sorted(p.name for p in self.dir[market].iterdir())

    def test_failed_local_apply_still_rotates_unprotected_old_copies(self):
        code = self.tick()
        self.assertEqual(code, 2)
        first, second, third, newest = self.ids["A"]
        # newest two kept, plus the protected local release; only `second` goes.
        self.assertEqual(self.remaining("A"), sorted([first, third, newest]))

    def test_failed_primary_bc_apply_still_rotates(self):
        self.tick()
        first, second, third, newest = self.ids["BC"]
        self.assertEqual(self.remaining("BC"), sorted([first, third, newest]))

    def test_failure_is_still_recorded_for_retry(self):
        self.tick()
        state = json.loads((self.root / "status.json").read_text())
        for m in ("A", "BC"):
            self.assertEqual(state[m]["status"], "retry_pending")
            self.assertTrue(state[m].get("error"))
            self.assertEqual(state[m]["release_id"], self.ids[m][3])

    def test_current_release_is_never_rotated_even_if_older(self):
        state = json.loads((self.root / "status.json").read_text())
        state["A"]["release_id"] = state["A"]["cloud_release"] = self.ids["A"][1]
        (self.root / "status.json").write_text(json.dumps(state))
        self.tick()
        self.assertIn(self.ids["A"][1], self.remaining("A"))
        self.assertIn(self.ids["A"][0], self.remaining("A"))


if __name__ == "__main__":
    unittest.main()
