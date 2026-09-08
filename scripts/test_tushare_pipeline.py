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

    def test_new_mirror_reads_multiple_historical_releases_without_databases(self):
        from backend.shared.tushare_store import read_dataset
        import socket

        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp).resolve() / "cloud", Path(tmp).resolve() / "mac"
            pipeline = Pipeline(source, CATALOG)
            releases = []
            for value in (1, 2, 3):
                with httpx.Client(
                    transport=httpx.MockTransport(lambda _, v=value: self.response([v]))
                ) as client:
                    pipeline.enqueue(
                        "fund_adj",
                        {"trade_date": "20260907", "offset": 0, "limit": 2},
                        epoch=str(value),
                    )
                    pipeline.db.commit()
                    pipeline.run(client, "synthetic-token", CONFIG, pause=0)
                releases.append(pipeline.publish())
                self.assertEqual(releases[-1], pipeline.publish())
            before = manifest_at(source, releases[-1])["archive"]["recovery"][
                "archived_releases"
            ]
            (source / "archive.sqlite").unlink()
            repaired = pipeline.publish()
            after = manifest_at(source, repaired)["archive"]["recovery"][
                "archived_releases"
            ]
            self.assertTrue(all(item in after for item in before))
            self.assertEqual(repaired, pipeline.publish())
            releases.append(repaired)
            latest = manifest_at(source, releases[-1])
            for name in latest["files"]:
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, dest)
            dest = target / "releases" / releases[-1] / "manifest.json"
            dest.parent.mkdir(parents=True)
            shutil.copyfile(source / "releases" / releases[-1] / "manifest.json", dest)
            self.assertFalse((target / "archive.sqlite").exists())
            with patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network forbidden"),
            ):
                for value, release in zip((1, 2, 3, 3), releases, strict=True):
                    verify_data(target, release)
                    rows = read_dataset(target, release, "fund_adj").to_pylist()
                    self.assertEqual([r["adj_factor"] for r in rows], [value])
            pipeline.close()

    def test_publication_recovers_retention_interruptions_without_version_loop(self):
        from backend.shared.tushare_archive import retain_release, recover_archive
        from backend.shared.tushare_pipeline import atomic_bytes

        for initialized in (False, True):
            with (
                self.subTest(initialized=initialized),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp).resolve()
                pipeline = Pipeline(root, CATALOG)
                if initialized:
                    recover_archive(root)
                first = pipeline.publish()
                raw = (root / "releases" / first / "manifest.json").read_bytes()
                # A copy may survive before the archive DB transaction commits.
                atomic_bytes(root / "archives" / (first[5:] + ".json"), raw)
                self.assertEqual(first, pipeline.publish())
                retain_release(root, first)
                for _ in range(3):
                    self.assertEqual(first, pipeline.publish())
                pipeline.enqueue("fund_adj", {"trade_date": "20260907"})
                pipeline.db.commit()
                original = atomic_json

                def interrupted(path, value, original=original):
                    if path.name == "CURRENT.json":
                        raise InterruptedError("before CURRENT swap")
                    return original(path, value)

                with patch(
                    "backend.shared.tushare_pipeline.atomic_json",
                    side_effect=interrupted,
                ):
                    with self.assertRaises(InterruptedError):
                        pipeline.publish()
                self.assertEqual(
                    json.loads((root / "CURRENT.json").read_bytes())["release_id"],
                    first,
                )
                second = pipeline.publish()
                self.assertNotEqual(first, second)
                self.assertEqual(second, pipeline.publish())
                verify_data(root, second)
                # Real recovery changes still produce a release, rather than
                # disappearing into the CURRENT-self projection.
                recover_archive(root, rescan_releases=True, max_items=10000)
                third = pipeline.publish()
                self.assertNotEqual(second, third)
                self.assertEqual(third, pipeline.publish())
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
            source, target = Path(tmp).resolve() / "cloud", Path(tmp).resolve() / "mac"
            pipeline = Pipeline(source, CATALOG)
            from backend.shared import tushare_documents as documents

            documents._document_db(source).close()
            evidence = documents._save(
                source,
                "attachments",
                ".bin",
                b"<html>Unexpected response</html>",
                "application/octet-stream",
            )
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
                self.assertIn(evidence["path"], manifest["files"])
                self.assertEqual(
                    (target / evidence["path"]).read_bytes(),
                    b"<html>Unexpected response</html>",
                )
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

    def test_named_hourly_quota_preserves_other_work_and_survives_restart(self):
        import time

        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(Path(tmp), CATALOG)
            key = p.enqueue("hk_daily", {"trade_date": "20260907"}, priority=1)
            p.db.execute("UPDATE jobs SET tries=5 WHERE id=?", (key,))
            p.db.commit()
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200,
                        json={
                            "code": 40203,
                            "msg": "抱歉，您访问接口(hk_daily)频率超限(1次/小时)，具体频次详情。",
                        },
                    )
                )
            ) as client:
                p.run(
                    client,
                    "fixture-token",
                    {"requests_per_minute": 240},
                    max_requests=1,
                    pause=0,
                )
            self.assertEqual(
                p.db.execute("SELECT state FROM jobs WHERE id=?", (key,)).fetchone()[0],
                "pending",
            )
            self.assertGreater(
                p.db.execute(
                    "SELECT next_at FROM request_gates WHERE scope='api:hk_daily'"
                ).fetchone()[0],
                time.time() + 3500,
            )
            p.enqueue("fund_daily", {"trade_date": "20260907"}, priority=2)
            p.db.commit()
            p.close()
            p = Pipeline(Path(tmp), CATALOG)
            next_row = p.next_job({"requests_per_minute": 240}, time.monotonic() + 1)
            self.assertEqual(json.loads(next_row["job"])["api_name"], "fund_daily")
            # Simulate the hourly wait elapsing without sleeping. Learned quota
            # must space the next successful request, not merely its retry.
            p.db.execute("UPDATE jobs SET state='done' WHERE id=?", (next_row["id"],))
            p.db.execute("UPDATE jobs SET retry_after=0 WHERE id=?", (key,))
            p.db.execute("UPDATE request_gates SET next_at=0")
            p.db.commit()
            next_row = p.next_job({"requests_per_minute": 240}, time.monotonic() + 1)
            self.assertEqual(json.loads(next_row["job"])["api_name"], "hk_daily")
            self.assertGreater(
                p.db.execute(
                    "SELECT next_at FROM request_gates WHERE scope='api:hk_daily'"
                ).fetchone()[0],
                time.time() + 3500,
            )
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

    def test_archived_manifest_fallback_rejects_corruption_and_symlinks(self):
        from backend.shared.tushare_intake import digest, json_bytes

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            raw = json_bytes({"files": {}, "datasets": []})
            sha = digest(raw)
            archived = root / "archives" / (sha + ".json")
            archived.parent.mkdir()
            archived.write_bytes(raw)
            self.assertEqual(manifest_at(root, "data-" + sha)["datasets"], [])
            original = root / "releases" / ("data-" + sha) / "manifest.json"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                manifest_at(root, "data-" + sha)
            original.unlink()
            original.symlink_to(archived)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                manifest_at(root, "data-" + sha)
            original.unlink()
            archived.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                manifest_at(root, "data-" + sha)

    def test_binary_evidence_only_allowed_under_attachments(self):
        from backend.shared.tushare_intake import digest, json_bytes

        with tempfile.TemporaryDirectory() as tmp:
            for family in ("objects", "parquet", "documents", "archives"):
                body = {
                    "files": {
                        family + "/" + "a" * 64 + ".bin": {
                            "sha256": "a" * 64,
                            "bytes": 0,
                        }
                    }
                }
                release = "data-" + digest(json_bytes(body))
                atomic_json(Path(tmp) / "releases" / release / "manifest.json", body)
                with self.assertRaisesRegex(ValueError, "Invalid object path"):
                    manifest_at(Path(tmp), release)


if __name__ == "__main__":
    unittest.main()
