"""Ownership, immutable transport and retry checks; no live services or vendor calls."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile

# macOS /var is a symlink; fixtures must obey the release no-symlink contract.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
import unittest
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import local_market_source as source
from backend.shared import data_source_config as policy


class LocalMarketSourceTest(unittest.TestCase):
    def test_primary_skips_cloud_and_does_not_reuse_sandbox_delivery_cursor(self):
        import quantdb_refresh as refresh
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            root = project / "source"
            (project / ".local-primary").mkdir()
            (project / ".local-primary/READY").touch()
            release_id = "market-" + "a" * 64
            clock = datetime(2026, 10, 14, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
            source.write_json(root / "status.json", {
                name: {"collected_day": "2026-10-14", "release_id": release_id,
                       "local_release": release_id} for name in ("A", "BC")})
            with patch.object(source.sys, "platform", "darwin"), \
                 patch.object(source, "now", return_value=clock), \
                 patch.object(source.shutil, "disk_usage", return_value=Mock(free=999*2**30)), \
                 patch.object(source, "collect_on_mac") as collect, \
                 patch.object(source.subprocess, "run", side_effect=AssertionError("no subprocess")), \
                 patch.object(refresh, "primary_wait_reason", return_value=None), \
                 patch.object(refresh, "apply", side_effect=[RuntimeError("busy"), None]) as apply, \
                 patch.object(refresh, "apply_bc") as bc:
                self.assertEqual(source.tick(root, project, project, "approved-image"), 2)
                self.assertEqual(source.tick(root, project, project, "approved-image"), 0)
                self.assertEqual(source.tick(root, project, project, "approved-image"), 0)
                self.assertEqual(apply.call_count, 2)
                apply.assert_called_with(project, root / "releases/A" / release_id)
                bc.assert_called_once_with(project, root / "releases/BC" / release_id)
                collect.assert_not_called()
            status = source.read_json(root / "status.json")
            self.assertTrue(all(status[name]["primary_release"] == release_id for name in ("A", "BC")))
            self.assertTrue(all("cloud_release" not in status[name] for name in ("A", "BC")))

    def test_ready_local_docker_is_reused(self):
        with patch.object(source.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            source.ensure_local_docker()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][:2], ["docker", "info"])

    def test_local_docker_is_started_and_readiness_is_awaited(self):
        results = [SimpleNamespace(returncode=n) for n in (1, 0, 1, 0)]
        with patch.object(source.subprocess, "run", side_effect=results) as run, \
             patch.object(source.time, "sleep") as sleep:
            source.ensure_local_docker()
        self.assertEqual(run.call_args_list[1].args[0], ["open", "-g", "-a", "Docker"])
        sleep.assert_called_once_with(5)

    def test_local_docker_startup_timeout_preserves_retry(self):
        with patch.object(source.subprocess, "run", return_value=SimpleNamespace(returncode=1)), \
             patch.object(source.time, "monotonic", side_effect=[0, 0, 180]), \
             patch.object(source.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "existing market data retained"):
                source.ensure_local_docker()

    def test_remote_docker_does_not_trigger_desktop_startup(self):
        with patch.object(source.sys, "platform", "darwin"), \
             patch.dict(source.os.environ, {"DOCKER_HOST": "tcp://remote:2375"}), \
             patch.object(source, "ensure_local_docker") as ensure:
            with self.assertRaisesRegex(RuntimeError, "local Docker"):
                source.collect_on_mac(Path("/tmp/source"), "A", Path("/tmp/project"), Path("/tmp/secrets"), "approved-image")
        ensure.assert_not_called()

    def test_explicit_local_image_runs_without_business_container_or_ready(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            project, root, secrets = (base / p for p in ("approved-code", "source", "secrets"))
            project.mkdir(); secrets.mkdir()
            (secrets / "runtime.env").write_text("fixture-only")
            image_id = "sha256:" + "f" * 64
            def output(command, **kwargs):
                if command[:3] == ["docker", "context", "inspect"]:
                    return "unix:///var/run/docker.sock\n"
                if command == ["docker", "image", "inspect", "approved-image", "--format", "{{.Id}}"]:
                    return image_id + "\n"
                raise AssertionError("Business-container inspection is forbidden")
            with patch.object(source.sys, "platform", "darwin"), \
                 patch.dict(source.os.environ, {"DOCKER_HOST": ""}), \
                 patch.object(source, "ensure_local_docker"), \
                 patch.object(source.subprocess, "check_output", side_effect=output), \
                 patch.object(source.subprocess, "run") as run:
                source.collect_on_mac(root, "BC", project, secrets, "approved-image")
            command = run.call_args.args[0]
            self.assertEqual(command[:5], ["docker", "run", "--rm", "--pull", "never"])
            self.assertIn(image_id, command)
            self.assertIn(str(project) + ":/app:ro", command)
            self.assertIn(str(root) + ":/source", command)
            self.assertEqual(command[-6:], ["scripts/local_market_source.py", "collect",
                                           "--root", "/source", "--market", "BC"])
            self.assertFalse((project / ".local-primary").exists())
            self.assertFalse((project / ".local-dev").exists())
            with patch.object(source.sys, "platform", "darwin"), \
                 patch.dict(source.os.environ, {"DOCKER_HOST": ""}), \
                 patch.object(source, "ensure_local_docker"), \
                 patch.object(source.subprocess, "check_output", side_effect=[
                     "unix:///var/run/docker.sock", subprocess.CalledProcessError(1, ["docker", "image", "inspect"])]), \
                 patch.object(source.subprocess, "run") as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    source.collect_on_mac(root, "BC", project, secrets, "missing-image")
                run.assert_not_called()

    def test_collection_publishes_before_primary_then_applies_without_recollection(self):
        import quantdb_refresh as refresh
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            project, code, root = (base / p for p in ("primary", "approved-code", "source"))
            code.mkdir()
            sandbox = project / ".local-dev"
            sandbox.mkdir(parents=True)
            (sandbox / "READY").touch()
            sentinel = sandbox / "preserved"
            sentinel.write_bytes(b"never apply to sandbox")
            clock = datetime(2026, 10, 16, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
            def collect(root, market, project, secrets, image):
                self.assertEqual(project, code)
                data = root / "working/project/data" / source.MARKETS[market][0]
                if market == "A":
                    path = data / "day.parquet"
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"published-price")
                else:
                    raw = data / "releases/raw-fixture"
                    raw.mkdir(parents=True, exist_ok=True)
                    (raw / "manifest.json").write_text('{"fixture": true}')
                    (raw / "bars.csv").write_text("2026-10-15,100\n")
                    source.write_json(data / "CURRENT.json", {
                        "release_id": raw.name, "manifest_sha256": source.digest(raw / "manifest.json")})
            service_states = None
            def docker_state(command, **kwargs):
                if command[0] == "curl":
                    self.assertEqual(command[-1], "http://127.0.0.1:8000/health")
                    return '{"status": "ok"}'
                if command[:3] == ["docker", "context", "inspect"]:
                    return "unix:///var/run/docker.sock"
                self.assertEqual(command[:2], ["docker", "inspect"])
                self.assertEqual(command[2:5], ["quantmind-local-db", "quantmind-local-redis", "quantmind-local-quantmind"])
                if service_states is None:
                    import subprocess
                    raise subprocess.CalledProcessError(1, command)
                return "\n".join(json.dumps(state) for state in service_states)
            with patch.object(source.sys, "platform", "darwin"), \
                 patch.object(source, "now", return_value=clock), \
                 patch.dict(source.os.environ, {"DOCKER_HOST": ""}), \
                 patch.object(source.shutil, "disk_usage", return_value=Mock(free=999*2**30)), \
                 patch.object(source, "collect_on_mac", side_effect=collect) as collector, \
                 patch.object(source.subprocess, "check_output", side_effect=docker_state), \
                 patch.object(refresh, "apply") as apply, patch.object(refresh, "apply_bc") as bc:
                self.assertEqual(source.tick(root, project, base, "approved-image", collector_project=code), 0)
                state = source.read_json(root / "status.json")
                for market, item in state.items():
                    self.assertEqual(item["collection_status"], "collected")
                    self.assertEqual(item["publication_status"], "published")
                    self.assertEqual(item["status"], "awaiting-primary")
                    self.assertEqual(item["apply_status"], "awaiting-primary")
                    self.assertNotIn("primary_release", item)
                    self.assertTrue(source.verify_bundle(root / "releases" / market / item["release_id"], market))
                    item.update(local_release=item["release_id"], cloud_release=item["release_id"], status="applied")
                source.write_json(root / "status.json", state)
                self.assertEqual(source.tick(root, project, base, "approved-image", collector_project=code), 0)
                apply.assert_not_called(); bc.assert_not_called()
                self.assertTrue(all(item["status"] == "awaiting-primary"
                                    for item in source.read_json(root / "status.json").values()))
                (project / ".local-primary").mkdir()
                (project / ".local-primary/READY").touch()
                # Adoption wrote READY, but the formal services do not yet exist.
                self.assertEqual(source.tick(root, project, base, "approved-image", market="BC",
                                             force=True, collector_project=code), 0)
                healthy = {"Running": True, "Health": {"Status": "healthy"}}
                for service_states in (
                    [{"Running": False}, healthy, healthy],
                    [healthy, healthy, {"Running": True, "Health": {"Status": "starting"}}],
                ):
                    self.assertEqual(source.tick(root, project, base, "approved-image", collector_project=code), 0)
                    apply.assert_not_called(); bc.assert_not_called()
                    self.assertTrue(all(item["status"] == "awaiting-primary" and item.get("apply_wait_reason")
                                        for item in source.read_json(root / "status.json").values()))
                service_states = [healthy, healthy, healthy]
                self.assertEqual(source.tick(root, project, base, "approved-image", collector_project=code), 0)
                self.assertEqual(source.tick(root, project, base, "approved-image", collector_project=code), 0)
                self.assertEqual(collector.call_count, 3)
                apply.assert_called_once_with(project, root / "releases/A" / state["A"]["release_id"])
                bc.assert_called_once_with(project, root / "releases/BC" / state["BC"]["release_id"])
            state = source.read_json(root / "status.json")
            self.assertTrue(all(item["primary_release"] == item["release_id"] and item["apply_status"] == "applied"
                                for item in state.values()))
            self.assertEqual(sentinel.read_bytes(), b"never apply to sandbox")

    def test_install_copies_approved_code_and_persists_explicit_collector_contract(self):
        import plistlib
        for start in (False, True):
            with self.subTest(start=start), tempfile.TemporaryDirectory() as d:
                base = Path(d)
                home, code, project, root = (base / p for p in ("home", "code", "primary", "market-source"))
                (home / "Library/LaunchAgents").mkdir(parents=True)
                for name in ("local_market_source.py", "dual_node_snapshot.py", "dual_node_inventory.py",
                             "dual_node_sync.py", "dual_node_check.py", "storage_guard.py", "quantdb_refresh.py"):
                    target = code / "scripts" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((Path(source.__file__).parent / name).read_bytes())
                (code / "deploy").mkdir()
                (code / "deploy/dual-node.env").write_text("fixture=approved\n")
                def launchctl(command, **kwargs):
                    if command[1] == "bootstrap":
                        with source.lock(root / ".source.lock"):
                            pass  # RunAtLoad must be able to acquire the source lock.
                    return SimpleNamespace(returncode=0, stdout="state = waiting\n")
                with patch.object(source.sys, "platform", "darwin"), patch.object(source.Path, "home", return_value=home), \
                     patch.object(source.subprocess, "run", side_effect=launchctl) as run:
                    if start:
                        source.install(project, root, base / "secrets", "approved-image", collector_project=code)
                    else:
                        source.install(project, root, base / "secrets", "approved-image", collector_project=code, start=False)
                definition = plistlib.loads((home / "Library/LaunchAgents/com.quantmind.market-source.plist").read_bytes())
                args = definition["ProgramArguments"]
                self.assertEqual(args[args.index("--project") + 1], str(project))
                self.assertEqual(args[args.index("--collector-project") + 1], str(code))
                self.assertEqual(args[args.index("--collector-image") + 1], "approved-image")
                self.assertNotIn("--host", args)
                installed = base / "market-source-client/scripts/local_market_source.py"
                self.assertEqual(installed.read_bytes(), Path(source.__file__).read_bytes())
                self.assertFalse(project.exists())
                self.assertEqual([call.args[0][1] for call in run.call_args_list],
                                 ["print", "bootout", "bootstrap"] if start else ["print", "bootout"])


    def test_install_never_replaces_or_boots_out_an_active_writer(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "source"
            with patch.object(source.sys, "platform", "darwin"), source.lock(root / ".source.lock"), \
                 patch.object(source.subprocess, "run") as run:
                with self.assertRaises(BlockingIOError):
                    source.install(Path("/missing"), root, Path("/missing"), "approved-image", start=False)
                run.assert_not_called()
            with patch.object(source.sys, "platform", "darwin"), \
                 patch.object(source.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="state = running\n\tpid = 123\n")) as run:
                with self.assertRaisesRegex(RuntimeError, "retain the writer"):
                    source.install(Path("/missing"), root, Path("/missing"), "approved-image", start=False)
                self.assertEqual(run.call_count, 1)
            self.assertFalse((root.parent / "market-source-client").exists())

    def test_tick_and_install_reject_implicit_images_and_removed_cloud_cli(self):
        for action in ("tick", "install"):
            for options in ([], ["--collector-image", "approved-image", "--host", "legacy"]):
                with self.subTest(action=action, options=options), \
                     patch.object(source.sys, "argv", ["source", action, *options]), \
                     patch.object(source, "tick") as tick, patch.object(source, "install") as install:
                    with self.assertRaises(SystemExit) as error:
                        source.main()
                    self.assertEqual(error.exception.code, 2)
                    tick.assert_not_called(); install.assert_not_called()

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

    def test_apply_retry_does_not_repeat_successful_vendor_collection(self):
        import quantdb_refresh as refresh
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local-primary").mkdir()
            (root / ".local-primary/READY").touch()
            clock = datetime(2026, 9, 27, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            def collect(root, market, project, secrets, image):
                data = root / "working/project/data/quantdb/day.parquet"
                data.parent.mkdir(parents=True)
                data.write_bytes(b"collected-price")
            with patch.object(source.sys, "platform", "darwin"), patch.object(source, "now", return_value=clock), \
                 patch.object(source.shutil, "disk_usage", return_value=Mock(free=999*2**30)), \
                 patch.object(refresh, "primary_wait_reason", return_value=None), \
                 patch.object(source, "collect_on_mac", side_effect=collect) as collector, \
                 patch.object(refresh, "apply", side_effect=RuntimeError("busy")) as apply:
                self.assertEqual(source.tick(root, root, root, "approved-image", "A"), 2)
                self.assertEqual(source.tick(root, root, root, "approved-image", "A"), 2)
                collector.assert_called_once()
                self.assertEqual(apply.call_count, 2)
            status = source.read_json(root / "status.json")["A"]
            self.assertEqual(status["publication_status"], "published")
            self.assertEqual(status["apply_status"], "retry_pending")
            bundle = root / "releases/A" / status["release_id"]
            self.assertEqual(source.verify_bundle(bundle, "A")[0]["sha256"], hashlib.sha256(b"collected-price").hexdigest())


    def test_local_backup_rotation_never_registers_legacy_or_research_directories(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d); root = project / "source"
            state = project / ".local-primary"; state.mkdir()
            legacy = state / "quantdb-before-legacy"; legacy.mkdir()
            research = state / "research-input"; research.mkdir()
            for i in range(3):
                backup = state / ("quantdb-before-20260927T000000-" + str(i)*6)
                backup.mkdir()
                source.write_json(state / "QUANTDB_SYNC.json", {"backup": str(backup)})
                source.retain_local_backups(root, project)
            self.assertTrue(legacy.exists()); self.assertTrue(research.exists())
            self.assertFalse((state / "quantdb-before-20260927T000000-000000").exists())
            self.assertEqual(len(source.read_json(root / "primary-backups.json")), 2)


    def test_receiver_cli_does_not_require_host_deploy_topology(self):
        import subprocess, shutil, sys
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            scripts = root / "scripts"; scripts.mkdir()
            for name in ("local_market_source.py", "dual_node_inventory.py", "storage_guard.py"):
                shutil.copy2(Path(source.__file__).parent / name, scripts / name)
            subprocess.run([sys.executable, "-I", str(scripts / "local_market_source.py"), "--help"],
                           stdout=subprocess.DEVNULL, check=True)

    def test_first_source_preparation_preserves_historical_factor_training_prices(self):
        import pandas as pd
        from backend.scripts import quantdb_daily_sync as qdb
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); data = root / "working/project/data/quantdb"
            factor = data / "6_ml_datasets/l1_factors/dt=20160104/data.parquet"
            daily = data / "1_kline_data/daily_backward/dt=20160104/data.parquet"
            factor.parent.mkdir(parents=True);daily.parent.mkdir(parents=True)
            pd.DataFrame({"symbol": ["600000.SH"], "factor_example": [2.5]}).to_parquet(factor, index=False)
            pd.DataFrame({"symbol": ["600000.SH"], **{c: [10.] for c in ("open","high","low","close","volume","amount")}}).to_parquet(daily, index=False)
            with patch.dict("os.environ", {"QM_NODE_ROLE": "archive"}), \
                 patch.object(qdb,"QUANTDB_DATA_DIR",data), patch.object(qdb,"reseed_state",return_value={}), \
                 patch.object(qdb,"sync_parquet",return_value={"errors": []}):
                source.collect(root,"A")
            actual = pd.read_parquet(factor)
            self.assertEqual(actual["close"].iloc[0], 10.)
            self.assertEqual(actual["factor_example"].iloc[0], 2.5)
            self.assertTrue((root / "A-history-prepared.json").exists())


if __name__ == "__main__":
    unittest.main()
