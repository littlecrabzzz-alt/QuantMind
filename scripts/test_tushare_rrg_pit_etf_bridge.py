"""RRG PIT/ETF bridge retains missingness and cannot promote research readiness."""

import hashlib
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
                    "_row_identity": "1" * 64,
                    "_fetched_at": "2026-09-03T00:00:00+00:00",
                    "_observation": "member-current.json",
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
                    "_row_identity": "2" * 64,
                    "_fetched_at": "2026-08-30T00:00:00+00:00",
                    "_observation": "etf-current.json",
                },
                {
                    "ts_code": "SZ159999",
                    "source_ts_code": "159999.SZ",
                    "exchange": "SZ",
                    "index_code": None,
                    "index_name": None,
                    "list_date": "20270101",
                    "list_status": "P",
                    "_row_identity": "3" * 64,
                    "_fetched_at": "2026-08-30T00:00:00+00:00",
                    "_observation": "future-current.json",
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
        self.manifest = {
            "retained_observations_included": True,
            "datasets": [
                {"api_name": api}
                for api in self.values
                if api not in {"ci_index_member", "etf_basic"}
            ],
            "coverage_by_api": [
                {"api_name": "ci_index_member", "state": "done", "partitions": 2},
                {"api_name": "etf_basic", "state": "done", "partitions": 5},
            ],
            "files": {},
        }
        self._add_vintage_partition(
            "ci_index_member",
            [
                {
                    "_row_identity": "1" * 64,
                    "l1_code": "CI005001",
                    "l2_code": None,
                    "l3_code": None,
                    "ts_code": "SH600001",
                    "in_date": "20200101",
                    "out_date": None,
                    "_fetched_at": "2026-09-01T16:30:00+00:00",
                    "_observation": "member-first.json",
                },
                {
                    "_row_identity": "1" * 64,
                    "l1_code": "CI005001",
                    "l2_code": None,
                    "l3_code": None,
                    "ts_code": "SH600001",
                    "in_date": "20200101",
                    "out_date": None,
                    "_fetched_at": "2026-09-03T00:00:00+00:00",
                    "_observation": "member-current.json",
                },
            ],
        )
        self._add_vintage_partition(
            "etf_basic",
            [
                {
                    "_row_identity": "5" * 64,
                    "ts_code": "SH510001",
                    "index_code": "000001.SH",
                    "index_name": "示例指数",
                    "_fetched_at": "2026-08-18T00:00:00+00:00",
                    "_observation": "etf-oldest-a.json",
                },
                {
                    "_row_identity": "4" * 64,
                    "ts_code": "SH510001",
                    "index_code": "000999.SH",
                    "index_name": "旧观察指数",
                    "_fetched_at": "2026-08-20T00:00:00+00:00",
                    "_observation": "etf-old-map.json",
                },
                {
                    "_row_identity": "2" * 64,
                    "ts_code": "SH510001",
                    "index_code": "000001.SH",
                    "index_name": "示例指数",
                    "_fetched_at": "2026-08-28T16:30:00+00:00",
                    "_observation": "etf-first.json",
                },
                {
                    "_row_identity": "2" * 64,
                    "ts_code": "SH510001",
                    "index_code": "000001.SH",
                    "index_name": "示例指数",
                    "_fetched_at": "2026-08-30T00:00:00+00:00",
                    "_observation": "etf-current.json",
                },
                {
                    "_row_identity": "3" * 64,
                    "ts_code": "SZ159999",
                    "index_code": None,
                    "index_name": None,
                    "_fetched_at": "2026-08-30T00:00:00+00:00",
                    "_observation": "future-current.json",
                },
            ],
        )

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def _add_file(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.manifest["files"][relative] = {
            "bytes": len(data),
            "sha256": self.digest(data),
        }

    def _add_vintage_partition(self, api, rows):
        for row in rows:
            object_data = ("object:" + row["_row_identity"]).encode()
            object_sha = self.digest(object_data)
            self._add_file(f"objects/{object_sha}.json", object_data)
            observation_data = json.dumps(
                {
                    "fetched_at": row["_fetched_at"],
                    "object_sha256": object_sha,
                    "request": {
                        "api_name": api,
                        "fields": "fixture",
                        "params": {
                            "list_status": "L"
                            if api == "etf_basic"
                            else "member"
                        },
                    },
                },
                sort_keys=True,
            ).encode()
            self._add_file("observations/" + row["_observation"], observation_data)
        temporary = self.root / (api + ".parquet")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), temporary)
        data = temporary.read_bytes()
        temporary.unlink()
        parquet_sha = self.digest(data)
        relative = f"parquet/{parquet_sha}.parquet"
        self._add_file(relative, data)
        self.manifest["datasets"].append({"api_name": api, "path": relative})

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
        with (
            patch.object(module, "manifest_at", return_value=self.manifest),
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
        vintages = pq.read_table(
            self.output / module.OUTPUTS["industry_member_vintages"]
        ).to_pylist()
        self.assertEqual(vintages[0]["observation_local_date"], "20260902")
        self.assertEqual(vintages[0]["forward_valid_from"], "20260903")
        self.assertFalse(vintages[0]["forward_usable_for_signal"])
        self.assertEqual(vintages[0]["source_release_id"], self.release)
        self.assertEqual(len(vintages[0]["source_object_sha256"]), 64)
        self.assertEqual(len(vintages[0]["source_observation_sha256"]), 64)
        self.assertFalse(vintages[0]["historical_known_at_verified"])
        self.assertFalse(vintages[0]["historical_mapping_verified"])
        mappings = pq.read_table(
            self.output / module.OUTPUTS["etf_index_mapping"]
        ).to_pylist()
        self.assertEqual(len(mappings), 1)
        self.assertEqual(
            (mappings[0]["EtfCode"], mappings[0]["index_code"]),
            ("SH510001", "000001.SH"),
        )
        self.assertEqual(mappings[0]["observation_local_date"], "20260829")
        self.assertEqual(mappings[0]["forward_valid_from"], "20260830")
        self.assertEqual(mappings[0]["source_observation"], "etf-first.json")
        self.assertEqual(
            mappings[0]["selected_source_observation"], "etf-current.json"
        )
        self.assertEqual(mappings[0]["selected_forward_valid_from"], "20260831")
        self.assertTrue(mappings[0]["episode_continuity_proven"])
        self.assertNotEqual(mappings[0]["index_code"], "000999.SH")
        self.assertTrue(mappings[0]["forward_usable_for_signal"])
        self.assertFalse(mappings[0]["historical_mapping_verified"])
        self.assertEqual(report["membership"]["forward_usable_on_signal_rows"], 0)
        self.assertEqual(report["etf"]["current_index_mapping_candidates"], 1)
        self.assertEqual(
            report["etf"]["forward_usable_index_mapping_candidates"], 1
        )
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

    def test_future_selected_row_is_unusable_until_its_local_next_day(self):
        row = self.values["etf_basic"][0]
        identity = module.row_key(row, module.ETF_INDEX_MAPPING_KEY)
        provenance = {
            identity: {
                "episode_start_observation_at": "2026-08-01T00:00:00+00:00",
                "observation_local_date": "20260801",
                "forward_valid_from": "20260802",
                "selected_fixed_observation_at": "2026-09-01T16:30:00+00:00",
                "selected_observation_local_date": "20260902",
                "selected_forward_valid_from": "20260903",
                "source_object_sha256": "1" * 64,
                "source_observation": "etf-first.json",
                "source_observation_sha256": "2" * 64,
                "selected_source_object_sha256": "3" * 64,
                "selected_source_observation": "etf-current.json",
                "selected_source_observation_sha256": "4" * 64,
                "episode_continuity_proven": True,
            }
        }
        same_day = module.etf_index_mapping_candidates(
            [row], provenance, "20260902", self.release
        )
        next_day = module.etf_index_mapping_candidates(
            [row], provenance, "20260903", self.release
        )
        self.assertEqual(
            same_day[0]["selected_observation_local_date"], "20260902"
        )
        self.assertFalse(same_day[0]["forward_usable_for_signal"])
        self.assertTrue(next_day[0]["forward_usable_for_signal"])

    def test_aba_mapping_starts_at_latest_continuous_a_episode(self):
        self.invoke()
        mapping = pq.read_table(
            self.output / module.OUTPUTS["etf_index_mapping"]
        ).to_pylist()[0]
        self.assertEqual(mapping["source_observation"], "etf-first.json")
        self.assertNotEqual(mapping["source_observation"], "etf-oldest-a.json")
        self.assertEqual(
            mapping["selected_source_observation"], "etf-current.json"
        )

    def test_unproven_observation_continuity_uses_selected_row_only(self):
        self.manifest["coverage_by_api"] = [
            row
            for row in self.manifest["coverage_by_api"]
            if row["api_name"] != "etf_basic"
        ]
        self.invoke()
        mapping = pq.read_table(
            self.output / module.OUTPUTS["etf_index_mapping"]
        ).to_pylist()[0]
        self.assertEqual(mapping["source_observation"], "etf-current.json")
        self.assertFalse(mapping["episode_continuity_proven"])

    def test_disappearance_restarts_the_current_value_episode(self):
        rows = [
            {
                "_row_identity": "6" * 64,
                "entity": "X",
                "value": "A",
                "_fetched_at": "2026-08-01T00:00:00+00:00",
                "_observation": "episode-old-a.json",
            },
            {
                "_row_identity": "7" * 64,
                "entity": "Y",
                "value": "Z",
                "_fetched_at": "2026-08-02T00:00:00+00:00",
                "_observation": "episode-x-missing.json",
            },
            {
                "_row_identity": "8" * 64,
                "entity": "X",
                "value": "A",
                "_fetched_at": "2026-08-03T00:00:00+00:00",
                "_observation": "episode-current-a.json",
            },
        ]
        self._add_vintage_partition("episode_test", rows)
        self.manifest["coverage_by_api"].append(
            {"api_name": "episode_test", "state": "done", "partitions": 3}
        )
        provenance = module.fixed_observation_episodes(
            self.root,
            self.manifest,
            "episode_test",
            [rows[-1]],
            ("entity", "value"),
            ("entity",),
            ("value",),
        )
        current = provenance[("X", "A")]
        self.assertEqual(current["source_observation"], "episode-current-a.json")
        self.assertEqual(current["forward_valid_from"], "20260804")

    def test_requires_retained_observation_manifest_contract(self):
        for missing_value in (False, None):
            with self.subTest(retained_observations_included=missing_value):
                if missing_value is None:
                    self.manifest.pop("retained_observations_included", None)
                else:
                    self.manifest["retained_observations_included"] = missing_value
                with self.assertRaisesRegex(ValueError, "retained observations"):
                    self.invoke()

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

    def test_rejects_tampered_forward_vintage_provenance(self):
        object_data = ("object:" + "1" * 64).encode()
        object_sha = self.digest(object_data)
        (self.root / "objects" / f"{object_sha}.json").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "provenance file"):
            self.invoke()


if __name__ == "__main__":
    unittest.main()
