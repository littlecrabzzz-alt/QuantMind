#!/usr/bin/env python3
"""Offline fixed-release query/export checks against generated Parquet files."""

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_store as store  # noqa: E402


def release(root, datasets, *, complete=True, observations=None):
    files, partitions = {}, []
    for name, observation in (observations or {}).items():
        payload = json.dumps(observation, sort_keys=True).encode()
        (root / "observations").mkdir(exist_ok=True)
        path = "observations/" + name
        (root / path).write_bytes(payload)
        files[path] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    (root / "parquet").mkdir(exist_ok=True)
    for api, rows in datasets:
        stream = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows), stream)
        payload = stream.getvalue().to_pybytes()
        sha = hashlib.sha256(payload).hexdigest()
        name = f"parquet/{sha}.parquet"
        (root / name).write_bytes(payload)
        files[name] = {"sha256": sha, "bytes": len(payload)}
        partitions.append({"api_name": api, "path": name, **files[name]})
    manifest = {
        "files": files,
        "datasets": partitions,
        "history_complete": False,
        "coverage_by_api": [],
    }
    if complete is not None:
        manifest["historical_versions_complete"] = complete
    payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    name = "data-" + hashlib.sha256(payload).hexdigest()
    directory = root / "releases" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_bytes(payload)
    return name


def row(**values):
    return {"_fetched_at": "2026-09-09T08:00:00+00:00", "_observation": "one", **values}


class FixedStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "store"
        self.root.mkdir()
        self.output = Path(self.tmp.name) / "query.jsonl"
        self.network = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        )
        self.dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        )
        self.network.start()
        self.dns.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.dns.stop)

    def test_versions_as_of_and_filters_after_latest(self):
        old = row(
            ts_code="SH600036",
            trade_date="20260908",
            adj_factor=1.0,
            name="old matching",
            source_ts_code="600036.SH",
            _fetched_at="2026-09-09T08:00:00+08:00",
        )
        new = row(
            ts_code="SH600036",
            trade_date="20260908",
            adj_factor=2.0,
            name="new",
            source_ts_code="600036.SH",
            _fetched_at="2026-09-09T01:00:00+00:00",
            _observation="two",
        )
        pinned = release(self.root, [("fund_adj", [old]), ("fund_adj", [new])])
        now = store.read_dataset(self.root, pinned, "fund_adj")
        self.assertEqual(now.to_pylist()[0]["adj_factor"], 2)
        self.assertEqual(now.to_pylist()[0]["source_ts_code"], "600036.SH")
        past = store.read_dataset(
            self.root,
            pinned,
            "fund_adj",
            as_of="2026-09-09T00:30:00Z",
            fields=["ts_code", "adj_factor"],
        )
        self.assertEqual(past.to_pylist(), [{"ts_code": "SH600036", "adj_factor": 1}])
        self.assertEqual(
            store.read_dataset(
                self.root, pinned, "fund_adj", keyword="matching"
            ).num_rows,
            0,
        )
        before = store.read_dataset(
            self.root, pinned, "fund_adj", as_of="2026-09-08T23:00:00Z"
        )
        self.assertEqual(before.num_rows, 0)
        metadata = json.loads(past.schema.metadata[b"tushare"])
        self.assertTrue(metadata["historical_versions_complete"])
        self.assertIn("not historical", metadata["as_of_semantics"])
        self.assertEqual(metadata["upstream_calls"], 0)

    def test_text_versions_keyword_source_and_schema_evolution(self):
        base = row(
            _source="cls",
            datetime="2026-09-08 12:00:00",
            title="Same title",
            content="原始内容",
            channels=None,
            source_ts_code="600036.SH",
            _row_identity="old",
        )
        changed = {
            **base,
            "content": "修订内容 100%",
            "_row_identity": "revised",
            "_observation": "two",
            "extra_supplier_field": "retained",
        }
        pinned = release(self.root, [("news", [base]), ("news", [changed])])
        all_rows = store.read_dataset(self.root, pinned, "news").to_pylist()
        self.assertEqual(len(all_rows), 2)
        result = store.read_dataset(
            self.root,
            pinned,
            "news",
            keyword="100%",
            keyword_fields=["content"],
            start_date="20260908",
            end_date="2026-09-08",
            fields=["content", "extra_supplier_field"],
        )
        self.assertEqual(
            result.to_pylist(),
            [{"content": "修订内容 100%", "extra_supplier_field": "retained"}],
        )
        self.assertEqual(
            store.read_dataset(
                self.root, pinned, "news", keyword="% OR 1=1 --"
            ).num_rows,
            0,
        )
        schema = store.dataset_schema(self.root, pinned, "news")
        self.assertIn("extra_supplier_field", [f["name"] for f in schema["fields"]])
        self.assertIn("_row_identity", schema["keys"])
        self.assertEqual(schema["default_date_field"], "datetime")

    def test_all_contracts_and_financial_aliases(self):
        fixtures = []
        observations = {}
        identity_params = {
            "tdx_index": {"trade_date": "20260904", "idx_type": "地区板块"},
            "kpl_list": {"trade_date": "20260904", "tag": "竞价"},
            "ths_hot": {"trade_date": "20260904", "market": "期货", "is_new": "N"},
            "dc_hot": {"trade_date": "20260904", "market": "美股市场", "hot_type": "飙升榜", "is_new": "N"},
            "stk_nineturn": {"trade_date": "2026-09-04 00:00:00", "freq": "daily"},
            "dc_daily": {"trade_date": "20260904", "idx_type": "概念板块"},
            "dc_index": {"trade_date": "20260904", "idx_type": "行业板块"},
            "limit_list_ths": {"trade_date": "20260904", "limit_type": "涨停池"},
            "limit_list_d": {"trade_date": "20260904", "limit_type": "D"},
            "fina_mainbz": {"ts_code": "600036.SH", "type": "P"},
            "stock_hsgt": {"trade_date": "20260904", "type": "HK_SZ"},
            "hsgt_top10": {"trade_date": "20260904", "market_type": "1"},
            "moneyflow_ind_dc": {"trade_date": "20260904", "content_type": "行业"},
        }
        for api, keys in store.KEYS.items():
            if api not in store.CONTRACTS and api not in (
                "trade_cal",
                "ci_daily",
                "ci_index_member",
                "etf_basic",
                "fund_daily",
                "fund_adj",
                "fund_portfolio",
            ):
                continue
            values = dict.fromkeys(keys, "key")
            if store.CONTRACTS.get(api, {}).get("preserve_distinct_rows"):
                values["_row_identity"] = "fixture-source-row"
            if store.CONTRACTS.get(api, {}).get("request_identity_fields"):
                observation = {
                    "request": {"api_name": api, "params": identity_params[api]}
                }
                # An immutable observation belongs to one request, not to every
                # dataset in this release. Reusing a name overwrites API evidence.
                name = (
                    hashlib.sha256(
                        json.dumps(observation, sort_keys=True).encode()
                    ).hexdigest()
                    + ".json"
                )
                values.update(_row_identity="b" * 64, _observation=name)
                observations[name] = observation
            fixtures.append((api, [row(**values)]))
        pinned = release(self.root, fixtures, observations=observations)
        for api, _ in fixtures:
            with self.subTest(api=api):
                table = store.read_dataset(self.root, pinned, api)
                self.assertEqual(table.num_rows, 1)
                if api in identity_params:
                    identity_fields = store.CONTRACTS[api]["request_identity_fields"]
                    self.assertEqual(
                        json.loads(table.to_pylist()[0]["_request_identity"]),
                        {
                            field: identity_params[api][field]
                            for field in identity_fields
                        },
                    )
                    metadata = json.loads(table.schema.metadata[b"tushare"])
                    self.assertEqual(
                        metadata["request_identity_status"],
                        "verified_from_immutable_observations",
                    )
        self.assertEqual(store.read_dataset(self.root, pinned, "income").num_rows, 1)
        self.assertEqual(len(observations), len(identity_params))
        self.assertTrue(
            {
                "stock_hsgt",
                "hsgt_top10",
                "moneyflow_cnt_ths",
                "moneyflow_ind_ths",
                "moneyflow_ind_dc",
            }
            <= {api for api, _ in fixtures}
        )
        self.assertTrue(
            {
                "hk_income",
                "hk_balancesheet",
                "hk_cashflow",
                "hk_fina_indicator",
                "us_income",
                "us_balancesheet",
                "us_cashflow",
                "us_fina_indicator",
            }
            <= {api for api, _ in fixtures}
        )
        self.assertEqual(len(fixtures), 179)

    def test_dates_codes_and_macro_periods(self):
        pinned = release(
            self.root,
            [
                (
                    "daily",
                    [
                        row(ts_code="SH600036", trade_date="20260908", close=3),
                        row(ts_code="SZ000001", trade_date="20260907", close=4),
                    ],
                ),
                (
                    "cn_cpi",
                    [row(month="202602", value=1), row(month="202603", value=2)],
                ),
                (
                    "cn_gdp",
                    [row(quarter="2026Q1", value=1), row(quarter="2026Q2", value=2)],
                ),
            ],
        )
        self.assertEqual(
            store.read_dataset(
                self.root,
                pinned,
                "daily",
                codes=["SH600036"],
                start_date=date(2026, 9, 8),
                limit=1,
            ).num_rows,
            1,
        )
        self.assertEqual(
            store.read_dataset(self.root, pinned, "daily", codes=[]).num_rows, 0
        )
        self.assertEqual(
            store.read_dataset(
                self.root, pinned, "cn_cpi", start_date="20260301"
            ).to_pylist()[0]["value"],
            2,
        )
        self.assertEqual(
            store.read_dataset(
                self.root, pinned, "cn_gdp", start_date="20260401"
            ).to_pylist()[0]["value"],
            2,
        )
        for options in (
            {"fields": ["ts_code; DROP TABLE stored"]},
            {"date_field": "missing", "start_date": "20260908"},
            {"codes": ["600036.SH"]},
            {"as_of": "2026-09-09"},
            {"start_date": "20260230"},
            {"start_date": "20260909", "end_date": "20260908"},
            {"limit": -1},
            {"keyword": "x", "keyword_fields": ["absent"]},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                store.read_dataset(self.root, pinned, "daily", **options)

    def test_streaming_export_and_failure_preserves_previous_output(self):
        pinned = release(
            self.root,
            [
                (
                    "stock_basic",
                    [
                        row(
                            ts_code="SH600036",
                            name="招商银行",
                            amount=Decimal("1.000000000000000001"),
                            listed=date(2026, 9, 8),
                            source_ts_code="600036.SH",
                        )
                    ],
                )
            ],
        )
        result = store.export_jsonl(
            self.root,
            pinned,
            "stock_basic",
            self.output,
            fields=["name", "amount", "listed", "source_ts_code"],
        )
        self.assertEqual(result["rows"], 1)
        self.assertEqual(
            json.loads(self.output.read_text())["amount"], "1.000000000000000001"
        )
        self.assertEqual(
            result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest()
        )
        before = self.output.read_bytes()
        bad = release(
            self.root, [("stock_basic", [row(ts_code="SH600036", value=float("nan"))])]
        )
        with self.assertRaises(ValueError):
            store.export_jsonl(self.root, bad, "stock_basic", self.output)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(list(self.output.parent.glob(".tushare-export-*")), [])
        with self.assertRaises(ValueError):
            store.export_jsonl(
                self.root, pinned, "stock_basic", self.root / "CURRENT.json"
            )

    def test_legacy_and_corrupt_missing_or_symlink_partitions(self):
        pinned = release(
            self.root,
            [
                (
                    "fund_adj",
                    [row(ts_code="SH510300", trade_date="20260908", adj_factor=1)],
                )
            ],
            complete=None,
        )
        table = store.read_dataset(
            self.root, pinned, "fund_adj", as_of="2026-09-09T09:00:00Z"
        )
        self.assertFalse(
            json.loads(table.schema.metadata[b"tushare"])[
                "historical_versions_complete"
            ]
        )
        with self.assertRaises(ValueError):
            store.read_dataset(self.root, pinned, "ci_daily")
        path = next((self.root / "parquet").iterdir())
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, "checksum"):
            store.read_dataset(self.root, pinned, "fund_adj")
        path.write_bytes(original)
        moved = self.root / "outside"
        path.replace(moved)
        path.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, "path"):
            store.read_dataset(self.root, pinned, "fund_adj")


if __name__ == "__main__":
    unittest.main()
