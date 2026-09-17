"""Bounded temp-only saturation fanout must retain parent-observed identities."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class ObservedFanout(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="tushare-observed-fanout-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(
                target, side_effect=AssertionError("No network or credentials")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def parent(self, api="moneyflow_dc", **params):
        if not params:
            params = {"ann_date" if api == "share_float" else "trade_date": "20260904"}
        key = self.p.enqueue(api, params, 5, "test-parent")
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        return row, json.loads(row["job"])

    def source(self, values, field="ts_code"):
        payload = {"data": {"fields": [field], "items": [[value] for value in values]}}
        raw = module.json_bytes(payload)
        sha = module.digest(raw)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (sha + ".json")).write_bytes(raw)
        return {"object_sha256": sha, "observation": "test-observation.json"}

    def children(self, parent):
        return [
            json.loads(row[0])["params"]
            for row in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=? ORDER BY j.id",
                (parent["id"],),
            )
        ]

    def evidence(self, parent):
        row = self.p.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (parent["id"],)
        ).fetchone()
        return row, json.loads(row["evidence"])

    def test_missing_source_codes_union_discovery_without_claiming_complete(self):
        row, job = self.parent()
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["600036.SH", "000001.SZ"]}
        ):
            result = self.p.split_request(
                row, job, self.source(["600036.SH", "830001.BJ", "830001.BJ"])
            )
        self.assertEqual(
            {r["ts_code"] for r in self.children(row)},
            {"600036.SH", "000001.SZ", "830001.BJ"},
        )
        self.assertTrue(all(r["trade_date"] == "20260904" for r in self.children(row)))
        self.assertFalse(result["universe_complete"])
        self.assertEqual(result["parent_observed_added_count"], 1)
        partition, evidence = self.evidence(row)
        self.assertEqual(partition["coverage_proven"], 0)
        self.assertEqual(evidence["parent_observed_code_count"], 2)
        self.assertEqual(evidence["parent_observed_added_count"], 1)

    def test_empty_discovery_uses_nonempty_strings_and_preserves_future_axis(self):
        row, job = self.parent("share_float")
        bad = [None, "", " ", "600036.SH\n", 123, False, {}, [], "\x00", "has space"]
        with patch.object(self.p, "identifiers", return_value={"stocks": bad}):
            result = self.p.split_request(
                row, job, self.source(bad + ["603448.SH", "603448.SH"])
            )
        self.assertEqual(
            self.children(row), [{"ann_date": "20260904", "ts_code": "603448.SH"}]
        )
        self.assertEqual(result["children"], 1)
        self.assertNotIn("end_date", self.children(row)[0])
        self.assertNotIn("float_date", self.children(row)[0])

    def test_reentry_adds_observed_codes_preserves_children_and_evidence(self):
        row, job = self.parent()
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["600036.SH"]}
        ):
            self.p.split_request(row, job)
        original = self.p.db.execute(
            "SELECT child_id FROM partition_children WHERE parent_id=?", (row["id"],)
        ).fetchone()[0]
        self.p.db.execute(
            "UPDATE partition_splits SET evidence=?,status='gap',gap='universe_not_verified' WHERE parent_id=?",
            (
                json.dumps({"origin": "legacy-audit", "review_note": "keep me"}),
                row["id"],
            ),
        )
        saved = self.source(["830001.BJ"])
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(saved), row["id"])
        )
        self.p.db.commit()
        self.p.close()
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        row = self.p.db.execute(
            "SELECT * FROM jobs WHERE id=?", (row["id"],)
        ).fetchone()
        with patch.object(self.p, "identifiers", return_value={"stocks": []}):
            first = self.p.split_request(row, job)
            count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            self.p.db.execute(
                "UPDATE partition_splits SET status='gap',gap='universe_not_verified' WHERE parent_id=?",
                (row["id"],),
            )
            again = self.p.split_request(row, job)
        self.assertEqual(first, again)
        self.assertEqual(
            count, self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        )
        self.assertEqual(count, 3)
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT 1 FROM partition_children WHERE parent_id=? AND child_id=?",
                (row["id"], original),
            ).fetchone()
        )
        partition, evidence = self.evidence(row)
        self.assertEqual(
            (partition["status"], partition["gap"]), ("gap", "universe_not_verified")
        )
        self.assertEqual(evidence["review_note"], "keep me")
        self.assertEqual(evidence["origin"], "legacy-audit")
        self.assertFalse(evidence["universe_complete"])

    def test_custom_saturation_parameter_and_unknown_universe_stay_unverified(self):
        spec = module.EXTENDED_CONTRACTS["moneyflow_dc"]
        row, job = self.parent()
        with (
            patch.dict(spec, {"saturation_param": "index_code"}),
            patch.object(self.p, "identifiers", return_value={}),
        ):
            result = self.p.split_request(
                row, job, self.source(["000300.CSI"], "index_code")
            )
            self.p.db.execute(
                "UPDATE partition_splits SET status='resolved',coverage_proven=1 WHERE parent_id=?",
                (row["id"],),
            )
            second = self.p.split_request(
                row, job, self.source(["000300.CSI"], "index_code")
            )
        self.assertEqual(
            self.children(row), [{"trade_date": "20260904", "index_code": "000300.CSI"}]
        )
        self.assertFalse(result["universe_complete"])
        self.assertFalse(second["universe_complete"])
        partition, _ = self.evidence(row)
        self.assertEqual(partition["coverage_proven"], 0)
        self.assertNotEqual(partition["status"], "resolved")

    def test_no_valid_codes_and_code_scoped_parent_never_invent_children(self):
        for params in (
            {"trade_date": "20260904"},
            {"trade_date": "20260904", "ts_code": "600036.SH"},
        ):
            row, job = self.parent(**params)
            with patch.object(self.p, "identifiers", return_value={}):
                result = self.p.split_request(row, job, self.source([None, ""]))
            self.assertIsNone(result)
            self.assertEqual(self.children(row), [])

    def test_date_bisection_keeps_precedence_and_existing_children(self):
        row, job = self.parent(start_date="20260901", end_date="20260904")
        with patch.object(
            self.p,
            "identifiers",
            side_effect=AssertionError("No fanout for date split"),
        ):
            result = self.p.split_request(row, job, self.source(["830001.BJ"]))
            again = self.p.split_request(row, job, self.source(["600036.SH"]))
        self.assertEqual(result["method"], "date_bisection")
        self.assertEqual(again["children"], 2)
        self.assertTrue(again["universe_complete"])

    def test_run_resumes_captured_parent_without_repeating_http(self):
        spec = module.EXTENDED_CONTRACTS["moneyflow_dc"]
        with patch.dict(spec, {"row_cap": 2}):
            row, _ = self.parent()
        seen = []

        def respond(request):
            payload = json.loads(request.content)
            seen.append(payload["params"])
            fields = payload["fields"].split(",")
            rows = [
                {"ts_code": code, "trade_date": "20260904"}
                for code in ("600036.SH", "830001.BJ")
            ]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                        "has_more": True,
                    },
                },
            )

        with (
            patch.dict(spec, {"row_cap": 2}),
            patch.object(self.p, "identifiers", return_value={"stocks": ["600036.SH"]}),
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
        ):
            # Serialize a two-row contract cap to exercise real capture/run plumbing.
            self.p.run(
                client,
                "fixture-only",
                {"priority_start": "20200101"},
                max_requests=1,
                max_seconds=2,
                pause=0,
            )
            self.assertEqual(self.children(row), [])
            resumed = self.p.run(
                client,
                "fixture-only",
                {"priority_start": "20200101"},
                max_requests=1,
                max_seconds=2,
                pause=0,
            )
            self.assertEqual(resumed["requests"], 1)
            self.assertEqual(resumed["partition_work"]["discovery_family"], "stocks")
        self.assertEqual(seen[0], {"trade_date": "20260904"})
        self.assertEqual(len(seen), 2)
        self.assertIn("ts_code", seen[1])
        self.assertEqual(
            {x["ts_code"] for x in self.children(row)}, {"600036.SH", "830001.BJ"}
        )
        stored = self.p.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (row["id"],)
        ).fetchone()
        self.assertEqual(stored[0], "split_pending")
        self.assertEqual(
            json.loads(stored[1])["split"]["parent_observed_added_count"], 1
        )


if __name__ == "__main__":
    unittest.main()
