import copy
from pathlib import Path
import tempfile
import struct
import hashlib
import unittest
from unittest.mock import patch

import run_frozen_research as runner


from scripts.continuous_research.qlib_provider import build_provider


def provider_args(root, cfg):
    base = root.resolve()
    cutoff = cfg["split"]["test"][1]
    raw = base / ("synthetic-provider-source-" + cutoff)
    manifest = (
        base / ("generated-provider-" + cutoff) / "provider/provider_manifest.json"
    )
    if not manifest.exists():
        calendar = [cfg["split"]["train"][0], cutoff]
        (raw / "calendars").mkdir(parents=True)
        (raw / "calendars/day.txt").write_text("\n".join(calendar) + "\n")
        (raw / "features/syn_a").mkdir(parents=True)
        (raw / "features/syn_a/close.day.bin").write_bytes(
            struct.pack("<3f", 0, 11, 12)
        )
        build_provider(
            raw,
            manifest.parents[1],
            calendar_prefix=calendar,
            cutoff=cutoff,
            symbols=["syn_a"],
            fields=["close"],
            lifetimes={"syn_a": calendar},
            benchmark=None,
        )
    return {
        "provider_manifest": manifest,
        "provider_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }


class FrozenResearchTest(unittest.TestCase):
    def setUp(self):
        self.cfg = runner.read(runner.ROOT / "config/research_controls_cn_l1.json")
        # Tests explicitly declare a boundary; the historical config is not
        # silently granted a current research admission date.
        self.cfg["development_end"] = self.cfg["split"]["test"][1]

    def test_missing_boundary_rejected_before_source_inventory(self):
        cfg = copy.deepcopy(self.cfg)
        cfg.pop("development_end")
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(runner, "snapshot_files") as inventory,
        ):
            with self.assertRaisesRegex(ValueError, "development_end"):
                runner.freeze(Path(temp), Path(temp) / "out", cfg, {"Id": "synthetic"})
            inventory.assert_not_called()
            self.assertFalse((Path(temp) / "out").exists())

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
            declared = provider_args(root, self.cfg)
            bounded = runner.validate_provider(
                declared["provider_manifest"],
                declared["provider_manifest_sha256"],
                cutoff=self.cfg["split"]["test"][1],
            )
            inventory = {
                p: Path("qlib") / p.relative_to(declared["provider_manifest"].parent)
                for p in bounded["files"]
            }
            inventory[source] = Path("data.txt")
            with (
                patch.object(runner, "snapshot_files", return_value=inventory),
                patch.object(runner.subprocess, "check_output", return_value="commit"),
            ):
                runner.freeze(root, out, self.cfg, {"Id": "sha256:fixed"}, **declared)
            source.write_text("new live data")
            self.assertEqual((out / "snapshot/data.txt").read_text(), "original data")
            runner.verify(out)
            (out / "snapshot/data.txt").write_text("tampered")
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                runner.verify(out)

    def test_separate_runtime_supplies_data_while_code_stays_in_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "source"
            runtime = Path(temp).resolve() / "runtime"
            for dataset in ("6_ml_datasets/l1_factors", "1_kline_data/daily_backward"):
                path = runtime / "data/quantdb" / dataset / "dt=20240102/part.parquet"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"runtime data")
            for name in ("calendars/day.txt", "instruments/all.txt"):
                path = runtime / "db/qlib_data" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("runtime qlib")
            code = root / "backend/example.py"
            code.parent.mkdir(parents=True)
            code.write_text("# candidate code")
            declared = provider_args(runtime, self.cfg)
            files = runner.snapshot_files(root, self.cfg, data_root=runtime, **declared)
            self.assertEqual(files[code], Path("code/backend/example.py"))
            self.assertEqual(
                files[declared["provider_manifest"].parent / "calendars/day.txt"],
                Path("qlib/calendars/day.txt"),
            )
            self.assertEqual(
                sum(str(target).startswith("quantdb/") for target in files.values()), 2
            )
            self.assertFalse(
                any(str(source).startswith(str(root / "data")) for source in files)
            )

    def test_container_only_mounts_readonly_snapshot_and_output(self):
        cmd = runner.command(
            Path("/experiments/one"),
            {"image": {"Id": "sha256:fixed", "Os": "linux", "Architecture": "amd64"}},
            Path("/experiments/one/attempt-1"),
        )
        mounts = [cmd[i + 1] for i, value in enumerate(cmd) if value == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertIn("dst=/frozen,readonly", mounts[0])
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertIn("sha256:fixed", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("PYTHONHASHSEED=42", cmd)


if __name__ == "__main__":
    unittest.main()
