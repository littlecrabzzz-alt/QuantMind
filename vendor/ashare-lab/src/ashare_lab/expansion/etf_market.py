"""将指定归档 release 的 ETF 日线并入可撮合行情；只写本地派生缓存。"""

from dataclasses import replace
import json

import duckdb
import pandas as pd

from ashare_lab.data.build import SOURCE
from ashare_lab.expansion.assets import CACHE


def with_etfs(data, frames):
    """按股票交易日历对齐，缺失开盘不能用前收替代。"""
    fields = ("open", "close", "adj", "amount", "volume", "suspended",
              "is_st", "up_limit", "down_limit")
    added = {field: {} for field in fields}
    listings = {}
    for code, frame in frames.items():
        aligned = frame.reindex(data.calendar)
        for field in ("open", "close", "adj", "amount", "volume"):
            added[field][code] = aligned[field]
        added["suspended"][code] = aligned.open.isna() | aligned.close.isna()
        added["is_st"][code] = pd.Series(False, index=data.calendar)
        previous = aligned.close.ffill().shift(1)
        added["up_limit"][code] = previous * 1.1
        added["down_limit"][code] = previous * 0.9
        listings[code] = aligned.close.first_valid_index() or pd.NaT

    def combine(original, extra):
        return pd.concat([original.drop(columns=list(frames), errors="ignore"), extra], axis=1)

    return replace(data, **{
        field: combine(getattr(data, field), pd.DataFrame(added[field], index=data.calendar))
        for field in fields
    }, list_date=pd.concat([data.list_date.drop(list(frames), errors="ignore"),
                            pd.Series(listings, dtype="datetime64[ns]")]),
        delist_date=pd.concat([data.delist_date.drop(list(frames), errors="ignore"),
                               pd.Series(pd.NaT, index=list(frames), dtype="datetime64[ns]")]),
        members={name: combine(frame, pd.DataFrame(False, index=frame.index,
                                                   columns=list(frames)))
                 for name, frame in data.members.items()})


def load_etf_frames(codes, calendar, release_id):
    """按 source_ts_code 读取指定 release，同代码日期保留最新抓取行。"""
    codes = tuple(dict.fromkeys(codes))
    if not codes:
        return {}
    if not release_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in release_id):
        raise ValueError("无效 release_id")
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"etf_{release_id[:12]}.parquet"
    saved = pd.read_parquet(cache) if cache.exists() else pd.DataFrame()
    if not saved.empty and set(saved.release_id) != {release_id}:
        raise ValueError("ETF 缓存 release_id 前缀冲突")
    known = set(saved.code) if not saved.empty else set()
    missing = [code for code in codes if code not in known]
    if missing:
        manifest = json.loads((SOURCE / "releases" / release_id / "manifest.json").read_text())
        paths = {api: [str(SOURCE / item["path"]) for item in manifest["datasets"]
                       if item["api_name"] == api] for api in ("fund_daily", "fund_adj")}
        tables = {}
        with duckdb.connect() as con:
            con.execute("SET threads = 4")
            con.execute("SET memory_limit = '1GB'")
            for api, fields in (("fund_daily", "open, close, amount * 1000.0 AS amount, vol * 100.0 AS volume"),
                                ("fund_adj", "adj_factor AS adj")):
                batches = []
                for offset in range(0, len(paths[api]), 512):
                    query = (f"SELECT source_ts_code AS code, trade_date, {fields}, "
                             "_fetched_at::TIMESTAMPTZ AS _fetched_at "
                             "FROM read_parquet(?, union_by_name=true, hive_partitioning=false) "
                             f"WHERE source_ts_code IN ({','.join('?' for _ in missing)})")
                    batches.append(con.execute(query, [paths[api][offset:offset + 512], *missing]).df())
                    print(f"{api}: {min(offset + 512, len(paths[api]))}/{len(paths[api])} files", flush=True)
                if not batches:
                    raise ValueError(f"release {release_id} 缺少 {api}")
                frame = pd.concat(batches, ignore_index=True).sort_values(
                    "_fetched_at", na_position="first", kind="stable").drop_duplicates(
                    ["code", "trade_date"], keep="last")
                frame["date"] = pd.to_datetime(frame.trade_date.astype(str), format="%Y%m%d")
                tables[api] = frame.drop(columns=["trade_date", "_fetched_at"])
        for code in missing:
            if any(code not in set(frame.code) for frame in tables.values()):
                raise ValueError(f"release {release_id} 缺少 {code} 行情或复权因子")
        new = tables["fund_daily"].merge(tables["fund_adj"], on=["code", "date"], how="outer")
        new["release_id"] = release_id
        saved = pd.concat([saved, new], ignore_index=True).sort_values(["code", "date"])
        saved.to_parquet(cache, index=False)
    return {code: saved.loc[saved.code == code].set_index("date")[
        ["open", "close", "adj", "amount", "volume"]].reindex(calendar) for code in codes}
