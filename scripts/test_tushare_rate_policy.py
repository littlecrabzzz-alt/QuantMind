"""No credentials/network: real temporary SQLite and mocked HTTP at the boundary."""

import json
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from backend.shared import tushare_pipeline as pmod
from backend.shared import tushare_daily_quota as quota
from backend.shared import tushare_rate_policy as policy
from backend.shared.tushare_intake import capture_sample

NOW = datetime(2026, 9, 9, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
CONFIG = {
    "rate_policy": "tiered_v1",
    "requests_per_minute": 500,
    "rollout_account_rpm": 300,
}


class Rates(unittest.TestCase):
    def rate(self, api, spec=None, config=None, now=NOW):
        return policy.resolved_api_rate(api, spec or {}, config or CONFIG, now)["rpm"]

    def test_exact_purchased_families_and_page_priority(self):
        for api, rate in policy.PURCHASED_RPM.items():
            self.assertEqual(self.rate(api), rate)
        self.assertEqual(
            self.rate("news", {"documented_requests_per_minute": 100}), 100
        )
        for api, rate in policy.PAGE_RPM.items():
            self.assertEqual(self.rate(api), rate)
        self.assertEqual(self.rate("daily"), 500)
        self.assertEqual(self.rate("cyq_perf"), 300)
        self.assertEqual(self.rate("factor_value", {"requests_per_minute": 30}), 30)
        self.assertEqual(
            self.rate(
                "hk_mins",
                {"independent_permission": "unknown", "requests_per_minute": 30},
            ),
            30,
        )

    def test_tiers_config_can_only_lower_and_unknown_metadata(self):
        spec = {
            "documented_rate_tiers": [
                {"minimum_points": 5000, "rpm": 30},
                {"minimum_points": 8000, "rpm": 500},
            ]
        }
        self.assertEqual(self.rate("stk_factor_pro", spec), 500)
        self.assertEqual(
            self.rate(
                "daily", config={**CONFIG, "api_requests_per_minute": {"daily": 120}}
            ),
            120,
        )
        self.assertEqual(
            self.rate(
                "daily",
                {
                    "documented_requests_per_minute": {
                        "2000_points": 200,
                        "5000_points": 500,
                    }
                },
            ),
            500,
        )
        self.assertEqual(
            self.rate("other_regular", {"documented_requests_per_minute": 50}), 50
        )
        self.assertEqual(self.rate("daily", {"documented_requests_per_minute": 50}), 50)
        self.assertEqual(self.rate("other_regular", {"requests_per_minute": 30}), 300)
        for api in policy.UNKNOWN_APIS:
            for cap in (30, 50):
                self.assertEqual(self.rate(api, {"requests_per_minute": cap}), cap)

    def test_expiry_notice_and_conservative_downgrade(self):
        report = policy.policy_report(CONFIG, NOW)
        self.assertEqual(report["entitlement"]["notice"], "expires_within_90_days")
        self.assertEqual(report["entitlement"]["expected_points_after_expiry"], 8100)
        expired = datetime(2026, 12, 5, tzinfo=NOW.tzinfo)
        self.assertEqual(
            policy.policy_report(CONFIG, expired)["cyq_perf_daily_cap"], 20000
        )
        self.assertEqual(self.rate("daily", now=expired), 500)
        self.assertEqual(self.rate("cyq_perf", now=expired), 200)
        self.assertEqual(
            self.rate(
                "news",
                {"requests_per_minute": 50},
                now=datetime(2027, 9, 8, tzinfo=NOW.tzinfo),
            ),
            50,
        )

    def test_explicit_category_allowlist_and_post_expiry_special_review(self):
        evidence = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "docs/tushare-general-rate-refinement.json"
            ).read_bytes()
        )["api_sets"]
        self.assertEqual(policy.REGULAR_APIS, frozenset(evidence["regular_500"]))
        self.assertEqual(
            policy.SPECIAL - {"broker_recommend", "cyq_chips", "report_rc", "cyq_perf"},
            set(evidence["special_300"]),
        )
        self.assertEqual(
            policy.UNKNOWN_APIS - {"fut_weekly_monthly", "hsgt_top10", "namechange"},
            set(evidence["uncertain"]),
        )
        expired = datetime(2026, 12, 5, tzinfo=NOW.tzinfo)
        for api in policy.REGULAR_APIS:
            self.assertEqual(self.rate(api, now=expired), 500)
        for api, cap in [
            ("stk_nineturn", 30),
            ("stk_ah_comparison", 30),
            ("stk_surv", 50),
        ]:
            spec = {"requests_per_minute": cap}
            self.assertEqual(self.rate(api, spec), 300)
            resolved = policy.resolved_api_rate(api, spec, CONFIG, expired)
            self.assertEqual(resolved["rpm"], cap)
            self.assertTrue(resolved["review_required"])
        resolved = policy.resolved_api_rate(
            "hm_detail",
            {"requests_per_minute": 50, "minimum_points": 10000},
            CONFIG,
            expired,
        )
        self.assertTrue(resolved["review_required"])
        self.assertEqual(resolved["review_reason"], "points_below_documented_minimum")

    def test_legacy_exact_compatibility_and_invalid(self):
        self.assertEqual(
            self.rate("daily", {"requests_per_minute": 30}, {"rate_policy": "legacy"}),
            30,
        )
        for value in (0, True, 501, "500"):
            with self.assertRaises(ValueError):
                self.rate(
                    "daily",
                    config={**CONFIG, "api_requests_per_minute": {"daily": value}},
                )
        with self.assertRaises(ValueError):
            policy.enabled({"rate_policy": "typo"})


class DurableQuota(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "pipeline-config.json").write_text(json.dumps(CONFIG))
        self.day = NOW.timestamp()
        for name in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(name, side_effect=AssertionError("offline"))
            guard.start()
            self.addCleanup(guard.stop)

    def reserve(self, stamp=None):
        return quota.reserve(
            self.root, "cyq_perf", now=self.day if stamp is None else stamp
        )

    def test_first_day_guard_persists_reopen_only_cyq(self):
        for _ in range(2):
            r = self.reserve()
            self.assertEqual(r["reason"], "activation_guard")
            self.assertFalse(r["reserved"])
        self.assertIsNone(quota.reserve(self.root, "daily", now=self.day))
        self.assertTrue(self.reserve(self.day + 86400)["reserved"])

    def test_midnight_is_beijing_and_cap_reopen(self):
        self.reserve()
        midnight = datetime(2026, 9, 10, tzinfo=NOW.tzinfo).timestamp()
        self.assertEqual(self.reserve(midnight - 0.01)["reason"], "activation_guard")
        self.assertEqual(self.reserve(midnight)["used"], 1)
        db = sqlite3.connect(self.root / "daily-quota.sqlite")
        db.execute("UPDATE daily_quota SET used=199999")
        db.commit()
        db.close()
        self.assertEqual(self.reserve(midnight + 1)["used"], 200000)
        self.assertEqual(self.reserve(midnight + 2)["reason"], "daily_quota_exhausted")
        self.assertEqual(self.reserve(midnight + 86400)["used"], 1)
        self.assertEqual(self.reserve(midnight + 3)["reason"], "clock_rollback_guard")

    def test_transport_failures_reserved_and_legacy_zero_mutation(self):
        job = {
            "api_name": "cyq_perf",
            "params": {"ts_code": "000001.SZ"},
            "fields": "ts_code,trade_date",
            "required_fields": [],
            "row_cap": 6000,
        }
        self.reserve()
        with (
            patch.object(quota.time, "time", return_value=self.day + 86400),
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("fixture"))
                )
            ) as client,
        ):
            result = capture_sample(client, "synthetic", job, self.root)
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(self.reserve(self.day + 86400 + 1)["used"], 2)
        before = (self.root / "daily-quota.sqlite").read_bytes()
        (self.root / "pipeline-config.json").write_text("{}")
        self.assertIsNone(self.reserve())
        self.assertEqual(before, (self.root / "daily-quota.sqlite").read_bytes())

    def test_corruption_fails_before_http(self):
        (self.root / "daily-quota.sqlite").write_bytes(b"broken")
        calls = []
        with httpx.Client(
            transport=httpx.MockTransport(lambda r: calls.append(r))
        ) as client:
            with self.assertRaises(sqlite3.DatabaseError):
                capture_sample(client, "synthetic", {"api_name": "cyq_perf"}, self.root)
        self.assertEqual(calls, [])

    def test_guard_preserves_jobs_observed_gate_and_other_api_consumes(self):
        p = pmod.Pipeline(self.root, {"entries": []})
        self.addCleanup(p.close)
        jid = p.enqueue("cyq_perf", {"ts_code": "000001.SZ", "trade_date": "20260904"})
        p.enqueue("daily", {"trade_date": "20260904"})
        p.db.commit()
        calls = []

        def respond(request):
            calls.append(json.loads(request.content)["api_name"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": ["ts_code", "trade_date"], "items": []},
                },
            )

        original_reserve = quota.reserve
        with (
            patch.object(
                quota,
                "reserve",
                side_effect=lambda root, api: original_reserve(root, api, now=self.day),
            ),
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
        ):
            count = p.run(
                client,
                "synthetic",
                {**CONFIG, "priority_start": "20200101"},
                max_requests=1,
                max_seconds=2,
                pause=0,
            )
        self.assertEqual(calls, ["daily"])
        self.assertEqual(count["requests"], 1)
        row = p.db.execute(
            "SELECT state,tries,result FROM jobs WHERE id=?", (jid,)
        ).fetchone()
        self.assertEqual(tuple(row), ("pending", 0, None))
        self.assertIsNone(
            p.db.execute(
                "SELECT * FROM capability WHERE scope='quota:cyq_perf'"
            ).fetchone()
        )

    def test_account_observed_gate_and_fairness_not_bypassed(self):
        p = pmod.Pipeline(self.root, {"entries": []})
        self.addCleanup(p.close)
        p.enqueue("daily", {"trade_date": "20260904"})
        p.db.commit()
        p.db.execute(
            "INSERT INTO capability VALUES('quota:daily','rate_limit_observed','fixture',?)",
            (json.dumps({"interval_seconds": 60}),),
        )
        p.db.commit()
        now = time.time()
        row = p.next_job(CONFIG, time.monotonic() + 0.5)
        self.assertIsNotNone(row)
        gate = p.db.execute(
            "SELECT next_at FROM request_gates WHERE scope='api:daily'"
        ).fetchone()[0]
        self.assertGreaterEqual(gate, now + 60)
        self.assertEqual(p.rate_gate_status["effective_account_rpm"], 300)
        self.assertIsNone(p.next_job(CONFIG, time.monotonic() + 0.01))
        self.assertEqual(p._fair_turn, 1)

    def test_concurrent_last_reservation_and_transaction_rollback(self):
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace

        self.reserve()
        self.reserve(self.day + 86400)
        path = self.root / "daily-quota.sqlite"
        db = sqlite3.connect(path)
        db.execute("UPDATE daily_quota SET used=199999")
        db.commit()
        db.close()
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(
                pool.map(lambda _: self.reserve(self.day + 86400 + 1), range(8))
            )
        self.assertEqual(sum(r["reserved"] for r in rows), 1)
        connect = sqlite3.connect

        def broken(*args, **kwargs):
            db = connect(*args, **kwargs)
            return SimpleNamespace(
                execute=db.execute,
                commit=lambda: (_ for _ in ()).throw(OSError("commit fixture")),
                rollback=db.rollback,
                close=db.close,
            )

        with patch.object(quota.sqlite3, "connect", side_effect=broken):
            with self.assertRaises(OSError):
                self.reserve(self.day + 2 * 86400)
        self.assertEqual(self.reserve(self.day + 2 * 86400)["used"], 1)

    def test_rollout_activation_without_calls_does_not_delay_first_later_request(self):
        for delay in (86400, 21 * 86400):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "pipeline-config.json").write_text("{}")
                quota.activate(root, now=self.day)
                (root / "pipeline-config.json").write_text(json.dumps(CONFIG))
                self.assertTrue(
                    quota.reserve(root, "cyq_perf", now=self.day + delay)["reserved"]
                )
                old = quota.activate(root, now=self.day + delay)
                self.assertEqual(old["activation_day"], NOW.date().isoformat())
        # Recovery while config is still legacy must move the guard forward.
        (self.root / "pipeline-config.json").write_text("{}")
        quota.activate(self.root, now=self.day)
        updated = quota.activate(self.root, now=self.day + 86400)
        self.assertEqual(updated["activation_day"], "2026-09-10")
        (self.root / "pipeline-config.json").write_text(json.dumps(CONFIG))
        self.assertEqual(self.reserve(self.day + 86400)["reason"], "activation_guard")

    def test_status_no_write_or_zero_usage_claim_before_activation(self):
        self.assertEqual(
            quota.status(self.root, CONFIG, now=self.day)["status"], "not_initialized"
        )
        self.assertFalse((self.root / "daily-quota.sqlite").exists())
        self.reserve()
        summary = quota.status(self.root, CONFIG, now=self.day)
        self.assertEqual(summary["status"], "activation_guard")
        self.assertIsNone(summary["used"])
        self.reserve(self.day + 86400)
        summary = quota.status(self.root, CONFIG, now=self.day + 86400)
        self.assertEqual(summary["used"], 1)
        self.assertEqual(summary["remaining"], 199999)

    def test_quota_database_is_not_in_published_files(self):
        self.reserve()
        pipeline = pmod.Pipeline(self.root, {"entries": []})
        try:
            release = pipeline.publish()
        finally:
            pipeline.close()
        manifest = pmod.manifest_at(self.root, release)
        self.assertFalse(
            any("daily-quota.sqlite" in name for name in manifest["files"])
        )


class Rollout(unittest.TestCase):
    def setUp(self):
        import tushare_rate_rollout as rollout

        self.mod = rollout
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = {
            "requests_per_minute": 240,
            "enable_market_members": True,
            "history_start": "19900101",
            "group_weights": {"rrg": 3},
            "unrelated": [1, None],
        }
        self.original = (json.dumps(self.cfg, indent=4) + "\n").encode()
        (self.root / "pipeline-config.json").write_bytes(self.original)
        for name, value in [("authority", lambda: None), ("ROOT", self.root.resolve())]:
            guard = patch.object(rollout, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch("socket.socket.connect", side_effect=AssertionError("offline"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_dry_run_atomic_apply_idempotence_other_keys(self):
        m = self.mod
        r = m.rollout(self.root, 300)
        self.assertEqual(r["phase"], "dry_run")
        self.assertEqual(
            (self.root / "pipeline-config.json").read_bytes(), self.original
        )
        applied = m.rollout(self.root, 300, execute=True)
        self.assertEqual(applied["effective_account_rpm"], 300)
        self.assertEqual(applied["old_account_ceiling"], 240)
        new = json.loads((self.root / "pipeline-config.json").read_bytes())
        for key in self.cfg.keys() - m.KEYS:
            self.assertEqual(new[key], self.cfg[key])
        self.assertEqual(m.rollout(self.root, 300, execute=True), applied)
        self.assertEqual(
            (self.root / "validation/rate-rollout/300.before.json").read_bytes(),
            self.original,
        )

    def test_config_replace_success_receipt_failure_recovers(self):
        m = self.mod
        atomic = m.atomic_bytes

        def write(path, raw):
            if path.name.endswith("committed.json"):
                raise OSError("receipt fixture")
            atomic(path, raw)

        with patch.object(m, "atomic_bytes", side_effect=write):
            with self.assertRaises(OSError):
                m.rollout(self.root, 300, execute=True)
        self.assertEqual(
            json.loads((self.root / "pipeline-config.json").read_bytes())[
                "rollout_account_rpm"
            ],
            300,
        )
        result = m.rollout(self.root, 300, execute=True)
        self.assertEqual(result["phase"], "committed")
        self.assertTrue(result["recovered"])

    def test_failed_replace_preserves_old_and_no_outside_overwrite(self):
        m = self.mod
        with patch.object(m, "atomic_bytes", side_effect=OSError("replace fixture")):
            with self.assertRaises(OSError):
                m.rollout(self.root, 300, execute=True)
        self.assertEqual(
            (self.root / "pipeline-config.json").read_bytes(), self.original
        )
        changed = {**self.cfg, "concurrent": "keep"}
        (self.root / "pipeline-config.json").write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            m.rollout(self.root, 300, execute=True)
        self.assertEqual(
            json.loads((self.root / "pipeline-config.json").read_bytes()), changed
        )

    def test_400_500_require_matching_previous_stage_evidence(self):
        m = self.mod
        m.rollout(self.root, 300, execute=True)
        for stage in (400, 500):
            with self.assertRaises(ValueError):
                m.rollout(self.root, stage, execute=True)
            proof = {
                "status": "passed",
                "rollout_account_rpm": stage - 100,
                "config_sha256": m.sha(
                    (self.root / "pipeline-config.json").read_bytes()
                ),
            }
            path = self.root / f"accept{stage}.json"
            path.write_bytes(m.encode(proof))
            with self.assertRaises(ValueError):
                m.rollout(
                    self.root, stage, execute=True, evidence=path, evidence_sha="0" * 64
                )
            result = m.rollout(
                self.root,
                stage,
                execute=True,
                evidence=path,
                evidence_sha=m.sha(path.read_bytes()),
            )
            self.assertEqual(result["effective_account_rpm"], stage)

    def test_cli_defaults_dry_run_and_lock_conflict_cannot_mutate(self):
        import contextlib
        import fcntl
        import io

        output = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["tushare_rate_rollout.py", "--root", str(self.root)]
            ),
            contextlib.redirect_stdout(output),
        ):
            self.mod.main()
        self.assertEqual(json.loads(output.getvalue())["phase"], "dry_run")
        with (self.root / "pipeline.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.mod.rollout(self.root, 300, execute=True)
        self.assertEqual(
            (self.root / "pipeline-config.json").read_bytes(), self.original
        )

    def test_points_all_tranches_and_notice_windows(self):
        for stamp, points in [
            ("2026-12-04", 10100),
            ("2026-12-05", 8100),
            ("2027-09-07", 8100),
            ("2027-09-08", 100),
        ]:
            now = datetime.fromisoformat(stamp).replace(tzinfo=NOW.tzinfo)
            self.assertEqual(
                policy.entitlement(CONFIG, now)["effective_points_conservative"], points
            )
        for stamp, window in [
            ("2026-09-09", 90),
            ("2026-11-05", 30),
            ("2026-11-28", 7),
            ("2026-12-05", 0),
        ]:
            notices = policy.entitlement(
                CONFIG, datetime.fromisoformat(stamp).replace(tzinfo=NOW.tzinfo)
            )["notices"]
            self.assertEqual(
                next(n for n in notices if n["points"] == 2000)["window_days"], window
            )
        self.assertEqual(
            policy.cyq_daily_limit(CONFIG, datetime(2027, 9, 8, tzinfo=NOW.tzinfo)), 0
        )


if __name__ == "__main__":
    unittest.main()
