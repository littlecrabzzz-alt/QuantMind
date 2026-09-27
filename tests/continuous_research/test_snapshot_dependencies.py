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


if __name__ == "__main__":
    unittest.main()
