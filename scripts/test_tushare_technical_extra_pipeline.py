"""Temporary-directory technical acquisition and fixed-release consumption checks."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_intake import capture_sample
from backend.shared.tushare_technical_extra_contracts import FIELDS, FIELD_METADATA
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, dataset_schema, export_jsonl
import test_tushare_risk_event_pipeline as fixtures


def source(api, **updates):
    row = {
        field: "source-label" if meta["type"] == "str" else -1.25
        for field, meta in FIELD_METADATA[api].items()
    }
    row.update(ts_code="T600001.SH", trade_date="20260904")
    if "price" in row:
        row.update(price=12.5, percent=0.15)
    if "pe" in row:
        row["pe"] = None
    row["supplier_extra"] = "unknown column retained"
    row.update(updates)
    return row


class TechnicalExtraRuntime(unittest.TestCase):
    setUp = fixtures.RiskEventRuntime.setUp
    discovery = fixtures.RiskEventRuntime.discovery

    def capture(self, api, params, rows=None, more=False, epoch="test", omit=()):
        key = self.p.enqueue(api, params, 10, epoch)
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        rows = [source(api)] if rows is None else rows
        fields = [f for f in rows[0] if f not in omit]

        def respond(request):
            sent = json.loads(request.content)
            self.assertEqual(
                set(sent["fields"].split(",")),
                set(contract_for(api)["requested_fields"]),
            )
            self.assertEqual(sent["params"], params)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                        "has_more": more,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            result = self.p.normalize(capture_sample(client, "fixture", job, self.root))
        attempt = row["tries"] + 1
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (key, attempt, json.dumps(result))
        )
        self.p.db.execute(
            "UPDATE jobs SET result=?,state=?,tries=? WHERE id=?",
            (
                json.dumps(result),
                "done" if result["status"] == "sample_ok" else "quality",
                attempt,
                key,
            ),
        )
        self.p.db.commit()
        return (
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone(),
            job,
            result,
        )

    def test_full_342_source_fields_fixed_read_filter_export_and_old_release(self):
        old = self.p.publish()
        expected = {}
        for api in FIELDS:
            rows = [
                source(api),
                source(api, ts_code="600001.SH"),
                source(api, supplier_extra="revision retained"),
            ]
            if api == "cyq_chips":
                rows.append(source(api, price=13.5, percent=0.1))
            expected[api] = {module.digest(module.json_bytes(r)): r for r in rows}
            for epoch in ("one", "repeat"):
                result = self.capture(
                    api,
                    {"ts_code": "T600001.SH", "trade_date": "20260904"},
                    rows,
                    epoch=epoch,
                )[2]
                self.assertEqual(result["status"], "sample_ok")
        pinned = self.p.publish()
        self.assertNotEqual(old, pinned)
        for api in FIELDS:
            table = read_dataset(self.root, pinned, api)
            actual = table.to_pylist()
            self.assertEqual(len(actual), len(expected[api]))
            for row in actual:
                raw = expected[api][row["_row_identity"]]
                for field, value in raw.items():
                    self.assertEqual(
                        row["source_ts_code" if field == "ts_code" else field], value
                    )
                self.assertEqual(
                    row["ts_code"],
                    "SHT600001" if raw["ts_code"].startswith("T") else "SH600001",
                )
            schema = dataset_schema(self.root, pinned, api)
            self.assertEqual(schema["default_date_field"], "trade_date")
            self.assertEqual(
                read_dataset(self.root, pinned, api, start_date="20260905").num_rows, 0
            )
            self.assertEqual(
                read_dataset(
                    self.root,
                    pinned,
                    api,
                    codes=["SH600001"],
                    start_date="20260904",
                    end_date="20260904",
                ).num_rows,
                1,
            )
            with self.assertRaisesRegex(
                ValueError, "Dataset unavailable in fixed release"
            ):
                read_dataset(self.root, old, api)
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            self.assertEqual(set(metadata["field_gaps"]), set(FIELDS[api]))
            self.assertEqual(metadata["deduplication_mode"], "distinct_supplier_rows")
            self.assertIn("adjustment_note", metadata)
            self.assertIn("unit_note", metadata)
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "technical.jsonl"
                export_jsonl(self.root, pinned, api, target, codes=["SH600001"])
                self.assertEqual(
                    json.loads(target.read_text())["source_ts_code"], "600001.SH"
                )
        self.assertEqual(
            {
                r["price"]
                for r in read_dataset(
                    self.root, pinned, "cyq_chips", codes=["SHT600001"]
                ).to_pylist()
            },
            {12.5, 13.5},
        )

    def test_discovery_includes_historical_retired_and_observed_without_other_namespaces(
        self,
    ):
        self.discovery("stock_basic", [{"ts_code": "T600018.SH", "list_status": "D"}])
        for api, code in (
            ("bak_basic", "600002.SH"),
            ("daily", "600003.SH"),
            ("daily_basic", "600004.SH"),
            ("adj_factor", "600005.SH"),
            ("top_list", "600006.SH"),
            ("stock_st", "600007.SH"),
            ("limit_list_d", "600008.SH"),
            ("etf_basic", "510300.SH"),
            ("ths_index", "600099.SH"),
        ):
            self.discovery(api, [{"ts_code": code}])
        self.capture(
            "cyq_perf", {"ts_code": "T600001.SH", "trade_date": "20260904"}, more=True
        )
        ids = self.p.identifiers()
        expected = {"T600018.SH", "T600001.SH"} | {f"60000{n}.SH" for n in range(2, 9)}
        self.assertEqual(set(ids["technical_stocks"]), expected)
        self.assertEqual(ids["stocks"], ["T600018.SH"])
        self.assertEqual(ids["ths_indices"], ["600099.SH"])
        self.assertEqual(ids["funds"], ["510300.SH"])
        cfg = {
            "enable_technical_extra": True,
            "technical_extra_apis": ["cyq_perf", "cyq_chips"],
            "technical_extra_history_start": "20260830",
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(cfg, date(2026, 9, 9))
        histories = [
            json.loads(r[0])
            for r in self.p.db.execute("SELECT job FROM jobs WHERE epoch='history'")
        ]
        for api in ("cyq_perf", "cyq_chips"):
            self.assertEqual(
                {j["params"]["ts_code"] for j in histories if j["api_name"] == api},
                expected,
            )
            self.assertEqual(contract_for(api)["dependencies"], ["technical_stocks"])
        self.assertEqual(
            set(module._planning_inputs("technical_extra", cfg, ids)[1]),
            {"technical_stocks"},
        )
        self.assertTrue(
            all(
                set(j["params"]) == {"ts_code", "start_date", "end_date"}
                for j in histories
            )
        )

    def test_opt_in_unknown_history_idempotence_and_validation_isolation(self):
        self.p.plan_extended({}, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
        )
        cfg = {"enable_technical_extra": True, "plan_jobs_per_tick": 1000}
        self.p.plan_extended(cfg, date(2026, 9, 9))
        self.p.plan_extended(cfg, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 21
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE epoch='history'"
            ).fetchone()[0],
            0,
        )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT reason FROM capability WHERE scope='planning:technical_extra:bak_daily:unknown_history_start_requires_scope'"
            ).fetchone()
        )
        ids = self.p.identifiers()
        ids["technical_stocks"] = ["bad;code"]
        cfg.update(
            enable_risk_event=True,
            risk_event_apis=["stock_st"],
            risk_event_history_start="20260909",
        )
        with patch.object(self.p, "identifiers", return_value=ids):
            stats = self.p.plan_extended(cfg, date(2026, 9, 9))
        self.assertNotIn("recent:technical_extra", stats)
        self.assertIn("recent:risk_event", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:technical_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertTrue(cfg["enable_technical_extra"])
        self.assertIn(
            '"backend/shared/tushare_technical_extra_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )

    def test_missing_columns_and_date_splits_keep_complete_fields_and_code(self):
        for api in FIELDS:
            params = {
                "ts_code": "T600001.SH",
                "start_date": "20240228",
                "end_date": "20240229",
            }
            omitted = FIELDS[api][-1]
            self.assertEqual(
                self.capture(api, params, omit=[omitted], epoch="missing")[2]["status"],
                "schema_gap",
            )
            row, job, result = self.capture(api, params, more=True, epoch="split")
            self.assertEqual(
                self.p.split_request(row, job, result)["method"], "date_bisection"
            )
            children = [
                json.loads(r[0])
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {j["params"]["start_date"] for j in children}, {"20240228", "20240229"}
            )
            self.assertTrue(
                all(
                    j["params"]["ts_code"] == "T600001.SH"
                    and set(j["fields"].split(",")) == set(FIELDS[api])
                    for j in children
                )
            )

    def test_all_market_saturation_fanout_keeps_unknown_universe_and_source_observations(
        self,
    ):
        self.discovery("bak_basic", [{"ts_code": "T600018.SH"}])
        self.discovery("etf_basic", [{"ts_code": "510300.SH"}])
        for api in ("stk_factor", "stk_factor_pro", "bak_daily"):
            row, job, result = self.capture(api, {"trade_date": "20260904"}, more=True)
            split = self.p.split_request(row, job, result)
            self.assertEqual(split["method"], "identifier_fanout")
            self.assertFalse(split["universe_complete"])
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {p["ts_code"] for p in children}, {"T600018.SH", "T600001.SH"}
            )
            self.assertTrue(
                all(
                    p["trade_date"] == "20260904"
                    and set(p) == {"ts_code", "trade_date"}
                    for p in children
                )
            )

    def test_real_cap_terminal_stays_blocked_without_backup_offset_or_chip_price_filters(
        self,
    ):
        keys = []
        for api in FIELDS:
            keys.append(
                self.p.enqueue(
                    api,
                    {"ts_code": "T600001.SH", "trade_date": "20260904"},
                    1,
                    "terminal",
                )
            )

        def respond(request):
            sent = json.loads(request.content)
            api = sent["api_name"]
            self.assertEqual(set(sent["params"]), {"ts_code", "trade_date"})
            row = source(api)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(row),
                        "items": [list(row.values())] * contract_for(api)["row_cap"],
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            report = self.p.run(
                client, "fixture", {}, max_requests=5, max_seconds=10, pause=0
            )
        self.assertEqual(report["requests"], 5)
        for key in keys:
            row = self.p.db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (key,)
            ).fetchone()
            self.assertEqual(row["state"], "blocked")
            self.assertEqual(json.loads(row["result"])["status"], "possibly_truncated")
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM partition_children").fetchone()[0],
            0,
        )
        self.assertNotIn("pagination", contract_for("bak_daily"))


if __name__ == "__main__":
    unittest.main()
