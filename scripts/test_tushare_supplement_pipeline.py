"""Supplement capture, discovery, replay and offline reader integration."""

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend.shared import tushare_pipeline as pipeline
from backend.shared.tushare_store import read_dataset
from backend.shared.tushare_supplement_contracts import FIELDS, SUPPLEMENT_CONTRACTS

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


class SupplementPipeline(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.p = pipeline.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("Offline boundary"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_all_five_capture_replay_and_fixed_release_reads(self):
        samples = {}
        for api in SUPPLEMENT_CONTRACTS:
            row = dict.fromkeys(FIELDS[api])
            row["future_field"] = "retained"
            if "trade_date" in row:
                row["trade_date"] = "20260904"
            if "ts_code" in row:
                row["ts_code"] = (
                    "000171.CSI"
                    if api == "mkt_idx_bmk"
                    else "510300.SH"
                    if api == "etf_share_size"
                    else "600036.SH"
                )
            if api == "mkt_idx_bmk":
                row["bmk_level"] = "一类库"
            elif api == "etf_share_size":
                row.update(nav=3.42, close=3.43, total_share=123.0)
            else:
                row["net_amount"] = -123.5
            samples[api] = row
            self.p.enqueue(
                api, {} if api == "mkt_idx_bmk" else {"trade_date": "20260904"}
            )
        self.p.db.commit()
        seen = []

        def respond(request):
            job = json.loads(request.content)
            api = job["api_name"]
            self.assertTrue(set(FIELDS[api]) <= set(job["fields"].split(",")))
            seen.append(api)
            row = samples[api]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": list(row), "items": [list(row.values())]},
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self.p.run(client, "fixture-token", {}, max_requests=5, pause=0)
            release = self.p.publish()
            self.assertEqual(
                self.p.run(client, "fixture-token", {}, max_requests=5, pause=0)[
                    "requests"
                ],
                0,
            )
        self.assertEqual(set(seen), set(samples))
        self.assertEqual(self.p.identifiers()["indexes"], ["000171.CSI"])
        for api in samples:
            rows = read_dataset(self.root, release, api).to_pylist()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["future_field"], "retained")
            if "ts_code" in samples[api]:
                self.assertEqual(rows[0]["source_ts_code"], samples[api]["ts_code"])
                self.assertNotIn(".", rows[0]["ts_code"])
        etf = read_dataset(
            self.root,
            release,
            "etf_share_size",
            codes=["SH510300"],
            fields=["nav", "close"],
        ).to_pylist()
        self.assertEqual(etf, [{"nav": 3.42, "close": 3.43}])
        self.assertEqual(
            read_dataset(
                self.root, release, "mkt_idx_bmk", codes=["CSI000171"]
            ).num_rows,
            1,
        )

    def test_planning_opt_in_isolation_and_scope_change(self):
        config = {
            "enable_supplement": True,
            "supplement_apis": ["moneyflow_dc"],
            "history_start": "20230901",
            "plan_jobs_per_tick": 1000,
        }
        self.assertEqual(self.p.plan_extended({}, date(2023, 9, 15)), {})
        self.p.plan_extended(config, date(2023, 9, 15))
        jobs = [json.loads(row[0]) for row in self.p.db.execute("SELECT job FROM jobs")]
        self.assertEqual(
            {job["params"]["trade_date"] for job in jobs},
            {"20230911", "20230912", "20230913", "20230914", "20230915"},
        )
        self.assertTrue(
            all(
                row[0] == "supplement"
                for row in self.p.db.execute("SELECT group_name FROM jobs")
            )
        )
        self.assertEqual(self.p.plan_extended(config, date(2023, 9, 15)), {})
        bad = {
            **config,
            "supplement_apis": ["invalid"],
            "enable_structured": True,
            "structured_apis": ["cn_cpi"],
        }
        planned = self.p.plan_extended(bad, date(2023, 9, 15))
        self.assertIn("recent:structured", planned)
        self.assertNotIn("recent:supplement", planned)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:supplement'"
            ).fetchone()[0],
            "validation_blocked",
        )
        self.p.plan_extended(config, date(2023, 9, 15))
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:supplement'"
            ).fetchone()[0],
            "validation_passed",
        )


if __name__ == "__main__":
    unittest.main()
