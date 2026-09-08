"""Offline limit-pool request identities, hidden fields and namespace isolation."""

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
from backend.shared.tushare_limit_extra_contracts import (
    FIELDS,
    INPUT_FIELDS,
    VARIANTS,
    HIDDEN_THS_FIELDS,
)
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, CONTRACTS as READ_CONTRACTS

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        {
            k: v
            for k, v in {
                "trade_date": "20260904",
                "ts_code": "885728.TI" if api == "limit_cpt_list" else "T600018.SH",
                "name": "ST源名称",
                "limit_type": "供应商池标签",
                "limit": "U",
                "lu_desc": "原因甲",
                "tag": "标签",
                "market_type": "HS",
                "price": 0.0,
                "pct_chg": -10.0,
                "nums": "02",
                "rank": "01",
                "up_stat": "9天7板",
            }.items()
            if k in row
        }
    )
    row["new_supplier_field"] = "原始扩展字段"
    row.update(updates)
    return row


class LimitExtraRuntime(unittest.TestCase):
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

    def capture(self, api, params, rows=None, more=False, epoch="test", omit=()):
        key = self.p.enqueue(api, params, 10, epoch)
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        rows = rows if rows is not None else [source(api)]
        fields = [f for f in rows[0] if f not in omit]

        def respond(request):
            sent = json.loads(request.content)
            self.assertEqual(set(sent["fields"].split(",")), set(FIELDS[api]))
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
        return (
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone(),
            job,
            result,
        )

    def raw_discovery(self, api, records):
        fields = list(records[0])
        payload = {
            "code": 0,
            "data": {
                "fields": fields,
                "items": [[r.get(f) for f in fields] for r in records],
            },
        }
        raw = module.json_bytes(payload)
        sha = module.digest(raw)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (sha + ".json")).write_bytes(raw)
        result = {"api_name": api, "object_sha256": sha}
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            ("fixture-" + api, 1, json.dumps(result)),
        )

    def test_capture_publish_read_keeps_all_pool_identities_and_source_rows(self):
        # Deliberately same vendor label/payload across requests: provenance is
        # preserved without claiming that supplier filter semantics were verified.
        for api in FIELDS:
            for variant in VARIANTS[api]:
                params = {"trade_date": "20260904", **variant}
                rows = [source(api)]
                if api == "limit_list_ths":
                    rows.append(source(api, lu_desc="原因乙"))
                for epoch in ("first", "repeat"):
                    result = self.capture(api, params, rows, epoch=epoch)[2]
                    self.assertEqual(result["status"], "sample_ok")
                    observed = json.loads(
                        (
                            self.root / "observations" / result["observation"]
                        ).read_bytes()
                    )
                    self.assertEqual(observed["request"]["params"], params)
        release = self.p.publish()
        for api in FIELDS:
            self.assertEqual(contract_for(api)["group"], "limit_extra")
            self.assertEqual(
                READ_CONTRACTS[api]["request_identity_fields"],
                contract_for(api)["request_identity_fields"],
            )
            table = read_dataset(self.root, release, api)
            rows = table.to_pylist()
            count = len(VARIANTS[api]) * (2 if api == "limit_list_ths" else 1)
            self.assertEqual(len(rows), count)
            self.assertEqual(len({r["_row_identity"] for r in rows}), count)
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            self.assertTrue(
                all(r["new_supplier_field"] == "原始扩展字段" for r in rows)
            )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            code = "885728.TI" if api == "limit_cpt_list" else "SHT600018"
            self.assertEqual(
                read_dataset(
                    self.root,
                    release,
                    api,
                    codes=[code],
                    start_date="20260904",
                    end_date="20260904",
                ).num_rows,
                count,
            )
            if api in ("limit_list_ths", "limit_list_d"):
                self.assertEqual(
                    {json.loads(r["_request_identity"])["limit_type"] for r in rows},
                    {v["limit_type"] for v in VARIANTS[api]},
                )
                self.assertEqual(
                    metadata["request_identity_status"],
                    "verified_from_immutable_observations",
                )
        self.assertEqual(
            read_dataset(self.root, release, "limit_step").to_pylist()[0]["nums"], "02"
        )
        self.assertEqual(
            read_dataset(self.root, release, "limit_cpt_list").to_pylist()[0]["rank"],
            "01",
        )

    def test_hidden_fields_are_sent_missing_is_gap_and_nulls_are_valid(self):
        params = {"trade_date": "20260904", "limit_type": "跌停池"}
        _, job, result = self.capture("limit_list_ths", params)
        self.assertEqual(result["status"], "sample_ok")
        self.assertTrue(set(HIDDEN_THS_FIELDS) <= set(job["fields"].split(",")))
        result = self.capture(
            "limit_list_ths", params, epoch="missing", omit=HIDDEN_THS_FIELDS
        )[2]
        self.assertEqual(result["status"], "schema_gap")
        self.assertEqual(
            set(result["requested_missing_fields"]), set(HIDDEN_THS_FIELDS)
        )
        self.assertEqual(set(result["missing_fields"]), set(HIDDEN_THS_FIELDS))

    def test_missing_pool_identity_cannot_enter_fixed_release_read(self):
        for api in ("limit_list_ths", "limit_list_d"):
            self.capture(api, {"trade_date": "20260904"})
        release = self.p.publish()
        for api in ("limit_list_ths", "limit_list_d"):
            with self.assertRaisesRegex(ValueError, "Request identity gap"):
                read_dataset(self.root, release, api)

    def test_stock_discovery_and_concept_fanout_are_separate_and_unverified(self):
        self.raw_discovery(
            "stock_basic", [{"ts_code": "T600001.SH", "list_status": "D"}]
        )
        self.raw_discovery("bak_basic", [{"ts_code": "600002.SH"}])
        self.raw_discovery("top_list", [{"ts_code": "600003.SH"}])
        self.capture(
            "limit_cpt_list",
            {"trade_date": "20260903"},
            [source("limit_cpt_list", ts_code="886000.TI")],
        )
        row, job, result = self.capture(
            "limit_list_ths",
            {"trade_date": "20260904", "limit_type": "连扳池", "market": "GEM"},
            more=True,
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["children"], 4)
        self.assertFalse(split["universe_complete"])
        ids = self.p.identifiers()
        self.assertEqual(
            set(ids["limit_securities"]),
            {"T600001.SH", "600002.SH", "600003.SH", "T600018.SH"},
        )
        self.assertEqual(ids["limit_concepts"], ["886000.TI"])
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                (row["id"],),
            )
        ]
        self.assertTrue(
            all(
                p["limit_type"] == "连扳池"
                and p["market"] == "GEM"
                and p["trade_date"] == "20260904"
                for p in children
            )
        )
        row, job, result = self.capture(
            "limit_cpt_list", {"trade_date": "20260904"}, more=True
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["children"], 2)
        self.assertFalse(split["universe_complete"])
        self.assertNotIn("885728.TI", self.p.identifiers()["stocks"])
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

    def test_concept_labels_are_never_normalized_as_stocks(self):
        # Opaque future source labels are preserved; this does not certify a
        # stock-shaped concept label as a valid supplier request identifier.
        self.capture(
            "limit_cpt_list",
            {"trade_date": "20260904"},
            [source("limit_cpt_list", ts_code="600001.SH")],
        )
        release = self.p.publish()
        row = read_dataset(self.root, release, "limit_cpt_list").to_pylist()[0]
        self.assertEqual(row["ts_code"], "600001.SH")
        self.assertEqual(row["source_ts_code"], "600001.SH")
        self.assertEqual(self.p.identifiers()["limit_concepts"], ["600001.SH"])
        self.assertEqual(self.p.identifiers()["stocks"], [])

    def test_terminal_saturation_blocks_and_d_pool_exchange_survives_range_split(self):
        row, job, result = self.capture(
            "limit_list_d",
            {
                "start_date": "20260903",
                "end_date": "20260904",
                "limit_type": "D",
                "exchange": "BJ",
            },
            more=True,
        )
        self.assertEqual(
            self.p.split_request(row, job, result)["method"], "date_bisection"
        )
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                (row["id"],),
            )
        ]
        self.assertTrue(
            all(p["limit_type"] == "D" and p["exchange"] == "BJ" for p in children)
        )
        self.p.db.execute("UPDATE jobs SET state='blocked'")
        pending = self.p.enqueue(
            "limit_list_d",
            {"trade_date": "20260905", "ts_code": "600001.SH", "limit_type": "Z"},
            1,
            "terminal",
        )

        def respond(request):
            row = source("limit_list_d")
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
                client, "fixture", {}, max_requests=1, max_seconds=10, pause=0
            )
        self.assertEqual(result["requests"], 1)
        self.assertEqual(
            self.p.db.execute(
                "SELECT state FROM jobs WHERE id=?", (pending,)
            ).fetchone()[0],
            "blocked",
        )

    def test_all_seventy_recent_partitions_and_st_gap_are_registered(self):
        config = {
            "enable_limit_extra": True,
            "limit_extra_history_start": "20260903",
            "plan_jobs_per_tick": 1000,
        }
        self.assertIn(
            "recent:limit_extra", self.p.plan_extended(config, date(2026, 9, 9))
        )
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 70
        )
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 70
        )
        reason = self.p.db.execute(
            "SELECT reason FROM capability WHERE scope='planning:limit_extra:limit_list_d:category_gap'"
        ).fetchone()[0]
        self.assertIn("excludes ST", reason)
        config.update(
            limit_extra_apis=["bad"],
            enable_listing_extra=True,
            listing_extra_apis=["bse_mapping"],
        )
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertNotIn("recent:limit_extra", stats)
        self.assertIn("recent:listing_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:limit_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertIn(
            '"backend/shared/tushare_limit_extra_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
