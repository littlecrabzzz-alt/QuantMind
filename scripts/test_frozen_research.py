import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_frozen_research as runner


class FrozenResearchTest(unittest.TestCase):
    def setUp(self):
        self.cfg = runner.read(runner.ROOT / "config/research_controls_cn_l1.json")

    def test_invalid_period_is_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["split"]["test"][0] = cfg["split"]["valid"][1]
        with self.assertRaises(ValueError):
            runner.validate_config(cfg)

    def test_live_edits_do_not_change_frozen_inputs_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.txt"
            source.write_text("original data")
            out = root / "experiment"
            with patch.object(runner, "snapshot_files", return_value={source: Path("data.txt")}), patch.object(runner.subprocess, "check_output", return_value="commit"):
                runner.freeze(root, out, self.cfg, {"Id": "sha256:fixed"})
            source.write_text("new live data")
            self.assertEqual((out / "snapshot/data.txt").read_text(), "original data")
            runner.verify(out)
            (out / "snapshot/data.txt").write_text("tampered")
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                runner.verify(out)

    def test_container_only_mounts_readonly_snapshot_and_output(self):
        cmd = runner.command(Path("/experiments/one"), {"image": {"Id": "sha256:fixed", "Os": "linux", "Architecture": "amd64"}}, Path("/experiments/one/attempt-1"))
        mounts = [cmd[i + 1] for i, value in enumerate(cmd) if value == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertIn("dst=/frozen,readonly", mounts[0])
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertIn("sha256:fixed", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("PYTHONHASHSEED=42", cmd)


if __name__ == "__main__":
    unittest.main()
