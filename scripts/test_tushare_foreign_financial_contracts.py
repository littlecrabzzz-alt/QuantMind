"""Offline acceptance of reviewed foreign financial selectors and bounded plans."""

from datetime import date, datetime, timedelta
from hashlib import sha256
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_foreign_financial_contracts import (
    DOCUMENTS,
    FIELDS,
    OUTPUT_FIELDS,
    FOREIGN_FINANCIAL_CONTRACTS as C,
    foreign_financial_prerequisites,
    iter_foreign_financial_jobs,
    split_foreign_financial_request,
    validate_foreign_financial_request,
)
from backend.shared.tushare_intake import assess_response

# Independent SHA fixtures of complete official output tables fetched 2026-09-09;
# includes names, source types/default flags/descriptions, not a copy of FIELDS.
TABLE_SHA = {
    389: "9dd46f9f0062cf9ff559a6d1c419d32cada1b137762751fd3ef59866fcf077c6",
    390: "236c14513587e79fbdfb11a1f1b0af16caab7176e6c9cc3d39c019f66d3a6caf",
    391: "9dd46f9f0062cf9ff559a6d1c419d32cada1b137762751fd3ef59866fcf077c6",
    388: "aa55b30460ef30b2b62f12a23e09811eca254bf50856a39db380af222dc2a477",
    394: "02c369bfe5c85895ed34acbdc2c4e0a175a2de994953f5a5dbcb5a595a9276d4",
    395: "02c369bfe5c85895ed34acbdc2c4e0a175a2de994953f5a5dbcb5a595a9276d4",
    396: "02c369bfe5c85895ed34acbdc2c4e0a175a2de994953f5a5dbcb5a595a9276d4",
    393: "1e99e3c00eb781a759e4bfb0f615bcdca6530bea8ab81bc159bc92417e2098c2",
}
IDS = {
    "hk_stocks": [
        {"ts_code": "00700.HK", "list_status": "L"},
        {"ts_code": "00001!A.HK", "list_status": "D"},
    ],
    "us_stocks": [{"ts_code": "BRK.B", "list_status": "D"}, "AAPL", "ABC/WS", "BRK.B"],
}


class ForeignFinancialTest(unittest.TestCase):
    def test_all_eight_full_official_tables_no_truncated_defaults(self):
        self.assertEqual(len(C), 8)
        for api, (doc, _) in DOCUMENTS.items():
            encoded = json.dumps(
                OUTPUT_FIELDS[api], ensure_ascii=False, sort_keys=True
            ).encode()
            self.assertEqual(sha256(encoded).hexdigest(), TABLE_SHA[doc])
            self.assertEqual(C[api]["extra_fields"], FIELDS[api])
            self.assertEqual(C[api]["default_fields"], FIELDS[api])
            self.assertEqual(C[api]["hidden_fields"], [])
            self.assertEqual(len(FIELDS[api]), len(set(FIELDS[api])))
        self.assertEqual(len(FIELDS["hk_fina_indicator"]), 87)
        self.assertEqual(len(FIELDS["us_fina_indicator"]), 69)
        self.assertIn("capitial_ratio", FIELDS["us_fina_indicator"])
        self.assertIn("hk_common_shares", FIELDS["hk_fina_indicator"])
        self.assertIn(
            "数据源有误", C["hk_fina_indicator"]["field_notes"]["hk_common_shares"]
        )
        self.assertEqual(C["hk_fina_indicator"]["field_types"]["start_date"], "float")

    def test_recent_first_fair_complete_source_discovery_and_history(self):
        with patch("socket.socket.connect", side_effect=AssertionError("offline")):
            jobs = list(iter_foreign_financial_jobs({}, date(2026, 9, 9), IDS))
        self.assertEqual(len(jobs), 40)  # 4 HK * 2 + 4 US * 3 per phase
        self.assertEqual({j["api_name"] for j in jobs[:8]}, set(C))
        self.assertEqual([j["priority"] for j in jobs], [25] * 20 + [45] * 20)
        self.assertTrue(all(j["epoch"] == "history" for j in jobs[20:]))
        for j in jobs:
            validate_foreign_financial_request(j["api_name"], j["params"])
            self.assertNotIn("report_type", j["params"])
            self.assertNotIn("ind_name", j["params"])
        self.assertIn("00001!A.HK", {j["params"]["ts_code"] for j in jobs})
        self.assertIn("ABC/WS", {j["params"]["ts_code"] for j in jobs})
        self.assertIn("BRK.B", {j["params"]["ts_code"] for j in jobs})
        for api in C:
            recent = next(j for j in jobs[:20] if j["api_name"] == api)["params"]
            history = next(j for j in jobs[20:] if j["api_name"] == api)["params"]
            self.assertEqual(history["start_date"], "20000101")
            self.assertEqual(
                datetime.strptime(history["end_date"], "%Y%m%d").date()
                + timedelta(days=1),
                datetime.strptime(recent["start_date"], "%Y%m%d").date(),
            )
            self.assertEqual(recent["end_date"], "20260908")

    def test_earlier_scope_not_clamped_and_no_artificial_symbol_sample(self):
        ids = {"us_stocks": [f"S{i}" for i in range(1201)]}
        config = {
            "foreign_financial_apis": ["us_income"],
            "foreign_financial_history_start": {"us_income": "19800101"},
        }
        stream = iter_foreign_financial_jobs(config, date(2026, 1, 1), ids)
        first = list(islice(stream, 1201))
        self.assertEqual(len({j["params"]["ts_code"] for j in first}), 1201)
        self.assertEqual(next(stream)["params"]["start_date"], "19800101")
        self.assertEqual(
            list(
                iter_foreign_financial_jobs(
                    {"foreign_financial_apis": []}, date(2026, 1, 1), IDS
                )
            ),
            [],
        )

    def test_saturation_bisects_all_fiscal_days_and_retains_filters(self):
        original = {
            "ts_code": "NVDA",
            "start_date": "20240228",
            "end_date": "20240301",
            "report_type": "Q1",
            "ind_name": "营业额",
        }
        out = split_foreign_financial_request("us_income", original)
        self.assertFalse(out["universe_complete"])
        self.assertEqual(out["children"][0]["end_date"], "20240229")
        self.assertEqual(out["children"][1]["start_date"], "20240301")
        for child in out["children"]:
            for key in ("ts_code", "report_type", "ind_name"):
                self.assertEqual(child[key], original[key])
        self.assertEqual(original["end_date"], "20240301")
        validate_foreign_financial_request(
            "us_income", {"ts_code": "NVDA", "period": "20250427"}
        )
        for params in (
            {"ts_code": "NVDA"},
            {"ts_code": "NVDA", "period": "20250427"},
            {"ts_code": "NVDA", "start_date": "20250427", "end_date": "20250427"},
        ):
            out = split_foreign_financial_request("us_income", params)
            self.assertEqual(out["children"], [])
            self.assertTrue(out["gap"])
            self.assertFalse(out["universe_complete"])

    def test_no_guessed_pagination_vip_or_cross_market_parameters(self):
        for params in (
            {"ts_code": "NVDA", "offset": 0},
            {"ts_code": "NVDA", "limit": 10000},
            {"ts_code": "NVDA", "ann_date": "20260901"},
            {"ts_code": "NVDA", "report_type": "1"},
            {"ts_code": "NVDA", "report_type": "单季报"},
            {"ts_code": "NVDA", "period": "20250230"},
            {"ts_code": "NVDA", "start_date": "20260909", "end_date": "20260908"},
            {"ts_code": "NVDA", "period": "20250930", "start_date": "20250101"},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                validate_foreign_financial_request("us_income", params)
        for code in ("HK00700", "00700", "700.HK", "", None):
            with self.assertRaises(ValueError):
                validate_foreign_financial_request("hk_income", {"ts_code": code})
        with self.assertRaises(ValueError):
            validate_foreign_financial_request(
                "hk_income", {"ts_code": "00700.HK", "report_type": "Q4"}
            )

    def test_cap_conflict_permissions_units_and_pit_are_not_success_claims(self):
        for api, spec in C.items():
            self.assertIsNone(spec["minimum_points"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertFalse(spec["history_bound_verified"])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertEqual(spec["split_axis"], "end_date")
            self.assertIsNone(spec["pagination"])
            self.assertIn("pit_gap", spec)
            self.assertEqual(
                spec["row_cap"], 200 if api.endswith("fina_indicator") else 10000
            )
        payload = {
            "code": 0,
            "data": {
                "fields": ["ts_code", "end_date"],
                "items": [["AAPL", "20250427"]] * 200,
            },
        }
        assessed = assess_response(payload, 200, ["ts_code", "end_date"])
        self.assertNotEqual(assessed["status"], "sample_ok")
        gaps = foreign_financial_prerequisites(IDS)
        self.assertEqual(
            len([g for g in gaps if g["reason"] == "independent_permission_unprobed"]),
            8,
        )
        self.assertTrue(any(g["reason"] == "history_gap" for g in gaps))
        empty = foreign_financial_prerequisites({})
        self.assertEqual(
            len(
                [
                    g
                    for g in empty
                    if g["reason"] == "awaiting_stored_historical_discovery"
                ]
            ),
            8,
        )
        self.assertEqual(
            list(iter_foreign_financial_jobs({}, date(2026, 9, 9), {})), []
        )


if __name__ == "__main__":
    unittest.main()
