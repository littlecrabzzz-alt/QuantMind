#!/usr/bin/env python3
"""Offline global queue, identifier and document dispatch integration checks."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module  # noqa: E402
from backend.shared.tushare_global_contracts import GLOBAL_CONTRACTS  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_text())


class GlobalPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
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

    def seed(self, api, records, params=None, epoch="fixture", attempt=1):
        """Persist a synthetic supplier observation exactly as a successful run would."""
        params = params or {}
        key = self.p.enqueue(api, params, epoch=epoch)
        fields = list(records[0])
        payload = {
            "code": 0,
            "data": {
                "fields": fields,
                "items": [[r.get(f) for f in fields] for r in records],
            },
        }
        raw = module.json_bytes(payload)
        sha = module.digest(raw)
        module.atomic_json(self.root / "objects" / (sha + ".json"), payload)
        observation = key + str(attempt) + ".json"
        observed = {
            "fetched_at": "2026-09-09T00:00:00+00:00",
            "request": {"params": params},
        }
        module.atomic_json(self.root / "observations" / observation, observed)
        result = {
            "api_name": api,
            "status": "sample_ok",
            "object_sha256": sha,
            "observation": observation,
            "observation_sha256": module.digest(module.json_bytes(observed)),
        }
        result = self.p.normalize(result)
        encoded = json.dumps(result)
        self.p.db.execute(
            "UPDATE jobs SET result=?,state='done',tries=? WHERE id=?",
            (encoded, attempt, key),
        )
        self.p.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (key, attempt, encoded),
        )
        self.p.db.commit()
        return result

    def test_global_opt_in_fields_and_group(self):
        self.assertIs(
            module.PLANNERS["global"],
            __import__(
                "backend.shared.tushare_global_contracts", fromlist=["iter_global_jobs"]
            ).iter_global_jobs,
        )
        self.assertEqual(self.p.plan_extended({}, date(2026, 9, 9)), {})
        config = {
            "enable_global": True,
            "global_apis": ["us_daily"],
            "plan_jobs_per_tick": 2,
            "global_history_start": "20260901",
        }
        for _ in range(10):
            self.p.plan_extended(config, date(2026, 9, 9))
        rows = self.p.db.execute("SELECT * FROM jobs").fetchall()
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(r["group_name"] == "global" for r in rows))
        fields = set(json.loads(rows[0]["job"])["fields"].split(","))
        self.assertTrue({"change", "turnover_ratio", "total_mv", "pe", "pb"} <= fields)
        self.assertEqual(self.p.plan_extended(config, date(2026, 9, 9)), {})
        config["global_history_start"] = "20260831"
        for _ in range(10):
            self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 10
        )

    def test_discovery_keeps_old_attempts_and_retired_supplier_codes(self):
        self.seed(
            "us_basic", [{"ts_code": "OLD", "delist_date": "20190101"}], attempt=1
        )
        self.seed("us_basic", [{"ts_code": "AAPL", "delist_date": None}], attempt=2)
        self.seed(
            "hk_basic",
            [
                {"ts_code": "00001.HK", "list_status": "D"},
                {"ts_code": "00700.HK", "list_status": "L"},
            ],
        )
        self.assertEqual(self.p.identifiers()["us_stocks"], ["AAPL", "OLD"])
        self.assertEqual(self.p.identifiers()["hk_stocks"], ["00001.HK", "00700.HK"])

    def test_prefix_conversion_preserves_raw_and_revision_identity(self):
        cases = [
            ("hk_daily", "00700.HK", "HK00700"),
            ("hk_daily", "02121!AE.HK", "HK02121!AE"),
            ("us_daily", "BRK.B", "USBRK.B"),
            ("us_daily", "USG", "USUSG"),
            ("weekly", "600000.SH", "SH600000"),
            ("index_weekly", "000300.CSI", "CSI000300"),
        ]
        for n, (api, raw_code, normalized) in enumerate(cases):
            original = {
                "ts_code": raw_code,
                "trade_date": "20260908",
                "close": 100.0,
                "extra_unknown": "preserved",
            }
            result = self.seed(api, [original], epoch=str(n))
            row = pq.read_table(self.root / result["parquet"]["path"]).to_pylist()[0]
            self.assertEqual(row["ts_code"], normalized)
            self.assertEqual(row["source_ts_code"], raw_code)
            self.assertEqual(row["extra_unknown"], "preserved")
            self.assertEqual(
                row["_row_identity"], module.digest(module.json_bytes(original))
            )
            self.assertEqual(self.p.records(result), [original])

    def test_saturated_cross_section_fans_out_without_losing_original(self):
        self.seed("us_basic", [{"ts_code": "AAPL"}, {"ts_code": "RETIRED"}])
        key = self.p.enqueue("us_adjfactor", {"trade_date": "20260908"})
        self.p.db.commit()
        payload = {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "exchange",
                    "cum_adjfactor",
                    "close_price",
                ],
                "items": [["AAPL", "20260908", "NAS", 1.0, None]],
            },
        }
        with patch.dict(module.EXTENDED_CONTRACTS["us_adjfactor"], {"row_cap": 1}):
            # Re-enqueue with the patched real cap used by capture_sample.
            self.p.db.execute("DELETE FROM jobs WHERE id=?", (key,))
            key = self.p.enqueue("us_adjfactor", {"trade_date": "20260908"})
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=payload)
                ),
                trust_env=False,
            ) as client:
                self.p.run(client, "synthetic", {}, max_requests=1, pause=0)
        saved = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        self.assertEqual(saved["state"], "split_pending")
        result = json.loads(saved["result"])
        self.assertIn("parquet", result)
        self.assertFalse(result["split"]["universe_complete"])
        pending = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute("SELECT job FROM jobs WHERE state='pending'")
        ]
        self.assertEqual({p["ts_code"] for p in pending}, {"AAPL", "RETIRED"})
        self.assertTrue(all(p["trade_date"] == "20260908" for p in pending))
        row = self.p.db.execute(
            "SELECT * FROM jobs WHERE state='pending' LIMIT 1"
        ).fetchone()
        self.assertIsNone(self.p.split_request(row, json.loads(row["job"])))

    def test_documented_pagination_avoids_identifier_fanout(self):
        self.seed("us_basic", [{"ts_code": "AAPL"}, {"ts_code": "OTHER"}])
        calls = []

        def handler(request):
            params = json.loads(request.content)["params"]
            calls.append(params)
            code = "AAPL" if not params.get("offset") else "OTHER"
            rows = [[code, "20260908", "NAS"]] if len(calls) < 3 else []
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "trade_date", "exchange"],
                        "items": rows,
                    },
                },
            )

        with patch.dict(module.EXTENDED_CONTRACTS["us_daily_adj"], {"row_cap": 1}):
            self.p.enqueue("us_daily_adj", {"trade_date": "20260908", "limit": 1})
            with httpx.Client(
                transport=httpx.MockTransport(handler), trust_env=False
            ) as client:
                self.p.run(client, "synthetic", {}, max_requests=3, pause=0)
        self.assertEqual([p.get("offset", 0) for p in calls], [0, 1, 2])
        self.assertTrue(all("ts_code" not in p for p in calls))
        self.assertFalse(
            self.p.db.execute("SELECT 1 FROM jobs WHERE state='pending'").fetchone()
        )

    def test_unknown_history_gap_is_portable_even_with_1990_scope(self):
        self.p.plan_extended(
            {
                "enable_global": True,
                "global_apis": ["hk_daily"],
                "history_start": "19900101",
                "plan_jobs_per_tick": 1,
            },
            date(2026, 9, 9),
        )
        release = self.p.publish()
        manifest = module.verify_data(self.root, release)
        gap = next(
            c
            for c in manifest["capabilities"]
            if c["scope"] == "planning:global:hk_daily:history"
        )
        self.assertEqual(gap["status"], "unknown_history_bound")
        reason = json.loads(gap["reason"])
        self.assertEqual(reason["requested_start"], "19900101")
        self.assertFalse(reason["scope_is_full_history_proof"])
        self.assertFalse(manifest["history_complete"])
        self.assertTrue(set(GLOBAL_CONTRACTS) <= set(manifest["implemented_contracts"]))
        self.assertEqual(self.p.publish(), release)

    def test_worker_document_mode_registers_without_inline_fetch(self):
        from backend.shared import tushare_documents, tushare_archive

        (self.root / "ENABLED").touch()
        for execution, should_run in [("worker", False), (None, True)]:
            module.atomic_json(
                self.root / "pipeline-config.json",
                {"enable_documents": True, "document_execution": execution},
            )
            pipeline = MagicMock()
            pipeline.run.return_value = {}
            pipeline.plan_extended.return_value = {}
            pipeline.publish.return_value = "synthetic-release"
            pipeline.register_documents.return_value = {"observations": 1}
            with (
                patch.object(module, "ROOT", self.root),
                patch.object(module, "authority"),
                patch.object(module, "get_secret", return_value="synthetic"),
                patch.object(module, "Pipeline", return_value=pipeline),
                patch.object(
                    module.shutil,
                    "disk_usage",
                    return_value=SimpleNamespace(free=200 * 2**30),
                ),
                patch.object(tushare_archive, "recover_archive", return_value={}),
                patch.object(
                    tushare_documents, "run_documents", return_value={"processed": 1}
                ) as download,
            ):
                report = module.tick(max_requests=1, max_seconds=1)
            pipeline.register_documents.assert_called_once()
            self.assertEqual(download.called, should_run)
            self.assertEqual(report["document_registration"], {"observations": 1})
            self.assertEqual("documents" in report, should_run)


if __name__ == "__main__":
    unittest.main()
