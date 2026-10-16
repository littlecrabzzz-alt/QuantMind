"""Research intake boundaries; all market data here are synthetic test inputs."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

import research_case as case
import research_watch


class ResearchCaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "data/research_cases/test"
        self.cfg = case.read(case.DEFAULT_CONFIG)
        watch = self.root / "data/research_watch"
        watch.mkdir(parents=True)
        payload = {"key": self.cfg["source"]["key"], "url": self.cfg["source"]["url"]}
        encoded = json.dumps(payload, sort_keys=True)
        self.cfg["source"]["fingerprint"] = hashlib.sha256(encoded.encode()).hexdigest()
        with closing(sqlite3.connect(watch / "catalog.sqlite3")) as db:
            db.execute("CREATE TABLE versions (key TEXT, fingerprint TEXT, payload TEXT)")
            db.execute("INSERT INTO versions VALUES (?,?,?)", (payload["key"], self.cfg["source"]["fingerprint"], encoded))
            db.commit()
        case.write(watch / "digest_state.json", {"reviewed": {payload["key"]: {
            "fingerprint": self.cfg["source"]["fingerprint"], "reading_depth": "source only"}}})
        note = self.root / self.cfg["source"]["note"]
        note.parent.mkdir(parents=True)
        note.write_text("Synthetic source note")

    def populate(self, missing=True):
        for spec in self.cfg["datasets"]:
            path = self.root / spec["glob"].replace("*", "SH000001")
            path.parent.mkdir(parents=True, exist_ok=True)
            columns = {key: ["1", "2"] for key in spec["required_columns"]}
            columns.update({key: ["2026-01-01", "2026-01-02"] for key in spec["inspect_fields"]})
            if "time" in columns:
                columns["time"] = ["2020-01-01", "2026-08-31"]
            if spec["id"] == "industry_prices":
                columns["Category"] = ["宽基" if missing else "中信一级"] * 2
            if spec["id"] == "industry_members" and missing:
                del columns["known_at"]
            if spec["id"] == "etf_pcf" and missing:
                columns["tradingDay"] = ["", ""]
            pq.write_table(pa.table(columns), path)

    def test_registration_is_idempotent_and_contract_cannot_drift(self):
        case.register(self.root, self.out, self.cfg)
        before = case.sha256(self.out / "case.json")
        case.register(self.root, self.out, self.cfg)
        self.assertEqual(before, case.sha256(self.out / "case.json"))
        changed = copy.deepcopy(self.cfg)
        changed["protocol"]["comparison_window"][0] = "2022-10-01"
        with self.assertRaisesRegex(ValueError, "contract changed"):
            case.register(self.root, self.out, changed)
        self.assertEqual(before, case.sha256(self.out / "case.json"))

    def test_source_mismatch_and_warmup_off_by_one_rejected(self):
        changed = copy.deepcopy(self.cfg)
        changed["source"]["fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Source version missing"):
            case.register(self.root, self.out, changed)
        changed = copy.deepcopy(self.cfg)
        changed["protocol"]["min_price_observations"] = 318
        with self.assertRaisesRegex(ValueError, "319 observations"):
            case.validate(changed)
        case.validate(self.cfg)

    def test_real_schema_gaps_block_and_rechecks_preserve_history(self):
        self.populate()
        state = case.check(self.root, self.out, self.cfg)
        self.assertEqual(state["workflow_stage"], "blocked_data")
        self.assertEqual(set(state["readiness"].values()), {"blocked"})
        report = case.read(self.out / state["latest_check"] / "report.json")
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertEqual(by_id["calendar"]["status"], "passed")
        self.assertEqual(by_id["industry_prices"]["status"], "blocked")
        self.assertEqual(by_id["industry_members"]["status"], "blocked")
        self.assertEqual(by_id["etf_pcf"]["status"], "blocked")
        second = case.check(self.root, self.out, self.cfg)
        self.assertNotEqual(state["latest_check"], second["latest_check"])
        self.assertEqual(len(list((self.out / "checks").iterdir())), 2)
        self.assertFalse(case.verify(self.out)["local_reproduction"])
        (self.out / state["latest_check"] / "manifest.json").unlink()
        with self.assertRaisesRegex(ValueError, "Completed audit missing"):
            case.verify(self.out)

    def test_schema_success_is_not_semantic_or_reproduction_success(self):
        self.populate(missing=False)
        state = case.check(self.root, self.out, self.cfg)
        self.assertEqual(state["workflow_stage"], "awaiting_data_review")
        self.assertEqual(set(state["readiness"].values()), {"needs_review"})
        self.assertFalse(state["local_reproduction"])
        self.assertFalse(state["automatic_trading_authorized"])
        # This deliberately includes nonsensical dates/prices in some fields:
        # mere schema availability must never promote them to executable data.

    def test_short_price_history_is_blocked(self):
        self.populate(missing=False)
        spec = next(s for s in self.cfg["datasets"] if s["id"] == "etf_prices")
        path = self.root / spec["glob"].replace("*", "SH000001")
        pq.write_table(pa.table({"time": ["2026-08-28"], "open": [1.], "close": [1.],
                                 "volume": [100], "amount": [100.]}), path)
        result = case.inspect_dataset(self.root, spec, self.cfg["protocol"]["comparison_window"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Observed dates do not cover", " ".join(result["reasons"]))

    def test_state_and_artifact_tampering_rejected(self):
        state = case.check(self.root, self.out, self.cfg)
        changed = {**state, "local_reproduction": True}
        case.write(self.out / "state.json", changed)
        with self.assertRaises(ValueError):
            case.verify(self.out)
        case.write(self.out / "state.json", state)
        report = self.out / state["latest_check"] / "report.json"
        report.write_text("{}")
        with self.assertRaisesRegex(ValueError, "Artifact changed"):
            case.verify(self.out)

    def test_registration_cannot_claim_validation_or_change_identity(self):
        case.register(self.root, self.out, self.cfg)
        state = case.read(self.out / "state.json")
        case.write(self.out / "state.json", {**state, "learning_status": "validated"})
        with self.assertRaisesRegex(ValueError, "registered state"):
            case.verify(self.out)
        case.write(self.out / "state.json", state)
        identity = case.read(self.out / "case.json")
        case.write(self.out / "case.json", {**identity, "case_id": "unrelated-method"})
        with self.assertRaisesRegex(ValueError, "identity differs"):
            case.verify(self.out)

    def test_source_index_preserves_other_cases_and_original_review(self):
        watch = self.root / "data/research_watch"
        digest_before = case.sha256(watch / "digest_state.json")
        other = {"title": "keep", "case_path": "/test/other", "state": {"workflow_stage": "registered"}}
        case.write(watch / "research_case_state.json", {"schema_version": 1, "cases": {"other": other}})
        case.register(self.root, self.out, self.cfg)
        case.sync_index(self.root, self.out)
        case.sync_index(self.root, self.out)
        index = case.read(watch / "research_case_state.json")
        self.assertEqual(len(index["cases"]), 2)
        self.assertEqual(index["cases"]["other"], other)
        self.assertEqual(digest_before, case.sha256(watch / "digest_state.json"))
        # The daily collector can read the linkage without executing the case.
        progress = research_watch.research_case_progress(watch)
        self.assertEqual(progress["status"], "recorded_not_reverified")
        self.assertEqual(len(progress["cases"]), 2)
        (watch / "research_case_state.json").write_text("broken JSON")
        self.assertEqual(research_watch.research_case_progress(watch)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
