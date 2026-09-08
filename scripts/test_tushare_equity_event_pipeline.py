"""Offline equity-event capture, lossless reading and planning integration."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as pipeline  # noqa: E402
from backend.shared.tushare_equity_event_contracts import (  # noqa: E402
    EQUITY_EVENT_CONTRACTS,
    FIELDS,
    INPUT_FIELDS,
)
from backend.shared.tushare_store import read_dataset  # noqa: E402
from scripts.test_tushare_store_extended import release as fixture_release  # noqa: E402

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


def sample(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(ts_code="600036.SH", ann_date="20260904", future_field="retained")
    if "end_date" in row:
        row["end_date"] = "20260630"
    if "holder_name" in row:
        row["holder_name"] = "同名股东"
    row.update(updates)
    return row


class EquityEventPipeline(unittest.TestCase):
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
        self.seen = []

    def capture(self, rows, *, epoch="one", timestamp="2026-09-09T00:00:00Z"):
        for api in rows:
            self.p.enqueue(
                api,
                {"ts_code": "600036.SH"}
                if api.startswith("top10_") or api == "dividend"
                else {"ann_date": "20260904"},
                epoch=epoch,
            )
        self.p.db.commit()

        def respond(request):
            job = json.loads(request.content)
            api = job["api_name"]
            self.assertTrue(set(FIELDS[api]) <= set(job["fields"].split(",")))
            self.assertNotIn("_row_identity", job["fields"])
            self.assertTrue(set(job["params"]) <= set(INPUT_FIELDS[api]))
            self.seen.append(api)
            fields = list(rows[api][0])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [
                            [row.get(key) for key in fields] for row in rows[api]
                        ],
                    },
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with patch("backend.shared.tushare_intake.utc_now", return_value=timestamp):
                self.p.run(client, "fixture-token", {}, max_requests=len(rows), pause=0)
            self.assertEqual(
                self.p.run(client, "fixture-token", {}, max_requests=1, pause=0)[
                    "requests"
                ],
                0,
            )

    def test_all_seven_capture_replay_fixed_release_and_future_unlock(self):
        rows = {api: [sample(api)] for api in EQUITY_EVENT_CONTRACTS}
        rows["share_float"][0]["float_date"] = "20290904"
        rows["top10_floatholders"] = [
            sample("top10_floatholders", hold_change=None),
            sample("top10_floatholders", hold_change=0),
        ]
        self.capture(rows)
        pinned = self.p.publish()
        self.assertEqual(set(self.seen), set(EQUITY_EVENT_CONTRACTS))
        self.assertEqual(
            {r[0] for r in self.p.db.execute("SELECT state FROM jobs")}, {"done"}
        )
        for api in rows:
            table = read_dataset(self.root, pinned, api, codes=["SH600036"])
            self.assertEqual(table.num_rows, len(rows[api]))
            for row in table.to_pylist():
                self.assertEqual(row["source_ts_code"], "600036.SH")
                self.assertEqual(row["future_field"], "retained")
                self.assertTrue(row["_row_identity"])
            meta = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(meta["upstream_calls"], 0)
            if api != "stk_holdernumber":
                self.assertEqual(meta["deduplication_mode"], "distinct_supplier_rows")
        self.assertEqual(
            read_dataset(
                self.root,
                pinned,
                "share_float",
                date_field="ann_date",
                start_date="20260904",
                end_date="20260904",
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                pinned,
                "share_float",
                date_field="float_date",
                end_date="20260909",
            ).num_rows,
            0,
        )
        self.assertEqual(
            {
                r["hold_change"]
                for r in read_dataset(
                    self.root, pinned, "top10_floatholders"
                ).to_pylist()
            },
            {None, 0},
        )

    def test_distinct_events_repeated_observations_and_as_of(self):
        old = sample("repurchase", amount=10)
        self.capture(
            {
                "repurchase": [old],
                "stk_holdernumber": [sample("stk_holdernumber", holder_num=10)],
            }
        )
        first = self.p.publish()
        self.capture(
            {
                "repurchase": [
                    old,
                    sample("repurchase", amount=20),
                    sample("repurchase", amount=20, future_field="new event"),
                ],
                "stk_holdernumber": [sample("stk_holdernumber", holder_num=20)],
            },
            epoch="two",
            timestamp="2026-09-09T01:00:00Z",
        )
        pinned = self.p.publish()
        events = read_dataset(self.root, pinned, "repurchase").to_pylist()
        self.assertEqual(len(events), 3)
        repeated = [r for r in events if r["amount"] == 10][0]
        self.assertEqual(repeated["_fetched_at"], "2026-09-09T01:00:00Z")
        self.assertEqual(read_dataset(self.root, first, "repurchase").num_rows, 1)
        self.assertEqual(
            read_dataset(
                self.root, pinned, "repurchase", as_of="2026-09-09T00:30:00Z"
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(self.root, pinned, "stk_holdernumber").to_pylist()[0][
                "holder_num"
            ],
            20,
        )
        self.assertEqual(
            read_dataset(
                self.root, pinned, "stk_holdernumber", as_of="2026-09-09T00:30:00Z"
            ).to_pylist()[0]["holder_num"],
            10,
        )

    def test_missing_source_identity_fails_closed(self):
        for identity in ("absent", None, ""):
            with self.subTest(identity=identity):
                row = sample("repurchase")
                row.update(_fetched_at="2026-09-09T00:00:00Z", _observation="one")
                if identity != "absent":
                    row["_row_identity"] = identity
                pinned = fixture_release(self.root, [("repurchase", [row])])
                with self.assertRaisesRegex(ValueError, "source row identity"):
                    read_dataset(self.root, pinned, "repurchase")

    def test_planning_gaps_isolation_recovery_and_signature(self):
        config = {
            "enable_equity_event": True,
            "equity_event_apis": ["top10_holders"],
            "plan_jobs_per_tick": 1000,
        }
        self.assertEqual(self.p.plan_extended({}, date(2026, 9, 9)), {})
        self.p.plan_extended(config, date(2026, 9, 9))
        gaps = dict(self.p.db.execute("SELECT scope,status FROM capability"))
        self.assertEqual(
            {
                key.rsplit(":", 1)[-1]
                for key in gaps
                if key.startswith("planning:equity_event:top10_holders:")
            },
            {"discovery", "history", "cap", "revision"},
        )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["600036.SH", "000001.SZ"]}
        ):
            planned = self.p.plan_extended(config, date(2026, 9, 9))
            self.assertIn("recent:equity_event", planned)
            before = self.p.db.execute(
                "SELECT signature FROM planning_state WHERE name='history:equity_event'"
            ).fetchone()[0]
            changed = {**config, "equity_event_history_start": "20240101"}
            self.p.plan_extended(changed, date(2026, 9, 9))
            after = self.p.db.execute(
                "SELECT signature FROM planning_state WHERE name='history:equity_event'"
            ).fetchone()[0]
            self.assertNotEqual(before, after)
            self.p.plan_extended(
                {**changed, "equity_event_apis": ["repurchase"]}, date(2026, 9, 9)
            )
            self.assertNotEqual(
                after,
                self.p.db.execute(
                    "SELECT signature FROM planning_state WHERE name='history:equity_event'"
                ).fetchone()[0],
            )
        bad = {
            **config,
            "history_start": "20260901",
            "enable_supplement": True,
            "supplement_apis": ["moneyflow_dc"],
            "enable_structured": True,
            "structured_apis": ["cn_cpi"],
        }
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["600036.SH"]}
        ):
            planned = self.p.plan_extended(
                {**bad, "equity_event_apis": ["unknown"]}, date(2026, 9, 9)
            )
        self.assertNotIn("recent:equity_event", planned)
        self.assertIn("recent:supplement", planned)
        self.assertIn("recent:structured", planned)
        with patch.object(self.p, "identifiers", return_value={"stocks": ["bad"]}):
            isolated = self.p.plan_extended(
                {
                    **bad,
                    "enable_structured": False,
                    "supplement_apis": ["moneyflow_mkt_dc"],
                },
                date(2026, 9, 9),
            )
        self.assertNotIn("recent:equity_event", isolated)
        self.assertIn("recent:supplement", isolated)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:equity_event'"
            ).fetchone()[0],
            "validation_blocked",
        )
        with patch.object(
            self.p, "identifiers", return_value={"stocks": ["600036.SH"]}
        ):
            self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:equity_event'"
            ).fetchone()[0],
            "validation_passed",
        )
        self.assertEqual(
            {
                r[0]
                for r in self.p.db.execute(
                    "SELECT DISTINCT group_name FROM jobs WHERE json_extract(job,'$.api_name') IN ('top10_holders','repurchase')"
                )
            },
            {"equity_event"},
        )

    def test_permission_and_single_day_saturation_remain_gaps(self):
        self.p.enqueue("dividend", {"ts_code": "600036.SH"})
        self.p.db.commit()
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"code": 40203, "msg": "permission denied"}
                )
            )
        ) as client:
            self.p.run(client, "fixture-token", {}, max_requests=1, pause=0)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='dividend:'"
            ).fetchone()[0],
            "permission_denied",
        )
        with patch.dict(pipeline.EXTENDED_CONTRACTS["repurchase"], {"row_cap": 2}):
            self.capture(
                {
                    "repurchase": [
                        sample("repurchase", amount=1),
                        sample("repurchase", amount=2),
                    ]
                }
            )
        job = self.p.db.execute(
            "SELECT job,state FROM jobs WHERE json_extract(job,'$.api_name')='repurchase'"
        ).fetchone()
        self.assertEqual(job["state"], "blocked")
        self.assertEqual(json.loads(job["job"])["params"], {"ann_date": "20260904"})
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 2
        )
        pinned = self.p.publish()
        manifest = pipeline.manifest_at(self.root, pinned)
        self.assertFalse(manifest["history_complete"])
        self.assertIn("permission_denied", json.dumps(manifest))
        self.assertIn("possibly_truncated", json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
