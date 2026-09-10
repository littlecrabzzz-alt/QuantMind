"""RRG PIT/ETF bridge retains missingness and cannot promote research readiness."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_rrg_pit_etf_bridge as module


class PitEtfBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "mirror"
        self.output = self.base / "output"
        self.release = "data-" + "a" * 64
        self.values = {
            "trade_cal": [
                {"exchange": "SSE", "cal_date": "20260831", "is_open": 1},
                {"exchange": "SSE", "cal_date": "20260901", "is_open": 1},
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
                    "index_code": "000001.SH",
                    "index_name": "示例指数",
                    "list_date": "20200101",
                    "list_status": "L",
                    "_observation": "etf.json",
                },
                {
                    "ts_code": "SZ159999",
                    "source_ts_code": "159999.SZ",
                    "exchange": "SZ",
                    "index_code": None,
                    "index_name": None,
                    "list_date": "20270101",
                    "list_status": "P",
                    "_observation": "future.json",
                },
            ],
            "fund_basic": [
                {"ts_code": "SH510001", "list_date": "20200101", "delist_date": None},
                {"ts_code": "SZ159999", "list_date": "20270101", "delist_date": None},
            ],
            "fund_daily": [
                {
                    "trade_date": "20260901",
                    "ts_code": "SH510001",
                    "open": 1.0,
                    "close": 1.1,
                    "vol": 100.0,
                    "amount": 110.0,
                    "_observation": "price.json",
                }
            ],
            "fund_adj": [
                {
                    "trade_date": "20260901",
                    "ts_code": "SH510001",
                    "adj_factor": 2.0,
                    "_observation": "factor.json",
                }
            ],
            "fund_portfolio": [
                {
                    "ts_code": "SH510001",
                    "symbol": "SZ000001",
                    "source_symbol": "000001.SZ",
                    "ann_date": "20260720",
                    "end_date": "20260630",
                    "mkv": 20.0,
                    "stk_mkv_ratio": 3.0,
                    "_observation": "new-holding.json",
                },
                {
                    "ts_code": "SH510001",
                    "symbol": "SH600000",
                    "source_symbol": "600000.SH",
                    "ann_date": "20260420",
                    "end_date": "20260331",
                    "mkv": 10.0,
                    "stk_mkv_ratio": 2.0,
                    "_observation": "old-holding.json",
                },
            ],
            "etf_sh_cons": [
                {
                    "ts_code": "SH510001",
                    "trade_date": "20260901",
                    "con_code": "510000.SH",
                    "con_name": "申赎现金",
                    "qty": "0",
                    "sub_flag": "必须",
                    "exchange": "SH",
                    "_observation": "pcf.json",
                }
            ],
            "etf_sz_cons": [],
        }

    def invoke(self, **overrides):
        def reader(root, release_id, api, **params):
            rows = self.values[api]
            return pa.Table.from_pylist(rows).replace_schema_metadata(
                {
                    b"tushare": json.dumps(
                        {"release_id": release_id, "upstream_calls": 0}
                    ).encode()
                }
            )

        args = {
            "root": self.root,
            "release_id": self.release,
            "signal_date": "20260831",
            "execution_date": "20260901",
            "output": self.output,
        }
        args.update(overrides)
        manifest = {"datasets": [{"api_name": api} for api in self.values]}
        with (
            patch.object(module, "manifest_at", return_value=manifest),
            patch.object(module, "read_dataset", side_effect=reader),
        ):
            return module.prepare(**args)

    def test_prepares_required_shapes_without_claiming_pit_or_tradability(self):
        report = self.invoke()
        self.assertEqual(report["status"], "blocked_data")
        self.assertFalse(report["membership"]["pit_ready"])
        self.assertEqual(report["membership"]["known_at_rows"], 0)
        self.assertEqual(report["etf"]["date_eligible_candidate_codes"], 1)
        self.assertEqual(report["etf"]["valid_price_and_factor_codes"], 1)
        self.assertEqual(report["etf"]["unsupported_exchange_codes"], [])
        self.assertFalse(report["etf"]["industry_mapping_verified"])
        members = pq.read_table(
            self.output / module.OUTPUTS["industry_members"]
        ).to_pylist()
        self.assertIsNone(members[0]["known_at"])
        self.assertFalse(members[0]["known_at_verified"])
        prices = pq.read_table(self.output / module.OUTPUTS["etf_prices"]).to_pylist()
        self.assertEqual((prices[0]["time"], prices[0]["open"]), ("20260901", 1.0))
        self.assertEqual(prices[0]["source_volume_unit"], "lot")
        self.assertFalse(prices[0]["open_tradability_verified"])
        holdings = pq.read_table(
            self.output / module.OUTPUTS["etf_holdings"]
        ).to_pylist()
        self.assertEqual({row["ComponentCode"] for row in holdings}, {"SZ000001"})
        self.assertFalse(holdings[0]["complete_exposure_verified"])
        pcf = pq.read_table(self.output / module.OUTPUTS["etf_pcf"]).to_pylist()
        self.assertEqual(pcf[0]["ComponentCode"], "510000.SH")
        self.assertFalse(pcf[0]["portfolio_weight_interpretation_allowed"])
        self.assertTrue((self.output / "manifest.json").is_file())
        self.assertNotIn(
            "codes",
            next(
                query
                for query in report["queries"]
                if query["api_name"] == "fund_daily"
            )["params"],
        )

    def test_missing_price_is_reported_and_never_filled(self):
        self.values["etf_basic"][1]["list_date"] = "20200101"
        self.values["fund_basic"][1]["list_date"] = "20200101"
        report = self.invoke()
        self.assertEqual(report["etf"]["date_eligible_candidate_codes"], 2)
        self.assertEqual(report["etf"]["execution_price_codes"], 1)
        self.assertEqual(report["etf"]["missing_execution_price_codes"], ["SZ159999"])
        rows = pq.read_table(self.output / module.OUTPUTS["etf_prices"]).to_pylist()
        self.assertEqual({row["EtfCode"] for row in rows}, {"SH510001"})

    def test_requires_exact_next_session_and_strictly_earlier_holdings(self):
        self.values["trade_cal"].insert(
            1, {"exchange": "SSE", "cal_date": "20260901", "is_open": 0}
        )
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.invoke()
        self.values["trade_cal"] = [
            {"exchange": "SSE", "cal_date": "20260831", "is_open": 1},
            {"exchange": "SSE", "cal_date": "20260901", "is_open": 1},
        ]
        self.values["fund_portfolio"][0]["ann_date"] = "20260831"
        with self.assertRaisesRegex(ValueError, "same-day or future"):
            self.invoke()

    def test_rejects_bad_intervals_invalid_prices_and_protected_output(self):
        self.values["ci_index_member"][0]["out_date"] = "20190101"
        with self.assertRaisesRegex(ValueError, "reversed"):
            self.invoke()
        self.values["ci_index_member"][0]["out_date"] = None
        self.values["fund_daily"][0]["open"] = 0
        report = self.invoke()
        self.assertEqual(report["etf"]["valid_price_and_factor_codes"], 0)
        with self.assertRaisesRegex(ValueError, "Output must be new"):
            module.prepare(
                self.root, self.release, "20260831", "20260901", self.root / "bad"
            )


if __name__ == "__main__":
    unittest.main()
