"""Offline projection equivalence; --benchmark measures a bounded wide fixture."""

import ast
import gc
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import time
import tracemalloc
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import Pipeline, json_bytes


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.p = Pipeline(self.root, {"entries": []})
        self.addCleanup(self.p.close)
        self.network = patch(
            "socket.socket.connect", side_effect=AssertionError("offline")
        )
        self.network.start()
        self.addCleanup(self.network.stop)
        self.number = 0
        (self.root / "objects").mkdir(exist_ok=True)

    def body(self, fields, items, api="stock_basic", status="sample_ok"):
        self.number += 1
        raw = json_bytes(
            {"request_id": self.number, "data": {"fields": fields, "items": items}}
        )
        sha = hashlib.sha256(raw).hexdigest()
        (self.root / "objects" / (sha + ".json")).write_bytes(raw)
        return {"api_name": api, "status": status, "object_sha256": sha}

    def save(self, result):
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            (str(self.number), 1, json.dumps(result)),
        )
        self.p.db.commit()

    def baseline(self):
        original = self.p.records
        with patch.object(
            self.p, "records", side_effect=lambda saved, **kw: original(saved)
        ):
            return self.p.identifiers()

    def test_last_duplicate_null_unknown_and_default(self):
        saved = self.body(
            ["ts_code", "unknown", "ts_code", "value"],
            [["old", {"x": [1]}, "T600018.SH", None]],
        )
        complete = self.p.records(saved)
        self.assertEqual(
            complete, [{"ts_code": "T600018.SH", "unknown": {"x": [1]}, "value": None}]
        )
        self.assertEqual(
            self.p.records(saved, fields={"ts_code", "value", "absent"}),
            [{"ts_code": "T600018.SH", "value": None}],
        )
        self.assertEqual(self.p.records(saved, fields=set()), [{}])

    def test_malformed_unselected_columns_still_fail(self):
        for fields, row in [
            (["ts_code", "extra"], ["x"]),
            (["ts_code"], ["x", 2]),
            ([["unhashable"]], [3]),
            (["ts_code"], None),
        ]:
            saved = self.body(fields, [row])
            with self.subTest(fields=fields, row=row):
                with self.assertRaises((ValueError, TypeError)) as old:
                    self.p.records(saved)
                with self.assertRaises(type(old.exception)):
                    self.p.records(saved, fields={"not_present"})
        self.assertEqual(
            self.p.records(self.body(["a", "b"], ["xy"]), fields={"b"}), [{"b": "y"}]
        )

    def test_discovery_all_branches_and_sources_equal(self):
        cases = [
            ("stock_basic", {"ts_code": "T600018.SH"}),
            ("hk_basic", {"ts_code": "02121!AE.HK"}),
            ("etf_basic", {"ts_code": "510300.SH"}),
            ("index_classify", {"index_code": "801010.SI", "level": "L3"}),
            ("index_classify", {"index_code": "801020.SI", "level": "L2"}),
            ("fut_basic", {"ts_code": "IFL.CFX", "fut_code": "IF"}),
            ("bse_mapping", {"o_code": "830001.BJ", "n_code": "920001.BJ"}),
            ("hm_list", {"name": "old desk"}),
            ("hm_detail", {"ts_code": "000001.SZ", "hm_name": "new desk"}),
            (
                "ci_index_member",
                {
                    "ts_code": "600000.SH",
                    "l1_code": "CI005001.CI",
                    "l2_code": "CI005101.CI",
                    "l3_code": "CI005201.CI",
                },
            ),
            ("tdx_member", {"ts_code": "880001.TDX", "con_code": "T600018.SH"}),
            ("kpl_concept_cons", {"ts_code": "123456.KPL", "con_code": "000002.SZ"}),
        ]
        for api, row in cases:
            row["ignored"] = [0, "-", None]
            self.save(
                self.body(list(row), [list(row.values())], api, "possibly_truncated")
            )
        actual = self.p.identifiers()
        self.assertEqual(json_bytes(actual), json_bytes(self.baseline()))
        self.assertEqual(actual["hot_money_names"], ["new desk", "old desk"])
        self.assertIn("000002.SZ", actual["market_sentiment_stocks"])
        self.assertNotIn("600000.SH", actual["cross_asset_indexes"])
        self.assertIn("02121!AE.HK", actual["hk_stocks"])
        # Jobs and attempts participate; updating a job never removes an old attempt.
        saved = self.body(["ts_code"], [["600018.SH"]], "daily")
        jobid = self.p.enqueue("daily", {"trade_date": "20260908"}, 25, "history")
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(saved), jobid)
        )
        self.p.db.commit()
        updated = self.p.identifiers()
        self.assertEqual(json_bytes(updated), json_bytes(self.baseline()))
        self.assertIn("T600018.SH", updated["technical_stocks"])
        self.assertIn("600018.SH", updated["technical_stocks"])

    def test_projection_inventory_covers_static_record_accesses(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(Pipeline.identifiers)))
        literals = set()
        selected = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "discovery_fields"
                for t in node.targets
            ):
                selected = set(ast.literal_eval(node.value.args[0]))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "record"
                and node.func.attr == "get"
                and isinstance(node.args[0], ast.Constant)
            ):
                literals.add(node.args[0].value)
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "record"
                and isinstance(node.slice, ast.Constant)
            ):
                literals.add(node.slice.value)
        self.assertTrue(literals <= selected, literals - selected)
        self.assertTrue(
            {"l1_code", "l2_code", "l3_code", "o_code", "n_code"} <= selected
        )

    def benchmark(self):
        # 4 immutable responses, 6000 rows each and 342 source columns. No dedup
        # hits: this isolates projection, not repeated-response elimination.
        fields = ["ts_code"] + [f"value_{i}" for i in range(341)]
        for _ in range(4):
            items = [
                [f"{i:06d}.SZ"] + [i + j * 0.25 for j in range(341)]
                for i in range(6000)
            ]
            self.save(self.body(fields, items, "stk_factor_pro"))
        del items
        report = {
            "fixture": {
                "responses": 4,
                "rows_each": 6000,
                "columns": 342,
                "raw_bytes": sum(
                    p.stat().st_size for p in (self.root / "objects").iterdir()
                ),
            }
        }
        for label, function in [
            ("full", self.baseline),
            ("projected", self.p.identifiers),
        ]:
            gc.collect()
            start = time.perf_counter()
            value = function()
            elapsed = time.perf_counter() - start
            gc.collect()
            tracemalloc.start()
            function()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            report[label] = {
                "elapsed_seconds": elapsed,
                "peak_traced_bytes": peak,
                "output_sha256": hashlib.sha256(json_bytes(value)).hexdigest(),
                "discovery": self.p.identifier_timing,
            }
        assert report["full"]["output_sha256"] == report["projected"]["output_sha256"]
        assert (
            report["projected"]["peak_traced_bytes"]
            < report["full"]["peak_traced_bytes"]
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if "--benchmark" in sys.argv:
        case = ProjectionTest()
        case.setUp()
        try:
            case.benchmark()
        finally:
            case.doCleanups()
    else:
        unittest.main()
