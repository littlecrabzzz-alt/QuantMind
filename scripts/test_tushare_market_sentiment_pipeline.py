"""Offline market-sentiment acquisition, identity and fixed-reader checks."""

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
from backend.shared.tushare_market_sentiment_contracts import (
    FIELDS,
    FIELD_METADATA,
    VARIANTS,
)
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, dataset_schema
import test_tushare_technical_extra_pipeline as fixtures


def source(api, **updates):
    row = {
        f: "source-label" if m["type"] == "str" else -1.25
        for f, m in FIELD_METADATA[api].items()
    }
    row.update(ts_code="600001.SH", trade_date="20260904")
    if api.startswith("tdx_"):
        row["ts_code"] = "880001.TDX"
    if api == "kpl_concept_cons":
        row["ts_code"] = "000001.KP"
    if "con_code" in row:
        row["con_code"] = "T600001.SH"
    if "rank_time" in row:
        row["rank_time"] = "2026-09-04 22:30:00"
    row["supplier_extra"] = None
    row.update(updates)
    return row


def params(api, **updates):
    return {"trade_date": "20260904", **VARIANTS[api][0], **updates}


class MarketSentimentRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    discovery = fixtures.TechnicalExtraRuntime.discovery
    capture = fixtures.TechnicalExtraRuntime.capture

    def test_all_101_fields_immutable_raw_distinct_rows_and_fixed_read(self):
        old = self.p.publish()
        expected = {}
        for api in FIELDS:
            rows = [source(api), source(api, supplier_extra="revision")]
            expected[api] = {module.digest(module.json_bytes(r)): r for r in rows}
            for epoch in ("one", "repeat"):
                self.assertEqual(
                    self.capture(api, params(api), rows, epoch=epoch)[2]["status"],
                    "sample_ok",
                )
        fixed = self.p.publish()
        self.assertEqual(sum(map(len, FIELDS.values())), 101)
        for api in FIELDS:
            table = read_dataset(self.root, fixed, api)
            self.assertEqual(table.num_rows, 2)
            for row in table.to_pylist():
                raw = expected[api][row.get("_raw_row_identity", row["_row_identity"])]
                for f, value in raw.items():
                    self.assertEqual(
                        row["source_" + f if f in ("ts_code", "con_code") else f], value
                    )
            self.assertEqual(
                read_dataset(self.root, fixed, api, start_date="20260905").num_rows, 0
            )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["permission_status"], "unprobed")
            self.assertEqual(set(metadata["field_metadata"]), set(FIELDS[api]))
            self.assertEqual(metadata["deduplication_mode"], "distinct_supplier_rows")
            self.assertIn("saturation_gap", metadata)
            self.assertEqual(
                dataset_schema(self.root, fixed, api)["default_date_field"],
                "trade_date",
            )
            with self.assertRaisesRegex(ValueError, "Dataset unavailable"):
                read_dataset(self.root, old, api)
        selected = read_dataset(
            self.root, fixed, "tdx_daily", fields=["3day", "1year", "source_ts_code"]
        )
        self.assertEqual(selected.column("3day").to_pylist(), [-1.25, -1.25])
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                "tdx_member",
                code_field="con_code",
                codes=["SHT600001"],
            ).num_rows,
            2,
        )

    def test_46_daily_variants_keep_immutable_identity_and_market_namespaces(self):
        for api in FIELDS:
            for variant in VARIANTS[api]:
                self.capture(api, params(api, **variant), [source(api)])
        fixed = self.p.publish()
        self.assertEqual(sum(len(v) for v in VARIANTS.values()), 46)
        for api in FIELDS:
            rows = read_dataset(self.root, fixed, api).to_pylist()
            self.assertEqual(len(rows), len(VARIANTS[api]))
            if contract_for(api)["request_identity_fields"]:
                self.assertEqual(
                    {r["_request_identity"] for r in rows},
                    {module.json_bytes(v).decode() for v in VARIANTS[api]},
                )
        hot = read_dataset(self.root, fixed, "ths_hot").to_pylist()
        expected = {
            "热股": "SH600001",
            "ETF": "FUND:600001.SH",
            "热基": "FUND:600001.SH",
            "可转债": "CB:600001.SH",
            "期货": "FUT:600001.SH",
            "行业板块": "THS:I:600001.SH",
            "概念板块": "THS:N:600001.SH",
            "港股": "HK:600001.SH",
            "美股": "US600001.SH",
        }
        for row in hot:
            self.assertEqual(
                row["ts_code"], expected[json.loads(row["_request_identity"])["market"]]
            )
        self.assertEqual(
            {
                r["ts_code"]
                for r in read_dataset(self.root, fixed, "tdx_index").to_pylist()
            },
            {"TDX:880001.TDX"},
        )

    def test_historical_hk_and_unknown_market_do_not_collapse(self):
        for market, code, _canonical in [
            ("港股", "00013!.HK", "HK00013!"),
            ("港股", "00013.HK", "HK00013"),
            ("热股", "T600001.SH", "SHT600001"),
            ("美股", "BRK.B", "USBRK.B"),
        ]:
            self.capture(
                "ths_hot",
                params("ths_hot", market=market),
                [source("ths_hot", ts_code=code)],
                epoch=code,
            )
        self.capture(
            "ths_hot",
            {"trade_date": "20260904", "is_new": "Y"},
            [source("ths_hot")],
            epoch="missing",
        )
        # Missing market remains explicitly incomplete and cannot be read as a valid identity.
        fixed = self.p.publish()
        with self.assertRaisesRegex(ValueError, "identity"):
            read_dataset(self.root, fixed, "ths_hot")
        import pyarrow.parquet as pq

        rows = [
            r
            for file in (self.root / "parquet").rglob("*.parquet")
            for r in pq.read_table(file).to_pylist()
        ]
        self.assertEqual(
            {r["ts_code"] for r in rows},
            {
                "HK00013!",
                "HK00013",
                "SHT600001",
                "USBRK.B",
                "UNVERIFIED_MARKET:600001.SH",
            },
        )

    def test_default_disabled_idempotence_discovery_and_scope_gaps(self):
        self.p.plan_extended({}, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        for api, rows in [
            ("stock_basic", [{"ts_code": "T600002.SH"}]),
            ("bak_basic", [{"ts_code": "600003.SH"}]),
            ("tdx_member", [{"ts_code": "880001.TDX", "con_code": "T600004.SH"}]),
            ("kpl_concept_cons", [{"ts_code": "1.KP", "con_code": "600005.SH"}]),
            ("etf_basic", [{"ts_code": "510300.SH"}]),
            ("ths_hot", [{"ts_code": "600099.SH"}]),
        ]:
            self.discovery(api, rows)
        ids = self.p.identifiers()
        self.assertEqual(
            set(ids["market_sentiment_stocks"]),
            {"T600002.SH", "600003.SH", "T600004.SH", "600005.SH"},
        )
        self.assertEqual(ids["tdx_indices"], ["880001.TDX"])
        self.assertEqual(ids["kpl_concepts"], ["1.KP"])
        cfg = {
            "enable_market_sentiment": True,
            "market_sentiment_history_start": "20260904",
            "recent_days": 1,
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(cfg, date(2026, 9, 4))
        count = self.p.db.execute(
            "SELECT count(*) FROM jobs WHERE group_name='market_sentiment'"
        ).fetchone()[0]
        self.p.plan_extended(cfg, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM jobs WHERE group_name='market_sentiment'"
            ).fetchone()[0],
            count,
        )
        self.assertEqual(count, 46)
        self.assertEqual(module._planning_inputs("market_sentiment", cfg, ids)[1], {})
        self.p.plan_extended(
            {"enable_market_sentiment": True, "plan_jobs_per_tick": 1000},
            date(2026, 9, 4),
        )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT 1 FROM capability WHERE scope='planning:market_sentiment:tdx_daily:unknown_history_start_requires_scope'"
            ).fetchone()
        )
        self.assertIn(
            "backend/shared/tushare_market_sentiment_contracts.py",
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )

    def test_invalid_family_does_not_block_other_and_missing_digit_field_is_gap(self):
        stats = self.p.plan_extended(
            {
                "enable_market_sentiment": True,
                "market_sentiment_apis": ["invalid"],
                "enable_technical_extra": True,
                "technical_extra_apis": ["stk_factor"],
                "plan_jobs_per_tick": 100,
            },
            date(2026, 9, 4),
        )
        self.assertNotIn("recent:market_sentiment", stats)
        self.assertIn("recent:technical_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:market_sentiment'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertEqual(
            self.capture(
                "tdx_daily", params("tdx_daily"), [source("tdx_daily")], omit=["3day"]
            )[2]["status"],
            "schema_gap",
        )

    def test_saturation_fanout_preserves_request_and_hot_terminal_blocks(self):
        self.discovery("stock_basic", [{"ts_code": "T600018.SH"}])
        self.discovery("tdx_index", [{"ts_code": "880002.TDX"}])
        for api in FIELDS:
            row, job, result = self.capture(api, params(api), [source(api)], more=True)
            split = self.p.split_request(row, job, result)
            if api in ("ths_hot", "dc_hot"):
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
                self.assertTrue(
                    all(j["params"].items() >= params(api).items() for j in children)
                )
            row, job, result = self.capture(
                api,
                params(api, ts_code=source(api)["ts_code"]),
                [source(api)],
                more=True,
                epoch="terminal",
            )
            self.assertIsNone(self.p.split_request(row, job, result))
        api = "ths_hot"
        key = self.p.enqueue(api, params(api, market="期货"), 1, "run")

        def respond(request):
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

        # Keep this run bounded to its dedicated pending job; split children are untouched.
        with (
            patch.object(
                self.p,
                "next_job",
                return_value=self.p.db.execute(
                    "SELECT * FROM jobs WHERE id=?", (key,)
                ).fetchone(),
            ),
            httpx.Client(
                transport=httpx.MockTransport(respond), trust_env=False
            ) as client,
        ):
            self.assertEqual(
                self.p.run(
                    client, "fixture", {}, max_requests=1, max_seconds=10, pause=0
                )["requests"],
                1,
            )
        self.assertEqual(
            self.p.db.execute("SELECT state FROM jobs WHERE id=?", (key,)).fetchone()[
                0
            ],
            "blocked",
        )


if __name__ == "__main__":
    unittest.main()
