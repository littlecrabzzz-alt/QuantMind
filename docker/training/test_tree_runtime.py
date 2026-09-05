"""Run in the existing OSS image: python -m unittest discover -s /app/docker/training -p 'test_tree_runtime.py'."""
import builtins
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np


class TreeRuntimeTest(unittest.TestCase):
    def test_lightgbm_trains_when_torch_is_unavailable(self):
        original_import = builtins.__import__

        def without_torch(name, *args, **kwargs):
            if name == "torch" or name.startswith("torch."):
                raise ModuleNotFoundError("PyTorch deliberately unavailable", name="torch")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_torch):
            spec = importlib.util.spec_from_file_location("tree_runtime_check", Path(__file__).with_name("train.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            x = np.arange(1200, dtype=np.float32).reshape(600, 2) / 1200
            y = x[:, 0] * 0.1
            cfg = {"model": {"num_boost_round": 10, "early_stopping_rounds": 2,
                             "params": {"num_threads": 2, "min_data_in_leaf": 5}},
                   "label": {"target_mode": "return"}}
            model = module._train_lgb(cfg, ["a", "b"], x[:500], y[:500], x[500:], y[500:])
            predicted = model.predict(x[500:])
            self.assertEqual(predicted.shape, (100,))
            self.assertTrue(np.isfinite(predicted).all())


if __name__ == "__main__":
    unittest.main()
