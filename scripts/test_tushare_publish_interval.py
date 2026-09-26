"""Bounded publication cadence with real immutable retention; fixtures only."""

from contextlib import ExitStack
import fcntl
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

    def test_deferred_check_verifies_identity_without_parsing_manifest(self):
        first = self.tick()["release_id"]
        with patch.object(
            module, "manifest_at", side_effect=AssertionError("must not parse")
        ):
            report = self.tick(120)
        self.assertEqual(report["release_id"], first)
        self.assertEqual(report["publication"]["status"], "deferred")

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
            ["open", "publication_check", "publish_lock", "publish", "close"],
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

    def test_active_document_worker_defers_publish_without_state_change(self):
        self.tick()
        pointer = (self.root / "CURRENT.json").read_bytes()
        checkpoint = self.checkpoint()
        events = []
        with (self.root / "documents.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deferred = self.tick(
                900, before_nonpublication_work=lambda: events.append("documents")
            )
        self.assertEqual(deferred["status"], "publish_deferred_documents_active")
        self.assertEqual(
            deferred["publication"]["status"], "deferred_documents_active"
        )
        self.assertEqual(events, [])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        self.assertEqual(self.checkpoint(), checkpoint)
        published = self.tick(
            before_nonpublication_work=lambda: events.append("documents")
        )
        self.assertEqual(published["status"], "publish_only")
        self.assertTrue(published["publication"]["performed"])
        self.assertEqual(events, [])

    def test_publish_lock_rejects_document_consumer_and_releases_on_error(self):
        observed = []
        original = module.Pipeline.publish

        def publish_while_checking_lock(pipeline):
            observed.append(docs.run_documents(self.root))
            return original(pipeline)

        with patch.object(module.Pipeline, "publish", publish_while_checking_lock):
            self.tick()
        self.assertEqual(observed, [{"status": "already_running", "processed": 0}])
        with (
            patch.object(
                module.Pipeline,
                "publish",
                side_effect=RuntimeError("fixture publish failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "fixture publish failure"),
        ):
            self.tick(900)
        with (self.root / "documents.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

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

    def test_research_publish_ignores_document_lock_and_keeps_full_checkpoint(self):
        self.config["publish_interval_seconds"] = 3600
        full = self.tick()["release_id"]
        checkpoint = self.checkpoint()
        self.config["research_publish_interval_seconds"] = 900
        (self.root / "documents.sqlite").touch()
        with (self.root / "documents.lock").open("a") as lock, patch.object(
            docs, "document_index", side_effect=AssertionError("document lane unavailable")
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            first = self.tick()
            self.assertEqual(first["status"], "research_publish_only")
            research = first["research_publication"]["current_release_id"]
            self.assertEqual(self.tick(899)["research_publication"]["status"], "deferred")
            due = self.tick(1)
        self.assertEqual(due["research_publication"]["current_release_id"], research)
        self.assertTrue(due["research_publication"]["performed"])
        self.assertEqual(self.checkpoint(), checkpoint)
        self.assertEqual(json.loads((self.root / "CURRENT.json").read_bytes())["release_id"], full)
        manifest = module.manifest_at(self.root, research)
        self.assertEqual(manifest["scope"], "research_structured")
        self.assertFalse(manifest["history_complete"])
        self.assertIsNone(manifest["documents"])
        # Research publication survives a later failing full publication.
        self.tick(2699)
        old = (self.root / "RESEARCH_CURRENT.json").read_bytes()
        with patch.object(docs, "document_index", side_effect=RuntimeError("index failure")):
            failed = self.tick(1)
            self.assertEqual(failed["status"], "partial")
            self.assertEqual(failed["publication"]["status"], "failed")
            self.assertEqual(self.acquisitions, 2)
        with (self.root / "documents.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            busy = self.tick(1)
            self.assertEqual(busy["publication"]["status"], "deferred_documents_active")
            self.assertEqual(self.acquisitions, 3)
        self.assertEqual((self.root / "RESEARCH_CURRENT.json").read_bytes(), old)

    def test_research_failure_is_partial_preserves_pointer_and_acquires(self):
        self.config["publish_interval_seconds"] = 3600
        self.tick()
        self.config["research_publish_interval_seconds"] = 900
        self.tick()
        old = (self.root / "RESEARCH_CURRENT.json").read_bytes()
        with patch.object(module.Pipeline, "publish", side_effect=ValueError("missing artifact")):
            failed = self.tick(900)
        self.assertEqual(failed["status"], "partial")
        self.assertEqual(failed["research_publication"]["status"], "failed")
        self.assertEqual(self.acquisitions, 1)
        self.assertEqual((self.root / "RESEARCH_CURRENT.json").read_bytes(), old)
        recovered = self.tick()
        self.assertEqual(recovered["research_publication"]["status"], "published")
        self.assertEqual(recovered["status"], "research_publish_only")

    def test_research_retains_attempt_overlays_and_archived_only_data(self):
        from backend.shared import tushare_archive as archive
        import test_tushare_research_cache as cache_fixture
        from scripts import tushare_research_cache as cache

        cache_fixture.ResearchCache().fixture(self.root)
        full_pointer = (self.root / "CURRENT.json").read_bytes()
        source = module.manifest_at(self.root, json.loads(full_pointer)["release_id"])
        by_path = {d["path"]: d for d in source["datasets"]}
        p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(p.close)
        # fund_daily exists only in the verified historical archive.
        db = archive._db(self.root)
        for name, item in source["files"].items():
            archive._register(db, name, item["sha256"], item["bytes"], by_path.get(name))
        db.commit()
        db.close()
        daily = next(d for d in source["datasets"] if d["api_name"] == "daily")
        obs = next(name for name in source["files"] if name.startswith("observations/")
                   and json.loads((self.root / name).read_bytes())["request"]["api_name"] == "daily")
        raw = b'{}'
        sha = module.digest(raw)
        module.atomic_bytes(self.root / "objects" / (sha + ".json"), raw)
        result = dict(api_name="daily", status="schema_gap", parquet=daily,
                      observation=obs.split("/")[1], observation_sha256=source["files"][obs]["sha256"],
                      object_sha256=sha)
        p.db.execute("INSERT INTO attempts VALUES(?,?,?)", ("daily-job", 1, json.dumps(result)))
        result.update(status="sample_ok", contract_reassessment={"reassessed_status": "sample_ok", "upstream_calls": 0})
        p.db.execute("INSERT INTO contract_reassessments VALUES(?,?,?,?)", ("daily-job", "now", "test", json.dumps(result)))
        # A nonpriority broken artifact must not gate this lane.
        p.db.execute("INSERT INTO attempts VALUES(?,?,?)", ("other-job", 1, json.dumps({
            "api_name": "fund_adj", "status": "sample_ok", "parquet": {"path": "parquet/missing.parquet"}
        })))
        p.db.commit()
        release = p.publish(research=True)
        manifest = module.manifest_at(self.root, release)
        self.assertEqual({d["api_name"] for d in manifest["datasets"]}, {"daily", "fund_daily"})
        selected = next(d for d in manifest["datasets"] if d["api_name"] == "daily")
        self.assertEqual(selected["quality_state"], "sample_ok")
        self.assertIn("contract_reassessment", selected)
        self.assertFalse(any(name.startswith(("documents/", "archives/")) for name in manifest["files"]))
        exported = cache.prepare(self.root, ["daily", "fund_daily"])
        self.assertEqual(exported["source_release_id"], release)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), full_pointer)
        old = (self.root / "RESEARCH_CURRENT.json").read_bytes()
        (self.root / obs).unlink()
        with self.assertRaises(FileNotFoundError):
            p.publish(research=True)
        self.assertEqual((self.root / "RESEARCH_CURRENT.json").read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
