"""Binance Spot public data: UTC closed bars with raw-response provenance.

REST uses the documented market-data-only host. Monthly archive files are
optional and verified against the publisher's SHA-256 checksum before parsing.
No authenticated/trading endpoint or automatic alternate-host fallback is used.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import zipfile
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
BINANCE_KLINE_URLS = ["https://data-api.binance.vision/api/v3/klines"]
BINANCE_EXCHANGE_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"
BINANCE_ARCHIVE_URL = "https://data.binance.vision/data/spot/monthly/klines"
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
_RAW_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
_VALUE_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
    "taker_buy_volume",
    "taker_buy_quote_volume",
]
_INTERVALS = {
    "1s": "1s",
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "3d": "3d",
    "1w": "7d",
}


def _get_api_url() -> str:
    """Compatibility helper; a restriction/error never triggers host switching."""
    return BINANCE_KLINE_URLS[0]


def _utc(value) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if pd.isna(result):
        raise ValueError("Invalid UTC timestamp")
    return (
        result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")
    )


def _symbol(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,40}", value):
        raise ValueError(f"Invalid Binance symbol: {value!r}")
    return value


def _request_bytes(url, *, params=None, cache_dir=None, max_retries=3):
    """Return bytes and their receipt metadata; cache is a pinned raw snapshot."""
    import requests

    if not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
        raise ValueError("max_retries must be between 0 and 5")
    request = {"url": url, "params": params or {}}
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    cache = Path(cache_dir) if cache_dir is not None else None
    suffix = (
        ".zip"
        if url.endswith(".zip")
        else ".CHECKSUM"
        if url.endswith(".CHECKSUM")
        else ".response"
    )
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        raw_path, meta_path = cache / f"{key}{suffix}", cache / f"{key}.json"
        if raw_path.is_file() and meta_path.is_file():
            body = raw_path.read_bytes()
            metadata = json.loads(meta_path.read_text())
            if (
                metadata.get("request") != request
                or metadata.get("sha256") != hashlib.sha256(body).hexdigest()
            ):
                raise ValueError(f"Corrupt Binance raw cache: {raw_path}")
            return body, metadata
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=(10, 30))
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_retries:
                raise
            time.sleep(min(2**attempt, 8))
            continue
        retryable = response.status_code == 429 or response.status_code >= 500
        if retryable and attempt < max_retries:
            delay = max(float(response.headers.get("Retry-After", 0)), 2**attempt)
            # Long bans/rate limits are surfaced for a later run, never truncated.
            if delay > 30:
                response.raise_for_status()
            time.sleep(delay)
            continue
        response.raise_for_status()  # Includes 400/403/418/451; no domain fallback.
        body = response.content
        metadata = {
            "request": request,
            "sha256": hashlib.sha256(body).hexdigest(),
            "collected_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        if cache:
            temporary = raw_path.with_suffix(raw_path.suffix + ".tmp")
            temporary.write_bytes(body)
            temporary.replace(raw_path)
            temporary = meta_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(metadata, indent=2))
            temporary.replace(meta_path)
        return body, metadata
    raise RuntimeError("Binance request exhausted retries")


def get_binance_exchange_info(symbols=None, *, cache_dir=None, max_retries=3) -> dict:
    """Native Spot exchangeInfo including status, assets and precision filters.

    This is current exchange metadata, not a historical universe or proof of
    equity ownership. The native schema is retained; provenance is an extra key.
    """
    params = {"symbols": json.dumps([_symbol(s) for s in symbols], separators=(",", ":"))} if symbols else None
    body, metadata = _request_bytes(
        BINANCE_EXCHANGE_INFO_URL,
        params=params,
        cache_dir=cache_dir,
        max_retries=max_retries,
    )
    result = json.loads(body)
    if not isinstance(result, dict) or not isinstance(result.get("symbols"), list):
        raise ValueError("Invalid Binance exchangeInfo response")
    if symbols and {s["symbol"] for s in result["symbols"]} != {
        _symbol(s) for s in symbols
    }:
        raise ValueError("Binance exchangeInfo did not return every requested symbol")
    result["provenance"] = metadata
    return result


def get_binance_first_kline(symbol: str, *, cache_dir=None, max_retries=3) -> pd.DataFrame:
    """Return the earliest closed daily Spot bar exposed by the public REST API.

    This is a one-row startTime=0 probe, not a paginated history download or an
    exchange listing-date assertion. Its raw response has independent provenance.
    """
    symbol = _symbol(symbol)
    body, metadata = _request_bytes(
        _get_api_url(),
        params={"symbol": symbol, "interval": "1d", "startTime": 0, "limit": 1},
        cache_dir=cache_dir,
        max_retries=max_retries,
    )
    rows = json.loads(body)
    frame = _parse_klines(rows, symbol, "1d", metadata, timestamp_unit="ms")
    if len(frame) > 1:
        raise ValueError("Binance earliest-bar probe exceeded its one-row limit")
    if frame.empty:
        return frame
    return frame[frame["available_at"] <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)


def validate_binance_klines(df: pd.DataFrame, interval: str = "1d") -> None:
    """Raise on invalid native bars or conflicting duplicate timestamps.

    Expects the UTC/native-value schema returned by download_binance_klines;
    duplicates with identical values are allowed for idempotent merges.
    """
    if df.empty:
        return
    if interval not in _INTERVALS and interval != "1M":
        raise ValueError(f"Unsupported Binance interval: {interval}")
    for column in ("open_time", "close_time", "available_at"):
        if (
            not isinstance(df[column].dtype, pd.DatetimeTZDtype)
            or str(df[column].dt.tz) != "UTC"
            or df[column].isna().any()
        ):
            raise ValueError(f"Binance {column} must contain aware UTC timestamps")
    expected_end = df["open_time"] + (
        pd.offsets.MonthBegin(1)
        if interval == "1M"
        else pd.Timedelta(_INTERVALS[interval])
    )
    if (df["available_at"] != expected_end).any():
        raise ValueError("Binance kline interval/close-time mismatch")
    if interval == "1d" and (df["open_time"] != df["open_time"].dt.normalize()).any():
        raise ValueError("Binance daily bars must open at UTC midnight")
    if (df["close_time"] < df["open_time"]).any() or (
        df["close_time"] >= df["available_at"]
    ).any():
        raise ValueError("Invalid Binance close-time boundary")
    values = df[_VALUE_COLUMNS]
    invalid = ~np.isfinite(values).all(axis=1) | (values < 0).any(axis=1)
    invalid |= (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    invalid |= df["high"] < df[["open", "low", "close"]].max(axis=1)
    invalid |= df["low"] > df[["open", "high", "close"]].min(axis=1)
    invalid |= df["trades"] % 1 != 0
    invalid |= df["taker_buy_volume"] > df["volume"] + 1e-8
    invalid |= df["taker_buy_quote_volume"] > df["quote_volume"] + 1e-8
    if invalid.any():
        raise ValueError("Invalid Binance OHLCV/trade values")
    duplicates = df[df.duplicated("open_time", keep=False)]
    if not duplicates.empty:
        comparisons = _VALUE_COLUMNS + ["available_at"]
        if (
            (duplicates.groupby("open_time")[comparisons].nunique(dropna=False) > 1)
            .any()
            .any()
        ):
            raise ValueError("Conflicting duplicate Binance klines")


def _parse_klines(rows, symbol, interval, metadata, *, timestamp_unit=None):
    if not isinstance(rows, list) or any(
        not isinstance(r, (list, tuple)) or len(r) != 12 for r in rows
    ):
        raise ValueError("Invalid Binance kline response schema")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=_RAW_COLUMNS)
    open_raw = pd.to_numeric(df["open_time"], errors="raise")
    close_raw = pd.to_numeric(df["close_time"], errors="raise")
    if (open_raw % 1).any() or (close_raw % 1).any():
        raise ValueError("Fractional Binance timestamps")
    units = pd.Series(np.where(open_raw >= 100_000_000_000_000, "us", "ms"))
    close_units = np.where(close_raw >= 100_000_000_000_000, "us", "ms")
    if (units != close_units).any() or (
        timestamp_unit and (units != timestamp_unit).any()
    ):
        raise ValueError("Unexpected Binance timestamp units")
    for name, raw in (("open_time", open_raw), ("close_time", close_raw)):
        df[name] = pd.to_datetime(
            raw * np.where(units == "us", 1000, 1_000_000), unit="ns", utc=True
        )
    df["available_at"] = df["close_time"] + pd.to_timedelta(
        np.where(units == "us", 1000, 1_000_000), unit="ns"
    )
    for col in _VALUE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="raise")
    validate_binance_klines(df, interval)
    df["trades"] = df["trades"].astype("int64")
    df["datetime"] = df["open_time"]
    df["instrument"] = symbol
    df["source"] = metadata["request"]["url"]
    df["source_sha256"] = metadata["sha256"]
    df["collected_at"] = _utc(metadata["collected_at"])
    df["source_timestamp_unit"] = units
    df["source_revision"] = None
    df["rest_source_sha256"] = None
    df["rest_close_time"] = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    return df.drop(columns=["ignore"])


def _combine_klines(frames, start, end, now):
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    duplicates = data[data.duplicated("open_time", keep=False)]
    if not duplicates.empty:
        comparisons = _VALUE_COLUMNS + ["available_at", "instrument"]
        if (
            (duplicates.groupby("open_time")[comparisons].nunique(dropna=False) > 1)
            .any()
            .any()
        ):
            raise ValueError("Conflicting duplicate Binance klines")
    data = data.drop_duplicates("open_time").sort_values("open_time")
    return data[
        (data["open_time"] >= start)
        & (data["open_time"] < end)
        & (data["available_at"] <= end)
        & (data["available_at"] <= now)
    ].reset_index(drop=True)


def _parse_rest_page(rows, symbol, interval, metadata, *, cache_dir, max_retries):
    try:
        return _parse_klines(rows, symbol, interval, metadata, timestamp_unit="ms")
    except ValueError as exc:
        # Historical REST bars can have a stale close-time even when the official
        # archive has the correct one. Only this proven discrepancy is repairable.
        if interval != "1d" or str(exc) != "Binance kline interval/close-time mismatch":
            raise
    if not pd.Series([int(row[0]) for row in rows]).is_monotonic_increasing:
        raise ValueError("Binance REST page is not chronological")
    suspect = [row for row in rows if int(row[6]) + 1 != int(row[0]) + 86_400_000]
    for row in suspect:
        if not int(row[0]) <= int(row[6]) < int(row[0]) + 86_400_000:
            raise ValueError("Invalid Binance REST close-time crosses its daily period")
    normal = [row for row in rows if int(row[6]) + 1 == int(row[0]) + 86_400_000]
    frames = [_parse_klines(normal, symbol, interval, metadata, timestamp_unit="ms")]
    months = {}
    for row in suspect:
        opening = pd.to_datetime(int(row[0]), unit="ms", utc=True)
        month = opening.normalize().replace(day=1)
        if month not in months:
            months[month] = _download_archive(
                symbol, interval, month, cache_dir=cache_dir, max_retries=max_retries,
                return_native_rows=True,
            )
        archived, native_rows = months[month]
        replacement = archived[archived["open_time"] == opening].copy()
        if len(replacement) != 1:
            raise ValueError("Binance archive cannot uniquely resolve REST close-time discrepancy")
        # Compare raw decimal strings; comparing parsed floats can hide a source
        # difference or falsely reject identical high-precision turnover values.
        native = [r for r in native_rows if pd.to_datetime(int(r[0]),
                  unit="us" if int(r[0]) >= 100_000_000_000_000 else "ms", utc=True) == opening]
        if len(native) != 1:
            raise ValueError("Binance archive has ambiguous native rows")
        for name in _VALUE_COLUMNS:
            position = _RAW_COLUMNS.index(name)
            if Decimal(str(row[position])) != Decimal(str(native[0][position])):
                raise ValueError(f"Binance REST/archive economic values differ: {symbol} {opening} {name}")
        replacement["source_revision"] = "archive_corrected_rest_close_time"
        replacement["rest_source_sha256"] = metadata["sha256"]
        replacement["rest_close_time"] = pd.to_datetime(int(row[6]), unit="ms", utc=True)
        frames.append(replacement)
        logger.warning("Using checksum-verified archive close-time for %s %s; REST sha256=%s",
                       symbol, opening.date(), metadata["sha256"])
    return pd.concat([frame for frame in frames if not frame.empty], ignore_index=True).sort_values("open_time").reset_index(drop=True)


def _download_rest(symbol, interval, start, end, limit, *, cache_dir, max_retries):
    frames = []
    current_start = start.value // 1_000_000
    end_ms = end.value // 1_000_000
    while current_start < end_ms:
        body, metadata = _request_bytes(
            _get_api_url(),
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start,
                "endTime": end_ms - 1,
                "limit": limit,
            },
            cache_dir=cache_dir,
            max_retries=max_retries,
        )
        data = json.loads(body)
        frame = _parse_rest_page(data, symbol, interval, metadata,
                                cache_dir=cache_dir, max_retries=max_retries)
        if frame.empty:
            break
        if not frame["open_time"].is_monotonic_increasing:
            raise ValueError("Binance REST page is not chronological")
        next_start = int(frame["available_at"].max().value // 1_000_000)
        if next_start <= current_start:
            raise ValueError("Binance pagination made no forward progress")
        frames.append(frame)
        current_start = next_start
        if len(data) < limit:
            break
        time.sleep(0.15)
    return frames


def _download_archive(symbol, interval, month, *, cache_dir, max_retries, return_native_rows=False):
    filename_interval = "1mo" if interval == "1M" else interval
    filename = f"{symbol}-{filename_interval}-{month:%Y-%m}.zip"
    url = f"{BINANCE_ARCHIVE_URL}/{symbol}/{filename_interval}/{filename}"
    body, metadata = _request_bytes(url, cache_dir=cache_dir, max_retries=max_retries)
    checksum, _ = _request_bytes(
        url + ".CHECKSUM", cache_dir=cache_dir, max_retries=max_retries
    )
    fields = checksum.decode().strip().split()
    if (
        len(fields) != 2
        or fields[1].lstrip("*") != filename
        or fields[0].lower() != metadata["sha256"]
    ):
        raise ValueError(f"Binance archive checksum mismatch: {filename}")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if names != [filename.removesuffix(".zip") + ".csv"]:
            raise ValueError(f"Unexpected Binance ZIP contents: {filename}")
        with archive.open(names[0]) as handle:
            rows = pd.read_csv(handle, header=None, dtype=str).values.tolist()
    frame = _parse_klines(rows, symbol, interval, metadata)
    return (frame, rows) if return_native_rows else frame


def download_binance_klines(
    symbol: str,
    interval: str = "1d",
    start_date: str = "2010-01-01",
    end_date: str | None = None,
    limit: int = 1000,
    *,
    source: str = "rest",
    cache_dir: str | Path | None = None,
    max_retries: int = 3,
    now=None,
) -> pd.DataFrame:
    """Fetch closed Spot bars within [start_date, end_date), always aware UTC.

    source='rest' is efficient for daily history; 'auto' verifies complete-month
    ZIPs and reads partial/unpublished months from REST. 'archive' requires whole,
    completed UTC months and fails if any archive is missing. 404-only fallback
    in 'auto' indicates an unpublished archive, not an alternate restriction host.
    cache_dir retains raw responses/checksums and pins them for reproducible reruns.
    A historical REST close-time discrepancy is resolved only against a verified
    archive row with identical economic values, and both sources remain recorded.
    available_at is the theoretical bar close boundary; collected_at records when
    the response was observed and does not claim historical publication latency.
    """
    import requests

    symbol = _symbol(symbol)
    if interval not in _INTERVALS and interval != "1M":
        raise ValueError(f"Unsupported Binance interval: {interval}")
    if source not in {"rest", "auto", "archive"}:
        raise ValueError("source must be rest, auto or archive")
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    observed_now = _utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    start = _utc(start_date)
    end = _utc(end_date) if end_date is not None else observed_now
    if end <= start:
        raise ValueError("end_date must be after start_date (exclusive UTC boundary)")
    end = min(end, observed_now)
    options = {"cache_dir": cache_dir, "max_retries": max_retries}
    if source == "rest":
        frames = _download_rest(symbol, interval, start, end, limit, **options)
    else:
        month = start.normalize().replace(day=1)
        if source == "archive" and (
            start != month or end != end.normalize().replace(day=1)
        ):
            raise ValueError("archive source requires completed whole UTC months")
        frames = []
        while month < end:
            next_month = month + pd.offsets.MonthBegin(1)
            left, right = max(start, month), min(end, next_month)
            if next_month <= observed_now and right == next_month:
                try:
                    frames.append(_download_archive(symbol, interval, month, **options))
                    month = next_month
                    continue
                except requests.HTTPError as exc:
                    if (
                        source != "auto"
                        or exc.response is None
                        or exc.response.status_code != 404
                    ):
                        raise
            if source == "archive":
                raise ValueError("archive source cannot include an unfinished month")
            frames.extend(
                _download_rest(symbol, interval, left, right, limit, **options)
            )
            month = next_month
    return _combine_klines(frames, start, end, observed_now)


def download_all_crypto(
    symbols: list[str] | None = None,
    start_date: str = "2010-01-01",
    end_date: str | None = None,
    output_dir: str = "/app/db/crypto_data",
    interval: str = "1d",
) -> str:
    """下载所有交易对数据并保存为 H5

    Args:
        interval: K线周期, "1d" (日线) 或 "5m" (5分钟)
    Returns: H5 文件路径
    """
    symbols = symbols or DEFAULT_SYMBOLS
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 5min 数据使用单独的子目录
    if interval == "5m":
        csv_dir = output_path / "csv_5m"
        h5_name = "5min_pv.h5"
    else:
        csv_dir = output_path / "csv"
        h5_name = "daily_pv.h5"
    csv_dir.mkdir(exist_ok=True)

    logger.info("Downloading %d crypto symbols (%s) from Binance...", len(symbols), interval)

    all_dfs = []
    for i, symbol in enumerate(symbols, 1):
        csv_file = csv_dir / f"{symbol}.csv"
        if csv_file.exists():
            logger.info("  [%d/%d] %s — cached", i, len(symbols), symbol)
            df = pd.read_csv(csv_file, parse_dates=["datetime"])
        else:
            logger.info("  [%d/%d] %s — downloading...", i, len(symbols), symbol)
            try:
                df = download_binance_klines(symbol, interval=interval, start_date=start_date, end_date=end_date)
                if df.empty:
                    logger.warning("  [%d/%d] %s — no data", i, len(symbols), symbol)
                    continue
                df.to_csv(csv_file, index=False)
            except Exception as e:
                logger.error("  [%d/%d] %s — failed: %s", i, len(symbols), symbol, e)
                continue

        all_dfs.append(df)

    if not all_dfs:
        raise RuntimeError("No data downloaded")

    # 合并为 H5（使用 $ 前缀列名，与 RD-Agent daily_pv.h5 兼容）
    combined = pd.concat(all_dfs, ignore_index=True)
    combined["factor"] = 1.0
    combined = combined.rename(columns={
        "open": "$open",
        "high": "$high",
        "low": "$low",
        "close": "$close",
        "volume": "$volume",
        "factor": "$factor",
    })
    combined = combined[["datetime", "instrument", "$open", "$high", "$low", "$close", "$volume", "$factor"]]
    combined = combined.set_index(["datetime", "instrument"])
    combined = combined.sort_index()

    h5_path = output_path / h5_name
    combined.to_hdf(str(h5_path), key="data", mode="w")
    logger.info("Saved H5: %s (%d rows, %d symbols)", h5_path, len(combined), len(all_dfs))

    return str(h5_path)


def convert_h5_to_qlib_format(
    h5_path: str,
    output_dir: str = "/app/db/qlib_data/crypto_data",
    freq: str = "day",
) -> str:
    """将 H5 转换为 Qlib 原生 bin 格式

    Args:
        freq: "day" 或 "5min"
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    df = pd.read_hdf(h5_path, key="data")

    cal_dir = output / "calendars"
    feat_dir = output / "features"
    inst_dir = output / "instruments"
    cal_dir.mkdir(exist_ok=True)
    feat_dir.mkdir(exist_ok=True)
    inst_dir.mkdir(exist_ok=True)

    # 日历
    dates = df.index.get_level_values("datetime").unique().sort_values()
    cal_file = f"{freq}.txt"
    with open(cal_dir / cal_file, "w") as f:
        for d in dates:
            if freq == "5min":
                f.write(d.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            else:
                f.write(d.strftime("%Y-%m-%d") + "\n")

    # 标的列表
    instruments = df.index.get_level_values("instrument").unique().sort_values()
    inst_file = "all.txt"
    with open(inst_dir / inst_file, "w") as f:
        start_str = dates.min().strftime("%Y-%m-%d")
        end_str = dates.max().strftime("%Y-%m-%d")
        for inst in instruments:
            f.write(f"{inst}\t{start_str}\t{end_str}\n")

    # 特征数据
    col_map = {col: col.lstrip("$") for col in df.columns}
    bin_suffix = f"{freq}.bin" if freq == "5min" else f"{freq}.bin"
    for inst in instruments:
        inst_dir_path = feat_dir / inst.lower()
        inst_dir_path.mkdir(exist_ok=True)
        try:
            inst_data = df.xs(inst, level="instrument")
        except KeyError:
            continue
        for orig_col, clean_col in col_map.items():
            if orig_col not in inst_data.columns:
                continue
            series = inst_data[orig_col].reindex(dates)
            bin_path = inst_dir_path / f"{clean_col}.{bin_suffix}"
            series.values.astype("float32").tofile(str(bin_path))

    logger.info("Converted to Qlib format: %s (%d instruments, %d dates, freq=%s)", output, len(instruments), len(dates), freq)
    return str(output)


def is_crypto_data_ready(qlib_dir: str = "/app/db/qlib_data/crypto_data") -> bool:
    """检查加密货币数据是否已就绪 (支持 5min 和 day 两种频率)"""
    p = Path(qlib_dir)
    has_calendar = (p / "calendars" / "5min.txt").is_file() or (p / "calendars" / "day.txt").is_file()
    return (
        p.is_dir()
        and has_calendar
        and (p / "instruments" / "all.txt").is_file()
        and (p / "features").is_dir()
        and len(list((p / "features").iterdir())) > 0
    )
