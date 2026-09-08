"""Offline source-only futures partitions retain opaque values and incomplete gaps."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


class FuturesObservedSplitTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(
                target, side_effect=AssertionError("no network or credentials")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def parent(self, api, params):
        key = self.p.enqueue(api, params, 10, "source-test")
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        return row, json.loads(row["job"])

    def source(self, rows, observation=None):
        fields = list(dict.fromkeys(k for r in rows for k in r))
        raw = module.json_bytes(
            {
                "data": {
                    "fields": fields,
                    "items": [[r.get(f) for f in fields] for r in rows],
                }
            }
        )
        sha = module.digest(raw)
        path = self.root / "objects" / (sha + ".json")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        return {
            "object_sha256": sha,
            "observation": observation or sha + ".json",
            "api_name": "fut_holding",
        }

    def children(self, row):
        return [
            (r["id"], json.loads(r["job"])["params"])
            for r in self.p.db.execute(
                "SELECT j.* FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=? ORDER BY j.id",
                (row["id"],),
            )
        ]

    def split(self, row, job, result):
        out = self.p.split_request(row, job, result)
        self.assertFalse(out["universe_complete"])
        return out

    def evidence(self, row):
        r = self.p.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (row["id"],)
        ).fetchone()
        self.assertEqual(r["coverage_proven"], 0)
        return json.loads(r["evidence"])

    def test_holding_pairs_not_products_or_cross_join_and_filters_unchanged(self):
        row, job = self.parent("fut_holding", {"trade_date": "20260904"})
        pairs = [
            ("CFFEX", "IC2609"),
            ("CFFEX", "IF2609"),
            ("DCE", "A2611"),
            ("DCE", "C"),
            ("DCE", "A2611"),
        ]
        result = self.source(
            [{"exchange": e, "symbol": s, "trade_date": "20260904"} for e, s in pairs]
        )
        raw = (self.root / "objects" / (result["object_sha256"] + ".json")).read_bytes()
        original = tuple(row)
        out = self.split(row, job, result)
        self.assertEqual(out["children"], 4)
        actual = {
            tuple(p[k] for k in ("exchange", "symbol")) for _, p in self.children(row)
        }
        self.assertEqual(actual, set(pairs))
        self.assertTrue(
            all(
                p["trade_date"] == "20260904"
                and set(p) == {"trade_date", "exchange", "symbol"}
                for _, p in self.children(row)
            )
        )
        self.assertEqual(
            raw,
            (self.root / "objects" / (result["object_sha256"] + ".json")).read_bytes(),
        )
        self.assertEqual(
            tuple(
                self.p.db.execute(
                    "SELECT * FROM jobs WHERE id=?", (row["id"],)
                ).fetchone()
            ),
            original,
        )
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0
        )

    def test_opaque_week_types_survive_and_saturated_week_has_pair_children(self):
        row, job = self.parent("fut_weekly_detail", {})
        weeks = ["20191", "201904", "20199", "202001", "202017", 20191]
        out = self.split(
            row, job, self.source([{"week": w, "week_date": "20190104"} for w in weeks])
        )
        self.assertEqual(out["children"], 6)
        params = [p for _, p in self.children(row)]
        self.assertEqual(
            {module.json_bytes(p) for p in params},
            {module.json_bytes({"week": w}) for w in weeks},
        )
        child = self.p.db.execute(
            "SELECT * FROM jobs WHERE id=?", (self.children(row)[0][0],)
        ).fetchone()
        child_job = json.loads(child["job"])
        w = child_job["params"]["week"]
        details = [
            {"week": w, "exchange": "DCE", "prd": "A"},
            {"week": w, "exchange": "CFFEX", "prd": "IF"},
        ]
        self.assertEqual(
            self.split(child, child_job, self.source(details))["children"], 2
        )
        self.assertEqual(
            {(p["exchange"], p["prd"]) for _, p in self.children(child)},
            {("DCE", "A"), ("CFFEX", "IF")},
        )
        leaf = self.p.db.execute(
            "SELECT * FROM jobs WHERE id=?", (self.children(child)[0][0],)
        ).fetchone()
        leaf_job = json.loads(leaf["job"])
        terminal = self.split(leaf, leaf_job, self.source([leaf_job["params"]]))
        self.assertEqual(terminal["children"], 0)
        self.assertEqual(terminal["gaps"], {"saturated_terminal_partition": 1})
        self.p.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id IN (?,?,?)",
            (row["id"], child["id"], leaf["id"]),
        )
        self.p.reconcile_partitions()
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM partition_splits WHERE status='resolved'"
            ).fetchone()[0],
            0,
        )

    def test_incremental_reentry_preserves_children_and_source_evidence(self):
        row, job = self.parent("fut_holding", {"trade_date": "20260904"})
        a = self.source(
            [{"exchange": "DCE", "symbol": "A2611", "trade_date": "20260904"}],
            "observation-a",
        )
        self.assertEqual(self.split(row, job, a)["added_children"], 1)
        before = self.evidence(row)
        self.assertEqual(self.split(row, job, a)["added_children"], 0)
        self.assertEqual(before, self.evidence(row))
        b = self.source(
            [{"exchange": "CFFEX", "symbol": "IC2609", "trade_date": "20260904"}],
            "observation-b",
        )
        self.assertEqual(self.split(row, job, b)["added_children"], 1)
        self.assertEqual(len(self.evidence(row)["source_observations"]), 2)
        self.assertEqual(self.split(row, job, a)["children"], 2)
        self.assertEqual(len(self.evidence(row)["source_observations"]), 2)
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 3
        )

    def test_missing_invalid_filter_mismatch_gaps_are_independent(self):
        row, job = self.parent(
            "fut_holding", {"trade_date": "20260904", "exchange": "DCE"}
        )
        records = [
            {"trade_date": "20260904", "exchange": "DCE"},
            {"trade_date": "20260904", "exchange": "DCE", "symbol": True},
            {"trade_date": "20260904", "exchange": "DCE", "symbol": "A\n"},
            {"trade_date": "20260903", "exchange": "DCE", "symbol": "A"},
            {"trade_date": "20260904", "exchange": "CFFEX", "symbol": "IC2609"},
            {"trade_date": "20260904", "exchange": "DCE", "symbol": "A2611"},
        ]
        out = self.split(row, job, self.source(records))
        self.assertEqual(out["children"], 1)
        self.assertEqual(
            out["gaps"],
            {
                "missing_partition_fields": 1,
                "invalid_partition_values": 2,
                "parent_filter_mismatch": 2,
            },
        )
        self.assertEqual(
            next(iter(self.evidence(row)["source_observations"].values()))["gaps"],
            out["gaps"],
        )
        for value in (None, True, [], {}, "", "2019 1", -1):
            parent, pjob = self.parent(
                "fut_weekly_detail", {"exchange": "DCE", "start_week": str(value)}
            )
            outcome = self.split(
                parent, pjob, self.source([{"week": value, "exchange": "DCE"}])
            )
            self.assertEqual(outcome["children"], 0)

    def test_row_result_fallback_and_missing_source_then_recovery(self):
        row, job = self.parent("fut_weekly_detail", {})
        self.assertEqual(
            self.split(row, job, {})["gaps"], {"missing_source_partition_rows": 1}
        )
        result = self.source([{"week": "20199"}])
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), row["id"])
        )
        row = self.p.db.execute(
            "SELECT * FROM jobs WHERE id=?", (row["id"],)
        ).fetchone()
        self.assertEqual(self.p.split_request(row, job)["children"], 1)
        self.assertEqual(len(self.evidence(row)["source_observations"]), 2)

    def test_existing_zero_child_gap_adopts_observed_method_without_erasing_evidence(
        self,
    ):
        row, job = self.parent("fut_weekly_detail", {})
        self.p.db.execute(
            "INSERT INTO partition_splits VALUES(?,'unknown',0,0,?,'gap','legacy_relationship_unverified')",
            (
                row["id"],
                json.dumps({"origin": "legacy_unverified", "legacy_note": "retained"}),
            ),
        )
        self.split(row, job, self.source([{"week": "20191"}]))
        self.assertEqual(
            self.split(row, job, self.source([{"week": "20199"}]))["children"], 2
        )
        self.assertEqual(self.evidence(row)["legacy_note"], "retained")
        self.assertEqual(len(self.evidence(row)["source_observations"]), 2)

    def test_run_keeps_parent_pending_when_observed_children_are_empty(self):
        row, job = self.parent("fut_holding", {"trade_date": "20260904"})
        requests = []

        def respond(request):
            params = json.loads(request.content)["params"]
            requests.append(params)
            fields = ["trade_date", "exchange", "symbol", "broker"]
            items = (
                [["20260904", "DCE", "C", "member"]] if "symbol" not in params else []
            )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": fields, "items": items, "has_more": bool(items)},
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            self.p.run(client, "fixture", {}, max_requests=2, max_seconds=5, pause=0)
        self.assertEqual(
            requests,
            [
                {"trade_date": "20260904"},
                {"trade_date": "20260904", "exchange": "DCE", "symbol": "C"},
            ],
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT state FROM jobs WHERE id=?", (row["id"],)
            ).fetchone()[0],
            "split_pending",
        )
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 2
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM partition_splits WHERE status='resolved'"
            ).fetchone()[0],
            0,
        )
        child, child_job = self.parent("fut_holding", requests[1])
        terminal = self.split(
            child, child_job, self.source([{**requests[1], "broker": "member"}])
        )
        self.assertEqual(terminal["children"], 0)
        self.assertEqual(terminal["gaps"], {"saturated_terminal_partition": 1})

    def test_existing_date_split_stays_exhaustive_and_cycle_is_rejected(self):
        row, job = self.parent(
            "fut_holding",
            {"symbol": "A", "start_date": "20260901", "end_date": "20260904"},
        )
        result = self.p.split_request(row, job, {})
        self.assertEqual(result["method"], "date_bisection")
        self.assertEqual(
            self.p.db.execute(
                "SELECT coverage_proven FROM partition_splits WHERE parent_id=?",
                (row["id"],),
            ).fetchone()[0],
            1,
        )
        row, job = self.parent("fut_weekly_detail", {})
        self.split(row, job, self.source([{"week": "20191"}]))
        key = self.p.enqueue("fut_weekly_detail", {"week": "20192"}, 11, "source-test")
        self.p.db.execute(
            "INSERT INTO partition_children VALUES(?,?)", (key, row["id"])
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.p.split_request(row, job, self.source([{"week": "20192"}]))


if __name__ == "__main__":
    unittest.main()
