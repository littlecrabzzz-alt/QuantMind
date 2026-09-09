"""Offline same-session boundaries, full output and future scope tests."""

from copy import deepcopy
from datetime import date
from itertools import islice
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_realtime_replay_contracts as replay
from backend.shared.tushare_realtime_extra_contracts import REALTIME_EXTRA_CONTRACTS


class RealtimeReplayContracts(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            block = patch(target, side_effect=AssertionError("offline only"))
            block.start()
            self.addCleanup(block.stop)
        self.today = date(2026, 9, 9)
        self.config = {
            "enable_realtime_replay": True,
            "realtime_replay_snapshot_epoch": "20260909T080000Z",
        }
        self.ids = {
            "indexes": ["000001.SH", "399300.SZ"],
            "minute_futures": ["cu2609.SHF", "IF2609.CFX"],
        }

    def jobs(self, ids=None, today=None, **config):
        return list(
            replay.iter_realtime_replay_jobs(
                {**self.config, **config},
                today or self.today,
                self.ids if ids is None else ids,
            )
        )

    def window(self, **changes):
        return {
            "epoch": "snapshot-20260909T080000Z",
            "source_api": "rt_fut_min_daily",
            "current_trade_date": "2026-09-09",
            "previous_trade_date": "2026-09-08",
            "lookback_verified": True,
            "immediate_previous_trading_day_verified": True,
            **changes,
        }

    def test18_full_fields_shared_evidence_and_independent_limits(self):
        self.assertEqual(sum(map(len, replay.FIELDS.values())), 18)
        for api, base in replay.BASE_APIS.items():
            spec = replay.REALTIME_REPLAY_CONTRACTS[api]
            parent = REALTIME_EXTRA_CONTRACTS[base]
            for key in ("fields", "field_metadata", "source_html_sha256", "source_url"):
                self.assertEqual(spec[key], parent[key])
            self.assertEqual(spec["required_fields"], spec["requested_fields"])
            self.assertEqual(spec["fields"], spec["extra_fields"])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertFalse(spec["default_enabled"])
            self.assertFalse(spec["row_cap_verified"])
            self.assertIsNone(spec["documented_row_cap"])
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertIsNone(spec["minimum_points"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["split"])
            self.assertIn("_request_identity", spec["keys"])
            self.assertEqual(spec["date_field"], "time")
        self.assertEqual(replay.INPUT_FIELDS["rt_idx_min_daily"], ["ts_code", "freq"])
        self.assertEqual(
            replay.INPUT_FIELDS["rt_fut_min_daily"], ["ts_code", "freq", "date_str"]
        )
        self.assertEqual(
            replay.REALTIME_REPLAY_CONTRACTS["rt_fut_min_daily"]["source_code_field"],
            "code",
        )
        self.assertEqual(
            REALTIME_EXTRA_CONTRACTS["rt_fut_min"]["allowed_params"],
            ["ts_code", "freq"],
        )

    def test_default_off_and_current_epoch_no_history(self):
        for config in (
            {},
            {"enable_realtime_replay": True},
            {"history_start": "19900101"},
        ):
            self.assertEqual(
                list(replay.iter_realtime_replay_jobs(config, self.today, self.ids)), []
            )
        jobs = self.jobs(
            history_start="19900101", realtime_replay_date_str="1990-01-01"
        )
        self.assertEqual(len(jobs), 20)
        self.assertTrue(all(set(j["params"]) == {"ts_code", "freq"} for j in jobs))
        for epoch in ("20260908T080000Z", "20260910T080000Z", "20260909"):
            with self.assertRaises(ValueError):
                self.jobs(realtime_replay_snapshot_epoch=epoch)
        self.assertEqual(
            len(self.jobs(realtime_replay_snapshot_epoch="20260908T160000Z")), 20
        )

    def test_five_exact_frequency_identities_single_source_and_case(self):
        jobs = self.jobs()
        for api in replay.BASE_APIS:
            self.assertEqual(
                {j["params"]["freq"] for j in jobs if j["api_name"] == api},
                set(replay.FREQUENCIES),
            )
        self.assertTrue(any(j["params"]["ts_code"] == "cu2609.SHF" for j in jobs))
        self.assertTrue(all("," not in j["params"]["ts_code"] for j in jobs))
        self.assertEqual([j["api_name"] for j in jobs[:2]], list(replay.BASE_APIS))
        for bad in ("1min", "1m", "60", 1):
            with self.assertRaises(ValueError):
                self.jobs(realtime_replay_frequencies=[bad])
        with self.assertRaises(ValueError):
            self.jobs(realtime_replay_apis=["rt_idx_min"])
        with self.assertRaises(ValueError):
            self.jobs(realtime_replay_futures_scope="all_history")

    def test_source_namespace_continuous_and_guessed_codes_stay_gap(self):
        ids = {
            "indexes": ["000001.SH", "801001.SI"],
            "minute_futures": ["CU8888.SHF", "CU9999.SHF", "cu2609.SHF", "CU.SHF"],
        }
        jobs = self.jobs(ids)
        self.assertEqual(
            {j["params"]["ts_code"] for j in jobs}, {"000001.SH", "cu2609.SHF"}
        )
        gaps = replay.realtime_replay_prerequisites(ids, config=self.config)
        states = [g for g in gaps if "unsupported_codes" in g]
        self.assertEqual([g["unsupported_codes"] for g in states], [1, 3])
        self.assertEqual(
            replay.REALTIME_REPLAY_CONTRACTS["rt_idx_min_daily"]["target_namespace"],
            "IDX:",
        )
        self.assertEqual(
            replay.REALTIME_REPLAY_CONTRACTS["rt_fut_min_daily"]["target_namespace"],
            "FUT:",
        )

    def test_prior_only_from_same_epoch_per_contract_verified_window(self):
        ids = deepcopy(self.ids)
        ids["realtime_replay_futures_windows"] = {"cu2609.SHF": self.window()}
        before = deepcopy(ids)
        jobs = self.jobs(
            ids, realtime_replay_futures_scope="current_and_verified_previous"
        )
        old = [j for j in jobs if "date_str" in j["params"]]
        self.assertEqual(len(old), 5)
        self.assertEqual({j["params"]["date_str"] for j in old}, {"2026-09-08"})
        self.assertEqual({j["params"]["ts_code"] for j in old}, {"cu2609.SHF"})
        self.assertEqual(ids, before)
        self.assertEqual(self.jobs(ids), self.jobs())
        for change in (
            {"epoch": "snapshot-20260908T080000Z"},
            {"lookback_verified": False},
            {"immediate_previous_trading_day_verified": False},
            {"current_trade_date": "2026-09-10"},
        ):
            ids["realtime_replay_futures_windows"]["cu2609.SHF"] = self.window(**change)
            jobs = self.jobs(
                ids, realtime_replay_futures_scope="current_and_verified_previous"
            )
            self.assertEqual(len(jobs), 20)
            self.assertTrue(all("date_str" not in j["params"] for j in jobs))

    def test_weekend_holiday_leap_boundaries_require_evidence_not_subtraction(self):
        cases = [
            (date(2026, 9, 7), "2026-09-04"),
            (date(2026, 10, 9), "2026-09-30"),
            (date(2024, 3, 1), "2024-02-29"),
        ]
        for today, previous in cases:
            epoch = today.strftime("%Y%m%dT080000Z")
            ids = {
                "minute_futures": ["cu2609.SHF"],
                "realtime_replay_futures_windows": {
                    "cu2609.SHF": self.window(
                        epoch="snapshot-" + epoch,
                        current_trade_date=today.isoformat(),
                        previous_trade_date=previous,
                    )
                },
            }
            jobs = self.jobs(
                ids,
                today=today,
                realtime_replay_apis=["rt_fut_min_daily"],
                realtime_replay_frequencies=["1MIN"],
                realtime_replay_futures_scope="current_and_verified_previous",
                realtime_replay_snapshot_epoch=epoch,
            )
            self.assertEqual(
                [j["params"].get("date_str") for j in jobs], [None, previous]
            )
        for bad in ("2026-09-09", "2026-09-10", "2026-02-30", "20260908"):
            ids = {
                "minute_futures": ["cu2609.SHF"],
                "realtime_replay_futures_windows": {
                    "cu2609.SHF": self.window(previous_trade_date=bad)
                },
            }
            with self.assertRaises(ValueError):
                self.jobs(
                    ids, realtime_replay_futures_scope="current_and_verified_previous"
                )

    def test_lazy_small_take_does_not_remove_remaining_code_frequency_scope(self):
        stream = replay.iter_realtime_replay_jobs(self.config, self.today, self.ids)
        first = list(islice(stream, 3))
        rest = list(stream)
        self.assertEqual(len(first), 3)
        self.assertEqual(first + rest, self.jobs())
        gaps = replay.realtime_replay_prerequisites(
            self.ids,
            config={
                **self.config,
                "realtime_replay_futures_scope": "current_and_verified_previous",
            },
        )
        self.assertIn(
            "awaiting_verified_previous_replay_window", {g["reason"] for g in gaps}
        )
        self.assertIn("field_scope_gap", {g["reason"] for g in gaps})


if __name__ == "__main__":
    unittest.main()
