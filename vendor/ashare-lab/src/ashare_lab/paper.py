"""纸面前向模拟：冻结账户、重放核验及只追加账本，无外部交易接口。"""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile

import pandas as pd

from . import metrics
from .benchmark import alpha_beta
from .engine import BacktestConfig, run_backtest
from .strategy import Strategy


class LedgerMismatch(Exception):
    """冻结参数或已落盘历史与本次重放不一致。"""


class InceptionRebalance(Strategy):
    def __init__(self, base, inception, open_days=None):
        self.base = base
        self.inception = pd.Timestamp(inception)
        self.open_days = (None if open_days is None else
                          pd.DatetimeIndex(open_days).drop_duplicates().sort_values())

    @property
    def name(self):
        return self.base.name

    def target_weights(self, t, data):
        return self.base.target_weights(t, data)

    def exposure(self, t, data):
        return self.base.exposure(t, data)

    def rebalance_dates(self, calendar):
        calendar = pd.DatetimeIndex(calendar)
        dates = pd.DatetimeIndex(self.base.rebalance_dates(calendar))
        dates = dates[dates > self.inception]
        if len(calendar) and calendar[-1] in dates:
            last = calendar[-1]
            if self.open_days is None:
                raise ValueError("Paper execution requires a real exchange calendar")
            future = self.open_days[self.open_days > last]
            if not len(future):
                raise ValueError("Exchange calendar must extend beyond the last session")
            following = future[0]
            if following is None or following.to_period("M") == last.to_period("M"):
                dates = dates[dates != last]
        if self.inception in calendar:
            dates = dates.union(pd.DatetimeIndex([self.inception]))
        return dates.drop_duplicates().sort_values()


class _SignalRecorder(Strategy):
    """记录引擎已执行的信号调用，不重复调用有状态策略。"""

    def __init__(self, base):
        self.base = base
        self.weights = pd.Series(dtype=float)
        self.last_exposure = 1.0
        self.pending = None

    def rebalance_dates(self, calendar):
        return self.base.rebalance_dates(calendar)

    def exposure(self, t, data):
        exposure = float(self.base.exposure(t, data))
        self.pending = (self.weights * exposure
                        if exposure != self.last_exposure else None)
        self.last_exposure = exposure
        return exposure

    def target_weights(self, t, data):
        self.weights = self.base.target_weights(t, data).astype(float).copy()
        self.pending = self.weights * self.last_exposure
        return self.weights


def simulate(strategy, data, inception, end, initial_cash, costs):
    recorder = _SignalRecorder(strategy)
    result = run_backtest(recorder, data, BacktestConfig(
        start=inception, end=end, initial_cash=initial_cash, costs=costs,
    ))
    pending = recorder.pending
    if pending is not None:
        pending = pending[pending > 0].copy()
    return result, pending


def _publish(contents):
    """全部内容先落临时文件，再逐文件原子替换；调用前必须完成所有核验。"""
    staged = []
    try:
        for path, content in contents.items():
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                             delete=False) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, path))
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def init_account(directory, meta):
    directory = Path(directory)
    path = directory / "meta.json"
    expected = {k: v for k, v in meta.items() if k != "created_at"}
    # JSON round-trip also normalizes tuples and verifies serializability.
    expected = json.loads(json.dumps(expected, allow_nan=False))
    if path.exists():
        saved = json.loads(path.read_text())
        saved.pop("created_at", None)
        if saved != expected:
            for key in sorted(saved.keys() | expected.keys()):
                if saved.get(key) != expected.get(key) or (key in saved) != (key in expected):
                    raise LedgerMismatch(
                        f"meta.{key}: 旧值={saved.get(key)!r}, 新值={expected.get(key)!r}")
        return
    directory.mkdir(parents=True, exist_ok=True)
    expected["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _publish({path: (json.dumps(expected, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n").encode()})


_COLUMNS = {
    "nav": ["date", "nav", "cash", "exposure"],
    "positions": ["date", "code", "shares"],
    "trades": ["date", "code", "side", "shares", "price", "value", "fee"],
    "targets": ["date", "code", "weight"],
}


def _read_frames(directory):
    frames = {}
    for name, columns in _COLUMNS.items():
        path = directory / f"{name}.csv"
        frame = pd.read_csv(path, dtype={"code": str, "side": str},
                            float_precision="round_trip", keep_default_na=False)
        if list(frame.columns) != columns:
            raise LedgerMismatch(f"{path.name} 字段: 旧值={list(frame.columns)}, 新值={columns}")
        frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d")
        for column in set(columns) - {"date", "code", "side"}:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        if "shares" in frame:
            # 引擎的除权乘法可以产生碎股，必须无损保存；整股列返回 int。
            if (frame.shares % 1 == 0).all():
                frame["shares"] = frame.shares.astype("int64")
        frames[name] = frame
    return frames


def read_ledger(directory):
    directory = Path(directory)
    frames = _read_frames(directory)
    frames["nav"] = frames["nav"].set_index("date")
    return {"meta": json.loads((directory / "meta.json").read_text()), **frames}


def _nonzero_rows(wide, value):
    rows = [(date, code, quantity) for date, row in wide.iterrows()
            for code, quantity in row.items() if quantity != 0]
    return pd.DataFrame(rows, columns=["date", "code", value]).sort_values(
        ["date", "code"], kind="stable").reset_index(drop=True)


def _mismatch(date, field, old, new):
    raise LedgerMismatch(f"{pd.Timestamp(date):%Y-%m-%d} {field}: 旧值={old!r}, 新值={new!r}")


def append_ledger(directory, result):
    directory = Path(directory)
    dates = pd.DatetimeIndex(result.nav.index)
    if dates.empty or not dates.is_unique or not dates.is_monotonic_increasing:
        raise LedgerMismatch("result.nav 日期须非空、升序且唯一")
    frames = {
        "nav": pd.DataFrame({"nav": result.nav, "cash": result.cash,
                             "exposure": result.exposure}).rename_axis("date").reset_index(),
        "positions": _nonzero_rows(result.positions, "shares"),
        "trades": result.trades[_COLUMNS["trades"]].copy().reset_index(drop=True),
        "targets": _nonzero_rows(result.target, "weight"),
    }
    paths = {name: directory / f"{name}.csv" for name in frames}
    exists = [path.exists() for path in paths.values()]
    old_dates = pd.DatetimeIndex([])
    if any(exists):
        if not all(exists):
            raise LedgerMismatch("账本文件不完整: 缺少 " + ", ".join(
                path.name for path in paths.values() if not path.exists()))
        try:
            old = _read_frames(directory)
        except LedgerMismatch:
            raise
        except (ValueError, TypeError, pd.errors.ParserError) as exc:
            raise LedgerMismatch(f"账本无法读取: {exc}") from exc
        old_dates = pd.DatetimeIndex(old["nav"].date)
        for i, date in enumerate(old_dates):
            if i >= len(dates) or date != dates[i]:
                _mismatch(date, "nav.date 前缀", date,
                          dates[i] if i < len(dates) else "缺失")
        for name, frame in old.items():
            outside = frame.loc[~frame.date.isin(old_dates)]
            if not outside.empty:
                _mismatch(outside.iloc[0].date, name + ".date", outside.iloc[0].date, "不在 nav 中")
        grouped_old = {name: {d: g for d, g in frame.groupby("date", sort=False)}
                       for name, frame in old.items()}
        grouped_new = {name: {d: g for d, g in frame.groupby("date", sort=False)}
                       for name, frame in frames.items()}
        for date in old_dates:
            for name, columns in _COLUMNS.items():
                left = grouped_old[name].get(date, old[name].iloc[:0])
                right = grouped_new[name].get(date, frames[name].iloc[:0])
                if name in ("positions", "targets"):
                    left = left.sort_values("code", kind="stable")
                    right = right.sort_values("code", kind="stable")
                if len(left) != len(right):
                    _mismatch(date, name + ".rows", left.to_dict("records"), right.to_dict("records"))
                for a, b in zip(left.itertuples(index=False, name=None),
                                right.itertuples(index=False, name=None)):
                    for field, x, y in zip(columns, a, b):
                        equal = (x == y if field in ("date", "code", "side", "shares") else
                                 math.isclose(x, y, rel_tol=1e-8, abs_tol=0.0))
                        if not equal:
                            _mismatch(date, f"{name}.{field}" +
                                      (f"[{a[1]}]" if "code" in columns else ""), x, y)
    new_dates = dates[len(old_dates):].tolist()
    if not new_dates:
        return {"new_dates": [], "last_date": dates[-1]}
    contents = {}
    for name, frame in frames.items():
        path = paths[name]
        added = frame.loc[frame.date.isin(new_dates)].copy()
        added["date"] = pd.to_datetime(added.date).dt.strftime("%Y-%m-%d")
        previous = path.read_bytes() if path.exists() else b""
        if previous and added.empty:
            continue
        contents[path] = previous + added.to_csv(
            index=False, header=not bool(previous), float_format=lambda value: repr(float(value)),
        ).encode()
    directory.mkdir(parents=True, exist_ok=True)
    # nav is the date watermark: publish it last.
    contents = dict(sorted(contents.items(), key=lambda item: item[0].name == "nav.csv"))
    _publish(contents)
    return {"new_dates": new_dates, "last_date": dates[-1]}


def account_summary(nav, trades, benchmarks):
    days = len(nav) - 1
    traded = trades.loc[trades.side.isin(["buy", "sell"])]
    result = {
        "days": days,
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1),
        **{name: getattr(metrics, name)(nav) for name in
           ("cagr", "max_drawdown", "sharpe", "ann_vol")},
        "turnover": float(traded.value.sum() / 2 / nav.mean() *
                          (252 / days if days > 0 else float("nan"))),
        "cost": float(trades.fee.sum()),
    }
    for name in benchmarks:
        aligned = pd.concat([nav.rename("nav"), benchmarks[name].rename("bench")],
                            axis=1, join="inner").dropna()
        result[f"{name}:return"] = (float(aligned.bench.iloc[-1] / aligned.bench.iloc[0] - 1)
                                    if len(aligned) else float("nan"))
        result.update({f"{name}:{key}": value
                       for key, value in alpha_beta(nav, benchmarks[name]).items()})
    return result
