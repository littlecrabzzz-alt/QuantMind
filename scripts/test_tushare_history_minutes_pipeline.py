"""Offline minute acquisition and second-precision fixed readers; no credentials."""

from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import (
    HISTORY_MINUTES_RUNTIME_CONTRACTS as CONTRACTS,
)
from backend.shared.tushare_history_minutes_contracts import FIELDS, FIELD_METADATA
from backend.shared.tushare_store import read_dataset, dataset_schema
import test_tushare_market_sentiment_pipeline as fixtures

CODES = {
    "stk_mins": "T600001.SH",
    "etf_mins": "1500011.SZ",
    "idx_mins": "CI005001.CI",
    "sw_mins": "801001.SI",
    "ft_mins": "CU2310.SHF",
    "opt_mins": "IO2609-C-4000.CFX",
    "hk_mins": "00013!.HK",
}
CANON = {
    "stk_mins": "SHT600001",
    "etf_mins": "FUND:1500011.SZ",
    "idx_mins": "IDX:CI005001.CI",
    "sw_mins": "SW:801001.SI",
    "ft_mins": "FUT:CU2310.SHF",
    "opt_mins": "OPT:IO2609-C-4000.CFX",
    "hk_mins": "HK00013!",
}


def source(api, when, **updates):
    row = {
        f: "source" if m["type"] == "str" else 1.25
        for f, m in FIELD_METADATA[api].items()
    }
    return {
        **row,
        "ts_code": CODES[api],
        "trade_time": when,
        "supplier_unknown": None,
        "freq": "supplier-extra-spelling",
        **updates,
    }


def parameters(api, freq="1min"):
    return {
        "ts_code": CODES[api],
        "freq": freq,
        "start_date": "2026-09-03 23:59:58",
        "end_date": "2026-09-04 00:00:02",
    }


class MinutesRuntime(unittest.TestCase):
    setUp = fixtures.MarketSentimentRuntime.setUp
    capture = fixtures.MarketSentimentRuntime.capture

    def test_all_seven_source_columns_frequency_revision_identity_and_seconds(self):
        for api in CONTRACTS:
            for freq in ("1min", "5min"):
                self.capture(
                    api,
                    parameters(api, freq),
                    [
                        source(api, "2026-09-03 23:59:59"),
                        source(api, "2026-09-04T00:00:00", close=None),
                    ],
                    epoch=freq,
                )
        fixed = self.p.publish()
        for api in CONTRACTS:
            rows = read_dataset(self.root, fixed, api).to_pylist()
            self.assertEqual(len(rows), 4)
            self.assertEqual({r["ts_code"] for r in rows}, {CANON[api]})
            self.assertEqual({r["source_ts_code"] for r in rows}, {CODES[api]})
            self.assertEqual(
                {json.loads(r["_request_identity"])["freq"] for r in rows},
                {"1min", "5min"},
            )
            self.assertEqual(len({r["_row_identity"] for r in rows}), 4)
            for r in rows:
                self.assertTrue(set(FIELDS[api]).issubset(r))
                self.assertIn("supplier_unknown", r)
                self.assertEqual(r["freq"], "supplier-extra-spelling")
                expected = source(
                    api,
                    r["trade_time"],
                    **({"close": None} if "T" in r["trade_time"] else {}),
                )
                for field, value in expected.items():
                    self.assertEqual(
                        r["source_ts_code" if field == "ts_code" else field], value
                    )
            metadata = dataset_schema(self.root, fixed, api)
            self.assertEqual(metadata["default_date_field"], "trade_time")
            self.assertIn("time_gap", metadata)
            self.assertIn("unit_note", metadata)
            self.assertEqual(metadata["permission_status"], "unprobed")
            exact = read_dataset(
                self.root,
                fixed,
                api,
                start_date="2026-09-04 00:00:00",
                end_date="2026-09-04T00:00:00",
            ).to_pylist()
            self.assertEqual(len(exact), 2)
            self.assertEqual({r["trade_time"] for r in exact}, {"2026-09-04T00:00:00"})
            self.assertEqual(
                read_dataset(
                    self.root, fixed, api, start_date="20260903", end_date="20260903"
                ).num_rows,
                2,
            )
            self.assertEqual(
                read_dataset(
                    self.root, fixed, api, start_date="2026-09-04 00:00:01"
                ).num_rows,
                0,
            )
            self.assertEqual(
                read_dataset(
                    self.root, fixed, api, as_of="1990-01-01T00:00:00Z"
                ).num_rows,
                0,
            )
            for bad in (
                "2026-09-04T00:00:00Z",
                "2026-09-04 00:00:00+08:00",
                "2026-09-04' OR 1=1",
            ):
                with self.assertRaises(ValueError):
                    read_dataset(self.root, fixed, api, start_date=bad)

    def test_missing_frequency_fails_reader_and_source_freq_is_not_overwritten(self):
        api = "opt_mins"
        params = parameters(api)
        params.pop("freq")
        self.capture(
            api, params, [source(api, "2026-09-04T00:00:00", freq="supplier-other")]
        )
        fixed = self.p.publish()
        with self.assertRaisesRegex(ValueError, "identity"):
            read_dataset(self.root, fixed, api)

    def test_source_discovery_isolated_assets_retired_codes_and_real_mapping(self):
        examples = [
            ("stock_basic", "T600001.SH", {}),
            ("etf_basic", "1500011.SZ", {}),
            ("index_basic", "CI005001.CI", {}),
            ("ci_index_member", "600099.SH", {"l1_code": "CI005001.CI"}),
            ("index_classify", None, {"index_code": "801001.SI", "level": "L1"}),
            ("fut_basic", "CU2310.SHF", {}),
            ("fut_basic", "CUL.SHF", {}),
            ("fut_mapping", "CUL.SHF", {"mapping_ts_code": "CU2401.SHF"}),
            ("opt_basic", "IO2609-C-4000.CFX", {}),
            ("hk_basic", "00013!.HK", {}),
        ]
        for n, (api, code, extra) in enumerate(examples):
            record = {"ts_code": code, "list_status": "D", **extra}
            raw = module.json_bytes(
                {"data": {"fields": list(record), "items": [list(record.values())]}}
            )
            digest = module.digest(raw)
            (self.root / "objects").mkdir(exist_ok=True)
            (self.root / "objects" / (digest + ".json")).write_bytes(raw)
            result = {
                "api_name": api,
                "object_sha256": digest,
                "status": "sample_ok",
                "response_format": "json",
            }
            self.p.db.execute(
                "INSERT INTO attempts VALUES(?,?,?)",
                ("discovery" + str(n), 1, json.dumps(result)),
            )
        self.p.db.commit()
        ids = self.p.identifiers()
        for api, spec in CONTRACTS.items():
            expected = {CODES[api]}
            if api == "ft_mins":
                expected.add("CU2401.SHF")
            self.assertEqual(set(ids[spec["dependencies"][0]]), expected)
        self.assertEqual(ids["minute_futures_unmapped"], ["CUL.SHF"])
        self.assertNotIn("1500011.SZ", ids["minute_stocks"])
        self.assertNotIn("IO2609-C-4000.CFX", ids["minute_stocks"])

    def test_saturated_second_ranges_keep_code_frequency_and_terminal_gap(self):
        api = "ft_mins"
        params = parameters(api)
        row, job, result = self.capture(
            api, params, [source(api, "2026-09-04 00:00:00")], more=True
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["method"], "date_bisection")
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE id IN (SELECT child_id FROM partition_children WHERE parent_id=?)",
                (row["id"],),
            )
        ]
        self.assertEqual(len(children), 2)
        for c in children:
            self.assertEqual(c["freq"], "1min")
            self.assertEqual(c["ts_code"], CODES[api])
            self.assertIn(":", c["start_date"])
        job["params"] = {
            **params,
            "start_date": "2026-09-04 00:00:00",
            "end_date": "2026-09-04 00:00:00",
        }
        childkey = self.p.enqueue(api, job["params"])
        childrow = self.p.db.execute(
            "SELECT * FROM jobs WHERE id=?", (childkey,)
        ).fetchone()
        self.assertIsNone(self.p.split_request(childrow, job, result))

    def test_planner_disabled_default_frequency_policy_and_bounded_resume(self):
        ids = {spec["dependencies"][0]: [CODES[api]] for api, spec in CONTRACTS.items()}
        cfg = {
            "enable_history_minutes": True,
            "history_minutes_history_start": "20260901",
            "history_minutes_frequencies": ["1min"],
            "plan_jobs_per_tick": 2,
        }
        with patch.object(self.p, "identifiers", return_value=ids):
            self.assertEqual(self.p.plan_extended({}, date(2026, 9, 9)), {})
            self.p.plan_extended(cfg, date(2026, 9, 9))
            before = [
                dict(r) for r in self.p.db.execute("SELECT * FROM planning_state")
            ]
            self.p.plan_extended(cfg, date(2026, 9, 9))
            after = [dict(r) for r in self.p.db.execute("SELECT * FROM planning_state")]
        for a, b in zip(before, after, strict=True):
            self.assertEqual(a["signature"], b["signature"])
            self.assertGreaterEqual(b["offset"], a["offset"])
        self.assertNotEqual(
            module._planning_inputs("history_minutes", cfg, ids)[0],
            module._planning_inputs(
                "history_minutes", {**cfg, "history_minutes_frequencies": ["5min"]}, ids
            )[0],
        )

    def test_factor_mode_change_does_not_reuse_unfinished_name_cursor(self):
        ids = {
            "factor_library_factors": [
                {"factor_name": "fixture_name", "asset_type": "STK"}
            ],
            "factor_library_stocks": ["T600001.SH"],
        }
        cfg = {
            "enable_factor_library": True,
            "factor_library_apis": ["factor_value"],
            "factor_library_history_start": "20260901",
            "plan_jobs_per_tick": 2,
        }
        with patch.object(self.p, "identifiers", return_value=ids):
            self.p.plan_extended(cfg, date(2026, 9, 9))
            old = dict(
                self.p.db.execute(
                    "SELECT * FROM planning_state WHERE name='history:factor_library'"
                ).fetchone()
            )
            jobs = [dict(r) for r in self.p.db.execute("SELECT * FROM jobs")]
            self.assertFalse(old["done"])
            report = self.p.plan_extended(
                {**cfg, "factor_library_value_mode": "code_only"}, date(2026, 9, 9)
            )
        new = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertNotEqual(old["signature"], new["signature"])
        self.assertEqual(
            report["history:factor_library"]["reset_reason"], "policy_or_legacy_change"
        )
        self.assertEqual(
            json.loads(new["signature"])["identifiers"],
            {"factor_library_stocks": ["T600001.SH"]},
        )
        for oldjob in jobs:
            self.assertEqual(
                dict(
                    self.p.db.execute(
                        "SELECT * FROM jobs WHERE id=?", (oldjob["id"],)
                    ).fetchone()
                ),
                oldjob,
            )
        self.assertTrue(
            any(
                "ts_code" in json.loads(r["job"])["params"]
                for r in self.p.db.execute("SELECT * FROM jobs")
            )
        )

    def test_factor_mode_policy_only_replaces_factor_value_dependency(self):
        ids = {
            "factor_library_factors": [{"factor_name": "old"}],
            "factor_library_stocks": ["600001.SH"],
        }
        cfg = {"factor_library_apis": ["factor_value"]}
        legacy = module._planning_inputs("factor_library", cfg, ids)
        new = module._planning_inputs(
            "factor_library", {**cfg, "factor_library_value_mode": "code_only"}, ids
        )
        self.assertNotEqual(legacy[0], new[0])
        self.assertEqual(new[1], {"factor_library_stocks": ["600001.SH"]})
        self.assertIn("factor_library_factors", legacy[1])
        with patch.dict(
            module.EXTENDED_CONTRACTS,
            {
                "factor_list": {
                    **module.EXTENDED_CONTRACTS["factor_list"],
                    "dependencies": ["factor_library_factors"],
                }
            },
        ):
            both = module._planning_inputs(
                "factor_library",
                {
                    "factor_library_apis": ["factor_list", "factor_value"],
                    "factor_library_value_mode": "code_only",
                },
                ids,
            )
        self.assertEqual(set(both[1]), set(ids))


if __name__ == "__main__":
    unittest.main()
