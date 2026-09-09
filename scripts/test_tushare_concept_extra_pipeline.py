"""Isolated concept discovery, source identities and fixed-release integration."""

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
from backend.shared.tushare_concept_extra_contracts import FIELDS, DC_VARIANTS
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, export_jsonl, CONTRACTS

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        {
            k: v
            for k, v in {
                "ts_code": "BK1186.DC" if api == "dc_index" else "885001.TI",
                "trade_date": "20260904",
                "name": "源板块",
                "exchange": "HK",
                "type": "I",
                "con_code": "00013!.HK",
                "con_name": "退市来源",
                "idx_type": "供应商分类",
                "leading_code": "600001.SH",
                "close": 0.0,
                "pct_change": -2.0,
            }.items()
            if k in row
        }
    )
    row["new_supplier_field"] = "保留未知列"
    row.update(updates)
    return row


class ConceptExtraRuntime(unittest.TestCase):
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
        rows = [source(api)] if rows is None else rows
        fields = [f for f in rows[0] if f not in omit]

        def respond(request):
            sent = json.loads(request.content)
            self.assertEqual(set(sent["fields"].split(",")), set(FIELDS[api]))
            self.assertEqual(sent["params"], params)
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

    def test_all_four_capture_publish_read_source_fields_categories_and_repeats(self):
        for api in FIELDS:
            for variant in DC_VARIANTS if api == "dc_index" else [{}]:
                params = {
                    **(
                        {"trade_date": "20260904"}
                        if api in ("ths_daily", "dc_index")
                        else {}
                    ),
                    **variant,
                }
                if api == "ths_member":
                    params = {"ts_code": "885001.TI"}
                rows = [source(api)]
                if api == "ths_member":
                    rows += [
                        source(api, con_code="00013.HK"),
                        source(api, con_code="AAPL"),
                        source(api, con_code="600001.SH"),
                    ]
                for epoch in ("first", "repeat"):
                    self.assertEqual(
                        self.capture(api, params, rows, epoch=epoch)[2]["status"],
                        "sample_ok",
                    )
        release = self.p.publish()
        for api in FIELDS:
            self.assertEqual(contract_for(api)["group"], "concept_extra")
            self.assertEqual(CONTRACTS[api]["keys"], contract_for(api)["keys"])
            table = read_dataset(self.root, release, api)
            rows = table.to_pylist()
            self.assertEqual(
                len(rows), 3 if api == "dc_index" else 4 if api == "ths_member" else 1
            )
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            self.assertTrue(all(r["new_supplier_field"] == "保留未知列" for r in rows))
            self.assertTrue(all(r["ts_code"] == r["source_ts_code"] for r in rows))
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            self.assertIn("history_gap", metadata)
            if api == "ths_member":
                self.assertEqual(
                    {r["con_code"] for r in rows},
                    {"00013!.HK", "00013.HK", "AAPL", "600001.SH"},
                )
                self.assertTrue(
                    all(r["con_code"] == r["source_con_code"] for r in rows)
                )
                self.assertIn("latest members only", metadata["history_gap"])
                self.assertIn("unpublished", metadata["cap_note"])
                self.assertEqual(
                    read_dataset(
                        self.root,
                        release,
                        api,
                        codes=["600001.SH"],
                        code_field="con_code",
                    ).num_rows,
                    1,
                )
            if api == "dc_index":
                self.assertEqual(
                    {json.loads(r["_request_identity"])["idx_type"] for r in rows},
                    {v["idx_type"] for v in DC_VARIANTS},
                )
                self.assertTrue(
                    all(
                        r["leading_code"] == r["source_leading_code"] == "600001.SH"
                        for r in rows
                    )
                )
                self.assertEqual(
                    read_dataset(
                        self.root,
                        release,
                        api,
                        codes=["600001.SH"],
                        code_field="leading_code",
                    ).num_rows,
                    3,
                )
        ids = self.p.identifiers()
        self.assertEqual(ids["ths_indices"], ["885001.TI"])
        self.assertEqual(ids["dc_indices"], ["BK1186.DC"])
        self.assertEqual(ids["stocks"], [])
        self.assertEqual(ids["indexes"], [])

    def test_opaque_stock_shaped_concepts_survive_normalize_store_and_export(self):
        for api in FIELDS:
            params = {"idx_type": "行业板块"} if api == "dc_index" else {}
            self.capture(
                api,
                params,
                [source(api, ts_code="600001.SH"), source(api, ts_code="T600001.SH")],
            )
        release = self.p.publish()
        for api in FIELDS:
            rows = read_dataset(self.root, release, api).to_pylist()
            self.assertEqual({r["ts_code"] for r in rows}, {"600001.SH", "T600001.SH"})
            self.assertEqual(
                read_dataset(self.root, release, api, codes=["600001.SH"]).num_rows, 1
            )
            self.assertEqual(
                read_dataset(self.root, release, api, codes=["T600001.SH"]).num_rows, 1
            )
            with tempfile.TemporaryDirectory() as export_dir:
                output = Path(export_dir) / (api + ".jsonl")
                export_jsonl(self.root, release, api, output, codes=["T600001.SH"])
                self.assertEqual(
                    json.loads(output.read_text())["ts_code"], "T600001.SH"
                )
        self.assertEqual(self.p.identifiers()["stocks"], [])

    def test_hidden_fields_missing_is_gap_null_unavailable_is_not_fabricated(self):
        for api in ("ths_daily", "ths_member"):
            hidden = contract_for(api)["hidden_fields"]
            self.assertEqual(self.capture(api, {})[2]["status"], "sample_ok")
            result = self.capture(api, {}, epoch="missing", omit=hidden)[2]
            self.assertEqual(result["status"], "schema_gap")
            self.assertEqual(set(result["missing_fields"]), set(hidden))
        self.capture("dc_index", {"trade_date": "20260904"})
        release = self.p.publish()
        with self.assertRaisesRegex(ValueError, "Request identity gap"):
            read_dataset(self.root, release, "dc_index")

    def test_planning_discovery_and_gap_validation_isolate_other_families(self):
        config = {"enable_concept_extra": True, "plan_jobs_per_tick": 1000}
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:concept_extra", stats)
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 29
        )
        self.assertIn(
            "awaiting_stored_ths_indices",
            self.p.db.execute(
                "SELECT reason FROM capability WHERE scope='planning:concept_extra:ths_member:discovery'"
            ).fetchone()[0],
        )
        self.capture(
            "ths_index",
            {},
            [
                source("ths_index", ts_code="retired.TH"),
                source("ths_index", ts_code="foreign.TH"),
            ],
        )
        self.p.plan_extended(config, date(2026, 9, 9))
        member_params = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE json_extract(job,'$.api_name')='ths_member'"
            )
        ]
        self.assertEqual(
            member_params, [{"ts_code": "foreign.TH"}, {"ts_code": "retired.TH"}]
        )
        for scope in (
            "history_gap",
            "cap_note",
            "hidden_fields_require_response_evidence",
        ):
            self.assertIsNotNone(
                self.p.db.execute(
                    "SELECT reason FROM capability WHERE scope=?",
                    ("planning:concept_extra:ths_member:" + scope,),
                ).fetchone()
            )
        previous = self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], previous
        )
        bad_ids = self.p.identifiers()
        bad_ids["ths_indices"] = ["bad,code"]
        with patch.object(self.p, "identifiers", return_value=bad_ids):
            stats = self.p.plan_extended(
                {
                    **config,
                    "enable_listing_extra": True,
                    "listing_extra_apis": ["bse_mapping"],
                },
                date(2026, 9, 9),
            )
        self.assertNotIn("recent:concept_extra", stats)
        self.assertIn("recent:listing_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:concept_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertIn(
            '"backend/shared/tushare_concept_extra_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )

    def test_date_split_and_source_only_fanout_keep_categories_and_gaps(self):
        self.capture("ths_index", {}, [source("ths_index", ts_code="retired.TH")])
        for api in ("ths_daily", "dc_index"):
            variant = {"idx_type": "地域板块"} if api == "dc_index" else {}
            row, job, result = self.capture(
                api,
                {"start_date": "20260903", "end_date": "20260904", **variant},
                more=True,
            )
            self.assertEqual(
                self.p.split_request(row, job, result)["method"], "date_bisection"
            )
            row, job, result = self.capture(
                api, {"trade_date": "20260904", **variant}, more=True
            )
            split = self.p.split_request(row, job, result)
            self.assertFalse(split["universe_complete"])
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {r["ts_code"] for r in children},
                {"BK1186.DC"} if api == "dc_index" else {"885001.TI", "retired.TH"},
            )
            self.assertTrue(
                all(all(r[k] == v for k, v in variant.items()) for r in children)
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
        # No invented member con_code fanout or snapshot date parameters.
        for api, params in (
            ("ths_index", {}),
            ("ths_member", {"ts_code": "885001.TI"}),
            (
                "dc_index",
                {
                    "trade_date": "20260904",
                    "ts_code": "BK1186.DC",
                    "idx_type": "地域板块",
                },
            ),
        ):
            row, job, result = self.capture(api, params, more=True, epoch="terminal")
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertIsNone(self.p.split_request(row, job, result))


if __name__ == "__main__":
    unittest.main()
