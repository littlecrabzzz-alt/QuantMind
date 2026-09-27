import unittest
from unittest.mock import patch
from backend.services.research_agent import continuous_state as st
from backend.services.research_agent.glm_quota import (
    normalize_quota,
    quota_decision,
    failure_kind,
    retry_delay,
    fetch_quota,
)


def quota(used=8, now=1000):
    return normalize_quota(
        {
            "code": 200,
            "data": {
                "level": "max",
                "limits": [
                    {"type": "TIME_LIMIT", "unit": 5, "percentage": 1},
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 3,
                        "number": 5,
                        "percentage": used,
                        "nextResetTime": 2000000,
                    },
                ],
            },
        },
        now,
    )


class QuotaTests(unittest.TestCase):
    def test_real_vendor_shape_no_invented_week(self):
        q = quota()
        self.assertEqual(q["remaining_percent"], 92)
        self.assertIsNone(q["weekly"])
        self.assertEqual(q["tools"]["remaining_percent"], 99)

    def test_missing_ambiguous_not_zero(self):
        for limits in (
            [],
            [{"type": "TIME_LIMIT", "percentage": 0}],
            [{"type": "TOKENS_LIMIT", "percentage": 0}] * 2,
        ):
            q = normalize_quota({"data": {"limits": limits}}, 1000)
            self.assertEqual(q["status"], "unknown")
            self.assertIsNone(q["remaining_percent"])

    def test_invalid_percentage(self):
        for v in (-1, 101, None, float("nan"), True):
            self.assertEqual(quota(v)["status"], "unknown")

    def test_freshness_and_reserve(self):
        self.assertEqual(quota_decision(quota(), 1181)[0], "quota_unknown")
        self.assertEqual(quota_decision(quota(99), 1000)[0], "waiting_quota")
        self.assertEqual(quota_decision(quota(), 1000)[0], "available")

    def test_classifier(self):
        for msg, kind in [
            ("1308 已达到5小时使用上限", "waiting_quota"),
            ("1310 weekly limit", "waiting_quota"),
            ("429 rate limit", "retrying"),
            ("503 overloaded", "retrying"),
            ("stream_read_error", "retrying"),
            ("401 invalid key", "auth_error"),
            ("syntax error", "failed"),
        ]:
            self.assertEqual(failure_kind(msg), kind)

    def test_retry_after(self):
        self.assertEqual(retry_delay(3, 123), 123)
        self.assertEqual(retry_delay(100), 900)

    def test_errors_do_not_leak(self):
        class Session:
            def get(self, *a, **kw):
                raise RuntimeError("a-secret-api-key")

        self.assertNotIn("a-secret", str(fetch_quota("a-secret-api-key", Session())))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.c = st.initial({"concurrency": 3})
        st.control(self.c, "start")
        st.quota_update(self.c, quota(), 1000)

    def test_quota_exhaust_restore_continues_same_task(self):
        t = st.claim(self.c, "worker", 1000)
        ident = t["id"]
        lease = t["lease"]
        t["pending_action"] = {"action": "experiment", "name": "intent-before-crash"}
        st.settle(self.c, ident, lease, "waiting_quota", now=1001)
        self.assertIsNone(st.claim(self.c, "worker", 1020))
        st.quota_update(self.c, quota(100, 1070), 1070)
        self.assertIsNone(st.claim(self.c, "worker", 1070))
        st.quota_update(self.c, quota(0, 1100), 1100)
        resumed = st.claim(self.c, "worker", 1100)
        self.assertEqual(resumed["id"], ident)
        self.assertNotEqual(resumed["lease"], lease)
        self.assertEqual(resumed["pending_action"]["name"], "intent-before-crash")
        with self.assertRaises(ValueError):
            st.fence(self.c, ident, lease, 1100)

    def test_fresh_but_unchanged_positive_quota_does_not_clear_denial(self):
        t = st.claim(self.c, "worker", 1000)
        st.settle(self.c, t["id"], t["lease"], "waiting_quota", now=1001)
        st.quota_update(self.c, quota(8, 1100), 1100)
        self.assertIsNone(st.claim(self.c, "worker", 1100))

    def test_unknown_prevents_dispatch(self):
        st.quota_update(self.c, {"status": "unknown", "observed_at": 1001}, 1001)
        self.assertIsNone(st.claim(self.c, "worker", 1001))

    def test_stop_idempotent_and_fenced(self):
        t = st.claim(self.c, "worker", 1000)
        st.control(self.c, "stop")
        g = self.c["generation"]
        st.control(self.c, "stop")
        self.assertEqual(g, self.c["generation"])
        with self.assertRaises(ValueError):
            st.fence(self.c, t["id"], t["lease"], 1001)
        self.assertEqual(
            st.settle(self.c, t["id"], t["lease"], "done", now=1002), "cancelled"
        )
        st.control(self.c, "start")
        self.assertEqual(t["status"], "queued")

    def test_crash_recovery_preserves_receipt(self):
        t = st.claim(self.c, "worker", 1000)
        t["tool_receipts"]["x"] = {"backtest_id": "original"}
        st.recover(self.c, 1121)
        st.quota_update(self.c, quota(0, 1121), 1121)
        resumed = st.claim(self.c, "new-worker", 1121)
        self.assertEqual(resumed["id"], t["id"])
        self.assertEqual(resumed["tool_receipts"]["x"]["backtest_id"], "original")

    def test_quota_does_not_consume_network_retry_budget(self):
        for i in range(10):
            now = 1000 + i * 100
            st.quota_update(self.c, quota(100, now - 1), now - 1)
            st.quota_update(self.c, quota(0, now), now)
            t = st.claim(self.c, "worker", now)
            st.settle(self.c, t["id"], t["lease"], "waiting_quota", now=now + 1)
        self.assertEqual(t.get("transient_errors", 0), 0)

    def test_done_requires_report(self):
        t = st.claim(self.c, "worker", 1000)
        self.assertEqual(
            st.settle(self.c, t["id"], t["lease"], "done", now=1001), "blocked"
        )

    def test_compute_wait_is_not_completion_or_new_progress(self):
        for _ in range(3):
            t = st.claim(self.c, "worker", 1000)
            self.assertIsNone(t["last_activity"])
            st.settle(self.c, t["id"], t["lease"], "waiting_compute", now=1000)
        self.assertIsNone(st.claim(self.c, "worker", 1001))
        self.assertEqual(self.c["status"], "waiting_compute")

    def test_duplicates_and_queue_cap(self):
        a = st.add_task(self.c, "trend", "new", "evidence")
        b = st.add_task(self.c, "trend", "new", "evidence")
        self.assertEqual(a, b)
        for i in range(16):
            st.add_task(self.c, "trend", str(i), "evidence")
        with self.assertRaises(ValueError):
            st.add_task(self.c, "trend", "overflow", "evidence")


if __name__ == "__main__":
    unittest.main()
