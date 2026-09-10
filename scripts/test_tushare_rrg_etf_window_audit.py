"""Pinned ETF-window audit preserves gaps and inactive PIT-dependent plans."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_tushare_rrg_etf_window as module


class EtfWindowAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "mirror"
        self.output = self.base / "output"
        self.release = "data-" + "a" * 64
        self.values = {
            "trade_cal": [
                {"exchange": "SSE", "cal_date": "20260130", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260131", "is_open": 0},
                {"exchange": "SSE", "cal_date": "20260201", "is_open": 0},
                {"exchange": "SSE", "cal_date": "20260202", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260203", "is_open": 1},
            ],
            "ci_index_member": [
                {
                    "l1_code": "CI005001",
                    "ts_code": "SH600001",
                    "source_ts_code": "600001.SH",
                    "source_l1_code": "CI005001.CI",
                    "in_date": "20200101",
                    "out_date": None,
                    "_observation": "member.json",
                }
            ],
            "etf_basic": [
                {
                    "ts_code": "SH510001",
                    "source_ts_code": "510001.SH",
                    "exchange": "SH",
                    "list_date": "20200101",
                    "list_status": "L",
                    "_observation": "listed.json",
                },
                {
                    "ts_code": "SZ159999",
                    "source_ts_code": "159999.SZ",
                    "exchange": "SZ",
                    "list_date": None,
                    "list_status": "P",
                    "_observation": "unknown.json",
                },
            ],
            "fund_basic": [
                {"ts_code": "SH510001", "list_date": "20200101", "delist_date": None},
                {"ts_code": "SZ159999", "list_date": None, "delist_date": None},
            ],
            "fund_daily": [
                {"trade_date": "20260130", "ts_code": "SH510001", "open": 1.0, "close": 1.1, "vol": 1.0, "amount": 1.0},
                {"trade_date": "20260203", "ts_code": "SH510001", "open": 1.1, "close": 1.2, "vol": 1.0, "amount": 1.0},
            ],
            "fund_adj": [
                {"trade_date": day, "ts_code": "SH510001", "adj_factor": 1.0}
                for day in ("20260130", "20260202", "20260203")
            ],
            "fund_div": [
                {"ts_code": "SH510001", "ann_date": "20250101", "ex_date": None, "pay_date": None, "div_proc": None}
            ],
            "etf_limit": [
                {
                    "trade_date": "20260202",
                    "ts_code": "FUND:510001.SH",
                    "source_ts_code": "510001.SH",
                    "up_limit": 1.2,
                    "down_limit": 0.8,
                }
            ],
            "etf_sh_cons": [
                {"trade_date": "20260202", "ts_code": "SH510001", "con_code": "600000.SH", "exchange": "SH"}
            ],
            "etf_sz_cons": [],
        }
        self.gaps = [
            {
                "id": "receipt",
                "api_name": "fund_div",
                "params": {"ts_code": "510001.SH"},
                "state": "empty",
                "assessment": "empty_unverified",
            }
        ]

    def invoke(self, **overrides):
        def reader(root, release_id, api, **params):
            return pa.Table.from_pylist(self.values[api]).replace_schema_metadata(
                {b"tushare": json.dumps({"release_id": release_id, "upstream_calls": 0}).encode()}
            )

        args = {
            "root": self.root,
            "release_id": self.release,
            "start_date": "20260130",
            "end_date": "20260203",
            "output": self.output,
        }
        args.update(overrides)
        manifest = {
            "datasets": [{"api_name": api} for api in self.values],
            "gaps": self.gaps,
        }
        with (
            patch.object(module, "manifest_at", return_value=manifest),
            patch.object(module, "read_dataset", side_effect=reader),
        ):
            return module.audit(**args)

    def test_reports_exact_missingness_without_filling_or_enabling_pcf(self):
        report = self.invoke()
        self.assertEqual(report["status"], "blocked_data")
        self.assertEqual(report["membership"]["rows"], 1)
        self.assertEqual(report["membership"]["known_at_rows"], 0)
        self.assertFalse(report["membership"]["revision_publication_evidence_verified"])
        self.assertEqual(report["universe"]["known_lifecycle_codes"], 1)
        self.assertEqual(report["universe"]["unknown_list_date_codes"], ["SZ159999"])
        self.assertEqual(report["coverage"]["expected_lifecycle_session_pairs"], 3)
        self.assertEqual(report["coverage"]["fund_daily_missing_pairs"], 1)
        self.assertEqual(report["coverage"]["fund_adj_lifecycle_missing_pairs"], 0)
        self.assertEqual(report["coverage"]["fund_adj_missing_for_price_pairs"], 0)
        self.assertEqual(report["coverage"]["joined_valid_price_factor_pairs"], 2)
        self.assertEqual(report["coverage"]["monthly_execution_expected_pairs"], 1)
        self.assertEqual(report["coverage"]["monthly_execution_valid_price_factor_pairs"], 0)
        self.assertEqual(report["coverage"]["etf_limit_observed_code_day_pairs"], 1)
        self.assertEqual(report["coverage"]["etf_limit_code_day_pairs"], 1)
        self.assertEqual(report["coverage"]["etf_limit_monthly_execution_pairs"], 1)
        self.assertEqual(report["coverage"]["pcf_monthly_execution_pairs"], 1)
        self.assertTrue(
            report["coverage"]["fund_div_empty_receipts_available_in_fixed_release"]
        )
        self.assertEqual(report["coverage"]["fund_div_empty_receipt_codes"], 1)
        self.assertEqual(report["coverage"]["fund_div_terminal_receipt_codes"], 1)
        self.assertEqual(report["coverage"]["fund_div_missing_terminal_receipt_codes"], 0)
        missing = [json.loads(line) for line in (self.output / "missing-observations.jsonl").read_text().splitlines()]
        self.assertEqual(missing[0]["ranges"], [{"start_date": "20260202", "end_date": "20260202"}])
        plans = [json.loads(line) for line in (self.output / "collection-plan.jsonl").read_text().splitlines()]
        pcf = [row for row in plans if row["api_name"] == "etf_sh_cons"]
        self.assertEqual(pcf[0]["gate"], "blocked_until_authoritative_etf_mapping")
        self.assertFalse(any(row["api_name"] == "fund_div" for row in plans))
        self.assertFalse(report["universe"]["industry_mapping_verified"])
        self.assertTrue((self.output / "manifest.json").is_file())

    def test_rejects_calendar_gaps_conflicts_and_protected_outputs(self):
        self.values["trade_cal"].pop(1)
        with self.assertRaisesRegex(ValueError, "Missing natural-day"):
            self.invoke()
        self.values["trade_cal"].insert(1, {"exchange": "SSE", "cal_date": "20260131", "is_open": 0})
        self.values["trade_cal"].append({"exchange": "SSE", "cal_date": "20260202", "is_open": 0})
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.invoke()
        with self.assertRaisesRegex(ValueError, "Output must be new"):
            module.audit(self.root, self.release, "20260130", "20260203", self.root / "bad")

    def test_rejects_mismatched_etf_limit_namespace_and_plans_missing_receipt(self):
        self.values["etf_limit"][0]["ts_code"] = "SH510001"
        with self.assertRaisesRegex(ValueError, "ETF limit source namespace"):
            self.invoke()

        self.values["etf_limit"][0]["ts_code"] = "FUND:510001.SH"
        self.gaps = []
        self.values["fund_div"] = []
        report = self.invoke()
        self.assertFalse(
            report["coverage"]["fund_div_empty_receipts_available_in_fixed_release"]
        )
        self.assertEqual(report["coverage"]["fund_div_missing_terminal_receipt_codes"], 1)
        plans = [
            json.loads(line)
            for line in (self.output / "collection-plan.jsonl").read_text().splitlines()
        ]
        self.assertEqual(sum(row["api_name"] == "fund_div" for row in plans), 1)


if __name__ == "__main__":
    unittest.main()
