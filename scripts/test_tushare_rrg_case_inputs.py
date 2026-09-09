"""Isolated input mapping checks; no strategy, upstream or registered case writes."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_rrg_case_inputs as module


class CaseInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "source"
        (self.repo / "config").mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        self.config = self.repo / "config/rrg.json"
        self.research = self.repo / "scripts/research_case.py"
        self.research.write_text(
            "raise RuntimeError('Must never execute this source')\n"
        )
        cfg = {
            "protocol": {
                "classification": "中信一级",
                "comparison_window": ["2026-08-28", "2026-08-31"],
                "parameters": {"ratio_lookback": 220},
            },
            "datasets": [
                {
                    "id": "industry_prices",
                    "glob": "data/quantdb/1_kline_data/index_daily/*.parquet",
                    "required_columns": [
                        "time",
                        "IndexCode",
                        "Category",
                        "open",
                        "close",
                    ],
                },
                {
                    "id": "calendar",
                    "glob": module.OUTPUTS["calendar"],
                    "required_columns": ["TradingDate", "IsTradingDay"],
                },
                {
                    "id": "industry_members",
                    "glob": "unused",
                    "required_columns": ["known_at"],
                },
            ],
            "review_gates": [
                {"id": "industry_integrity"},
                {"id": "point_in_time_breadth"},
                {"id": "tradable_etf_universe"},
            ],
        }
        self.config.write_text(json.dumps(cfg))
        report = {
            "status": "coordinate_consumer_passed",
            "release_id": "fixed-prices",
            "source_hashes": {"config": module.sha(self.config)},
            "comparison_window": cfg["protocol"]["comparison_window"],
            "parameters": cfg["protocol"]["parameters"],
            "included_codes": ["CI005001"],
            "price_rows": 2,
            "slice_audit": {
                "status": "slice_structure_passed",
                "release_id": "fixed-prices",
                "calendar": {"warmup_start": "20260828"},
                "queries": {"ci_daily": {"limit": 100}, "trade_cal": {"limit": 100}},
            },
            "month_end_mapping": [
                {"signal_close_date": "2026-08-31", "next_open_date": None}
            ],
        }
        self.report = self.base / "accepted-report.json"
        self.report.write_text(json.dumps(report))
        self.values = {
            ("fixed-prices", "ci_daily"): [
                {
                    "ts_code": "CI005001",
                    "trade_date": d,
                    "open": 1.0,
                    "close": 2.0,
                    "_observation": "source.json",
                    "supplier_extra": "retained",
                }
                for d in ("20260828", "20260831")
            ],
            ("fixed-prices", "trade_cal"): [
                {"exchange": "SSE", "cal_date": d, "is_open": flag}
                for d, flag in (
                    ("20260828", 1),
                    ("20260829", 0),
                    ("20260830", 0),
                    ("20260831", 1),
                )
            ],
            ("fixed-calendar", "trade_cal"): [
                {"exchange": "SSE", "cal_date": "20260901", "is_open": 1}
            ],
        }

    def invoke(self, **overrides):
        def reader(root, rid, api, **query):
            self.assertNotIn("fields", query)
            return pa.Table.from_pylist(self.values[rid, api]).replace_schema_metadata(
                {
                    b"tushare": json.dumps(
                        {"release_id": rid, "upstream_calls": 0}
                    ).encode()
                }
            )

        args = {
            "root": self.base / "mirror",
            "release_id": "fixed-prices",
            "config_path": self.config,
            "report_path": self.report,
            "report_sha256": module.sha(self.report),
            "calendar_release_id": "fixed-calendar",
            "calendar_end": "20260901",
            "output": self.base / "output",
            "research_case_path": self.research,
        }
        args.update(overrides)
        with (
            patch.object(module, "manifest_at", return_value={"datasets": []}),
            patch.object(module, "read_dataset", side_effect=reader),
        ):
            return module.prepare(**args)

    def test_mapping_retains_originals_provenance_and_all_gates(self):
        original = self.research.read_bytes()
        report = self.invoke()
        rows = pq.read_table(
            self.base / "output" / module.OUTPUTS["industry_prices"]
        ).to_pylist()
        self.assertEqual(rows[0]["IndexCode"], rows[0]["ts_code"])
        self.assertEqual(rows[0]["supplier_extra"], "retained")
        self.assertEqual(
            rows[0]["classification_verification"], "frozen_audit_scope_only"
        )
        self.assertNotIn("known_at", rows[0])
        self.assertEqual(report["workflow_stage"], "blocked_data")
        self.assertFalse(report["research_ready"])
        self.assertTrue(all(g["status"] == "unknown" for g in report["review_gates"]))
        self.assertEqual(report["unprepared_datasets"], ["industry_members"])
        self.assertEqual(report["month_end_mapping"][0]["next_open_date"], "2026-09-01")
        self.assertFalse(report["month_end_mapping"][0]["execution_price_verified"])
        self.assertEqual(original, self.research.read_bytes())
        inventory = json.loads((self.base / "output/manifest.json").read_text())
        for name, item in inventory["files"].items():
            self.assertEqual(module.sha(self.base / "output" / name), item["sha256"])
        self.assertFalse((self.base / "output/state.json").exists())

    def test_reject_changed_report_config_existing_or_source_output(self):
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.invoke(report_sha256="0" * 64)
        self.config.write_text(self.config.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.invoke()
        self.config.write_text(self.config.read_text()[:-1])
        with self.assertRaisesRegex(ValueError, "outside"):
            self.invoke(output=self.repo / "new-data")
        self.invoke()
        with self.assertRaisesRegex(ValueError, "new"):
            self.invoke()

    def test_missing_calendar_date_and_changed_prior_mapping_rejected(self):
        self.values["fixed-calendar", "trade_cal"] = [
            {"exchange": "SSE", "cal_date": "20260902", "is_open": 1}
        ]
        with self.assertRaisesRegex(ValueError, "missing dates"):
            self.invoke(calendar_end="20260902")
        self.values["fixed-calendar", "trade_cal"] = [
            {"exchange": "SSE", "cal_date": "20260901", "is_open": 1}
        ]
        report = json.loads(self.report.read_text())
        report["month_end_mapping"][0]["next_open_date"] = "2026-09-02"
        self.report.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "mapping changed"):
            self.invoke()


if __name__ == "__main__":
    unittest.main()
