"""Offline historical lending scope, identity, nullable fields and cap boundaries."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_securities_lending_history_contracts import (  # noqa: E402
    SECURITIES_LENDING_HISTORY_CONTRACTS as CONTRACTS,
    FIELDS,
    FIELD_METADATA,
    INPUT_FIELDS,
    SOURCE_HTML_SHA256,
    iter_securities_lending_history_jobs as jobs,
    securities_lending_history_identifiers as identifiers,
    securities_lending_history_prerequisites as prerequisites,
)
from backend.shared.tushare_intake import capture_sample  # noqa: E402
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402

CFG = {"enable_securities_lending_history": True, "history_start": "20240227"}


class LendingHistory(unittest.TestCase):
    def test_full_reviewed_schema_units_and_historical_uncertainty(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        self.assertEqual(set(CONTRACTS), {"slb_sec", "slb_sec_detail", "slb_len_mm"})
        self.assertEqual(sum(map(len, FIELDS.values())), 20)
        for api, spec in CONTRACTS.items():
            entry = next(x for x in catalog if api in x["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(SOURCE_HTML_SHA256[api], entry["html_sha256"])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(set(FIELD_METADATA[api]), set(FIELDS[api]))
            self.assertTrue(
                all(x["default"] == "Y" for x in FIELD_METADATA[api].values())
            )
            self.assertEqual(spec["hidden_fields"], [])
            self.assertFalse(spec["default_enabled"])
            self.assertIsNone(spec["history_start"])
            self.assertIsNone(spec["stop_date"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertEqual(spec["requests_per_minute"], 30)
            self.assertEqual(spec["documented_requests_per_minute"]["5000_points"], 500)
            self.assertFalse(spec["row_cap_verified"])
            self.assertEqual(spec["row_cap"], 5000)
            self.assertEqual(spec["positive_fields"], [])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertNotIn("_row_identity", spec["extra_fields"])
            self.assertNotIn("pagination", spec)
        self.assertEqual(
            CONTRACTS["slb_sec_detail"]["keys"],
            ["trade_date", "ts_code", "tenor", "fee_rate"],
        )
        self.assertEqual(FIELD_METADATA["slb_sec_detail"]["tenor"]["type"], "str")
        self.assertIn("万元", FIELD_METADATA["slb_sec"]["end_bal"]["description"])
        self.assertIn("万股", FIELD_METADATA["slb_sec"]["lent_qnt"]["description"])

    def test_default_off_empty_selection_and_invalid_scopes(self):
        self.assertEqual(list(jobs({}, date(2026, 9, 9))), [])
        self.assertEqual(prerequisites(), [])
        self.assertEqual(
            list(
                jobs({**CFG, "securities_lending_history_apis": []}, date(2024, 3, 1))
            ),
            [],
        )
        for extra in (
            {"enable_securities_lending_history": "yes"},
            {"securities_lending_history_apis": ["slb_len"]},
            {"securities_lending_history_start": []},
            {"securities_lending_history_start": {"slb_len": "20200101"}},
            {"history_start": "20240230"},
            {"history_start": ""},
            {"history_start": "20260101"},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                list(jobs({**CFG, **extra}, date(2024, 3, 1)))

    def test_leap_day_weekends_recent_then_fair_history_without_duplicates(self):
        today = date(2024, 3, 12)
        config = {**CFG, "planning_epoch": "fixed"}
        before = json.dumps(config, sort_keys=True)
        with (
            patch("socket.socket.connect", side_effect=AssertionError("offline")),
            patch("socket.getaddrinfo", side_effect=AssertionError("offline")),
        ):
            planned = list(jobs(config, today))
        self.assertEqual(len(planned), 15 * 3)
        self.assertEqual(planned, list(jobs(config, datetime(2024, 3, 12, 15))))
        self.assertEqual(json.dumps(config, sort_keys=True), before)
        for api in FIELDS:
            own = [j for j in planned if j["api_name"] == api]
            self.assertEqual(
                {j["params"]["trade_date"] for j in own},
                {
                    (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d")
                    for i in range(15)
                },
            )
        self.assertEqual([j["api_name"] for j in planned[21:24]], list(FIELDS))
        self.assertTrue(
            all(j["priority"] == 20 and j["epoch"] == "fixed" for j in planned[:21])
        )
        self.assertTrue(
            all(j["priority"] == 40 and j["epoch"] == "history" for j in planned[21:])
        )
        identity = {
            (j["api_name"], json.dumps(j["params"], sort_keys=True)) for j in planned
        }
        self.assertEqual(len(identity), len(planned))
        self.assertTrue(all(set(j["params"]) == {"trade_date"} for j in planned))

    def test_1990_operational_start_is_lazy_and_not_history_proof(self):
        cfg = {"enable_securities_lending_history": True}
        prefix = list(islice(jobs(cfg, date(2026, 9, 9)), 24))
        self.assertEqual(prefix[21]["params"], {"trade_date": "19900101"})
        self.assertEqual(prefix[23]["params"], {"trade_date": "19900101"})
        gaps = prerequisites(config=cfg)
        self.assertEqual(
            {
                g["api_name"]
                for g in gaps
                if g["reason"]
                == "configured_scope_does_not_prove_earlier_history_absent"
            },
            set(FIELDS),
        )
        self.assertTrue(
            all(spec["history_start"] is None for spec in CONTRACTS.values())
        )
        # Same already historical code/day keeps its epoch and params as today advances.
        old = list(jobs(CFG, date(2024, 3, 12)))[21:]
        new = list(jobs(CFG, date(2024, 3, 13)))[21:]
        self.assertEqual(old, new[: len(old)])

    def test_per_api_scope_subset_and_missing_universe_do_not_drop_allmarket(self):
        cfg = {
            **CFG,
            "securities_lending_history_apis": [
                "slb_sec_detail",
                "slb_sec",
                "slb_sec_detail",
            ],
            "securities_lending_history_start": {"slb_sec": "20240311"},
        }
        planned = list(jobs(cfg, date(2024, 3, 12), {}))
        self.assertEqual(len([j for j in planned if j["api_name"] == "slb_sec"]), 2)
        self.assertEqual(
            len([j for j in planned if j["api_name"] == "slb_sec_detail"]), 15
        )
        self.assertEqual(
            {
                g["api_name"]
                for g in prerequisites({}, config=cfg)
                if g["reason"] == "missing_stocks_for_saturated_day"
            },
            {"slb_sec", "slb_sec_detail"},
        )

    def test_real_retired_and_t_identifiers_no_guessed_stock(self):
        ids = {
            "stocks": [
                {"ts_code": "T600018.SH", "list_status": "D"},
                "600018.SH",
                "920680.BJ",
                "000851.SZ",
            ]
        }
        before = json.dumps(ids, sort_keys=True)
        self.assertEqual(
            identifiers(ids)["stocks"],
            ["000851.SZ", "600018.SH", "920680.BJ", "T600018.SH"],
        )
        self.assertEqual(json.dumps(ids, sort_keys=True), before)
        self.assertEqual(identifiers()["stocks"], [])
        for value in ("SH600018", "00001.HK", 600018, "600018.SH\n"):
            with self.assertRaises(ValueError):
                identifiers({"stocks": [value]})
        gaps = prerequisites(ids, config=CFG)
        self.assertEqual(
            len([g for g in gaps if g["reason"] == "historical_universe_unverified"]), 3
        )

    def test_existing_date_split_preserves_stock_and_exhausts_at_single_day(self):
        api = "slb_sec_detail"
        pipeline = object.__new__(Pipeline)
        params = {
            "ts_code": "T600018.SH",
            "start_date": "20240228",
            "end_date": "20240301",
        }
        with patch(
            "backend.shared.tushare_pipeline.contract_for", return_value=CONTRACTS[api]
        ):
            children = pipeline.date_children({"api_name": api, "params": params})
            self.assertEqual(
                children,
                [
                    {**params, "end_date": "20240229"},
                    {**params, "start_date": "20240301"},
                ],
            )
            self.assertIsNone(
                pipeline.date_children(
                    {"api_name": api, "params": {**params, "end_date": "20240228"}}
                )
            )
            self.assertIsNone(
                pipeline.date_children(
                    {
                        "api_name": api,
                        "params": {"ts_code": "T600018.SH", "trade_date": "20240228"},
                    }
                )
            )
        for spec in CONTRACTS.values():
            self.assertEqual(spec["saturation_fallback"], "stocks")
            self.assertEqual(spec["saturation_param"], "ts_code")
            self.assertNotIn("tenor", spec["allowed_params"])
            self.assertNotIn("fee_rate", spec["allowed_params"])
            self.assertNotIn("offset", spec["allowed_params"])

    def test_capture_keeps_null_zero_unknown_and_does_not_hide_cap_or_missing_column(
        self,
    ):
        api = "slb_sec_detail"
        spec = CONTRACTS[api]
        fields = FIELDS[api] + ["new_source"]
        values = [
            "20240620",
            "000001.SZ",
            None,
            "14",
            0.0,
            None,
            {"unknown": [0, None]},
        ]
        base = {
            "api_name": api,
            "params": {"trade_date": "20240620"},
            "fields": ",".join(FIELDS[api]),
            **spec,
        }
        for case, result_fields, rows, expected in (
            ("normal", fields, [values], "sample_ok"),
            (
                "missing nullable fee_rate",
                fields[:4] + fields[5:],
                [values[:4] + values[5:]],
                "schema_gap",
            ),
            ("saturated", fields, [values] * 5000, "possibly_truncated"),
            ("empty", fields, [], "empty_unverified"),
        ):
            payload = {"code": 0, "data": {"fields": result_fields, "items": rows}}
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as tmp,
                patch("socket.socket.connect", side_effect=AssertionError("offline")),
                httpx.Client(
                    transport=httpx.MockTransport(
                        lambda _, body=payload: httpx.Response(200, json=body)
                    )
                ) as client,
            ):
                result = capture_sample(client, "synthetic-no-secret", base, Path(tmp))
                self.assertEqual(result["status"], expected)
                raw = json.loads(
                    (
                        Path(tmp) / "objects" / (result["object_sha256"] + ".json")
                    ).read_bytes()
                )
                self.assertEqual(raw, payload)
                self.assertFalse(result["history_complete"])
                if case == "normal":
                    self.assertEqual(
                        result["unexpected_returned_fields"], ["new_source"]
                    )
                if case.startswith("missing"):
                    self.assertIn("fee_rate", result["requested_missing_fields"])


if __name__ == "__main__":
    unittest.main()
