import importlib.util
import tempfile
import struct
import hashlib
import unittest
from datetime import date, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "frozen", Path(__file__).resolve().parents[2] / "scripts/run_frozen_research.py"
)
frozen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen)


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


class SnapshotDependencyTests(unittest.TestCase):
    def test_inventory_includes_loading_and_universe_history(self):
        for train_start, expected_start in (
            ("2026-01-01", "2025-08-04"),  # Short training needs earlier pool history.
            ("2025-05-01", "2025-04-01"),  # Long training keeps the loading buffer.
            ("2025-09-03", "2025-08-04"),  # Exactly 150 calendar days: same bound.
        ):
            with (
                self.subTest(train_start=train_start),
                tempfile.TemporaryDirectory() as d,
            ):
                root = Path(d)
                cfg = frozen.read(frozen.ROOT / "config/research_controls_cn_l1.json")
                cfg.update(
                    development_end="2026-03-24",
                    split={
                        "train": [train_start, "2026-01-31"],
                        "valid": ["2026-02-01", "2026-02-28"],
                        "test": ["2026-03-01", "2026-03-20"],
                    },
                )
                frozen.validate_config(
                    cfg
                )  # A short, ordered training split stays legal.
                lower = date.fromisoformat(expected_start)
                upper = date(2026, 3, 20)
                included = {
                    lower,
                    date.fromisoformat(train_start) - timedelta(days=30),
                    date(2025, 8, 4),  # 180 calendar days before this training end.
                    date(2026, 1, 31),
                    upper,
                }
                excluded = {
                    lower - timedelta(days=1),
                    upper + timedelta(days=1),
                    date(
                        2026, 3, 24
                    ),  # Policy cutoff does not extend the requested end.
                    date(2026, 3, 25),  # Invented holdout sentinel; never selected.
                }
                expected_files = set()
                for dataset in (
                    "6_ml_datasets/l1_factors",
                    "1_kline_data/daily_backward",
                ):
                    for day in included | excluded:
                        relative = Path(dataset) / f"dt={day:%Y%m%d}/a.parquet"
                        path = root / "data/quantdb" / relative
                        path.parent.mkdir(parents=True)
                        path.write_bytes(b"synthetic inventory only; not Parquet")
                        if day in included:
                            expected_files.add(Path("quantdb") / relative)
                selected = frozen.snapshot_files(root, cfg, **provider_args(root, cfg))
                self.assertEqual(
                    {p for p in selected.values() if p.parts[0] == "quantdb"},
                    expected_files,
                )
                self.assertEqual(frozen.snapshot_date_bounds(cfg), (lower, upper))

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
            cfg = {
                "development_end": "2025-02-02",
                "split": {
                    "train": ["2025-01-01", "2025-01-02"],
                    "test": ["2025-02-01", "2025-02-02"],
                },
            }
            inventory = frozen.snapshot_files(root, cfg, **provider_args(root, cfg))
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
            cfg = {
                "development_end": "2026-03-24",
                "split": {
                    "train": ["2026-01-01", "2026-01-31"],
                    "valid": ["2026-02-01", "2026-02-28"],
                    "test": ["2026-03-01", "2026-03-24"],
                },
            }
            selected = frozen.snapshot_files(root, cfg, **provider_args(root, cfg))
            market = [str(p) for p in selected.values() if p.parts[0] == "quantdb"]
            self.assertEqual(len(market), 4)
            self.assertTrue(all("20260323" in p or "20260324" in p for p in market))
            # An earlier test end also cannot be expanded up to the policy cutoff.
            cfg["split"]["test"][1] = "2026-03-23"
            market = [
                str(p)
                for p in frozen.snapshot_files(
                    root, cfg, **provider_args(root, cfg)
                ).values()
                if p.parts[0] == "quantdb"
            ]
            self.assertEqual(len(market), 2)
            self.assertTrue(all("20260323" in p for p in market))
            invalid = root / "data/quantdb/6_ml_datasets/l1_factors/dt=20260230"
            invalid.mkdir()
            with self.assertRaises(ValueError):
                frozen.snapshot_files(root, cfg, **provider_args(root, cfg))

    def test_boundary_is_required_and_every_split_is_bounded(self):
        cfg = {
            "split": {
                "train": ["2026-01-01", "2026-01-31"],
                "test": ["2026-03-01", "2026-03-24"],
            }
        }
        for cutoff in (None, "", "20260324", "2026-02-30", "2026-03-23"):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                frozen.snapshot_date_bounds({**cfg, "development_end": cutoff})
        cfg["development_end"] = "2026-03-24"
        cfg["split"]["valid"] = ["2026-02-01", "2026-03-25"]
        with self.assertRaisesRegex(ValueError, "outside development_end"):
            frozen.snapshot_date_bounds(cfg)


if __name__ == "__main__":
    unittest.main()
