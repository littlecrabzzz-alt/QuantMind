"""Preserve old invalid attempts while corrected plans cover the same dates."""

import copy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_intake as intake
from backend.shared import tushare_pipeline as module

FACTOR_APIS = ("idx_factor_pro", "fund_factor_pro", "cb_factor_pro")
BAD_PARAMS = {
    **{api: {"start_date": "20240228", "end_date": "20240302"} for api in FACTOR_APIS},
    "fut_index_daily": {"trade_date": "20240229"},
}
CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


class RequestContractGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        self.network = patch(
            "socket.socket.connect", side_effect=AssertionError("offline")
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def job(self, key):
        return dict(
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        )

    def legacy(self, api):
        key = self.p.enqueue(api, BAD_PARAMS[api], 10, "history")
        job = json.loads(self.job(key)["job"])
        # Reproduce a retained attempt made by the previous deployed contract.
        with (
            patch.object(intake, "validate_request_shape"),
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        json={
                            "code": 50101,
                            "msg": "fixture missing required selector",
                        },
                    )
                )
            ) as client,
        ):
            result = intake.capture_sample(client, "fixture-only", job, self.root)
        encoded = json.dumps(result)
        self.p.db.execute("INSERT INTO attempts VALUES(?,?,?)", (key, 1, encoded))
        self.p.db.execute("UPDATE jobs SET result=?,tries=1 WHERE id=?", (encoded, key))
        self.p.db.commit()
        return key

    def run_once(self, keys=None, requests=4):
        self.sent = []

        def respond(request):
            body = json.loads(request.content)
            intake.validate_request_shape(body)
            self.sent.append(body)
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": [], "items": []}}
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            return self.p.run(
                client, "fixture-only", {}, requests, 3, pause=0, task_ids=keys
            )

    def test_capture_rejects_invalid_before_quota_token_or_http(self):
        for api, params in BAD_PARAMS.items():
            with (
                self.subTest(api=api),
                patch(
                    "backend.shared.tushare_daily_quota.reserve",
                    side_effect=AssertionError("no quota reservation"),
                ),
            ):
                with self.assertRaises(ValueError):
                    intake.capture_sample(
                        None, "", {"api_name": api, "params": params}, self.root
                    )
        self.assertFalse((self.root / "objects").exists())
        self.assertFalse((self.root / "observations").exists())

    def test_legacy_evidence_retained_and_valid_work_continues(self):
        keys = [self.legacy(api) for api in BAD_PARAMS]
        before = {key: self.job(key) for key in keys}
        attempts = [
            tuple(r)
            for r in self.p.db.execute("SELECT * FROM attempts ORDER BY job_id")
        ]
        hashes = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("objects", "observations")
            for p in (self.root / folder).iterdir()
        }
        for api in BAD_PARAMS:
            params = {"trade_date": "20240229"}
            if api == "fut_index_daily":
                params["ts_code"] = "NHCI.NH"
            self.p.enqueue(api, params, 20, "history")
        report = self.run_once()
        self.assertEqual(report["requests"], 4)
        self.assertEqual(report["invalid_requests_blocked"], 4)
        self.assertEqual(len(self.sent), 4)
        for key in keys:
            self.assertEqual(self.job(key), {**before[key], "state": "blocked"})
            capability = self.p.db.execute(
                "SELECT status,reason FROM capability WHERE scope=?",
                ("dispatch:" + key,),
            ).fetchone()
            self.assertEqual(capability[0], "request_contract_blocked")
            self.assertFalse(json.loads(capability[1])["coverage_proven"])
            self.assertEqual(json.loads(capability[1])["upstream_calls"], 0)
        for old in attempts:
            self.assertEqual(
                tuple(
                    self.p.db.execute(
                        "SELECT * FROM attempts WHERE job_id=? AND attempt=?", old[:2]
                    ).fetchone()
                ),
                old,
            )
        self.assertEqual(
            hashes,
            {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes},
        )
        report = self.run_once(keys)
        self.assertEqual(report["requests"], 0)
        self.assertEqual(self.sent, [])

    def test_exact_invalid_scope_never_recaptures_and_transaction_rolls_back(self):
        key = self.legacy("idx_factor_pro")
        before = self.job(key)
        self.p.db.execute(
            "CREATE TEMP TRIGGER fail_guard BEFORE INSERT ON capability BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
        self.p.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_once([key])
        self.assertEqual(self.job(key), before)
        self.assertEqual(self.sent, [])
        self.p.db.execute("DROP TRIGGER fail_guard")
        self.p.db.commit()
        report = self.run_once([key])
        self.assertEqual(report["requests"], 0)
        self.assertEqual(report["invalid_requests_blocked"], 1)
        self.assertEqual(self.job(key), {**before, "state": "blocked"})

    def test_invalid_selection_does_not_reserve_rate_or_fairness_budget(self):
        key = self.legacy("idx_factor_pro")
        self.p.db.execute("INSERT INTO request_gates VALUES('account',1)")
        self.p.db.execute("INSERT INTO request_gates VALUES('api:idx_factor_pro',2)")
        self.p.db.execute("INSERT INTO scheduler_state VALUES('sentinel',17)")
        self.p.db.commit()
        self.p._install_exact_task_scope([key])
        before = {
            table: [
                tuple(r)
                for r in self.p.db.execute("SELECT * FROM " + table + " ORDER BY 1")
            ]
            for table in ("request_gates", "scheduler_state")
        }
        fair_turn = self.p._fair_turn
        for rpm in (None, 500):
            for exact in (False, True):
                config = {"enable_cross_asset_extra": True}
                if rpm:
                    config.update(rate_policy="tiered_v1", requests_per_minute=rpm)
                with self.subTest(rpm=rpm, exact=exact):
                    row = self.p.next_job(
                        config, time.monotonic() + 1, task_scope=exact
                    )
                    self.assertEqual(row["id"], key)
                    self.assertEqual(self.p._fair_turn, fair_turn)
                    for table, expected in before.items():
                        self.assertEqual(
                            [
                                tuple(r)
                                for r in self.p.db.execute(
                                    "SELECT * FROM " + table + " ORDER BY 1"
                                )
                            ],
                            expected,
                        )

    def test_changed_factor_policy_replays_old_incomplete_cursor_without_date_gaps(
        self,
    ):
        config = {
            "enable_cross_asset_extra": True,
            "cross_asset_extra_apis": list(FACTOR_APIS),
            "history_start": "20240228",
            "plan_jobs_per_tick": 1000,
        }
        old = {
            api: copy.deepcopy(module.EXTENDED_CONTRACTS[api]) for api in FACTOR_APIS
        }
        for spec in old.values():
            spec.pop("parameter_note", None)
            spec.pop("planning_note", None)

        def legacy_planner(config, today, identifiers=None):
            for api in FACTOR_APIS:
                yield {
                    "api_name": api,
                    "params": BAD_PARAMS[api],
                    "epoch": "history",
                    "priority": 55,
                }

        with patch.object(self.p, "identifiers", return_value={}):
            with (
                patch.dict(module.EXTENDED_CONTRACTS, old),
                patch.dict(module.PLANNERS, {"cross_asset_extra": legacy_planner}),
            ):
                self.p.plan_extended(config, date(2024, 3, 10))
            previous = self.p.db.execute(
                "SELECT signature FROM planning_state WHERE name='history:cross_asset_extra'"
            ).fetchone()[0]
            self.p.db.execute(
                "UPDATE planning_state SET offset=9000,done=0 WHERE name='history:cross_asset_extra'"
            )
            self.p.db.commit()
            self.p.plan_extended(config, date(2024, 3, 10))
        current = self.p.db.execute(
            "SELECT signature,offset FROM planning_state WHERE name='history:cross_asset_extra'"
        ).fetchone()
        self.assertNotEqual(
            json.loads(previous)["policy"], json.loads(current[0])["policy"]
        )
        self.assertLess(current[1], 9000)
        expected = {
            (date(2024, 2, 28) + timedelta(days=i)).strftime("%Y%m%d")
            for i in range(11)
        }
        for api in FACTOR_APIS:
            jobs = [
                json.loads(row[0])
                for row in self.p.db.execute(
                    "SELECT job FROM jobs WHERE json_extract(job,'$.api_name')=?",
                    (api,),
                )
            ]
            self.assertEqual(
                {
                    job["params"]["trade_date"]
                    for job in jobs
                    if "trade_date" in job["params"]
                },
                expected,
            )
            self.assertTrue(any(job["params"] == BAD_PARAMS[api] for job in jobs))


if __name__ == "__main__":
    unittest.main()
