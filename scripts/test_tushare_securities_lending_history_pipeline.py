"""Offline financing-history runtime: immutable rows, source identity and caps."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module  # noqa: E402
from backend.shared.tushare_registry import contract_for  # noqa: E402
from backend.shared.tushare_securities_lending_history_contracts import (  # noqa: E402
    FIELDS,
    FIELD_METADATA,
)
from backend.shared.tushare_store import (  # noqa: E402
    read_dataset,
    dataset_schema,
    export_jsonl,
)
import test_tushare_technical_extra_pipeline as fixtures  # noqa: E402

FAMILY = "securities_lending_history"


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(ts_code="T600018.SH", trade_date="20240620", name="历史来源")
    if api == "slb_sec_detail":
        row.update(tenor="14", fee_rate=0.0, lent_qnt=None)
    else:
        row.update(ope_inv=0.0, lent_qnt=None, cls_inv=1.25, end_bal=0.0)
    row["unknown_source"] = "保留"
    row.update(updates)
    return row


class LendingRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    discovery = fixtures.TechnicalExtraRuntime.discovery
    capture = fixtures.TechnicalExtraRuntime.capture

    def test_twenty_columns_null_unknown_t_identities_and_content_revisions(self):
        old = self.p.publish()
        expected = {}
        first_asof = None
        for api in FIELDS:
            rows = [source(api), source(api, ts_code="600018.SH")]
            if api == "slb_sec_detail":
                rows += [source(api, tenor="28"), source(api, fee_rate=2.2)]
            first = self.capture(api, {"trade_date": "20240620"}, rows, epoch="old")[2]
            if first_asof is None:
                observation = json.loads(
                    (self.root / "observations" / first["observation"]).read_bytes()
                )
                first_asof = observation["fetched_at"]
            revised = source(api, unknown_source="修订版本")
            rows.append(revised)
            for epoch in ("new", "repeat"):
                self.assertEqual(
                    self.capture(api, {"trade_date": "20240620"}, rows, epoch=epoch)[2][
                        "status"
                    ],
                    "sample_ok",
                )
            expected[api] = {module.digest(module.json_bytes(row)): row for row in rows}
        fixed = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, fixed, api)
            self.assertEqual(table.num_rows, len(expected[api]))
            for row in table.to_pylist():
                raw = expected[api][row["_row_identity"]]
                self.assertEqual(
                    {f: row["source_ts_code" if f == "ts_code" else f] for f in raw},
                    raw,
                )
                self.assertEqual(
                    row["ts_code"],
                    "SHT600018" if raw["ts_code"].startswith("T") else "SH600018",
                )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["deduplication_mode"], "distinct_supplier_rows")
            self.assertEqual(metadata["permission_status"], "unprobed")
            self.assertEqual(metadata["update_status"], "catalog_marked_stopped")
            self.assertEqual(metadata["field_metadata"], FIELD_METADATA[api])
            self.assertIsNone(metadata["stop_date"])
            self.assertFalse(metadata["history_bound_verified"])
            self.assertIn("pit_gap", metadata)
            schema = dataset_schema(self.root, fixed, api)
            self.assertEqual(schema["default_date_field"], "trade_date")
            self.assertIn("_row_identity", schema["keys"])
            self.assertEqual(
                read_dataset(
                    self.root,
                    fixed,
                    api,
                    start_date="20240620",
                    end_date="20240620",
                    codes=["SH600018"],
                ).num_rows,
                1,
            )
            self.assertEqual(
                read_dataset(self.root, fixed, api, start_date="20240621").num_rows, 0
            )
            with self.assertRaises(ValueError):
                read_dataset(self.root, old, api)
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "out.jsonl"
                export_jsonl(self.root, fixed, api, target, codes=["SH600018"])
                self.assertEqual(
                    json.loads(target.read_text())["source_ts_code"], "600018.SH"
                )
            with self.assertRaises(ValueError):
                read_dataset(
                    self.root, fixed, api, fields=["ts_code; DROP TABLE stored"]
                )
        # Only the earliest captured API is observed at this timestamp; this is not PIT.
        before = read_dataset(self.root, fixed, "slb_sec", as_of=first_asof)
        self.assertEqual(before.num_rows, 2)
        self.assertNotIn("修订版本", [r["unknown_source"] for r in before.to_pylist()])

    def test_default_off_idempotence_and_saturation_only_stocks_do_not_reset_cursor(
        self,
    ):
        self.p.plan_extended({}, date(2024, 6, 20))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        cfg = {
            "enable_" + FAMILY: True,
            "securities_lending_history_start": "20240601",
            "plan_jobs_per_tick": 4,
        }
        stats = self.p.plan_extended(cfg, date(2024, 6, 20))
        self.assertIn("history:" + FAMILY, stats)
        prior = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", ("history:" + FAMILY,)
            ).fetchone()
        )
        self.assertFalse(prior["done"])
        self.assertEqual(json.loads(prior["signature"])["identifiers"], {})
        self.discovery("stock_basic", [{"ts_code": "T600018.SH", "list_status": "D"}])
        self.discovery("slb_sec", [source("slb_sec", ts_code="600999.SH")])
        ids = self.p.identifiers()
        self.assertEqual(ids["stocks"], ["600999.SH", "T600018.SH"])
        policy1 = module._planning_inputs(FAMILY, cfg, ids)
        self.assertEqual(policy1, module._planning_inputs(FAMILY, cfg, {"stocks": []}))
        self.p.plan_extended(cfg, date(2024, 6, 20))
        after = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", ("history:" + FAMILY,)
            ).fetchone()
        )
        self.assertEqual(after["signature"], prior["signature"])
        self.assertGreater(after["offset"], prior["offset"])
        self.assertEqual(policy1[1], {})
        self.assertNotEqual(
            policy1,
            module._planning_inputs(
                FAMILY, {**cfg, "securities_lending_history_start": "20240602"}, ids
            ),
        )
        self.assertNotEqual(
            policy1,
            module._planning_inputs(
                FAMILY, {**cfg, FAMILY + "_apis": ["slb_sec"]}, ids
            ),
        )
        before_count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        same = self.p.enqueue("slb_sec", {"trade_date": "20240620"}, 10, "idempotence")
        self.assertEqual(
            same,
            self.p.enqueue("slb_sec", {"trade_date": "20240620"}, 10, "idempotence"),
        )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0],
            before_count + 1,
        )
        scopes = [r[0] for r in self.p.db.execute("SELECT scope FROM capability")]
        self.assertTrue(any(scope.endswith(":pit_gap") for scope in scopes))
        self.assertTrue(any(scope.endswith(":discovery") for scope in scopes))

    def test_real_scope_key_refreshes_completed_plan_without_rewriting_old_jobs(self):
        cfg = {
            "enable_securities_lending_history": True,
            "securities_lending_history_start": "20240610",
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(cfg, date(2024, 6, 20))
        before = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", ("history:" + FAMILY,)
            ).fetchone()
        )
        self.assertTrue(before["done"])
        old_jobs = {r["id"]: dict(r) for r in self.p.db.execute("SELECT * FROM jobs")}

        def history_dates():
            return {
                json.loads(r[0])["params"]["trade_date"]
                for r in self.p.db.execute(
                    "SELECT job FROM jobs WHERE group_name=? AND epoch='history'",
                    (FAMILY,),
                )
            }

        self.assertEqual(
            history_dates(), {"20240610", "20240611", "20240612", "20240613"}
        )
        # Typo/inert config is not a planner dependency. Actual one-key change is.
        inputs = module._planning_inputs(FAMILY, cfg, {})
        self.assertEqual(
            inputs,
            module._planning_inputs(
                FAMILY,
                {**cfg, "securities_lending_history_history_start": "19900101"},
                {},
            ),
        )
        changed = {**cfg, "securities_lending_history_start": "20240609"}
        self.assertNotEqual(inputs, module._planning_inputs(FAMILY, changed, {}))
        self.p.plan_extended(changed, date(2024, 6, 20))
        after = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", ("history:" + FAMILY,)
            ).fetchone()
        )
        self.assertTrue(after["done"])
        self.assertNotEqual(after["signature"], before["signature"])
        self.assertEqual(
            history_dates(),
            {"20240609", "20240610", "20240611", "20240612", "20240613"},
        )
        for key, old in old_jobs.items():
            self.assertEqual(
                dict(
                    self.p.db.execute(
                        "SELECT * FROM jobs WHERE id=?", (key,)
                    ).fetchone()
                ),
                old,
            )
        self.discovery("stock_basic", [{"ts_code": "T600018.SH", "list_status": "D"}])
        self.p.plan_extended(changed, date(2024, 6, 20))
        unchanged = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", ("history:" + FAMILY,)
            ).fetchone()
        )
        self.assertEqual(unchanged["signature"], after["signature"])
        self.assertEqual(unchanged["offset"], after["offset"])

    def test_saturated_day_fanout_retains_observed_universe_gap_and_date_split(self):
        self.discovery("stock_basic", [{"ts_code": "600018.SH", "list_status": "D"}])
        self.discovery("etf_basic", [{"ts_code": "510300.SH"}])
        for api in FIELDS:
            row, job, result = self.capture(
                api, {"trade_date": "20240620"}, [source(api)], more=True
            )
            split = self.p.split_request(row, job, result)
            self.assertEqual(split["method"], "identifier_fanout")
            self.assertFalse(split["universe_complete"])
            self.assertEqual(self.p.split_request(row, job, result)["children"], 2)
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {p["ts_code"] for p in children}, {"600018.SH", "T600018.SH"}
            )
            self.assertTrue(all(set(p) == {"trade_date", "ts_code"} for p in children))
            row, job, result = self.capture(
                api,
                {
                    "start_date": "20240228",
                    "end_date": "20240301",
                    "ts_code": "T600018.SH",
                },
                [source(api)],
                more=True,
                epoch="range",
            )
            self.assertEqual(
                self.p.split_request(row, job, result)["method"], "date_bisection"
            )
            params = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {(p["start_date"], p["end_date"]) for p in params},
                {("20240228", "20240229"), ("20240301", "20240301")},
            )

    def test_real_5000_cap_single_stock_day_remains_blocked_not_fake_pagination(self):
        keys = [
            self.p.enqueue(
                api, {"ts_code": "T600018.SH", "trade_date": "20240620"}, 1, "terminal"
            )
            for api in FIELDS
        ]

        def respond(request):
            sent = json.loads(request.content)
            row = source(sent["api_name"])
            self.assertEqual(set(sent["params"]), {"ts_code", "trade_date"})
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": list(row), "items": [list(row.values())] * 5000},
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            report = self.p.run(
                client, "fixture", {}, max_requests=3, max_seconds=10, pause=0
            )
        self.assertEqual(report["requests"], 3)
        for key in keys:
            row = self.p.db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (key,)
            ).fetchone()
            self.assertEqual(row["state"], "blocked")
            result = json.loads(row["result"])
            self.assertEqual(result["row_count"], 5000)
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertTrue(
                (self.root / "objects" / (result["object_sha256"] + ".json")).is_file()
            )
            self.assertTrue((self.root / result["parquet"]["path"]).is_file())
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.capture(
                "slb_sec",
                {"trade_date": "20240619"},
                [source("slb_sec")] * 4000,
                epoch="under_cap",
            )[2]["status"],
            "sample_ok",
        )

    def test_missing_nullable_field_denied_permission_and_shared_gates(self):
        for api in FIELDS:
            self.assertEqual(
                self.capture(
                    api,
                    {"trade_date": "20240620"},
                    [source(api)],
                    omit=["lent_qnt"],
                    epoch="missing",
                )[2]["status"],
                "schema_gap",
            )
        key = self.p.enqueue("slb_sec", {"trade_date": "20240621"}, 1, "deny")
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"code": -2002, "msg": "没有访问该接口权限", "data": None}
                )
            ),
            trust_env=False,
        ) as client:
            self.p.run(client, "fixture", {}, max_requests=1, max_seconds=2, pause=0)
        self.assertEqual(
            self.p.db.execute("SELECT state FROM jobs WHERE id=?", (key,)).fetchone()[
                0
            ],
            "blocked",
        )
        self.assertEqual(
            json.loads(
                self.p.db.execute(
                    "SELECT result FROM jobs WHERE id=?", (key,)
                ).fetchone()[0]
            )["status"],
            "permission_denied",
        )
        later = self.p.enqueue("slb_sec", {"trade_date": "20240622"}, 1, "later")
        self.assertEqual(
            self.p.db.execute("SELECT state FROM jobs WHERE id=?", (later,)).fetchone()[
                0
            ],
            "permission_blocked",
        )
        self.p.enqueue("slb_len_mm", {"trade_date": "20240622"}, 1, "rate")
        with patch.object(module.time, "time", return_value=1000.0):
            chosen = self.p.next_job(
                {"enable_" + FAMILY: True, "requests_per_minute": 240},
                time.monotonic() + 1,
            )
        self.assertIsNotNone(chosen)
        self.assertEqual(
            self.p.db.execute(
                "SELECT next_at FROM request_gates WHERE scope='account'"
            ).fetchone()[0],
            1000.25,
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT next_at FROM request_gates WHERE scope='api:slb_len_mm'"
            ).fetchone()[0],
            1002.0,
        )

    def test_invalid_source_stays_raw_not_fake_normalized_identity(self):
        with self.assertRaisesRegex(ValueError, "source stock code"):
            self.capture(
                "slb_sec",
                {"trade_date": "20240620"},
                [source("slb_sec", ts_code=600018)],
                epoch="bad",
            )
        self.assertEqual(len(list((self.root / "objects").glob("*.json"))), 1)
        self.assertFalse(list((self.root / "parquet").glob("*.parquet")))
        self.discovery("slb_sec", [source("slb_sec", ts_code=600018)])
        self.assertEqual(self.p.identifiers()["stocks"], [])

    def test_mirror_bundles_contract_and_old_family_policy_unchanged(self):
        mirror = (ROOT / "scripts/tushare_mirror.py").read_text()
        self.assertIn(
            '"backend/shared/tushare_securities_lending_history_contracts.py"', mirror
        )
        cfg = {"history_start": "20200101"}
        ids = self.p.identifiers()
        for family in module.PLANNERS:
            if family == FAMILY:
                continue
            self.assertEqual(
                module._planning_inputs(family, cfg, ids),
                module._planning_inputs(
                    family,
                    {
                        **cfg,
                        "enable_" + FAMILY: True,
                        "securities_lending_history_start": "20000101",
                        FAMILY + "_apis": ["slb_sec"],
                    },
                    ids,
                ),
            )


if __name__ == "__main__":
    unittest.main()
