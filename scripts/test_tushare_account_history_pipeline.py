"""Stopped account statistics: raw periods, fixed interval reads and scope policy."""

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
from backend.shared import tushare_pipeline as module  # noqa: E402
from backend.shared.tushare_account_history_contracts import FIELDS, FIELD_METADATA  # noqa: E402
from backend.shared.tushare_registry import contract_for  # noqa: E402
from backend.shared.tushare_store import read_dataset, dataset_schema, export_jsonl  # noqa: E402
import test_tushare_technical_extra_pipeline as fixtures  # noqa: E402


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row["date"] = "20181228" if api == "stk_account" else "20141229~0102"
    if api == "stk_account":
        row.update(weekly_new=0.0, total=1000.5)
    else:
        row.update(new_sh=0, new_sz=12, total_sh=800.5)
    row.update(unknown_source="原文", ts_code="label-not-a-stock")
    row.update(updates)
    return row


class AccountHistoryRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    capture = fixtures.TechnicalExtraRuntime.capture

    def test_full14_columns_unknown_null_and_revisions_without_cross_api_alias(self):
        empty = self.p.publish()
        first_time = None
        expected = {}
        for api in FIELDS:
            original = source(api)
            params = {"start_date": "20140101", "end_date": "20181231"}
            first = self.capture(api, params, [original], epoch="old")[2]
            if first_time is None:
                first_time = json.loads(
                    (self.root / "observations" / first["observation"]).read_bytes()
                )["fetched_at"]
            rows = [original, source(api, unknown_source="修订")]
            for epoch in ("new", "repeat"):
                self.capture(api, params, rows, epoch=epoch)
            expected[api] = {module.digest(module.json_bytes(r)): r for r in rows}
        fixed = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, fixed, api)
            self.assertEqual(table.num_rows, 2)
            for row in table.to_pylist():
                raw = expected[api][row["_row_identity"]]
                self.assertEqual({field: row[field] for field in raw}, raw)
                self.assertNotIn("source_ts_code", row)
            schema = dataset_schema(self.root, fixed, api)
            self.assertEqual(schema["default_date_field"], "date")
            self.assertEqual(schema["field_metadata"], FIELD_METADATA[api])
            self.assertEqual(schema["permission_status"], "unprobed")
            self.assertTrue(schema["stopped_updates"])
            self.assertIsNone(schema["documented_row_cap"])
            self.assertIn("boundary_gap", schema)
            self.assertIn("pit_gap", schema)
            self.assertIn("_row_identity", schema["keys"])
            with self.assertRaises(ValueError):
                read_dataset(self.root, empty, api)
        self.assertEqual(
            read_dataset(self.root, fixed, "stk_account", as_of=first_time).num_rows, 1
        )
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                "stk_account",
                start_date="20181228",
                end_date="20181228",
            ).num_rows,
            2,
        )
        self.assertEqual(
            read_dataset(
                self.root, fixed, "stk_account", start_date="20181229"
            ).num_rows,
            0,
        )

    def test_crossyear_interval_overlap_and_explicit_endpoint_queries(self):
        api = "stk_account_old"
        raw_dates = ["20141222~1226", "20141229~0102", "20150105~0109", "20160228~0301"]
        self.capture(
            api,
            {"start_date": "20141201", "end_date": "20160301"},
            [source(api, date=d) for d in raw_dates],
        )
        fixed = self.p.publish()
        cross = read_dataset(
            self.root, fixed, api, start_date="20150101", end_date="20150101"
        )
        self.assertEqual(cross.num_rows, 1)
        self.assertEqual(cross.to_pylist()[0]["date"], "20141229~0102")
        self.assertEqual(cross.to_pylist()[0]["_period_start"], "20141229")
        self.assertEqual(cross.to_pylist()[0]["_period_end"], "20150102")
        self.assertEqual(
            read_dataset(
                self.root, fixed, api, start_date="20150102", end_date="20150102"
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root, fixed, api, start_date="20150103", end_date="20150104"
            ).num_rows,
            0,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                api,
                start_date="20150101",
                end_date="20150102",
                date_field="_period_start",
            ).num_rows,
            0,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                api,
                start_date="20150101",
                end_date="20150102",
                date_field="_period_end",
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root, fixed, api, start_date="20160229", end_date="20160229"
            ).num_rows,
            1,
        )
        schema = dataset_schema(self.root, fixed, api)
        self.assertEqual(schema["period_projection_unverified_rows"], 0)
        self.assertIn("inclusive overlap", schema["period_date_semantics"])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "period.jsonl"
            export_jsonl(
                self.root,
                fixed,
                api,
                target,
                fields=["date", "new_sh"],
                start_date="20150101",
                end_date="20150101",
            )
            self.assertEqual(
                json.loads(target.read_text()), {"date": "20141229~0102", "new_sh": 0}
            )
        with self.assertRaises(ValueError):
            read_dataset(
                self.root, fixed, api, date_field="total_sh", start_date="20150101"
            )
        with self.assertRaises(ValueError):
            read_dataset(self.root, fixed, api, fields=["date;DROP TABLE stored"])

    def test_unknown_period_stays_published_raw_and_blocks_only_ambiguous_date_query(
        self,
    ):
        api = "stk_account_old"
        first = self.capture(
            api,
            {"start_date": "20141201", "end_date": "20141231"},
            [source(api)],
            epoch="good",
        )[2]
        asof = json.loads(
            (self.root / "observations" / first["observation"]).read_bytes()
        )["fetched_at"]
        key = self.p.enqueue(
            api, {"start_date": "20150101", "end_date": "20150131"}, 1, "unknown"
        )
        rows = [
            source(api, date=d)
            for d in ("future-pattern", "20140229~0301", "20141201~1215")
        ]
        payload = {
            "code": 0,
            "data": {
                "fields": list(rows[0]),
                "items": [list(r.values()) for r in rows],
            },
        }
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
            trust_env=False,
        ) as client:
            report = self.p.run(
                client, "fixture", {}, max_requests=1, max_seconds=5, pause=0
            )
        self.assertEqual(report["requests"], 1)
        saved = self.p.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (key,)
        ).fetchone()
        self.assertEqual(saved["state"], "blocked")
        result = json.loads(saved["result"])
        self.assertEqual(
            result["period_projection_gap"], "period_projection_unverified"
        )
        self.assertEqual(result["period_projection_unverified_rows"], 3)
        self.assertTrue((self.root / result["parquet"]["path"]).is_file())
        raw = json.loads(
            (self.root / "objects" / (result["object_sha256"] + ".json")).read_bytes()
        )
        self.assertEqual(raw, payload)
        fixed = self.p.publish()
        allrows = read_dataset(self.root, fixed, api).to_pylist()
        self.assertEqual(len(allrows), 4)
        self.assertEqual(
            dataset_schema(self.root, fixed, api)["period_projection_unverified_rows"],
            3,
        )
        self.assertEqual(
            {
                r["date"]
                for r in allrows
                if r["_period_projection_status"] == "period_projection_unverified"
            },
            {r["date"] for r in rows},
        )
        with self.assertRaisesRegex(ValueError, "period_projection_unverified"):
            read_dataset(self.root, fixed, api, start_date="20150101")
        # A later unknown observation must not poison an earlier fixed as_of view.
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                api,
                as_of=asof,
                start_date="20150101",
                end_date="20150101",
            ).num_rows,
            1,
        )

    def test_only_explicit_month_history_with_real_policy_key_and_completed_refresh(
        self,
    ):
        self.p.plan_extended({}, date(2015, 6, 1))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        self.p.plan_extended({"enable_account_history": True}, date(2015, 6, 1))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        cfg = {
            "enable_account_history": True,
            "account_history_history_start": "20150501",
            "plan_jobs_per_tick": 100,
        }
        self.p.plan_extended(cfg, date(2015, 6, 1))
        before = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:account_history'"
            ).fetchone()
        )
        self.assertTrue(before["done"])
        oldjobs = {r["id"]: dict(r) for r in self.p.db.execute("SELECT * FROM jobs")}
        self.assertTrue(all(r["epoch"] == "history" for r in oldjobs.values()))
        oldparams = [
            json.loads(r["job"])["params"]
            for r in oldjobs.values()
            if json.loads(r["job"])["api_name"] == "stk_account_old"
        ]
        self.assertEqual(
            oldparams, [{"start_date": "20150501", "end_date": "20150529"}]
        )
        changed = {**cfg, "account_history_history_start": "20150401"}
        self.p.plan_extended(changed, date(2015, 6, 1))
        after = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:account_history'"
            ).fetchone()
        )
        self.assertNotEqual(before["signature"], after["signature"])
        for key, old in oldjobs.items():
            self.assertEqual(
                dict(
                    self.p.db.execute(
                        "SELECT * FROM jobs WHERE id=?", (key,)
                    ).fetchone()
                ),
                old,
            )
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM jobs WHERE json_extract(job,'$.params.start_date')='20150401'"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(module._planning_inputs("account_history", changed, {})[1], {})
        self.assertEqual(
            module._planning_inputs("account_history", changed, {}),
            module._planning_inputs(
                "account_history", changed, {"stocks": ["T600018.SH"]}
            ),
        )

    def test_guard_has_no_fake_old_period_bisection_or_offset_and_new_range_splits(
        self,
    ):
        for api in FIELDS:
            result = self.capture(
                api,
                {"start_date": "20141201", "end_date": "20141231"},
                [source(api)],
                more=True,
            )
            split = self.p.split_request(*result)
            if api == "stk_account_old":
                self.assertIsNone(split)
                self.assertIsNone(contract_for(api)["split"])
                self.assertNotIn("date", contract_for(api)["allowed_params"])
            else:
                self.assertEqual(split["method"], "date_bisection")
            self.assertIsNone(contract_for(api)["documented_row_cap"])
            self.assertFalse(contract_for(api)["row_cap_verified"])
            self.assertNotIn("offset", contract_for(api)["allowed_params"])

    def test_old_guard_saturation_preserves_rows_without_unproven_children(self):
        api = "stk_account_old"
        key = self.p.enqueue(
            api, {"start_date": "20141201", "end_date": "20141231"}, 1, "cap"
        )
        raw = source(api)
        payload = {
            "code": 0,
            "data": {"fields": list(raw), "items": [list(raw.values())] * 1000},
        }
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
            trust_env=False,
        ) as client:
            self.p.run(client, "fixture", {}, max_requests=1, max_seconds=5, pause=0)
        saved = self.p.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (key,)
        ).fetchone()
        self.assertEqual(saved["state"], "blocked")
        result = json.loads(saved["result"])
        self.assertEqual(result["status"], "possibly_truncated")
        self.assertEqual(result["row_count"], 1000)
        self.assertTrue((self.root / result["parquet"]["path"]).is_file())
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )
        self.assertFalse(result["history_complete"])

    def test_nullable_columns_are_still_required_and_permission_denial_is_retained(
        self,
    ):
        for api in FIELDS:
            result = self.capture(
                api,
                {"start_date": "20141201", "end_date": "20141231"},
                [source(api)],
                omit=[FIELDS[api][-1]],
                epoch="missing",
            )[2]
            self.assertEqual(result["status"], "schema_gap")
            self.assertEqual(result["requested_missing_fields"], [FIELDS[api][-1]])
        key = self.p.enqueue(
            "stk_account_old",
            {"start_date": "20130101", "end_date": "20130131"},
            1,
            "denied",
        )
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"code": -2002, "msg": "没有访问该接口权限", "data": None}
                )
            ),
            trust_env=False,
        ) as client:
            self.p.run(client, "fixture", {}, max_requests=1, max_seconds=5, pause=0)
        saved = self.p.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (key,)
        ).fetchone()
        self.assertEqual(saved["state"], "blocked")
        self.assertEqual(json.loads(saved["result"])["status"], "permission_denied")
        newer = self.p.enqueue(
            "stk_account_old",
            {"start_date": "20130201", "end_date": "20130228"},
            1,
            "later",
        )
        self.assertEqual(
            self.p.db.execute("SELECT state FROM jobs WHERE id=?", (newer,)).fetchone()[
                0
            ],
            "permission_blocked",
        )

    def test_no_identifier_cache_edits_needed_and_mirror_contains_pure_module(self):
        self.assertIn(
            '"backend/shared/tushare_account_history_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )
        cfg = {"history_start": "20000101"}
        for family in module.PLANNERS:
            if family != "account_history":
                self.assertEqual(
                    module._planning_inputs(family, cfg, {}),
                    module._planning_inputs(
                        family,
                        {
                            **cfg,
                            "enable_account_history": True,
                            "account_history_history_start": "20080101",
                            "account_history_apis": ["stk_account_old"],
                        },
                        {},
                    ),
                )


if __name__ == "__main__":
    unittest.main()
