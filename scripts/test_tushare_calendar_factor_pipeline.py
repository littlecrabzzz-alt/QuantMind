"""Calendar/factor capture -> normalization -> fixed reader, isolated and offline."""

from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_calendar_extra_contracts import FIELD_METADATA as CAL_FIELDS
from backend.shared.tushare_factor_library_contracts import (
    FIELD_METADATA as FACTOR_FIELDS,
)
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, dataset_schema
import test_tushare_technical_extra_pipeline as fixtures

FIELDS = {**CAL_FIELDS, **FACTOR_FIELDS}


def source(api, **updates):
    row = {
        f: "source-label" if m["type"] == "str" else -1.25
        for f, m in FIELDS[api].items()
    }
    for field, value in {
        "date": "20260904",
        "ann_date": "20260904",
        "publish_date": "20260904",
        "month": "202609",
        "trade_date": "20260904",
        "ts_code": "T600001.SH",
        "factor_name": "Observed_CASE",
        "asset_type": "STK",
        "time": "08:30",
        "value": "1.2K",
        "pre_value": None,
        "fore_value": "3%",
        "data_api": "待上线",
        "url": "https://example.test/announcement",
    }.items():
        if field in row:
            row[field] = value
    row["supplier_extra"] = None
    row.update(updates)
    return row


def params(api):
    return {
        "eco_cal": {"date": "20260904"},
        "cn_schedule": {"m": "202609"},
        "idx_anns": {"ann_date": "20260904"},
        "factor_list": {},
        "factor_value": {"factor_name": "Observed_CASE", "trade_date": "20260904"},
    }[api]


class CalendarFactorRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    discovery = fixtures.TechnicalExtraRuntime.discovery
    capture = fixtures.TechnicalExtraRuntime.capture

    def test_capture_all26_fields_unknown_null_revisions_fixed_read(self):
        old = self.p.publish()
        expected = {}
        for api in FIELDS:
            rows = [source(api), source(api, supplier_extra="revision")]
            if api == "factor_value":
                rows.append(source(api, ts_code="600001.SH"))
            expected[api] = {module.digest(module.json_bytes(r)): r for r in rows}
            for epoch in ("first", "repeat"):
                self.assertEqual(
                    self.capture(api, params(api), rows, epoch=epoch)[2]["status"],
                    "sample_ok",
                )
        fixed = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, fixed, api)
            self.assertEqual(table.num_rows, len(expected[api]))
            for row in table.to_pylist():
                raw = expected[api][row["_row_identity"]]
                for field, value in raw.items():
                    self.assertEqual(
                        row[
                            "source_ts_code"
                            if api == "factor_value" and field == "ts_code"
                            else field
                        ],
                        value,
                    )
            self.assertEqual(set(FIELDS[api]) - set(table.column_names), set())
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["permission_status"], "unprobed")
            self.assertEqual(set(metadata["field_metadata"]), set(FIELDS[api]))
            self.assertEqual(metadata["deduplication_mode"], "distinct_supplier_rows")
            for note in ("history_gap", "pit_gap", "identity_gap", "saturation_gap"):
                self.assertEqual(metadata[note], contract_for(api)[note])
            self.assertEqual(
                dataset_schema(self.root, fixed, api)["default_date_field"],
                contract_for(api)["date_field"],
            )
            if api != "factor_list":
                self.assertEqual(
                    read_dataset(
                        self.root,
                        fixed,
                        api,
                        start_date="20260904",
                        end_date="20260904",
                    ).num_rows,
                    table.num_rows,
                )
                self.assertEqual(
                    read_dataset(self.root, fixed, api, start_date="20260905").num_rows,
                    0,
                )
            with self.assertRaisesRegex(ValueError, "Dataset unavailable"):
                read_dataset(self.root, old, api)
        self.assertEqual(
            {
                r["ts_code"]
                for r in read_dataset(self.root, fixed, "factor_value").to_pylist()
            },
            {"SHT600001", "SH600001"},
        )
        self.assertEqual(
            read_dataset(
                self.root, fixed, "factor_value", codes=["SHT600001"]
            ).num_rows,
            2,
        )
        with self.assertRaises(ValueError):
            read_dataset(self.root, fixed, "factor_list", start_date="20260901")
        from backend.shared.tushare_documents import enqueue_documents

        with patch(
            "backend.shared.tushare_documents.enqueue_documents",
            wraps=enqueue_documents,
        ) as enqueue:
            self.p.register_documents(max_observations=100)
        self.assertTrue(enqueue.called)
        self.assertEqual(
            {call.args[2] for call in enqueue.call_args_list}, {"idx_anns"}
        )
        self.assertTrue(all(call.args[4] == ["url"] for call in enqueue.call_args_list))

    def test_disabled_actual_factor_name_asset_discovery_and_scope(self):
        self.p.plan_extended({}, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        self.discovery(
            "factor_list",
            [
                source("factor_list"),
                source(
                    "factor_list",
                    factor_name="Observed_CASE",
                    factor_desc="revised definition",
                ),
                source("factor_list", factor_name="Other", asset_type="ETF"),
                source("factor_list", factor_name="collision"),
                source("factor_list", factor_name="collision", asset_type="IDX"),
            ],
        )
        self.discovery(
            "factor_value",
            [
                source(
                    "factor_value", factor_name="not_a_list_seed", ts_code="T600009.SH"
                )
            ],
        )
        self.discovery("stock_basic", [{"ts_code": "600001.SH", "list_status": "D"}])
        self.discovery("bak_basic", [{"ts_code": "T000002.SZ"}])
        ids = self.p.identifiers()
        self.assertEqual(len(ids["factor_library_factors"]), 4)
        self.assertNotIn(
            "not_a_list_seed", {r["factor_name"] for r in ids["factor_library_factors"]}
        )
        self.assertEqual(
            set(ids["factor_library_stocks"]), {"T600009.SH", "600001.SH", "T000002.SZ"}
        )
        self.assertEqual(ids["stocks"], ["600001.SH"])
        cfg = {
            "enable_calendar_extra": True,
            "enable_factor_library": True,
            "history_start": "20260901",
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(cfg, date(2026, 9, 4))
        jobs = [
            json.loads(r[0])
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE group_name IN ('calendar_extra','factor_library') AND state='pending'"
            )
        ]
        self.assertEqual({j["api_name"] for j in jobs}, set(FIELDS))
        self.assertEqual(
            {
                j["params"]["factor_name"]
                for j in jobs
                if j["api_name"] == "factor_value"
            },
            {"Observed_CASE"},
        )
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(cfg, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], count
        )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT 1 FROM capability WHERE scope='planning:factor_library:factor_value:discovery'"
            ).fetchone()
        )
        self.assertEqual(
            module._planning_inputs("factor_library", cfg, ids)[1],
            {"factor_library_factors": ids["factor_library_factors"]},
        )

    def test_missing_or_invalid_discovery_does_not_block_calendar(self):
        cfg = {
            "enable_calendar_extra": True,
            "enable_factor_library": True,
            "plan_jobs_per_tick": 100,
        }
        self.p.plan_extended(cfg, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM jobs WHERE json_extract(job,'$.api_name')='factor_value'"
            ).fetchone()[0],
            0,
        )
        ids = self.p.identifiers()
        ids["factor_library_factors"] = [{"factor_name": None, "asset_type": "STK"}]
        with patch.object(self.p, "identifiers", return_value=ids):
            stats = self.p.plan_extended(cfg, date(2026, 9, 5))
        self.assertIn("recent:calendar_extra", stats)
        self.assertNotIn("recent:factor_library", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:factor_library'"
            ).fetchone()[0],
            "validation_blocked",
        )

    def test_new_family_inputs_do_not_change_any_old_family_signature(self):
        ids = self.p.identifiers()
        cfg = {"history_start": "20200101"}
        before = {
            family: module._planning_inputs(family, cfg, ids)
            for family in module.PLANNERS
            if family not in ("calendar_extra", "factor_library")
        }
        newer = {
            **cfg,
            "enable_factor_library": True,
            "factor_library_apis": ["factor_list", "factor_value"],
            "factor_library_history_start": "19900101",
            "calendar_extra_history_start": "19950101",
        }
        newids = {
            **ids,
            "factor_library_factors": [{"factor_name": "new", "asset_type": "STK"}],
            "factor_library_stocks": ["T600001.SH"],
        }
        self.assertEqual(
            before,
            {
                family: module._planning_inputs(family, newer, newids)
                for family in before
            },
        )
        first = module._planning_inputs("factor_library", {}, newids)
        self.assertEqual(
            first,
            module._planning_inputs(
                "factor_library",
                {},
                {**newids, "factor_library_stocks": ["T600002.SH"]},
            ),
        )
        self.assertNotEqual(
            first,
            module._planning_inputs(
                "factor_library", {}, {**newids, "factor_library_factors": []}
            ),
        )
        self.assertNotEqual(
            first,
            module._planning_inputs(
                "factor_library", {"factor_library_history_start": "19900101"}, newids
            ),
        )

    def test_legal_range_children_month_and_terminal_cap_gaps(self):
        for api in ("eco_cal", "idx_anns", "factor_value"):
            p = {**params(api), "start_date": "20240228", "end_date": "20240301"}
            p.pop("date", None)
            p.pop("ann_date", None)
            p.pop("trade_date", None)
            children = self.p.date_children({"api_name": api, "params": p})
            self.assertEqual(
                children,
                [{**p, "end_date": "20240229"}, {**p, "start_date": "20240301"}],
            )
        for api in (
            "eco_cal",
            "cn_schedule",
            "idx_anns",
            "factor_list",
            "factor_value",
        ):
            self.assertIsNone(
                self.p.date_children({"api_name": api, "params": params(api)})
            )
        self.assertEqual(
            contract_for("factor_value")["saturation_fallback"], "factor_library_stocks"
        )
        self.assertFalse(contract_for("factor_list")["row_cap_verified"])
        self.assertEqual(contract_for("eco_cal")["row_cap"], 100)

    def test_code_only_value_probe_is_readable_but_not_a_name_discovery_seed(self):
        code_params = {"ts_code": "T600001.SH", "trade_date": "20260904"}
        self.capture("factor_value", code_params, [source("factor_value")])
        fixed = self.p.publish()
        self.assertEqual(read_dataset(self.root, fixed, "factor_value").num_rows, 1)
        ids = self.p.identifiers()
        self.assertEqual(ids["factor_library_factors"], [])
        self.assertEqual(ids["factor_library_stocks"], ["T600001.SH"])
        jobs = list(module.PLANNERS["factor_library"]({}, date(2026, 9, 4), ids))
        self.assertEqual({j["api_name"] for j in jobs}, {"factor_list"})

    def test_actual_run_terminal_caps_keep_raw_and_block(self):
        keys = []
        for api in FIELDS:
            request_params = params(api)
            if api == "factor_value":
                request_params = {**request_params, "ts_code": "T600001.SH"}
            keys.append(self.p.enqueue(api, request_params, 10, "cap"))

        def respond(request):
            sent = json.loads(request.content)
            row = source(sent["api_name"])
            self.assertEqual(
                set(sent["fields"].split(",")), set(FIELDS[sent["api_name"]])
            )
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
            outcome = self.p.run(
                client, "fixture", {}, max_requests=5, max_seconds=10, pause=0
            )
        self.assertEqual(outcome["requests"], 5)
        for key in keys:
            row = self.p.db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (key,)
            ).fetchone()
            self.assertEqual(row["state"], "blocked")
            result = json.loads(row["result"])
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertTrue(
                (self.root / "observations" / result["observation"]).is_file()
            )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )

    def test_unknown_market_code_is_raw_quality_not_invented_equity(self):
        with self.assertRaisesRegex(ValueError, "source STK code"):
            self.capture(
                "factor_value",
                params("factor_value"),
                [source("factor_value", ts_code="00013.HK")],
            )
        self.assertTrue(list((self.root / "objects").glob("*.json")))
        self.assertFalse(list((self.root / "parquet").rglob("*.parquet")))


if __name__ == "__main__":
    unittest.main()
