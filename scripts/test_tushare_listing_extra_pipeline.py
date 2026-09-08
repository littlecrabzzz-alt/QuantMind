"""Offline listing snapshots, IPO date axes and market-category acquisition."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_intake import capture_sample
from backend.shared.tushare_listing_extra_contracts import (
    DAILY_INFO_STARTS,
    FIELDS,
    INPUT_FIELDS,
)
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, dataset_schema

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        {
            k: v
            for k, v in {
                "trade_date": "20260904",
                "ts_code": "SH_A" if api == "daily_info" else "T600018.SH",
                "name": "原始名称",
                "ipo_date": "20260904",
                "issue_date": "20261001",
                "sub_code": "780018",
                "o_code": "838163.BJ",
                "n_code": "920163.BJ",
                "list_date": "20200727",
                "exchange": "SH",
                "tr": None,
                "pe": -12.5,
                "float_share": 0.0,
            }.items()
            if k in row
        }
    )
    row["new_supplier_field"] = "保留"
    row.update(updates)
    return row


class ListingExtraRuntime(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
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

    def capture(self, api, params, rows=None, more=False, epoch="fixture", omit=()):
        key = self.p.enqueue(api, params, 10, epoch)
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        rows = rows if rows is not None else [source(api)]
        fields = [f for f in rows[0] if f not in omit]

        def respond(request):
            sent = json.loads(request.content)
            self.assertEqual(set(sent["fields"].split(",")), set(FIELDS[api]))
            self.assertTrue(set(sent["params"]) <= set(INPUT_FIELDS[api]))
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
        return (
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone(),
            job,
            result,
        )

    def test_capture_publish_read_preserves_source_namespaces_and_both_dates(self):
        for api in FIELDS:
            params = (
                {}
                if api == "bse_mapping"
                else {"start_date": "20260901", "end_date": "20260909"}
                if api == "new_share"
                else {"trade_date": "20260904"}
            )
            for epoch in ("first", "repeat"):
                _, _, result = self.capture(api, params, epoch=epoch)
                self.assertEqual(result["status"], "sample_ok")
                observation = json.loads(
                    (self.root / "observations" / result["observation"]).read_bytes()
                )
                self.assertEqual(observation["request"]["params"], params)
        release = self.p.publish()
        for api in FIELDS:
            rows = read_dataset(self.root, release, api).to_pylist()
            self.assertEqual(len(rows), 1)
            self.assertTrue(set(FIELDS[api]) <= set(rows[0]))
            self.assertEqual(rows[0]["new_supplier_field"], "保留")
            self.assertEqual(contract_for(api)["group"], "listing_extra")
        ipo = read_dataset(
            self.root, release, "new_share", start_date="20260904", end_date="20260904"
        )
        row = ipo.to_pylist()[0]
        self.assertEqual(row["ts_code"], "SHT600018")
        self.assertEqual(row["source_ts_code"], "T600018.SH")
        self.assertEqual(row["sub_code"], "780018")
        self.assertEqual(row["issue_date"], "20261001")
        self.assertEqual(
            dataset_schema(self.root, release, "new_share")["default_date_field"],
            "ipo_date",
        )
        self.assertEqual(
            read_dataset(
                self.root,
                release,
                "new_share",
                date_field="issue_date",
                start_date="20261001",
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(self.root, release, "daily_info", codes=["SH_A"]).num_rows, 1
        )
        mapping = read_dataset(
            self.root, release, "bse_mapping", code_field="o_code", codes=["838163.BJ"]
        )
        self.assertEqual(mapping.to_pylist()[0]["n_code"], "920163.BJ")
        self.assertEqual(
            read_dataset(
                self.root,
                release,
                "bse_mapping",
                code_field="n_code",
                codes=["920163.BJ"],
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                release,
                "bse_mapping",
                code_field="o_code",
                codes=["920163.BJ"],
            ).num_rows,
            0,
        )
        with self.assertRaisesRegex(ValueError, "internal prefix"):
            read_dataset(self.root, release, "bak_basic", codes=["600018.SH"])
        meta = json.loads(mapping.schema.metadata[b"tushare"])
        self.assertIn("not code-change", meta["date_axis_note"])
        self.assertEqual(meta["upstream_calls"], 0)

    def test_ipo_future_null_listing_date_and_revisions_remain_distinct(self):
        self.capture(
            "new_share",
            {},
            [
                source("new_share", issue_date=None),
                source("new_share", issue_date="20261001"),
            ],
        )
        self.capture(
            "bse_mapping",
            {},
            [source("bse_mapping"), source("bse_mapping", name="修订名称")],
        )
        release = self.p.publish()
        self.assertEqual(
            {
                r["issue_date"]
                for r in read_dataset(self.root, release, "new_share").to_pylist()
            },
            {None, "20261001"},
        )
        self.assertEqual(read_dataset(self.root, release, "bse_mapping").num_rows, 2)

    def test_discovery_unions_historical_mapping_but_keeps_market_and_subscription_separate(
        self,
    ):
        self.capture(
            "bak_basic",
            {"trade_date": "20160104"},
            [source("bak_basic", ts_code="T600001.SH")],
        )
        self.capture(
            "new_share",
            {},
            [source("new_share", ts_code="600002.SH", sub_code="780002")],
        )
        self.capture("bse_mapping", {})
        self.capture(
            "daily_info",
            {"trade_date": "20260903"},
            [source("daily_info", ts_code="SH_NEW")],
        )
        ids = self.p.identifiers()
        self.assertEqual(
            set(ids["historical_listing_securities"]),
            {"T600001.SH", "600002.SH", "838163.BJ", "920163.BJ"},
        )
        self.assertEqual(ids["bse_old_codes"], ["838163.BJ"])
        self.assertEqual(ids["bse_new_codes"], ["920163.BJ"])
        self.assertEqual(
            set(ids["market_stat_categories"]), set(DAILY_INFO_STARTS) | {"SH_NEW"}
        )
        self.assertEqual(ids["stocks"], [])
        self.assertNotIn("780002", ids["historical_listing_securities"])
        row, job, result = self.capture(
            "bak_basic", {"trade_date": "20260904"}, more=True
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["children"], 5)
        self.assertFalse(split["universe_complete"])
        row, job, result = self.capture(
            "daily_info", {"trade_date": "20260904"}, more=True
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["children"], 32)
        self.assertFalse(split["universe_complete"])
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                (row["id"],),
            )
        ]
        self.assertEqual(
            {p["ts_code"] for p in children}, set(ids["market_stat_categories"])
        )
        self.assertTrue(all(p["trade_date"] == "20260904" for p in children))

    def test_ipo_date_bisection_preserves_issuance_axis_terminal_snapshots_stay_unresolved(
        self,
    ):
        row, job, result = self.capture(
            "new_share", {"start_date": "20260901", "end_date": "20260902"}, more=True
        )
        self.assertEqual(
            self.p.split_request(row, job, result)["method"], "date_bisection"
        )
        for api, params in (
            ("new_share", {"start_date": "20260904", "end_date": "20260904"}),
            ("new_share", {}),
            ("bse_mapping", {}),
            ("daily_info", {"trade_date": "20260904", "ts_code": "SH_A"}),
        ):
            row, job, result = self.capture(api, params, more=True)
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertIsNone(self.p.split_request(row, job, result))
        for record in self.p.db.execute(
            "SELECT job FROM jobs WHERE json_extract(job,'$.api_name')='new_share'"
        ):
            self.assertTrue(
                set(json.loads(record[0])["params"]) <= {"start_date", "end_date"}
            )

    def test_actual_run_blocks_terminal_caps_without_synthetic_partitions(self):
        pending = [
            self.p.enqueue(api, params, 1, "terminal-run")
            for api, params in (
                ("new_share", {}),
                ("bse_mapping", {}),
                ("daily_info", {"trade_date": "20260904", "ts_code": "SH_A"}),
            )
        ]

        def respond(request):
            row = source(json.loads(request.content)["api_name"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(row),
                        "items": [list(row.values())],
                        "has_more": True,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            result = self.p.run(
                client, "fixture", {}, max_requests=3, max_seconds=10, pause=0
            )
        self.assertEqual(result["requests"], 3)
        for key in pending:
            row = self.p.db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (key,)
            ).fetchone()
            self.assertEqual(row["state"], "blocked")
            self.assertEqual(json.loads(row["result"])["status"], "possibly_truncated")
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM partition_splits").fetchone()[0], 0
        )

    def test_category_missing_column_stays_gap_and_all_groups_plan_without_api_probes(
        self,
    ):
        self.assertEqual(
            self.capture("daily_info", {"trade_date": "20260904"}, omit=["tr"])[2][
                "status"
            ],
            "schema_gap",
        )
        config = {
            "enable_listing_extra": True,
            "listing_extra_history_start": "20260901",
            "plan_jobs_per_tick": 1000,
        }
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:listing_extra", stats)
        count = self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            count, self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        )
        gap = self.p.db.execute(
            "SELECT reason FROM capability WHERE scope='planning:listing_extra:new_share:terminal_gap'"
        ).fetchone()
        self.assertIsNotNone(gap)
        config.update(
            listing_extra_apis=["bad"],
            enable_trading_event=True,
            trading_event_apis=["hm_list"],
        )
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertNotIn("recent:listing_extra", stats)
        self.assertIn("recent:trading_event", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:listing_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertIn(
            '"backend/shared/tushare_listing_extra_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
