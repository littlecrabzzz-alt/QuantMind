# ruff: noqa: E402
"""Synthetic files only; never opens Pipeline, SQLite or provider connections."""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load("rtprobe", str(REPO / "scripts/tushare_realtime_probe.py"))
verify = load("rtverify", str(REPO / "scripts/verify_tushare_realtime_fixed.py"))
from backend.shared.tushare_intake import json_bytes
from backend.shared.tushare_registry import (
    REALTIME_RUNTIME_CONTRACTS,
    project_realtime_row,
)
import pyarrow as pa
import pyarrow.parquet as pq


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="realtime10-isolated-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "fixed"
        self.root.mkdir()
        self.files = {}
        self.parts = []
        self.number = 0
        for obj, attr in ((socket.socket, "connect"), (socket, "getaddrinfo")):
            guard = patch.object(obj, attr, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)
        for name in (
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
            "sqlite3.connect",
            "backend.shared.tushare_pipeline.Pipeline",
        ):
            guard = patch(name, side_effect=AssertionError("No credentials or DB"))
            guard.start()
            self.addCleanup(guard.stop)

    def put(self, name, body):
        path = self.root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        self.files[name] = {"sha256": verify.digest(body), "bytes": len(body)}

    def observed(self, api, params, rows):
        fields = list(rows[0])
        body = json_bytes(
            {
                "code": 0,
                "data": {
                    "fields": fields,
                    "items": [[r[k] for k in fields] for r in rows],
                },
            }
        )
        sha = verify.digest(body)
        self.put("objects/" + sha + ".json", body)
        self.number += 1
        name = f"{self.number:032x}.json"
        obs = {
            "request": {"api_name": api, "params": params, "fields": ",".join(fields)},
            "object_sha256": sha,
            "requested_at": "2026-09-09T08:00:00+00:00",
            "fetched_at": "2026-09-09T08:00:00+00:00",
        }
        data = json_bytes(obs)
        self.put("observations/" + name, data)
        return name, sha, verify.digest(data)

    def release(self):
        manifest = {
            "files": self.files,
            "datasets": self.parts,
            "coverage_by_api": [],
            "history_complete": False,
            "historical_versions_complete": True,
        }
        payload = json_bytes(manifest)
        rid = "data-" + verify.digest(payload)
        path = self.root / "releases" / rid
        path.mkdir(parents=True, exist_ok=True)
        (path / "manifest.json").write_bytes(payload)
        return rid

    def seeds(self):
        today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
        recent = (today - timedelta(days=1)).strftime("%Y%m%d")
        old = (today - timedelta(days=20)).strftime("%Y%m%d")
        records = {
            "stock": ("stock_basic", {"list_status": "L"}, {"ts_code": "600000.SH"}),
            "etf": ("etf_basic", {}, {"ts_code": "159001.SZ"}),
            "index": ("index_basic", {}, {"ts_code": "000001.SH"}),
            "sw": ("index_classify", {}, {"index_code": "801001.SI"}),
            "future": (
                "fut_basic",
                {},
                {
                    "ts_code": "CU2610.SHF",
                    "list_date": "20250101",
                    "delist_date": "20271001",
                },
            ),
        }
        sources = {}
        for kind, (api, params, row) in records.items():
            obs, _, _ = self.observed(api, params, [row])
            sources[kind] = {
                "observation": obs,
                "value": row.get("ts_code", row.get("index_code")),
            }
        cal, _, _ = self.observed(
            "trade_cal",
            {"exchange": "SSE"},
            [{"cal_date": d, "is_open": 1} for d in (recent, old)],
        )
        recipe = {
            "release_id": self.release(),
            "sources": sources,
            "calendar": {
                "observation": cal,
                "recent": recent,
                "history_start": old,
                "history_end": old,
            },
        }
        path = Path(self.temp.name) / "seeds.json"
        path.write_bytes(json_bytes(recipe))
        return path, verify.digest(path.read_bytes())

    def generated(self, mutation=None):
        seeds, sha = self.seeds()
        planned, _ = probe.seed_requests(self.root, seeds, sha)
        slot = "20260909T080000Z"
        results = []
        for api, params in planned:
            spec = REALTIME_RUNTIME_CONTRACTS[api]
            row = dict.fromkeys(spec["fields"], 1.5)
            row[spec["source_code_field"]] = params["ts_code"]
            row[spec["date_field"]] = (
                params.get("trade_date", params.get("start_date"))
                if api == "stk_auction"
                else "2026-09-09 16:00:00"
            )
            if "freq" in row:
                row["freq"] = "1MIN"
            if "name" in row:
                row["name"] = "synthetic"
            row["supplier_future_null"] = None
            if mutation:
                mutation("raw", api, row)
            obs, objsha, obssha = self.observed(api, params, [row])
            record = {
                "api_name": api,
                "params": params,
                "status": "sample_ok",
                "row_count": 1,
                "observation": obs,
                "object_sha256": objsha,
                "observation_sha256": obssha,
            }
            if mutation:
                mutation("report", api, record)
            results.append(record)
            stored = project_realtime_row(api, dict(row), params)
            rawidentity = verify.digest(json_bytes(row))
            stored["_row_identity"] = rawidentity
            if spec["request_identity_fields"]:
                identity = {k: params.get(k) for k in spec["request_identity_fields"]}
                identity_json = json_bytes(identity).decode()
                stored.update(
                    _raw_row_identity=rawidentity,
                    _request_identity=identity_json,
                    _request_identity_status="complete",
                    _request_identity_missing="[]",
                )
                stored["_row_identity"] = verify.digest(
                    (rawidentity + "\n" + identity_json).encode()
                )
            stored.update(
                _fetched_at="2026-09-09T08:00:00+00:00",
                _observation=obs,
                _source="",
                _api_name=api,
            )
            if mutation:
                mutation("parquet", api, stored)
            stream = pa.BufferOutputStream()
            pq.write_table(pa.Table.from_pylist([stored]), stream)
            body = stream.getvalue().to_pybytes()
            name = "parquet/" + verify.digest(body) + ".parquet"
            self.put(name, body)
            self.parts.append({"api_name": api, "path": name, **self.files[name]})
        report = {
            "snapshot_slot": slot,
            "planned_requests": [{"api_name": a, "params": p} for a, p in planned],
            "results": results,
            "actual_upstream_calls": 15,
            "replay_scope": "current_only",
            "frequencies_tested": ["1MIN"],
        }
        path = Path(self.temp.name) / "probe.json"
        path.write_bytes(json_bytes(report))
        return argparse.Namespace(
            root=self.root,
            report=path,
            release_id=self.release(),
            max_rows=100000,
            max_partitions=200,
        )

    def test_plan_all_variants_single_source_current_only(self):
        path, sha = self.seeds()
        planned, _ = probe.seed_requests(self.root, path, sha)
        self.assertEqual(
            Counter(a for a, p in planned),
            Counter({a: 6 if a == "stk_auction" else 1 for a in probe.APIS}),
        )
        self.assertTrue(all("ts_code" in p for a, p in planned))
        self.assertTrue(
            all(set(p) <= {"ts_code", "freq"} for a, p in planned if a != "stk_auction")
        )
        self.assertEqual({p["freq"] for a, p in planned if "freq" in p}, {"1MIN"})
        for a, p in planned:
            probe.validate_request(a, p)
        with self.assertRaises(ValueError):
            probe.validate_request(
                "rt_fut_min_daily",
                {"ts_code": "CU2610.SHF", "freq": "1MIN", "date_str": "2026-09-08"},
            )

    def test_seed_hash_and_actual_code_are_required(self):
        path, sha = self.seeds()
        with self.assertRaises(ValueError):
            probe.seed_requests(self.root, path, "0" * 64)
        recipe = json.loads(path.read_bytes())
        recipe["sources"]["stock"]["value"] = "600001.SH"
        path.write_bytes(json_bytes(recipe))
        with self.assertRaisesRegex(ValueError, "not present"):
            probe.seed_requests(self.root, path, verify.digest(path.read_bytes()))

    def test_unknown_calendar_and_expired_contract_rejected(self):
        path, sha = self.seeds()
        recipe = json.loads(path.read_bytes())
        recipe["calendar"]["history_start"] = "20250101"
        path.write_bytes(json_bytes(recipe))
        with self.assertRaisesRegex(ValueError, "calendar"):
            probe.seed_requests(self.root, path, verify.digest(path.read_bytes()))

    def test_mandatory_parent_guard_behavior(self):
        probe.runtime_guard_preflight()
        with patch(
            "backend.shared.tushare_registry.realtime_dispatch_status",
            return_value=None,
        ):
            with self.assertRaisesRegex(ValueError, "2abcd7f"):
                probe.runtime_guard_preflight()

    def test_full_fixed_raw_parquet_query_and_mac_equivalence(self):
        args = self.generated()
        first = verify.audit(args)
        second = verify.audit(args)
        self.assertEqual(first["gaps"], [])
        self.assertEqual(first["equivalence_sha256"], second["equivalence_sha256"])
        self.assertEqual(set(first["sample_passed_api_candidates"]), set(probe.APIS))
        self.assertEqual(
            sum(d["raw_probe_rows_verified"] for d in first["dataset_checks"]), 15
        )
        self.assertEqual(first["official_field_count"], 105)
        self.assertFalse(first["automatic_activation_permitted"])
        self.assertEqual(first["upstream_calls"], 0)

    def test_missing_unknown_null_column_fails(self):
        def mutate(stage, api, row):
            if stage == "parquet" and api == "rt_k":
                row.pop("supplier_future_null")

        with self.assertRaisesRegex(ValueError, "scalar"):
            verify.audit(self.generated(mutate))

    def test_raw_hash_tamper_fails(self):
        args = self.generated()
        name = next(
            n
            for n in self.files
            if n.startswith("objects/")
            and n
            in json.loads(
                (
                    self.root / "releases" / args.release_id / "manifest.json"
                ).read_bytes()
            )["files"]
        )
        # Tamper a selected probe source, not seed-only evidence.
        sample = json.loads(args.report.read_bytes())["results"][0]
        name = "objects/" + sample["object_sha256"] + ".json"
        (self.root / name).write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "SHA"):
            verify.audit(args)

    def test_source_date_mismatch_blocks_exact_api(self):
        def mutate(stage, api, row):
            if stage == "raw" and api == "rt_k":
                row["trade_time"] = "2026-09-08 16:00:00"

        report = verify.audit(self.generated(mutate))
        self.assertNotIn("rt_k", report["sample_passed_api_candidates"])
        self.assertIn(
            "source_filter_or_time_mismatch", {g["kind"] for g in report["gaps"]}
        )

    def test_permission_result_is_not_success(self):
        def mutate(stage, api, row):
            if stage == "report" and api == "rt_k":
                row["status"] = "permission_denied"

        report = verify.audit(self.generated(mutate))
        self.assertNotIn("rt_k", report["sample_passed_api_candidates"])

    def test_no_silent_fixed_row_truncation(self):
        args = self.generated()
        args.max_rows = 14
        with self.assertRaisesRegex(ValueError, "bound"):
            verify.audit(args)

    def test_plan_only_no_slot_no_pipeline(self):
        path, sha = self.seeds()
        report = Path(self.temp.name) / "never-created.json"
        argv = [
            "probe",
            "--repo",
            str(REPO),
            "--root",
            str(self.root),
            "--seeds",
            str(path),
            "--seeds-sha256",
            sha,
            "--report",
            str(report),
        ]
        with patch.object(sys, "argv", argv), patch("builtins.print") as emit:
            probe.main()
        result = json.loads(emit.call_args.args[0])
        self.assertIsNone(result["snapshot_slot"])
        self.assertFalse(report.exists())

    def test_raw_multiplicity_and_saturation_stay_blocked(self):
        args = self.generated()
        # A complete part cannot add an identical raw row silently.
        part = self.parts[0]
        rows = pq.read_table(self.root / part["path"]).to_pylist()
        stream = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows + rows), stream)
        body = stream.getvalue().to_pybytes()
        name = "parquet/" + verify.digest(body) + ".parquet"
        self.put(name, body)
        self.parts[0] = {"api_name": part["api_name"], "path": name, **self.files[name]}
        args.release_id = self.release()
        with self.assertRaisesRegex(ValueError, "multiplicity"):
            verify.audit(args)

    def test_saturation_and_empty_outcomes_do_not_activate(self):
        args = self.generated()
        contracts = dict(REALTIME_RUNTIME_CONTRACTS)
        contracts["rt_k"] = {**contracts["rt_k"], "row_cap": 1}
        with patch(
            "backend.shared.tushare_registry.REALTIME_RUNTIME_CONTRACTS", contracts
        ):
            report = verify.audit(args)
        self.assertIn("saturation_unresolved", {g["kind"] for g in report["gaps"]})
        self.assertNotIn("rt_k", report["sample_passed_api_candidates"])

    def test_report_cannot_sneak_prior_replay_or_different_frequency(self):
        args = self.generated()
        report = json.loads(args.report.read_bytes())
        report["planned_requests"][-1]["params"]["date_str"] = "2026-09-08"
        args.report.write_bytes(json_bytes(report))
        with self.assertRaisesRegex(ValueError, "Current-only"):
            verify.audit(args)


class MemoryCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class MemoryDB:
    """Tiny assertion double; no SQLite file and no production state."""

    def __init__(self):
        self.gates = {}
        self.states = {}
        self.committed = []
        self.denied = set()
        self.quotas = {}

    def execute(self, sql, args=()):
        if sql.startswith("SELECT 1 FROM capability"):
            return MemoryCursor((1,) if args[0] in self.denied else None)
        if sql.startswith("SELECT MAX(next_at)"):
            return MemoryCursor((max((self.gates.get(k, 0) for k in args), default=0),))
        if sql.startswith("SELECT reason"):
            return MemoryCursor(
                (json.dumps(self.quotas[args[0]]),) if args[0] in self.quotas else None
            )
        if sql.startswith("UPDATE jobs SET state='probe_inflight'"):
            self.states[args[0]] = "probe_inflight"
        elif sql.startswith("UPDATE jobs SET state='probe_prepared'"):
            self.states[args[0]] = "probe_prepared"
        elif sql.startswith("UPDATE jobs SET state=?"):
            self.states[args[2]] = args[0]
        elif sql.startswith("INSERT INTO request_gates"):
            self.gates[args[0]] = max(self.gates.get(args[0], 0), args[1])
        return MemoryCursor()

    def executemany(self, sql, args):
        for row in args:
            self.execute(sql, row)

    def commit(self):
        self.committed.append(dict(self.states))


class Executor(unittest.TestCase):
    setUp = Fixtures.setUp
    put = Fixtures.put
    observed = Fixtures.observed
    release = Fixtures.release
    seeds = Fixtures.seeds

    def execute_mocked(
        self,
        status="sample_ok",
        exception=False,
        seconds=120,
        config=None,
        local_quota=False,
    ):
        path, sha = self.seeds()
        planned, _ = probe.seed_requests(self.root, path, sha)
        config = config or {"rate_policy": "tiered_v1", "requests_per_minute": 500}
        db = MemoryDB()
        rows = {}
        moment = [datetime(2026, 9, 9, 8, tzinfo=timezone.utc).timestamp()]

        def reserve(p, api, params, epoch):
            key = verify.digest(json_bytes([api, params, epoch]))
            db.states[key] = "probe_prepared"
            row = {
                "epoch": epoch,
                "result": None,
                "state": "probe_prepared",
                "retry_after": 0,
                "tries": 0,
                "job": json.dumps(
                    {
                        "api_name": api,
                        "params": params,
                        "fields": ",".join(REALTIME_RUNTIME_CONTRACTS[api]["fields"]),
                    }
                ),
            }
            rows[key] = row
            return key, row

        captured = []

        def capture(client, token, job, root):
            api = job["api_name"]
            self.assertIn("account", db.gates)
            self.assertIn("api:" + api, db.gates)
            self.assertGreater(db.gates["account"], moment[0])
            self.assertAlmostEqual(
                db.gates["account"] - moment[0],
                60
                / min(
                    config["requests_per_minute"],
                    config.get("rollout_account_rpm", 500),
                ),
                places=5,
            )
            self.assertTrue(
                any(state == "probe_inflight" for state in db.committed[-1].values())
            )
            captured.append(api)
            if local_quota:
                return {
                    "api_name": api,
                    "status": "rate_limited",
                    "upstream_calls": 0,
                    "local_daily_quota": {"reserved": False},
                }
            if exception:
                raise OSError("synthetic uncertain request")
            return {
                "api_name": api,
                "status": status if api == "stk_auction" else "empty_unverified",
                "row_count": 0,
            }

        args = argparse.Namespace(
            seeds=path,
            seeds_sha256=sha,
            report=Path(self.temp.name) / "result.json",
            epoch="snapshot-20260909T080000Z",
            seconds=seconds,
            helper_sha256="0" * 64,
        )
        fake = argparse.Namespace(root=self.root, db=db)
        context = (
            patch.object(probe, "seed_requests", return_value=(planned, {})),
            patch.object(probe, "reserve_probe", side_effect=reserve),
            patch.object(probe.time, "time", side_effect=lambda: moment[0]),
            patch.object(probe.time, "monotonic", side_effect=lambda: moment[0]),
            patch.object(
                probe.time,
                "sleep",
                side_effect=lambda seconds: moment.__setitem__(0, moment[0] + seconds),
            ),
            patch.object(probe.signal, "setitimer"),
            patch("backend.shared.tushare_intake.capture_sample", side_effect=capture),
        )
        from contextlib import ExitStack

        with ExitStack() as stack:
            for guard in context:
                stack.enter_context(guard)
            if exception:
                with self.assertRaises(OSError):
                    probe.collect(
                        fake,
                        config,
                        None,
                        lambda: "synthetic-not-a-secret",
                        args,
                    )
                result = json.loads(args.report.read_bytes())
            else:
                result = probe.collect(
                    fake,
                    config,
                    None,
                    lambda: "synthetic-not-a-secret",
                    args,
                )
        return result, captured, db, args

    def test_collect_max15_and_gates_before_every_request(self):
        result, calls, db, args = self.execute_mocked()
        self.assertEqual(len(calls), 15)
        self.assertEqual(result["actual_upstream_calls"], 15)
        self.assertEqual(Counter(calls)["stk_auction"], 6)
        self.assertFalse(result["enable_performed"])
        self.assertFalse(result["configuration_changed"])

    def test_denial_stops_same_api_preserves_others(self):
        result, calls, db, args = self.execute_mocked(status="permission_denied")
        self.assertEqual(len(calls), 10)
        self.assertEqual(Counter(calls)["stk_auction"], 1)
        self.assertEqual(
            sum(r["status"] == "skipped_same_api_stop" for r in result["results"]), 5
        )

    def test_rate_limit_stops_same_api(self):
        result, calls, db, args = self.execute_mocked(status="rate_limited")
        self.assertLessEqual(Counter(calls)["stk_auction"], 1)

    def test_uncertain_request_stays_nonschedulable_and_reported(self):
        result, calls, db, args = self.execute_mocked(exception=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["actual_upstream_calls"], 1)
        self.assertEqual(set(db.states.values()), {"probe_inflight"})
        self.assertEqual(result["stop_reason"], "probe_interrupted:OSError")

    def test_short_budget_defers_without_overshooting(self):
        result, calls, db, args = self.execute_mocked(seconds=15)
        self.assertLessEqual(len(calls), 15)
        self.assertTrue(
            any(r["status"] == "deferred_cached_gate" for r in result["results"])
        )

    def test_rollout300_not_account500_is_persisted(self):
        config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 300,
        }
        result, calls, db, args = self.execute_mocked(config=config)
        self.assertEqual(result["actual_upstream_calls"], 15)
        self.assertEqual(len(calls), 15)

    def test_local_no_http_quota_keeps_prepared_and_counts_zero(self):
        result, calls, db, args = self.execute_mocked(local_quota=True)
        self.assertEqual(result["actual_upstream_calls"], 0)
        self.assertEqual(set(db.states.values()), {"probe_prepared"})
        self.assertTrue(
            any(r["status"] == "deferred_local_daily_quota" for r in result["results"])
        )


class CurrentPolicy(unittest.TestCase):
    def test_shared_resolver_rollout_ceiling_and_observed_quota(self):
        from backend.shared.tushare_rate_policy import resolved_api_rate
        from datetime import timezone

        db = MemoryDB()
        db.quotas["quota:rt_idx_k"] = {"interval_seconds": 1800}
        config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 300,
            "api_requests_per_minute": {"rt_idx_k": 25},
            "api_min_interval_seconds": {"rt_idx_k": 5},
        }
        instant = datetime(2026, 9, 10, tzinfo=timezone.utc)
        with patch.object(probe.time, "time", return_value=instant.timestamp()):
            actual = probe.resolved_gates(db, "rt_idx_k", config)
        expected = resolved_api_rate(
            "rt_idx_k", REALTIME_RUNTIME_CONTRACTS["rt_idx_k"], config, instant
        )
        self.assertEqual(
            actual,
            {
                "account_rpm": 300,
                "api_rpm": expected["rpm"],
                "minimum_interval_seconds": 1800,
            },
        )
        self.assertLessEqual(actual["api_rpm"], 25)

    def test_missing_policy_bad_rollout_or_nan_quota_fail_closed(self):
        db = MemoryDB()
        for config in (
            {"requests_per_minute": 500},
            {"rate_policy": "tiered_v1", "requests_per_minute": True},
            {
                "rate_policy": "tiered_v1",
                "requests_per_minute": 500,
                "rollout_account_rpm": 0,
            },
        ):
            with self.assertRaises(ValueError):
                probe.resolved_gates(db, "rt_k", config)
        db.quotas["quota:rt_k"] = {"interval_seconds": float("nan")}
        with self.assertRaises(ValueError):
            probe.resolved_gates(
                db, "rt_k", {"rate_policy": "tiered_v1", "requests_per_minute": 500}
            )

    def test_response_message_body_and_header_never_enter_result(self):
        private = "FAKE_PRIVATE_RESPONSE_MARKER"
        result = probe.safe_result(
            {
                "status": "permission_denied",
                "row_count": 0,
                "message": private,
                "body": private,
                "token": private,
                "headers": {"Authorization": private},
                "missing_fields": [private],
                "normalization_error": private,
            }
        )
        self.assertNotIn(private, json.dumps(result))
        self.assertEqual(result["status"], "permission_denied")
        self.assertIn("normalization_error", result)
        self.assertEqual(
            probe.safe_result({"status": private})["status"], "invalid_response"
        )


if __name__ == "__main__":
    unittest.main()
