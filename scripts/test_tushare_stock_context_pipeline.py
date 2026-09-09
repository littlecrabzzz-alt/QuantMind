"""Stock context runtime checks using only temporary storage and mock HTTP."""

from datetime import date
import json
from pathlib import Path
import sys
import unittest

import httpx
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_stock_context_contracts import FIELDS, FIELD_METADATA
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, dataset_schema
import test_tushare_technical_extra_pipeline as fixtures


def source(api, **updates):
    row = {
        f: "source-label" if m["type"] == "str" else -1.25
        for f, m in FIELD_METADATA[api].items()
    }
    row.update(ts_code="T600001.SH")
    for f, v in {
        "trade_date": "20260904",
        "ann_date": "20260904",
        "end_date": "20251231",
        "begin_date": "20240101",
        "birthday": "1970-01",
        "resume": None,
        "hk_code": "00013!.HK",
        "freq": "daily",
    }.items():
        if f in row:
            row[f] = v
    if api == "stk_nineturn":
        row["trade_date"] = "2026-09-04 00:00:00"
    row["supplier_extra"] = "retained"
    row.update(updates)
    return row


def params(api, code=None):
    p = (
        {"ts_code": code or "T600001.SH"}
        if api == "stk_rewards"
        else {"ann_date": "20260904"}
        if api == "stk_managers"
        else {"trade_date": "2026-09-04 00:00:00", "freq": "daily"}
        if api == "stk_nineturn"
        else {"trade_date": "20260904"}
    )
    if code:
        p["ts_code"] = code
    return p


class StockContextRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    discovery = fixtures.TechnicalExtraRuntime.discovery
    capture = fixtures.TechnicalExtraRuntime.capture

    def test_full_fields_raw_identity_fixed_release_dates_and_hk_pairs(self):
        old = self.p.publish()
        expected = {}
        for api in FIELDS:
            rows = [source(api), source(api, supplier_extra="revision")]
            if api == "stk_ah_comparison":
                rows.append(source(api, hk_code="00013.HK"))
            expected[api] = {module.digest(module.json_bytes(r)): r for r in rows}
            for epoch in ("first", "repeat"):
                self.assertEqual(
                    self.capture(api, params(api), rows, epoch=epoch)[2]["status"],
                    "sample_ok",
                )
        pinned = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, pinned, api)
            self.assertEqual(table.num_rows, len(expected[api]))
            for row in table.to_pylist():
                raw = expected[api][row.get("_raw_row_identity", row["_row_identity"])]
                self.assertEqual(row["ts_code"], "SHT600001")
                for f, value in raw.items():
                    self.assertEqual(
                        row["source_" + f if f in ("ts_code", "hk_code") else f], value
                    )
            self.assertEqual(
                read_dataset(self.root, pinned, api, start_date="20260905").num_rows, 0
            )
            self.assertEqual(
                read_dataset(
                    self.root,
                    pinned,
                    api,
                    codes=["SHT600001"],
                    start_date="20260904",
                    end_date="20260904",
                ).num_rows,
                table.num_rows,
            )
            self.assertEqual(
                dataset_schema(self.root, pinned, api)["default_date_field"],
                contract_for(api)["date_field"],
            )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            self.assertEqual(metadata["permission_status"], "unprobed")
            self.assertEqual(set(metadata["field_gaps"]), set(FIELDS[api]))
            self.assertIn("pit_gap", metadata)
            self.assertEqual(metadata["deduplication_mode"], "distinct_supplier_rows")
            with self.assertRaisesRegex(ValueError, "Dataset unavailable"):
                read_dataset(self.root, old, api)
        self.assertEqual(
            {
                r["hk_code"]
                for r in read_dataset(
                    self.root, pinned, "stk_ah_comparison"
                ).to_pylist()
            },
            {"HK00013!", "HK00013"},
        )
        self.assertEqual(
            read_dataset(
                self.root,
                pinned,
                "stk_ah_comparison",
                code_field="hk_code",
                codes=["HK00013!"],
            ).num_rows,
            2,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                pinned,
                "stk_rewards",
                date_field="end_date",
                end_date="20251231",
            ).num_rows,
            2,
        )
        self.assertEqual(
            read_dataset(
                self.root, pinned, "stk_rewards", end_date="20251231"
            ).num_rows,
            0,
        )

    def test_default_disabled_planning_idempotence_and_discovery(self):
        self.p.plan_extended({}, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        for api, code in [
            ("stock_basic", "T600018.SH"),
            ("bak_basic", "600002.SH"),
            ("daily", "600003.SH"),
            ("top_list", "600004.SH"),
            ("stk_rewards", "600005.SH"),
            ("etf_basic", "510300.SH"),
            ("ths_index", "600099.SH"),
        ]:
            self.discovery(api, [{"ts_code": code}])
        ids = self.p.identifiers()
        expected = {"T600018.SH", "600002.SH", "600003.SH", "600004.SH", "600005.SH"}
        self.assertEqual(set(ids["stock_context_stocks"]), expected)
        self.assertEqual(ids["stocks"], ["T600018.SH"])
        cfg = {
            "enable_stock_context": True,
            "stock_context_history_start": "20260901",
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(cfg, date(2026, 9, 9))
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(cfg, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], count
        )
        jobs = [
            json.loads(r[0])
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE group_name='stock_context'"
            )
        ]
        rewards = [j for j in jobs if j["api_name"] == "stk_rewards"]
        self.assertEqual({j["params"]["ts_code"] for j in rewards}, expected)
        self.assertTrue(all(set(j["params"]) == {"ts_code"} for j in rewards))
        self.assertEqual({j["api_name"] for j in jobs}, set(FIELDS))
        self.assertEqual(
            set(module._planning_inputs("stock_context", cfg, ids)[1]),
            {"stock_context_stocks", "stock_context_reward_periods"},
        )
        self.assertIn(
            "backend/shared/tushare_stock_context_contracts.py",
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )

    def test_hidden_resume_required_and_unknown_scope_retained(self):
        result = self.capture(
            "stk_managers",
            params("stk_managers"),
            [source("stk_managers")],
            omit=["resume"],
        )[2]
        self.assertEqual(result["status"], "schema_gap")
        self.p.plan_extended(
            {"enable_stock_context": True, "plan_jobs_per_tick": 1000}, date(2026, 9, 9)
        )
        for api in ("stk_auction_o", "stk_auction_c", "stk_managers", "stk_premarket"):
            self.assertIsNotNone(
                self.p.db.execute(
                    "SELECT 1 FROM capability WHERE scope=?",
                    (
                        f"planning:stock_context:{api}:unknown_history_start_requires_scope",
                    ),
                ).fetchone()
            )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT 1 FROM capability WHERE scope='planning:stock_context:stk_rewards:discovery'"
            ).fetchone()
        )

    def test_validation_blocked_does_not_block_other_family(self):
        ids = self.p.identifiers()
        ids["stock_context_stocks"] = ["bad;code"]
        cfg = {
            "enable_stock_context": True,
            "enable_technical_extra": True,
            "technical_extra_apis": ["stk_factor"],
            "plan_jobs_per_tick": 100,
        }
        with patch.object(self.p, "identifiers", return_value=ids):
            stats = self.p.plan_extended(cfg, date(2026, 9, 9))
        self.assertNotIn("recent:stock_context", stats)
        self.assertIn("recent:technical_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:stock_context'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertTrue(cfg["enable_stock_context"])

    def test_saturation_uses_historical_source_codes_and_no_invented_second_dimension(
        self,
    ):
        self.discovery("stock_basic", [{"ts_code": "T600018.SH"}])
        for api in FIELDS:
            row, job, result = self.capture(api, params(api), [source(api)], more=True)
            split = self.p.split_request(row, job, result)
            if api == "stk_rewards":
                self.assertIsNone(split)
            else:
                self.assertEqual(split["method"], "identifier_fanout")
                self.assertFalse(split["universe_complete"])
                children = [
                    json.loads(r[0])
                    for r in self.p.db.execute(
                        "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                        (row["id"],),
                    )
                ]
                self.assertEqual(
                    {j["params"]["ts_code"] for j in children},
                    {"T600018.SH", "T600001.SH"},
                )
                self.assertTrue(
                    all(j["params"].items() >= params(api).items() for j in children)
                )
            if api != "stk_rewards":
                row, job, result = self.capture(
                    api,
                    params(api, "T600001.SH"),
                    [source(api)],
                    more=True,
                    epoch="terminal",
                )
                self.assertIsNone(self.p.split_request(row, job, result))
        self.assertTrue(all(not contract_for(api).get("pagination") for api in FIELDS))

    def test_terminal_saturation_stays_blocked_with_saved_response(self):
        keys = [
            self.p.enqueue(api, params(api, "T600001.SH"), 1, "terminal")
            for api in FIELDS
        ]

        def respond(request):
            sent = json.loads(request.content)
            api = sent["api_name"]
            self.assertEqual(sent["params"], params(api, "T600001.SH"))
            self.assertEqual(set(sent["fields"].split(",")), set(FIELDS[api]))
            row = source(api)
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
            report = self.p.run(
                client, "fixture", {}, max_requests=7, max_seconds=10, pause=0
            )
        self.assertEqual(report["requests"], 7)
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


if __name__ == "__main__":
    unittest.main()
