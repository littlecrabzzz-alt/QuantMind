"""Offline historical-minute identity, scope and date-boundary contracts."""

from datetime import date, datetime, timedelta, timezone
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_history_minutes_contracts import (
    HISTORY_MINUTES_CONTRACTS as CONTRACTS,
    FIELDS,
    FIELD_METADATA,
    INPUT_FIELDS,
    FREQUENCIES,
    TIME_FORMAT,
    history_minutes_prerequisites,
    iter_history_minutes_jobs,
)


class HistoryMinutesContracts(unittest.TestCase):
    def setUp(self):
        for name in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(
                name, side_effect=AssertionError("no network in pure planning")
            )
            guard.start()
            self.addCleanup(guard.stop)
        self.today = date(2026, 9, 9)
        self.ids = {
            "minute_stocks": [
                {"ts_code": "T600001.SH", "list_status": "D"},
                "600001.SH",
            ],
            "minute_etfs": ["510300.SH"],
            "minute_indexes": ["000001.SH"],
            "minute_sw_indexes": [{"index_code": "801003.SI", "level": "L1"}],
            "minute_futures": ["cu2301.SHF"],
            "minute_options": ["IO2609-C-4000.CFX", "10007976.SH"],
            "minute_hk_stocks": ["00013!.HK", "00013!CLP.HK", "00013.HK"],
        }

    def test_all58_columns_exact_catalog_schema_and_request_frequency_identity(self):
        entries = {
            a: e
            for e in json.loads((ROOT / "config/tushare-catalog.json").read_text())[
                "entries"
            ]
            for a in e["api_names"]
        }
        self.assertEqual(sum(map(len, FIELDS.values())), 58)
        for api, spec in CONTRACTS.items():
            self.assertEqual(FIELDS[api], entries[api]["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entries[api]["input_fields"])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertEqual(spec["request_identity_fields"], ["freq"])
            self.assertEqual(spec["keys"], ["ts_code", "trade_time"])
            self.assertEqual(spec["field_metadata"], FIELD_METADATA[api])
            self.assertNotIn("freq", FIELDS[api])
            self.assertEqual(set(spec["field_gaps"]), set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["history_start"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertEqual(spec["split"]["precision"], "second")
        self.assertEqual(FIELDS["sw_mins"][-2:], ["amount", "vol"])
        self.assertEqual(FIELD_METADATA["sw_mins"]["vol"]["type"], "float")
        self.assertEqual(
            {a for a in FIELDS if "oi" in FIELDS[a]}, {"ft_mins", "opt_mins"}
        )

    def test_five_real_frequencies_per_source_and_no_current_day_polling(self):
        jobs = list(iter_history_minutes_jobs({}, self.today, self.ids))
        expected = sum(len(v) for v in self.ids.values()) * 5 * 7
        self.assertEqual(len(jobs), expected)
        for api in CONTRACTS:
            group = [j for j in jobs if j["api_name"] == api]
            self.assertEqual({j["params"]["freq"] for j in group}, set(FREQUENCIES))
            self.assertEqual({j["fields"] for j in group}, {",".join(FIELDS[api])})
        end = datetime(2026, 9, 9)
        for job in jobs:
            p = job["params"]
            self.assertEqual(set(p), {"ts_code", "freq", "start_date", "end_date"})
            a, b = (
                datetime.strptime(p[k], TIME_FORMAT) for k in ("start_date", "end_date")
            )
            self.assertLess(a, end)
            self.assertLessEqual(b, end)
            self.assertEqual(b - a, timedelta(days=1))
            self.assertNotEqual(job["epoch"], "history")
        self.assertEqual([j["api_name"] for j in jobs[:7]], list(CONTRACTS))

    def test_leap_midnight_and_partial_start_have_shared_continuous_boundaries(self):
        cfg = {
            "history_minutes_apis": ["ft_mins"],
            "history_minutes_history_start": "2024-02-27 21:15:00",
            "history_minutes_frequencies": ["1min"],
        }
        jobs = list(iter_history_minutes_jobs(cfg, date(2024, 3, 7), self.ids))
        windows = sorted(
            (
                datetime.strptime(j["params"]["start_date"], TIME_FORMAT),
                datetime.strptime(j["params"]["end_date"], TIME_FORMAT),
            )
            for j in jobs
        )
        self.assertEqual(windows[0][0], datetime(2024, 2, 27, 21, 15))
        self.assertEqual(windows[-1][1], datetime(2024, 3, 7))
        for (_, last), (first, _) in zip(windows, windows[1:], strict=False):
            self.assertEqual(last, first)
        self.assertIn((datetime(2024, 2, 29), datetime(2024, 3, 1)), windows)
        self.assertEqual(len(set(windows)), len(windows))
        self.assertEqual(
            sum((b - a for a, b in windows), timedelta()),
            datetime(2024, 3, 7) - datetime(2024, 2, 27, 21, 15),
        )
        self.assertEqual(
            [j["epoch"] == "history" for j in jobs],
            sorted(j["epoch"] == "history" for j in jobs),
        )
        # Overnight intervals are retained whole; no stock-session/end-of-day guess.
        self.assertTrue(
            any(j["params"]["start_date"].endswith("00:00:00") for j in jobs)
        )

    def test_source_assets_expired_t_hk_reuse_option_hyphens_preserved(self):
        jobs = list(
            iter_history_minutes_jobs(
                {"history_start": "20260908"}, self.today, self.ids
            )
        )
        expected = {
            "stk_mins": {"T600001.SH", "600001.SH"},
            "etf_mins": {"510300.SH"},
            "idx_mins": {"000001.SH"},
            "sw_mins": {"801003.SI"},
            "ft_mins": {"cu2301.SHF"},
            "opt_mins": {"IO2609-C-4000.CFX", "10007976.SH"},
            "hk_mins": {"00013!.HK", "00013!CLP.HK", "00013.HK"},
        }
        for api, codes in expected.items():
            self.assertEqual(
                {j["params"]["ts_code"] for j in jobs if j["api_name"] == api}, codes
            )
        self.assertEqual(
            len({spec["source_namespace"] for spec in CONTRACTS.values()}), 7
        )
        self.assertEqual(
            list(iter_history_minutes_jobs({}, self.today, {"stocks": ["600001.SH"]})),
            [],
        )

    def test_permission_history_and_sw_cap_discrepancy_never_disappear(self):
        gaps = history_minutes_prerequisites(
            self.ids, config={"history_start": "19900101"}
        )
        reasons = {g["reason"] for g in gaps}
        self.assertTrue(
            {
                "permission_gap",
                "configured_scope_not_verified_complete",
                "time_gap",
                "saturation_gap",
                "pit_gap",
                "cap_conflict_gap",
            }
            <= reasons
        )
        self.assertEqual(CONTRACTS["sw_mins"]["row_cap"], 5000)
        self.assertEqual(
            {s["row_cap"] for a, s in CONTRACTS.items() if a != "sw_mins"}, {8000}
        )
        self.assertEqual(CONTRACTS["hk_mins"]["documented_trial_requests"], 2)
        self.assertTrue(all(s["independent_permission"] for s in CONTRACTS.values()))
        missing = history_minutes_prerequisites()
        self.assertEqual(
            sum(g["reason"] == "missing_source_identifiers" for g in missing), 7
        )
        self.assertTrue(
            all(not g["universe_complete"] for g in missing if "universe_complete" in g)
        )

    def test_frequency_subset_is_explicit_and_unknown_values_rejected(self):
        cfg = {"history_minutes_frequencies": ["5min", "5min", "60min"]}
        jobs = list(iter_history_minutes_jobs(cfg, self.today, self.ids))
        self.assertEqual({j["params"]["freq"] for j in jobs}, {"5min", "60min"})
        gaps = history_minutes_prerequisites(self.ids, config=cfg)
        selected = [g for g in gaps if g["reason"] == "frequency_subset_scope"]
        self.assertEqual(len(selected), 7)
        self.assertTrue(
            all(g["excluded"] == ["1min", "15min", "30min"] for g in selected)
        )
        for invalid in (["1MIN"], ["2min"], "1min", [1]):
            with self.assertRaises(ValueError):
                list(
                    iter_history_minutes_jobs(
                        {"history_minutes_frequencies": invalid}, self.today, self.ids
                    )
                )

    def test_scope_rejects_future_timezone_and_bad_identifiers_without_guessing(self):
        for start in (
            "2026-09-09 00:00:01",
            "20260910",
            "2026-09-01T00:00:00Z",
            "2026-09-01 00:00:00+08:00",
            "20260230",
        ):
            with self.assertRaises(ValueError):
                list(
                    iter_history_minutes_jobs(
                        {"history_minutes_history_start": start}, self.today, self.ids
                    )
                )
        with self.assertRaises(ValueError):
            list(iter_history_minutes_jobs({}, datetime.now(timezone.utc), self.ids))
        with self.assertRaises(ValueError):
            list(
                iter_history_minutes_jobs(
                    {}, self.today, {"minute_stocks": ["600001.SH,600002.SH"]}
                )
            )
        self.assertEqual(
            list(
                iter_history_minutes_jobs(
                    {"history_start": "20260909"}, self.today, self.ids
                )
            ),
            [],
        )
        self.assertEqual(
            list(
                iter_history_minutes_jobs(
                    {"history_minutes_apis": []}, self.today, self.ids
                )
            ),
            [],
        )

    def test_lazy_decade_scope_determinism_and_per_api_start(self):
        cfg = {
            "history_minutes_apis": ["hk_mins"],
            "history_minutes_frequencies": ["1min"],
            "history_start": "19900101",
            "planning_epoch": "stable",
        }
        jobs = list(islice(iter_history_minutes_jobs(cfg, self.today, self.ids), 22))
        self.assertEqual(jobs[-1]["epoch"], "history")
        self.assertEqual(jobs[-1]["params"]["start_date"], "1990-01-01 00:00:00")
        self.assertEqual(
            jobs, list(islice(iter_history_minutes_jobs(cfg, self.today, self.ids), 22))
        )
        cfg = {
            "history_minutes_apis": ["etf_mins"],
            "history_minutes_history_start": {"etf_mins": "2026-09-08 12:34:56"},
        }
        jobs = list(iter_history_minutes_jobs(cfg, self.today, self.ids))
        self.assertEqual(len(jobs), 5)
        self.assertTrue(
            all(j["params"]["start_date"] == "2026-09-08 12:34:56" for j in jobs)
        )


if __name__ == "__main__":
    unittest.main()
