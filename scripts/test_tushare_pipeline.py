"""Offline failure, resume and mirror acceptance; temporary files only."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import (
    Pipeline,
    atomic_json,
    manifest_at,
    verify_data,
)
from scripts.tushare_mirror import checked_file, mirror

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_text()
)
CONFIG = {"priority_start": "20200101"}


class PipelineAcceptance(unittest.TestCase):
    def response(self, values):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "adj_factor"],
                    "items": [["510300" + ".SH", "20260907", x] for x in values],
                },
            },
        )

    def test_checkpoint_resume_normalization_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []

            def handler(request):
                params = json.loads(request.content)["params"]
                calls.append(params)
                return self.response([1, 2] if params["offset"] == 0 else [3])

            pipeline = Pipeline(root, CATALOG)
            pipeline.enqueue(
                "fund_adj", {"trade_date": "20260907", "offset": 0, "limit": 2}
            )
            pipeline.db.commit()
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                pipeline.run(client, "synthetic-token", CONFIG, max_requests=1, pause=0)
                self.assertEqual(pipeline.status(), {"done": 1, "pending": 1})
                first = pipeline.publish()
                pipeline.close()
                pipeline = Pipeline(root, CATALOG)
                pipeline.run(
                    client, "synthetic-token", CONFIG, max_requests=10, pause=0
                )
                self.assertEqual(len(calls), 2)
                self.assertEqual(
                    pipeline.run(client, "synthetic-token", CONFIG, pause=0)[
                        "requests"
                    ],
                    0,
                )
                second = pipeline.publish()
                self.assertNotEqual(first, second)
                self.assertEqual(second, pipeline.publish())
                manifest = verify_data(root, second)
                frames = [
                    pq.read_table(root / d["path"]).to_pylist()
                    for d in manifest["datasets"]
                ]
                self.assertEqual(sum(map(len, frames)), 3)
                self.assertEqual(frames[0][0]["ts_code"], "SH510300")
                self.assertIn("source_ts_code", frames[0][0])
                self.assertFalse(manifest["history_complete"])
                pipeline.close()

    def test_full_page_keeps_quality_failure(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            httpx.Client(
                transport=httpx.MockTransport(lambda _: self.response([0, 2]))
            ) as client,
        ):
            pipeline = Pipeline(tmp, CATALOG)
            pipeline.enqueue(
                "fund_adj", {"trade_date": "20260907", "offset": 0, "limit": 2}
            )
            pipeline.db.commit()
            result = pipeline.run(
                client, "synthetic-token", CONFIG, max_requests=1, pause=0
            )
            self.assertEqual(result["quality"], 1)
            self.assertEqual(result["pending"], 1)
            pipeline.close()

    def test_ignored_offset_is_blocked_not_infinite_pagination(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            httpx.Client(
                transport=httpx.MockTransport(lambda _: self.response([1, 2]))
            ) as client,
        ):
            pipeline = Pipeline(tmp, CATALOG)
            pipeline.enqueue(
                "fund_adj", {"trade_date": "20260907", "offset": 0, "limit": 2}
            )
            pipeline.db.commit()
            result = pipeline.run(client, "synthetic-token", CONFIG, pause=0)
            self.assertEqual(result["requests"], 2)
            self.assertEqual(result["blocked"], 1)
            pipeline.close()

    def test_transport_backoff_and_blocked_row_cap(self):
        def failure(request):
            raise httpx.ConnectError("synthetic-token", request=request)

        with (
            tempfile.TemporaryDirectory() as tmp,
            httpx.Client(transport=httpx.MockTransport(failure)) as client,
        ):
            pipeline = Pipeline(tmp, CATALOG)
            pipeline.enqueue("ci_daily", {"trade_date": "20260907"})
            pipeline.db.commit()
            self.assertEqual(
                pipeline.run(client, "synthetic-token", CONFIG, pause=0)["requests"], 1
            )
            self.assertEqual(
                pipeline.run(client, "synthetic-token", CONFIG, pause=0)["requests"], 0
            )
            self.assertNotIn(
                "synthetic-token",
                pipeline.db.execute("select result from jobs").fetchone()[0],
            )
            pipeline.close()

    def test_mirror_interruption_retry_noop_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "cloud", Path(tmp) / "mac"
            pipeline = Pipeline(source, CATALOG)
            with httpx.Client(
                transport=httpx.MockTransport(lambda _: self.response([1]))
            ) as client:
                pipeline.enqueue(
                    "fund_adj", {"trade_date": "20260907", "offset": 0, "limit": 2}
                )
                pipeline.db.commit()
                pipeline.run(client, "synthetic-token", CONFIG, pause=0)
            first = pipeline.publish()
            shutil.copytree(source, target)
            before = (target / "CURRENT.json").read_bytes()
            with httpx.Client(
                transport=httpx.MockTransport(lambda _: self.response([2]))
            ) as client:
                pipeline.enqueue(
                    "fund_adj",
                    {"trade_date": "20260907", "offset": 0, "limit": 2},
                    epoch="revision",
                )
                pipeline.db.commit()
                pipeline.run(client, "synthetic-token", CONFIG, pause=0)
            second = pipeline.publish()

            def download(cmd, **kwargs):
                listing = next(
                    v.split("=", 1)[1] for v in cmd if v.startswith("--files-from=")
                )
                for name in Path(listing).read_text().splitlines():
                    (target / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / name, target / name)

            def ssh(cmd, **kwargs):
                if cmd[-1].endswith("CURRENT.json"):
                    return (source / "CURRENT.json").read_bytes()
                return (source / "releases" / second / "manifest.json").read_bytes()

            with patch(
                "scripts.tushare_mirror.subprocess.check_output", side_effect=ssh
            ):
                with patch(
                    "scripts.tushare_mirror.subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, "rsync"),
                ):
                    with self.assertRaises(subprocess.CalledProcessError):
                        mirror(target)
                self.assertEqual((target / "CURRENT.json").read_bytes(), before)
                verify_data(target, first)
                with patch(
                    "scripts.tushare_mirror.subprocess.run", side_effect=download
                ):
                    self.assertGreater(mirror(target)["downloaded_files"], 0)
                    with patch(
                        "scripts.tushare_mirror.checked_file", wraps=checked_file
                    ) as checked:
                        unchanged = mirror(target)
                        self.assertEqual(unchanged["downloaded_files"], 0)
                        self.assertEqual(checked.call_count, unchanged["files"])
                manifest = verify_data(target, second)
                one = next(iter(manifest["files"]))
                (target / one).write_bytes(b"corrupted")
                with self.assertRaises(ValueError):
                    verify_data(target, second)
                with patch(
                    "scripts.tushare_mirror.subprocess.run", side_effect=download
                ):
                    self.assertEqual(mirror(target)["downloaded_files"], 1)
            pipeline.close()

    def test_mirror_rejects_parent_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            outside = root / "outside"
            outside.mkdir()
            payload = outside / "data.json"
            payload.write_bytes(b"data")
            (root / "objects").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                checked_file(
                    root / "objects/data.json", {"bytes": 4, "sha256": "ignored"}
                )

    def test_offline_reader_selects_latest_observation(self):
        from backend.shared.tushare_store import read_dataset
        import socket

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline = Pipeline(root, CATALOG)
            for value, epoch in ((1, "old"), (2, "new")):
                with httpx.Client(
                    transport=httpx.MockTransport(lambda _, v=value: self.response([v]))
                ) as client:
                    pipeline.enqueue(
                        "fund_adj",
                        {"trade_date": "20260907", "offset": 0, "limit": 2},
                        epoch=epoch,
                    )
                    pipeline.db.commit()
                    pipeline.run(client, "synthetic-token", CONFIG, pause=0)
            release = pipeline.publish()
            with (
                patch.object(
                    socket.socket,
                    "connect",
                    side_effect=AssertionError("network forbidden"),
                ),
                patch(
                    "backend.shared.tushare_pipeline.get_secret",
                    side_effect=AssertionError("secret forbidden"),
                ),
            ):
                rows = read_dataset(root, release, "fund_adj").to_pylist()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["adj_factor"], 2)
                with self.assertRaises(ValueError):
                    read_dataset(root, release, "ci_daily")
            pipeline.close()

    def test_initialization_is_idempotent_with_daily_generations(self):
        from datetime import date

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline = Pipeline(root, CATALOG)
            config = {
                **CONFIG,
                "history_start": "20260101",
                "seed_release": "probe-fixture",
            }
            atomic_json(root / "releases/probe-fixture/manifest.json", {"results": []})
            pipeline.initialize(config, date(2026, 9, 9))
            count = pipeline.status()["pending"]
            pipeline.initialize(config, date(2026, 9, 9))
            self.assertEqual(pipeline.status()["pending"], count)
            pipeline.initialize(config, date(2026, 9, 10))
            self.assertGreater(pipeline.status()["pending"], count)
            pipeline.close()

    def test_rate_reservation_survives_worker_reopen(self):
        now = [100.0]
        posts = []

        def sleep(seconds):
            now[0] += seconds

        def response(_):
            posts.append(now[0])
            return self.response([1])

        config = {
            **CONFIG,
            "requests_per_minute": 240,
            "api_requests_per_minute": {"fund_adj": 60},
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "backend.shared.tushare_pipeline.time.time", side_effect=lambda: now[0]
            ),
            patch(
                "backend.shared.tushare_pipeline.time.monotonic",
                side_effect=lambda: now[0],
            ),
            patch("backend.shared.tushare_pipeline.time.sleep", side_effect=sleep),
            httpx.Client(transport=httpx.MockTransport(response)) as client,
        ):
            for epoch in ("first", "second"):
                p = Pipeline(tmp, CATALOG)
                p.enqueue(
                    "fund_adj",
                    {"trade_date": "20260907", "offset": 0, "limit": 2},
                    epoch=epoch,
                )
                p.db.commit()
                p.run(client, "synthetic-token", config, max_requests=1, pause=0)
                p.close()
            self.assertGreaterEqual(posts[1] - posts[0], 1)

    def test_slow_api_does_not_block_ready_other_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            import time

            p = Pipeline(tmp, CATALOG)
            p.enqueue(
                "fund_adj",
                {"trade_date": "20260907", "offset": 0, "limit": 2},
                priority=0,
            )
            p.enqueue("fund_daily", {"trade_date": "20260907"}, priority=1)
            p.db.execute(
                "INSERT INTO request_gates VALUES(?,?)",
                ("api:fund_adj", time.time() + 60),
            )
            p.db.commit()
            row = p.next_job({"requests_per_minute": 240}, time.monotonic() + 1)
            self.assertEqual(json.loads(row["job"])["api_name"], "fund_daily")
            p.close()

    def test_frequency_error_is_not_permission_denial(self):
        from backend.shared.tushare_intake import assess_response, capture_sample

        self.assertEqual(
            assess_response(
                {"code": 2002, "msg": "每分钟最多访问该接口500次"}, 1000, []
            )["status"],
            "rate_limited",
        )
        self.assertEqual(
            assess_response({"code": 40203, "msg": "没有访问该接口的权限"}, 1000, [])[
                "status"
            ],
            "permission_denied",
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            httpx.Client(
                transport=httpx.MockTransport(lambda _: httpx.Response(429))
            ) as client,
        ):
            result = capture_sample(
                client,
                "synthetic-token",
                {
                    "api_name": "news",
                    "params": {},
                    "fields": "title",
                    "row_cap": 1000,
                    "required_fields": [],
                },
                Path(tmp),
            )
            self.assertEqual(result["status"], "rate_limited")

    def test_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            from backend.shared.tushare_intake import digest, json_bytes

            body = {"files": {"../outside": {"sha256": "0" * 64, "bytes": 0}}}
            release = "data-" + digest(json_bytes(body))
            atomic_json(Path(tmp) / "releases" / release / "manifest.json", body)
            with self.assertRaises(ValueError):
                manifest_at(Path(tmp), release)


if __name__ == "__main__":
    unittest.main()
