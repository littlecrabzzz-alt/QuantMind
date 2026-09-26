"""Ownership, immutable transport and retry checks; no live services or vendor calls."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

from scripts import local_market_source as source
from backend.shared import data_source_config as policy


class LocalMarketSourceTest(unittest.TestCase):
    def bundle(self, base, name="data/quantdb/1_kline_data/daily_forward/dt=20260924/data.parquet"):
        payload = b"bounded-fixture"
        row = {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        raw = json.dumps(row, sort_keys=True) + "\n"
        root = base / ("market-" + hashlib.sha256(raw.encode()).hexdigest())
        root.mkdir()
        path = root / "project" / name
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        (root / "runtime-manifest.jsonl").write_text(raw)
        return root, path

    def test_cloud_never_acquires_or_dispatches_even_if_old_schedule_is_enabled(self):
        from backend.services.engine.tasks import market_sync_scheduler as scheduler
        with patch.dict("os.environ", {"QM_NODE_ROLE": "authority"}), patch.object(scheduler, "_redis") as redis:
            self.assertFalse(policy.upstream_collection_allowed())
            with self.assertRaisesRegex(RuntimeError, "本地采集"):
                policy.require_upstream_collection()
            self.assertEqual(scheduler.dispatch_due_syncs()["dispatched"], [])
            with self.assertRaises(RuntimeError):
                scheduler.save_schedule("A", {"enabled": True})
            with self.assertRaises(RuntimeError):
                scheduler.run_market_sync("BC", {})
            redis.assert_not_called()
        with patch.dict("os.environ", {"QM_NODE_ROLE": "archive"}):
            policy.require_upstream_collection()

    def test_integrity_fails_closed_on_mutation_unlisted_file_or_manifest_change(self):
        with tempfile.TemporaryDirectory() as d:
            bundle, path = self.bundle(Path(d))
            self.assertEqual(len(source.verify_bundle(bundle, "A")), 1)
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError): source.verify_bundle(bundle, "A")
            path.write_bytes(b"bounded-fixture")
            extra = bundle / "project/data/quantdb/unlisted.parquet"
            extra.write_bytes(b"x")
            with self.assertRaises(ValueError): source.verify_bundle(bundle, "A")
            extra.unlink()
            with (bundle / "runtime-manifest.jsonl").open("a") as f: f.write("\n")
            with self.assertRaises(ValueError): source.verify_bundle(bundle, "A")

    def test_paths_cannot_escape_scope_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            for name in ("../outside", "/data/quantdb/x.parquet", "data/quantbc/x.parquet", "data/quantdb/../x.parquet", "data/quantdb/x.sqlite"):
                with self.assertRaises(ValueError): source.safe_file(project, name, "A")
            (project / "data").symlink_to(project)
            with self.assertRaises(ValueError): source.safe_file(project, "data/quantdb/x.parquet", "A")

    def test_manual_before_schedule_does_not_consume_later_daily_slot(self):
        zone = ZoneInfo("Asia/Shanghai")
        before = datetime(2026, 9, 27, 0, 15, tzinfo=zone)
        after = datetime(2026, 9, 27, 8, 15, tzinfo=zone)
        self.assertEqual(source.collection_day(before, "BC"), "2026-09-26")
        self.assertEqual(source.collection_day(after, "BC"), "2026-09-27")

    def test_receive_completed_version_does_not_repeat_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            release_id = "market-" + "a" * 64
            source.write_json(root / "A-receipt.json", {"status": "applied", "release_id": release_id})
            with patch.object(source, "verify_bundle") as verify:
                self.assertEqual(source.receive(root, "A", release_id)["status"], "applied")
                verify.assert_not_called()

    def test_reseed_v1_does_not_inherit_v2_release_cursor(self):
        from backend.scripts import quantdb_daily_sync as sync
        client, state = Mock(), Mock()
        client._get.return_value = {"releases": [{"release_id": "v2", "objects": []}]}
        client.query_manifest.return_value = []
        datasets = [sync.V2_DATASETS[0], sync.V1_DATASETS[0]]
        with patch.object(sync, "_make_client", return_value=client), patch.object(sync, "_open_state", return_value=state):
            result = sync.reseed_state(datasets)
        client.query_manifest.assert_called_once_with(category_id=datasets[1]["category_id"], sub_category=datasets[1]["sub_category"])
        self.assertEqual(set(result["per_dataset"]), {x["sub_category"] for x in datasets})

    def test_crash_after_directory_exchange_recovers_without_exchanging_back(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundle, path = self.bundle(root)
            rows = source.verify_bundle(bundle, "A")
            live = root / "data/quantdb"
            live.mkdir(parents=True)
            (live / "old.parquet").write_bytes(b"rollback")
            receipt_path = root / "A-receipt.json"
            original = source.exchange
            def crash_after_exchange(left, right):
                original(left, right)
                raise InterruptedError("simulated process death")
            with patch.object(source, "exchange", side_effect=crash_after_exchange):
                with self.assertRaises(InterruptedError):
                    source.install_quantdb_files(bundle, live, root, receipt_path, {}, rows)
            receipt = source.read_json(receipt_path)
            self.assertEqual(receipt["status"], "installing")
            with patch.object(source, "exchange", side_effect=AssertionError("must not swap back")):
                result = source.install_quantdb_files(bundle, live, root, receipt_path, receipt, rows)
            self.assertEqual(result["status"], "files_applied")
            self.assertTrue(source.installed_matches(root / "data", rows, "A"))
            self.assertEqual((root / "backups" / ("quantdb-before-" + bundle.name) / "old.parquet").read_bytes(), b"rollback")

    def test_transport_retention_preserves_unverified_unknown_and_pinned_versions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for i in range(5):
                p = root / ("market-" + str(i) * 64);p.mkdir();(p / "VERIFIED").touch()
                import os
                os.utime(p, (100 + i, 100 + i))
            pending = root / ("market-" + "a" * 64);pending.mkdir()
            (root / "unrelated-research-input").mkdir()
            pinned = "market-" + "0" * 64
            removed = source.retain_transport_copies(root, protected=[pinned])
            self.assertEqual(len(removed), 2)
            for name in [pinned, pending.name, "unrelated-research-input", "market-" + "4" * 64]:
                self.assertTrue((root / name).exists())

    def test_delivery_retry_does_not_repeat_successful_vendor_collection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundle, _ = self.bundle(root)
            clock = datetime(2026, 9, 27, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            with patch.object(source.sys, "platform", "darwin"), patch.object(source, "now", return_value=clock), \
                 patch.object(source.shutil, "disk_usage", return_value=Mock(free=999*2**30)), \
                 patch.object(source, "collect_on_mac") as collect, patch.object(source, "publish", return_value=bundle), \
                 patch.object(source, "send_cloud", side_effect=RuntimeError("offline")) as send:
                self.assertEqual(source.tick(root, root, root, "host", "A"), 2)
                self.assertEqual(source.tick(root, root, root, "host", "A"), 2)
                collect.assert_called_once()
                self.assertEqual(send.call_count, 2)

    def test_local_backup_rotation_never_registers_legacy_or_research_directories(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d); root = project / "source"
            state = project / ".local-dev"; state.mkdir()
            legacy = state / "quantdb-before-legacy"; legacy.mkdir()
            research = state / "research-input"; research.mkdir()
            for i in range(3):
                backup = state / ("quantdb-before-20260927T000000-" + str(i)*6)
                backup.mkdir()
                source.write_json(state / "QUANTDB_SYNC.json", {"backup": str(backup)})
                source.retain_local_backups(root, project)
            self.assertTrue(legacy.exists()); self.assertTrue(research.exists())
            self.assertFalse((state / "quantdb-before-20260927T000000-000000").exists())
            self.assertEqual(len(source.read_json(root / "local-backups.json")), 2)

    def test_resume_delivery_does_not_overwrite_interrupted_rollback_files(self):
        release = "market-" + "a" * 64
        for status in ("installing", "files_applied", "applied"):
            with patch.object(source.subprocess, "check_output", return_value=json.dumps({"release_id": release, "status": status})), \
                 patch.object(source, "transfer") as transfer, patch.object(source, "ssh") as ssh:
                source.send_cloud(Path(release), "A", "host")
                transfer.assert_not_called()
                ssh.assert_called_once()


if __name__ == "__main__":
    unittest.main()
