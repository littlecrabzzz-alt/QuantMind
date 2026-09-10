"""Malformed discovery leaves cannot starve valid stock-context supplements."""

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_equity_event_contracts import _stocks
from backend.shared.tushare_registry import technical_extra_runtime_prerequisites
from backend.shared.tushare_stock_context_contracts import (
    iter_stock_context_jobs,
    stock_context_prerequisites,
    stock_context_stock_inventory,
)
from test_tushare_stock_context_pipeline import source
import test_tushare_technical_extra_pipeline as fixtures

TODAY = date(2026, 9, 10)
CONFIG = {
    "enable_stock_context": True,
    "stock_context_apis": ["stk_rewards", "stk_managers"],
    "stock_context_history_start": "20260904",
    "plan_jobs_per_tick": 10,
}
GAP_SCOPE = "planning:stock_context:stk_rewards:malformed_stock_supplier_identifiers"


class StockInventoryValidation(unittest.TestCase):
    def test_valid_leaves_continue_without_repair_or_mutating_discovery(self):
        ids = {"stocks": ["X20720.SZ", "000001.SZ", {"ts_code": "T600001.SH"}]}
        original = deepcopy(ids)
        stocks, inventory = stock_context_stock_inventory(ids)
        self.assertEqual(stocks, ["000001.SZ", "T600001.SH"])
        self.assertEqual(inventory["invalid_identifier_count"], 1)
        self.assertEqual(
            inventory["invalid_identifier_examples"][0]["source_code"], "X20720.SZ"
        )
        self.assertFalse(inventory["source_inventory_complete"])
        jobs = list(iter_stock_context_jobs(CONFIG, TODAY, ids))
        reward_codes = {
            j["params"]["ts_code"] for j in jobs if j["api_name"] == "stk_rewards"
        }
        self.assertEqual(reward_codes, set(stocks))
        self.assertTrue(any(j["api_name"] == "stk_managers" for j in jobs))
        self.assertEqual(ids, original)

    def test_gap_examples_are_bounded_and_arbitrary_text_is_not_echoed(self):
        values = ["X20720.SZ", "not a code: arbitrary private text", None] + [
            f"X{i}.SZ" for i in range(9)
        ]
        ids = {"stocks": values + ["000001.SZ"]}
        gap = next(
            g
            for g in stock_context_prerequisites(ids, config=CONFIG)
            if g["reason"] == "malformed_stock_supplier_identifiers"
        )
        self.assertEqual(gap["invalid_identifier_count"], 12)
        self.assertEqual(gap["valid_stock_count"], 1)
        self.assertEqual(len(gap["invalid_identifier_examples"]), 5)
        self.assertNotIn("arbitrary private text", json.dumps(gap))
        self.assertTrue(
            all(
                len(x["value_sha256"]) == 64 for x in gap["invalid_identifier_examples"]
            )
        )
        self.assertEqual(
            gap["dependencies"], []
        )  # reason-specific capability, not overwritten by discovery gap

    def test_container_errors_and_other_families_remain_strict(self):
        for ids in ([], {"stocks": {}}, {"stocks": "000001.SZ"}):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                stock_context_prerequisites(ids, config=CONFIG)
        with self.assertRaisesRegex(ValueError, "Invalid stock supplier identifier"):
            _stocks({"stocks": ["000001.SZ", "X20720.SZ"]})
        with self.assertRaisesRegex(ValueError, "Invalid stock supplier identifier"):
            technical_extra_runtime_prerequisites(
                {"technical_stocks": ["000001.SZ", "X20720.SZ"]},
                config={"technical_extra_apis": ["cyq_perf"]},
            )


class StockInventoryRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    capture = fixtures.TechnicalExtraRuntime.capture
    discovery = fixtures.TechnicalExtraRuntime.discovery

    def test_all_54_observed_pairs_resume_and_bad_source_stays_a_gap(self):
        # Synthetic equivalent of 54 actual code/period identities, not a claim
        # that this fixture is the production history or a complete period set.
        pairs = {
            (code, f"{year}1231")
            for code in ("000001.SZ", "T600001.SH")
            for year in range(1999, 2026)
        }
        self.assertEqual(len(pairs), 54)
        self.discovery("stk_managers", [{"ts_code": "X20720.SZ"}])
        parent, _, _ = self.capture(
            "stk_rewards",
            {"ts_code": "000001.SZ"},
            [
                source("stk_rewards", ts_code=code, end_date=period)
                for code, period in sorted(pairs)
            ],
            more=True,
        )
        parent_before = tuple(
            self.p.db.execute(
                "SELECT * FROM jobs WHERE id=?", (parent["id"],)
            ).fetchone()
        )
        raw_before = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.root / "objects").rglob("*")
            if p.is_file()
        }
        self.assertTrue(raw_before)
        ids_before = self.p.identifiers()
        self.assertIn("X20720.SZ", ids_before["stock_context_stocks"])
        self.assertEqual(len(ids_before["stock_context_reward_periods"]), 54)
        self.p.db.execute(
            "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?)",
            (
                "planning:stock_context",
                "validation_blocked",
                "2026-09-10T00:01:40Z",
                '{"reason":"Invalid stock supplier identifier"}',
            ),
        )
        self.p.db.commit()
        for _ in range(20):
            self.p.plan_extended(CONFIG, TODAY)
        histories = [
            json.loads(r[0])
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE json_extract(job, '$.api_name')='stk_rewards' AND epoch='history'"
            )
        ]
        self.assertEqual(
            {(j["params"]["ts_code"], j["params"]["end_date"]) for j in histories},
            pairs,
        )
        gap_row = self.p.db.execute(
            "SELECT status,reason FROM capability WHERE scope=?", (GAP_SCOPE,)
        ).fetchone()
        self.assertEqual(gap_row[0], "coverage_unverified")
        gap = json.loads(gap_row[1])
        self.assertEqual(gap["invalid_identifier_count"], 1)
        self.assertEqual(
            gap["invalid_identifier_examples"][0]["source_code"], "X20720.SZ"
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:stock_context'"
            ).fetchone()[0],
            "validation_passed",
        )
        planned = [
            json.loads(r[0])
            for r in self.p.db.execute("SELECT job FROM jobs WHERE state='pending'")
        ]
        self.assertTrue(any(j["api_name"] == "stk_managers" for j in planned))
        self.assertTrue(any(j["params"] == {"ts_code": "000001.SZ"} for j in planned))
        self.assertNotIn("X20720.SZ", json.dumps(planned))
        self.assertEqual(self.p.identifiers(), ids_before)
        self.assertEqual(
            tuple(
                self.p.db.execute(
                    "SELECT * FROM jobs WHERE id=?", (parent["id"],)
                ).fetchone()
            ),
            parent_before,
        )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )
        self.assertEqual(
            {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (self.root / "objects").rglob("*")
                if p.is_file()
            },
            raw_before,
        )
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(CONFIG, TODAY)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], count
        )


if __name__ == "__main__":
    unittest.main()
