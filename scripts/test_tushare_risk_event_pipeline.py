"""Isolated risk-event acquisition, date filters and historical security scopes."""

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
from backend.shared.tushare_risk_event_contracts import FIELDS
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import (
    read_dataset,
    dataset_schema,
    export_jsonl,
    CONTRACTS,
)

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        {
            k: v
            for k, v in {
                "ts_code": "513310.SH" if api == "stk_alert" else "T600001.SH",
                "name": "历史来源风险名称",
                "trade_date": "20260904",
                "type": "ST",
                "pub_date": "2026-09-04",
                "imp_date": "2026-09-15",
                "st_type": "撤销叠加*ST",
                "start_date": "2026-09-04",
                "end_date": "2026-09-25",
                "st_reason": "原因",
                "st_explain": "叠加风险尚未全部解除",
                "trade_market": "源交易所标签",
                "reason": "源异常说明",
                "period": "2026-09-01-2026-09-25",
            }.items()
            if k in row
        }
    )
    row["supplier_extra"] = "未知列保留"
    row.update(updates)
    return row


class RiskEventRuntime(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("offline only"))
            guard.start()
            self.addCleanup(guard.stop)

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

    def discovery(self, api, rows):
        # Source-only stored metadata fixture, not an upstream call or a claim
        # that a partial fixture validates the real master contract.
        payload = {
            "code": 0,
            "data": {
                "fields": list(rows[0]),
                "items": [list(r.values()) for r in rows],
            },
        }
        raw = module.json_bytes(payload)
        sha = module.digest(raw)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (sha + ".json")).write_bytes(raw)
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            ("fixture-" + api, 1, json.dumps({"api_name": api, "object_sha256": sha})),
        )

    def test_all_five_capture_publish_read_retains_fields_source_rows_and_dates(self):
        for api in FIELDS:
            for epoch in ("first", "repeat"):
                result = self.capture(
                    api,
                    {"pub_date": "20260904"}
                    if api == "st"
                    else {"trade_date": "20260904"},
                    [source(api), source(api, supplier_extra="来源不同修订")],
                    epoch=epoch,
                )[2]
                self.assertEqual(result["status"], "sample_ok")
        pinned = self.p.publish()
        for api in FIELDS:
            self.assertEqual(contract_for(api)["group"], "risk_event")
            self.assertEqual(contract_for(api)["permission_status"], "unprobed")
            self.assertEqual(CONTRACTS[api]["keys"], contract_for(api)["keys"])
            table = read_dataset(
                self.root, pinned, api, start_date="20260904", end_date="20260904"
            )
            rows = table.to_pylist()
            self.assertEqual(len(rows), 2)
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            self.assertEqual(
                {r["supplier_extra"] for r in rows}, {"未知列保留", "来源不同修订"}
            )
            code = "SH513310" if api == "stk_alert" else "SHT600001"
            original = "513310.SH" if api == "stk_alert" else "T600001.SH"
            self.assertTrue(
                all(
                    r["ts_code"] == code and r["source_ts_code"] == original
                    for r in rows
                )
            )
            self.assertEqual(
                read_dataset(self.root, pinned, api, codes=[code]).num_rows, 2
            )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            self.assertIn("date_axis_note", metadata)
            self.assertIn("pit_gap", metadata)
            if api in ("stk_shock", "stk_high_shock"):
                self.assertTrue(
                    all(r["period"] == "2026-09-01-2026-09-25" for r in rows)
                )
            if api == "st":
                self.assertTrue(
                    all(
                        r["imp_date"] == "2026-09-15" and r["st_type"] == "撤销叠加*ST"
                        for r in rows
                    )
                )
            if api == "stk_alert":
                self.assertTrue(all(r["end_date"] == "2026-09-25" for r in rows))
                self.assertNotIn("trade_date", table.column_names)

    def test_default_schema_read_and_export_axes_differ_from_future_implementation_or_expiry(
        self,
    ):
        for api in ("st", "stk_alert"):
            self.capture(
                api,
                {"pub_date": "20260904"} if api == "st" else {"trade_date": "20260904"},
            )
        pinned = self.p.publish()
        for api, axis, future_axis, future in (
            ("st", "pub_date", "imp_date", "20260915"),
            ("stk_alert", "start_date", "end_date", "20260925"),
        ):
            self.assertEqual(
                dataset_schema(self.root, pinned, api)["default_date_field"], axis
            )
            self.assertEqual(
                read_dataset(
                    self.root, pinned, api, start_date=future, end_date=future
                ).num_rows,
                0,
            )
            self.assertEqual(
                read_dataset(
                    self.root,
                    pinned,
                    api,
                    start_date=future,
                    end_date=future,
                    date_field=future_axis,
                ).num_rows,
                1,
            )
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "risk.jsonl"
                export_jsonl(
                    self.root,
                    pinned,
                    api,
                    output,
                    start_date="20260904",
                    end_date="20260904",
                )
                self.assertEqual(
                    json.loads(output.read_text())[future_axis],
                    "2026-09-15" if api == "st" else "2026-09-25",
                )

    def test_risk_universes_include_history_and_etf_without_mutating_stock_or_concept_families(
        self,
    ):
        self.discovery("stock_basic", [{"ts_code": "T600018.SH", "list_status": "D"}])
        self.discovery("bak_basic", [{"ts_code": "600002.SH"}])
        self.discovery("etf_basic", [{"ts_code": "513310.SH"}])
        self.discovery("fund_basic", [{"ts_code": "159001.SZ"}])
        self.capture(
            "stk_shock",
            {"trade_date": "20260904"},
            [source("stk_shock", ts_code="600003.SH")],
        )
        self.capture(
            "stk_alert",
            {"trade_date": "20260904"},
            [source("stk_alert", ts_code="159999.SZ")],
        )
        ids = self.p.identifiers()
        self.assertEqual(ids["stocks"], ["T600018.SH"])
        self.assertEqual(
            set(ids["risk_stocks"]), {"T600018.SH", "600002.SH", "600003.SH"}
        )
        self.assertEqual(
            set(ids["risk_securities"]),
            set(ids["risk_stocks"]) | {"513310.SH", "159001.SZ", "159999.SZ"},
        )
        self.assertEqual(ids["ths_indices"], [])
        config = {
            "enable_risk_event": True,
            "risk_event_apis": ["st"],
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(config, date(2026, 9, 9))
        hist = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE epoch='history' AND json_extract(job,'$.api_name')='st'"
            )
        ]
        self.assertEqual({r["ts_code"] for r in hist}, set(ids["risk_stocks"]))
        self.assertTrue(all(set(r) == {"ts_code"} for r in hist))
        self.assertEqual(contract_for("st")["dependencies"], ["risk_stocks"])
        self.assertEqual(
            set(module._planning_inputs("risk_event", config, ids)[1]), {"risk_stocks"}
        )

    def test_planning_axes_unknown_history_and_family_validation_remain_isolated(self):
        config = {
            "enable_risk_event": True,
            "risk_event_apis": ["st", "stk_shock", "stk_high_shock", "stk_alert"],
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 35
        )
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 35
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE epoch='history'"
            ).fetchone()[0],
            0,
        )
        st_requests = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE json_extract(job,'$.api_name')='st'"
            )
        ]
        self.assertEqual(len(st_requests), 14)
        self.assertTrue(
            all(set(p) in ({"pub_date"}, {"imp_date"}) for p in st_requests)
        )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT reason FROM capability WHERE scope='planning:risk_event:stk_alert:future_gap'"
            ).fetchone()
        )
        ids = self.p.identifiers()
        ids["risk_stocks"] = ["bad,code"]
        bad = {
            **config,
            "enable_dc_extra": True,
            "dc_extra_apis": ["dc_daily"],
            "dc_extra_history_start": "20260909",
        }
        with patch.object(self.p, "identifiers", return_value=ids):
            stats = self.p.plan_extended(bad, date(2026, 9, 9))
        self.assertNotIn("recent:risk_event", stats)
        self.assertIn("recent:dc_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:risk_event'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertEqual(bad["risk_event_apis"], config["risk_event_apis"])
        self.assertIn(
            '"backend/shared/tushare_risk_event_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )

    def test_required_columns_and_complete_request_constraints_survive_saturation(self):
        self.discovery("stock_basic", [{"ts_code": "T600018.SH"}])
        self.discovery("etf_basic", [{"ts_code": "513310.SH"}])
        for api in FIELDS:
            missing = "st_explain" if api == "st" else "name"
            params = (
                {"pub_date": "20260904"} if api == "st" else {"trade_date": "20260904"}
            )
            self.assertEqual(
                self.capture(api, params, omit=[missing], epoch="missing")[2]["status"],
                "schema_gap",
            )
            row, job, result = self.capture(api, params, more=True, epoch="cap")
            split = self.p.split_request(row, job, result)
            self.assertFalse(split["universe_complete"])
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertTrue(
                all(all(child[k] == v for k, v in params.items()) for child in children)
            )
            codes = {child["ts_code"] for child in children}
            self.assertIn("T600018.SH", codes)
            if api == "stk_alert":
                self.assertIn("513310.SH", codes)
            else:
                self.assertNotIn("513310.SH", codes)
            self.p.db.execute(
                "UPDATE jobs SET state='split_pending' WHERE id=?", (row["id"],)
            )
            self.p.reconcile_partitions()
            self.assertEqual(
                self.p.db.execute(
                    "SELECT gap FROM partition_splits WHERE parent_id=?", (row["id"],)
                ).fetchone()[0],
                "universe_unverified",
            )

    def test_range_partition_uses_request_axis_and_preserves_code(self):
        for api in ("stock_st", "stk_shock", "stk_high_shock", "stk_alert"):
            params = {
                "ts_code": "513310.SH" if api == "stk_alert" else "T600001.SH",
                "start_date": "20260903",
                "end_date": "20260904",
            }
            row, job, result = self.capture(api, params, more=True)
            self.assertEqual(
                self.p.split_request(row, job, result)["method"], "date_bisection"
            )
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {(p["start_date"], p["end_date"]) for p in children},
                {("20260903", "20260903"), ("20260904", "20260904")},
            )
            self.assertTrue(all(p["ts_code"] == params["ts_code"] for p in children))
        self.assertIsNone(
            self.p.date_children(
                {"api_name": "st", "params": {"ts_code": "T600001.SH"}}
            )
        )

    def test_actual_thousand_row_terminal_requests_stay_blocked_without_fake_date_or_offset(
        self,
    ):
        keys = []
        for api in FIELDS:
            params = {"ts_code": "T600001.SH"}
            if api != "st":
                params["trade_date"] = "20260904"
            keys.append(self.p.enqueue(api, params, 1, "terminal"))

        def respond(request):
            sent = json.loads(request.content)
            payload = source(sent["api_name"])
            self.assertNotIn("offset", sent["params"])
            self.assertNotIn("start_date", sent["params"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(payload),
                        "items": [list(payload.values())] * 1000,
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


if __name__ == "__main__":
    unittest.main()
