"""Driver cycle logic against fixtures: quota backoff branch, unknown-status
pause branch, and the clean no_candidates exit. Catches zsh read-only variable
regressions (e.g. assigning to `status`) because a failed assignment aborts
the script with a non-zero code and stderr output."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
DRIVER = Path(__file__).resolve().parents[1] / "scripts" / "pdf_text_driver.sh"


class DriverCycle(unittest.TestCase):
    def run_driver(self, stage_script):
        home = tempfile.mkdtemp(prefix="qm-driver-test-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", home], check=False))
        env = dict(os.environ)
        env.update({
            "QM_OCR_M": home,
            "QM_OCR_RT": tempfile.gettempdir(),
            "QM_OCR_ROOT": home,
            "QM_OCR_ST": home,
            "QM_OCR_STAGE": stage_script,
            "QM_OCR_BACKOFF": "1",
            "QM_OCR_PAUSE": "1",
            "QM_OCR_PARSE_PATTERN": "qm_driver_test_no_such_parse_job",
        })
        Path(home, "ocr.log").write_text("", encoding="utf-8")
        return subprocess.run(["zsh", str(DRIVER)], env=env,
                              capture_output=True, text=True, timeout=60), home

    def test_quota_backoff_then_no_candidates_exits_cleanly(self):
        stage = (
            'if [ ! -f "$QM_OCR_M/.cycle" ]; then touch "$QM_OCR_M/.cycle"; '
            'echo "stage=quota_exceeded bounded_wait_exceeded=1"; '
            'else echo "stage=no_candidates attempted=2 completed=2 total_pages=53"; fi'
        )
        proc, home = self.run_driver(stage)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        maintain = Path(home, "maintain.log").read_text(encoding="utf-8")
        self.assertIn("quota backoff 1s", maintain)
        self.assertIn("no more candidates", maintain)

    def test_unknown_status_pauses_then_exits_on_no_candidates(self):
        stage = (
            'if [ ! -f "$QM_OCR_M/.cycle" ]; then touch "$QM_OCR_M/.cycle"; '
            'echo "WARNING:root:OCR quota wait sha=abc page=3 sleep=120s"; '
            'else echo "stage=no_candidates attempted=0 completed=0 total_pages=0"; fi'
        )
        proc, home = self.run_driver(stage)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        maintain = Path(home, "maintain.log").read_text(encoding="utf-8")
        self.assertIn("no more candidates", maintain)
        self.assertNotIn("quota backoff", maintain)


if __name__ == "__main__":
    unittest.main()
