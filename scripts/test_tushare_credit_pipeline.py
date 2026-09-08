"""Credit contracts through stored discovery, durable planning and offline reads."""

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
from backend.shared.tushare_credit_extra_contracts import FIELDS, INPUT_FIELDS
from backend.shared.tushare_intake import capture_sample
from backend.shared.tushare_registry import PLANNERS, contract_for
from backend.shared.tushare_store import read_dataset

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


def source(api):
    row = dict.fromkeys(FIELDS[api])
    row.update(dict.fromkeys(contract_for(api)["keys"], "source"))
    for key, value in {
        "ts_code": "T600018.SH",
        "trade_date": "20260904",
        "ann_date": "20260904",
        "start_date": "20200101",
        "end_date": "20290904",
        "exchange_id": "SSE",
        "exchange": "SSE",
        "pledge_amount": 123.45,
        "holding_amount": 987.65,
        "is_buyback": "0",
        "price": 9.21,
        "vol": 87.5,
        "amount": 805.875,
        "is_release": "N",
        "ob": 0.12,
    }.items():
        if key in row:
            row[key] = value
    row["unknown_supplier_field"] = "原始字段"
    return row


class CreditPipelineTest(unittest.TestCase):
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

    def capture(self, api, params, rows=None, *, has_more=False):
        key = self.p.enqueue(api, params, epoch="credit-fixture")
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        rows = [source(api)] if rows is None else rows
        fields = list(rows[0])

        def respond(request):
            sent = json.loads(request.content)
            if api in FIELDS:
                self.assertTrue(set(FIELDS[api]) <= set(sent["fields"].split(",")))
                self.assertTrue(set(params) <= set(INPUT_FIELDS[api]))
                self.assertNotIn("_row_identity", sent["fields"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                        "has_more": has_more,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            result = capture_sample(client, "fixture", job, self.root)
        result = self.p.normalize(result)
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

    def test_all_seven_roundtrip_fields_event_identity_and_announcement_axis(self):
        for api in FIELDS:
            params = (
                {"ann_date": "20260904"}
                if api == "pledge_detail"
                else (
                    {"ts_code": "T600018.SH"}
                    if api == "pledge_stat"
                    else {"trade_date": "20260904"}
                )
            )
            rows = [source(api)]
            if api == "pledge_detail":
                rows.append({**rows[0], "is_release": "Y", "is_buyback": "1"})
            _, _, result = self.capture(api, params, rows)
            self.assertEqual(result["status"], "sample_ok")
            self.assertEqual(contract_for(api)["group"], "credit_extra")
        release = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, release, api)
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            rows = table.to_pylist()
            self.assertEqual(len(rows), 2 if api == "pledge_detail" else 1)
            for field, value in source(api).items():
                if field not in ("ts_code", "is_release", "is_buyback"):
                    self.assertEqual(rows[0][field], value, (api, field))
            if "ts_code" in FIELDS[api]:
                self.assertEqual(rows[0]["source_ts_code"], "T600018.SH")
            self.assertEqual(
                json.loads(table.schema.metadata[b"tushare"])["upstream_calls"], 0
            )
        pledge = read_dataset(
            self.root,
            release,
            "pledge_detail",
            start_date="20260904",
            end_date="20260904",
        )
        self.assertEqual(pledge.num_rows, 2)
        self.assertEqual(len({r["_row_identity"] for r in pledge.to_pylist()}), 2)
        self.assertEqual({r["end_date"] for r in pledge.to_pylist()}, {"20290904"})
        self.assertEqual(
            read_dataset(
                self.root,
                release,
                "pledge_detail",
                start_date="20290904",
                end_date="20290904",
            ).num_rows,
            0,
        )

    def test_credit_universe_keeps_etf_t_codes_observations_and_retired_discovery(self):
        self.capture(
            "stock_basic",
            {"list_status": "D"},
            [{"ts_code": "T600018.SH", "name": "退市", "symbol": "T600018"}],
        )
        self.capture(
            "etf_basic",
            {},
            [{"ts_code": "510300.SH", "list_status": "D", "list_date": "20000101"}],
        )
        self.capture("fund_basic", {}, [{"ts_code": "000001.OF", "name": "场外"}])
        self.capture(
            "margin_secs",
            {"trade_date": "20260904"},
            [{**source("margin_secs"), "ts_code": "159999.SZ"}],
        )
        ids = self.p.identifiers()
        self.assertEqual(
            ids["credit_securities"], ["159999.SZ", "510300.SH", "T600018.SH"]
        )
        self.assertIn("000001.OF", ids["funds"])
        row, job, result = self.capture(
            "margin_detail",
            {"trade_date": "20260904"},
            [{**source("margin_detail"), "ts_code": "888888.BJ"}],
            has_more=True,
        )
        split = self.p.split_request(row, job, result)
        self.assertFalse(split["universe_complete"])
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE parent_id=?",
                (row["id"],),
            )
        ]
        self.assertEqual(
            {r["ts_code"] for r in children},
            {"159999.SZ", "510300.SH", "T600018.SH", "888888.BJ"},
        )
        self.assertTrue(
            all(
                r["trade_date"] == "20260904" and set(r) == {"trade_date", "ts_code"}
                for r in children
            )
        )
        self.assertEqual(self.p.split_request(row, job, result)["children"], 4)

    def test_malformed_credit_discovery_blocks_only_credit_family(self):
        self.capture(
            "fund_basic", {}, [{"ts_code": "unrecognized-fund", "name": "原始"}]
        )
        config = {
            "enable_credit_extra": True,
            "credit_extra_apis": ["margin_detail"],
            "enable_research_extra": True,
            "research_extra_apis": ["report_rc"],
            "plan_jobs_per_tick": 20,
        }
        report = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertNotIn("recent:credit_extra", report)
        self.assertIn("recent:research_extra", report)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:credit_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertIn("unrecognized-fund", self.p.identifiers()["funds"])

    def test_old_credit_observation_survives_latest_result_replacement(self):
        for code in ("159999.SZ", "510300.SH"):
            self.capture(
                "margin_secs",
                {"trade_date": "20260904"},
                [{**source("margin_secs"), "ts_code": code}],
            )
        self.assertEqual(
            self.p.identifiers()["credit_securities"], ["159999.SZ", "510300.SH"]
        )

    def test_seven_digit_fund_planning_fanout_and_stored_identity(self):
        self.capture(
            "fund_basic",
            {},
            [
                {"ts_code": code, "name": "原始基金"}
                for code in ("150001.SZ", "1500011.SZ", "5010021.SH", "0000371.OF")
            ],
        )
        self.capture(
            "margin_secs",
            {"trade_date": "20260904"},
            [
                {**source("margin_secs"), "ts_code": code}
                for code in ("150001.SZ", "1500011.SZ")
            ],
        )
        self.p.db.execute(
            "INSERT INTO capability VALUES('planning:credit_extra','validation_blocked','old','old error')"
        )
        self.p.db.commit()
        planned = self.p.plan_extended(
            {
                "enable_credit_extra": True,
                "credit_extra_apis": ["margin_detail"],
                "credit_extra_history_start": "20260901",
                "plan_jobs_per_tick": 100,
            },
            date(2026, 9, 9),
        )
        self.assertIn("recent:credit_extra", planned)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:credit_extra'"
            ).fetchone()[0],
            "validation_passed",
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:credit_extra:margin_detail:opaque_fund_identity_unverified'"
            ).fetchone()[0],
            "coverage_unverified",
        )
        for code, expected in (("1500011.SZ", 3), ("5020561.SH", 4)):
            row, job, result = self.capture(
                "margin_detail",
                {"trade_date": "20260904"},
                [{**source("margin_detail"), "ts_code": code}],
                has_more=True,
            )
            split = self.p.split_request(row, job, result)
            self.assertEqual(split["children"], expected)
            self.assertFalse(split["universe_complete"])
            self.assertEqual(
                self.p.split_request(row, job, result)["children"], expected
            )
        children = {
            json.loads(r[0])["params"]["ts_code"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                (row["id"],),
            )
        }
        self.assertEqual(
            children, {"150001.SZ", "1500011.SZ", "5010021.SH", "5020561.SH"}
        )
        release = self.p.publish()
        rows = read_dataset(self.root, release, "margin_secs").to_pylist()
        self.assertEqual({r["ts_code"] for r in rows}, {"SZ150001", "1500011.SZ"})
        self.assertEqual(
            {r["source_ts_code"] for r in rows}, {"150001.SZ", "1500011.SZ"}
        )
        self.assertEqual(
            read_dataset(
                self.root, release, "margin_secs", codes=["1500011.SZ"]
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root, release, "margin_secs", codes=["SZ150001"]
            ).num_rows,
            1,
        )
        master = read_dataset(self.root, release, "fund_basic").to_pylist()
        self.assertIn("0000371.OF", {r["source_ts_code"] for r in master})
        self.assertIn("0000371.OF", {r["ts_code"] for r in master})

    def test_legal_pledge_range_split_and_unsplittable_stock_history(self):
        row, job, result = self.capture(
            "pledge_detail",
            {"start_date": "20260901", "end_date": "20260904"},
            has_more=True,
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["method"], "date_bisection")
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE parent_id=?",
                (row["id"],),
            )
        ]
        self.assertEqual(
            sorted(children, key=lambda r: r["start_date"]),
            [
                {"start_date": "20260901", "end_date": "20260902"},
                {"start_date": "20260903", "end_date": "20260904"},
            ],
        )
        row, job, result = self.capture(
            "pledge_stat", {"ts_code": "T600018.SH"}, has_more=True
        )
        self.assertIsNone(self.p.split_request(row, job, result))
        self.assertEqual(result["status"], "possibly_truncated")
        self.assertNotIn("offset", job["params"])

    def test_planner_flags_signature_gaps_and_family_validation_isolated(self):
        self.assertIn("credit_extra", PLANNERS)
        config = {
            "enable_credit_extra": True,
            "credit_extra_apis": list(FIELDS),
            "credit_extra_history_start": "20260901",
            "plan_jobs_per_tick": 1000,
        }
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:credit_extra", stats)
        self.assertIn("history:credit_extra", stats)
        self.assertEqual(
            {r[0] for r in self.p.db.execute("SELECT DISTINCT group_name FROM jobs")},
            {"credit_extra"},
        )
        count = self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], count
        )
        old = self.p.db.execute(
            "SELECT signature FROM planning_state WHERE name='history:credit_extra'"
        ).fetchone()[0]
        config["credit_extra_history_start"] = "20260831"
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertNotEqual(
            self.p.db.execute(
                "SELECT signature FROM planning_state WHERE name='history:credit_extra'"
            ).fetchone()[0],
            old,
        )
        gaps = {
            r[0]: json.loads(r[1])
            for r in self.p.db.execute("SELECT scope,reason FROM capability")
        }
        self.assertIn("planning:credit_extra:pledge_stat:saturation_gap", gaps)
        self.assertFalse(
            gaps["planning:credit_extra:margin_detail:discovery"]["universe_complete"]
        )
        config.update(
            enable_research_extra=True,
            research_extra_apis=["report_rc"],
            credit_extra_apis=["fake"],
        )
        stats = self.p.plan_extended(config, date(2026, 9, 10))
        self.assertNotIn("recent:credit_extra", stats)
        self.assertIn("recent:research_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:credit_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )


if __name__ == "__main__":
    unittest.main()
