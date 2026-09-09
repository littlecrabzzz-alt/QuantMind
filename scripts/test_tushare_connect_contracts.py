"""Pure, offline Connect/board-flow plans; never registers or probes endpoints."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_connect_contracts import (
    CONNECT_CONTRACTS as CONTRACTS,
    FIELDS,
    INPUT_FIELDS,
    VARIANTS,
    connect_prerequisites,
    iter_connect_jobs,
)
from backend.shared.tushare_registry import EXTENDED_CONTRACTS
from backend.shared.tushare_intake import assess_response


def span(start, end):
    return {
        (start + timedelta(days=n)).strftime("%Y%m%d")
        for n in range((end - start).days + 1)
    }


class ConnectContractsTest(unittest.TestCase):
    def test_five_unregistered_apis_fields_and_parameter_table_not_enum_table(self):
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )["entries"]
        self.assertEqual(
            set(CONTRACTS),
            {
                "stock_hsgt",
                "hsgt_top10",
                "moneyflow_cnt_ths",
                "moneyflow_ind_ths",
                "moneyflow_ind_dc",
            },
        )
        for api, spec in CONTRACTS.items():
            self.assertNotIn("group", spec)
            entry = next(e for e in catalog if api in e.get("api_names", []))
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["input_fields"], INPUT_FIELDS[api])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertEqual(spec["requests_per_minute"], 50)
            self.assertEqual(spec["positive_fields"], [])
            self.assertEqual(spec["attachment_fields"], [])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertNotIn("pagination", spec)
        registered = json.dumps(EXTENDED_CONTRACTS, sort_keys=True)
        list(iter_connect_jobs({"connect_apis": ["hsgt_top10"]}, date(2026, 9, 9)))
        self.assertEqual(json.dumps(EXTENDED_CONTRACTS, sort_keys=True), registered)
        self.assertEqual(
            INPUT_FIELDS["stock_hsgt"],
            ["ts_code", "trade_date", "type", "start_date", "end_date"],
        )
        self.assertFalse(
            set(INPUT_FIELDS["stock_hsgt"]) & {"HK_SZ", "SZ_HK", "HK_SH", "SH_HK"}
        )
        self.assertIsNone(CONTRACTS["hsgt_top10"]["minimum_points"])
        self.assertFalse(CONTRACTS["hsgt_top10"]["row_cap_verified"])
        self.assertEqual(CONTRACTS["stock_hsgt"]["history_start"], "20250812")

    def test_all_directions_types_recent_first_and_complete_date_union(self):
        cfg = {"connect_history_start": "20250701", "planning_epoch": "fixture"}
        with (
            patch("socket.getaddrinfo", side_effect=AssertionError("offline")),
            patch("socket.socket.connect", side_effect=AssertionError("offline")),
        ):
            jobs = list(iter_connect_jobs(cfg, date(2025, 9, 9)))
        self.assertEqual(jobs, list(iter_connect_jobs(cfg, date(2025, 9, 9))))
        self.assertEqual(len(jobs), len({json.dumps(j, sort_keys=True) for j in jobs}))
        first = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(
            all(j["epoch"] == "fixture" and j["priority"] == 20 for j in jobs[:first])
        )
        self.assertTrue(
            all(j["epoch"] == "history" and j["priority"] == 40 for j in jobs[first:])
        )
        covered = defaultdict(set)
        for job in jobs:
            api, p = job["api_name"], job["params"]
            self.assertTrue(set(p) <= set(INPUT_FIELDS[api]))
            self.assertNotIn("offset", p)
            if "trade_date" in p:
                days = {p["trade_date"]}
            else:
                begin = datetime.strptime(p["start_date"], "%Y%m%d").date()
                end = datetime.strptime(p["end_date"], "%Y%m%d").date()
                days = span(begin, end)
            variant = tuple(
                (key, p[key])
                for key in ("type", "market_type", "content_type")
                if key in p
            )
            self.assertFalse(covered[(api, variant)] & days)
            covered[(api, variant)] |= days
        for api in CONTRACTS:
            begin = date(2025, 8, 12) if api == "stock_hsgt" else date(2025, 7, 1)
            for variant in VARIANTS.get(api, [{}]):
                self.assertEqual(
                    covered[(api, tuple(variant.items()))],
                    span(begin, date(2025, 9, 9)),
                )
        self.assertTrue(
            all(
                "trade_date" in j["params"]
                for j in jobs
                if j["api_name"] == "hsgt_top10"
            )
        )

    def test_leap_month_split_metadata_and_historical_prefix_not_guessed(self):
        cfg = {
            "connect_apis": [
                "moneyflow_cnt_ths",
                "moneyflow_ind_ths",
                "moneyflow_ind_dc",
            ],
            "connect_history_start": "20240227",
        }
        jobs = list(iter_connect_jobs(cfg, date(2024, 3, 9)))
        history = [j for j in jobs if j["epoch"] == "history"]
        for api in cfg["connect_apis"]:
            windows = [j["params"] for j in history if j["api_name"] == api]
            self.assertTrue(
                any(
                    p["start_date"] == "20240227" and p["end_date"] == "20240229"
                    for p in windows
                )
            )
            self.assertTrue(
                any(
                    p["start_date"] == "20240301" and p["end_date"] == "20240302"
                    for p in windows
                )
            )
            self.assertEqual(
                CONTRACTS[api]["split"],
                {
                    "start_param": "start_date",
                    "end_param": "end_date",
                    "precision": "day",
                },
            )
        unknown = list(
            iter_connect_jobs({"connect_apis": ["moneyflow_ind_dc"]}, date(2026, 9, 9))
        )
        self.assertEqual(len(unknown), 21)
        self.assertFalse(any(j["epoch"] == "history" for j in unknown))
        gaps = connect_prerequisites(config={"connect_apis": ["moneyflow_ind_dc"]})
        self.assertIn(
            "unknown_history_start_requires_scope", {g["reason"] for g in gaps}
        )
        self.assertTrue(
            all(not g["universe_complete"] for g in gaps if "universe_complete" in g)
        )
        self.assertEqual(
            list(iter_connect_jobs({"connect_apis": ["stock_hsgt"]}, date(2024, 1, 1))),
            [],
        )

    def test_negative_null_supplier_measurements_not_rejected_or_reconstructed(self):
        for api, spec in CONTRACTS.items():
            row = dict.fromkeys(FIELDS[api])
            row.update(dict.fromkeys(spec["required_fields"], "supplier-key"))
            row["trade_date"] = "20260904"
            for f in ("net_amount", "change", "net_buy_amount"):
                if f in row:
                    row[f] = -123.45
            payload = {
                "code": 0,
                "data": {"fields": list(row), "items": [list(row.values())]},
            }
            before = json.dumps(payload, ensure_ascii=False)
            assessed = assess_response(
                payload,
                row_cap=spec["row_cap"],
                required_fields=spec["required_fields"],
                nullable_fields=spec["nullable_fields"],
                positive_fields=spec["positive_fields"],
            )
            self.assertEqual(assessed["status"], "sample_ok")
            self.assertEqual(json.dumps(payload, ensure_ascii=False), before)
        self.assertEqual(
            CONTRACTS["moneyflow_ind_dc"]["keys"],
            ["trade_date", "ts_code", "content_type"],
        )
        self.assertIn("hundred-million", CONTRACTS["moneyflow_ind_ths"]["unit_note"])
        self.assertIn("CNY", CONTRACTS["moneyflow_ind_dc"]["unit_note"])

    def test_validation_and_lazy_long_history(self):
        for cfg in (
            {"connect_apis": ["ggt_daily"]},
            {"connect_apis": "stock_hsgt"},
            {"connect_history_start": 42},
            {"connect_history_start": {"wrong": "20200101"}},
            {"connect_history_start": "20240230"},
            {"connect_history_start": "20990101"},
        ):
            with self.assertRaises(ValueError):
                list(iter_connect_jobs(cfg, date(2026, 9, 9)))
        self.assertEqual(
            list(iter_connect_jobs({"connect_apis": []}, date(2026, 9, 9))), []
        )
        self.assertEqual(
            len(
                list(
                    islice(
                        iter_connect_jobs(
                            {"history_start": "19000101"}, date(2026, 9, 9)
                        ),
                        5,
                    )
                )
            ),
            5,
        )
        gaps = connect_prerequisites(config={"history_start": "19900101"})
        self.assertIn(
            "pit_gap", {g["reason"] for g in gaps if g["api_name"] == "stock_hsgt"}
        )
        self.assertIn(
            "filter_consistency_gap",
            {g["reason"] for g in gaps if g["api_name"] == "stock_hsgt"},
        )
        self.assertIn(
            "cap_gap", {g["reason"] for g in gaps if g["api_name"] == "hsgt_top10"}
        )


if __name__ == "__main__":
    unittest.main()
