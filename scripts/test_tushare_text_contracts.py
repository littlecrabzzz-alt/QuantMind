#!/usr/bin/env python3
"""Offline contract and boundary checks; no token, I/O or upstream access."""

import json
from collections import Counter
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_text_contracts import (  # noqa: E402
    MAJOR_NEWS_SOURCES,
    NEWS_SOURCES,
    TEXT_CONTRACTS,
    TEXT_CONTRACT_NOTES,
    iter_text_jobs,
)


class TextPlans(unittest.TestCase):
    def test_sources_recent_first_and_leap_day(self):
        jobs = list(iter_text_jobs({"history_start": "20240228"}, date(2024, 3, 8)))
        recent = [j for j in jobs if j["epoch"] != "history"]
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertEqual(first_history, len(recent))
        news = [j for j in recent if j["api_name"] == "news"]
        self.assertEqual(
            Counter(j["params"]["src"] for j in news), dict.fromkeys(NEWS_SOURCES, 7)
        )
        major = [j for j in recent if j["api_name"] == "major_news"]
        self.assertEqual(
            Counter(j["params"].get("src") for j in major),
            dict.fromkeys((None,) + MAJOR_NEWS_SOURCES, 7),
        )
        leap = [
            j
            for j in jobs
            if j["api_name"] == "news"
            and j["params"]["start_date"] == "2024-02-29 00:00:00"
        ]
        self.assertEqual(len(leap), 9)
        self.assertTrue(
            all(j["params"]["end_date"] == "2024-03-01 00:00:00" for j in leap)
        )
        self.assertEqual(len(jobs), len({json.dumps(j, sort_keys=True) for j in jobs}))

    def test_documented_lower_bounds_and_unknown_prefix(self):
        cfg = {
            "history_start": "20000101",
            "text_apis": ["irm_qa_sh", "monetary_policy", "npr"],
        }
        jobs = list(iter_text_jobs(cfg, "20230602"))
        sh = [
            j
            for j in jobs
            if j["api_name"] == "irm_qa_sh" and "start_date" in j["params"]
        ]
        self.assertEqual(
            [j["params"]["start_date"] for j in sh], ["20230602", "20230601"]
        )
        policy = [j for j in jobs if j["api_name"] == "monetary_policy"]
        self.assertEqual(policy[-1]["params"]["start_date"], "20010101")
        self.assertIn(
            {
                "api_name": "npr",
                "params": {"end_date": "1999-12-31 23:59:59"},
                "priority": 40,
                "epoch": "history",
            },
            jobs,
        )
        self.assertIsNone(TEXT_CONTRACTS["npr"]["history_start"])

    def test_intraday_epoch_and_late_reply_axis(self):
        jobs = list(
            iter_text_jobs(
                {
                    "history_start": "20260901",
                    "text_apis": ["irm_qa_sz"],
                    "planning_epoch": "20260909T1200",
                },
                "20260909",
            )
        )
        recent = [j for j in jobs if j["epoch"] == "20260909T1200"]
        self.assertEqual(len(recent), 14)
        self.assertEqual(sum("pub_start" in j["params"] for j in recent), 7)
        self.assertEqual(sum("start_date" in j["params"] for j in recent), 7)
        self.assertEqual(sum(j["epoch"] == "history" for j in jobs), 2)
        self.assertTrue(all("ann_date" not in j["params"] for j in jobs))

    def test_fields_cover_catalog_and_hidden_example(self):
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_text()
        )
        for api, contract in TEXT_CONTRACTS.items():
            fields = {
                f
                for e in catalog["entries"]
                if api in e.get("api_names", [])
                for f in e["output_fields"]
            }
            self.assertLessEqual(
                fields, set(contract["required_fields"] + contract["extra_fields"])
            )
            self.assertGreater(contract["row_cap"], 0)
            self.assertGreater(contract["requests_per_minute"], 0)
            self.assertIn(api, TEXT_CONTRACT_NOTES)
        self.assertIn("file_name", TEXT_CONTRACTS["research_report"]["extra_fields"])
        self.assertIn("_source", TEXT_CONTRACTS["news"]["keys"])

    def test_bad_config_and_streaming(self):
        for cfg in (
            {},
            {"history_start": "bad"},
            {"history_start": "20260910"},
            {"history_start": "20260901", "text_apis": ["news", "news"]},
            {
                "history_start": "20260901",
                "text_history_starts": {"missing": "20260901"},
            },
        ):
            with self.assertRaises(ValueError):
                list(iter_text_jobs(cfg, "20260909"))
        iterator = iter_text_jobs({"history_start": "19000101"}, "20260909")
        self.assertIs(iter(iterator), iterator)
        self.assertEqual(next(iterator)["priority"], 20)
        self.assertEqual(
            list(
                iter_text_jobs(
                    {"history_start": "19000101", "text_apis": []}, "20260909"
                )
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
