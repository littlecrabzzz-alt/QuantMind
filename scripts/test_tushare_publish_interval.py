"""Bounded publication cadence with real immutable retention; fixtures only."""

from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs
from backend.shared import tushare_pipeline as module


class PublicationInterval(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(
            self.stack.enter_context(tempfile.TemporaryDirectory())
        ).resolve()
        (self.root / "ENABLED").touch()
        self.config = {
            "publish_interval_seconds": 900,
            "enable_documents": True,
            "document_execution": "worker",
        }
        self.now = 1800000000
        self.acquisitions = 0
        self.registrations = 0
        self.collect = None
        self.run_original = module.Pipeline.run
        self.client_type = httpx.Client
        for target, kwargs in (
            ("ROOT", {"new": self.root}),
            ("authority", {}),
            ("get_secret", {"return_value": "fixture-only"}),
        ):
            self.stack.enter_context(patch.object(module, target, **kwargs))
        self.stack.enter_context(
            patch.object(module.time, "time", side_effect=lambda: self.now)
        )
        self.stack.enter_context(
            patch.object(
                module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=200 * 2**30),
            )
        )
        self.stack.enter_context(patch.object(module.httpx, "Client"))
        self.stack.enter_context(patch.object(module.Pipeline, "initialize"))
        self.stack.enter_context(
            patch.object(module.Pipeline, "plan_extended", return_value={})
        )
        self.stack.enter_context(
            patch(
                "backend.shared.tushare_archive.recover_archive",
                return_value={"remaining": 0},
            )
        )
        self.stack.enter_context(patch.object(module.Pipeline, "run", self.acquire))
        self.stack.enter_context(
            patch.object(module.Pipeline, "register_documents", self.register)
        )
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            self.stack.enter_context(
                patch(target, side_effect=AssertionError("offline only"))
            )

    def acquire(self, *args, **kwargs):
        self.acquisitions += 1
        if self.collect:
            return self.collect()
        return {"requests": 0}

    def register(self, *args, **kwargs):
        self.registrations += 1
        return {"observations": 0}

    def tick(self, advance=0, before_nonpublication_work=None):
        self.now += advance
        (self.root / "pipeline-config.json").write_text(json.dumps(self.config))
        result = module.tick(before_nonpublication_work=before_nonpublication_work)
        self.assertEqual(result, self.saved())
        return result

    def saved(self):
        return json.loads((self.root / "pipeline-status.json").read_bytes())

    def checkpoint(self):
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            row = db.execute(
                "SELECT value FROM scheduler_state WHERE name='publish_success_at'"
            ).fetchone()
        return row[0] if row else None

    def test_first_publish_restart_defer_boundary_and_noop_checkpoint(self):
        first = self.tick()
        self.assertTrue(first["publication"]["performed"])
        pointer = (self.root / "CURRENT.json").read_bytes()
        checkpoint = self.checkpoint()
        for advance in (120, 120, 659):
            deferred = self.tick(advance)
            self.assertEqual(deferred["publication"]["status"], "deferred")
            self.assertTrue(deferred["publication"]["pending"])
            self.assertFalse(deferred["publication"]["performed"])
            self.assertEqual(deferred["release_id"], first["release_id"])
            self.assertEqual(
                deferred["publication"]["current_release_id"], first["release_id"]
            )
            self.assertEqual(deferred["publication"]["mirror_status"], "not_checked")
            self.assertNotIn("publish", deferred["timing"])
            self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
            self.assertEqual(self.checkpoint(), checkpoint)
        # Empty publication checks still succeed and start the next interval.
        due = self.tick(1)
        self.assertTrue(due["publication"]["performed"])
        self.assertEqual(due["release_id"], first["release_id"])
        self.assertEqual(self.checkpoint(), self.now)
        self.assertEqual(len(list((self.root / "releases").iterdir())), 1)
        self.assertEqual(self.acquisitions, 3)
        self.assertEqual(self.registrations, 3)
        self.assertEqual(self.tick(120)["publication"]["status"], "deferred")

    def test_default_zero_preserves_each_tick_publish_and_does_not_write_checkpoint(
        self,
    ):
        del self.config["publish_interval_seconds"]
        self.assertTrue(self.tick()["publication"]["performed"])
        with patch.object(
            module.Pipeline, "publish", wraps=None, return_value="fixture-release"
        ) as publish:
            self.tick(1)
            self.tick(1)
            self.assertEqual(publish.call_count, 2)
        self.assertIsNone(self.checkpoint())

    def test_manual_publish_bypasses_interval_without_changing_tick_checkpoint(self):
        first = self.tick()
        checkpoint = self.checkpoint()
        p = module.Pipeline(self.root, {"entries": []})
        try:
            p.enqueue("trade_cal", {"start_date": "20260101"}, 1, "fixture")
            p.db.commit()
            manual = p.publish()
        finally:
            p.close()
        self.assertNotEqual(manual, first["release_id"])
        self.assertEqual(self.checkpoint(), checkpoint)
        self.assertEqual(self.tick(120)["release_id"], manual)

    def test_failure_keeps_checkpoint_current_and_retries_immediately(self):
        first = self.tick()
        checkpoint = self.checkpoint()
        pointer = (self.root / "CURRENT.json").read_bytes()
        with patch.object(
            module.Pipeline,
            "publish",
            side_effect=RuntimeError("fixture private error"),
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture private"):
                self.tick(900)
        self.assertEqual(self.checkpoint(), checkpoint)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        report = self.saved()
        self.assertEqual(report["publication"]["status"], "failed")
        self.assertTrue(report["publication"]["pending"])
        self.assertFalse(report["publication"]["performed"])
        self.assertEqual(
            report["publication"]["current_release_id"], first["release_id"]
        )
        self.assertNotIn("fixture private", json.dumps(report))
        self.assertTrue(self.tick()["publication"]["performed"])
        self.assertEqual(self.checkpoint(), self.now)

    def test_clock_rollback_and_missing_current_cannot_defer(self):
        first = self.tick()
        self.assertTrue(self.tick(-100)["publication"]["performed"])
        self.assertEqual(self.checkpoint(), self.now)
        (self.root / "CURRENT.json").unlink()
        report = self.tick(1)
        self.assertTrue(report["publication"]["performed"])
        self.assertEqual(report["release_id"], first["release_id"])

    def test_corrupt_current_is_safe_failure_not_published_or_timestamp_advance(self):
        self.tick()
        checkpoint = self.checkpoint()
        pointer = self.root / "CURRENT.json"
        old = pointer.read_bytes()
        current = json.loads(old)
        current["manifest_sha256"] = "f" * 64
        pointer.write_text(json.dumps(current))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.tick(120)
        self.assertEqual(self.checkpoint(), checkpoint)
        self.assertFalse(self.saved()["publication"]["performed"])
        self.assertTrue(self.saved()["publication"]["pending"])
        pointer.write_bytes(old)
        manifest = self.root / "releases" / current["release_id"] / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.tick()
        self.assertEqual(self.checkpoint(), checkpoint)

    def test_due_publish_needs_no_provider_token_client_or_planning(self):
        with (
            patch.object(
                module, "get_secret", side_effect=AssertionError("no token read")
            ),
            patch.object(module.Pipeline, "initialize") as initialize,
            patch.object(module.Pipeline, "plan_extended") as plan,
            patch.object(module.httpx, "Client") as client,
        ):
            report = self.tick()
        self.assertEqual(report["status"], "publish_only")
        self.assertEqual(report["requests"], 0)
        self.assertEqual(report["publication"]["mode"], "publish_only")
        self.assertEqual(
            report["timing"]["completed_stages"],
            ["open", "publication_check", "publish", "close"],
        )
        initialize.assert_not_called()
        plan.assert_not_called()
        client.assert_not_called()
        self.assertEqual(self.acquisitions, 0)
        self.assertEqual(self.registrations, 0)
        deferred = self.tick(120)
        self.assertEqual(deferred["publication"]["mode"], "acquire_only")
        self.assertEqual(self.acquisitions, 1)
        self.assertEqual(self.registrations, 1)

    def test_document_hook_skips_publish_and_precedes_acquisition(self):
        events = []
        self.collect = lambda: events.append("acquire") or {"requests": 0}
        published = self.tick(
            before_nonpublication_work=lambda: events.append("documents")
        )
        self.assertEqual(published["status"], "publish_only")
        self.assertEqual(events, [])
        acquired = self.tick(
            120, before_nonpublication_work=lambda: events.append("documents")
        )
        self.assertEqual(acquired["publication"]["mode"], "acquire_only")
        self.assertEqual(events, ["documents", "acquire"])

    def test_failed_publish_does_not_run_document_hook(self):
        events = []
        with (
            patch.object(
                module.Pipeline,
                "publish",
                side_effect=RuntimeError("fixture publish failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "fixture publish failure"),
        ):
            self.tick(
                before_nonpublication_work=lambda: events.append("documents")
            )
        self.assertEqual(events, [])

    def test_60_second_publish_and_90_second_acquire_never_share_interval_tick(self):
        elapsed = [0.0]
        original = module.Pipeline.publish

        def slow_publish(pipeline):
            elapsed[0] += 60
            self.now += 60
            return original(pipeline)

        def slow_collect():
            elapsed[0] += 90
            self.now += 90
            return {"requests": 10}

        self.collect = slow_collect
        with (
            patch.object(module.time, "monotonic", side_effect=lambda: elapsed[0]),
            patch.object(module.Pipeline, "publish", slow_publish),
        ):
            initial = self.tick()
            self.assertEqual(initial["timing"]["total_elapsed_seconds"], 60)
            checkpoint = self.checkpoint()
            # Starting one second before due must finish acquisition without adding
            # a 60s publish; the next automatic tick handles the durable backlog.
            acquire = self.tick(899)
            self.assertEqual(acquire["timing"]["total_elapsed_seconds"], 90)
            self.assertEqual(acquire["publication"]["status"], "deferred")
            self.assertEqual(self.checkpoint(), checkpoint)
            due = self.tick()
            self.assertEqual(due["timing"]["total_elapsed_seconds"], 60)
            self.assertEqual(due["requests"], 0)
            self.assertNotIn("acquire", due["timing"]["stage_seconds"])
            self.assertEqual(self.acquisitions, 1)
            self.assertEqual(self.registrations, 1)
            self.assertEqual(self.checkpoint(), self.now)

    def test_interval_rejects_invalid_values_before_collecting(self):
        for value in (-1, True, 1.5, "900", None):
            with self.subTest(value=value):
                self.config["publish_interval_seconds"] = value
                with self.assertRaisesRegex(ValueError, "publication interval"):
                    self.tick()
        self.assertEqual(self.acquisitions, 0)

    def test_all_between_publish_raw_attempts_and_document_versions_reach_fresh_mirror(
        self,
    ):
        original_files = []

        def collect():
            p = module.Pipeline(self.root, {"entries": []})
            try:
                p.enqueue(
                    "fund_adj", {"trade_date": "20260907", "offset": 0, "limit": 2}
                )
                p.db.execute("UPDATE jobs SET state='pending',retry_after=0")
                p.db.commit()
                value = self.acquisitions
                with self.client_type(
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(
                            200,
                            json={
                                "code": 0,
                                "data": {
                                    "fields": ["ts_code", "trade_date", "adj_factor"],
                                    "items": [["510300.SH", "20260907", value]],
                                },
                            },
                        )
                    )
                ) as client:
                    result = self.run_original(
                        p,
                        client,
                        "fixture-only",
                        {"priority_start": "20200101", "requests_per_minute": None},
                        max_requests=1,
                        max_seconds=2,
                        pause=0,
                    )
            finally:
                p.close()
            # Several document versions occur while the release pointer is fixed.
            raw = docs._save(
                self.root,
                "attachments",
                ".html",
                f"<p>version {value}</p>".encode(),
                "text/html",
            )
            text = docs._save(
                self.root,
                "extracted",
                ".json",
                json.dumps({"text": f"version {value}"}).encode(),
                "application/json",
            )
            original_files.extend([raw["path"], text["path"]])
            artifact = {
                "status": "downloaded",
                "parse_status": "parsed",
                "files": [raw, text],
                "fetched_at": f"fixture-{value}",
            }
            db = docs._document_db(self.root)
            db.execute(
                "INSERT OR IGNORE INTO documents(id,observation,url) VALUES(?,?,?)",
                ("a" * 64, "fixture-observation", "https://example.com/document"),
            )
            downloaded = {**artifact, "parse_status": "parse_pending", "files": [raw]}
            for phase, evidence in (("download", downloaded), ("parse", artifact)):
                db.execute(
                    "INSERT INTO document_attempts(document_id,phase,result,created_at) VALUES(?,?,?,?)",
                    ("a" * 64, phase, json.dumps(evidence), self.now),
                )
            db.execute(
                "UPDATE documents SET download_status='downloaded',parse_status='parsed',result=? WHERE id=?",
                (json.dumps(artifact), "a" * 64),
            )
            db.commit()
            db.close()
            return result

        self.collect = collect
        first = self.tick()
        pointer = (self.root / "CURRENT.json").read_bytes()
        for _ in range(4):
            self.assertEqual(self.tick(120)["publication"]["status"], "deferred")
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        last = self.tick(420)
        self.assertEqual(last["status"], "publish_only")
        self.assertEqual(last["requests"], 0)
        self.assertEqual(self.acquisitions, 4)
        manifest = module.verify_data(self.root, last["release_id"])
        self.assertNotEqual(last["release_id"], first["release_id"])
        self.assertEqual(len(manifest["datasets"]), 4)
        values = [
            pq.read_table(self.root / d["path"]).to_pylist()[0]["adj_factor"]
            for d in manifest["datasets"]
        ]
        self.assertEqual(sorted(values), [1, 2, 3, 4])
        self.assertEqual(sum(n.startswith("objects/") for n in manifest["files"]), 4)
        self.assertEqual(
            sum(n.startswith("observations/") for n in manifest["files"]), 4
        )
        self.assertTrue(set(original_files).issubset(manifest["files"]))
        index = json.loads((self.root / manifest["documents"]["path"]).read_bytes())
        attempts = [
            r
            for shard in index["attempts"]
            for r in json.loads((self.root / shard["path"]).read_bytes())["items"]
        ]
        self.assertEqual([a["phase"] for a in attempts], ["download", "parse"] * 4)
        self.assertEqual(
            [a["result"]["fetched_at"] for a in attempts],
            [f"fixture-{i}" for i in (1, 2, 3, 4) for _ in range(2)],
        )
        # A fresh offline mirror needs only the final manifest and its file closure.
        target = self.root / "fresh-mirror"
        for name in [
            f"releases/{last['release_id']}/manifest.json",
            *manifest["files"],
        ]:
            dst = target / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root / name, dst)
        self.assertEqual(module.verify_data(target, last["release_id"]), manifest)
        self.assertFalse((target / "pipeline.sqlite").exists())
        self.assertFalse((target / "documents.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
