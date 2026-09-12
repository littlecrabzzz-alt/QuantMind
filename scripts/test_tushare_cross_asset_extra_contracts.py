"""Pure six-API schemas, identifiers, historical coverage and saturation bounds."""

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_cross_asset_extra_contracts import (
    CROSS_ASSET_EXTRA_CONTRACTS as C,
    FIELDS,
    FIELD_METADATA,
    GLOBAL_INDEX_CODES,
    SZ_BOARD_STARTS,
    cross_asset_identifiers,
    cross_asset_extra_prerequisites,
    iter_cross_asset_extra_jobs,
    validate_cross_asset_request,
    split_cross_asset_request,
)


class Contracts(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("pure test: no network"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_all_official_fields_hidden_and_types(self):
        self.assertEqual(
            {k: len(v) for k, v in FIELDS.items()},
            {
                "idx_factor_pro": 89,
                "fund_factor_pro": 90,
                "cb_factor_pro": 89,
                "index_global": 12,
                "sz_daily_info": 9,
                "etf_limit": 7,
            },
        )
        self.assertEqual(C["index_global"]["hidden_fields"], ["amount"])
        self.assertEqual(
            C["etf_limit"]["hidden_fields"], ["pre_close", "asset_type", "exchange"]
        )
        self.assertEqual(
            FIELD_METADATA["fund_factor_pro"]["trade_date_doris"]["type"], "None"
        )
        self.assertEqual(
            FIELD_METADATA["cb_factor_pro"]["amount"]["description"], "成交金额(万元)"
        )
        for api, spec in C.items():
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["positive_fields"], [])
            self.assertEqual(spec["keys"], ["ts_code", "trade_date"])
            self.assertEqual(len(FIELDS[api]), len(set(FIELDS[api])))
            self.assertFalse(spec["universe_complete"])
            self.assertTrue(spec["preserve_distinct_rows"])
        self.assertFalse(
            any("_qfq" in f or "_hfq" in f for f in FIELDS["cb_factor_pro"])
        )

    def test_schema_canonical_fingerprints(self):
        expected = SCHEMA_SHA
        for api, sha in expected.items():
            actual = hashlib.sha256(
                json.dumps(
                    FIELD_METADATA[api],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            self.assertEqual(actual, sha)

    def test_namespace_source_codes_and_retired_boards(self):
        ids = cross_asset_identifiers(
            {
                "indexes": ["000001.SH"],
                "sw_indexes": ["801010.SI"],
                "ci_indexes": ["CI005001.CI"],
                "funds": [
                    {"ts_code": "1500011.SZ", "status": "D"},
                    "150001.SZ",
                    "000001.OF",
                ],
                "etfs": ["510300.SH"],
                "bonds": ["T123456.SZ", "123456.SZ"],
                "global_indexes": ["RETIRED.X"],
                "sz_boards": ["中小板", "历史新板块"],
            }
        )
        self.assertEqual(
            ids["cross_asset_indexes"], ["000001.SH", "801010.SI", "CI005001.CI"]
        )
        self.assertIn("1500011.SZ", ids["cross_asset_funds"])
        self.assertIn("150001.SZ", ids["cross_asset_funds"])
        self.assertNotIn("000001.OF", ids["cross_asset_funds"])
        self.assertIn("RETIRED.X", ids["global_indexes"])
        self.assertIn("中小板", ids["sz_boards"])
        self.assertEqual(len(GLOBAL_INDEX_CODES), 21)
        self.assertEqual(SZ_BOARD_STARTS["基础设施基金"], "20210621")
        for api, code in [
            ("sz_daily_info", "中小板"),
            ("index_global", "HSI"),
            ("idx_factor_pro", "801010.SI"),
            ("fund_factor_pro", "1500011.SZ"),
            ("cb_factor_pro", "T123456.SZ"),
        ]:
            validate_cross_asset_request(api, {"ts_code": code})
        for api, params in [
            ("fund_factor_pro", {"ts_code": "000001.OF"}),
            ("index_global", {"offset": 0}),
            ("sz_daily_info", {"ts_code": "股票'OR1"}),
            ("etf_limit", {"asset_type": "ETF"}),
            ("idx_factor_pro", {"ts_code": "SH000001"}),
        ]:
            with self.assertRaises(ValueError):
                validate_cross_asset_request(api, params)

    def test_history_recent_full_coverage_leap_and_fairness(self):
        jobs = list(
            iter_cross_asset_extra_jobs(
                {"history_start": "20240220"}, date(2024, 3, 10)
            )
        )
        recent = [j for j in jobs if j["epoch"] != "history"]
        history = [j for j in jobs if j["epoch"] == "history"]
        self.assertEqual(len(recent), 42)
        self.assertEqual(jobs[:42], recent)
        self.assertEqual(len({j["api_name"] for j in history[:6]}), 6)
        self.assertEqual(len(history), 42)
        factor_apis = {"idx_factor_pro", "fund_factor_pro", "cb_factor_pro"}
        for api in C:
            days = []
            for job in jobs:
                if job["api_name"] != api:
                    continue
                self.assertEqual(job["fields"].split(","), FIELDS[api])
                validate_cross_asset_request(api, job["params"])
                p = job["params"]
                if api in factor_apis:
                    self.assertEqual(set(p), {"trade_date"})
                left = date.fromisoformat(
                    "-".join(
                        [
                            p.get("trade_date", p.get("start_date"))[:4],
                            p.get("trade_date", p.get("start_date"))[4:6],
                            p.get("trade_date", p.get("start_date"))[6:],
                        ]
                    )
                )
                rightstr = p.get("trade_date", p.get("end_date"))
                right = date(int(rightstr[:4]), int(rightstr[4:6]), int(rightstr[6:]))
                while left <= right:
                    days.append(left)
                    left += timedelta(days=1)
            self.assertEqual(
                sorted(days), [date(2024, 2, 20) + timedelta(days=i) for i in range(19)]
            )
            self.assertEqual(len(days), len(set(days)))

    def test_factor_request_minimum_and_planning_contract(self):
        codes = {
            "idx_factor_pro": "801010.SI",
            "fund_factor_pro": "1500011.SZ",
            "cb_factor_pro": "T123456.SZ",
        }
        for api, code in codes.items():
            for params in (
                {},
                {"start_date": "20240101"},
                {
                    "start_date": "20240101",
                    "end_date": "20240131",
                },
            ):
                with (
                    self.subTest(api=api, params=params),
                    self.assertRaisesRegex(
                        ValueError, "requires ts_code or trade_date"
                    ),
                ):
                    validate_cross_asset_request(api, params)
            validate_cross_asset_request(api, {"trade_date": "20240102"})
            validate_cross_asset_request(
                api,
                {
                    "ts_code": code,
                    "start_date": "20240101",
                    "end_date": "20240131",
                },
            )
            self.assertIn("live code 50101", C[api]["parameter_note"])
            self.assertIn("every configured calendar date", C[api]["planning_note"])

    def test_no_unknown_start_invented_and_older_scope_not_clipped(self):
        config = {"cross_asset_extra_apis": ["index_global"]}
        cross_asset_extra_prerequisites(
            {"funds": ["invalid unrelated family"]}, config=config
        )
        self.assertEqual(
            len(list(iter_cross_asset_extra_jobs(config, date(2026, 9, 9)))), 7
        )
        gaps = cross_asset_extra_prerequisites(config=config)
        self.assertTrue(
            any(g["reason"] == "unknown_history_start_requires_scope" for g in gaps)
        )
        jobs = iter_cross_asset_extra_jobs(
            {"cross_asset_extra_apis": ["sz_daily_info"], "history_start": "19900101"},
            date(2026, 9, 9),
        )
        first = next(j for j in jobs if j["epoch"] == "history")
        self.assertEqual(first["params"]["start_date"], "19900101")
        for g in gaps:
            self.assertNotEqual(g.get("universe_complete"), True)

    def test_date_split_is_exhaustive_preserves_code_and_no_pagination(self):
        for api in C:
            code = {
                "index_global": "HSI",
                "sz_daily_info": "中小板",
                "fund_factor_pro": "1500011.SZ",
                "etf_limit": "510300.SH",
                "idx_factor_pro": "801010.SI",
                "cb_factor_pro": "123456.SZ",
            }[api]
            p = {"ts_code": code, "start_date": "20240228", "end_date": "20240301"}
            children = split_cross_asset_request(api, p)
            self.assertEqual(
                children,
                [{**p, "end_date": "20240229"}, {**p, "start_date": "20240301"}],
            )
            self.assertEqual(
                split_cross_asset_request(
                    api, {"ts_code": code, "trade_date": "20240229"}
                ),
                [],
            )
            self.assertFalse(C[api]["universe_complete"])
        for p in [
            {"start_date": "20240230"},
            {"start_date": "20240302", "end_date": "20240301"},
            {"trade_date": "20240101", "start_date": "20240101"},
        ]:
            with self.assertRaises(ValueError):
                validate_cross_asset_request("index_global", p)


SCHEMA_SHA = {
    "idx_factor_pro": "3d232fe8874e1640201bdf8cc318631a89a9a8f7e81917339fc041e1ddd3c7d8",
    "index_global": "2c20ec0635d91884c84010aa442a6f5d661eae612de5938a58ac0e9387f54f2e",
    "sz_daily_info": "47075e6c7fc557a3b76fa6a0733ab9c8066e69aed943be3e30a4da09f1db7bc0",
    "etf_limit": "8c94449c19617cb89ba0b18d48d15581fb962949a935ff4232c12c61b36bfb7d",
    "fund_factor_pro": "852fad67e4b22cdb08125afdfef5a53725db45521c267de5003b9c12f783c144",
    "cb_factor_pro": "bcfd604958b42159d9dc0f6d41ad529ce98d56d87de048997e37984587f9f94c",
}
if __name__ == "__main__":
    unittest.main()
