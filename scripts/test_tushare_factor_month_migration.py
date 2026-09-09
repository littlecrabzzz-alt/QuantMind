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
        self.assertFalse(result["apply_allowed"])
        self.assertEqual(result["status"], "plan_only_atomic_switch_unavailable")
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


if __name__ == "__main__":
    unittest.main()
