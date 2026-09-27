"""Synthetic-only frozen boundary regression; no model fitting or real data reads."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from data.loading import load_data, read_development_range
from data.splits import _split_data


class DevelopmentBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.days = pd.bdate_range("2024-01-02", periods=60).delete([8, 29])
        self.cutoff = str(self.days[-1].date())
        self.cfg = {
            "development_end": self.cutoff,
            "label": {"target_horizon_days": 1},
            "split": {name: [str(self.days[a].date()), str(self.days[z].date())]
                      for name, a, z in (("train", 0, 17), ("valid", 18, 35), ("test", 36, 57))},
        }
        future = pd.bdate_range(self.days[-1] + pd.Timedelta(days=1), periods=5)
        self.source = pd.DataFrame([
            {"trade_date": day, "symbol": symbol, "volume": 100., "close": 100. + i,
             "factor": float(i), "mom_ret_1d": .01}
            for symbol in ("SH600000", "SH600001")
            for i, day in enumerate(self.days.append(future))
            if symbol == "SH600000" or i % 7 != 0
        ])
        self.source.loc[self.source.trade_date > self.cutoff, "close"] = 999999.

    def load(self, *, bounded=True, over_return=False):
        reader = Mock()
        reader.describe.return_value = SimpleNamespace(
            min_date=self.source.trade_date.min(), max_date=self.source.trade_date.max())

        def read(source, **kw):
            if bounded:
                self.assertLessEqual(pd.Timestamp(kw["end"]), pd.Timestamp(self.cutoff),
                                     "sentinel: attempted reserved-period read")
            if over_return:
                return self.source.copy()
            return self.source[self.source.trade_date.between(
                pd.Timestamp(kw["start"]), pd.Timestamp(kw["end"]))].copy()

        reader.read_range.side_effect = read
        with patch("backend.services.engine.data_platform.quantdb_factor_reader.QuantDBFactorReader",
                   return_value=reader):
            frame, _ = load_data(*self.cfg["split"]["train"], ["factor"],
                                 valid_end=self.cfg["split"]["valid"][1],
                                 test_end=self.cutoff, local_dir="/synthetic-only",
                                 factor_source="l1_factors",
                                 development_end=self.cutoff if bounded else None)
        return frame, reader

    def test_capped_read_and_sparse_labels_purged_in_all_segments(self):
        frame, reader = self.load()
        self.assertEqual(str(reader.read_range.call_args.kwargs["end"]), self.cutoff)
        self.assertLessEqual(frame._label_end_date.max(), pd.Timestamp(self.cutoff))
        splits = _split_data(frame, self.cfg)
        for name, part in zip(("train", "valid", "test"), splits, strict=True):
            end = pd.Timestamp(self.cfg["split"][name][1])
            self.assertTrue((part._label_end_date <= end).all())
            self.assertEqual(part.attrs["label_purge"]["rows_after"], len(part))
        self.assertGreater(splits[0].attrs["label_purge"]["rows_removed"], 0)
        self.assertGreater(splits[1].attrs["label_purge"]["rows_removed"], 0)
        # The loader already discarded missing final labels. Do not purge again
        # against the last FEATURE date and silently discard two extra days.
        self.assertEqual(splits[2]._label_end_date.max(), pd.Timestamp(self.cutoff))
        self.assertEqual(splits[2].attrs["label_purge"]["rows_removed"], 0)

    def test_reader_over_return_is_rejected_before_label_construction(self):
        with self.assertRaisesRegex(ValueError, "returned dates outside development_end"):
            self.load(over_return=True)

    def test_frozen_all_unknown_volume_date_cannot_be_silently_dropped(self):
        day = self.days[5]
        mask = self.source.trade_date == day
        original = self.source.loc[mask, "volume"].copy()
        self.source.loc[mask, "volume"] = float("nan")
        with self.assertRaisesRegex(ValueError, "Frozen volume unknown on 1 dates"):
            self.load()
        # Ordinary training remains unchanged; this is a frozen-scope guard.
        ordinary, _ = self.load(bounded=False)
        self.assertNotIn(day, ordinary.trade_date.tolist())
        self.source.loc[mask, "volume"] = original
        # Partial unknown volume is not sufficient evidence to delete the day.
        self.source.loc[mask & (self.source.symbol == "SH600000"), "volume"] = float("nan")
        partial, _ = self.load()
        self.assertIn(day, partial.trade_date.tolist())

    def test_description_is_bounded_and_source_start_is_still_clamped(self):
        _, reader = self.load()
        self.assertEqual(reader.describe.call_args.args, ("l1_factors",))
        self.assertEqual(
            reader.describe.call_args.kwargs,
            {
                "start": (pd.Timestamp(self.cfg["split"]["train"][0])
                          - pd.Timedelta(days=7)).date(),
                "end": pd.Timestamp(self.cutoff).date(),
            },
        )
        self.assertEqual(
            pd.Timestamp(reader.read_range.call_args.kwargs["start"]),
            self.source.trade_date.min(),
        )
        _, ordinary = self.load(bounded=False)
        ordinary.describe.assert_called_once_with("l1_factors")

    def test_bounded_description_never_samples_future_only_donor(self):
        from backend.services.engine.data_platform.quantdb_factor_reader import (
            QuantDBFactorReader,
        )

        class StopAtRange(Exception):
            pass

        original_schema = QuantDBFactorReader._sample_schema_relation
        sampled = []

        def schema(files):
            sampled.extend(files)
            return original_schema(files)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            allowed = root / "6_ml_datasets/ccass_factors/dt=20260324/data.parquet"
            allowed.parent.mkdir(parents=True)
            pd.DataFrame([{
                "symbol": "600001.SH", "date": "2026-03-24", "factor": 1.0,
            }]).to_parquet(allowed, index=False)
            future = root / "6_ml_datasets/l1_factors/dt=20260325/future.parquet"
            future.parent.mkdir(parents=True)
            future.write_bytes(b"FUTURE_DONOR_FOOTER_MUST_NOT_BE_OPENED")
            with patch.object(QuantDBFactorReader, "_sample_schema_relation",
                              side_effect=schema), \
                 patch.object(QuantDBFactorReader, "read_range",
                              side_effect=StopAtRange) as read:
                with self.assertRaises(StopAtRange):
                    load_data(
                        "2026-03-24", "2026-03-24", ["factor"],
                        local_dir=str(root), quantdb_dir=str(root),
                        factor_source="ccass_factors", development_end="2026-03-24",
                    )
            self.assertEqual(sampled, [allowed])
            self.assertEqual(str(read.call_args.kwargs["start"]), "2026-03-24")
            self.assertEqual(str(read.call_args.kwargs["end"]), "2026-03-24")

    def test_worker_reader_guard_rejects_outside_request_before_io(self):
        reader = Mock()
        for boundary in (None, "", "NaT", "2024-03-25T00:00:00"):
            with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                read_development_range(reader, "l1_factors", development_end=boundary,
                                       features=["factor"], start="2024-01-02", end=self.cutoff)
        with self.assertRaisesRegex(ValueError, "request outside development_end"):
            read_development_range(reader, "l1_factors", development_end=self.cutoff,
                                   features=["factor"], start="2024-01-02", end="2030-01-01")
        reader.read_range.assert_not_called()

    def test_model_test_tail_is_purged_even_if_supplied_labels_cross_boundary(self):
        # Existing ordinary training permits a future label buffer. Feed its
        # date provenance into the frozen splitter to catch the original bug.
        frame, reader = self.load(bounded=False)
        self.assertGreater(pd.Timestamp(reader.read_range.call_args.kwargs["end"]),
                           pd.Timestamp(self.cutoff))
        self.assertTrue((frame._label_end_date > self.cutoff).any())
        *_, test = _split_data(frame, self.cfg)
        self.assertTrue((test._label_end_date <= self.cutoff).all())
        self.assertGreater(test.attrs["label_purge"]["rows_removed"], 0)
        ordinary = copy.deepcopy(self.cfg)
        ordinary.pop("development_end")
        self.assertTrue((_split_data(frame, ordinary)[2]._label_end_date > self.cutoff).any())

    def test_missing_provenance_unbounded_source_and_bad_split_fail_closed(self):
        frame, _ = self.load()
        with self.assertRaisesRegex(ValueError, "label end dates"):
            _split_data(frame.drop(columns="_label_end_date"), self.cfg)
        with self.assertRaisesRegex(ValueError, "bounded direct factor source"):
            load_data("2024-01-02", "2024-02-01", ["factor"],
                      local_dir="/must-not-read", development_end=self.cutoff)
        with patch("backend.services.engine.data_platform.quantdb_factor_reader.QuantDBFactorReader") as factory:
            with self.assertRaisesRegex(ValueError, "split exceeds development_end"):
                load_data("2024-01-02", "2030-01-01", ["factor"], factor_source="l1_factors",
                          local_dir="/must-not-read", development_end=self.cutoff)
            factory.assert_not_called()

    def test_frozen_worker_requires_boundary_before_any_market_or_model_call(self):
        import frozen_research_worker as worker

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = copy.deepcopy(self.cfg)
            missing.pop("development_end")
            outside = copy.deepcopy(self.cfg)
            outside["split"]["test"][1] = "2030-01-01"
            for cfg in (missing, outside):
                (root / "config.json").write_text(json.dumps(cfg))
                with self.subTest(config=cfg), patch.object(worker, "FROZEN", root), \
                     patch.object(worker.train, "__file__", str(root / "code/train.py")), \
                     patch.object(worker.qlib, "init") as init, \
                     patch.object(worker, "QuantDBFactorReader") as reader, \
                     patch.object(worker.train, "_train_single_model") as model:
                    with self.assertRaisesRegex(ValueError, "development_end"):
                        worker.main()
                    init.assert_not_called()
                    reader.assert_not_called()
                    model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
