"""Offline checks for futures fields, distinct clocks and lazy complete scopes."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_futures_extra_contracts import (  # noqa: E402
    FIELDS,
    FUTURES_EXTRA_CONTRACTS as CONTRACTS,
    INPUT_FIELDS,
    futures_extra_prerequisites,
    iter_futures_extra_jobs as jobs,
)


def days(begin, end):
    return {
        (begin + timedelta(days=i)).strftime("%Y%m%d")
        for i in range((end - begin).days + 1)
    }


class FuturesExtra(unittest.TestCase):
    def test_all_seven_exact_docs_fields_hidden_and_caps(self):
        expected = {
            "fut_trade_cal",
            "fut_daily_adj",
            "fut_weekly_monthly",
            "fut_holding",
            "fut_index_daily",
            "fut_weekly_detail",
            "ft_limit",
        }
        self.assertEqual(set(CONTRACTS), expected)
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        for api, contract in CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(contract["extra_fields"], FIELDS[api])
            self.assertTrue(set(contract["keys"]) <= set(FIELDS[api]))
            self.assertEqual(contract["positive_fields"], [])
            self.assertEqual(contract["permission_status"], "unprobed")
            self.assertIsNone(contract["independent_permission"])
            self.assertNotIn("pagination", contract)
            self.assertNotIn("catalog_api", contract)
            self.assertNotIn("dataset_identity", contract)
        self.assertEqual(CONTRACTS["fut_trade_cal"]["hidden_fields"], ["pretrade_date"])
        self.assertEqual(CONTRACTS["fut_daily_adj"]["hidden_fields"], ["delv_settle"])
        self.assertEqual(CONTRACTS["fut_holding"]["hidden_fields"], ["exchange"])
        self.assertEqual(CONTRACTS["fut_daily_adj"]["row_cap"], 3000)
        self.assertEqual(CONTRACTS["fut_weekly_monthly"]["row_cap"], 6000)
        self.assertIsNone(CONTRACTS["fut_weekly_monthly"]["minimum_points"])
        self.assertFalse(CONTRACTS["fut_index_daily"]["row_cap_verified"])
        self.assertFalse(CONTRACTS["fut_trade_cal"]["row_cap_verified"])
        self.assertEqual(sum(map(len, FIELDS.values())), 85)

    def test_offline_valid_parameters_recent_before_history(self):
        config = {
            "futures_extra_history_start": "20240101",
            "planning_epoch": "fixture",
        }
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            planned = list(jobs(config, date(2024, 3, 12)))
        self.assertEqual(planned, list(jobs(config, date(2024, 3, 12))))
        self.assertEqual(
            len(planned), len({json.dumps(j, sort_keys=True) for j in planned})
        )
        first_history = next(
            i for i, j in enumerate(planned) if j["epoch"] == "history"
        )
        self.assertTrue(
            all(
                j["epoch"] == "fixture" and j["priority"] == 20
                for j in planned[:first_history]
            )
        )
        self.assertTrue(all(j["priority"] == 40 for j in planned[first_history:]))
        for j in planned:
            p = j["params"]
            self.assertTrue(set(p) <= set(INPUT_FIELDS[j["api_name"]]))
            self.assertNotIn("offset", p)
            self.assertNotIn("limit", p)
            if j["api_name"] == "fut_holding":
                self.assertIn("trade_date", p)
                self.assertNotIn("ts_code", p)
            if j["api_name"] == "fut_weekly_monthly":
                self.assertIn(p["freq"], ("week", "month"))

    def test_daily_and_exchange_calendar_cover_holidays_and_leap_day(self):
        begin, today = date(2024, 2, 27), date(2024, 3, 12)
        apis = [
            "fut_trade_cal",
            "fut_daily_adj",
            "fut_holding",
            "fut_index_daily",
            "ft_limit",
        ]
        planned = list(
            jobs({"futures_extra_apis": apis, "history_start": "20240227"}, today)
        )
        for api in apis:
            dates = []
            for j in planned:
                if j["api_name"] != api:
                    continue
                p = j["params"]
                if api == "fut_trade_cal":
                    dates.extend(
                        days(
                            date.fromisoformat(p["start_date"]),
                            date.fromisoformat(p["end_date"]),
                        )
                    )
                    self.assertNotIn("is_open", p)
                    self.assertNotIn("exchange", p)
                else:
                    dates.append(p["trade_date"])
            self.assertEqual(set(dates), days(begin, today))
            self.assertEqual(len(dates), len(set(dates)))
        self.assertIn("GFEX", CONTRACTS["fut_trade_cal"]["discovery_gap"])
        self.assertIn("night", CONTRACTS["fut_trade_cal"]["session_note"])
        self.assertNotIn("SSE", json.dumps(planned))

    def test_current_period_labels_include_future_friday_month_end(self):
        today = date(2026, 9, 9)
        planned = list(
            jobs(
                {
                    "futures_extra_apis": ["fut_weekly_monthly"],
                    "history_start": "20260101",
                },
                today,
            )
        )
        for freq in ("week", "month"):
            labels = [
                j["params"]["trade_date"]
                for j in planned
                if j["params"]["freq"] == freq
            ]
            self.assertEqual(set(labels), days(date(2026, 1, 1), date(2026, 9, 30)))
            self.assertEqual(len(labels), len(set(labels)))
            self.assertIn("20260911", labels)
            self.assertIn("20260930", labels)
        self.assertEqual(
            CONTRACTS["fut_weekly_monthly"]["keys"],
            ["ts_code", "trade_date", "freq", "end_date"],
        )
        self.assertEqual(CONTRACTS["fut_weekly_monthly"]["split_axis"], "period_label")
        month_edge = list(
            jobs({"futures_extra_apis": ["fut_weekly_monthly"]}, date(2026, 9, 30))
        )
        self.assertIn("20261002", {j["params"]["trade_date"] for j in month_edge})

    def test_week_ordinals_do_not_invent_iso_or_rewrite_source_spelling(self):
        planned = list(
            jobs(
                {
                    "futures_extra_apis": ["fut_weekly_detail"],
                    "history_start": "20100315",
                },
                date(2026, 1, 1),
            )
        )
        observed = {j["params"]["week"] for j in planned}
        self.assertEqual(
            observed,
            {
                f"{year}{ordinal:02d}"
                for year in range(2010, 2027)
                for ordinal in range(1, 54)
            },
        )
        self.assertEqual(len(observed), len(planned))
        self.assertEqual(
            {j["params"]["week"][:4] for j in planned if j["epoch"] != "history"},
            {"2025", "2026"},
        )
        self.assertTrue(all(set(j["params"]) == {"week"} for j in planned))
        self.assertIsNone(CONTRACTS["fut_weekly_detail"]["split"])
        self.assertIn("20199", CONTRACTS["fut_weekly_detail"]["week_note"])
        self.assertIn("amout_yoy", FIELDS["fut_weekly_detail"])
        self.assertNotIn("amount_yoy", FIELDS["fut_weekly_detail"])
        self.assertEqual(
            CONTRACTS["fut_weekly_detail"]["history_start_precision"], "month"
        )
        self.assertEqual(CONTRACTS["ft_limit"]["history_start_precision"], "year")

    def test_unknown_history_and_incomplete_discovery_stay_explicit(self):
        unknown = [a for a, c in CONTRACTS.items() if c["history_start"] is None]
        planned = list(jobs({"futures_extra_apis": unknown}, date(2026, 9, 9)))
        self.assertTrue(all(j["epoch"] != "history" for j in planned))
        gaps = futures_extra_prerequisites(enabled_apis=unknown)
        self.assertEqual(
            {
                g["api_name"]
                for g in gaps
                if g["reason"] == "unknown_history_start_requires_scope"
            },
            set(unknown),
        )
        ids = {
            "futures": [
                {"ts_code": "cu1901.SHF", "delist_date": "20190115"},
                "CU2601.SHF",
            ],
            "futures_continuous": ["IF.CFX", "IFL3.CFX"],
            "futures_indexes": ["CU.NH", "ER.NH"],
        }
        gaps = futures_extra_prerequisites(ids, config={"history_start": "20100101"})
        discoveries = [
            g for g in gaps if g["reason"] == "saturation_discovery_unverified"
        ]
        self.assertTrue(
            all(
                g["observed_codes"] == 2 and not g["universe_complete"]
                for g in discoveries
            )
        )
        self.assertTrue(
            any(
                g["reason"] == "configured_scope_does_not_prove_earlier_history_absent"
                for g in gaps
            )
        )
        self.assertIn("SHFE includes INE", CONTRACTS["fut_holding"]["parameter_note"])
        self.assertTrue(CONTRACTS["fut_holding"]["preserve_distinct_rows"])
        self.assertNotIn("saturation_fallback", CONTRACTS["fut_holding"])
        self.assertNotIn("_row_identity", FIELDS["fut_holding"])

    def test_validation_scope_maps_and_history_fairness_are_lazy(self):
        for config, ids in (
            ({"futures_extra_apis": ["daily"]}, {}),
            ({"futures_extra_apis": "ft_limit"}, {}),
            ({"futures_extra_history_start": 20050101}, {}),
            ({"futures_extra_history_start": {"daily": "20050101"}}, {}),
            ({"history_start": "20240230"}, {}),
            ({"history_start": "20990101"}, {}),
            ({}, {"futures": ["600036.SH"]}),
            ({}, {"futures_continuous": ["FTIF.CFX"], "futures_indexes": ["CU.SHF"]}),
        ):
            with self.subTest(config=config, ids=ids), self.assertRaises(ValueError):
                next(jobs(config, date(2026, 9, 9), ids))
        mapped = {
            "futures_extra_apis": ["fut_daily_adj", "fut_index_daily"],
            "history_start": "20240201",
            "futures_extra_history_start": {"fut_daily_adj": "20240101"},
        }
        planned = list(jobs(mapped, date(2024, 3, 12)))
        self.assertEqual(
            min(
                j["params"]["trade_date"]
                for j in planned
                if j["api_name"] == "fut_daily_adj"
            ),
            "20240101",
        )
        self.assertEqual(
            min(
                j["params"]["trade_date"]
                for j in planned
                if j["api_name"] == "fut_index_daily"
            ),
            "20240201",
        )
        stream = jobs({"history_start": "10000101"}, date(2026, 9, 9))
        while (job := next(stream))["epoch"] != "history":
            pass
        first = [job, *islice(stream, 6)]
        self.assertEqual({j["api_name"] for j in first}, set(CONTRACTS))
        self.assertEqual(
            list(
                jobs(
                    {"futures_extra_apis": []},
                    date(2026, 9, 9),
                    {"stocks": ["invalid irrelevant"]},
                )
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
