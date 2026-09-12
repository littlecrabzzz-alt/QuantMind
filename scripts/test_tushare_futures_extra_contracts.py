"""Offline checks for futures fields, distinct clocks and lazy complete scopes."""

from datetime import date, datetime, timedelta
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
    FUT_INDEX_DAILY_DOCUMENTED_CODES,
    FUTURES_EXTRA_CONTRACTS as CONTRACTS,
    INPUT_FIELDS,
    futures_extra_prerequisites,
    iter_futures_extra_jobs as jobs,
    validate_futures_index_request,
)


def days(begin, end):
    return {
        (begin + timedelta(days=i)).strftime("%Y%m%d")
        for i in range((end - begin).days + 1)
    }


class FuturesExtra(unittest.TestCase):
    def test_observed_dce_underscore_codes_do_not_block_family(self):
        # Actual fut_basic discovery includes these six supplier identifiers.
        codes = ["L_F.DCE", "L_FL.DCE", "PP_F.DCE", "PP_FL.DCE", "V_F.DCE", "V_FL.DCE"]
        config = {"futures_extra_apis": ["ft_limit"], "history_start": "20260901"}
        gaps = futures_extra_prerequisites({"futures": codes}, config=config)
        self.assertEqual(
            next(g["observed_codes"] for g in gaps if g["dependencies"]), 6
        )
        self.assertTrue(list(jobs(config, date(2026, 9, 9), {"futures": codes})))
        for bad in ("L F.DCE", "L_F.DCE/", "L_F.UNKNOWN"):
            with self.assertRaises(ValueError):
                futures_extra_prerequisites({"futures": [bad]}, config=config)

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
        self.assertEqual(len(FUT_INDEX_DAILY_DOCUMENTED_CODES), 56)
        self.assertEqual(len(set(FUT_INDEX_DAILY_DOCUMENTED_CODES)), 56)
        self.assertIn("CU.NH", FUT_INDEX_DAILY_DOCUMENTED_CODES)
        self.assertEqual(
            CONTRACTS["fut_index_daily"]["dependencies"], ["futures_indexes"]
        )
        self.assertEqual(
            CONTRACTS["fut_index_daily"]["documented_codes"],
            list(FUT_INDEX_DAILY_DOCUMENTED_CODES),
        )
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
            if j["api_name"] == "fut_index_daily":
                self.assertEqual(set(p), {"ts_code", "start_date", "end_date"})
                self.assertRegex(p["ts_code"], r"^[A-Za-z][A-Za-z0-9]*\.NH$")
                validate_futures_index_request(p)

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
            dates_by_code = {}
            for j in planned:
                if j["api_name"] != api:
                    continue
                p = j["params"]
                if api == "fut_trade_cal":
                    dates.extend(
                        days(
                            datetime.strptime(p["start_date"], "%Y%m%d").date(),
                            datetime.strptime(p["end_date"], "%Y%m%d").date(),
                        )
                    )
                    self.assertNotIn("is_open", p)
                    self.assertNotIn("exchange", p)
                elif api == "fut_index_daily":
                    covered = days(
                        datetime.strptime(p["start_date"], "%Y%m%d").date(),
                        datetime.strptime(p["end_date"], "%Y%m%d").date(),
                    )
                    dates_by_code.setdefault(p["ts_code"], []).extend(covered)
                    self.assertEqual(p["start_date"][:4], p["end_date"][:4])
                else:
                    dates.append(p["trade_date"])
            if api == "fut_index_daily":
                self.assertEqual(
                    set(dates_by_code), set(FUT_INDEX_DAILY_DOCUMENTED_CODES)
                )
                for covered in dates_by_code.values():
                    self.assertEqual(set(covered), days(begin, today))
                    self.assertEqual(len(covered), len(set(covered)))
            else:
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
        index_gap = next(g for g in discoveries if g["api_name"] == "fut_index_daily")
        self.assertEqual(index_gap["documented_codes"], 56)
        self.assertEqual(index_gap["eligible_codes"], 56)
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
                j["params"]["start_date"]
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

    def test_fut_index_daily_uses_documented_and_observed_codes_with_ranges(self):
        config = {
            "futures_extra_apis": ["fut_index_daily"],
            "history_start": "20250101",
            "planning_epoch": "fixture",
        }
        identifiers = {"futures_indexes": ["CU.NH", "OLD1.NH"]}
        planned = list(jobs(config, date(2026, 9, 9), identifiers))
        expected_codes = set(FUT_INDEX_DAILY_DOCUMENTED_CODES) | {"OLD1.NH"}
        self.assertEqual({j["params"]["ts_code"] for j in planned}, expected_codes)
        self.assertTrue(all("trade_date" not in j["params"] for j in planned))
        self.assertTrue(
            all(
                set(j["params"]) == {"ts_code", "start_date", "end_date"}
                for j in planned
            )
        )
        identities = {
            (j["params"]["ts_code"], j["params"]["start_date"], j["params"]["end_date"])
            for j in planned
        }
        self.assertEqual(len(identities), len(planned))
        self.assertTrue(any(j["params"]["ts_code"] == "OLD1.NH" for j in planned))
        self.assertTrue(any(j["epoch"] == "history" for j in planned))
        for bad in ("CU.SHF", "1CU.NH", "CU.NH/"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                next(jobs(config, date(2026, 9, 9), {"futures_indexes": [bad]}))

    def test_fut_index_unknown_history_keeps_recent_legal_scope_and_gap(self):
        config = {"futures_extra_apis": ["fut_index_daily"]}
        planned = list(jobs(config, date(2026, 9, 9)))
        self.assertEqual(len(planned), len(FUT_INDEX_DAILY_DOCUMENTED_CODES))
        self.assertTrue(all(j["epoch"] != "history" for j in planned))
        self.assertTrue(
            all(
                j["params"]["start_date"] == "20260903"
                and j["params"]["end_date"] == "20260909"
                for j in planned
            )
        )
        gaps = futures_extra_prerequisites(config=config)
        self.assertTrue(
            any(
                gap["api_name"] == "fut_index_daily"
                and gap["reason"] == "unknown_history_start_requires_scope"
                for gap in gaps
            )
        )
        self.assertTrue(
            any(
                gap["api_name"] == "fut_index_daily"
                and gap["reason"] == "saturation_discovery_unverified"
                and not gap["universe_complete"]
                for gap in gaps
            )
        )

    def test_fut_index_request_validator_rejects_unbounded_or_mixed_axes(self):
        for params in (
            {"trade_date": "20260909"},
            {"ts_code": "CU.SHF", "trade_date": "20260909"},
            {
                "ts_code": "CU.NH",
                "trade_date": "20260909",
                "start_date": "20260901",
                "end_date": "20260909",
            },
            {
                "ts_code": "CU.NH",
                "start_date": "20260909",
                "end_date": "20260901",
            },
            {"ts_code": "CU.NH", "trade_date": "20260230"},
            {"ts_code": "CU.NH", "trade_date": "20260909", "offset": 0},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                validate_futures_index_request(params)
        validate_futures_index_request({"ts_code": "CU.NH", "trade_date": "20260909"})
        for optional in ({}, {"start_date": "20260901"}, {"end_date": "20260909"}):
            validate_futures_index_request({"ts_code": "CU.NH", **optional})
        validate_futures_index_request(
            {
                "ts_code": "CU.NH",
                "start_date": "20260101",
                "end_date": "20261231",
            }
        )


if __name__ == "__main__":
    unittest.main()
