import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "frozen", Path(__file__).resolve().parents[2] / "scripts/run_frozen_research.py"
)
frozen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen)


class SnapshotDependencyTests(unittest.TestCase):
    def test_training_subpackages_are_part_of_frozen_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for relative in (
                "data/quantdb/6_ml_datasets/l1_factors/dt=20250101/a.parquet",
                "data/quantdb/1_kline_data/daily_backward/dt=20250101/a.parquet",
                "db/qlib_data/calendars/day.txt",
                "db/qlib_data/instruments/all.txt",
                "docker/training/train.py",
                "docker/training/model_trainers/__init__.py",
                "docker/training/model_trainers/metrics.py",
                "docker/training/data/loading.py",
                "docker/training/diagnostics/drift.py",
            ):
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("")
            inventory = frozen.snapshot_files(
                root,
                {
                    "development_end": "2025-02-02",
                    "split": {
                        "train": ["2025-01-01", "2025-01-02"],
                        "test": ["2025-02-01", "2025-02-02"],
                    }
                },
            )
            for relative in (
                "model_trainers/__init__.py",
                "model_trainers/metrics.py",
                "data/loading.py",
                "diagnostics/drift.py",
            ):
                self.assertIn(
                    Path("code/docker/training") / relative, inventory.values()
                )

    def test_quantdb_inventory_stops_at_requested_end(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for dataset in ("6_ml_datasets/l1_factors", "1_kline_data/daily_backward"):
                for day in ("20260323", "20260324", "20260325", "20260420"):
                    path = root / "data/quantdb" / dataset / f"dt={day}/a.parquet"
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"synthetic inventory only; never open as Parquet")
            for name in ("calendars/day.txt", "instruments/all.txt"):
                path = root / "db/qlib_data" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            cfg = {"development_end": "2026-03-24", "split": {
                "train": ["2026-01-01", "2026-01-31"],
                "valid": ["2026-02-01", "2026-02-28"],
                "test": ["2026-03-01", "2026-03-24"],
            }}
            selected = frozen.snapshot_files(root, cfg)
            market = [str(p) for p in selected.values() if p.parts[0] == "quantdb"]
            self.assertEqual(len(market), 4)
            self.assertTrue(all("20260323" in p or "20260324" in p for p in market))
            # An earlier test end also cannot be expanded up to the policy cutoff.
            cfg["split"]["test"][1] = "2026-03-23"
            market = [str(p) for p in frozen.snapshot_files(root, cfg).values()
                      if p.parts[0] == "quantdb"]
            self.assertEqual(len(market), 2)
            self.assertTrue(all("20260323" in p for p in market))
            invalid = root / "data/quantdb/6_ml_datasets/l1_factors/dt=20260230"
            invalid.mkdir()
            with self.assertRaises(ValueError):
                frozen.snapshot_files(root, cfg)

    def test_boundary_is_required_and_every_split_is_bounded(self):
        cfg = {"split": {"train": ["2026-01-01", "2026-01-31"],
                         "test": ["2026-03-01", "2026-03-24"]}}
        for cutoff in (None, "", "20260324", "2026-02-30", "2026-03-23"):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                frozen.snapshot_date_bounds({**cfg, "development_end": cutoff})
        cfg["development_end"] = "2026-03-24"
        cfg["split"]["valid"] = ["2026-02-01", "2026-03-25"]
        with self.assertRaisesRegex(ValueError, "outside development_end"):
            frozen.snapshot_date_bounds(cfg)


if __name__ == "__main__":
    unittest.main()
