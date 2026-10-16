"""只读本地行情；所有派生缓存只写 data/extra/cache。"""

from functools import lru_cache
from pathlib import Path
import hashlib
import json

import duckdb
import pandas as pd

from ashare_lab.data.build import SOURCE

ROOT = Path(__file__).resolve().parents[3]
EXTRA = ROOT / "data/extra"
CACHE = EXTRA / "cache"
ETF_CODES = ("511010.SH", "518880.SH", "511880.SH")


@lru_cache(maxsize=1)
def source_paths():
    release = json.loads((SOURCE / "CURRENT.json").read_text())["release_id"]
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{release}_paths.json"
    if cache.exists():
        return release, json.loads(cache.read_text())
    manifest = json.loads((SOURCE / "releases" / release / "manifest.json").read_text())
    paths = {api: [] for api in ("sge_daily", "fund_daily", "fund_adj", "trade_cal")}
    for dataset in manifest["datasets"]:
        if dataset["api_name"] in paths:
            paths[dataset["api_name"]].append(str(SOURCE / dataset["path"]))
    cache.write_text(json.dumps(paths))
    return release, paths


@lru_cache(maxsize=None)
def archive(api, codes, field):
    release, paths = source_paths()
    key = hashlib.sha256(repr((release, api, codes, field)).encode()).hexdigest()[:20]
    cache = CACHE / f"{api}_{key}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    with duckdb.connect() as con:
        con.execute("SET threads = 4")
        con.execute("SET memory_limit = '1GB'")
        # 只执行 SELECT；不打开归档数据库、不创建归档侧临时文件。
        for offset in range(0, len(paths[api]), 512):
            files = paths[api][offset:offset + 512]
            placeholders = ','.join('?' for _ in codes)
            query = (f"SELECT source_ts_code, trade_date, {field}, "
                     "_fetched_at::TIMESTAMPTZ AS _fetched_at "
                     "FROM read_parquet(?, union_by_name=true, hive_partitioning=false) "
                     f"WHERE source_ts_code IN ({placeholders})")
            frames.append(con.execute(query, [files, *codes]).df())
            print(f"{api}: {min(offset + 512, len(paths[api]))}/{len(paths[api])} files", flush=True)
    if not frames:
        raise ValueError(f"归档缺少 {api}")
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.sort_values("_fetched_at", na_position="first").drop_duplicates(
        ["source_ts_code", "trade_date"], keep="last")
    frame["date"] = pd.to_datetime(frame.trade_date.astype(str), format="%Y%m%d")
    frame = frame.sort_values(["source_ts_code", "date"])
    frame.to_parquet(cache, index=False)
    return frame


def load_calendar():
    return pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(ROOT / "data/panel/calendar.parquet").date)).sort_values()


def align(series, calendar):
    """先丢弃日历外行情，再填充日历内缺口，不反向填充上市前数据。"""
    return series.sort_index().reindex(calendar).ffill()


def load_asset(name, calendar=None):
    calendar = load_calendar() if calendar is None else calendar
    if name == "bond_index":
        frame = pd.read_parquet(EXTRA / "h11001.parquet")
        frame = frame[frame.ts_code == "H11001.CSI"].copy()
        frame["date"] = pd.to_datetime(frame.trade_date, format="%Y%m%d")
        series = frame.drop_duplicates("date").set_index("date").close
    elif name == "gold_spot":
        # 归档 sge_daily 在 2020–2026-09 缺失，改用 tools/fetch_gold.py 在线补拉的完整日线。
        frame = pd.read_parquet(EXTRA / "sge_au9999.parquet")
        frame["date"] = pd.to_datetime(frame.trade_date, format="%Y%m%d")
        series = frame.drop_duplicates("date").set_index("date").close
    elif name.startswith("etf:"):
        code = name.split(":", 1)[1]
        prices = archive("fund_daily", ETF_CODES, "close")
        factors = archive("fund_adj", ETF_CODES, "adj_factor")
        close = align(prices[prices.source_ts_code == code].set_index("date").close, calendar)
        adj = align(factors[factors.source_ts_code == code].set_index("date").adj_factor, calendar)
        series = close * adj
    else:
        raise ValueError(f"未知资产 {name}")
    return align(series, calendar).rename(name)


def load_futures(calendar=None):
    calendar = load_calendar() if calendar is None else calendar
    daily = pd.read_parquet(EXTRA / "fut_daily_cffex.parquet")
    daily["date"] = pd.to_datetime(daily.trade_date, format="%Y%m%d")
    daily["price"] = daily.close.fillna(daily.settle)
    prices = daily.drop_duplicates(["date", "ts_code"]).pivot(index="date", columns="ts_code", values="price")
    prices = prices.reindex(calendar).ffill()
    mapping = pd.read_parquet(EXTRA / "fut_mapping_cffex.parquet")
    mapping["date"] = pd.to_datetime(mapping.trade_date, format="%Y%m%d")
    mapping = mapping.drop_duplicates(["date", "ts_code"]).pivot(
        index="date", columns="ts_code", values="mapping_ts_code").reindex(calendar).ffill()
    basic = pd.read_parquet(EXTRA / "fut_basic_cffex.parquet")
    for col in ("list_date", "delist_date"):
        basic[col] = pd.to_datetime(basic[col], format="%Y%m%d")
    return prices, mapping, basic


def load_indexes(calendar=None):
    calendar = load_calendar() if calendar is None else calendar
    frame = pd.read_parquet(ROOT / "data/panel/index_daily.parquet")
    frame["date"] = pd.to_datetime(frame.date)
    return {product: align(frame[frame.index_code == code].set_index("date").close, calendar)
            for product, code in (("IF", "000300.SH"), ("IC", "000905.SH"))}
