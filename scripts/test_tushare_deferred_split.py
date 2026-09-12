"""Real immutable capture + SQLite; no upstream/credentials, simulated slow stages."""

import hashlib
import json
import unittest
from unittest.mock import patch

import httpx

import test_tushare_observed_fanout as fixture

module = fixture.module


class DeferredSplit(unittest.TestCase):
    parent = fixture.ObservedFanout.parent
    children = fixture.ObservedFanout.children
    evidence = fixture.ObservedFanout.evidence

    def setUp(self):
        fixture.ObservedFanout.setUp(self)
        self.now = 0.0
        self.calls = []
        self.guard = patch.object(
            module.time, "monotonic", side_effect=lambda: self.now
        )
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.spec_guard = patch.dict(
            module.EXTENDED_CONTRACTS["moneyflow_dc"], {"row_cap": 2}
        )
        self.spec_guard.start()
        self.addCleanup(self.spec_guard.stop)
        self.config = {"priority_start": "20200101"}

    def respond(self, request):
        body = json.loads(request.content)
        self.calls.append(body["params"])
        fields = body["fields"].split(",")
        records = [
            {"ts_code": code, "trade_date": "20260904"}
            for code in ("600036.SH", "830001.BJ")
        ]
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": fields,
                    "items": [[row.get(f) for f in fields] for row in records],
                    "has_more": True,
                },
            },
        )

    def run_once(self, requests=1, seconds=90, respond=None):
        with httpx.Client(
            transport=httpx.MockTransport(respond or self.respond)
        ) as client:
            return self.p.run(
                client, "fixture-only", self.config, requests, seconds, pause=0
            )

    def stored(self, row):
        return dict(
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        )

    def attempts(self):
        return [
            tuple(r)
            for r in self.p.db.execute("SELECT * FROM attempts ORDER BY job_id,attempt")
        ]

    def reopen(self):
        self.p.close()
        self.p = module.Pipeline(self.root, fixture.CATALOG)
        self.addCleanup(self.p.close)

    def test_capture_at_end_of_budget_then_restart_split_only_preserves_all_evidence(
        self,
    ):
        row, job = self.parent()

        def late_response(request):
            self.now = 89
            return self.respond(request)

        with patch.object(
            self.p, "identifiers", side_effect=AssertionError("must defer discovery")
        ):
            collected = self.run_once(respond=late_response)
        self.assertEqual(collected["elapsed_seconds"], 89)
        self.assertEqual(collected["requests"], 1)
        stored = self.stored(row)
        result = json.loads(stored["result"])
        self.assertEqual(stored["state"], "split_pending")
        self.assertEqual(
            result["partition_deferred"], {"version": 1, "kind": "identifier_fanout"}
        )
        self.assertIn("parquet", result)
        paths = [
            self.root / "objects" / (result["object_sha256"] + ".json"),
            self.root / "observations" / result["observation"],
            self.root / result["parquet"]["path"],
        ]
        hashes = {
            str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        }
        self.assertEqual(
            hashes[str(paths[0].relative_to(self.root))], result["object_sha256"]
        )
        self.assertEqual(
            hashes[str(paths[2].relative_to(self.root))], result["parquet"]["sha256"]
        )
        attempts = self.attempts()
        self.assertEqual(len(attempts), 1)
        self.p.db.execute("INSERT INTO request_gates VALUES('account',12345)")
        self.p.db.execute("INSERT INTO scheduler_state VALUES('family_turn',456)")
        self.p.db.commit()
        self.reopen()

        def slow_discovery(*, _source_apis=None):
            self.assertEqual(_source_apis, module.STOCK_IDENTIFIER_SOURCE_APIS)
            self.now += 71
            return {"stocks": ["600036.SH", "000001.SZ"]}

        with patch.object(self.p, "identifiers", side_effect=slow_discovery):
            resumed = self.run_once(
                requests=0,
                respond=lambda r: self.fail("resumed parent must not call HTTP")
            )
        self.assertEqual(resumed["requests"], 0)
        self.assertEqual(resumed["elapsed_seconds"], 71)
        self.assertEqual(resumed["partition_work"]["status"], "partitioned")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.attempts(), attempts)
        after = self.stored(row)
        for name in (
            "id",
            "logical_key",
            "epoch",
            "job",
            "priority",
            "tries",
            "retry_after",
        ):
            self.assertEqual(after[name], stored[name])
        self.assertNotIn("partition_deferred", json.loads(after["result"]))
        self.assertEqual(
            {p["ts_code"] for p in self.children(row)},
            {"600036.SH", "830001.BJ", "000001.SZ"},
        )
        split, evidence = self.evidence(row)
        self.assertEqual(split["gap"], "universe_unverified")
        self.assertEqual(split["coverage_proven"], 0)
        self.assertEqual(evidence["parent_observation"], result["observation"])
        self.assertEqual(
            self.p.db.execute(
                "SELECT next_at FROM request_gates WHERE scope='account'"
            ).fetchone()[0],
            12345,
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name='family_turn'"
            ).fetchone()[0],
            456,
        )
        self.assertEqual(
            hashes,
            {
                str(p.relative_to(self.root)): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in paths
            },
        )

    def test_at_most_one_parent_per_run_and_no_recapture_after_completion(self):
        first, _ = self.parent()
        second, _ = self.parent(trade_date="20260903")
        self.run_once(requests=2)
        self.assertEqual(len(self.calls), 2)
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["600036.SH"]}
        ):
            one = self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
            self.assertEqual(one["partition_work"]["job_id"], first["id"])
            self.assertIn(
                "partition_deferred", json.loads(self.stored(second)["result"])
            )
            self.reopen()
            with patch.object(
                self.p, "identifiers", return_value={"stocks": ["600036.SH"]}
            ):
                two = self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(two["partition_work"]["job_id"], second["id"])
        self.assertEqual(len(self.attempts()), 2)
        with patch.object(
            self.p, "identifiers", side_effect=AssertionError("no repeated fanout")
        ):
            self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))

    def test_fast_stock_projection_uses_remaining_deadline_for_acquisition(self):
        parent, _ = self.parent()
        self.run_once()
        parent_attempt = self.attempts()
        self.calls.clear()
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["000001.SZ"]}
        ) as discovery:
            report = self.run_once(requests=1)
        self.assertEqual(report["requests"], 1)
        self.assertEqual(report["partition_work"]["discovery_family"], "stocks")
        discovery.assert_called_once_with(
            _source_apis=module.STOCK_IDENTIFIER_SOURCE_APIS
        )
        self.assertEqual(len(self.attempts()), len(parent_attempt) + 1)
        self.assertTrue(self.calls)
        self.assertTrue(all("ts_code" in params for params in self.calls))
        self.assertNotIn({"trade_date": "20260904"}, self.calls)
        self.assertEqual(self.stored(parent)["tries"], 1)

    def test_stock_projection_overrun_does_not_dispatch_after_deadline(self):
        self.parent()
        self.run_once()
        self.calls.clear()

        def slow(*, _source_apis=None):
            self.assertEqual(_source_apis, module.STOCK_IDENTIFIER_SOURCE_APIS)
            self.now += 91
            return {"stocks": ["000001.SZ"]}

        with patch.object(self.p, "identifiers", side_effect=slow):
            report = self.run_once(requests=1)
        self.assertEqual(report["requests"], 0)
        self.assertGreater(report["elapsed_seconds"], 90)
        self.assertEqual(self.calls, [])
        self.assertEqual(report["partition_work"]["discovery_family"], "stocks")

    def test_nonstock_partition_keeps_full_discovery_isolation(self):
        with (
            patch.object(
                self.p,
                "resume_identifier_split",
                return_value={
                    "status": "partitioned",
                    "discovery_family": "funds",
                    "upstream_calls": 0,
                },
            ),
            patch.object(
                self.p, "next_job", side_effect=AssertionError("must stay isolated")
            ),
        ):
            report = self.run_once(requests=1, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(report["requests"], 0)
        self.assertEqual(report["partition_work"]["discovery_family"], "funds")

    def test_failure_after_child_inserts_rolls_back_and_restart_retries_local_work(
        self,
    ):
        row, _ = self.parent()
        self.run_once()
        before = self.stored(row)
        attempts = self.attempts()
        with (
            patch.object(self.p, "identifiers", return_value={"stocks": ["000001.SZ"]}),
            patch.object(
                self.p,
                "record_partition",
                side_effect=RuntimeError("simulated crash before commit"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(self.stored(row), before)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1
        )
        self.assertEqual(self.attempts(), attempts)
        self.reopen()
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["000001.SZ"]}
        ):
            self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(len(self.children(row)), 3)
        self.assertEqual(self.attempts(), attempts)

    def test_deadline_before_resume_keeps_durable_parent_unchanged(self):
        row, _ = self.parent()
        self.run_once()
        before = self.stored(row)
        with patch.object(
            self.p, "identifiers", side_effect=AssertionError("budget elapsed")
        ):
            report = self.run_once(seconds=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(report["partition_work"]["status"], "deadline_deferred")
        self.assertEqual(self.stored(row), before)

    def test_slow_expand_or_selection_never_dispatches_after_deadline(self):
        row, _ = self.parent()
        for stage in ("expand", "next_job"):
            with self.subTest(stage=stage):
                self.now = 0

                def slow(*a, **k):
                    self.now = 91
                    return row

                with patch.object(self.p, stage, side_effect=slow):
                    report = self.run_once(
                        respond=lambda r: self.fail("deadline passed")
                    )
                self.assertEqual(report["requests"], 0)
                self.assertEqual(self.stored(row)["tries"], 0)
                self.assertEqual(self.attempts(), [])

    def test_fast_date_and_futures_partition_paths_stay_synchronous(self):
        row, _ = self.parent(start_date="20260904", end_date="20260905")
        with patch.object(
            self.p, "identifiers", side_effect=AssertionError("date split is direct")
        ):
            self.run_once()
        self.assertEqual(len(self.children(row)), 2)
        self.assertNotIn("partition_deferred", json.loads(self.stored(row)["result"]))
        for api in ("fut_holding", "fut_weekly_detail"):
            self.assertFalse(
                self.p.identifier_split_needs_discovery({"api_name": api, "params": {}})
            )

    def test_pending_parent_artifacts_publish_and_old_rows_need_no_schema_change(self):
        row, _ = self.parent()
        version = self.p.db.execute("PRAGMA user_version").fetchone()[0]
        self.run_once()
        result = json.loads(self.stored(row)["result"])
        release = self.p.publish()
        manifest = module.manifest_at(self.root, release)
        for path in (
            "objects/" + result["object_sha256"] + ".json",
            "observations/" + result["observation"],
            result["parquet"]["path"],
        ):
            self.assertIn(path, manifest["files"])
        self.assertEqual(
            self.p.db.execute("PRAGMA user_version").fetchone()[0], version
        )
        # Old split_pending rows without a marker retain their existing reconciliation.
        result.pop("partition_deferred")
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), row["id"])
        )
        self.p.db.commit()
        with patch.object(
            self.p, "identifiers", side_effect=AssertionError("legacy not requeued")
        ):
            self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(self.stored(row)["tries"], 1)

    def test_normalization_failure_does_not_lose_legacy_child_obligation(self):
        row, _ = self.parent()
        with patch.object(
            self.p, "normalize", side_effect=ValueError("fixture schema failure")
        ):
            self.run_once()
        result = json.loads(self.stored(row)["result"])
        self.assertEqual(result["normalization_error"], "ValueError")
        self.assertIn("partition_deferred", result)
        attempts = self.attempts()
        self.reopen()
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["000001.SZ"]}
        ):
            self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(len(self.children(row)), 3)
        self.assertEqual(self.stored(row)["state"], "blocked")
        self.assertEqual(self.attempts(), attempts)
        self.assertEqual(self.evidence(row)[0]["gap"], "parent_not_split_pending")

    def test_unknown_marker_fails_closed_and_no_legal_children_remains_blocked(self):
        row, _ = self.parent()
        self.run_once()
        result = json.loads(self.stored(row)["result"])
        result["partition_deferred"]["version"] = 999
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), row["id"])
        )
        self.p.db.commit()
        before = self.stored(row)
        with self.assertRaisesRegex(ValueError, "Unsupported deferred"):
            self.run_once(requests=0, respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(self.stored(row), before)
        result["partition_deferred"]["version"] = 1
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), row["id"])
        )
        self.p.db.commit()
        with patch.object(self.p, "split_request", return_value=None):
            report = self.run_once(respond=lambda r: self.fail("no HTTP"))
        self.assertEqual(report["partition_work"]["status"], "blocked")
        self.assertEqual(self.stored(row)["state"], "blocked")
        self.assertEqual(self.stored(row)["tries"], 1)


if __name__ == "__main__":
    unittest.main()
