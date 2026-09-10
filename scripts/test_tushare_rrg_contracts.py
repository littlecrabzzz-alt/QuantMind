"""Offline contract, queue and fixed-release checks for the original RRG APIs."""

import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_pipeline import Pipeline
from backend.shared.tushare_registry import EXTENDED_CONTRACTS, contract_for
from backend.shared.tushare_rrg_contracts import FIELDS, INPUT_FIELDS, RRG_CONTRACTS
from backend.shared.tushare_store import KEYS, dataset_schema, read_dataset

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_text())
DOCS = {
    "trade_cal": "26",
    "ci_daily": "308",
    "ci_index_member": "373",
    "etf_basic": "385",
    "fund_daily": "127",
    "fund_adj": "199",
    "fund_portfolio": "121",
}


def source_value(api, field):
    values = {
        "ts_code": "600000.SH" if api == "ci_index_member" else "510300.SH",
        "exchange": "SSE",
        "cal_date": "20260904",
        "trade_date": "20260904",
        "ann_date": "20260904",
        "end_date": "20260630",
        "in_date": "20200101",
        "out_date": None,
        "is_open": 1,
        "is_new": "Y",
        "l1_code": "CI005001",
        "symbol": "600000",
        "open": 1.0,
        "close": 1.0,
        "adj_factor": 1.0,
        "mkv": 1.0,
    }
    return values.get(field)


class RRGContracts(unittest.TestCase):
    def setUp(self):
        guard = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_pinned_catalogue_fields_registry_and_reader_keys_match(self):
        entries = {entry["doc_id"]: entry for entry in CATALOG["entries"]}
        self.assertEqual(set(RRG_CONTRACTS), set(DOCS))
        for api, doc_id in DOCS.items():
            entry = entries[doc_id]
            spec = RRG_CONTRACTS[api]
            self.assertEqual(entry["api_names"], [api])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(spec["source_html_sha256"], entry["html_sha256"])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertFalse(spec["row_cap_verified"])
            self.assertEqual(contract_for(api)["group"], "rrg")
            self.assertEqual(KEYS[api], tuple(spec["keys"]))
            self.assertIn(api, EXTENDED_CONTRACTS)

    def test_enqueue_requests_every_reviewed_field_and_preserves_group(self):
        params = {
            "trade_cal": {
                "exchange": "SSE",
                "start_date": "20260904",
                "end_date": "20260904",
            },
            "ci_daily": {"ts_code": "CI005001", "trade_date": "20260904"},
            "ci_index_member": {"l1_code": "CI005001", "is_new": "Y"},
            "etf_basic": {"list_status": "L"},
            "fund_daily": {"trade_date": "20260904"},
            "fund_adj": {"trade_date": "20260904", "offset": 0, "limit": 1000},
            "fund_portfolio": {"ts_code": "510300.SH", "period": "20260630"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(tmp, CATALOG)
            for api in RRG_CONTRACTS:
                key = pipeline.enqueue(api, params[api])
                row = pipeline.db.execute(
                    "SELECT job,group_name FROM jobs WHERE id=?", (key,)
                ).fetchone()
                job = json.loads(row["job"])
                self.assertEqual(set(job["fields"].split(",")), set(FIELDS[api]))
                self.assertEqual(job["required_fields"], FIELDS[api])
                self.assertEqual(row["group_name"], "rrg")
            pipeline.close()

    def test_complete_mock_rows_publish_and_query_without_upstream_fallback(self):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            api = body["api_name"]
            fields = body["fields"].split(",")
            requests.append((api, fields))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[source_value(api, field) for field in fields]],
                    },
                },
            )

        params = {
            "trade_cal": {
                "exchange": "SSE",
                "start_date": "20260904",
                "end_date": "20260904",
            },
            "ci_daily": {"ts_code": "CI005001", "trade_date": "20260904"},
            "ci_index_member": {"l1_code": "CI005001", "is_new": "Y"},
            "etf_basic": {"list_status": "L"},
            "fund_daily": {"trade_date": "20260904"},
            "fund_adj": {"trade_date": "20260904", "offset": 0, "limit": 1000},
            "fund_portfolio": {"ts_code": "510300.SH", "period": "20260630"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(tmp, CATALOG)
            for api in RRG_CONTRACTS:
                pipeline.enqueue(api, params[api])
            pipeline.db.commit()
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = pipeline.run(
                    client,
                    "synthetic-token",
                    {"priority_start": "20200101"},
                    max_requests=len(RRG_CONTRACTS),
                    pause=0,
                )
            self.assertEqual(result["done"], len(RRG_CONTRACTS))
            release = pipeline.publish()
            pipeline.close()
            self.assertEqual({api for api, _ in requests}, set(RRG_CONTRACTS))
            with patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("query attempted network"),
            ):
                for api in RRG_CONTRACTS:
                    table = read_dataset(tmp, release, api)
                    self.assertEqual(table.num_rows, 1)
                    schema = dataset_schema(tmp, release, api)
                    self.assertEqual(schema["keys"], RRG_CONTRACTS[api]["keys"])
                    self.assertEqual(
                        schema["default_date_field"], RRG_CONTRACTS[api]["date_field"]
                    )
                    metadata = json.loads(table.schema.metadata[b"tushare"])
                    self.assertEqual(metadata["upstream_calls"], 0)
                    self.assertFalse(metadata["history_bound_verified"])
                    self.assertEqual(set(metadata["field_gaps"]), set(FIELDS[api]))

    def test_missing_any_reviewed_column_is_a_schema_gap(self):
        api = "fund_daily"
        fields = FIELDS[api][:-1]

        def handler(_request):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[source_value(api, field) for field in fields]],
                    },
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(tmp, CATALOG)
            pipeline.enqueue(api, {"trade_date": "20260904"})
            pipeline.db.commit()
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = pipeline.run(
                    client,
                    "synthetic-token",
                    {"priority_start": "20200101"},
                    max_requests=1,
                    pause=0,
                )
            self.assertEqual(result["quality"], 1)
            pipeline.close()


if __name__ == "__main__":
    unittest.main()
