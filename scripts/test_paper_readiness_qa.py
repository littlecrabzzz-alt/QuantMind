"""Contract regressions for the paper-readiness v1 producer: exact account and
asset keys, two-root relative paths only, honest states from real fixture rows,
cache reuse across runs. Uses tiny synthetic parquet fixtures, no archive access."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import paper_readiness_qa as qa  # noqa: E402

RID = "data-" + "a" * 64
FULL = "data-" + "b" * 64


def write_parquet(path, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)


class ReadinessQA(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="qm readiness test "))
        self.addCleanup(lambda: __import__("shutil").rmtree(base, ignore_errors=True))
        self.archive = base / "archive"
        self.artifact = base / "artifact"
        self.cache = base / "cache"

        def pointer(name, rid):
            manifest = self.archive / "releases" / rid / "manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            datasets = {"datasets": [
                {"api_name": api, "path": f"parquet/{api}-{rid[:8]}.parquet"}
                for api in ("daily", "fund_daily", "stk_limit", "trade_cal")]}
            manifest.write_text(json.dumps(datasets))
            (self.archive / name).write_text(json.dumps(
                {"release_id": rid, "manifest_sha256": hashlib.sha256(
                    manifest.read_bytes()).hexdigest()}))

        pointer("RESEARCH_CURRENT.json", RID)
        pointer("CURRENT.json", FULL)

        write_parquet(self.archive / f"parquet/daily-{RID[:8]}.parquet",
                      {"trade_date": ["20261001", "20261015"]})
        write_parquet(self.archive / f"parquet/fund_daily-{RID[:8]}.parquet",
                      {"trade_date": ["20261001", "20261015"]})
        write_parquet(self.archive / f"parquet/stk_limit-{RID[:8]}.parquet",
                      {"ts_code": ["510300.SH", "511010.SH", "518880.SH"],
                       "trade_date": ["20261015", "20261015", "20261015"],
                       "up_limit": [4.1, 1.1, 7.7], "down_limit": [3.4, 0.9, 6.3]})
        write_parquet(self.archive / f"parquet/stk_limit-{FULL[:8]}.parquet",
                      {"ts_code": ["000001.SZ"], "trade_date": ["20261015"]})
        for rid in (RID, FULL):
            write_parquet(self.archive / f"parquet/trade_cal-{rid[:8]}.parquet",
                          {"cal_date": ["20261015", "20261016", "20261017"],
                           "is_open": [1, 1, 0]})
        write_parquet(self.archive / f"parquet/daily-{FULL[:8]}.parquet",
                      {"trade_date": ["20261015"]})
        write_parquet(self.archive / f"parquet/fund_daily-{FULL[:8]}.parquet",
                      {"trade_date": ["20261015"]})

        cb = self.artifact / "ashare-takeover/trees/ashare-lab-ideas-cb/data/extra"
        write_parquet(cb / "cb_basic.parquet", {"ts_code": ["113000.SH"]})
        write_parquet(cb / "cb_call.parquet", {"ts_code": ["113000.SH"]})
        write_parquet(cb / "cb_daily/20260930.parquet",
                      {"ts_code": ["113000.SH"], "trade_date": ["20260930"]})
        cta = self.artifact / "ashare-takeover/trees/ashare-lab-ideas-cta/data/extra/i9_futures"
        for part in ("basic", "contracts", "mapping"):
            (cta / part).mkdir(parents=True, exist_ok=True)
            (cta / part / "x.parquet").write_bytes(b"")

    def report(self):
        return qa.build_report(self.archive, self.artifact, self.cache)

    def test_contract_keys_paths_and_states(self):
        report = self.report()
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(tuple(report["accounts"]), qa.ACCOUNTS)
        self.assertEqual(tuple(report["asset_inputs"]), qa.ASSET_KEYS)
        self.assertEqual(report["state"], "ready")
        self.assertEqual(report["usable_date"], "2026-10-15")
        self.assertEqual(report["calendar"]["confirmed_next_session"], "2026-10-16")
        self.assertTrue(report["calendar"]["path"].startswith("parquet/"))
        encoded = json.dumps(report)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn('"..', encoded)
        for name in qa.ACCOUNTS[:3]:
            self.assertEqual(report["accounts"][name]["state"], "ready", name)
        self.assertEqual(report["accounts"]["cta_combined"]["state"], "blocked")
        self.assertEqual(report["accounts"]["cta_trend"]["state"], "blocked")
        self.assertEqual(report["accounts"]["cb_double_low"]["state"], "pending")
        self.assertTrue(any("2026-09-30" in r for r in
                            report["accounts"]["cb_double_low"]["reasons"]))
        self.assertIn("multiplier", json.dumps(report["accounts"]["cta_combined"]))
        for key in qa.ASSET_KEYS:
            self.assertEqual(report["asset_inputs"][key]["state"],
                             report["accounts"][key]["state"], key)

    def test_s1_policy_a_blocks_when_real_limits_missing(self):
        path = self.archive / f"parquet/stk_limit-{RID[:8]}.parquet"
        write_parquet(path, {"ts_code": ["510300.SH"], "trade_date": ["20261015"]})
        report = self.report()
        self.assertEqual(report["asset_inputs"]["s1_invvol_etf"]["state"], "pending")
        self.assertTrue(any("insufficient" in r for r in
                            report["asset_inputs"]["s1_invvol_etf"]["reasons"]))

    def test_pending_calendar_downgrades_original_accounts_not_fake_ready(self):
        path = next((self.archive / "parquet").glob(f"trade_cal-{FULL[:8]}.parquet"))
        write_parquet(path, {"cal_date": ["20261015"], "is_open": [1]})
        self.cache.mkdir(parents=True, exist_ok=True)
        report = self.report()
        self.assertIsNone(report["calendar"]["confirmed_next_session"])
        for name in qa.ACCOUNTS[:3]:
            self.assertEqual(report["accounts"][name]["state"], "pending", name)

    def test_cache_reuse_keeps_cutoffs_stable(self):
        first = self.report()
        entries = list(self.cache.glob("*.json"))
        self.assertTrue(entries)
        second = self.report()
        self.assertEqual(first["per_api_cutoffs"], second["per_api_cutoffs"])

    def test_write_report_rejects_absolute_paths(self):
        bad = dict(self.report())
        bad["market"]["manifest_path"] = "/Users/leaked/manifest.json"
        with self.assertRaises(ValueError):
            qa.write_report(bad, self.cache / "out.json")


if __name__ == "__main__":
    unittest.main()
