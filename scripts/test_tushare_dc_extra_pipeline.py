"""Offline DC historical members, category identity and fixed-release reads."""

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
from backend.shared.tushare_dc_extra_contracts import FIELDS, DAILY_VARIANTS
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, export_jsonl, CONTRACTS

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        {
            k: v
            for k, v in {
                "ts_code": "BK1184.DC",
                "trade_date": "20260904",
                "con_code": "873593.BJ",
                "name": "来源成员",
                "category": "源分类",
                "close": 0.0,
                "change": -1.0,
                "vol": 0.0,
                "amount": None,
            }.items()
            if k in row
        }
    )
    row["supplier_extra"] = "新增来源字段"
    row.update(updates)
    return row


class DcExtraRuntime(unittest.TestCase):
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

    def test_capture_publish_read_preserves_all_columns_rows_and_category_requests(
        self,
    ):
        for epoch in ("first", "again"):
            self.capture(
                "dc_member",
                {"trade_date": "20260904"},
                [
                    source("dc_member"),
                    source("dc_member", name="同代码修订名称"),
                    source("dc_member", con_code="00013!.HK"),
                    source("dc_member", con_code="AAPL"),
                ],
                epoch=epoch,
            )
            for variant in DAILY_VARIANTS:
                result = self.capture(
                    "dc_daily", {"trade_date": "20260904", **variant}, epoch=epoch
                )[2]
                self.assertEqual(result["status"], "sample_ok")
        pinned = self.p.publish()
        for api in FIELDS:
            self.assertEqual(contract_for(api)["group"], "dc_extra")
            self.assertEqual(CONTRACTS[api]["keys"], contract_for(api)["keys"])
            table = read_dataset(
                self.root, pinned, api, start_date="20260904", end_date="20260904"
            )
            rows = table.to_pylist()
            self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
            self.assertTrue(all(r["supplier_extra"] == "新增来源字段" for r in rows))
            self.assertTrue(
                all(r["ts_code"] == r["source_ts_code"] == "BK1184.DC" for r in rows)
            )
            self.assertEqual(len(rows), 4 if api == "dc_member" else 3)
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["upstream_calls"], 0)
            self.assertIn("point-in-time", metadata["pit_gap"])
            self.assertIn("history_note", metadata)
            if api == "dc_member":
                self.assertTrue(
                    all(r["con_code"] == r["source_con_code"] for r in rows)
                )
                self.assertEqual(
                    {r["con_code"] for r in rows}, {"873593.BJ", "00013!.HK", "AAPL"}
                )
                self.assertEqual(
                    read_dataset(
                        self.root,
                        pinned,
                        api,
                        codes=["873593.BJ"],
                        code_field="con_code",
                    ).num_rows,
                    2,
                )
                self.assertIn("second dimension", metadata["saturation_gap"])
            else:
                self.assertEqual(
                    {json.loads(r["_request_identity"])["idx_type"] for r in rows},
                    {v["idx_type"] for v in DAILY_VARIANTS},
                )
                self.assertTrue(
                    all(r["category"] == "源分类" and r["change"] == -1.0 for r in rows)
                )
                self.assertEqual(
                    metadata["request_identity_status"],
                    "verified_from_immutable_observations",
                )
                self.assertIn("vol is shares", metadata["unit_note"])
        self.assertEqual(self.p.identifiers()["dc_indices"], ["BK1184.DC"])
        self.assertEqual(self.p.identifiers()["stocks"], [])
        self.assertEqual(self.p.identifiers()["ths_indices"], [])

    def test_opaque_board_spelling_and_member_source_survive_read_export(self):
        for api in FIELDS:
            self.capture(
                api,
                {"idx_type": "行业板块"} if api == "dc_daily" else {},
                [source(api, ts_code="600001.SH"), source(api, ts_code="T600001.SH")],
            )
        pinned = self.p.publish()
        for api in FIELDS:
            rows = read_dataset(self.root, pinned, api).to_pylist()
            self.assertEqual({r["ts_code"] for r in rows}, {"600001.SH", "T600001.SH"})
            self.assertEqual(
                read_dataset(self.root, pinned, api, codes=["600001.SH"]).num_rows, 1
            )
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "dc.jsonl"
                export_jsonl(self.root, pinned, api, output, codes=["T600001.SH"])
                self.assertEqual(
                    json.loads(output.read_text())["ts_code"], "T600001.SH"
                )
        self.assertEqual(self.p.identifiers()["stocks"], [])

    def test_column_or_request_identity_omission_remains_a_gap(self):
        for api, missing in (("dc_member", "name"), ("dc_daily", "category")):
            params = {
                "trade_date": "20260904",
                **({"idx_type": "概念板块"} if api == "dc_daily" else {}),
            }
            result = self.capture(api, params, omit=[missing])[2]
            self.assertEqual(result["status"], "schema_gap")
            self.assertIn(missing, result["requested_missing_fields"])
        self.capture("dc_daily", {"trade_date": "20260905"})
        pinned = self.p.publish()
        with self.assertRaisesRegex(ValueError, "Request identity gap"):
            read_dataset(self.root, pinned, "dc_daily")

    def test_planning_preserves_history_scope_gaps_and_family_isolation(self):
        config = {
            "enable_dc_extra": True,
            "dc_extra_history_start": "20260902",
            "plan_jobs_per_tick": 1000,
        }
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:dc_extra", stats)
        self.assertIn("history:dc_extra", stats)
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 32
        )
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 32
        )
        for api in FIELDS:
            for reason in (
                "history_gap",
                "pit_gap",
                "configured_scope_not_verified_complete",
            ):
                self.assertIsNotNone(
                    self.p.db.execute(
                        "SELECT reason FROM capability WHERE scope=?",
                        (f"planning:dc_extra:{api}:{reason}",),
                    ).fetchone()
                )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT reason FROM capability WHERE scope='planning:dc_extra:dc_member:saturation_gap'"
            ).fetchone()
        )
        bad = {
            **config,
            "dc_extra_apis": ["dc_index"],
            "enable_concept_extra": True,
            "concept_extra_apis": ["ths_index"],
        }
        stats = self.p.plan_extended(bad, date(2026, 9, 9))
        self.assertNotIn("recent:dc_extra", stats)
        self.assertIn("recent:concept_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:dc_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.assertEqual(bad["dc_extra_apis"], ["dc_index"])
        self.assertIn(
            '"backend/shared/tushare_dc_extra_contracts.py"',
            (ROOT / "scripts/tushare_mirror.py").read_text(),
        )

    def test_range_and_observed_board_fanout_preserve_params_and_incompleteness(self):
        master = dict.fromkeys(contract_for("dc_index")["required_fields"])
        master.update(ts_code="retired.DC", trade_date="20260901")
        self.capture(
            "dc_index", {"trade_date": "20260901", "idx_type": "行业板块"}, [master]
        )
        for api in FIELDS:
            extra = (
                {"con_code": "873593.BJ"}
                if api == "dc_member"
                else {"idx_type": "地域板块"}
            )
            row, job, result = self.capture(
                api,
                {"start_date": "20260903", "end_date": "20260904", **extra},
                more=True,
            )
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
                {(r["start_date"], r["end_date"]) for r in children},
                {("20260903", "20260903"), ("20260904", "20260904")},
            )
            self.assertTrue(
                all(all(r[k] == v for k, v in extra.items()) for r in children)
            )
            row, job, result = self.capture(
                api, {"trade_date": "20260904", **extra}, more=True
            )
            split = self.p.split_request(row, job, result)
            self.assertEqual(split["children"], 2)
            self.assertFalse(split["universe_complete"])
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {r["ts_code"] for r in children}, {"retired.DC", "BK1184.DC"}
            )
            self.assertTrue(
                all(all(r[k] == v for k, v in extra.items()) for r in children)
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
        self.assertEqual(
            self.p.identifiers()["dc_indices"], ["BK1184.DC", "retired.DC"]
        )

    def test_business_runner_keeps_single_board_saturation_blocked(self):
        ids = {}
        for api in FIELDS:
            params = {"trade_date": "20260904", "ts_code": "BK1184.DC"}
            if api == "dc_daily":
                params["idx_type"] = "行业板块"
            ids[api] = self.p.enqueue(api, params, 1, "terminal")

        def respond(request):
            sent = json.loads(request.content)
            payload = source(sent["api_name"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(payload),
                        "items": [list(payload.values())],
                        "has_more": True,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            report = self.p.run(
                client, "fixture", {}, max_requests=2, max_seconds=10, pause=0
            )
        self.assertEqual(report["requests"], 2)
        for key in ids.values():
            self.assertEqual(
                self.p.db.execute(
                    "SELECT state FROM jobs WHERE id=?", (key,)
                ).fetchone()[0],
                "blocked",
            )
        self.assertEqual(
            self.p.db.execute("SELECT COUNT(*) FROM partition_children").fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
