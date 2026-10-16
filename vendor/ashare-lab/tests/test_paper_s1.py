"""S1 更新入口建账与重放幂等性（合成行情，无归档写入）。"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.paper import update_s1
from synth import make_data, refresh_limits


def test_update_builds_and_replays_without_duplicate_rows(tmp_path, monkeypatch):
    dates = pd.bdate_range("2025-01-01", periods=330)
    inception = dates[-3].strftime("%Y-%m-%d")
    rng = np.random.default_rng(0)
    data = make_data(dates, ["A", "B"])
    data.members["000906.SH"] = data.members["IDX"].copy()
    for code in data.close:
        data.close[code] = 10 * np.exp(np.cumsum(rng.normal(0, .01, len(dates))))
        data.open[code] = data.close[code].shift(1).fillna(10)
    data.amount[:] = 1e9
    refresh_limits(data)
    etfs = {}
    for code, initial, sigma in (("511010.SH", 100, .002), ("518880.SH", 5, .01)):
        close = pd.Series(initial * np.exp(np.cumsum(rng.normal(0, sigma, len(dates)))), index=dates)
        etfs[code] = pd.DataFrame({"open": close.shift(1).fillna(close), "close": close,
                                  "adj": 1., "amount": 1e9, "volume": 1e7})
    panel = tmp_path / "data/live/panel"
    panel.mkdir(parents=True)
    (panel / "build_meta.json").write_text(json.dumps({"release_id": "synthetic-release"}))
    pd.DataFrame({"code": ["A", "B"], "name": ["股票甲", "股票乙"]}).to_parquet(panel / "stocks.parquet")
    monkeypatch.setattr(update_s1, "ROOT", tmp_path)
    monkeypatch.setattr(update_s1, "load_market_data", lambda *a, **kw: data)
    monkeypatch.setattr(update_s1, "load_etf_frames", lambda *a: etfs)
    monkeypatch.setattr(update_s1, "exchange_days", lambda *a: (dates.append(pd.DatetimeIndex([dates[-1] + pd.offsets.BDay()])), None))
    root = tmp_path / "dryrun"
    monkeypatch.setattr(sys, "argv", ["update_s1.py", "--ledger-root", str(root), "--inception", inception])
    assert update_s1.main() == 0
    account = root / "s1_invvol_etf"
    saved = {path.name: path.read_bytes() for path in account.iterdir()}
    nav = pd.read_csv(account / "nav.csv")
    assert len(nav) == 3 and nav.date.is_unique
    positions = pd.read_csv(account / "positions.csv")
    assert set(update_s1.SLEEVES.values()) <= set(positions.code)
    report = (root / "s1_latest.md").read_text()
    assert all(name in report for name in (*update_s1.ETF_NAMES.values(), "股票甲", "股票乙"))
    assert update_s1.main() == 0
    assert saved == {path.name: path.read_bytes() for path in account.iterdir()}
