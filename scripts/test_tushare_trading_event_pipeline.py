"""Offline trading-event capture, discovery, saturated requests and fixed reads."""

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
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset
from backend.shared.tushare_trading_event_contracts import FIELDS, INPUT_FIELDS

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    values = dict.fromkeys(FIELDS[api])
    values.update(
        {
            k: v
            for k, v in {
                "trade_date": "20260904",
                "ts_code": "600036.SH",
                "name": "源名",
                "exalter": "同一席位",
                "side": "0",
                "reason": "涨幅偏离",
                "hm_name": "标签",
                "hm_orgs": "营业部",
                "tag": None,
                "net_amount": -12.5,
                "net_buy": -12.5,
                "orgs": ["机构甲", "机构乙"],
            }.items()
            if k in values
        }
    )
    values["unknown_supplier_column"] = "原样保留"
    values.update(updates)
    return values


class TradingEventRuntime(unittest.TestCase):
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
        rows = rows if rows is not None else [source(api)]
        fields = [field for field in rows[0] if field not in omit]

        def respond(request):
            sent = json.loads(request.content)
            self.assertEqual(set(sent["fields"].split(",")), set(FIELDS[api]))
            self.assertTrue(set(sent["params"]) <= set(INPUT_FIELDS[api]))
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

    def test_full_capture_publish_read_keeps_event_rows_and_source_fields(self):
        cases = {
            "top_list": [source("top_list"), source("top_list", reason="三日累计")],
            "top_inst": [source("top_inst"), source("top_inst", side="1")],
            "hm_list": [source("hm_list"), source("hm_list", orgs=["新机构"])],
            "hm_detail": [source("hm_detail"), source("hm_detail", tag="关联")],
        }
        for api, rows in cases.items():
            self.assertEqual(contract_for(api)["group"], "trading_event")
            params = {} if api == "hm_list" else {"trade_date": "20260904"}
            for epoch in ("first", "repeat"):
                _, _, result = self.capture(api, params, rows, epoch=epoch)
                self.assertEqual(result["status"], "sample_ok")
                observation = json.loads(
                    (self.root / "observations" / result["observation"]).read_bytes()
                )
                self.assertEqual(observation["request"]["params"], params)
        release = self.p.publish()
        for api in cases:
            table = read_dataset(self.root, release, api)
            rows = table.to_pylist()
            self.assertEqual(len(rows), 2, api)
            self.assertEqual(len({r["_row_identity"] for r in rows}), 2)
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            self.assertTrue(
                all(r["unknown_supplier_column"] == "原样保留" for r in rows)
            )
            self.assertEqual(
                json.loads(table.schema.metadata[b"tushare"])["upstream_calls"], 0
            )
            if api != "hm_list":
                self.assertEqual({r["source_ts_code"] for r in rows}, {"600036.SH"})
                self.assertEqual(
                    read_dataset(
                        self.root,
                        release,
                        api,
                        codes=["SH600036"],
                        start_date="20260904",
                        end_date="20260904",
                    ).num_rows,
                    2,
                )
        self.assertEqual(
            {
                r["side"]
                for r in read_dataset(self.root, release, "top_inst").to_pylist()
            },
            {"0", "1"},
        )
        self.assertEqual(
            {
                r["tag"]
                for r in read_dataset(self.root, release, "hm_detail").to_pylist()
            },
            {None, "关联"},
        )

    def test_hidden_tag_absence_is_schema_gap_null_is_valid(self):
        _, job, result = self.capture(
            "hm_detail", {"trade_date": "20260904"}, omit=["tag"]
        )
        self.assertIn("tag", job["fields"].split(","))
        self.assertEqual(result["status"], "schema_gap")
        self.assertIn("tag", result["missing_fields"])
        self.assertEqual(
            self.capture("hm_detail", {"trade_date": "20260905"})[2]["status"],
            "sample_ok",
        )

    def test_fanout_unions_retired_stocks_all_observed_events_and_parent_rows(self):
        # Use a raw immutable stock observation, without asserting a full master.
        payload = {
            "code": 0,
            "data": {
                "fields": ["ts_code", "list_status"],
                "items": [["T600018.SH", "D"], ["000001.SZ", "L"]],
            },
        }
        raw = module.json_bytes(payload)
        sha = module.digest(raw)
        path = self.root / "objects" / (sha + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        stock = {"api_name": "stock_basic", "object_sha256": sha}
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            ("stock-fixture", 1, json.dumps(stock)),
        )
        self.capture(
            "top_inst",
            {"trade_date": "20260903"},
            [source("top_inst", ts_code="920999.BJ")],
        )
        self.capture("hm_list", {}, [source("hm_list", name="新标签")])
        row, job, result = self.capture(
            "hm_detail", {"trade_date": "20260904", "hm_name": "标签"}, more=True
        )
        split = self.p.split_request(row, job, result)
        self.assertEqual(split["children"], 4)
        self.assertFalse(split["universe_complete"])
        ids = self.p.identifiers()
        self.assertEqual(
            set(ids["trading_event_securities"]),
            {"T600018.SH", "000001.SZ", "920999.BJ", "600036.SH"},
        )
        self.assertEqual(set(ids["hot_money_names"]), {"新标签", "标签"})
        self.assertNotIn("920999.BJ", ids["stocks"])
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                (row["id"],),
            )
        ]
        self.assertTrue(
            all(
                p["hm_name"] == "标签" and p["trade_date"] == "20260904"
                for p in children
            )
        )
        self.assertEqual(
            {p["ts_code"] for p in children}, set(ids["trading_event_securities"])
        )
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

    def test_terminal_code_cap_and_list_cap_stay_blocked_without_fake_hm_fanout(self):
        self.p.plan_extended(
            {"enable_trading_event": True, "trading_event_apis": []}, date(2026, 9, 9)
        )
        self.p.record_extra_planning_gaps(
            "trading_event", {"trading_event_apis": ["hm_detail"]}, {}
        )
        for api, params in (
            ("hm_detail", {"trade_date": "20260904", "ts_code": "600036.SH"}),
            ("hm_list", {}),
        ):
            row, job, result = self.capture(api, params, more=True)
            self.assertIsNone(self.p.split_request(row, job, result))
        # The actual run path uses blocked for a saturated terminal request.
        pending = self.p.enqueue(
            "hm_detail",
            {"trade_date": "20260905", "ts_code": "600036.SH"},
            1,
            "terminal",
        )

        def respond(request):
            row = source("hm_detail")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(row),
                        "items": [list(row.values())],
                        "has_more": True,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            self.p.run(client, "fixture", {}, max_requests=1, max_seconds=10, pause=0)
        self.assertEqual(
            self.p.db.execute(
                "SELECT state FROM jobs WHERE id=?", (pending,)
            ).fetchone()[0],
            "blocked",
        )
        gap = self.p.db.execute(
            "SELECT reason FROM capability WHERE scope='planning:trading_event:hm_detail:secondary_partition_gap'"
        ).fetchone()
        self.assertIsNotNone(gap)
        self.assertIn("complete discovery", gap[0])

    def test_planning_is_idempotent_invalid_family_does_not_block_connect(self):
        config = {
            "enable_trading_event": True,
            "trading_event_history_start": "20260901",
            "plan_jobs_per_tick": 1000,
        }
        self.assertIn(
            "recent:trading_event", self.p.plan_extended(config, date(2026, 9, 9))
        )
        count = self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], count
        )
        config.update(
            trading_event_apis=["bad"], enable_connect=True, connect_apis=["stock_hsgt"]
        )
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertNotIn("recent:trading_event", stats)
        self.assertIn("recent:connect", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:trading_event'"
            ).fetchone()[0],
            "validation_blocked",
        )

    def test_catalog_correction_preserves_baseline_evidence_and_installer(self):
        after = next(e for e in CATALOG["entries"] if "hm_list" in e["api_names"])
        self.assertEqual(after["output_fields"], ["name", "desc", "orgs"])
        self.assertEqual(
            after["html_sha256"],
            "6ea2c654c4c31b413f527d7d97fa603a9eea0390658684fcbe13120b2ce6d7a4",
        )
        self.assertEqual(after["doc_id"], "311")
        self.assertEqual(after["input_fields"], ["name"])
        self.assertEqual(after["permission_status"], "unprobed")
        self.assertIn(
            '"backend/shared/tushare_trading_event_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
