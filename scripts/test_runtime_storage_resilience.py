"""Offline regression tests: never import application settings or open real services."""

import ast
import asyncio
import errno
import importlib.util
import io
import json
import logging
import logging.handlers
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def module_at(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def consumer_class(client, logger):
    tree = ast.parse(
        (
            ROOT / "backend/services/trade/services/sandbox_signal_consumer.py"
        ).read_text()
    )
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "SandboxSignalConsumer"
    )
    cls.body = [
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"__init__", "start", "stop", "_consume_batch", "_wait_for_poll"}
    ]
    ns = {
        "asyncio": asyncio,
        "time": time,
        "json": json,
        "logger": logger,
        "redis_client": types.SimpleNamespace(client=client),
        "SimulationAccountManager": Mock(),
        "httpx": types.SimpleNamespace(AsyncClient=object),
        "_SIGNAL_QUEUE": "offline",
        "_BATCH_SIZE": 50,
        "_POLL_INTERVAL": 0.2,
        "_RETRY_INITIAL": 1.0,
        "_RETRY_MAX": 30.0,
        "_ERROR_LOG_INTERVAL": 60.0,
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "<consumer>", "exec"), ns)
    return ns["SandboxSignalConsumer"]


class ConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_error_ends_batch_after_one_read(self):
        client = Mock()
        client.lpop.side_effect = RuntimeError("MISCONF")
        consumer = consumer_class(client, Mock())()
        self.assertFalse(await consumer._consume_batch())
        self.assertEqual(client.lpop.call_count, 1)

    async def test_processing_error_does_not_pause_or_requeue(self):
        client = Mock()
        client.lpop.side_effect = ["{}", "{}", None]
        consumer = consumer_class(client, Mock())()
        consumer._process_signal = AsyncMock(side_effect=[ValueError("bad"), None])
        self.assertTrue(await consumer._consume_batch())
        self.assertEqual(consumer._process_signal.await_count, 2)
        client.rpush.assert_not_called()

    async def test_backoff_is_bounded_and_recovers_once(self):
        logger = Mock()
        client = Mock()
        client.lpop.side_effect = [RuntimeError("offline")] * 8 + [None, None]
        consumer = consumer_class(client, logger)()
        waits = []

        async def wait(delay):
            waits.append(delay)
            if len(waits) == 10:
                await consumer.stop()

        consumer._wait_for_poll = wait
        await asyncio.wait_for(consumer.start(), timeout=1.0)
        self.assertEqual(waits, [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 0.2, 0.2])
        self.assertEqual(logger.warning.call_count, 1)
        self.assertEqual(sum("恢复" in str(c) for c in logger.info.call_args_list), 1)

    async def test_periodic_outage_summary_and_missing_client(self):
        logger = Mock()
        cls = consumer_class(None, logger)
        consumer = cls()
        clock = Mock(side_effect=[0.0, 10.0, 61.0])
        cls.start.__globals__["time"] = types.SimpleNamespace(monotonic=clock)
        waits = []

        async def wait(delay):
            waits.append(delay)
            if len(waits) == 3:
                await consumer.stop()

        consumer._wait_for_poll = wait
        await consumer.start()
        self.assertEqual(waits, [1.0, 2.0, 4.0])
        self.assertEqual(logger.warning.call_count, 2)

    async def test_stop_interrupts_backoff(self):
        client = Mock()
        client.lpop.side_effect = RuntimeError("offline")
        consumer = consumer_class(client, Mock())()
        task = asyncio.create_task(consumer.start())
        await asyncio.sleep(0.01)
        await consumer.stop()
        await asyncio.wait_for(task, timeout=0.2)
        self.assertFalse(consumer.is_running)

    async def test_cancel_interrupts_backoff(self):
        client = Mock()
        client.lpop.side_effect = RuntimeError("offline")
        consumer = consumer_class(client, Mock())()
        task = asyncio.create_task(consumer.start())
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.wait_for(task, timeout=0.2)
        self.assertFalse(consumer.is_running)


class LogTests(unittest.TestCase):
    def test_enospc_is_suppressed_then_reopens_and_recovers(self):
        tree = ast.parse((ROOT / "backend/shared/logging_config.py").read_text())
        classes = [
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "ResilientRotatingFileHandler"
        ]
        self.assertTrue(classes, "need ENOSPC resilient handler")
        ns = {
            "logging": logging,
            "errno": errno,
            "sys": __import__("sys"),
            "time": time,
            "Path": Path,
        }
        exec(
            compile(ast.Module(body=classes, type_ignores=[]), "<logging>", "exec"), ns
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            handler = ns["ResilientRotatingFileHandler"](
                str(Path(tmp) / "app.log"), maxBytes=1024, backupCount=1, delay=True
            )
            record = logging.LogRecord("test", 20, "", 1, "hello", (), None)
            with (
                patch.object(time, "monotonic", return_value=1.0),
                patch.object(
                    handler, "_open", side_effect=OSError(errno.ENOSPC, "full")
                ) as opened,
            ):
                for _ in range(100):
                    handler.emit(record)
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(len(stderr.getvalue().splitlines()), 1)
                self.assertNotIn("Traceback", stderr.getvalue())
            with patch.object(time, "monotonic", return_value=100.0):
                handler.emit(record)
                handler.emit(record)
            handler.close()
            self.assertEqual((Path(tmp) / "app.log").read_text().count("hello"), 2)
            self.assertEqual(len(stderr.getvalue().splitlines()), 2)


class HealthTests(unittest.TestCase):
    def test_http_200_degraded_is_rejected(self):
        health = module_at("scripts/check_cloud_health.py")
        response = Mock(status=200)
        response.read.return_value = b'{"status":"degraded"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(health.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            self.assertFalse(health.healthy())

    def test_readiness_rejects_persistence_error_and_low_space(self):
        path = ROOT / "scripts/check_storage_readiness.py"
        self.assertTrue(path.exists(), "need separate storage readiness report")
        readiness = module_at("scripts/check_storage_readiness.py")
        state = {
            "aof_enabled": 1,
            "aof_last_write_status": "err",
            "aof_last_bgrewrite_status": "ok",
            "rdb_last_bgsave_status": "ok",
        }
        self.assertFalse(readiness.redis_persistence_ready(state))
        state["aof_last_write_status"] = "ok"
        self.assertTrue(readiness.redis_persistence_ready(state))
        self.assertFalse(readiness.redis_persistence_ready({}))
        with (
            patch.object(
                readiness.shutil,
                "disk_usage",
                return_value=types.SimpleNamespace(total=10000, used=9999, free=1),
            ),
            patch.object(readiness, "probe_dependency", return_value={"ok": True}),
        ):
            report = readiness.readiness_report(min_free_bytes=100)
        self.assertFalse(report["ready"])
        self.assertFalse(report["disks"]["/data"]["ok"])

    def test_healthy_and_malformed_payloads(self):
        health = module_at("scripts/check_cloud_health.py")
        for payload, expected in [
            (b'{"status":"healthy"}', True),
            (b"not-json", False),
            (b"{}", False),
            (b"[]", False),
        ]:
            response = Mock(status=200)
            response.read.return_value = payload
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch.object(health.urllib.request, "build_opener") as opener:
                opener.return_value.open.return_value = response
                self.assertEqual(health.healthy(), expected)

    def test_dependency_failure_is_not_ready_and_errors_are_sanitized(self):
        readiness = module_at("scripts/check_storage_readiness.py")
        with (
            patch.object(
                readiness.shutil,
                "disk_usage",
                return_value=types.SimpleNamespace(total=1000, used=0, free=1000),
            ),
            patch.object(
                readiness, "probe_dependency", side_effect=[{"ok": False}, {"ok": True}]
            ),
        ):
            self.assertFalse(readiness.readiness_report(100)["ready"])
        with patch.object(
            readiness.subprocess, "run", side_effect=OSError("credential-like text")
        ):
            report = readiness.probe_dependency("postgres")
        self.assertEqual(report, {"ok": False, "error": "probe_failed"})

    def test_readiness_accepts_healthy_dependencies_and_reports_disk_errors(self):
        readiness = module_at("scripts/check_storage_readiness.py")
        with (
            patch.object(
                readiness.shutil,
                "disk_usage",
                return_value=types.SimpleNamespace(total=1000, used=0, free=1000),
            ),
            patch.object(readiness, "probe_dependency", return_value={"ok": True}),
        ):
            self.assertTrue(readiness.readiness_report(100)["ready"])
        with (
            patch.object(
                readiness.shutil, "disk_usage", side_effect=OSError("missing")
            ),
            patch.object(readiness, "probe_dependency", return_value={"ok": True}),
        ):
            self.assertFalse(readiness.readiness_report(100)["ready"])

    def test_redis_info_failures_are_not_ping_success(self):
        readiness = module_at("scripts/check_storage_readiness.py")
        for field in (
            "aof_last_write_status",
            "aof_last_bgrewrite_status",
            "rdb_last_bgsave_status",
        ):
            info = {
                "aof_enabled": 1,
                "aof_last_write_status": "ok",
                "aof_last_bgrewrite_status": "ok",
                "rdb_last_bgsave_status": "ok",
            }
            info[field] = "err"
            result = types.SimpleNamespace(
                stdout=json.dumps({"ok": True, "persistence": info})
            )
            with patch.object(readiness.subprocess, "run", return_value=result):
                self.assertFalse(readiness.probe_dependency("redis")["ok"])


if __name__ == "__main__":
    unittest.main()
