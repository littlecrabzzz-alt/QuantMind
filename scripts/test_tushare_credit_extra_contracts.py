"""Offline credit contract scopes, source identities and legal date axes."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_credit_extra_contracts import (  # noqa: E402
    CREDIT_EXTRA_CONTRACTS as CONTRACTS,
    FIELDS,
    INPUT_FIELDS,
    credit_extra_prerequisites,
    credit_identifiers,
    iter_credit_extra_jobs as jobs,
)

IDS = {
    "stocks": ["600018.SH", {"ts_code": "T600018.SH", "list_status": "D"}, "920000.BJ"],
    "funds": ["510300.SH", {"ts_code": "159001.SZ", "status": "D"}, "000001.OF"],
    "credit_securities": ["T600018.SH", "510500.SH"],
}


def dates(begin, end):
    return {
        (begin + timedelta(days=i)).strftime("%Y%m%d")
        for i in range((end - begin).days + 1)
    }


class CreditExtra(unittest.TestCase):
    def test_exact_seven_full_official_fields_and_permission_uncertainty(self):
        self.assertEqual(
            set(CONTRACTS),
            {
                "margin",
                "margin_detail",
                "margin_secs",
                "slb_len",
                "block_trade",
                "pledge_detail",
                "pledge_stat",
            },
        )
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        for api, spec in CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["hidden_fields"], [])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertIsNone(spec["history_start"])
            self.assertIsNone(spec["stop_date"])
            self.assertEqual(
                spec["update_status"], "not_marked_stopped_in_reviewed_catalog"
            )
            self.assertNotIn("pagination", spec)
            self.assertNotIn("dataset_identity", spec)
            self.assertNotIn("catalog_api", spec)
            self.assertNotIn("_row_identity", spec["extra_fields"])
            self.assertEqual(spec["positive_fields"], [])
        self.assertEqual(sum(map(len, FIELDS.values())), 58)
        self.assertIn("name", CONTRACTS["margin_detail"]["nullable_fields"])
        self.assertIn("is_buyback", FIELDS["pledge_detail"])
        self.assertEqual(CONTRACTS["slb_len"]["row_cap"], 5000)
        self.assertEqual(
            CONTRACTS["margin"]["documented_exchanges"], ["SSE", "SZSE", "BSE"]
        )
        self.assertIn("slb_sec_detail", CONTRACTS["slb_len"]["alias_note"])

    def test_security_union_keeps_etfs_retired_and_distinct_t_stock_codes(self):
        before = json.dumps(IDS, sort_keys=True)
        identities = credit_identifiers(IDS)
        self.assertEqual(identities["stocks"], ["600018.SH", "920000.BJ", "T600018.SH"])
        self.assertEqual(
            identities["credit_securities"],
            [
                "159001.SZ",
                "510300.SH",
                "510500.SH",
                "600018.SH",
                "920000.BJ",
                "T600018.SH",
            ],
        )
        self.assertNotIn("000001.OF", identities["credit_securities"])
        self.assertEqual(json.dumps(IDS, sort_keys=True), before)
        for api in ("margin_detail", "margin_secs", "block_trade"):
            self.assertEqual(CONTRACTS[api]["saturation_fallback"], "credit_securities")
            self.assertEqual(
                CONTRACTS[api]["saturation_dependencies"],
                ["stocks", "funds", "credit_securities"],
            )
        self.assertEqual(
            credit_identifiers({"stocks": ["invalid"]}, ["margin", "slb_len"]), {}
        )
        self.assertEqual(
            credit_identifiers(
                {"stocks": IDS["stocks"], "funds": ["irrelevant"]}, ["pledge_stat"]
            )["stocks"],
            identities["stocks"],
        )

    def test_seven_digit_fund_sources_remain_distinct_and_reentrant(self):
        funds = "0000371.OF 1610142.OF 4720072.OF 1500011.SZ 1601231.SZ 1604221.SZ 1610221.SZ 1612111.SZ 1612301.SZ 1618111.SZ 1627171.SZ 1638271.SZ 1642051.SZ 1648141.SZ 1660071.SZ 5010021.SH 5010491.SH 5010631.SH 5020001.SH 5020201.SH 5020561.SH".split()
        inputs = {
            "stocks": ["600018.SH", "T600018.SH"],
            "funds": [{"ts_code": c, "status": "D"} for c in funds] + ["150001.SZ"],
            "credit_securities": ["1500011.SZ", "0000371.OF"],
        }
        before = json.dumps(inputs, sort_keys=True)
        ids = credit_identifiers(inputs)
        self.assertEqual(
            set(ids["credit_securities"]),
            {c for c in funds if not c.endswith(".OF")}
            | {"150001.SZ", "600018.SH", "T600018.SH"},
        )
        self.assertEqual(credit_identifiers({**inputs, **ids}), ids)
        self.assertEqual(json.dumps(inputs, sort_keys=True), before)
        gaps = credit_extra_prerequisites(inputs, config={"history_start": "19900101"})
        identity = [g for g in gaps if g["reason"] == "opaque_fund_identity_unverified"]
        self.assertEqual(
            {g["api_name"] for g in identity},
            {"margin_detail", "margin_secs", "block_trade"},
        )
        self.assertTrue(all(g["observed_codes"] == 18 for g in identity))
        with self.assertRaises(ValueError):
            credit_identifiers({"stocks": ["1500011.SZ"]})
        for code in ("15000111.SZ", "1500011.US", "T1500011.SZ", "1500011.SZ\n"):
            with self.assertRaises(ValueError):
                credit_identifiers({"funds": [code]})

    def test_legal_offline_requests_recent_first_and_fair_history(self):
        config = {"history_start": "20240227", "planning_epoch": "fixture"}
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            planned = list(jobs(config, date(2024, 3, 12), IDS))
        self.assertEqual(planned, list(jobs(config, date(2024, 3, 12), IDS)))
        self.assertEqual(
            len(planned), len({json.dumps(j, sort_keys=True) for j in planned})
        )
        first = next(i for i, j in enumerate(planned) if j["epoch"] == "history")
        self.assertTrue(
            all(
                j["epoch"] == "fixture" and j["priority"] == 20 for j in planned[:first]
            )
        )
        self.assertTrue(all(j["priority"] == 40 for j in planned[first:]))
        self.assertEqual(
            {j["api_name"] for j in planned[first : first + 7]}, set(CONTRACTS)
        )
        for job in planned:
            api, params = job["api_name"], job["params"]
            self.assertTrue(set(params) <= set(INPUT_FIELDS[api]), job)
            self.assertNotIn("offset", params)
            self.assertNotIn("limit", params)
            if api == "block_trade":
                self.assertEqual(set(params), {"trade_date"})
            if api == "margin_secs":
                self.assertNotIn("exchange_id", params)
            if api == "margin":
                self.assertNotIn("exchange", params)
            if api == "pledge_stat":
                self.assertEqual(len(params), 1)
                self.assertIn(next(iter(params)), ("ts_code", "end_date"))

    def test_date_windows_cover_leap_holidays_and_separate_pledge_axes(self):
        begin, today = date(2024, 2, 27), date(2024, 3, 12)
        planned = list(jobs({"history_start": "20240227"}, today, IDS))
        for api in CONTRACTS.keys() - {"pledge_stat"}:
            observed = []
            for job in planned:
                if job["api_name"] != api:
                    continue
                p = job["params"]
                if "start_date" in p:
                    observed.extend(
                        dates(
                            datetime.strptime(p["start_date"], "%Y%m%d").date(),
                            datetime.strptime(p["end_date"], "%Y%m%d").date(),
                        )
                    )
                else:
                    observed.append(p["trade_date"])
            self.assertEqual(set(observed), dates(begin, today))
            self.assertEqual(len(observed), len(set(observed)))
        self.assertEqual(CONTRACTS["pledge_detail"]["split_axis"], "announcement_date")
        self.assertEqual(CONTRACTS["pledge_stat"]["split_axis"], "cutoff_date")
        self.assertIsNone(CONTRACTS["pledge_stat"]["split"])
        self.assertNotIn("start_date", INPUT_FIELDS["pledge_stat"])
        self.assertIn("release_date", FIELDS["pledge_detail"])
        self.assertIn("Monday", CONTRACTS["margin"]["update_note"])
        self.assertIn("20190910", CONTRACTS["margin_detail"]["field_note"])

    def test_pledge_stock_history_discovery_keeps_t_and_scope_is_explicit(self):
        config = {
            "credit_extra_apis": ["pledge_stat"],
            "credit_extra_history_start": "20260901",
        }
        planned = list(jobs(config, date(2026, 9, 9), IDS))
        self.assertEqual(
            [j["params"] for j in planned if j["epoch"] == "history"],
            [
                {"ts_code": "600018.SH"},
                {"ts_code": "920000.BJ"},
                {"ts_code": "T600018.SH"},
            ],
        )
        self.assertEqual(
            {j["params"]["end_date"] for j in planned if j["epoch"] != "history"},
            dates(date(2026, 9, 3), date(2026, 9, 9)),
        )
        self.assertIn(
            "all supplier history", CONTRACTS["pledge_stat"]["history_strategy"]
        )
        missing = list(jobs(config, date(2026, 9, 9)))
        self.assertTrue(all(j["epoch"] != "history" for j in missing))
        gaps = credit_extra_prerequisites(config=config)
        self.assertTrue(
            any(g["reason"] == "awaiting_stored_security_discovery" for g in gaps)
        )
        self.assertTrue(any(g["reason"] == "saturation_gap" for g in gaps))

    def test_unknown_histories_revisions_and_multiplicity_do_not_disappear(self):
        planned = list(jobs({}, date(2026, 9, 9), IDS))
        self.assertEqual(
            {j["api_name"] for j in planned if j["epoch"] == "history"}, {"pledge_stat"}
        )
        gaps = credit_extra_prerequisites(IDS)
        self.assertEqual(
            {
                g["api_name"]
                for g in gaps
                if g["reason"] == "unknown_history_start_requires_scope_or_discovery"
            },
            set(CONTRACTS),
        )
        self.assertTrue(
            all(not g["universe_complete"] for g in gaps if "universe_complete" in g)
        )
        scoped = credit_extra_prerequisites(IDS, config={"history_start": "19900101"})
        self.assertEqual(
            {
                g["api_name"]
                for g in scoped
                if g["reason"]
                == "configured_scope_does_not_prove_earlier_history_absent"
            },
            set(CONTRACTS),
        )
        self.assertTrue(
            any(
                g["api_name"] == "block_trade" and g["reason"] == "multiplicity_gap"
                for g in scoped
            )
        )
        for api in ("block_trade", "pledge_detail"):
            self.assertTrue(CONTRACTS[api]["preserve_distinct_rows"])
            self.assertIn("_row_identity", CONTRACTS[api]["row_identity_note"])
        self.assertIn("is_release", CONTRACTS["pledge_detail"]["row_identity_note"])

    def test_config_validation_overrides_and_lazy_large_history(self):
        for config, identities in (
            ({"credit_extra_apis": ["daily"]}, IDS),
            ({"credit_extra_apis": "margin"}, IDS),
            ({"credit_extra_history_start": 19900101}, IDS),
            ({"credit_extra_history_start": {"unknown": "19900101"}}, IDS),
            ({"history_start": "20260230"}, IDS),
            ({"history_start": "20990101"}, IDS),
            ({}, {"stocks": ["600018!"]}),
            ({}, {"funds": ["USNVDA"]}),
            ({}, {"funds": "510300.SH"}),
            ({}, {"credit_securities": ["SH600018"]}),
        ):
            with (
                self.subTest(config=config, identities=identities),
                self.assertRaises(ValueError),
            ):
                next(jobs(config, date(2026, 9, 9), identities))
        selected = {
            "credit_extra_apis": ["margin", "margin_detail"],
            "history_start": "20240201",
            "credit_extra_history_start": {"margin": "20240101"},
        }
        planned = list(jobs(selected, date(2024, 3, 12)))
        self.assertEqual(
            min(
                j["params"]["start_date"] for j in planned if j["api_name"] == "margin"
            ),
            "20240101",
        )
        self.assertEqual(
            min(
                j["params"]["trade_date"]
                for j in planned
                if j["api_name"] == "margin_detail"
            ),
            "20240201",
        )
        stream = jobs({"history_start": "10000101"}, date(2026, 9, 9), IDS)
        while (first := next(stream))["epoch"] != "history":
            pass
        self.assertEqual(
            {j["api_name"] for j in [first, *islice(stream, 6)]}, set(CONTRACTS)
        )
        self.assertEqual(
            list(jobs({"credit_extra_apis": []}, date(2026, 9, 9), IDS)), []
        )


if __name__ == "__main__":
    unittest.main()
