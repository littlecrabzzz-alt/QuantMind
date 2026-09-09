"""Pure bond-contract checks: no credentials, provider calls or authoritative data."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_bond_extra_contracts import (
    BOND_EXTRA_CONTRACTS as CONTRACTS,
    FIELDS,
    FIELD_METADATA,
    INPUT_FIELDS,
    INPUT_METADATA,
    bond_extra_prerequisites,
    iter_bond_extra_jobs,
)


class BondContracts(unittest.TestCase):
    def setUp(self):
        self.net = patch(
            "socket.socket.connect", side_effect=AssertionError("pure only")
        )
        self.net.start()
        self.addCleanup(self.net.stop)

    def test_all_fields_hidden_outputs_and_input_catalog_identity(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        entries = {
            api: entry for entry in catalog["entries"] for api in entry["api_names"]
        }
        self.assertEqual(sum(map(len, FIELDS.values())), 70)
        self.assertEqual(
            {
                a: len(s["hidden_fields"])
                for a, s in CONTRACTS.items()
                if s["hidden_fields"]
            },
            {"bc_otcqt": 13, "bc_bestotcqt": 9},
        )
        for api, spec in CONTRACTS.items():
            self.assertEqual(FIELDS[api], entries[api]["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entries[api]["input_fields"])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["field_metadata"], FIELD_METADATA[api])
            self.assertEqual(set(spec["field_gaps"]), set(FIELDS[api]))
            self.assertTrue(
                all(
                    m.keys() == {"type", "default", "description"}
                    for m in FIELD_METADATA[api].values()
                )
            )
            self.assertTrue(
                all(
                    m.keys() == {"type", "required", "description"}
                    for m in INPUT_METADATA[api].values()
                )
            )
            self.assertNotIn("offset", INPUT_FIELDS[api])
            self.assertNotIn("pagination", spec)
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertIsNone(spec["history_start"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertEqual(spec["permission_status"], "unprobed")
        self.assertIn("yield", FIELDS["yc_cb"])
        self.assertEqual(CONTRACTS["cb_rating"]["input_fields"], ["ts_code"])
        self.assertIn(
            "example calls cb_daily", CONTRACTS["cb_rating"]["documentation_gap"]
        )
        self.assertNotIn("catalog_api", CONTRACTS["cb_rating"])

    def test_one_day_variants_and_missing_convertible_discovery(self):
        cfg = {"bond_extra_history_start": "20260904"}
        jobs = list(iter_bond_extra_jobs(cfg, date(2026, 9, 4)))
        self.assertEqual(len(jobs), 7)
        self.assertEqual(
            {j["params"]["curve_type"] for j in jobs if j["api_name"] == "yc_cb"},
            {"0", "1"},
        )
        self.assertFalse(
            any(j["api_name"] in ("top10_cb_holders", "cb_rating") for j in jobs)
        )
        for j in jobs:
            self.assertEqual(j["params"]["trade_date"], "20260904")
            self.assertEqual(j["epoch"], "20260904")
            self.assertEqual(set(j["fields"].split(",")), set(FIELDS[j["api_name"]]))
            self.assertLessEqual(set(j["params"]), set(INPUT_FIELDS[j["api_name"]]))
        gaps = bond_extra_prerequisites(config=cfg)
        discovery = [g for g in gaps if g["dependencies"]]
        self.assertEqual(
            {g["api_name"] for g in discovery}, {"top10_cb_holders", "cb_rating"}
        )
        self.assertTrue(
            all(
                g["observed_codes"] == 0 and not g["universe_complete"]
                for g in discovery
            )
        )

    def test_holders_report_range_and_ratings_legal_code_only(self):
        ids = {
            "bonds": [
                {"ts_code": "T110001.SH", "delist_date": "20010101"},
                {"ts_code": "123001.SZ", "list_date": "20260101"},
                "T110001.SH",
            ]
        }
        cfg = {
            "bond_extra_apis": ["top10_cb_holders", "cb_rating"],
            "history_start": "19900101",
            "planning_epoch": "fixed-anchor",
        }
        jobs = list(iter_bond_extra_jobs(cfg, datetime(2026, 9, 4), ids))
        self.assertEqual(len(jobs), 6)
        self.assertEqual(
            {j["params"]["ts_code"] for j in jobs}, {"T110001.SH", "123001.SZ"}
        )
        for code in ("T110001.SH", "123001.SZ"):
            holders = [
                j
                for j in jobs
                if j["api_name"] == "top10_cb_holders"
                and j["params"]["ts_code"] == code
            ]
            recent = next(j for j in holders if j["epoch"] == "fixed-anchor")
            historic = next(j for j in holders if j["epoch"] == "history")
            self.assertEqual(
                recent["params"],
                {"ts_code": code, "start_date": "20250101", "end_date": "20260904"},
            )
            self.assertEqual(
                historic["params"],
                {"ts_code": code, "start_date": "19900101", "end_date": "20241231"},
            )
            rating = next(
                j
                for j in jobs
                if j["api_name"] == "cb_rating" and j["params"]["ts_code"] == code
            )
            self.assertEqual(rating["params"], {"ts_code": code})
            self.assertEqual(rating["epoch"], "fixed-anchor")
        self.assertEqual(CONTRACTS["top10_cb_holders"]["split_axis"], "end_date")
        self.assertEqual(CONTRACTS["cb_rating"]["date_field"], "ann_date")
        self.assertIsNone(CONTRACTS["cb_rating"]["split"])
        self.assertTrue(
            any(
                g["reason"] == "history_scope_gap"
                for g in bond_extra_prerequisites(ids, config=cfg)
            )
        )
        # A later explicit report scope never expands into an earlier period.
        cfg["bond_extra_history_start"] = "20260301"
        self.assertEqual(
            [
                j["params"]["start_date"]
                for j in iter_bond_extra_jobs(cfg, date(2026, 9, 4), ids)
                if j["api_name"] == "top10_cb_holders"
            ],
            ["20260301", "20260301"],
        )

    def test_daily_leap_year_boundary_no_overlap_or_date_omissions(self):
        cfg = {
            "bond_extra_apis": ["repo_daily", "yc_cb"],
            "bond_extra_history_start": "20240226",
        }
        today = date(2024, 3, 4)
        jobs = list(iter_bond_extra_jobs(cfg, today))
        dates = {
            (date(2024, 2, 26) + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)
        }
        for api in cfg["bond_extra_apis"]:
            groups = ("0", "1") if api == "yc_cb" else (None,)
            for kind in groups:
                chosen = [
                    j
                    for j in jobs
                    if j["api_name"] == api and j["params"].get("curve_type") == kind
                ]
                self.assertEqual(len(chosen), 8)
                self.assertEqual({j["params"]["trade_date"] for j in chosen}, dates)
                self.assertEqual(
                    [
                        j["params"]["trade_date"]
                        for j in chosen
                        if j["epoch"] == "history"
                    ],
                    ["20240226"],
                )
        self.assertEqual(list(iter_bond_extra_jobs(cfg, today)), jobs)

    def test_unknown_history_namespaces_units_and_saturation_stay_visible(self):
        jobs = list(
            iter_bond_extra_jobs({"bond_extra_apis": ["repo_daily"]}, date(2026, 9, 4))
        )
        self.assertEqual(len(jobs), 7)
        self.assertTrue(all(j["epoch"] != "history" for j in jobs))
        gaps = bond_extra_prerequisites()
        self.assertEqual(
            sum(g["reason"] == "unknown_history_start_requires_scope" for g in gaps), 8
        )
        self.assertIsNotNone(CONTRACTS["yc_cb"]["independent_permission"])
        self.assertIsNone(CONTRACTS["yc_cb"]["minimum_points"])
        self.assertEqual(
            CONTRACTS["repo_daily"]["source_namespace"], "REPO:<original ts_code>"
        )
        self.assertEqual(
            CONTRACTS["top10_cb_holders"]["source_namespace"], "CB:<original ts_code>"
        )
        self.assertEqual(CONTRACTS["yc_cb"]["request_identity_fields"], ["curve_type"])
        self.assertIn("curve_term", INPUT_FIELDS["yc_cb"])
        self.assertIn("bank", INPUT_FIELDS["bc_otcqt"])
        self.assertNotIn("qt_time", INPUT_FIELDS["bc_otcqt"])
        self.assertNotIn("bank", INPUT_FIELDS["bc_bestotcqt"])
        self.assertIn("Shenzhen", CONTRACTS["bond_blk_detail"]["coverage_gap"])
        self.assertIn("percent rates", CONTRACTS["repo_daily"]["unit_note"])
        self.assertIn("万张", CONTRACTS["top10_cb_holders"]["unit_note"])
        self.assertIn("unimplemented", CONTRACTS["bc_otcqt"]["saturation_gap"])
        self.assertIn("unknown", CONTRACTS["yc_cb"]["saturation_gap"])
        self.assertNotIn(
            "stocks", {d for s in CONTRACTS.values() for d in s.get("dependencies", [])}
        )

    def test_invalid_scope_or_required_discovery_fails_before_first_job(self):
        configs = [
            {"bond_extra_apis": "repo_daily"},
            {"bond_extra_apis": ["cb_daily"]},
            {"bond_extra_history_start": 42},
            {"bond_extra_history_start": {"wrong": "20000101"}},
            {"history_start": "20260230"},
            {"history_start": "20270101"},
        ]
        for cfg in configs:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                next(iter_bond_extra_jobs(cfg, date(2026, 9, 4)))
        with self.assertRaises(ValueError):
            next(iter_bond_extra_jobs({}, date(2026, 9, 4), {"bonds": ["bad;code"]}))
        # An unrelated malformed convertible list does not block daily-only scope.
        self.assertEqual(
            len(
                list(
                    iter_bond_extra_jobs(
                        {"bond_extra_apis": ["repo_daily"]},
                        date(2026, 9, 4),
                        {"bonds": ["bad;code"]},
                    )
                )
            ),
            7,
        )
        self.assertEqual(
            list(iter_bond_extra_jobs({"bond_extra_apis": []}, date(2026, 9, 4))), []
        )

    def test_history_stream_is_lazy_and_api_round_robin(self):
        tracemalloc.start()
        try:
            jobs = list(
                islice(
                    iter_bond_extra_jobs(
                        {"history_start": "19900101"},
                        date(2099, 12, 31),
                        {"bonds": ["110001.SH"]},
                    ),
                    300,
                )
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 2_000_000)
        self.assertEqual({j["api_name"] for j in jobs[:8]}, set(CONTRACTS))
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(all(j["epoch"] == "history" for j in jobs[first_history:]))
        self.assertEqual(
            {
                j["params"]["start_date"]
                for j in jobs
                if j["api_name"] == "top10_cb_holders" and j["epoch"] == "history"
            },
            {"19900101"},
        )


if __name__ == "__main__":
    unittest.main()
