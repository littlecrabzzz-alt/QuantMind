"""Offline scope, full columns, timestamp identities and legal realtime plans."""

from copy import deepcopy
from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_realtime_extra_contracts as rt  # noqa: E402
from backend.shared.tushare_discovered_contracts import DISCOVERED_CONTRACTS  # noqa: E402
from backend.shared.tushare_structured_contracts import _parse  # noqa: E402


class RealtimeContracts(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(
                target, side_effect=AssertionError("No network in pure planning")
            )
            guard.start()
            self.addCleanup(guard.stop)
        self.today = date(2026, 9, 9)
        self.cfg = {
            "enable_realtime_extra": True,
            "realtime_extra_snapshot_epoch": "20260909T010000Z",
        }
        self.ids = {
            "stocks": ["600000.SH", "T000018.SZ"],
            "etfs": ["159103.SZ", "510300.SH"],
            "indexes": ["000001.SH", "399300.SZ"],
            "sw_indexes": ["801001.SI"],
            "minute_futures": ["CU2501.SHF", "a2501.DCE"],
        }

    def jobs(self, apis, **kwargs):
        return list(
            rt.iter_realtime_extra_jobs(
                {**self.cfg, "realtime_extra_apis": apis, **kwargs},
                self.today,
                self.ids,
            )
        )

    def test_all103_columns_hidden8_and_legal_table_scope(self):
        self.assertEqual(sum(map(len, rt.FIELDS.values())), 103)
        self.assertEqual(
            sum(len(s["hidden_fields"]) for s in rt.REALTIME_EXTRA_CONTRACTS.values()),
            8,
        )
        entries = {
            a: e
            for e in json.loads((ROOT / "config/tushare-catalog.json").read_text())[
                "entries"
            ]
            for a in e["api_names"]
        }
        discovered = {
            a: e
            for e in json.loads(
                (ROOT / "config/tushare-coverage-ledger.json").read_text()
            )["discovered_entries"]
            for a in e.get("api_names", [])
        }
        for api, spec in rt.REALTIME_EXTRA_CONTRACTS.items():
            self.assertEqual(spec["fields"], spec["required_fields"])
            self.assertEqual(spec["fields"], spec["requested_fields"])
            self.assertEqual(spec["fields"], spec["extra_fields"])
            self.assertEqual(set(spec["field_gaps"]), set(rt.FIELDS[api]))
            self.assertFalse(spec["default_enabled"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertFalse(spec["row_cap_verified"])
            self.assertEqual(len(spec["source_html_sha256"]), 64)
            self.assertIn("_observation", spec["keys"])
            if api in entries:
                self.assertEqual(rt.FIELDS[api], entries[api]["output_fields"])
                catalog_inputs = entries[api]["input_fields"]
                self.assertEqual(
                    set(catalog_inputs) - set(rt.INPUT_FIELDS[api]),
                    {"date_str"} if api == "rt_fut_min" else set(),
                )
                self.assertTrue(set(rt.INPUT_FIELDS[api]) <= set(catalog_inputs))
            elif api in DISCOVERED_CONTRACTS:
                self.assertEqual(
                    rt.FIELDS[api], DISCOVERED_CONTRACTS[api]["extra_fields"]
                )
            else:
                self.assertIn(api, {"rt_min", "rt_etf_min"})
                self.assertEqual(spec["source_url"], discovered[api]["url"])
                self.assertEqual(
                    spec["source_html_sha256"], discovered[api]["source_sha256"]
                )
                self.assertEqual(len(spec["source_markdown_sha256"]), 64)
                self.assertEqual(
                    spec["requested_fields"], discovered[api]["output_fields"]
                )
        self.assertEqual(rt.INPUT_FIELDS["rt_fut_min"], ["ts_code", "freq"])
        self.assertEqual(rt.FIELD_METADATA["stk_auction"]["price"]["type"], "int")
        self.assertIn(
            "decimals", rt.REALTIME_EXTRA_CONTRACTS["stk_auction"]["type_gap"]
        )
        self.assertNotIn("pct_change", rt.FIELDS["rt_sw_k"])

    def test_reused_contracts_are_not_mutated_or_registered_twice(self):
        for api in ("rt_k", "rt_etf_k"):
            self.assertEqual(DISCOVERED_CONTRACTS[api]["required_fields"], ["ts_code"])
            self.assertIsNot(
                rt.REALTIME_EXTRA_CONTRACTS[api], DISCOVERED_CONTRACTS[api]
            )
            self.assertEqual(
                rt.REALTIME_EXTRA_CONTRACTS[api]["hidden_fields"],
                DISCOVERED_CONTRACTS[api]["hidden_fields"],
            )

    def test_default_off_no_epoch_no_realtime_backfill(self):
        self.assertEqual(
            list(
                rt.iter_realtime_extra_jobs(
                    {"history_start": "19900101"}, self.today, self.ids
                )
            ),
            [],
        )
        apis = [a for a in rt.FIELDS if a != "stk_auction"]
        self.assertEqual(
            self.jobs(
                apis, realtime_extra_snapshot_epoch=None, history_start="19900101"
            ),
            [],
        )
        rows = self.jobs(apis, history_start="19900101")
        self.assertEqual({j["api_name"] for j in rows}, set(apis))
        for job in rows:
            self.assertTrue(job["epoch"].startswith("snapshot-"))
            self.assertFalse(
                {
                    "date",
                    "date_str",
                    "trade_date",
                    "start_date",
                    "end_date",
                    "limit",
                    "offset",
                }
                & job["params"].keys()
            )
            self.assertEqual(job["fields"].split(","), rt.FIELDS[job["api_name"]])

    def test_each_source_code_all5_frequencies_distinct_request_identity(self):
        rows = self.jobs(list(rt.MINUTE_APIS))
        self.assertEqual(len(rows), 40)
        for api in rt.MINUTE_APIS:
            calls = [j for j in rows if j["api_name"] == api]
            self.assertEqual(
                len({(j["params"]["ts_code"], j["params"]["freq"]) for j in calls}), 10
            )
            self.assertEqual({j["params"]["freq"] for j in calls}, set(rt.FREQUENCIES))
            self.assertEqual(
                rt.REALTIME_EXTRA_CONTRACTS[api]["request_identity_fields"], ["freq"]
            )
            self.assertIn("_request_identity", rt.REALTIME_EXTRA_CONTRACTS[api]["keys"])
        self.assertIn("code", rt.FIELDS["rt_fut_min"])
        self.assertNotIn("ts_code", rt.FIELDS["rt_fut_min"])
        self.assertNotIn("freq", rt.FIELDS["rt_idx_min"])

    def test_epochs_rollover_and_wrong_day_rejected(self):
        first = self.jobs(["rt_k"])
        later = self.jobs(["rt_k"], realtime_extra_snapshot_epoch="20260909T010100Z")
        self.assertEqual([j["params"] for j in first], [j["params"] for j in later])
        self.assertNotEqual(first[0]["epoch"], later[0]["epoch"])
        for epoch in (
            "20260908T010000Z",
            "20260909T170000Z",
            "20260909T010000",
            "20260230T010000Z",
        ):
            with self.assertRaises(ValueError):
                self.jobs(["rt_idx_k"], realtime_extra_snapshot_epoch=epoch)
        # UTC September8 16:00 is the current Shanghai calendar day.
        self.assertTrue(
            self.jobs(["rt_idx_k"], realtime_extra_snapshot_epoch="20260908T160000Z")
        )

    def test_namespace_discovery_no_stock_fanout_into_other_markets(self):
        ids = deepcopy(self.ids)
        ids["indexes"] += ["801001.SI", "SPX.USA"]
        ids["minute_futures"] += ["CU2501.SHF", "CU.SHF", "CUL.SHF", "IF8888.CFX"]
        before = deepcopy(ids)
        config = {**self.cfg, "realtime_extra_apis": ["rt_idx_min", "rt_fut_min"]}
        rows = list(rt.iter_realtime_extra_jobs(config, self.today, ids))
        codes = {j["params"]["ts_code"] for j in rows}
        self.assertFalse(
            {"600000.SH", "801001.SI", "SPX.USA", "CU.SHF", "CUL.SHF", "IF8888.CFX"}
            & codes
        )
        self.assertEqual(ids, before)
        gaps = rt.realtime_extra_prerequisites(ids, config=config)
        unsupported = {c for g in gaps for c in g.get("unsupported_source_codes", [])}
        self.assertTrue(
            {"801001.SI", "SPX.USA", "CU.SHF", "CUL.SHF", "IF8888.CFX"} <= unsupported
        )
        self.assertEqual(
            rt.REALTIME_EXTRA_CONTRACTS["rt_etf_k"]["target_namespace"], "FUND:"
        )

    def test_optional_whole_market_and_existing_etf_topic_requests(self):
        rows = self.jobs(["rt_etf_sz_iopv", "rt_sw_k", "rt_etf_k"])
        by_api = {
            api: [j["params"] for j in rows if j["api_name"] == api]
            for api in ("rt_etf_sz_iopv", "rt_sw_k", "rt_etf_k")
        }
        self.assertEqual(by_api["rt_etf_sz_iopv"], [{}])
        self.assertEqual(by_api["rt_sw_k"], [{}])
        self.assertEqual(
            by_api["rt_etf_k"],
            [{"ts_code": "5*.SH", "topic": "HQ_FND_TICK"}, {"ts_code": "1*.SZ"}],
        )
        self.assertIn("parameter_gap", rt.REALTIME_EXTRA_CONTRACTS["rt_etf_k"])

    def test_auction_history_is_real_exception_with_three_variants(self):
        rows = self.jobs(["stk_auction"], realtime_extra_history_start="20250227")
        recent = [j for j in rows if j["epoch"] != "history"]
        history = [j for j in rows if j["epoch"] == "history"]
        self.assertEqual(len(recent), 21)
        self.assertEqual(
            history[0]["params"], {"start_date": "20250227", "end_date": "20250228"}
        )
        for i in range(0, len(history), 3):
            self.assertEqual(
                [j["params"].get("ts_type") for j in history[i : i + 3]],
                [None, "STK", "ETF"],
            )
        self.assertEqual(history[-1]["params"]["end_date"], "20260902")
        days = []
        for job in history[::3]:
            lo, hi = (_parse(job["params"][k]) for k in ("start_date", "end_date"))
            days.extend(lo + timedelta(days=n) for n in range((hi - lo).days + 1))
        days.extend(_parse(j["params"]["trade_date"]) for j in recent[::3])
        self.assertEqual(
            sorted(days),
            [
                date(2025, 2, 27) + timedelta(days=n)
                for n in range((self.today - date(2025, 2, 27)).days + 1)
            ],
        )
        self.assertEqual(len(days), len(set(days)))

    def test_leap_month_explicit_earlier_request_scope_is_not_removed(self):
        rows = list(
            rt.iter_realtime_extra_jobs(
                {
                    "enable_realtime_extra": True,
                    "realtime_extra_apis": ["stk_auction"],
                    "history_start": "20240228",
                },
                date(2024, 3, 10),
            )
        )
        history = [j for j in rows if j["epoch"] == "history"]
        self.assertEqual(history[0]["params"]["end_date"], "20240229")
        self.assertEqual(history[0]["params"]["start_date"], "20240228")
        self.assertFalse(
            rt.REALTIME_EXTRA_CONTRACTS["stk_auction"]["history_bound_verified"]
        )

    def test_validation_gaps_and_adjacent_apis_remain_explicit(self):
        gaps = rt.realtime_extra_prerequisites(
            {}, config={"enable_realtime_extra": True}
        )
        self.assertEqual({g["api_name"] for g in gaps}, set(rt.FIELDS))
        self.assertTrue(
            any(g["reason"] == "explicit_current_snapshot_epoch_required" for g in gaps)
        )
        self.assertTrue(any(g["reason"] == "catalog_gap" for g in gaps))
        self.assertEqual(
            set(rt.ADJACENT_API_OBLIGATIONS), {"rt_idx_min_daily", "rt_fut_min_daily"}
        )
        self.assertNotIn("date_str", rt.INPUT_FIELDS["rt_fut_min"])
        self.assertIn(
            "date_str",
            rt.ADJACENT_API_OBLIGATIONS["rt_fut_min_daily"]["allowed_params"],
        )
        for bad in (
            {"realtime_extra_apis": ["rt_idx_min_daily"]},
            {"realtime_extra_frequencies": ["1min"]},
            {"enable_realtime_extra": "true"},
            {"realtime_extra_apis": [{}]},
        ):
            with self.assertRaises(ValueError):
                list(
                    rt.iter_realtime_extra_jobs(
                        {**self.cfg, **bad}, self.today, self.ids
                    )
                )

    def test_invalid_auction_scope_fails_before_any_sibling_snapshot(self):
        jobs = rt.iter_realtime_extra_jobs(
            {**self.cfg, "realtime_extra_history_start": "20270101"},
            self.today,
            self.ids,
        )
        with self.assertRaises(ValueError):
            next(jobs)

    def test_lazy_snapshot_batches_and_idempotent_parameters(self):
        ids = {"stocks": [f"{n:06d}.SH" for n in range(10000)]}
        config = {**self.cfg, "realtime_extra_apis": ["rt_k"]}
        head = list(islice(rt.iter_realtime_extra_jobs(config, self.today, ids), 2))
        self.assertEqual(len(head), 2)
        self.assertEqual(len(head[0]["params"]["ts_code"].split(",")), 100)
        self.assertEqual(
            head, list(islice(rt.iter_realtime_extra_jobs(config, self.today, ids), 2))
        )


if __name__ == "__main__":
    unittest.main()
