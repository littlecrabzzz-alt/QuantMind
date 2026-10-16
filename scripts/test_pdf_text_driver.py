"""Driver cycle logic against fixtures. QM_OCR_PY substitutes the python
executable with a fixture script that prints stage markers, so the quota
backoff, unknown-status pause and no_candidates branches run without eval and
without touching production paths. Paths deliberately contain spaces. A zsh
read-only variable regression (e.g. assigning to `status`) aborts the script
with a non-zero code and stderr output, so these tests catch it too."""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
DRIVER = Path(__file__).resolve().parents[1] / "scripts" / "pdf_text_driver.sh"
CLIENT = Path.home() / "Library/Application Support/QuantMind/tushare-client"

FIXTURE_STAGE = """#!/bin/sh
# Fixture "python": prints a chosen stage marker per invocation cycle; when
# invoked as the maintenance entry it exits with QM_FIX_MAINTAIN_RC (default 0).
case "$*" in
  *maintain.py*)
    exit "${QM_FIX_MAINTAIN_RC:-0}"
    ;;
esac
if [ ! -f "$QM_FIX_DIR/.cycle" ]; then
  touch "$QM_FIX_DIR/.cycle"
  printf '%s\\n' "$QM_FIX_FIRST"
else
  echo "stage=no_candidates attempted=2 completed=2 total_pages=53"
fi
"""


class DriverCycle(unittest.TestCase):

    def fixture_home(self):
        home = tempfile.mkdtemp(prefix="qm driver test dir ")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", home], check=False))
        Path(home, "ocr.log").write_text("", encoding="utf-8")
        return home

    def base_env(self, home):
        env = dict(os.environ)
        env.update({
            "QM_OCR_M": home,
            "QM_OCR_RT": tempfile.gettempdir(),
            "QM_OCR_ROOT": home + "/root with space",
            "QM_OCR_ST": home + "/staging with space",
            "QM_OCR_BACKOFF": "1",
            "QM_OCR_PAUSE": "1",
            "QM_OCR_PARSE_PATTERN": "qm_driver_test_no_such_parse_job",
        })
        return env

    def run_fixture_driver(self, first_marker):
        home = self.fixture_home()
        fixture_py = Path(home, "fake python bin")
        fixture_py.write_text(FIXTURE_STAGE, encoding="utf-8")
        fixture_py.chmod(fixture_py.stat().st_mode | stat.S_IXUSR)
        env = self.base_env(home)
        env.update({"QM_OCR_PY": str(fixture_py), "QM_FIX_DIR": home,
                    "QM_FIX_FIRST": first_marker})
        proc = subprocess.run(["zsh", str(DRIVER)], env=env,
                              capture_output=True, text=True, timeout=60)
        return proc, home

    def test_quota_backoff_then_no_candidates_exits_cleanly(self):
        proc, home = self.run_fixture_driver("stage=quota_exceeded bounded_wait_exceeded=1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        maintain = Path(home, "maintain.log").read_text(encoding="utf-8")
        self.assertIn("quota backoff 1s", maintain)
        self.assertIn("no more candidates", maintain)

    def test_unknown_status_pauses_then_exits_on_no_candidates(self):
        proc, home = self.run_fixture_driver(
            "WARNING:root:OCR quota wait sha=abc page=3 sleep=120s")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        maintain = Path(home, "maintain.log").read_text(encoding="utf-8")
        self.assertIn("no more candidates", maintain)
        self.assertNotIn("quota backoff", maintain)
    def test_real_stage_command_handles_paths_with_spaces(self):

        # Exercises the production command line (only the python executable is
        # substituted) so word-splitting regressions on "Application Support"
        # style paths fail here instead of in the error loop.
        if not (CLIENT / ".venv/bin/python").exists():
            self.skipTest("local tushare-client runtime not installed")
        home = self.fixture_home()
        env = self.base_env(home)
        env["QM_OCR_RT"] = str(CLIENT)
        env["QM_OCR_PY"] = str(CLIENT / ".venv/bin/python")
        proc = subprocess.run(["zsh", str(DRIVER)], env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log = Path(home, "ocr.log").read_text(encoding="utf-8")
        self.assertNotIn("unrecognized arguments", log)
        self.assertIn("stage=no_candidates", log)
        self.assertIn("no more candidates",
                      Path(home, "maintain.log").read_text(encoding="utf-8"))


    def drain_home(self, maintain_rc=None):
        home = self.fixture_home()
        fixture_py = Path(home, "fake python bin")
        fixture_py.write_text(FIXTURE_STAGE, encoding="utf-8")
        fixture_py.chmod(fixture_py.stat().st_mode | stat.S_IXUSR)
        Path(home, "maintain.py").write_text("# stub for fixture driver\n")
        staging = Path(home, "staging with space")
        staging.mkdir()
        (staging / "abc.json").write_text("{}", encoding="utf-8")
        env = self.base_env(home)
        env.update({"QM_OCR_PY": str(fixture_py), "QM_FIX_DIR": home,
                    "QM_FIX_FIRST": "stage=no_candidates attempted=0 completed=0 total_pages=0"})
        if maintain_rc is not None:
            env["QM_FIX_MAINTAIN_RC"] = str(maintain_rc)
        return env, home

    def test_final_drain_ingests_pending_staged_before_exit(self):
        env, home = self.drain_home()
        proc = subprocess.run(["zsh", str(DRIVER)], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        maintain = Path(home, "maintain.log").read_text(encoding="utf-8")
        self.assertIn("final drain start (1 staged)", maintain)
        self.assertIn("final drain done", maintain)
        self.assertTrue(Path(home, ".last-maintain").exists())

    def test_final_drain_busy_keeps_retrying_instead_of_exiting(self):
        env, home = self.drain_home(maintain_rc=75)
        proc = subprocess.Popen(["zsh", str(DRIVER)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                proc.communicate(timeout=6)
        finally:
            proc.kill()
            proc.communicate()
        maintain = Path(home, "maintain.log").read_text(encoding="utf-8")
        self.assertGreaterEqual(maintain.count("final drain busy/failed"), 2)

if __name__ == "__main__":
    unittest.main()
