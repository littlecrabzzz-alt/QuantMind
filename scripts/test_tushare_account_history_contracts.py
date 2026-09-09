"""Offline full-schema and boundary checks for stopped account-history contracts."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_account_history_contracts as account
from backend.shared.tushare_structured_contracts import _parse


class AccountHistoryContracts(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            mock = patch(target, side_effect=AssertionError("offline only"))
            mock.start()
            self.addCleanup(mock.stop)
        self.today = date(2026, 9, 9)

    def jobs(self, config, today=None):
        return list(
            account.iter_account_history_jobs(
                {"enable_account_history": True, **config}, today or self.today
            )
        )

    def test_disabled_without_explicit_enable(self):
        for config in (
            {},
            {"history_start": "19900101"},
            {"enable_account_history": False, "history_start": "19900101"},
        ):
            self.assertEqual(
                list(account.iter_account_history_jobs(config, self.today)), []
            )

    def test_complete14_fields_legal_inputs_and_nulls(self):
        entries = {
            api: entry
            for entry in json.loads((ROOT / "config/tushare-catalog.json").read_text())[
                "entries"
            ]
            for api in entry["api_names"]
        }
        self.assertEqual(sum(map(len, account.FIELDS.values())), 14)
        for api, spec in account.ACCOUNT_HISTORY_CONTRACTS.items():
            self.assertEqual(account.FIELDS[api], entries[api]["output_fields"])
            self.assertEqual(account.INPUT_FIELDS[api], entries[api]["input_fields"])
            self.assertEqual(spec["requested_fields"], spec["required_fields"])
            self.assertEqual(spec["extra_fields"], account.FIELDS[api])
            self.assertEqual(spec["nullable_fields"], account.FIELDS[api][1:])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertFalse(spec["default_enabled"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["documented_row_cap"])
            self.assertFalse(spec["row_cap_verified"])
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertEqual(len(spec["source_html_sha256"]), 64)
        old = account.ACCOUNT_HISTORY_CONTRACTS["stk_account_old"]
        self.assertNotIn("date", old["allowed_params"])
        self.assertIsNone(old["date_field"])
        self.assertIn("户", old["field_metadata"]["new_sh"]["description"])
        self.assertIn("万户", old["field_metadata"]["trade_sz"]["description"])

    def test_projection_crossyear_holiday_and_leap_preserves_raw(self):
        row = {"date": "20141229~0102", "trade_sh": None, "new_unknown": "opaque"}
        before = dict(row)
        self.assertEqual(
            account.project_account_period(row["date"]), ("20141229", "20150102")
        )
        self.assertEqual(row, before)
        for value, expected in (
            ("20141008~1010", ("20141008", "20141010")),
            ("20140929~1003", ("20140929", "20141003")),
            ("20140909~0912", ("20140909", "20140912")),
            ("20120227~0302", ("20120227", "20120302")),
            ("20120229~0302", ("20120229", "20120302")),
        ):
            self.assertEqual(account.project_account_period(value), expected)

    def test_unknown_impossible_and_overlong_periods_not_guessed(self):
        for value in (
            None,
            "",
            "20141229",
            "20141229~20150102",
            "20140229~0301",
            "20141229~0132",
            "20141229~0108",
            "20140620~0619",
            "20150227~0229",
            "20150101~1231",
            "20141229~0102 ",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                account.project_account_period(value)

    def test_month_windows_continuous_clipped_and_leapday(self):
        jobs = self.jobs(
            {"history_start": "20120227", "account_history_apis": ["stk_account"]},
            date(2012, 3, 2),
        )
        self.assertEqual(
            [j["params"] for j in jobs],
            [
                {"start_date": "20120227", "end_date": "20120229"},
                {"start_date": "20120301", "end_date": "20120302"},
            ],
        )
        days = []
        for job in jobs:
            first, last = (_parse(job["params"][k]) for k in ("start_date", "end_date"))
            days.extend(
                first + timedelta(days=i) for i in range((last - first).days + 1)
            )
            self.assertEqual(job["epoch"], "history")
            self.assertEqual(job["fields"].split(","), account.FIELDS[job["api_name"]])
        self.assertEqual(
            days, [date(2012, 2, 27) + timedelta(days=i) for i in range(5)]
        )

    def test_legacy_end_does_not_fake_new_boundary(self):
        jobs = self.jobs({"history_start": "20150501"}, date(2015, 6, 2))
        old = [j for j in jobs if j["api_name"] == "stk_account_old"]
        new = [j for j in jobs if j["api_name"] == "stk_account"]
        self.assertEqual(
            old[0]["params"], {"start_date": "20150501", "end_date": "20150529"}
        )
        self.assertEqual(new[0]["params"]["start_date"], "20150501")
        self.assertEqual(new[-1]["params"]["end_date"], "20150602")
        self.assertTrue(
            all(set(j["params"]) == {"start_date", "end_date"} for j in jobs)
        )
        self.assertEqual(
            self.jobs(
                {
                    "history_start": "20150530",
                    "account_history_apis": ["stk_account_old"],
                }
            ),
            [],
        )

    def test_no_invented_history_and_all_material_gaps_remain(self):
        self.assertEqual(self.jobs({}), [])
        gaps = account.account_history_prerequisites(config={})
        for api in account.FIELDS:
            reasons = {g["reason"] for g in gaps if g["api_name"] == api}
            self.assertTrue(
                {
                    "unknown_history_start_requires_scope",
                    "history_gap",
                    "permission_gap",
                    "boundary_gap",
                    "pit_gap",
                    "saturation_gap",
                    "date_gap",
                }
                <= reasons
            )
        scoped = account.account_history_prerequisites(
            config={"history_start": "19900101"}
        )
        self.assertTrue(
            any(g["reason"] == "configured_scope_not_verified_complete" for g in scoped)
        )
        self.assertTrue(any(g["reason"] == "projection_gap" for g in scoped))

    def test_scope_mapping_empty_selection_and_validation(self):
        jobs = self.jobs(
            {
                "history_start": "20150101",
                "account_history_history_start": {"stk_account": "20150402"},
            },
            date(2015, 5, 1),
        )
        self.assertEqual(
            [j["params"]["start_date"] for j in jobs[:2]], ["20150402", "20150101"]
        )
        self.assertEqual(self.jobs({"account_history_apis": []}), [])
        for config in (
            {"account_history_apis": "stk_account"},
            {"account_history_apis": ["bad"]},
            {"account_history_history_start": {"bad": "20150101"}},
            {"history_start": "2015-01-01"},
            {"history_start": "20270909"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.jobs(config)

    def test_lazy_roundrobin_and_stable_identity(self):
        config = {"enable_account_history": True, "history_start": "19900101"}
        with patch.object(account, "_months", wraps=account._months) as monthly:
            iterator = account.iter_account_history_jobs(config, self.today)
            self.assertEqual(monthly.call_count, 0)
            head = list(islice(iterator, 4))
            self.assertEqual(monthly.call_count, 2)
        self.assertEqual(
            [j["api_name"] for j in head], ["stk_account", "stk_account_old"] * 2
        )
        self.assertEqual(
            head, list(islice(account.iter_account_history_jobs(config, self.today), 4))
        )
        self.assertEqual(
            config, {"enable_account_history": True, "history_start": "19900101"}
        )


if __name__ == "__main__":
    unittest.main()
