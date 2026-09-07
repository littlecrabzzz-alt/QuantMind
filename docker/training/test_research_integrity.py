"""Focused research regressions; run with unittest in the existing OSS image."""
from pathlib import Path
from contextlib import nullcontext
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import train


class ResearchIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep research fixtures and fitted ensemble artifacts for inspection.
        cls.output = Path(os.getenv("QM_RESEARCH_TEST_OUTPUT") or tempfile.mkdtemp(prefix="quantmind-research-"))
        cls.output.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        rng = np.random.default_rng(42)
        dates = pd.bdate_range("2022-01-03", periods=400)
        self.df = pd.DataFrame({
            "trade_date": np.repeat(dates, 12),
            "symbol": np.tile([f"SH{600000+i}" for i in range(12)], len(dates)),
            "factor": rng.normal(size=len(dates) * 12),
        })
        self.df["label"] = self.df["factor"] * 0.2 + rng.normal(size=len(self.df))
        self.cfg = {
            "label": {"target_horizon_days": 5},
            "model": {"type": "lightgbm", "num_boost_round": 5,
                      "early_stopping_rounds": 2, "params": {"num_threads": 2}},
            "split": {"train": [str(dates[0].date()), str(dates[279].date())],
                      "valid": [str(dates[280].date()), str(dates[339].date())],
                      "test": [str(dates[340].date()), str(dates[-1].date())]},
        }

    def assert_labels_before(self, full, earlier, later):
        ends = full.sort_values(["symbol", "trade_date"]).groupby("symbol")["trade_date"].shift(-6)
        self.assertTrue((ends.loc[earlier.index] < later["trade_date"].min()).all())

    def test_sparse_stock_and_short_segment_purge(self):
        sparse = self.df[(self.df["symbol"] != "SH600000") | (self.df.index % 60 == 0)]
        earlier = sparse[sparse["trade_date"] < self.df["trade_date"].unique()[80]]
        later = sparse[sparse["trade_date"] >= self.df["trade_date"].unique()[80]]
        purged = train._purge_label_tail(earlier, self.cfg)
        self.assert_labels_before(sparse, purged, later)
        self.assertTrue(train._purge_label_tail(self.df.iloc[:60], self.cfg).empty)

    def test_recorded_rank_label_end_rejects_cross_section_leak(self):
        frame = self.df.iloc[:120].copy()
        frame["_label_end_date"] = frame["trade_date"]
        # One sparse stock can make every rank label on a date depend on later prices.
        day = frame["trade_date"].iloc[0]
        frame.loc[frame["trade_date"] == day, "_label_end_date"] = pd.Timestamp("2030-01-01")
        result = train._purge_label_tail(frame, self.cfg)
        self.assertFalse((result["trade_date"] == day).any())
        self.assertEqual(len(result), 108)

    def test_load_tracks_rank_label_dates_and_does_not_shift_across_stocks(self):
        source = self.df.iloc[:240].copy()
        source = source[(source["symbol"] != "SH600000") | (source.index % 36 == 0)]
        source["mom_ret_1d"] = 0.01
        source["volume"] = 100
        source.to_parquet(self.output / "model_features_core.parquet", index=False)
        expected = source.sort_values(["symbol", "trade_date"])
        expected["_label_end_date"] = expected.groupby("symbol")["trade_date"].shift(-6)
        expected = expected.dropna(subset=["_label_end_date"])
        expected["_label_end_date"] = expected.groupby("trade_date")["_label_end_date"].transform("max")
        loaded, _ = train.load_data("2022-01-03", "2022-01-28", ["factor"],
                                    target_horizon_days=5, local_dir=str(self.output))
        self.assertEqual(len(loaded), len(expected))
        joined = loaded.merge(expected, on=["symbol", "trade_date"], suffixes=("_actual", "_expected"))
        self.assertTrue((joined["_label_end_date_actual"] == joined["_label_end_date_expected"]).all())

    def test_wfa_purges_labels_and_uses_separate_early_stopping(self):
        wfa = {"strategy": "rolling", "train_years": 1, "val_months": 1,
               "step_months": 1, "start": "2022-01-03"}
        earlier, later = train._wfa_split_window(self.df, wfa, 0, self.cfg)
        self.assert_labels_before(self.df, earlier, later)
        with patch.object(train, "_prepare_arrays", wraps=train._prepare_arrays) as prepare:
            result = train._train_wfa_single(self.cfg, ["factor"], earlier, later, wfa, 0)
        self.assertIsNotNone(result)
        fit, stop = prepare.call_args.args[:2]
        self.assert_labels_before(self.df, fit, stop)
        self.assert_labels_before(self.df, stop, later)
        self.assertEqual(result["evaluation_role"], "held_out_window")

    def test_real_stacking_daily_metrics_and_oof_separation(self):
        self.df.to_parquet(self.output / "stacking-input.parquet", index=False)
        (self.output / "config.json").write_text(json.dumps(self.cfg, indent=2))
        with nullcontext(str(self.output)) as temp:
            def output_path(value):
                return Path(temp) / Path(value).name if str(value).startswith("/workspace/") else Path(value)

            original = train._train_single_model
            calls = []

            def record(model_type, fit, stop, holdout, *args, **kwargs):
                calls.append((fit, stop, holdout))
                return original(model_type, fit, stop, holdout, *args, **kwargs)

            with patch.object(train, "Path", side_effect=output_path), patch.object(train, "_train_single_model", side_effect=record):
                result = train.train_stacking(self.df, ["factor"], self.cfg,
                                              ["lightgbm", "linear"], n_folds=2)
            self.assertEqual(len(calls), 6)
            for fit, stop, holdout in calls:
                self.assertLess(fit["trade_date"].max(), stop["trade_date"].min())
                self.assertLess(stop["trade_date"].max(), holdout["trade_date"].min())
            test = result["split_frames"]["test"].merge(result["pred_df"], on=["symbol", "trade_date"])
            daily = test.groupby("trade_date").apply(
                lambda group: group["label"].corr(group["pred"], method="spearman"),
                include_groups=False,
            )
            expected = daily.mean() / (daily.std(ddof=0) + 1e-9)
            self.assertAlmostEqual(result["test_ensemble_m"]["rank_icir"], expected)
            scaled = train._compute_metrics(test, test["label"].values, test["pred"].values * 0.01)
            self.assertAlmostEqual(scaled["rank_icir"], expected)
            self.assertTrue((Path(temp) / "oof_predictions.parquet").exists())
            (self.output / "stacking-metrics.json").write_text(json.dumps(result["test_ensemble_m"], indent=2))


if __name__ == "__main__":
    unittest.main()
