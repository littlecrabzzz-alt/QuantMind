"""Storage maintenance regressions; disposable fixtures only, never real data."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import storage_maintenance as sm


def _release(parent, name, age, marker="VERIFIED", size=1000):
    path = parent / name
    (path / "project").mkdir(parents=True)
    (path / "COMPLETE").write_text("")
    if marker:
        (path / marker).write_text("")
    (path / "project" / "blob.bin").write_bytes(b"x" * size)
    stamp = time.time() - age * 3600
    os.utime(path, (stamp, stamp))
    return path


def _ids(entries):
    return sorted(Path(e["path"]).name for e in entries)


class Fixture:
    def __init__(self, base):
        self.app = base / "app"
        self.project = base / "project"
        self.receipts = base / "receipts"
        rel = self.app / "market-source" / "releases"
        self.a = rel / "A"
        self.bc = rel / "BC"
        for name, age in (("market-a1", 40), ("market-a2", 30), ("market-a3", 20), ("market-a4", 10)):
            _release(self.a, name, age)
        for name, age in (("market-b5", 30), ("market-b6", 20), ("market-b7", 10)):
            _release(self.bc, name, age)
        self.write_status({"A": {"release_id": "market-a1", "local_release": None},
                           "BC": {"release_id": "market-b7", "local_release": "market-b5"}})
        (self.app / "market-source" / "SOURCE.json").write_text(
            json.dumps({"quantdb_baseline": "snapshot-quantdb-q2"}))

        cloud = self.app / "cloud-snapshots"
        for name, age in (("snapshot-s0", 50), ("snapshot-s1", 40), ("snapshot-s2", 30), ("snapshot-s3", 20)):
            _release(cloud, name, age, marker=None)
        (cloud / "latest").symlink_to("snapshot-s2")
        q = cloud / "quantdb"
        for name, age in (("snapshot-quantdb-q1", 40), ("snapshot-quantdb-q2", 30),
                          ("snapshot-quantdb-q3", 20), ("snapshot-quantdb-q4", 10)):
            _release(q, name, age)
        (q / "latest").symlink_to("snapshot-quantdb-q4")

        local = self.project / ".local-dev"
        local.mkdir(parents=True)
        (local / "SNAPSHOT_ID").write_text("snapshot-s1\n")
        (local / "QUANTDB_SYNC.json").write_text(json.dumps({"snapshot": str(q / "snapshot-quantdb-q2")}))

    def write_status(self, status):
        (self.app / "market-source").mkdir(parents=True, exist_ok=True)
        (self.app / "market-source" / "status.json").write_text(json.dumps(status))

    def plan(self):
        return sm.build_plan(self.app, self.project, keep_newest=1)


class StoragePlan(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_market_releases_keep_referenced_and_newest(self):
        names = _ids(e for e in self.fx.plan()["delete"] if "market-source" in e["path"])
        self.assertEqual(names, ["market-a2", "market-a3", "market-b6"])

    def test_cloud_snapshots_keep_latest_baseline_references_and_newest(self):
        names = _ids(e for e in self.fx.plan()["delete"] if "cloud-snapshots" in e["path"])
        # s1: SNAPSHOT_ID, s2: latest, s3: newest; q2: referenced, q4: latest+newest.
        self.assertEqual(names, ["snapshot-quantdb-q1", "snapshot-quantdb-q3", "snapshot-s0"])

    def test_every_kept_entry_has_a_reason(self):
        plan = self.fx.plan()
        self.assertIn("market-a1", _ids(plan["keep"]))
        self.assertTrue(all(e.get("reason") for e in plan["keep"]))

    def test_unverified_market_release_is_never_deleted(self):
        _release(self.fx.a, "market-a0", 100, marker=None)
        self.assertNotIn("market-a0", _ids(self.fx.plan()["delete"]))

    def test_incomplete_snapshot_is_never_deleted(self):
        path = _release(self.fx.app / "cloud-snapshots", "snapshot-sx", 100, marker=None)
        (path / "COMPLETE").unlink()
        self.assertNotIn("snapshot-sx", _ids(self.fx.plan()["delete"]))

    def test_symlinked_release_directory_is_skipped(self):
        target = _release(Path(self._tmp.name) / "elsewhere", "market-a9", 100)
        (self.fx.a / "market-a9").symlink_to(target)
        plan = self.fx.plan()
        self.assertNotIn("market-a9", _ids(plan["delete"]))
        self.assertTrue(target.exists())

    def test_bytes_are_counted(self):
        plan = self.fx.plan()
        self.assertTrue(all(e["bytes"] >= 1000 for e in plan["delete"]))
        self.assertEqual(plan["total_bytes"], sum(e["bytes"] for e in plan["delete"]))

    def test_plan_only_targets_known_roots(self):
        roots = [str((self.fx.app / "market-source" / "releases").resolve()),
                 str((self.fx.app / "cloud-snapshots").resolve())]
        for entry in self.fx.plan()["delete"]:
            self.assertTrue(any(str(Path(entry["path"]).resolve()).startswith(r + os.sep) for r in roots))

    def test_build_plan_does_not_modify_anything(self):
        before = sorted(str(p) for p in self.fx.app.rglob("*"))
        self.fx.plan()
        self.assertEqual(before, sorted(str(p) for p in self.fx.app.rglob("*")))


class StorageApply(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))
        self.plan_path = Path(self._tmp.name) / "plan.json"
        self.sha = sm.write_plan(self.fx.plan(), self.plan_path)

    def tearDown(self):
        self._tmp.cleanup()

    def apply(self, sha=None):
        return sm.apply_plan(self.plan_path, sha or self.sha, self.fx.app, self.fx.project,
                             self.fx.receipts, keep_newest=1)

    def test_wrong_confirmation_refuses(self):
        with self.assertRaises(Exception):
            self.apply("0" * 64)
        self.assertTrue((self.fx.a / "market-a2").exists())

    def test_apply_deletes_exactly_planned_and_writes_receipt(self):
        receipt = self.apply()
        for name in ("market-a2", "market-a3"):
            self.assertFalse((self.fx.a / name).exists())
        self.assertFalse((self.fx.bc / "market-b6").exists())
        for name in ("market-a1", "market-a4"):
            self.assertTrue((self.fx.a / name).exists())
        self.assertTrue((self.fx.app / "cloud-snapshots" / "snapshot-s1").exists())
        self.assertEqual(_ids(receipt["removed"]), _ids(json.loads(self.plan_path.read_text())["delete"]))
        self.assertEqual(len(list(self.fx.receipts.glob("*.json"))), 1)

    def test_newly_referenced_release_blocks_whole_apply(self):
        self.fx.write_status({"A": {"release_id": "market-a2", "local_release": None},
                              "BC": {"release_id": "market-b7", "local_release": "market-b5"}})
        with self.assertRaises(Exception):
            self.apply()
        for name in ("market-a2", "market-a3"):
            self.assertTrue((self.fx.a / name).exists())
        self.assertTrue((self.fx.bc / "market-b6").exists())

    def test_tampered_plan_with_resigned_sha_is_refused(self):
        plan = json.loads(self.plan_path.read_text())
        plan["delete"].append({"path": str(self.fx.a / "market-a1"), "bytes": 1, "group": "A"})
        sha = sm.write_plan(plan, self.plan_path)
        with self.assertRaises(Exception):
            self.apply(sha)
        self.assertTrue((self.fx.a / "market-a1").exists())
        self.assertTrue((self.fx.a / "market-a2").exists())


if __name__ == "__main__":
    unittest.main()
