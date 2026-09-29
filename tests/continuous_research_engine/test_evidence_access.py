"""Synthetic SQL tests; never reads a real result, market file or service."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.services.research_agent.continuous_evidence import inspect_evidence


class FakeDB:
    def __init__(self, cfg, result, status="completed", file_path=None):
        self.cfg, self.result, self.status = cfg, result, status
        self.calls = []
        self.owner = ("tenant-a", "00000001")
        self.changed = False
        self.file_path = file_path

    async def execute(self, sql, params):
        sql = str(sql)
        self.calls.append((sql, copy.deepcopy(params)))
        if (params["tenant"], params["user"]) != self.owner:
            row = None
        elif sql.startswith("SELECT status,config_json"):
            row = (self.status, copy.deepcopy(self.cfg))
        elif sql.startswith("SELECT result_json"):
            assert len(self.calls) == 2
            assert "status='completed'" in sql
            assert "config_json=CAST(:config AS jsonb)" in sql
            assert json.loads(params["config"]) == self.cfg
            row = None if self.changed else (copy.deepcopy(self.result), self.file_path)
        else:
            raise AssertionError("Unexpected SQL")
        return SimpleNamespace(first=lambda: row)


class EvidenceAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ident = "programme-one"
        self.bid = "r01bt-" + "a" * 32
        self.auth = SimpleNamespace(user_id="1", tenant_id="tenant-a")
        manifest = "b" * 64
        code = 'def on_signal(ctx):\n return {"targets": None}'
        self.exp = {
            "action": "experiment",
            "backtest_id": self.bid,
            "strategy_id": "61",
            "revision_id": "rev-1",
            "code": code,
            "parameters": {"symbols": ["510300.SH"], "lookback": 12},
            "start_date": "2015-01-05",
            "end_date": "2015-01-07",
            "name": "DO_NOT_EXPOSE_NAME",
            "hypothesis": "DO_NOT_EXPOSE_HYPOTHESIS",
        }
        self.t = {"id": "task-a", "kind": "research", "experiments": {"exp": self.exp}}
        self.c = {
            "contract": {
                "start_date": "2014-08-01",
                "end_date": "2026-03-24",
                "input_manifest_sha256": manifest,
                "symbols": ["510300.SH", "518880.SH"],
            },
            "tasks": {"task-a": self.t},
        }
        self.cfg = {
            "executor_kind": "r01_ledger",
            "strategy_id": "61",
            "strategy_revision": "rev-1",
            "strategy_version": 1,
            "research_id": self.ident,
            "research_case_id": self.ident,
            "start_date": "2015-01-05",
            "end_date": "2015-01-07",
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "validation_status": "development_only",
            "data_binding": {
                "manifest_sha256": manifest,
                "package_id": "etf-package-v2",
                "development_end": "2026-03-24",
            },
        }
        ledger = "r01-B1-s61-" + self.bid + "-v1-a0001"
        days = ["2015-01-05", "2015-01-06", "2015-01-07"]
        nav = [
            {
                "trade_date": d,
                "nav": 30000 + n,
                "nav_exact": 30000 + n + 0.00001,
                "cash": 20000,
                "dividend_receivable": 0,
                "market_value": 10000 + n,
                "valuation_reliable": True,
                "risk_status": "active",
                "positions": {
                    "510300.SH": {
                        "symbol": "510300.SH",
                        "qty": 100,
                        "avg_cost": 100,
                        "available_qty": 100,
                        "last_mark": 100,
                        "close": 100,
                        "mark_source": "eod_close",
                        "last_mark_date": d,
                        "market_value": 10000,
                        "private": "DO_NOT_EXPOSE_POSITION",
                    }
                },
                "private": "DO_NOT_EXPOSE_NAV",
            }
            for n, d in enumerate(days)
        ]
        fill = {
            "trade_date": days[0],
            "signal_date": "2015-01-02",
            "symbol": "510300.SH",
            "side": "buy",
            "price": 100,
            "quantity": 100,
            "commission": 5,
            "stamp_duty": 0,
            "transfer_fee": 0,
            "total_fee": 5,
            "total_fee_exact": 5,
            "price_source": "open",
            "private": "DO_NOT_EXPOSE_FILL",
        }
        order = {
            "trade_date": days[0],
            "signal_date": "2015-01-02",
            "client_order_id": ledger + ":1",
            "ledger_run_id": ledger,
            "symbol": "510300.SH",
            "side": "buy",
            "origin": "signal",
            "status": "filled",
            "reject_reason": None,
            "qty_target": 100,
            "qty_filled": 100,
            "qty_remaining": 0,
            "avg_fill_price": 100,
            "fees": 5,
            "fills": [fill],
            "private": "DO_NOT_EXPOSE_ORDER",
        }
        self.result = {
            "backtest_id": self.bid,
            "status": "completed",
            "user_id": "1",
            "tenant_id": "tenant-a",
            "config": {
                **copy.deepcopy(self.cfg),
                "parameters": copy.deepcopy(self.exp["parameters"]),
                "ledger_run_id": ledger,
                "research_title": "DO_NOT_EXPOSE_TITLE",
            },
            "ledger_evidence": {
                "session": {
                    "manifest_sha256": manifest,
                    "input_package_id": "etf-package-v2",
                    "is_fixture": False,
                    "strategy_id": "s61-" + self.bid,
                    "strategy_version": 1,
                    "ledger_run_id": ledger,
                    "match_assumptions": {"asset_type": "etf"},
                },
                "package": {
                    "manifest_sha256": manifest,
                    "package_id": "etf-package-v2",
                    "is_fixture": False,
                    "symbols": ["510300.SH", "518880.SH"],
                },
                "equity": nav,
                "orders": [order],
            },
            "ledger_view": {
                "session": {"ledger_run_id": ledger},
                "package": {"manifest_sha256": manifest},
                "days": [{"date": d} for d in days],
            },
            "strategy_decisions": [
                {
                    "execution_date": d,
                    "decision_date": prev,
                    "targets": None,
                    "reason": "DO_NOT_EXPOSE_REASON",
                    "state": {"private": "DO_NOT_EXPOSE_STATE"},
                }
                for d, prev in zip(days, ["2015-01-02", *days[:2]], strict=True)
            ],
            "equity_curve": [{"date": d, "value": 30000} for d in days],
            "drawdown_curve": [{"date": d, "value": 0} for d in days],
            "advanced_stats": {
                "actual_max_input_date": days[-1],
                "read_through": days[-1],
                "private": "DO_NOT_EXPOSE_STATS",
            },
            "private": "DO_NOT_EXPOSE_RESULT",
        }

    async def inspect(self, view="nav", task=None, **extra):
        db = FakeDB(self.cfg, self.result)
        packet = await inspect_evidence(
            self.ident,
            self.c,
            task or self.t,
            {
                "action": "inspect_evidence",
                "backtest_id": self.bid,
                "view": view,
                **extra,
            },
            self.auth,
            db,
        )
        return packet, db

    async def test_pagination_precision_sources_and_repeatability(self):
        before = copy.deepcopy(self.c)
        p, db = await self.inspect(limit=2)
        self.assertEqual((p["total"], p["next_offset"], len(p["rows"])), (3, 2, 2))
        self.assertEqual(p["rows"][0]["nav_exact"], 30000.00001)
        self.assertNotIn("result_json", db.calls[0][0])
        self.assertEqual(db.calls[0][1]["user"], "00000001")
        q, _ = await self.inspect(limit=2)
        self.assertEqual(p, q)
        tail, _ = await self.inspect(limit=2, offset=2)
        self.assertEqual((len(tail["rows"]), tail["next_offset"]), (1, None))
        empty, _ = await self.inspect(offset=99)
        self.assertEqual(
            (empty["rows"], empty["total"], empty["next_offset"]), ([], 3, None)
        )
        self.assertEqual(self.c, before)
        self.assertEqual(len(p["sources"]), 3)
        self.assertTrue(all(len(s["sha256"]) == 64 for s in p["sources"]))

    async def test_views_filter_and_no_unapproved_fields(self):
        for view in ("overview", "nav", "decisions", "orders", "fills"):
            with self.subTest(view=view):
                p, _ = await self.inspect(view)
                self.assertNotIn("DO_NOT_EXPOSE", json.dumps(p))
                self.assertEqual(p["boundary"], "2026-03-24")
        p, _ = await self.inspect("overview")
        self.assertEqual(p["rows"][0]["code"], self.exp["code"])
        self.assertEqual(p["rows"][0]["parameters"], self.exp["parameters"])
        p, _ = await self.inspect(start_date="2015-01-06", end_date="2015-01-06")
        self.assertEqual((p["total"], p["rows"][0]["trade_date"]), (1, "2015-01-06"))
        p, _ = await self.inspect("fills")
        self.assertEqual((p["total"], p["rows"][0]["total_fee_exact"]), (1, 5))

    async def test_review_requires_explicit_bound_id_but_research_can_compare_parent(
        self,
    ):
        review = {"kind": "evidence_review", "evidence": {"id": "packet-id"}}
        with self.assertRaisesRegex(ValueError, "review_backtest_not_authorized"):
            await self.inspect(task=review)
        review["evidence"]["allowed_backtest_ids"] = [self.bid]
        p, _ = await self.inspect(task=review)
        self.assertEqual(p["backtest_id"], self.bid)
        p, _ = await self.inspect(task={"kind": "research", "experiments": {}})
        self.assertEqual(p["backtest_id"], self.bid)

    async def test_unknown_stock_and_future_requests_stop_before_sql(self):
        cases = [
            {"backtest_id": "stock-unsafe"},
            {"backtest_id": "r01bt-" + "d" * 32},
            {"end_date": "2026-03-25"},
            {"start_date": "2014-07-31"},
            {"start_date": "20150105"},
            {"offset": True},
            {"offset": -1},
            {"limit": 121},
            {"limit": 0},
            {"path": "/tmp/anything"},
            {"view": []},
        ]
        for extra in cases:
            db = FakeDB(self.cfg, self.result)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                await inspect_evidence(
                    self.ident,
                    self.c,
                    self.t,
                    {
                        "action": "inspect_evidence",
                        "backtest_id": self.bid,
                        "view": "nav",
                        **extra,
                    },
                    self.auth,
                    db,
                )
            self.assertEqual(db.calls, [])
        self.t["kind"] = "stock_factor"
        with self.assertRaisesRegex(ValueError, "task_kind_denied"):
            await self.inspect()
        with self.assertRaisesRegex(ValueError, "etf_experiment_required"):
            await self.inspect(task={"kind": "research"})

    async def test_bad_metadata_never_selects_payload(self):
        mutations = [
            ("executor_kind", "stock_factor"),
            ("research_id", "other-programme"),
            ("research_case_id", "other-programme"),
            ("strategy_revision", "other-rev"),
            ("strategy_id", "62"),
            ("code_sha256", "c" * 64),
            ("end_date", "2026-03-25"),
            ("start_date", "2014-07-31"),
            ("data_binding", {**self.cfg["data_binding"], "manifest_sha256": "d" * 64}),
        ]
        for key, value in mutations:
            db = FakeDB({**self.cfg, key: value}, self.result)
            with self.subTest(key=key), self.assertRaises(ValueError):
                await inspect_evidence(
                    self.ident,
                    self.c,
                    self.t,
                    {
                        "action": "inspect_evidence",
                        "backtest_id": self.bid,
                        "view": "nav",
                    },
                    self.auth,
                    db,
                )
            self.assertEqual(len(db.calls), 1)
            self.assertNotIn("result_json", db.calls[0][0])
        for status in ("running", "failed", "pending"):
            db = FakeDB(self.cfg, self.result, status)
            with self.assertRaisesRegex(ValueError, "completed_run_required"):
                await inspect_evidence(
                    self.ident,
                    self.c,
                    self.t,
                    {
                        "action": "inspect_evidence",
                        "backtest_id": self.bid,
                        "view": "nav",
                    },
                    self.auth,
                    db,
                )
            self.assertEqual(len(db.calls), 1)

    async def test_other_owner_and_read_race_are_rejected(self):
        for auth in (
            SimpleNamespace(user_id="2", tenant_id="tenant-a"),
            SimpleNamespace(user_id="1", tenant_id="tenant-b"),
        ):
            db = FakeDB(self.cfg, self.result)
            with self.assertRaisesRegex(ValueError, "owned_run_missing"):
                await inspect_evidence(
                    self.ident,
                    self.c,
                    self.t,
                    {
                        "action": "inspect_evidence",
                        "backtest_id": self.bid,
                        "view": "nav",
                    },
                    auth,
                    db,
                )
            self.assertEqual(len(db.calls), 1)
        db = FakeDB(self.cfg, self.result)
        db.changed = True
        with self.assertRaisesRegex(ValueError, "run_changed_during_read"):
            await inspect_evidence(
                self.ident,
                self.c,
                self.t,
                {"action": "inspect_evidence", "backtest_id": self.bid, "view": "nav"},
                self.auth,
                db,
            )

    async def test_result_identity_future_rows_and_stock_symbols_rejected(self):
        original = copy.deepcopy(self.result)
        mutations = [
            lambda r: r.update(user_id="2"),
            lambda r: r["config"].update(strategy_revision="wrong"),
            lambda r: r["ledger_evidence"]["package"].update(manifest_sha256="c" * 64),
            lambda r: r["ledger_evidence"]["equity"][-1].update(
                trade_date="2026-03-25"
            ),
            lambda r: r["ledger_view"]["days"][-1].update(date="2026-03-25"),
            lambda r: r["strategy_decisions"][-1].update(execution_date="2026-03-25"),
            lambda r: r["strategy_decisions"][0].update(decision_date="2015-01-05"),
            lambda r: r["ledger_evidence"]["orders"][0].update(symbol="600000.SH"),
            lambda r: r["advanced_stats"].update(actual_max_input_date="2026-03-25"),
        ]
        for i, mutate in enumerate(mutations):
            self.result = copy.deepcopy(original)
            mutate(self.result)
            with self.subTest(case=i), self.assertRaises(ValueError):
                await self.inspect(
                    limit=1
                )  # Future data beyond this page is still denied.

    async def test_registered_stock_symbols_denied_before_db(self):
        self.exp["parameters"]["symbols"] = ["600000.SH"]
        db = FakeDB(self.cfg, self.result)
        with self.assertRaisesRegex(ValueError, "symbols_outside_contract"):
            await inspect_evidence(
                self.ident,
                self.c,
                self.t,
                {"action": "inspect_evidence", "backtest_id": self.bid, "view": "nav"},
                self.auth,
                db,
            )
        self.assertEqual(db.calls, [])

    async def test_public_parameter_normalization_preserves_registered_source(self):
        self.exp["parameters"]["symbols"] = ["518880.SH", "510300.SH"]
        self.exp["parameters"]["target_weights"] = {"SH510300": "0.6"}
        self.result["config"]["parameters"] = {
            **copy.deepcopy(self.exp["parameters"]),
            "symbols": ["510300.SH", "518880.SH"],
            "target_weights": {"510300.SH": 0.6},
        }
        before = copy.deepcopy(self.c)
        p, _ = await self.inspect("overview")
        self.assertEqual(self.c, before)
        self.assertEqual(p["rows"][0]["parameters"], self.exp["parameters"])
        source = p["sources"][-1]
        expected = hashlib.sha256(
            json.dumps(
                self.exp, sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()
        self.assertEqual(source["sha256"], expected)

    async def test_parameter_normalization_does_not_allow_other_changes(self):
        original = copy.deepcopy(self.result["config"]["parameters"])
        cases = [
            {**original, "unknown_parameter": 1},
            {**original, "research_case_id": self.ident},
            {**original, "lookback": 13},
            {**original, "lookback": True},
            {"symbols": original["symbols"]},
            {**original, "symbols": ["518880.SH"]},
        ]
        for parameters in cases:
            self.result["config"]["parameters"] = parameters
            with (
                self.subTest(parameters=parameters),
                self.assertRaisesRegex(ValueError, "result_parameters_mismatch"),
            ):
                await self.inspect("overview")

    def split_original(self):
        fields = {
            "equity_curve",
            "drawdown_curve",
            "trades",
            "positions",
            "ledger_view",
            "ledger_evidence",
            "strategy_decisions",
        }
        return (
            {k: v for k, v in self.result.items() if k not in fields},
            {k: v for k, v in self.result.items() if k in fields},
        )

    async def test_owned_split_file_is_read_only_and_reproducible(self):
        summary, original = self.split_original()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "tenant-a" / "00000001" / (self.bid + ".json")
            target.parent.mkdir(parents=True)
            raw = json.dumps(original).encode()
            target.write_bytes(raw)
            before = target.stat()
            packets = []
            with patch(
                "backend.services.research_agent.continuous_evidence._local_result_location",
                return_value=(root, target),
            ):
                for _ in range(2):
                    db = FakeDB(self.cfg, summary, file_path=str(target))
                    packets.append(
                        await inspect_evidence(
                            self.ident,
                            self.c,
                            self.t,
                            {
                                "action": "inspect_evidence",
                                "backtest_id": self.bid,
                                "view": "nav",
                                "limit": 2,
                            },
                            self.auth,
                            db,
                        )
                    )
            self.assertEqual(packets[0], packets[1])
            self.assertEqual((packets[0]["total"], packets[0]["next_offset"]), (3, 2))
            self.assertEqual(
                packets[0]["sources"][-1]["sha256"], hashlib.sha256(raw).hexdigest()
            )
            self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(target.read_bytes(), raw)

    async def test_summary_rejected_before_any_original_file_open(self):
        summary, _ = self.split_original()
        summary["config"]["strategy_revision"] = "other-revision"
        db = FakeDB(self.cfg, summary, file_path="/private/anything")
        with patch(
            "backend.services.research_agent.continuous_evidence._read_originals"
        ) as read:
            with self.assertRaises(ValueError):
                await inspect_evidence(
                    self.ident,
                    self.c,
                    self.t,
                    {
                        "action": "inspect_evidence",
                        "backtest_id": self.bid,
                        "view": "nav",
                    },
                    self.auth,
                    db,
                )
            read.assert_not_called()

    async def test_arbitrary_and_symbolic_paths_rejected(self):
        summary, original = self.split_original()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "tenant-a" / "00000001" / (self.bid + ".json")
            target.parent.mkdir(parents=True)
            other = root / "unrelated.json"
            other.write_text(json.dumps(original))
            with patch(
                "backend.services.research_agent.continuous_evidence._local_result_location",
                return_value=(root, target),
            ):
                for supplied in [str(other), str(target.parent / ".." / target.name)]:
                    db = FakeDB(self.cfg, summary, file_path=supplied)
                    with patch(
                        "backend.services.research_agent.continuous_evidence.os.open"
                    ) as opened:
                        with self.assertRaisesRegex(
                            ValueError, "noncanonical_original_path"
                        ):
                            await inspect_evidence(
                                self.ident,
                                self.c,
                                self.t,
                                {
                                    "action": "inspect_evidence",
                                    "backtest_id": self.bid,
                                    "view": "nav",
                                },
                                self.auth,
                                db,
                            )
                        opened.assert_not_called()
                target.symlink_to(other)
                db = FakeDB(self.cfg, summary, file_path=str(target))
                with self.assertRaisesRegex(ValueError, "unavailable_or_symlink"):
                    await inspect_evidence(
                        self.ident,
                        self.c,
                        self.t,
                        {
                            "action": "inspect_evidence",
                            "backtest_id": self.bid,
                            "view": "nav",
                        },
                        self.auth,
                        db,
                    )
                target.unlink()
                target.parent.rmdir()
                target.parent.symlink_to(root, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "unavailable_or_symlink"):
                    await inspect_evidence(
                        self.ident,
                        self.c,
                        self.t,
                        {
                            "action": "inspect_evidence",
                            "backtest_id": self.bid,
                            "view": "nav",
                        },
                        self.auth,
                        FakeDB(self.cfg, summary, file_path=str(target)),
                    )


if __name__ == "__main__":
    unittest.main()
