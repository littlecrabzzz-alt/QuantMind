"""策略可见的行情数据。"""

from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


@dataclass
class MarketData:
    """保存对齐后的日频行情与成分。"""

    open: pd.DataFrame
    close: pd.DataFrame
    up_limit: pd.DataFrame
    down_limit: pd.DataFrame
    adj: pd.DataFrame
    volume: pd.DataFrame
    amount: pd.DataFrame
    suspended: pd.DataFrame
    is_st: pd.DataFrame
    list_date: pd.Series
    delist_date: pd.Series
    members: dict[str, pd.DataFrame]
    index_close: pd.DataFrame
    extra: dict[str, pd.DataFrame] = field(default_factory=dict)

    @property
    def calendar(self) -> pd.DatetimeIndex:
        """返回交易日历。"""
        return self.close.index

    def truncate(self, t: str | pd.Timestamp) -> "MarketData":
        """按日期切片，保留截至 t 的历史。"""
        stop = self.calendar.searchsorted(pd.Timestamp(t), side="right")
        return MarketData(
            **{
                name: getattr(self, name).iloc[:stop]
                for name in (
                    "open", "close", "up_limit", "down_limit", "adj", "volume",
                    "amount", "suspended", "is_st", "index_close",
                )
            },
            list_date=self.list_date,
            delist_date=self.delist_date,
            members={code: frame.iloc[:stop] for code, frame in self.members.items()},
            extra={name: frame.loc[:t] for name, frame in self.extra.items()},
        )

    def adj_close(self) -> pd.DataFrame:
        """返回前向填充后的后复权收盘价。"""
        return self.close.ffill() * self.adj.ffill()


def load_market_data(
    panel_dir: str | PathLike[str],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    universe: str | None = None,
) -> MarketData:
    """读取面板，并按最近一期历史快照对齐指数成分。"""
    panel = Path(panel_dir)
    calendar = pd.DatetimeIndex(pd.read_parquet(panel / "calendar.parquet")["date"])
    if start is not None:
        calendar = calendar[calendar >= pd.Timestamp(start)]
    if end is not None:
        calendar = calendar[calendar <= pd.Timestamp(end)]
    stocks = pd.read_parquet(panel / "stocks.parquet").set_index("code")
    snapshots = pd.read_parquet(panel / "index_members.parquet")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])

    if universe is not None:
        selected = snapshots[snapshots.index_code == universe]
        if selected.empty:
            raise ValueError(f"Unknown index universe: {universe}")
        if len(calendar):
            previous = selected.loc[selected.snapshot_date <= calendar[0], "snapshot_date"].max()
            lower = calendar[0] if pd.isna(previous) else previous
            selected = selected[(selected.snapshot_date >= lower) &
                                (selected.snapshot_date <= calendar[-1])]
        else:
            selected = selected.iloc[:0]
        codes = pd.Index(sorted(selected.code.unique()), name="code")
    else:
        # Include daily observations even if stock_basic has no matching row.
        observed = pq.read_table(panel / "daily.parquet", columns=["code"])["code"].unique().to_pylist()
        codes = pd.Index(sorted(set(stocks.index) | set(observed)), name="code")

    fields = ("open", "close", "up_limit", "down_limit", "adj", "volume",
              "amount", "suspended", "is_st")
    frames = {
        field: pd.DataFrame(
            np.zeros((len(calendar), len(codes)), dtype=bool) if field in ("suspended", "is_st")
            else np.full((len(calendar), len(codes)), np.nan),
            index=calendar, columns=codes,
        ) for field in fields
    }
    if len(calendar) and len(codes):
        table = pq.read_table(panel / "daily.parquet", columns=["date", "code", *fields],
            filters=[("date", ">=", calendar[0].date()),
                     ("date", "<=", calendar[-1].date()), ("code", "in", codes.tolist())])
        row = calendar.get_indexer(pd.DatetimeIndex(table["date"].to_numpy()))
        col = codes.get_indexer(table["code"].to_numpy())
        valid = (row >= 0) & (col >= 0)
        for field in fields:
            frames[field].values[row[valid], col[valid]] = table[field].to_numpy()[valid]
        del table

    list_date = pd.to_datetime(stocks.list_date.reindex(codes))
    delist_date = pd.to_datetime(stocks.delist_date.reindex(codes))
    if len(calendar) and len(codes):
        dates = calendar.to_numpy()[:, None]
        outside = ((dates < list_date.to_numpy()[None, :]) |
                   (dates >= delist_date.to_numpy()[None, :]))
        for field in ("open", "close"):
            frames[field].values[outside] = np.nan
        frames["suspended"].values[outside] = False

    members = {
        index_code: _member_frame(group, calendar, codes)
        for index_code, group in snapshots.groupby("index_code", sort=True)
    }
    index_daily = pd.read_parquet(panel / "index_daily.parquet", columns=["date", "index_code", "close"])
    index_daily["date"] = pd.to_datetime(index_daily["date"])
    index_close = index_daily.pivot(index="date", columns="index_code", values="close").reindex(calendar)
    extra = {}
    if (panel / "basic.parquet").exists():
        names = ["total_mv", "circ_mv", "pe_ttm", "pb", "dv_ttm", "turnover_rate_f"]
        if len(calendar) and len(codes):
            basic = pd.read_parquet(panel / "basic.parquet", columns=["date", "code", *names],
                filters=[("date", ">=", calendar[0].date()),
                         ("date", "<=", calendar[-1].date()), ("code", "in", codes.tolist())])
            basic["date"] = pd.to_datetime(basic["date"])
            extra = {name: basic.pivot(index="date", columns="code", values=name)
                     .reindex(index=calendar, columns=codes) for name in names}
        else:
            extra = {name: pd.DataFrame(index=calendar, columns=codes, dtype=float) for name in names}
    return MarketData(**frames, list_date=list_date, delist_date=delist_date,
                      members=members, index_close=index_close, extra=extra)


def _member_frame(snapshots, calendar, codes):
    """Expand complete snapshots; never fill individual membership bits forward."""
    dates = pd.DatetimeIndex(sorted(snapshots.snapshot_date.unique()))
    values = np.zeros((len(dates), len(codes)), dtype=bool)
    row = dates.get_indexer(snapshots.snapshot_date)
    col = codes.get_indexer(snapshots.code)
    valid = col >= 0
    values[row[valid], col[valid]] = True
    latest = dates.searchsorted(calendar, side="right") - 1
    result = np.zeros((len(calendar), len(codes)), dtype=bool)
    known = latest >= 0
    result[known] = values[latest[known]]
    return pd.DataFrame(result, index=calendar, columns=codes)
