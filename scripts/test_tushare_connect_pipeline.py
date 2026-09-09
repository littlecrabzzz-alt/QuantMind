"""Connect runtime: source fields, request identities, discovery and closed-loop splits."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_connect_contracts import FIELDS, INPUT_FIELDS, VARIANTS
from backend.shared.tushare_intake import capture_sample
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import CONTRACTS as READ_CONTRACTS, read_dataset

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)
CODES = {
    "stock_hsgt": "00700.HK",
    "hsgt_top10": "600036.SH",
    "moneyflow_cnt_ths": "885748.TI",
    "moneyflow_ind_ths": "881267.TI",
    "moneyflow_ind_dc": "BK0475",
}


def source(api):
    values = dict.fromkeys(FIELDS[api])
    values.update({"trade_date": "20260904", "ts_code": CODES[api]})
    values.update(VARIANTS.get(api, [{}])[0])
    for field, value in {
        "name": "原始名称",
        "type_name": "source route",
        "industry": "原始板块",
        "net_amount": -123.456,
        "net_buy_amount": 0.0,
        "company_num": 12,
        "close": 9.12,
        "change": -0.3,
        "rank": 1,
        "buy_sm_amount_stock": "源名称",
    }.items():
        if field in values:
            values[field] = value
    values["unlisted_source_field"] = "新字段也保留"
    return values


class ConnectRuntimeTest(unittest.TestCase):
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
            guard = patch(target, side_effect=AssertionError("offline only"))
            guard.start()
            self.addCleanup(guard.stop)

    def capture(self, api, params, rows=None, more=False):
        key = self.p.enqueue(api, params, 10, "connect-test")
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        rows = rows if rows is not None else [source(api)]
        fields = list(rows[0])

        def respond(request):
            sent = json.loads(request.content)
            self.assertTrue(set(FIELDS[api]) <= set(sent["fields"].split(",")))
            self.assertTrue(set(sent["params"]) <= set(INPUT_FIELDS[api]))
            self.assertNotIn("_request_identity", sent["fields"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                        "has_more": more,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            result = self.p.normalize(capture_sample(client, "fixture", job, self.root))
        attempt = row["tries"] + 1
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (key, attempt, json.dumps(result))
        )
        self.p.db.execute(
            "UPDATE jobs SET result=?,state=?,tries=? WHERE id=?",
            (
                json.dumps(result),
                "done" if result["status"] == "sample_ok" else "quality",
                attempt,
                key,
            ),
        )
        self.p.db.commit()
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        return row, job, result

    def test_all_fields_identity_scopes_and_source_namespaces_in_fixed_release(self):
        for api in FIELDS:
            self.assertEqual(contract_for(api)["group"], "connect")
            self.assertEqual(
                READ_CONTRACTS[api]["request_identity_fields"],
                contract_for(api)["request_identity_fields"],
            )
            for variant in VARIANTS.get(api, [{}]):
                # Deliberately same supplier payload under different requests:
                # preserve provenance, do not conflate it with filter validation.
                self.assertEqual(
                    self.capture(api, {"trade_date": "20260904", **variant})[2][
                        "status"
                    ],
                    "sample_ok",
                )
        release = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, release, api)
            rows = table.to_pylist()
            self.assertEqual(len(rows), len(VARIANTS.get(api, [{}])))
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            for key, value in source(api).items():
                if key != "ts_code":
                    self.assertEqual(rows[0][key], value, (api, key))
            self.assertTrue(all(r["source_ts_code"] == CODES[api] for r in rows))
            expected = "SH600036" if api == "hsgt_top10" else CODES[api]
            self.assertEqual({r["ts_code"] for r in rows}, {expected})
            self.assertEqual(
                read_dataset(self.root, release, api, codes=[expected]).num_rows,
                len(rows),
            )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            if api in VARIANTS:
                self.assertEqual(
                    {r["_request_identity"] for r in rows},
                    {module.json_bytes(v).decode() for v in VARIANTS[api]},
                )
                self.assertEqual(len({r["_row_identity"] for r in rows}), len(rows))
                self.assertEqual(
                    metadata["request_identity_status"],
                    "verified_from_immutable_observations",
                )
        ids = self.p.identifiers()
        for api, code in CODES.items():
            self.assertIn(code, ids["connect_" + api])
        self.assertNotIn("BK0475", ids["stocks"])
        self.assertNotIn("00700.HK", ids["stocks"])

    def test_stored_discovery_and_parent_observed_reentry_keep_source_filters(self):
        api = "moneyflow_ind_dc"
        params = {"trade_date": "20260904", "content_type": "地域"}
        self.capture(
            api,
            {"trade_date": "20260903", "content_type": "地域"},
            [{**source(api), "ts_code": "OLD.BOARD"}],
        )
        row, job, result = self.capture(api, params, more=True)
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["children"], 2)
        self.assertFalse(split["universe_complete"])
        row, job, result = self.capture(
            api, params, [{**source(api), "ts_code": "NEW.BOARD"}], more=True
        )
        self.assertEqual(self.p.split_request(row, job, result)["children"], 3)
        self.assertEqual(self.p.split_request(row, job, result)["children"], 3)
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                (row["id"],),
            )
        ]
        self.assertEqual(
            {p["ts_code"] for p in children}, {"OLD.BOARD", "BK0475", "NEW.BOARD"}
        )
        self.assertTrue(
            all(
                p["content_type"] == "地域" and p["trade_date"] == "20260904"
                for p in children
            )
        )
        self.p.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (row["id"],)
        )
        self.p.reconcile_partitions()
        self.assertEqual(
            self.p.db.execute(
                "SELECT gap FROM partition_splits WHERE parent_id=?", (row["id"],)
            ).fetchone()[0],
            "universe_unverified",
        )

    def test_actual_run_saturated_month_bisects_and_saturated_day_fans_out(self):
        api = "moneyflow_cnt_ths"
        parent = self.p.enqueue(
            api, {"start_date": "20260901", "end_date": "20260902"}, 1, "split-run"
        )
        calls = []

        def respond(request):
            params = json.loads(request.content)["params"]
            calls.append(params)
            row = source(api)
            row["trade_date"] = params.get("start_date", "20260901")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(row),
                        "items": [list(row.values())],
                        "has_more": "ts_code" not in params,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            result = self.p.run(
                client, "fixture", {}, max_requests=5, max_seconds=10, pause=0
            )
            self.assertEqual(result["requests"], 3)
            for _ in range(2):
                resumed = self.p.run(
                    client, "fixture", {}, max_requests=5, max_seconds=10, pause=0
                )
                self.assertEqual(resumed["requests"], 0)
            remaining = self.p.run(
                client, "fixture", {}, max_requests=2, max_seconds=10, pause=0
            )
        self.assertEqual(result["requests"] + remaining["requests"], 5)
        self.assertEqual(len(calls), 5)
        parent_split = self.p.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (parent,)
        ).fetchone()
        self.assertEqual(parent_split["method"], "date_bisection")
        self.assertEqual(parent_split["coverage_proven"], 1)
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM partition_splits WHERE method='identifier_fanout' AND coverage_proven=0"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM partition_splits WHERE status='resolved'"
            ).fetchone()[0],
            0,
        )
        self.assertTrue(all(set(p) <= set(INPUT_FIELDS[api]) for p in calls))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 5
        )

    def test_planning_validation_group_and_missing_request_identity_gap(self):
        config = {
            "enable_connect": True,
            "connect_history_start": "20250812",
            "plan_jobs_per_tick": 1000,
        }
        result = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:connect", result)
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(DISTINCT json_extract(job,'$.api_name')) FROM jobs WHERE group_name='connect'"
            ).fetchone()[0],
            5,
        )
        scopes = {r[0] for r in self.p.db.execute("SELECT scope FROM capability")}
        self.assertIn("planning:connect:stock_hsgt:filter_consistency_gap", scopes)
        self.assertIn("planning:connect:hsgt_top10:cap_gap", scopes)
        config.update(
            connect_apis=["unknown"],
            enable_research_extra=True,
            research_extra_apis=["report_rc"],
        )
        result = self.p.plan_extended(config, date(2026, 9, 10))
        self.assertNotIn("recent:connect", result)
        self.assertIn("recent:research_extra", result)
        self.capture("stock_hsgt", {"trade_date": "20260904"})
        release = self.p.publish()
        with self.assertRaisesRegex(ValueError, "Request identity gap"):
            read_dataset(self.root, release, "stock_hsgt")


if __name__ == "__main__":
    unittest.main()
