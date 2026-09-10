"""Publication crash windows, durable identity and legacy clock semantics."""

import fcntl
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from scripts import test_tushare_publish_interval as fixture
from backend.shared import tushare_pipeline as m


class Signal(BaseException):
    pass


class PublicationCommitRecovery(unittest.TestCase):
    setUp = fixture.PublicationInterval.setUp
    acquire = fixture.PublicationInterval.acquire
    register = fixture.PublicationInterval.register
    tick = fixture.PublicationInterval.tick
    saved = fixture.PublicationInterval.saved
    checkpoint = fixture.PublicationInterval.checkpoint

    def rows(self):
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            return dict(db.execute("SELECT name,value FROM scheduler_state"))

    def seed(self):
        first = self.tick()
        p = m.Pipeline(self.root, {"entries": []})
        try:
            p.enqueue("daily", {"trade_date": "20260904"}, epoch="fixture")
            p.db.commit()
        finally:
            p.close()
        return first["release_id"]

    def interrupt_pointer(self, after=True, advance=900):
        original = m.atomic_json

        def fail(path, value):
            if path.name == "CURRENT.json" and not after:
                raise Signal("before CURRENT")
            original(path, value)
            if path.name == "CURRENT.json":
                raise Signal("after CURRENT")

        with (
            patch.object(m, "atomic_json", side_effect=fail),
            self.assertRaises(Signal),
        ):
            self.tick(advance)
        pointer = json.loads((self.root / "CURRENT.json").read_bytes())
        return pointer["release_id"]

    def assert_success_identity(self, release, timestamp):
        rows = self.rows()
        self.assertEqual(rows["publish_success_at"], timestamp)
        self.assertEqual(rows["publish_success:" + release], timestamp)
        self.assertFalse(any(k.startswith("publish_intent:") for k in rows))

    def test_swap_then_signal_restarts_with_verified_intent_no_republication(self):
        first = self.seed()
        old_success = self.checkpoint()
        second = self.interrupt_pointer()
        self.assertNotEqual(second, first)
        intent_at = self.now
        self.assertEqual(self.checkpoint(), old_success)
        self.assertEqual(self.rows()["publish_intent:" + second], intent_at)
        m.manifest_at(self.root, second)
        with patch.object(
            m.Pipeline, "publish", side_effect=AssertionError("must recover")
        ):
            report = self.tick(120)
        self.assertEqual(
            report["publication"]["checkpoint_recovery"], "verified_current_intent"
        )
        self.assertEqual(report["publication"]["recovered_release_id"], second)
        self.assertFalse(report["publication"]["performed"])
        self.assert_success_identity(second, intent_at)
        self.assertEqual(report["publication"]["next_due_at"], intent_at + 900)

    def test_first_publication_swap_without_old_scalar_is_recoverable(self):
        current = self.interrupt_pointer(advance=0)
        self.assertIsNone(self.checkpoint())
        expected = self.now
        with patch.object(
            m.Pipeline, "publish", side_effect=AssertionError("must recover")
        ):
            self.tick(120)
        self.assert_success_identity(current, expected)

    def test_before_swap_intent_cannot_acknowledge_unchanged_current(self):
        first = self.seed()
        previous = self.checkpoint()
        self.assertEqual(self.interrupt_pointer(after=False), first)
        self.assertEqual(self.checkpoint(), previous)
        self.assertNotIn("publish_intent:" + first, self.rows())
        original = m.Pipeline.publish
        calls = []

        def publish(p):
            calls.append(True)
            return original(p)

        with patch.object(m.Pipeline, "publish", publish):
            report = self.tick()
        self.assertEqual(len(calls), 1)
        self.assertTrue(report["publication"]["performed"])

    def test_noop_return_interruption_has_identity_evidence_too(self):
        first = self.tick()["release_id"]
        old = self.checkpoint()
        original = m.Pipeline.publish

        def fail(p):
            self.assertEqual(original(p), first)
            raise Signal("after no-op comparison")

        with patch.object(m.Pipeline, "publish", fail), self.assertRaises(Signal):
            self.tick(900)
        self.assertEqual(self.checkpoint(), old)
        when = self.now
        with patch.object(
            m.Pipeline, "publish", side_effect=AssertionError("must recover noop")
        ):
            self.tick(120)
        self.assert_success_identity(first, when)

    def test_missing_corrupt_manifest_never_advances_checkpoint(self):
        self.seed()
        old = self.checkpoint()
        release = self.interrupt_pointer()
        path = self.root / "releases" / release / "manifest.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.tick()
        self.assertEqual(self.checkpoint(), old)
        path.write_bytes(b"!" + raw[1:])
        with self.assertRaises(ValueError):
            self.tick()
        self.assertEqual(self.checkpoint(), old)
        self.assertIn("publish_intent:" + release, self.rows())

    def test_legacy_checkpoint_and_future_mtime_do_not_invent_success(self):
        first = self.tick()["release_id"]
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            db.execute(
                "DELETE FROM scheduler_state WHERE name LIKE 'publish_success:%' OR name LIKE 'publish_intent:%'"
            )
        future = self.now + 100000
        for path in (
            self.root / "CURRENT.json",
            self.root / "releases" / first / "manifest.json",
        ):
            os.utime(path, (future, future))
        original = m.Pipeline.publish
        calls = []

        def publish(p):
            calls.append(True)
            return original(p)

        with patch.object(m.Pipeline, "publish", publish):
            report = self.tick(900)
        self.assertEqual(calls, [True])
        self.assertNotIn("checkpoint_recovery", report["publication"])
        self.assert_success_identity(first, self.now)

    def test_clock_rollback_forces_publication_even_when_intent_matches(self):
        self.seed()
        self.interrupt_pointer()
        self.now -= 100
        original = m.Pipeline.publish
        calls = []

        def publish(p):
            calls.append(True)
            return original(p)

        with patch.object(m.Pipeline, "publish", publish):
            report = self.tick()
        self.assertEqual(calls, [True])
        self.assertEqual(report["publication"]["checkpoint_recovery"], "clock_rollback")
        self.assertEqual(self.checkpoint(), self.now)

    def test_recovered_old_commit_does_not_receive_a_fresh_full_interval(self):
        self.seed()
        self.interrupt_pointer()
        original = m.Pipeline.publish
        calls = []

        def publish(p):
            calls.append(True)
            return original(p)

        with patch.object(m.Pipeline, "publish", publish):
            report = self.tick(901)
        self.assertEqual(calls, [True])
        self.assertEqual(
            report["publication"]["checkpoint_recovery"], "verified_current_intent"
        )
        self.assertTrue(report["publication"]["performed"])
        self.assertEqual(self.checkpoint(), self.now)

    def test_older_intent_does_not_regress_newer_success(self):
        first = self.seed()
        previous = self.checkpoint()
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            db.execute(
                "INSERT INTO scheduler_state VALUES(?,?)",
                ("publish_intent:" + first, previous - 10),
            )
        with patch.object(m.Pipeline, "publish", side_effect=AssertionError("not due")):
            report = self.tick(120)
        self.assertEqual(report["publication"]["checkpoint_recovery"], "older_intent")
        self.assertEqual(self.checkpoint(), previous)

    def test_changed_pointer_before_checkpoint_fails_closed(self):
        first = self.seed()
        old = self.checkpoint()
        self.interrupt_pointer()
        original = m.Pipeline._publication_success

        def drift(p, release, when):
            m.atomic_json(
                self.root / "CURRENT.json",
                {"release_id": first, "manifest_sha256": first[5:]},
            )
            return original(p, release, when)

        with (
            patch.object(m.Pipeline, "_publication_success", drift),
            self.assertRaisesRegex(ValueError, "identity changed"),
        ):
            self.tick()
        self.assertEqual(self.checkpoint(), old)

    def test_success_transaction_failure_keeps_scalar_identity_and_intent_atomic(self):
        self.seed()
        release = self.interrupt_pointer()
        before = self.rows()
        p = m.Pipeline(self.root, {"entries": []})
        try:
            p.db.set_authorizer(
                lambda action, table, *args: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_DELETE and table == "scheduler_state"
                    else sqlite3.SQLITE_OK
                )
            )
            with self.assertRaises(sqlite3.DatabaseError):
                p._publication_success(release, self.now)
            p.db.set_authorizer(lambda *args: sqlite3.SQLITE_OK)
            self.assertEqual(
                dict(p.db.execute("SELECT name,value FROM scheduler_state")), before
            )
        finally:
            p.close()

    def test_other_lock_owner_cannot_enter_publication_check(self):
        self.seed()
        self.interrupt_pointer()
        before = self.rows()
        with (self.root / "pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = m.tick()
        self.assertEqual(result, {"status": "already_running"})
        self.assertEqual(self.rows(), before)


if __name__ == "__main__":
    unittest.main()
