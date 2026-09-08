"""Isolated document task/routing checks; no Celery broker, token or network.

Pass --backend-root to a parallel integration checkout until it is merged.
"""

import argparse
import ast
import fcntl
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

options = argparse.ArgumentParser(add_help=False)
options.add_argument(
    "--backend-root", type=Path, default=Path(__file__).resolve().parents[1]
)
args, remaining = options.parse_known_args()
sys.path.insert(0, str(args.backend_root.resolve()))
sys.argv = [sys.argv[0], *remaining]

from backend.shared import tushare_pipeline as pipeline  # noqa: E402
from backend.shared import tushare_documents as documents  # noqa: E402
from backend.shared import runtime_secrets  # noqa: E402
import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


class TaskApp:
    def __init__(self):
        self.send_task = Mock()
        self.options = {}

    def task(self, **options):
        def decorate(function):
            self.options[options["name"]] = options
            return function

        return decorate


class DocumentWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tushare-document-task-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {"enable_documents": True, "document_execution": "worker"}
        (self.root / "ENABLED").touch()
        self.save_config()
        self.app = TaskApp()
        stub = types.ModuleType("backend.services.engine.qlib_app.celery_config")
        stub.celery_app = self.app
        with patch.dict(sys.modules, {stub.__name__: stub}):
            spec = importlib.util.spec_from_file_location(
                "candidate_document_tasks",
                REPO / "backend/services/engine/tasks/tushare_tasks.py",
            )
            self.tasks = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.tasks)
        self.addCleanup(patch.stopall)
        patch.object(pipeline, "ROOT", self.root).start()
        self.authority = patch.object(pipeline, "authority").start()
        self.tick = patch.object(
            pipeline, "tick", return_value={"status": "api_done"}
        ).start()
        self.real_run = documents.run_documents
        self.run = patch.object(
            documents, "run_documents", return_value={"status": "ok", "processed": 3}
        ).start()
        patch.object(
            self.tasks.shutil,
            "disk_usage",
            return_value=types.SimpleNamespace(free=101 * 2**30),
        ).start()
        self.secret = patch.object(
            pipeline, "get_secret", side_effect=AssertionError("No token reads")
        ).start()
        self.other_secret = patch.object(
            runtime_secrets, "get_secret", side_effect=AssertionError("No credentials")
        ).start()
        self.connect = patch.object(
            socket.socket, "connect", side_effect=AssertionError("No network")
        ).start()
        self.dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("No DNS")
        ).start()

    def tearDown(self):
        for mock in (self.secret, self.other_secret, self.connect, self.dns):
            mock.assert_not_called()

    def save_config(self):
        (self.root / "pipeline-config.json").write_text(json.dumps(self.config))

    def test_acquire_dispatches_before_tick_to_separate_queue(self):
        order = []
        self.app.send_task.side_effect = lambda *a, **k: order.append("documents")
        self.tick.side_effect = lambda: order.append("api") or {"status": "api_done"}
        result = self.tasks.tushare_acquire()
        self.assertEqual(order, ["documents", "api"])
        self.app.send_task.assert_called_once_with(
            "engine.tasks.tushare_documents", queue="tushare_documents", expires=110
        )
        self.assertEqual(result["document_dispatch"], {"status": "queued"})
        self.run.assert_not_called()
        self.authority.assert_called_once()

    def test_dispatch_failure_preserves_api_continuation(self):
        self.app.send_task.side_effect = RuntimeError("mock unavailable broker")
        result = self.tasks.tushare_acquire()
        self.assertEqual(result["document_dispatch"]["status"], "dispatch_failed")
        self.tick.assert_called_once()

    def test_mode_and_operator_switch_disable_dispatch_and_consumption(self):
        for enabled, mode in ((False, "worker"), (True, "inline"), (True, None)):
            self.config = {"enable_documents": enabled, "document_execution": mode}
            self.save_config()
            self.tasks.tushare_acquire()
            self.assertEqual(self.tasks.tushare_documents()["status"], "disabled")
        self.config = {"enable_documents": True, "document_execution": "worker"}
        self.save_config()
        (self.root / "ENABLED").unlink()
        self.tasks.tushare_acquire()
        self.assertEqual(self.tasks.tushare_documents()["status"], "disabled")
        self.app.send_task.assert_not_called()
        self.run.assert_not_called()

    def test_worker_bounds_disk_guard_and_atomic_status(self):
        result = self.tasks.tushare_documents()
        self.run.assert_called_once_with(
            self.root, max_documents=100, max_seconds=90, download_workers=1
        )
        self.assertEqual(
            json.loads((self.root / "document-worker-status.json").read_bytes()), result
        )
        self.assertEqual(result["processed"], 3)
        self.config.update(
            document_worker_max_documents=7,
            document_worker_max_seconds=12.5,
            document_download_workers=2,
        )
        self.save_config()
        self.tasks.tushare_documents()
        self.run.assert_called_with(
            self.root, max_documents=7, max_seconds=12.5, download_workers=2
        )
        for key, value in (
            ("document_download_workers", 3),
            ("document_download_workers", True),
            ("document_worker_max_documents", 101),
            ("document_worker_max_documents", True),
            ("document_worker_max_seconds", 91),
            ("document_worker_max_seconds", float("nan")),
        ):
            self.config = {
                "enable_documents": True,
                "document_execution": "worker",
                key: value,
            }
            self.save_config()
            with self.assertRaises(ValueError):
                self.tasks.tushare_documents()
        self.run.reset_mock()
        with patch.object(
            self.tasks.shutil,
            "disk_usage",
            return_value=types.SimpleNamespace(free=99 * 2**30),
        ):
            self.assertEqual(
                self.tasks.tushare_documents()["status"], "blocked_disk_reserve"
            )
        self.run.assert_not_called()

    def test_authority_denial_precedes_reads_and_writes(self):
        self.authority.side_effect = ValueError("not authority")
        (self.root / "pipeline-config.json").unlink()
        with self.assertRaisesRegex(ValueError, "not authority"):
            self.tasks.tushare_documents()
        with self.assertRaisesRegex(ValueError, "not authority"):
            self.tasks.tushare_acquire()
        self.assertFalse((self.root / "document-worker-status.json").exists())
        self.app.send_task.assert_not_called()
        self.run.assert_not_called()

    def test_unexpected_worker_error_records_failure_without_hiding_it(self):
        self.run.side_effect = RuntimeError("synthetic queue failure")
        with self.assertRaises(RuntimeError):
            self.tasks.tushare_documents()
        status = json.loads((self.root / "document-worker-status.json").read_bytes())
        self.assertEqual(status["status"], "worker_failed")
        self.assertEqual(status["error_type"], "RuntimeError")

    def test_existing_lock_rejects_duplicate_consumer(self):
        self.run.side_effect = self.real_run
        with (self.root / "documents.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(
                self.tasks.tushare_documents()["status"], "already_running"
            )
        self.assertEqual(self.tasks.tushare_documents()["processed"], 0)

    def test_route_resource_bounds_and_snapshot_writer(self):
        options = self.app.options["engine.tasks.tushare_documents"]
        self.assertEqual(
            (options["soft_time_limit"], options["time_limit"]), (105, 110)
        )
        self.assertTrue(options["acks_late"])
        self.assertTrue(options["reject_on_worker_lost"])
        config = (
            REPO / "backend/services/engine/qlib_app/celery_config.py"
        ).read_text()
        tree = ast.parse(config)
        routes = next(
            k.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for k in node.keywords
            if k.arg == "task_routes"
        )
        # Other routes refer to variables; evaluate only the document entry.
        index = [key.value for key in routes.keys].index(
            "engine.tasks.tushare_documents"
        )
        self.assertEqual(
            ast.literal_eval(routes.values[index]), {"queue": "tushare_documents"}
        )
        self.assertEqual(config.count('"engine.tasks.tushare_documents"'), 1)
        services = yaml.load(
            (REPO / "deploy/compose.cloud.yml").read_text(), Loader=yaml.BaseLoader
        )["services"]
        worker = services["tushare-document-worker"]
        self.assertEqual(worker["mem_limit"], "1536m")
        self.assertEqual(worker["cpus"], "0.5")
        self.assertEqual(worker["environment"]["QM_NODE_ROLE"], "authority")
        self.assertIn("-Q tushare_documents", worker["command"])
        self.assertIn("--concurrency=1 --prefetch-multiplier=1", worker["command"])
        snapshot = (REPO / "scripts/dual_node_snapshot.py").read_text()
        writers = next(
            node.value
            for node in ast.parse(snapshot).body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "WRITERS" for t in node.targets)
        )
        self.assertIn("quantmind-tushare-document-worker", ast.literal_eval(writers))
        self.assertIn('"engine.tasks.tushare_documents"', snapshot)


if __name__ == "__main__":
    unittest.main()
