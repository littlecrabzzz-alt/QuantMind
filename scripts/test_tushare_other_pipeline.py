#!/usr/bin/env python3
"""Offline capture -> normalize -> immutable release -> DuckDB reader acceptance."""

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
from backend.shared import tushare_pipeline as module  # noqa: E402
from backend.shared.tushare_other_contracts import OTHER_CONTRACTS, FIELDS  # noqa: E402
from backend.shared.tushare_store import read_dataset, dataset_schema, KEYS  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_text())


def sample(api):
    row = dict.fromkeys(FIELDS[api])
    if api.startswith("opt_"):
        row.update(ts_code="600000.SH", symbol="600000", delist_date="20200101")
    elif api.startswith("sge_"):
        row.update(ts_code="Au(T+D)")
    elif api.startswith("fx_"):
        row.update(ts_code="USDCNH.FXCM")
    if "trade_date" in row:
        row["trade_date"] = "20260908"
    if "date" in row:
        row["date"] = "20260908"
    if api == "libor":
        row.update(curr_type="CHF", **{"1m": -0.75})
    if api == "hibor":
        row["2w"] = 1.25
    row["future_vendor_field"] = "retained"
    return row


class OtherPipeline(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(name, side_effect=AssertionError("Offline test boundary"))
            guard.start()
            self.addCleanup(guard.stop)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)

    def capture(self, samples):
        seen = []

        def respond(request):
            job = json.loads(request.content)
            api = job["api_name"]
            self.assertTrue(set(FIELDS[api]) <= set(job["fields"].split(",")))
            rows = samples[api]
            fields = list(rows[0])
            seen.append(api)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                    },
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self.p.run(
                client,
                "synthetic-fixture",
                {"priority_start": "20200101"},
                max_requests=len(samples),
                pause=0,
            )
        self.assertEqual(set(seen), set(samples))

    def test_all_fifteen_capture_and_offline_pinned_read(self):
        for api in OTHER_CONTRACTS:
            params = (
                {}
                if api.endswith("basic")
                else {"start_date": "20260908", "end_date": "20260908"}
            )
            if api == "libor":
                params["curr_type"] = "CHF"
            self.p.enqueue(api, params)
        self.p.db.commit()
        self.capture({api: [sample(api)] for api in OTHER_CONTRACTS})
        self.assertEqual(self.p.status(), {"done": 15})
        self.p.record_other_planning_gaps(
            {"other_history_start": "19900101"}, self.p.identifiers()
        )
        self.p.db.commit()
        release = self.p.publish()
        for api in OTHER_CONTRACTS:
            table = read_dataset(self.root, release, api)
            row = table.to_pylist()[0]
            self.assertEqual(table.num_rows, 1)
            self.assertEqual(row["future_vendor_field"], "retained")
            self.assertEqual(KEYS[api], tuple(OTHER_CONTRACTS[api]["keys"]))
            self.assertEqual(
                {f["name"] for f in dataset_schema(self.root, release, api)["fields"]},
                set(table.column_names),
            )
            if api.startswith(("opt_", "sge_", "fx_")):
                prefix = {"opt": "OPT:", "sge": "SGE:", "fx": "FX:"}[api.split("_")[0]]
                self.assertEqual(row["ts_code"], prefix + sample(api)["ts_code"])
                self.assertEqual(row["source_ts_code"], sample(api)["ts_code"])
                filtered = read_dataset(self.root, release, api, codes=[row["ts_code"]])
                self.assertEqual(filtered.num_rows, 1)
            self.assertFalse(
                json.loads(table.schema.metadata[b"tushare"])[
                    "historical_versions_complete"
                ]
            )
        option = read_dataset(self.root, release, "opt_basic").to_pylist()[0]
        self.assertEqual(option["symbol"], "OPT:600000")
        self.assertEqual(option["source_symbol"], "600000")
        self.assertEqual(
            read_dataset(self.root, release, "libor").to_pylist()[0]["1m"], -0.75
        )
        self.assertEqual(
            read_dataset(self.root, release, "hibor").to_pylist()[0]["2w"], 1.25
        )
        manifest = json.loads(
            (self.root / "releases" / release / "manifest.json").read_text()
        )
        self.assertFalse(manifest["history_complete"])
        self.assertEqual(manifest["rrg_status"], "blocked_data")
        self.assertTrue(
            any(c["status"] == "discovery_unverified" for c in manifest["capabilities"])
        )
        self.assertTrue(set(OTHER_CONTRACTS) <= set(manifest["implemented_contracts"]))

    def test_retired_discovery_and_daily_only_symbols_are_union(self):
        for api in ("opt_basic", "sge_basic", "fx_obasic"):
            self.p.enqueue(api, {}, epoch="old")
        self.p.db.commit()
        self.capture(
            {api: [sample(api)] for api in ("opt_basic", "sge_basic", "fx_obasic")}
        )
        for api in ("opt_daily", "sge_daily", "fx_daily"):
            self.p.enqueue(api, {"trade_date": "20260908"}, epoch="new")
        self.p.db.commit()
        daily = {
            api: [{**sample(api), "ts_code": code}]
            for api, code in (
                ("opt_daily", "M1707-C-2400.DCE"),
                ("sge_daily", "Pt99.95"),
                ("fx_daily", "BTCUSD.FXCM"),
            )
        }
        self.capture(daily)
        ids = self.p.identifiers()
        self.assertEqual(ids["options"], ["600000.SH", "M1707-C-2400.DCE"])
        self.assertEqual(ids["spot_metals"], ["Au(T+D)", "Pt99.95"])
        self.assertEqual(ids["fx_instruments"], ["BTCUSD.FXCM", "USDCNH.FXCM"])
        self.assertNotIn("600000.SH", ids["stocks"])
        self.p.record_other_planning_gaps({"other_apis": ["opt_daily"]}, ids)
        reason = json.loads(
            self.p.db.execute(
                "SELECT reason FROM capability WHERE scope='planning:other:opt_daily:discovery'"
            ).fetchone()[0]
        )
        self.assertFalse(reason["universe_complete"])

    def test_flag_incremental_planning_and_config_invalidation(self):
        self.assertEqual(self.p.plan_extended({}, date(2026, 9, 9)), {})
        config = {
            "enable_other": True,
            "other_apis": ["fx_daily"],
            "other_history_start": "20260908",
            "plan_jobs_per_tick": 1,
        }
        for _ in range(4):
            self.p.plan_extended(config, date(2026, 9, 9))
        rows = self.p.db.execute("SELECT * FROM jobs").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["group_name"] == "other" for r in rows))
        config["other_history_start"] = "20260907"
        for _ in range(5):
            self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 3
        )
        cap = self.p.db.execute(
            "SELECT status FROM capability WHERE scope='planning:other:fx_daily:discovery'"
        ).fetchone()[0]
        self.assertEqual(cap, "awaiting_discovery")

    def test_saturated_daily_keeps_unverified_universe_gap(self):
        self.p.enqueue("opt_basic", {})
        self.p.db.commit()
        records = [
            sample("opt_basic"),
            {**sample("opt_basic"), "ts_code": "M1707-C-2400.DCE"},
        ]
        self.capture({"opt_basic": records})
        rows = [
            sample("opt_daily"),
            {**sample("opt_daily"), "ts_code": "M1707-C-2400.DCE"},
        ]
        with patch.dict(module.EXTENDED_CONTRACTS["opt_daily"], {"row_cap": 2}):
            key = self.p.enqueue("opt_daily", {"trade_date": "20260908"})
            self.p.db.commit()
            self.capture({"opt_daily": rows})
        split = self.p.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (key,)
        ).fetchone()
        self.assertEqual(split["expected_children"], 2)
        self.assertEqual(split["coverage_proven"], 0)
        self.p.reconcile_partitions()
        split = self.p.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (key,)
        ).fetchone()
        self.assertEqual(split["gap"], "universe_unverified")
        children = self.p.db.execute(
            "SELECT job FROM jobs WHERE id IN (SELECT child_id FROM partition_children WHERE parent_id=?)",
            (key,),
        ).fetchall()
        self.assertEqual(
            {json.loads(j[0])["params"]["ts_code"] for j in children},
            {"600000.SH", "M1707-C-2400.DCE"},
        )
        self.assertEqual(
            self.p.db.execute("SELECT state FROM jobs WHERE id=?", (key,)).fetchone()[
                0
            ],
            "split_pending",
        )

    def test_hk_retired_reused_code_remains_distinct(self):
        self.p.enqueue("hk_basic", {"list_status": "D"})
        self.p.db.commit()
        payload = {
            "code": 0,
            "data": {
                "fields": ["ts_code", "name"],
                "items": [["02121!AE.HK", "retired"], ["02121.HK", "current"]],
            },
        }
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client:
            self.p.run(
                client,
                "synthetic-fixture",
                {"priority_start": "20200101"},
                max_requests=1,
                pause=0,
            )
        release = self.p.publish()
        rows = read_dataset(self.root, release, "hk_basic").to_pylist()
        self.assertEqual({r["ts_code"] for r in rows}, {"HK02121!AE", "HK02121"})
        self.assertEqual(
            {r["source_ts_code"] for r in rows}, {"02121!AE.HK", "02121.HK"}
        )
        self.assertEqual({r["name"] for r in rows}, {"retired", "current"})
        self.assertEqual(self.p.identifiers()["hk_stocks"], ["02121!AE.HK", "02121.HK"])

    def test_legacy_hk_projection_deduplicates_before_filter_without_rewrite(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        payload = {
            "code": 0,
            "data": {
                "fields": ["ts_code", "name"],
                "items": [["02121!AE.HK", "old retired name"], ["02121.HK", "current"]],
            },
        }
        original_write = pq.write_table

        def legacy_write(table, *args, **kwargs):
            # Create a legacy-format fixture initially; never rewrite stored files.
            codes = [
                "02121!AE.HK" if c == "HK02121!AE" else c
                for c in table["ts_code"].to_pylist()
            ]
            table = table.set_column(
                table.schema.get_field_index("ts_code"), "ts_code", pa.array(codes)
            )
            return original_write(table, *args, **kwargs)

        for epoch, observed in (
            ("old", "2026-09-08T00:00:00+00:00"),
            ("new", "2026-09-09T00:00:00+00:00"),
        ):
            self.p.enqueue("hk_basic", {"list_status": "D"}, epoch=epoch)
            self.p.db.commit()
            if epoch == "new":
                payload["data"]["items"][0][1] = "new retired name"
            with (
                httpx.Client(
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=payload)
                    )
                ) as client,
                patch("backend.shared.tushare_intake.utc_now", return_value=observed),
                patch(
                    "pyarrow.parquet.write_table",
                    side_effect=legacy_write if epoch == "old" else original_write,
                ),
            ):
                self.p.run(
                    client,
                    "synthetic-fixture",
                    {"priority_start": "20200101"},
                    max_requests=1,
                    pause=0,
                )
            if epoch == "old":
                old_release = self.p.publish()
                old_manifest = json.loads(
                    (self.root / "releases" / old_release / "manifest.json").read_text()
                )
                immutable_before = {
                    name: module.digest((self.root / name).read_bytes())
                    for name in old_manifest["files"]
                }
        release = self.p.publish()
        rows = read_dataset(self.root, release, "hk_basic").to_pylist()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["ts_code"] for r in rows}, {"HK02121!AE", "HK02121"})
        retired = read_dataset(
            self.root, release, "hk_basic", codes=["HK02121!AE"]
        ).to_pylist()
        self.assertEqual(len(retired), 1)
        self.assertEqual(retired[0]["name"], "new retired name")
        self.assertEqual(retired[0]["source_ts_code"], "02121!AE.HK")
        prior = read_dataset(
            self.root,
            release,
            "hk_basic",
            codes=["HK02121!AE"],
            as_of="2026-09-08T12:00:00+00:00",
        ).to_pylist()
        self.assertEqual(len(prior), 1)
        self.assertEqual(prior[0]["name"], "old retired name")
        self.assertEqual(prior[0]["_fetched_at"], "2026-09-08T00:00:00+00:00")
        self.assertEqual(prior[0]["source_ts_code"], "02121!AE.HK")
        self.assertEqual(
            read_dataset(
                self.root, old_release, "hk_basic", codes=["HK02121!AE"]
            ).to_pylist()[0]["name"],
            "old retired name",
        )
        for name, sha in immutable_before.items():
            self.assertEqual(module.digest((self.root / name).read_bytes()), sha)
        legacy_codes = {
            r["ts_code"]
            for d in old_manifest["datasets"]
            for r in pq.read_table(self.root / d["path"]).to_pylist()
        }
        self.assertIn("02121!AE.HK", legacy_codes)

    def test_invalid_discovery_blocks_only_family_and_recovers(self):
        config = {
            "enable_global": True,
            "enable_other": True,
            "enable_structured": True,
            "enable_text": True,
            "global_apis": ["hk_daily"],
            "other_apis": ["fx_daily"],
            "structured_apis": ["daily"],
            "text_apis": ["news"],
            "history_start": "20260908",
            "plan_jobs_per_tick": 1,
        }
        original = json.dumps(config, sort_keys=True)
        ids = self.p.identifiers()
        with patch.object(self.p, "identifiers", return_value=ids):
            self.p.plan_extended(config, date(2026, 9, 9))
        before = [
            tuple(r)
            for r in self.p.db.execute(
                "SELECT * FROM planning_state WHERE name LIKE '%:global' ORDER BY name"
            )
        ]
        bad = {**ids, "hk_stocks": ["bad HK identifier"]}
        with patch.object(self.p, "identifiers", return_value=bad):
            continued = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertTrue(
            {"recent:text", "recent:structured", "recent:other"} <= set(continued)
        )
        self.assertNotIn("recent:global", continued)
        after = [
            tuple(r)
            for r in self.p.db.execute(
                "SELECT * FROM planning_state WHERE name LIKE '%:global' ORDER BY name"
            )
        ]
        self.assertEqual(before, after)
        cap = self.p.db.execute(
            "SELECT status,reason FROM capability WHERE scope='planning:global'"
        ).fetchone()
        self.assertEqual(cap["status"], "validation_blocked")
        self.assertEqual(json.loads(cap["reason"])["error_type"], "ValueError")
        groups = {
            r[0] for r in self.p.db.execute("SELECT DISTINCT group_name FROM jobs")
        }
        self.assertTrue({"text", "structured", "other"} <= groups)
        with patch.object(self.p, "identifiers", return_value=ids):
            self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:global'"
            ).fetchone()[0],
            "validation_passed",
        )
        self.assertEqual(original, json.dumps(config, sort_keys=True))
        # All families blocked must still persist their diagnostic across reopen.
        bad_other = {**ids, "options": ["invalid option identifier"]}
        with patch.object(self.p, "identifiers", return_value=bad_other):
            self.p.plan_extended(
                {"enable_other": True, "other_apis": ["fx_daily"]}, date(2026, 9, 9)
            )
        with module.sqlite3.connect(self.root / "pipeline.sqlite") as db:
            self.assertEqual(
                db.execute(
                    "SELECT status FROM capability WHERE scope='planning:other'"
                ).fetchone()[0],
                "validation_blocked",
            )

    def test_permission_denial_survives_publish(self):
        self.p.enqueue("opt_basic", {})
        self.p.db.commit()
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"code": 40203, "msg": "permission denied", "data": None}
                )
            )
        ) as client:
            self.p.run(
                client,
                "synthetic-fixture",
                {"priority_start": "20200101"},
                max_requests=1,
                pause=0,
            )
        self.p.enqueue("opt_basic", {"exchange": "SSE"})
        self.p.db.commit()
        release = self.p.publish()
        manifest = json.loads(
            (self.root / "releases" / release / "manifest.json").read_text()
        )
        self.assertTrue(
            any(c["status"] == "permission_denied" for c in manifest["capabilities"])
        )
        self.assertTrue(any(g["api_name"] == "opt_basic" for g in manifest["gaps"]))
        self.assertEqual(self.p.status().get("permission_blocked"), 1)
        self.assertFalse(manifest["history_complete"])


if __name__ == "__main__":
    unittest.main()
