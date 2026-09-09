"""Read-only preflight, immutable audit crashes and actual CLI: no authority mutation."""

from datetime import date
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tushare_factor_month_migration as helper  # noqa: E402
import test_tushare_factor_library_month_planning as fixtures  # noqa: E402
from backend.shared.tushare_factor_library_contracts import iter_factor_library_jobs  # noqa: E402


class Preflight(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.FactorMonths()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.p, self.root = self.f.p, self.f.root.resolve()
        self.config = {**fixtures.CONFIG, "factor_library_history_start": "20260801"}
        self.f.plan(self.config)
        (self.root / "pipeline.lock").write_bytes(b"")
        (self.root / "pipeline-config.json").write_bytes(helper.encoded(self.config))
        self.output_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.output_dir.cleanup)
        self.output = Path(self.output_dir.name) / "audit.json"

    def contents(self):
        return {
            table: [tuple(r) for r in self.p.db.execute("SELECT * FROM " + table)]
            for table in (
                "jobs",
                "attempts",
                "planning_state",
                "request_gates",
                "capability",
            )
        }

    def test_locked_prepare_proves_whole_tail_and_exact_frozen_front_without_writes(
        self,
    ):
        before = self.contents()
        cfg = (self.root / "pipeline-config.json").read_bytes()
        result = helper.prepare(self.root)
        self.assertTrue(result["apply_allowed"])
        self.assertEqual(result["status"], "prepared_month_transition")
        self.assertEqual(result["deferred_jobs"], 0)
        proof = result["coverage"]["history:factor_library"]
        self.assertEqual(proof["daily_history_requests"], 66)
        self.assertEqual(proof["month_history_requests"], 4)
        self.assertEqual(proof["consumed_history_source_items"], 3)
        self.assertEqual(proof["unplanned_daily_history_items"], 63)
        self.assertEqual(proof["next_date_already_enumerated_codes"], ["000001.SZ"])
        self.assertEqual(proof["next_unplanned_daily_date"], "20260802")
        actual = list(
            iter_factor_library_jobs(
                {**self.config, "factor_library_history_window": "month"},
                date(2026, 9, 9),
                fixtures.IDS,
            )
        )
        history = [j for j in actual if j["epoch"] == "history"]
        self.assertEqual(
            {
                helper.encoded({k: v for k, v in j["params"].items() if k != "ts_code"})
                for j in history
            },
            {helper.encoded(w) for w in proof["month_windows"]},
        )
        self.assertEqual(
            result["preimage_states"]["history:factor_library"]["offset"], 17
        )
        self.assertEqual(
            result["candidate_states_not_applied"]["history:factor_library"]["offset"],
            0,
        )
        recent = result["preimage_states"]["recent:factor_library"]
        self.assertEqual(
            result["candidate_states_not_applied"]["recent:factor_library"]["offset"],
            recent["offset"],
        )
        self.assertEqual(self.contents(), before)
        self.assertEqual((self.root / "pipeline-config.json").read_bytes(), cfg)

    def test_idempotent_audit_and_before_after_write_interruption_leave_authority_unchanged(
        self,
    ):
        result, before = helper.prepare(self.root), self.contents()
        with patch.object(
            helper.os, "link", side_effect=OSError("fixture before install")
        ):
            with self.assertRaises(OSError):
                helper.save_immutable(self.output, result)
        self.assertFalse(self.output.exists())
        real_link = helper.os.link

        def installed_then_crashed(a, b):
            real_link(a, b)
            raise OSError("fixture after atomic install")

        with patch.object(helper.os, "link", side_effect=installed_then_crashed):
            with self.assertRaises(OSError):
                helper.save_immutable(self.output, result)
        raw = self.output.read_bytes()
        helper.save_immutable(self.output, helper.prepare(self.root, result))
        self.assertEqual(self.output.read_bytes(), raw)
        self.assertEqual(self.contents(), before)
        with self.assertRaises(ValueError):
            helper.save_immutable(self.output, {**result, "changed": True})
        self.assertEqual(self.output.read_bytes(), raw)

    def test_configuration_drift_or_new_cursor_progress_refused_not_rolled_back(self):
        before = helper.prepare(self.root)
        path = self.root / "pipeline-config.json"
        path.write_bytes(helper.encoded({**self.config, "group_weights": {"rrg": 100}}))
        with self.assertRaisesRegex(ValueError, "drift"):
            helper.prepare(self.root, before)
        self.assertEqual(json.loads(path.read_bytes())["group_weights"], {"rrg": 100})
        path.write_bytes(helper.encoded(self.config))
        self.f.plan(self.config)
        progressed = self.contents()
        with self.assertRaisesRegex(ValueError, "drift"):
            helper.prepare(self.root, before)
        self.assertEqual(self.contents(), progressed)

    def test_existing_job_progress_and_raw_artifacts_never_restored_or_deferred(self):
        before = helper.prepare(self.root)
        row = {
            "factor_name": "observed",
            "ts_code": "T600018.SH",
            "trade_date": "20260801",
            "factor_value": None,
        }
        saved = self.f.capture(
            "factor_value",
            {"ts_code": "T600018.SH", "trade_date": "20260801"},
            [row],
            epoch="history",
        )[2]
        current = self.contents()
        files = [
            self.root / "observations" / saved["observation"],
            self.root / "objects" / (saved["object_sha256"] + ".json"),
            self.root / saved["parquet"]["path"],
        ]
        checksums = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
        self.assertEqual(helper.prepare(self.root, before), before)
        self.assertEqual(self.contents(), current)
        self.assertEqual(
            [hashlib.sha256(p.read_bytes()).hexdigest() for p in files], checksums
        )

    def test_busy_lock_and_unknown_state_reject_without_mutation(self):
        before = self.contents()
        with (self.root / "pipeline.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                helper.prepare(self.root)
        self.assertEqual(before, self.contents())
        self.p.db.execute(
            "UPDATE planning_state SET signature='legacy' WHERE name='history:factor_library'"
        )
        self.p.db.commit()
        changed = self.contents()
        with self.assertRaisesRegex(ValueError, "Legacy"):
            helper.prepare(self.root)
        self.assertEqual(changed, self.contents())

    def test_prefix_offsets_completed_history_and_empty_scope_bounds(self):
        state = helper.prepare(self.root)["preimage_states"]["history:factor_library"]
        for offset in (0, 5, 14, 17, 80):
            proof = helper.coverage(
                self.config, {**state, "offset": offset, "done": int(offset == 80)}
            )
            self.assertEqual(
                proof["consumed_history_source_items"], max(0, offset - 14)
            )
        with self.assertRaises(ValueError):
            helper.coverage(self.config, {**state, "offset": 81})
        with self.assertRaises(ValueError):
            helper.coverage(self.config, {**state, "offset": 17, "done": 1})

    def test_old_runtime_without_month_policy_support_rejected(self):
        from backend.shared import tushare_pipeline as pipeline

        real = pipeline._planning_inputs

        def legacy(family, config, ids):
            return real(
                family,
                {
                    k: v
                    for k, v in config.items()
                    if k != "factor_library_history_window"
                },
                ids,
            )

        before = self.contents()
        with patch.object(pipeline, "_planning_inputs", side_effect=legacy):
            with self.assertRaisesRegex(ValueError, "not installed"):
                helper.prepare(self.root)
        self.assertEqual(before, self.contents())

    def test_real_python310_cli_subprocess_and_revalidation_no_execute_switch(self):
        script = Path(helper.__file__)
        cmd = [
            sys.executable,
            "-S",
            str(script),
            "--root",
            str(self.root),
            "--output",
            str(self.output),
        ]
        before = self.contents()
        first = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        self.assertEqual(first.returncode, 0, first.stderr)
        body = self.output.read_bytes()
        again = subprocess.run(
            cmd
            + [
                "--revalidate",
                str(self.output),
                "--expected-audit-sha256",
                helper.sha(body),
            ],
            capture_output=True,
            text=True,
            timeout=35,
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.output.read_bytes(), body)
        unsupported = subprocess.run(
            cmd + ["--execute"], capture_output=True, text=True, timeout=35
        )
        self.assertNotEqual(unsupported.returncode, 0)
        self.assertEqual(self.contents(), before)


class Apply(Preflight):
    def setUp(self):
        super().setUp()
        self.audit = helper.prepare(self.root)
        self.audit_path = Path(self.output_dir.name) / "reviewed.json"
        helper.save_immutable(self.audit_path, self.audit)
        self.audit_sha = helper.sha(self.audit_path.read_bytes())
        self.helper_sha = helper.sha(Path(helper.__file__).read_bytes())

    def apply(self, mode="execute"):
        with patch.object(helper, "_require_authority") as guard:
            result = helper.transition(
                self.root, self.audit_path, self.audit_sha, self.helper_sha, mode
            )
            guard.assert_called_once_with(self.root)
            return result

    def unaffected(self):
        return {k: v for k, v in self.contents().items() if k != "planning_state"}

    def test_all_interruption_points_recover_only_exact_old_new_and_complete(self):
        # Each subtest has its own complete isolated authority fixture.
        stages = (
            "before_journal",
            "after_journal",
            "after_config",
            "after_first_state",
            "before_sql_commit",
            "after_sql_commit",
            "before_receipt_rename",
            "after_receipt_rename",
            "after_receipt_fsync",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                f = Apply()
                f.setUp()
                try:
                    untouched = f.unaffected()

                    def crash(at, wanted=stage):
                        if at == wanted:
                            raise OSError("fixture crash")

                    with patch.object(helper, "_checkpoint", side_effect=crash):
                        with self.assertRaises(OSError):
                            f.apply()
                    self.assertEqual(f.unaffected(), untouched)
                    pending = (f.root / helper.PENDING).exists()
                    if pending:
                        from backend.shared import tushare_pipeline as pipeline

                        with (
                            patch.object(pipeline, "ROOT", f.root),
                            patch.object(pipeline, "authority"),
                            patch.object(
                                pipeline,
                                "get_secret",
                                side_effect=AssertionError(
                                    "pending must not read secrets"
                                ),
                            ),
                        ):
                            (f.root / "ENABLED").touch()
                            self.assertEqual(
                                pipeline.tick()["status"], "blocked_pending_migration"
                            )
                        result = f.apply("recover")
                    else:
                        result = f.apply()
                    self.assertIn(
                        result["status"], ("completed", "already_completed_no_changes")
                    )
                    self.assertFalse((f.root / helper.PENDING).exists())
                    self.assertEqual(f.unaffected(), untouched)
                    actual = {
                        r["name"]: dict(r)
                        for r in f.p.db.execute("SELECT * FROM planning_state")
                    }
                    self.assertEqual(actual, f.audit["candidate_states_not_applied"])
                    self.assertEqual(
                        json.loads((f.root / "pipeline-config.json").read_bytes()),
                        {**f.config, "factor_library_history_window": "month"},
                    )
                    self.assertEqual(
                        f.apply()["status"], "already_completed_no_changes"
                    )
                finally:
                    f.doCleanups()

    def test_completed_new_planning_resumes_month_and_preserves_existing_jobs(self):
        oldjobs = self.unaffected()
        self.apply()
        cfg = json.loads((self.root / "pipeline-config.json").read_bytes())
        snapshot = json.loads(
            self.audit["candidate_states_not_applied"]["history:factor_library"][
                "signature"
            ]
        )
        # Actual existing planner, not a replacement model; no source calls.
        self.f.plan(cfg)
        state = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertEqual(json.loads(state["signature"]), snapshot)
        self.assertGreater(state["offset"], 0)
        jobs = [dict(r) for r in self.p.db.execute("SELECT * FROM jobs")]
        originals = {row[0]: row for row in oldjobs["jobs"]}
        for r in self.p.db.execute("SELECT * FROM jobs"):
            if r["id"] in originals:
                self.assertEqual(tuple(r), originals[r["id"]])
        month = [
            json.loads(r["job"])
            for r in jobs
            if "start_date" in json.loads(r["job"])["params"]
        ]
        self.assertEqual(len(month), 3)
        advanced = self.contents()
        self.assertEqual(self.apply()["status"], "already_completed_no_changes")
        self.assertEqual(self.contents(), advanced)

    def test_real_tick_after_complete_uses_month_and_keeps_done_raw_attempts(self):
        from backend.shared import tushare_pipeline as pipeline
        from types import SimpleNamespace

        row = {
            "factor_name": "observed",
            "ts_code": "T600018.SH",
            "trade_date": "20260801",
            "factor_value": 1.0,
        }
        saved = self.f.capture(
            "factor_value",
            {"ts_code": "T600018.SH", "trade_date": "20260801"},
            [row],
            epoch="history",
        )[2]
        untouched = self.unaffected()
        files = [
            self.root / "observations" / saved["observation"],
            self.root / "objects" / (saved["object_sha256"] + ".json"),
            self.root / saved["parquet"]["path"],
        ]
        hashes = [helper.sha(p.read_bytes()) for p in files]
        self.apply()
        (self.root / "ENABLED").touch()
        original_planner = self.p.plan_extended

        def actual_planner(config, today):
            with patch.object(self.p, "identifiers", return_value=fixtures.IDS):
                return original_planner(config, today)

        with (
            patch.object(pipeline, "ROOT", self.root),
            patch.object(pipeline, "authority"),
            patch.object(pipeline, "get_secret", return_value="fixture-only"),
            patch.object(
                pipeline.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=200 * 2**30),
            ),
            patch.object(pipeline, "Pipeline", return_value=self.p),
            patch.object(self.p, "initialize"),
            patch.object(self.p, "plan_extended", side_effect=actual_planner),
            patch("backend.shared.tushare_archive.recover_archive", return_value={}),
            patch.object(self.p, "run", return_value={"requests": 0}),
            patch.object(self.p, "publish", return_value="data-" + "a" * 64),
            patch.object(self.p, "close"),
        ):
            result = pipeline.tick()
        self.assertEqual(result["requests"], 0)
        state = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertEqual(
            state["signature"],
            self.audit["candidate_states_not_applied"]["history:factor_library"][
                "signature"
            ],
        )
        self.assertGreater(state["offset"], 0)
        now = self.contents()
        for table in ("attempts", "request_gates", "capability"):
            self.assertEqual(now[table], untouched[table])
        jobs = {r[0]: r for r in now["jobs"]}
        self.assertTrue(all(jobs[r[0]] == r for r in untouched["jobs"]))
        self.assertEqual([helper.sha(p.read_bytes()) for p in files], hashes)
        self.assertTrue(
            any(
                "start_date" in json.loads(r["job"])["params"]
                for r in self.p.db.execute("SELECT * FROM jobs")
            )
        )

    def test_drift_secret_credentials_and_unknown_partial_state_fail_closed(self):
        before = self.unaffected()
        with patch.object(
            helper,
            "_checkpoint",
            side_effect=lambda stage: (
                (_ for _ in ()).throw(OSError("fixture"))
                if stage == "after_journal"
                else None
            ),
        ):
            with self.assertRaises(OSError):
                self.apply()
        p = self.root / "pipeline-config.json"
        p.write_bytes(helper.encoded({**self.config, "batch_requests": 1}))
        current = self.contents()
        with self.assertRaisesRegex(ValueError, "drift"):
            self.apply("recover")
        self.assertEqual(self.contents(), current)
        p.write_bytes(helper.encoded(self.config))
        self.p.db.execute(
            "UPDATE planning_state SET offset=offset+1 WHERE name='history:factor_library'"
        )
        self.p.db.commit()
        with self.assertRaisesRegex(ValueError, "drift"):
            self.apply("recover")
        self.assertEqual(self.unaffected(), before)
        with self.assertRaisesRegex(ValueError, "Credential"):
            helper._safe_config({"nested": {"TUSHARE_TOKEN": "never-save"}})

    def test_execute_requires_authority_sha_and_explicit_recover(self):
        with self.assertRaises(ValueError):
            helper.transition(
                self.root, self.audit_path, self.audit_sha, self.helper_sha, "execute"
            )
        with patch.object(helper, "_require_authority"):
            with self.assertRaisesRegex(ValueError, "helper SHA"):
                helper.transition(
                    self.root, self.audit_path, self.audit_sha, "0" * 64, "execute"
                )
            with self.assertRaisesRegex(ValueError, "audit SHA"):
                helper.transition(
                    self.root, self.audit_path, "0" * 64, self.helper_sha, "execute"
                )
        with patch.object(
            helper,
            "_checkpoint",
            side_effect=lambda stage: (
                (_ for _ in ()).throw(OSError("fixture"))
                if stage == "after_journal"
                else None
            ),
        ):
            with self.assertRaises(OSError):
                self.apply()
        with self.assertRaisesRegex(ValueError, "explicit recover"):
            self.apply()

    def test_fsync_failure_before_config_keeps_pending_and_tick_gate(self):
        original = helper._sync_dir
        count = [0]

        def fail_once(path):
            count[0] += 1
            if count[0] == 1:
                raise OSError("fixture directory fsync failure")
            return original(path)

        old = (self.root / "pipeline-config.json").read_bytes()
        with patch.object(helper, "_sync_dir", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.apply()
        self.assertTrue((self.root / helper.PENDING).exists())
        self.assertEqual((self.root / "pipeline-config.json").read_bytes(), old)
        self.assertEqual(self.apply("recover")["status"], "completed")

    def test_config_replace_and_receipt_rename_failures_recover_without_dropping_pending(
        self,
    ):
        for operation in ("replace", "rename"):
            with self.subTest(operation=operation):
                f = Apply()
                f.setUp()
                try:
                    old = f.unaffected()
                    with patch.object(
                        helper.os,
                        operation,
                        side_effect=OSError("fixture rename failure"),
                    ):
                        with self.assertRaises(OSError):
                            f.apply()
                    self.assertTrue((f.root / helper.PENDING).exists())
                    self.assertEqual(f.unaffected(), old)
                    self.assertEqual(f.apply("recover")["status"], "completed")
                    self.assertEqual(f.unaffected(), old)
                finally:
                    f.doCleanups()

    def test_apply_real_cli_subprocess_and_idempotent_output(self):
        # Only the authority boundary is mocked in a fresh child; real argparse,
        # file SHA, lock, journal, config and SQLite transaction run on temp files.
        code = """
import sys,sysconfig
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[1]+'/scripts', str(Path(sys.executable).absolute().parent.parent/'lib'/('python%d.%d'%sys.version_info[:2])/'site-packages'),sysconfig.get_paths()['purelib']]
import tushare_factor_month_migration as h
expected = Path(sys.argv[2])
def fixture_authority(root):
    assert root == expected and root != Path('/data/tushare') and root.is_dir()
h._require_authority = fixture_authority
sys.argv = [h.__file__, '--root', str(expected), '--output', sys.argv[3], '--mode', 'execute', '--revalidate', sys.argv[4], '--expected-audit-sha256', sys.argv[5], '--helper-sha256', sys.argv[6]]
h.main()
"""
        repo = str(Path(helper.__file__).resolve().parents[1])
        cmd = [
            sys.executable,
            "-S",
            "-c",
            code,
            repo,
            str(self.root),
            str(self.output),
            str(self.audit_path),
            self.audit_sha,
            self.helper_sha,
        ]
        old = self.unaffected()
        for _ in range(2):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(self.output.read_bytes())["status"], "completed_receipt"
            )
            self.assertEqual(self.unaffected(), old)

    def test_ungated_old_tick_is_rejected_before_any_transition(self):
        from backend.shared import tushare_pipeline as pipeline

        old = self.contents()
        with patch.object(pipeline, "tick", lambda: None):
            with self.assertRaisesRegex(ValueError, "not installed"):
                self.apply()
        self.assertFalse((self.root / helper.PENDING).exists())
        self.assertEqual(self.contents(), old)

    def test_tick_reads_config_only_after_lock_and_gate(self):
        from backend.shared import tushare_pipeline as pipeline

        (self.root / "ENABLED").touch()
        original = pipeline.fcntl.flock

        def lock_and_change(fd, mode):
            original(fd, mode)
            # Simulate config changing while this tick is acquiring the lock.
            (self.root / "pipeline-config.json").write_bytes(b'{"batch_requests":0}')

        with (
            patch.object(pipeline, "ROOT", self.root),
            patch.object(pipeline, "authority"),
            patch.object(pipeline.fcntl, "flock", side_effect=lock_and_change),
            patch.object(
                pipeline, "get_secret", side_effect=AssertionError("no credentials")
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Invalid bounded batch limits"):
                pipeline.tick()


if __name__ == "__main__":
    unittest.main()
