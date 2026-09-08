"""Synthetic, offline runtime smoke: real LightGBM + Qlib/CnExchange, no live data.

Run in an ephemeral cloud image with network=none and only read-only code mounts.
This checks the execution environment, not market-data or strategy validity.
"""
import json
from pathlib import Path
import tempfile

import lightgbm as lgb
import numpy as np
import pandas as pd
import qlib

import frozen_research_worker as worker


def main():
    with tempfile.TemporaryDirectory(prefix="qm-runtime-smoke-") as directory:
        root = Path(directory)
        provider = root / "qlib"
        days = pd.bdate_range("2024-01-02", periods=30)
        symbols = ["SH600001", "SH600002", "SZ000001", "SH000300"]
        (provider / "calendars").mkdir(parents=True)
        (provider / "instruments").mkdir()
        (provider / "calendars/day.txt").write_text("\n".join(days.strftime("%Y-%m-%d")) + "\n")
        (provider / "instruments/all.txt").write_text("".join(
            f"{s}\t{days[0]:%Y-%m-%d}\t{days[-1]:%Y-%m-%d}\n" for s in symbols))
        rows = []
        for index, symbol in enumerate(symbols):
            folder = provider / "features" / symbol.lower()
            folder.mkdir(parents=True)
            close = 10 + index + np.arange(len(days)) * (index + 1) * .01
            fields = {"close": close, "open": close, "high": close + .1,
                      "low": close - .1, "volume": np.full(len(days), 1e7),
                      "factor": np.ones(len(days)), "change": np.r_[0, np.diff(close) / close[:-1]]}
            for field, values in fields.items():
                np.r_[0, values].astype("<f4").tofile(folder / f"{field}.day.bin")
            if symbol != "SH000300":
                rows.extend((day, symbol, float(index), float(i), .01 * (index + 1))
                            for i, day in enumerate(days))
        frame = pd.DataFrame(rows, columns=["datetime", "instrument", "x1", "x2", "label"])
        fit = frame[frame.datetime < days[9]]
        features = ["x1", "x2"]
        model = lgb.train({"objective": "regression", "num_threads": 2, "verbosity": -1,
                           "min_data_in_leaf": 2, "num_leaves": 3, "seed": 42},
                          lgb.Dataset(fit[features], label=fit.label), num_boost_round=5)
        model.save_model(str(root / "model.lgb"))
        restored = lgb.Booster(model_file=str(root / "model.lgb"))
        scores = model.predict(frame[features], num_threads=2)
        assert np.allclose(scores, restored.predict(frame[features], num_threads=2), atol=1e-12)
        assert np.isfinite(scores).all()
        qlib.init(provider_uri=str(provider), region="cn", kernels=1,
                  expression_cache=None, dataset_cache=None,
                  exp_manager={"class": "MLflowExpManager", "module_path": "qlib.workflow.expm",
                               "kwargs": {"uri": (root / "mlruns").as_uri(), "default_exp_name": "smoke"}})
        frame["score"] = scores
        worker.OUT = root
        cfg = {"split": {"test": [str(days[10].date()), str(days[19].date())]},
               "portfolio": {"initial_capital": 100000, "risk_degree": .8, "topk": 2,
                             "n_drop": 1, "benchmark": "SH000300"},
               "exchange": {"deal_price": "close", "limit_threshold": .095}}
        result = worker.run_portfolio("model", frame.set_index(["datetime", "instrument"])["score"], cfg, symbols[:3])
        assert result["trading_days"] == 10 and result["trades"] >= 2
        print(json.dumps({"synthetic_only": True, "training_rows": len(fit),
                          "model_reload_equal": True, "backtest": result}, indent=2))


if __name__ == "__main__":
    main()
