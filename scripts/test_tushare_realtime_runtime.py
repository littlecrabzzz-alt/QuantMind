"""Offline realtime8/replay2 capture, immutable reads and dispatch expiry."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import (
    REALTIME_RUNTIME_CONTRACTS as CONTRACTS,
    PLANNERS,
    realtime_identifiers,
)
from backend.shared.tushare_store import read_dataset, dataset_schema
import test_tushare_technical_extra_pipeline as fixtures


CODES = {
    api: "cu2609.SHF"
    if "fut" in api
    else "159001.SZ"
    if "etf" in api
    else "801005.SI"
    if api == "rt_sw_k"
    else "T600001.SH"
    if api in ("rt_k", "stk_auction")
    else "000001.SH"
    for api in CONTRACTS
}


def params(api, freq="1MIN"):
    if api == "stk_auction":
        return {"trade_date": "20260904"}
    if api == "rt_etf_sz_iopv" or api == "rt_sw_k":
        return {}
    return {"ts_code": CODES[api], **({"freq": freq} if "min" in api else {})}


def source(api, **changes):
    spec = CONTRACTS[api]
    result = {
        f: "synthetic-label" if m["type"] == "str" else 1.25
        for f, m in spec["field_metadata"].items()
    }
    result.update(
        {
            spec["source_code_field"]: CODES[api],
            spec["date_field"]: "20260904"
            if api == "stk_auction"
            else "2026-09-04 10:00:01",
            "unknown_source_column": None,
        }
    )
    if "freq" in result:
        result["freq"] = "1MIN"
    result.update(changes)
    return result


class RealtimeRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    capture = fixtures.TechnicalExtraRuntime.capture
    discovery = fixtures.TechnicalExtraRuntime.discovery

    def test_ten_apis_full105_fields_raw_roundtrip_and_namespaces(self):
        self.assertEqual(sum(len(s["fields"]) for s in CONTRACTS.values()), 105)
        expected_codes = {}
        for api in CONTRACTS:
            row = source(api)
            self.assertEqual(
                self.capture(api, params(api), [row])[2]["status"], "sample_ok"
            )
            expected_codes[api] = (
                "FUT:" + CODES[api]
                if "fut" in api
                else "FUND:" + CODES[api]
                if "etf" in api
                else "SHT600001"
                if api == "rt_k"
                else "AUCTION_UNTYPED:" + CODES[api]
                if api == "stk_auction"
                else "IDX:" + CODES[api]
            )
        fixed = self.p.publish()
        for api, spec in CONTRACTS.items():
            rows = read_dataset(self.root, fixed, api).to_pylist()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row[spec["source_code_field"]], expected_codes[api])
            self.assertEqual(row["ts_code"], expected_codes[api])
            for field, value in source(api).items():
                self.assertEqual(
                    row[
                        "source_" + field
                        if field == spec["source_code_field"]
                        else field
                    ],
                    value,
                )
            if "fut" in api:
                self.assertEqual(row["source_code"], row["source_ts_code"])
            if spec["request_identity_fields"]:
                self.assertEqual(row["_request_identity_status"], "complete")
            meta = dataset_schema(self.root, fixed, api)
            self.assertEqual(meta["default_date_field"], spec["date_field"])
            self.assertEqual(meta["permission_status"], "unprobed")
            self.assertEqual(
                read_dataset(
                    self.root, fixed, api, codes=[expected_codes[api]]
                ).num_rows,
                1,
            )
            if api != "stk_auction":
                self.assertEqual(
                    read_dataset(
                        self.root,
                        fixed,
                        api,
                        start_date="2026-09-04 10:00:01",
                        end_date="2026-09-04 10:00:01",
                    ).num_rows,
                    1,
                )
                self.assertEqual(
                    read_dataset(
                        self.root, fixed, api, start_date="2026-09-04 10:00:02"
                    ).num_rows,
                    0,
                )

    def test_five_freq_optional_dimensions_and_mixed_auction_never_collapse(self):
        for api in ("rt_idx_min", "rt_idx_min_daily", "rt_fut_min", "rt_fut_min_daily"):
            for freq in ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN"):
                self.capture(
                    api,
                    params(api, freq),
                    [source(api, **({"freq": freq} if "fut" in api else {}))],
                    epoch=freq,
                )
        for kind in (None, "STK", "ETF"):
            self.capture(
                "stk_auction",
                {**params("stk_auction"), **({"ts_type": kind} if kind else {})},
                [source("stk_auction", ts_code="123039.SZ")],
                epoch=str(kind),
            )
        self.capture(
            "rt_fut_min_daily",
            {**params("rt_fut_min_daily"), "date_str": "2026-09-03"},
            [source("rt_fut_min_daily")],
            epoch="prior",
        )
        fixed = self.p.publish()
        for api in ("rt_idx_min", "rt_idx_min_daily", "rt_fut_min", "rt_fut_min_daily"):
            rows = read_dataset(self.root, fixed, api).to_pylist()
            self.assertEqual(len(rows), 6 if api == "rt_fut_min_daily" else 5)
            self.assertEqual(
                {json.loads(r["_request_identity"])["freq"] for r in rows},
                {"1MIN", "5MIN", "15MIN", "30MIN", "60MIN"},
            )
        rows = read_dataset(self.root, fixed, "stk_auction").to_pylist()
        self.assertEqual(
            {r["ts_code"] for r in rows},
            {"AUCTION_UNTYPED:123039.SZ", "SZ123039", "FUND:123039.SZ"},
        )
        discovery = self.p.identifiers()
        self.assertEqual(discovery["realtime_auction_untyped"], ["123039.SZ"])
        self.assertEqual(discovery["stocks"], [])
        self.assertEqual(discovery["realtime_futures"], ["cu2609.SHF"])
        self.assertIn("cu2609.SHF", realtime_identifiers(discovery)["minute_futures"])

    def test_source_frequency_mismatch_keeps_raw_without_false_projection(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.capture(
                "rt_fut_min", params("rt_fut_min", "5MIN"), [source("rt_fut_min")]
            )
        self.assertEqual(len(list((self.root / "objects").glob("*.json"))), 1)
        self.assertEqual(len(list((self.root / "parquet").glob("*.parquet"))), 0)

    def test_required_identity_missing_still_blocks_reader(self):
        self.capture(
            "rt_idx_min_daily",
            {"ts_code": CODES["rt_idx_min_daily"]},
            [source("rt_idx_min_daily")],
        )
        fixed = self.p.publish()
        with self.assertRaisesRegex(ValueError, "missing request fields freq"):
            read_dataset(self.root, fixed, "rt_idx_min_daily")

    def test_default_off_and_explicit_epoch_policy_auction_history_separate(self):
        before = module._planning_inputs(
            "structured", {"history_start": "20260901"}, {}
        )
        self.assertEqual(list(PLANNERS["realtime_extra"]({}, date(2026, 9, 9), {})), [])
        cfg = {
            "enable_realtime_extra": True,
            "realtime_extra_apis": ["rt_idx_min"],
            "enable_realtime_auction": True,
            "realtime_extra_snapshot_epoch": "20260909T080000Z",
            "realtime_auction_history_start": "20260801",
            "realtime_extra_frequencies": ["1MIN"],
            "history_start": "20260901",
        }
        ids = {"indexes": ["000001.SH"]}
        jobs = list(PLANNERS["realtime_extra"](cfg, date(2026, 9, 9), ids)) + list(
            PLANNERS["realtime_auction"](cfg, date(2026, 9, 9), ids)
        )
        self.assertTrue(
            any(
                j["epoch"] == "history" and j["api_name"] == "stk_auction" for j in jobs
            )
        )
        self.assertTrue(
            any(
                j["epoch"].startswith("snapshot-") and j["api_name"] == "rt_idx_min"
                for j in jobs
            )
        )
        self.assertTrue(
            all(
                j["api_name"] == "stk_auction"
                for j in PLANNERS["realtime_extra"](cfg, date(2026, 9, 10), ids)
            )
        )
        auction_policy = module._planning_inputs("realtime_auction", cfg, ids)[0]
        self.assertEqual(
            auction_policy,
            module._planning_inputs(
                "realtime_auction",
                {**cfg, "realtime_extra_snapshot_epoch": "20260909T090000Z"},
                ids,
            )[0],
        )
        policy = module._planning_inputs("realtime_extra", cfg, ids)[0]
        self.assertNotEqual(
            policy,
            module._planning_inputs(
                "realtime_extra",
                {**cfg, "realtime_extra_snapshot_epoch": "20260909T090000Z"},
                ids,
            )[0],
        )
        self.assertEqual(before, module._planning_inputs("structured", cfg, {}))
        self.assertEqual(self.p.plan_extended({}, date(2026, 9, 9)), {})

    def test_dispatch_all_nine_reject_old_future_invalid_with_zero_http(self):
        config = {"enable_realtime_extra": True, "enable_realtime_replay": True}
        midnight = datetime(2026, 9, 9, 16, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(
            module.realtime_dispatch_status(
                "rt_idx_k", "snapshot-20260909T155959Z", config, midnight
            ),
            "snapshot_expired",
        )
        self.assertIsNone(
            module.realtime_dispatch_status(
                "rt_idx_k", "snapshot-20260909T160000Z", config, midnight
            )
        )
        self.assertEqual(
            module.realtime_dispatch_status(
                "rt_idx_k", "snapshot-20260909T160000Z", {}, midnight
            ),
            "snapshot_disabled",
        )
        oldids = []
        for api in CONTRACTS:
            if api == "stk_auction":
                continue
            for epoch in (
                "snapshot-20260908T080000Z",
                "snapshot-20260910T080000Z",
                "snapshot-20260909T083001Z",
                "history",
                "snapshot-20260230T080000Z",
            ):
                oldids.append(self.p.enqueue(api, params(api), epoch=epoch))
        self.p.db.commit()
        now = datetime(2026, 9, 9, 8, 30, tzinfo=timezone.utc).timestamp()
        with (
            patch.object(module.time, "time", return_value=now),
            patch.object(
                module, "capture_sample", side_effect=AssertionError("must not call")
            ),
        ):
            result = self.p.run(
                None, "fixture", config, max_requests=1, max_seconds=2, pause=0
            )
        self.assertEqual(result["requests"], 0)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 0
        )
        self.assertEqual(
            {r[0] for r in self.p.db.execute("SELECT state FROM jobs")},
            {"snapshot_expired", "snapshot_future_epoch", "snapshot_invalid_epoch"},
        )
        for api in CONTRACTS:
            if api == "stk_auction":
                continue
            new_id = self.p.enqueue(api, params(api), epoch="snapshot-20260909T080000Z")
            self.assertNotIn(new_id, oldids)
        self.p.db.commit()
        with (
            patch.object(module.time, "time", return_value=now),
            patch.object(
                module,
                "capture_sample",
                side_effect=lambda client, token, job, root: {
                    "api_name": job["api_name"],
                    "status": "empty_unverified",
                    "row_count": 0,
                },
            ) as capture,
        ):
            result = self.p.run(
                None, "fixture", config, max_requests=9, max_seconds=2, pause=0
            )
        self.assertEqual(result["requests"], 9)
        self.assertEqual(capture.call_count, 9)

    def test_auction_history_cursor_survives_snapshot_slot_changes(self):
        cfg = {
            "enable_realtime_auction": True,
            "enable_realtime_extra": True,
            "realtime_extra_apis": ["rt_idx_min"],
            "realtime_extra_frequencies": ["1MIN"],
            "realtime_auction_history_start": "20250101",
            "plan_jobs_per_tick": 1,
            "realtime_extra_snapshot_epoch": "20260909T080000Z",
        }
        with patch.object(
            self.p, "identifiers", return_value={"indexes": ["000001.SH"]}
        ):
            self.p.plan_extended(cfg, date(2026, 9, 9))
            first = dict(
                self.p.db.execute(
                    "SELECT * FROM planning_state WHERE name='history:realtime_auction'"
                ).fetchone()
            )
            self.p.plan_extended(
                {**cfg, "realtime_extra_snapshot_epoch": "20260909T090000Z"},
                date(2026, 9, 9),
            )
            second = dict(
                self.p.db.execute(
                    "SELECT * FROM planning_state WHERE name='history:realtime_auction'"
                ).fetchone()
            )
        self.assertFalse(first["done"])
        self.assertGreater(second["offset"], first["offset"])
        self.assertEqual(first["signature"], second["signature"])

    def test_unknown_timestamp_has_unfiltered_source_but_no_guessed_filter(self):
        self.capture(
            "rt_idx_k", params("rt_idx_k"), [source("rt_idx_k", trade_time="10:00:01")]
        )
        fixed = self.p.publish()
        self.assertEqual(read_dataset(self.root, fixed, "rt_idx_k").num_rows, 1)
        with self.assertRaisesRegex(ValueError, "realtime_timestamp_unverified"):
            read_dataset(self.root, fixed, "rt_idx_k", start_date="20260904")

    def test_auction_and_old_family_dispatch_job_bytes_unchanged(self):
        config = {"enable_realtime_extra": True}
        now = datetime(2026, 9, 9, 8, 30, tzinfo=timezone.utc).timestamp()
        snapshots = []
        for use_guard in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                p = module.Pipeline(Path(tmp), fixtures.fixtures.CATALOG)
                try:
                    for api, param in (
                        ("daily", {"trade_date": "20260904"}),
                        ("stk_auction", params("stk_auction")),
                    ):
                        p.enqueue(api, param, epoch="history")
                    p.db.commit()
                    real_guard = module.realtime_dispatch_status
                    with (
                        patch.object(module.time, "time", return_value=now),
                        patch.object(
                            module,
                            "realtime_dispatch_status",
                            side_effect=real_guard if use_guard else lambda *a: None,
                        ),
                        patch.object(
                            module,
                            "capture_sample",
                            side_effect=lambda c, t, job, r: {
                                "api_name": job["api_name"],
                                "status": "empty_unverified",
                                "row_count": 0,
                            },
                        ) as captured,
                    ):
                        self.assertEqual(
                            p.run(
                                None,
                                "fixture",
                                config,
                                max_requests=2,
                                max_seconds=2,
                                pause=0,
                            )["requests"],
                            2,
                        )
                    snapshots.append(
                        (
                            json.dumps(
                                [
                                    dict(r)
                                    for r in p.db.execute(
                                        "SELECT * FROM jobs ORDER BY id"
                                    )
                                ],
                                sort_keys=True,
                            ),
                            [c.args[2] for c in captured.call_args_list],
                        )
                    )
                finally:
                    p.close()
        self.assertEqual(snapshots[0], snapshots[1])


if __name__ == "__main__":
    unittest.main()
