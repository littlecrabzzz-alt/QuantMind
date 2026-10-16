"""Contract regressions for the paper-readiness v1 producer: exact keys,
two-root relative paths, honest states from independently verified evidence
(byte hashes plus row-level dates, never file names or declared values),
required-bar completeness, calendar next-session computed from real open days,
and cache reuse. Synthetic parquet fixtures only; no archive access."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Shared datasets() iterator lives in the candidate repo scripts tree; the
# deployed QA runs alongside it in the same scripts directory.
sys.path.insert(0, str(Path.home() / "code/quantmind-aline/scripts"))
from scripts import paper_readiness_qa as qa  # noqa: E402

RID = "data-" + "a" * 64
FULL = "data-" + "b" * 64
EPOCH = "20990101T000000000000Z"


def write_parquet(path, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReadinessQA(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="qm readiness test "))
        self.addCleanup(lambda: __import__("shutil").rmtree(base, ignore_errors=True))
        self.archive = base / "archive"
        self.artifact = base / "artifact"
        self.cache = base / "cache"
        self._archive_fixture()
        self._cb_cta_fixture()

    def _archive_fixture(self):
        def pointer(name, rid, apis):
            manifest = self.archive / "releases" / rid / "manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps(
                {"datasets": [{"api_name": api, "path": f"parquet/{api}-{rid[:8]}.parquet",
                               "quality_state": "sample_ok"}
                              for api in apis]}))
            (self.archive / name).write_text(json.dumps(
                {"release_id": rid, "manifest_sha256": sha(manifest)}))

        bar_apis = list(qa.BAR_APIS)
        pointer("RESEARCH_CURRENT.json", RID, bar_apis + ["fund_adj"])
        pointer("CURRENT.json", FULL, ["trade_cal"])
        for api in bar_apis:
            write_parquet(self.archive / f"parquet/{api}-{RID[:8]}.parquet",
                          {"ts_code": ["000001.SZ"], "trade_date": ["20261015"]})
        write_parquet(self.archive / f"parquet/fund_adj-{RID[:8]}.parquet",
                      {"ts_code": ["510300.SH"], "trade_date": ["20261015"]})
        # Real open days with a gap: next session after 10-15 is 10-19 (10-16/17
        # closed), so weekday or +1day inference would fail.
        october = [f"202610{d:02d}" for d in range(1, 32)]
        november = ["20261101", "20261102"]
        open_flags = [0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1,
                      1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1]
        write_parquet(self.archive / f"parquet/trade_cal-{FULL[:8]}.parquet",
                      {"cal_date": october + november,
                       "is_open": open_flags[:len(october)] + [0, 1]})

    def _cb_cta_fixture(self):
        cb = self.artifact / "ashare-takeover/trees/cb/data/extra"
        # File name deliberately unrelated to its rows: names are not data.
        write_parquet(cb / "cb_daily/20200101.parquet",
                      {"ts_code": ["113000.SH"], "trade_date": ["20261015"],
                       "cb_over_rate": [12.3]})
        cta = self.artifact / "ashare-takeover/trees/cta/data/extra/i9"
        write_parquet(cta / "basic.parquet",
                      {"ts_code": ["CU2612.SHF"], "multiplier": [5]})
        write_parquet(cta / "mapping.parquet",
                      {"ts_code": ["CU2612.SHF"], "trade_date": ["20261015"],
                       "mapping_ts_code": ["CU2612.SHF"]})
        write_parquet(cta / "contracts/CU2612.parquet",
                      {"ts_code": ["CU2612.SHF"], "trade_date": ["20261015"],
                       "settle": [78000.0]})

    def _etf_parquet(self):
        path = self.artifact / "prepared/etf-normalized.parquet"
        write_parquet(path, {
            "date": ["2026-10-15"] * 3,
            "code": ["510300.SH", "511010.SH", "518880.SH"],
            "open": [4.0, 1.05, 7.2], "close": [4.05, 1.06, 7.3],
            "adj": [1.0, 1.0, 1.0], "amount": [1e8, 5e7, 3e7],
            "volume": [2.4e6, 4.7e6, 4.1e5],
            "up_limit": [4.41, 1.155, 8.03], "down_limit": [3.61, 0.945, 6.57]})
        return path

    def _deliver(self, etf_path=None, mutate=None):
        etf_path = etf_path or self._etf_parquet()
        epoch = self.artifact / qa.EVIDENCE_REL / "assets-testcanonical"
        epoch.mkdir(parents=True, exist_ok=True)
        manifest = self.artifact / "prepared/supplement-manifest.json"
        files = {}
        for rel in ("prepared/etf-normalized.parquet",
                    "ashare-takeover/trees/cb/data/extra/cb_daily/20200101.parquet",
                    "ashare-takeover/trees/cta/data/extra/i9/basic.parquet",
                    "ashare-takeover/trees/cta/data/extra/i9/contracts/CU2612.parquet"):
            files[rel] = {"bytes": (self.artifact / rel).stat().st_size,
                          "sha256": sha(self.artifact / rel)}
        manifest.write_text(json.dumps({"schema_version": 1, "files": files}))
        if mutate:
            mutate()
        etf_entry = {"path": "prepared/etf-normalized.parquet", "version": "e1",
                     "manifest_path": "prepared/supplement-manifest.json",
                     "manifest_sha256": sha(manifest),
                     "evidence": {"replay_start": "2026-10-01"}}
        cb_entry = {"path": "ashare-takeover/trees/cb/data/extra", "version": "c1",
                    "manifest_path": "prepared/supplement-manifest.json",
                    "manifest_sha256": sha(manifest)}
        cta_entry = {"path": "ashare-takeover/trees/cta/data/extra/i9", "version": "f1",
                     "manifest_path": "prepared/supplement-manifest.json",
                     "manifest_sha256": sha(manifest)}
        evidence = {"schema_version": 1,
                    "inputs": {"i7_turn_of_month": etf_entry,
                               "s1_invvol_etf": etf_entry,
                               "cb_double_low": cb_entry,
                               "cta_combined": cta_entry, "cta_trend": cta_entry},
                    "errors": {}, "calendar_candidates": []}
        bundle = epoch / "bundle.json"
        bundle.write_text(json.dumps({"schema_version": 1,
                                      "data_identity": "test-identity",
                                      "evidence": evidence}))
        (self.artifact / qa.EVIDENCE_REL / "CURRENT.json").write_text(json.dumps({
            "schema_version": 1, "data_identity": "test-identity",
            "bundle_path": "ashare-input-supplements/assets-testcanonical/bundle.json",
            "bundle_sha256": sha(bundle)}))

    def report(self):
        return qa.build_report(self.archive, self.artifact, self.cache)

    def test_no_delivery_leaves_assets_pending_with_dynamic_reason(self):
        report = self.report()
        for key in qa.ASSET_KEYS:
            self.assertEqual(report["asset_inputs"][key]["state"], "pending", key)
            self.assertIn("not yet present",
                          report["asset_inputs"][key]["reasons"][0])

    def test_delivered_evidence_flips_states_via_independent_verification(self):
        self._deliver()
        report = self.report()
        self.assertEqual(report["usable_date"], "2026-10-15")
        self.assertEqual(report["calendar"]["confirmed_next_session"], "2026-10-18")
        for key in qa.ASSET_KEYS:
            self.assertEqual(report["asset_inputs"][key]["state"], "ready", key)
            self.assertEqual(report["accounts"][key]["state"], "ready", key)
        self.assertTrue(report["asset_inputs"]["i7_turn_of_month"]["path"]
                        .startswith("prepared/"))
        self.assertEqual(report["asset_bundle"]["data_identity"], "test-identity")
        self.assertEqual(report["asset_bundle"]["pointer_path"],
                         "ashare-input-supplements/CURRENT.json")
        i7_input = report["asset_inputs"]["i7_turn_of_month"]
        self.assertEqual(i7_input["path"], "prepared/etf-normalized.parquet")
        encoded = json.dumps(report)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn('"..', encoded)

    def test_i7_only_pending_when_month_context_incomplete(self):
        self._deliver()
        write_parquet(self.archive / f"parquet/trade_cal-{FULL[:8]}.parquet",
                      {"cal_date": ["20261015", "20261016", "20261020",
                                    "20261101", "20261102"],
                       "is_open": [1, 1, 1, 0, 1]})
        self.cache.mkdir(parents=True, exist_ok=True)
        report = self.report()
        self.assertEqual(report["calendar"]["confirmed_next_session"], "2026-10-16")
        self.assertEqual(report["calendar_context"]["complete"], False)
        self.assertEqual(report["asset_inputs"]["i7_turn_of_month"]["state"],
                         "pending")
        self.assertIn("natural days lack a real SSE calendar row",
                      report["asset_inputs"]["i7_turn_of_month"]["reasons"][0])
        # The month-context gate is I7-only: the delivered s1 stays ready.
        self.assertEqual(report["asset_inputs"]["s1_invvol_etf"]["state"], "ready")
        self.assertEqual(report["accounts"]["i7_turn_of_month"]["state"], "pending")

    def test_tampered_file_is_blocked_by_byte_hash(self):
        self._deliver(mutate=lambda: write_parquet(
            self.artifact / "prepared/etf-normalized.parquet",
            {"date": ["2026-10-15"], "code": ["510300.SH"], "open": [1], "close": [1],
             "adj": [1], "amount": [1], "volume": [1], "up_limit": [1],
             "down_limit": [1]}))
        report = self.report()
        self.assertEqual(report["asset_inputs"]["i7_turn_of_month"]["state"], "blocked")
        self.assertTrue(any("sha256 mismatch" in r for r in
                            report["asset_inputs"]["i7_turn_of_month"]["reasons"]))

    def test_s1_blocked_when_limits_missing_at_usable_date(self):
        path = self.artifact / "prepared/etf-normalized.parquet"
        write_parquet(path, {
            "date": ["2026-10-15"] * 3, "code": list(qa.ETF_LIMIT_CODES),
            "open": [1, 1, 1], "close": [1, 1, 1], "adj": [1, 1, 1],
            "amount": [1, 1, 1], "volume": [1, 1, 1],
            "up_limit": [4.4, None, 8.0], "down_limit": [3.6, None, 6.5]})
        self._deliver(etf_path=path)
        report = self.report()
        self.assertEqual(report["asset_inputs"]["s1_invvol_etf"]["state"], "blocked")
        self.assertTrue(any("lack real up_limit/down_limit" in r for r in
                            report["asset_inputs"]["s1_invvol_etf"]["reasons"]))

    def test_cta_blocked_without_multiplier_and_cb_blocked_on_row_dates(self):
        self._deliver()
        write_parquet(self.artifact / "ashare-takeover/trees/cta/data/extra/i9/basic.parquet",
                      {"ts_code": ["CU2612.SHF"]})
        write_parquet(self.artifact / "ashare-takeover/trees/cb/data/extra/cb_daily/20200101.parquet",
                      {"ts_code": ["113000.SH"], "trade_date": ["20260930"],
                       "cb_over_rate": [12.3]})
        report = self.report()
        self.assertEqual(report["asset_inputs"]["cta_combined"]["state"], "blocked")
        self.assertTrue(any("multiplier" in r for r in
                            report["asset_inputs"]["cta_combined"]["reasons"]))
        self.assertEqual(report["asset_inputs"]["cb_double_low"]["state"], "blocked")
        self.assertTrue(any("row-level max trade_date 2026-09-30" in r for r in
                            report["asset_inputs"]["cb_double_low"]["reasons"]))

    def test_missing_required_bar_api_blocks_instead_of_min_of_rest(self):
        (self.archive / f"parquet/daily-{RID[:8]}.parquet").unlink()
        self.cache.mkdir(parents=True, exist_ok=True)
        report = self.report()
        self.assertIsNone(report["usable_date"])
        self.assertEqual(report["state"], "blocked")
        self.assertTrue(any("missing row-level dates" in r and "daily" in r
                            for r in report["reasons"]))

    def test_artifact_root_resolution_chain(self):
        root, reason = qa.resolve_artifact_root("/explicit/path")
        self.assertEqual(str(root), "/explicit/path")
        os.environ[qa.MARKER_ENV] = "/from/env"
        try:
            root, reason = qa.resolve_artifact_root()
            self.assertEqual(str(root), "/from/env")
        finally:
            del os.environ[qa.MARKER_ENV]
        marker = Path.home() / "Library/Application Support/QuantMind/market-source/paper-artifact-root"
        saved = marker.read_text() if marker.exists() else None
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("/from/marker")
        try:
            root, reason = qa.resolve_artifact_root()
            self.assertEqual(str(root), "/from/marker")
        finally:
            if saved is None:
                marker.unlink()
            else:
                marker.write_text(saved)
        root, reason = qa.resolve_artifact_root()
        self.assertIsNone(root)
        self.assertIn("unresolved", reason)

    def test_write_report_rejects_absolute_paths(self):
        bad = dict(self.report())
        bad["market"]["manifest_path"] = "/Users/leaked/manifest.json"
        with self.assertRaises(ValueError):
            qa.write_report(bad, self.cache / "out.json")


if __name__ == "__main__":
    unittest.main()
