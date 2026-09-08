#!/usr/bin/env python3
"""Offline checks for current-only snapshots and unavailable discovered pages."""

from datetime import date
from itertools import islice
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_discovered_contracts import (  # noqa: E402
    DISCOVERED_CONTRACTS as CONTRACTS,
    DISCOVERED_GAPS,
    INPUT_FIELDS,
    discovered_prerequisites as prerequisites,
    iter_discovered_jobs as jobs,
)


class DiscoveredContracts(unittest.TestCase):
    def setUp(self):
        for target in (
            patch.object(
                socket.socket, "connect", side_effect=AssertionError("No network")
            ),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.today = date(2026, 9, 9)
        self.config = {"discovered_snapshot_epoch": "20260909T010000Z"}

    def test_current_official_contracts_and_missing_pages_are_separate(self):
        self.assertEqual(set(CONTRACTS), {"rt_k", "rt_etf_k"})
        self.assertEqual(set(DISCOVERED_GAPS), {"hk_hold", "dc_concept_cons"})
        # Source output table reviewed 2026-09-09, including default-hidden fields.
        common = set(
            "ts_code name pre_close high open low close vol amount num ask_volume1 bid_volume1 trade_time".split()
        )
        self.assertEqual(set(CONTRACTS["rt_etf_k"]["extra_fields"]), common)
        self.assertEqual(
            set(CONTRACTS["rt_k"]["extra_fields"]),
            common | {"ask_price1", "bid_price1"},
        )
        for spec in CONTRACTS.values():
            self.assertEqual(spec["required_fields"], ["ts_code"])
            self.assertEqual(
                spec["positive_fields"], []
            )  # Idle quotes may be zero/null.
            self.assertIn("trade_time", spec["nullable_fields"])
            self.assertIn("_observation", spec["keys"])
            self.assertNotIn("_observation", spec["extra_fields"])
            self.assertTrue(set(spec["hidden_fields"]) <= set(spec["extra_fields"]))
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertTrue(spec["independent_permission"])
            self.assertFalse(spec["row_cap_verified"])
            self.assertIsNone(spec["split"])
            self.assertIsNone(spec["history_start"])
            self.assertEqual(spec["units"]["vol"], "shares")
        self.assertEqual(CONTRACTS["rt_k"]["documented_row_cap"], 6000)
        self.assertIsNone(CONTRACTS["rt_etf_k"]["documented_row_cap"])

    def test_missing_docs_never_generate_history_or_executable_jobs(self):
        config = dict(self.config, discovered_apis=["hk_hold", "dc_concept_cons"])
        self.assertEqual(list(jobs(config, self.today)), [])
        gaps = prerequisites(config=config)
        self.assertEqual({g["api_name"] for g in gaps}, set(DISCOVERED_GAPS))
        self.assertTrue(all(g["reason"] == "official_document_missing" for g in gaps))
        self.assertTrue(all(g["http_status"] == 200 for g in gaps))

    def test_explicit_current_epoch_and_no_implicit_historical_schedule(self):
        ids = {"stocks": ["600000.SH"]}
        self.assertEqual(list(jobs({}, self.today, ids)), [])
        self.assertIn(
            "explicit_snapshot_epoch_required",
            {g["reason"] for g in prerequisites(ids)},
        )
        first = list(jobs(self.config, self.today, ids))
        self.assertEqual(first, list(jobs(self.config, self.today, ids)))
        second = list(
            jobs(
                dict(self.config, discovered_snapshot_epoch="20260909T010100Z"),
                self.today,
                ids,
            )
        )
        self.assertEqual([j["params"] for j in first], [j["params"] for j in second])
        self.assertNotEqual(first[0]["epoch"], second[0]["epoch"])
        for job in first:
            self.assertEqual(job["priority"], 20)
            self.assertTrue(job["epoch"].startswith("snapshot-"))
            self.assertTrue(set(job["params"]) <= set(INPUT_FIELDS[job["api_name"]]))
            self.assertFalse(
                {
                    "start_date",
                    "end_date",
                    "trade_date",
                    "fields",
                    "_observation",
                    "offset",
                    "limit",
                }
                & job["params"].keys()
            )
        # 16:30 UTC on Sep8 belongs to Sep9 Shanghai, not Sep8.
        self.assertTrue(
            list(
                jobs(
                    dict(self.config, discovered_snapshot_epoch="20260908T163000Z"),
                    self.today,
                    ids,
                )
            )
        )
        for epoch in ("20260908T010000Z", "20260909", "20260909T256100Z"):
            with self.assertRaises(ValueError):
                list(
                    jobs(
                        dict(self.config, discovered_snapshot_epoch=epoch),
                        self.today,
                        ids,
                    )
                )

    def test_stock_batching_retains_opaque_retired_identity_without_duplicates(self):
        stocks = [f"{i:06d}.SH" for i in range(203)]
        stocks += [
            {"ts_code": "T600018.SH", "list_status": "D"},
            "600018.SH",
            "920061.BJ",
            stocks[0],
        ]
        config = dict(self.config, discovered_apis=["rt_k"])
        result = list(jobs(config, self.today, {"stocks": stocks}))
        requests = [j["params"]["ts_code"].split(",") for j in result]
        self.assertEqual([len(r) for r in requests], [100, 100, 6])
        flattened = [c for r in requests for c in r]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertTrue({"T600018.SH", "600018.SH", "920061.BJ"} <= set(flattened))
        gaps = prerequisites({"stocks": stocks}, ["rt_k"], self.config)
        universe = next(
            g for g in gaps if g["reason"] == "stored_discovery_completeness_unverified"
        )
        self.assertEqual(universe["observed_codes"], 206)
        self.assertFalse(universe["universe_complete"])

    def test_etf_documented_wildcards_plus_every_uncovered_identifier(self):
        ids = {
            "etfs": [
                "510300.SH",
                "159919.SZ",
                "T510300.SH",
                "900001.SH",
                "200001.SZ",
                "900001.BJ",
            ]
        }
        result = list(
            jobs(dict(self.config, discovered_apis=["rt_etf_k"]), self.today, ids)
        )
        params = [j["params"] for j in result]
        self.assertEqual(
            params[:2],
            [{"ts_code": "5*.SH", "topic": "HQ_FND_TICK"}, {"ts_code": "1*.SZ"}],
        )
        self.assertEqual(
            {p["ts_code"] for p in params[2:]},
            {"T510300.SH", "900001.SH", "200001.SZ", "900001.BJ"},
        )
        for param in params:
            if param["ts_code"].endswith(".SH"):
                self.assertEqual(param["topic"], "HQ_FND_TICK")
            else:
                self.assertNotIn("topic", param)
        self.assertIn(
            "parameter_gap",
            {g["reason"] for g in prerequisites(ids, ["rt_etf_k"], self.config)},
        )

    def test_stream_interleaving_and_input_validation(self):
        ids = {"stocks": [f"{i:06d}.SH" for i in range(1000)]}
        result = list(islice(jobs(self.config, self.today, ids), 4))
        self.assertEqual(
            [j["api_name"] for j in result], ["rt_k", "rt_etf_k", "rt_k", "rt_etf_k"]
        )
        for config in ({"discovered_apis": "rt_k"}, {"discovered_apis": ["fake"]}):
            with self.assertRaises(ValueError):
                list(jobs(config, self.today))
        for code in (
            "SH.600000",
            "600000",
            "600000.SH,000001.SZ",
            "5*.SH",
            "00013!AE.HK",
        ):
            with self.assertRaises(ValueError):
                list(jobs(self.config, self.today, {"stocks": [code]}))
        with self.assertRaises(ValueError):
            list(jobs(self.config, self.today, {"stocks": "600000.SH"}))


if __name__ == "__main__":
    unittest.main()
