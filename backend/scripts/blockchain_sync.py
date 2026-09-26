#!/usr/bin/env python3
"""Binance Spot daily intake using immutable QuantBC releases.

The default universe is BTCUSDT/ETHUSDT. Tokenized equities require an explicit
product type and a separate root. Original observations and checksums are kept;
a failed download or quality check leaves CURRENT unchanged. Updates replay seven
closed UTC days; --refresh-history explicitly rechecks older source revisions.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("blockchain_sync")

_QUANTBC_DATA_DIR_ENV = "QM_QUANTBC_DATA_DIR"
_QUANTBC_DEFAULT_DIR = "/data/quantbc"
_QUANTBC_LOCAL_DIR = str(PROJECT_ROOT / "data" / "quantbc")

# QuantDB OHLCV compatibility plus original Binance fields and provenance.
KLINE_COLS = [
    "symbol",
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "quote_volume",
    "trades",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "open_time",
    "close_time",
    "available_at",
    "collected_at",
    "source",
    "source_sha256",
    "source_timestamp_unit",
    "venue",
    "product_type",
    "source_revision",
    "rest_source_sha256",
    "rest_close_time",
    "release_id",
    "published_at",
]

# Initial reviewed universe; do not infer product type from a ticker suffix.
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
# Curated first intake; unknown Spot listings must not silently become crypto.
SPOT_PRODUCTS = {
    "BTCUSDT": ("crypto_spot", None, None),
    "ETHUSDT": ("crypto_spot", None, None),
    "AAPLBUSDT": ("tokenized_equity_spot", "US", "AAPL"),
}
MANIFEST_SEMANTICS = {
    "available_at_semantics": "bar_period_end_lower_bound",
    "point_in_time_verified": False,
    "history_complete_scope": "current_public_api_daily_bar_coverage",
}


def _data_dir() -> Path:
    env_val = os.getenv(_QUANTBC_DATA_DIR_ENV, "").strip()
    if env_val:
        return Path(env_val)
    container_dir = Path(_QUANTBC_DEFAULT_DIR)
    if container_dir.is_dir():
        return container_dir
    local_dir = Path(_QUANTBC_LOCAL_DIR)
    local_dir.mkdir(parents=True, exist_ok=True)
    return local_dir


def _normalise_kline(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Preserve Binance observations; amount is the actual quote-asset volume."""
    return _normalise(df, symbol, daily=True)


def _normalise_minute_kline(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Binance 分钟 K 线 → QuantDB 分钟 schema。

    与日线不同：time 保留完整时间戳（datetime），否则同日多根 K 线会被去重。
    """
    return _normalise(df, symbol, daily=False)


def _normalise(df: pd.DataFrame, symbol: str, *, daily: bool) -> pd.DataFrame:
    out = df.copy()
    required = {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trades",
        "taker_buy_volume",
        "taker_buy_quote_volume",
        "open_time",
        "close_time",
        "available_at",
        "collected_at",
        "source",
        "source_sha256",
        "source_timestamp_unit",
    }
    if missing := required - set(out):
        raise ValueError(f"Missing original Binance fields: {sorted(missing)}")
    for col in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trades",
        "taker_buy_volume",
        "taker_buy_quote_volume",
    ):
        out[col] = pd.to_numeric(out[col], errors="raise")
    if not np.isfinite(
        out[
            list(required & {"open", "high", "low", "close", "volume", "quote_volume"})
        ].to_numpy()
    ).all():
        raise ValueError("Non-finite Binance prices/volumes")
    for col in ("open_time", "close_time", "available_at", "collected_at"):
        out[col] = pd.to_datetime(out[col], utc=True, errors="raise")
    out["symbol"] = symbol
    out["time"] = out["open_time"].dt.date if daily else out["open_time"]
    out["amount"] = out["quote_volume"]
    out["venue"] = "binance"
    for col in ("source_revision", "rest_source_sha256", "rest_close_time"):
        if col not in out:
            out[col] = None
    out["product_type"] = "crypto_spot"
    out["release_id"] = "pending"
    out["published_at"] = datetime.now(timezone.utc).isoformat()
    return out[KLINE_COLS]


def _atomic_parquet(df: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", suffix=".parquet", dir=target.parent)
    os.close(fd)
    try:
        df.to_parquet(name, index=False)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def _write_partition(root: Path, date_str: str, chunk: pd.DataFrame) -> Path:
    """写单个 Hive 分区 dt=YYYYMMDD/data.parquet（增量追加去重）。"""
    dt_dir = root / f"dt={date_str}"
    dt_dir.mkdir(parents=True, exist_ok=True)
    target = dt_dir / "data.parquet"
    if target.exists():
        old = pd.read_parquet(target)
        combined = pd.concat([old, chunk], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol", "time"], keep="last")
        _atomic_parquet(combined, target)
    else:
        _atomic_parquet(chunk, target)
    return target


def _write_symbol_file(root: Path, symbol: str, df: pd.DataFrame) -> Path:
    """写标的级分钟 K 线文件 {root}/{symbol}.parquet，增量追加去重。"""
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{symbol}.parquet"
    if target.exists():
        old = pd.read_parquet(target)
        combined = pd.concat([old, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol", "time"], keep="last")
        _atomic_parquet(combined, target)
    else:
        _atomic_parquet(df, target)
    return target


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _previous(root: Path) -> tuple[Path | None, dict, pd.DataFrame]:
    pointer = root / "CURRENT.json"
    if not pointer.is_file():
        if (root / "1_kline_data").exists():
            raise ValueError(
                "Legacy flat dataset requires explicit migration; refusing replacement"
            )
        return None, {}, pd.DataFrame(columns=KLINE_COLS)
    current = json.loads(pointer.read_text())
    path = (root / current["path"]).resolve()
    if path.parent != (root / "releases").resolve():
        raise ValueError("Invalid release path")
    if _sha(path / "manifest.json") != current["manifest_sha256"]:
        raise ValueError("Release manifest checksum mismatch")
    manifest = json.loads((path / "manifest.json").read_text())
    if (
        manifest.get("status") != "complete"
        or manifest["release_id"] != current["release_id"]
    ):
        raise ValueError("Incomplete release")
    actual = {
        str(p.relative_to(path))
        for p in path.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    if actual != set(manifest["files"]) or any(p.is_symlink() for p in path.rglob("*")):
        raise ValueError("Release file inventory mismatch")
    for name, digest in manifest["files"].items():
        target = (path / name).resolve()
        if not target.is_relative_to(path) or _sha(target) != digest:
            raise ValueError(f"Release file checksum mismatch: {name}")
    files = sorted(
        path / name
        for name in manifest["files"]
        if name.startswith("1_kline_data/daily_forward/")
        and name.endswith("/data.parquet")
    )
    data = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    for col in ("source_revision", "rest_source_sha256", "rest_close_time"):
        if col not in data:
            data[col] = None
    return path, manifest, data[KLINE_COLS]


def validate_daily(
    data: pd.DataFrame,
    symbols: list[str],
    end: date,
    expected_starts: dict[str, date] | None = None,
) -> dict:
    """Every published symbol has continuous, closed UTC daily observations."""
    from backend.services.engine.rd_agent.data_pipeline.crypto_data import (
        validate_binance_klines,
    )

    if data.empty or set(data["symbol"]) != set(symbols):
        raise ValueError("Missing requested symbols")
    cutoff = pd.Timestamp(end, tz="UTC")
    coverage = {}
    for symbol, group in data.groupby("symbol"):
        group = group.sort_values("open_time")
        raw = group.rename(columns={"symbol": "instrument"}).assign(
            datetime=group["open_time"]
        )
        validate_binance_klines(raw, "1d")
        if group["open_time"].duplicated().any():
            raise ValueError(f"Duplicate daily bars: {symbol}")
        if (group["available_at"] > cutoff).any() or (
            group["open_time"] >= cutoff
        ).any():
            raise ValueError(f"Unclosed/future daily bars: {symbol}")
        dates = pd.DatetimeIndex(group["open_time"])
        if expected_starts and dates.min().date() != expected_starts[symbol]:
            raise ValueError(
                f"Missing leading history for {symbol}: expected {expected_starts[symbol]}, got {dates.min().date()}"
            )
        expected = pd.date_range(dates.min(), cutoff - pd.Timedelta(days=1), freq="D")
        missing = expected.difference(dates)
        if len(missing):
            raise ValueError(
                f"Daily gaps for {symbol}: {len(missing)}; first={missing[0]}"
            )
        if not (group["amount"].to_numpy() == group["quote_volume"].to_numpy()).all():
            raise ValueError("Amount must equal actual quote volume")
        coverage[symbol] = {
            "rows": len(group),
            "first": dates.min().date().isoformat(),
            "last": dates.max().date().isoformat(),
            "gaps": 0,
            "duplicates": 0,
            "unclosed": 0,
        }
    revisions = data[data["source_revision"].fillna("").ne("")]
    return {
        "status": "passed",
        "timezone": "UTC",
        "end_exclusive": end.isoformat(),
        "symbols": coverage,
        "rows": len(data),
        "source_revisions": [
            {"symbol": row.symbol, "date": str(row.time), "reason": row.source_revision}
            for row in revisions.itertuples()
        ],
    }


def _publish_daily(
    root: Path,
    symbols: list[str],
    start: date,
    end: date,
    *,
    source: str,
    product_type: str,
    refresh_history: bool = False,
) -> dict:
    from backend.services.engine.rd_agent.data_pipeline.crypto_data import (
        download_binance_klines,
        get_binance_exchange_info,
        get_binance_first_kline,
    )

    _, previous, old = _previous(root)
    if previous and (
        set(previous["symbols"]) != set(symbols)
        or previous["product_type"] != product_type
    ):
        raise ValueError(
            "A release dataset cannot silently change its universe/product type"
        )
    if previous and end.isoformat() < previous["end_exclusive"]:
        raise ValueError("Refusing to regress the published cutoff")
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    cache = root / "raw" / attempt_id
    last_path = root / "last_attempt.json"
    # An interrupted attempt resumes only its identical frozen request window.
    request = {
        "symbols": symbols,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source": source,
        "product_type": product_type,
        "refresh_history": refresh_history,
    }
    if last_path.is_file():
        last = json.loads(last_path.read_text())
        if (
            last.get("status") in {"running", "failed"}
            and last.get("request") == request
        ):
            candidate = (root / last["raw_path"]).resolve()
            if candidate.parent == (root / "raw").resolve():
                cache = candidate
    attempt = {
        "status": "running",
        "attempt_id": attempt_id,
        "request": request,
        "raw_path": str(cache.relative_to(root)),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _json(last_path, attempt)
    try:
        info = get_binance_exchange_info(symbols, cache_dir=cache / "metadata")
        records = {s["symbol"]: s for s in info["symbols"]}
        for symbol in symbols:
            record = records[symbol]
            if record.get("quoteAsset") != "USDT" or not record.get(
                "isSpotTradingAllowed", False
            ):
                raise ValueError(f"Not an enabled USDT Spot instrument: {symbol}")
            if record.get("status") != "TRADING":
                raise ValueError(
                    f"Instrument no longer trading; lifecycle review required: {symbol}"
                )
        frames = []
        first_available = {}
        expected_starts = {}
        for symbol in symbols:
            first = get_binance_first_kline(
                symbol, cache_dir=cache / "first_observation"
            )
            if first.empty:
                raise ValueError(f"Cannot establish history boundary: {symbol}")
            first_available[symbol] = first.iloc[0]["open_time"].date()
            effective_start = max(start, first_available[symbol])
            symbol_start = effective_start
            prior = old[old["symbol"] == symbol]
            if not prior.empty:
                # Replay the overlap so revisions are visible in a new release.
                old_start = pd.Timestamp(prior["time"].min()).date()
                if refresh_history:
                    symbol_start = min(effective_start, old_start)
                elif effective_start >= old_start:
                    symbol_start = max(
                        effective_start,
                        pd.Timestamp(prior["time"].max()).date() - timedelta(days=7),
                    )
                expected_starts[symbol] = max(
                    first_available[symbol], min(start, old_start)
                )
            else:
                expected_starts[symbol] = max(first_available[symbol], start)
            raw = download_binance_klines(
                symbol,
                interval="1d",
                start_date=symbol_start.isoformat(),
                end_date=end.isoformat(),
                source=source,
                cache_dir=cache / symbol,
            )
            if raw.empty:
                raise ValueError(f"No observations for requested window: {symbol}")
            frame = _normalise_kline(raw, symbol)
            frame["product_type"] = product_type
            frames.append(frame)
            attempt["last_downloaded_symbol"] = symbol
            _json(last_path, attempt)
        incoming = pd.concat(frames, ignore_index=True)
        data = (
            pd.concat([old, incoming], ignore_index=True) if not old.empty else incoming
        )
        data = data.drop_duplicates(["symbol", "open_time"], keep="last").sort_values(
            ["symbol", "open_time"]
        )
        quality = validate_daily(data, symbols, end, expected_starts)
        quality["history_complete"] = all(
            pd.Timestamp(data.loc[data.symbol == symbol, "time"].min()).date()
            == first_available[symbol]
            for symbol in symbols
        )
        quality["first_available"] = {
            symbol: day.isoformat() for symbol, day in first_available.items()
        }
        values = [
            "symbol",
            "open_time",
            "available_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "product_type",
        ]
        digest = hashlib.sha256(
            data[values]
            .to_json(orient="records", date_format="iso", double_precision=15)
            .encode()
        ).hexdigest()
        instrument_digest = hashlib.sha256(
            json.dumps(records, sort_keys=True).encode()
        ).hexdigest()
        changed_rows = 0
        if not old.empty:
            joined = old[values].merge(
                incoming[values], on=["symbol", "open_time"], suffixes=("_old", "_new")
            )
            changed_rows = int(
                np.logical_or.reduce(
                    [
                        (joined[c + "_old"] != joined[c + "_new"]).to_numpy()
                        for c in values
                        if c not in {"symbol", "open_time"}
                    ]
                ).sum()
            )
        result = {
            "status": "completed",
            "kline": {"symbols": len(symbols), "rows": len(data), "errors": 0},
            "quality": quality,
            "revised_rows": changed_rows,
        }
        if (
            previous.get("data_digest") == digest
            and previous.get("instrument_digest") == instrument_digest
            and previous.get("columns") == KLINE_COLS
            and all(previous.get(k) == v for k, v in MANIFEST_SEMANTICS.items())
        ):
            result.update(
                release_id=previous["release_id"],
                unchanged=True,
                data_dir=str(root / "releases" / previous["release_id"]),
                quality=previous["quality"],
                checked_quality=quality,
            )
        else:
            release_id = f"binance-{attempt_id}-{digest[:10]}"
            data["release_id"] = release_id
            published = datetime.now(timezone.utc).isoformat()
            data["published_at"] = published
            releases = root / "releases"
            releases.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".staging-", dir=root) as directory:
                staged = Path(directory) / release_id
                staged.mkdir()
                kline_root = staged / "1_kline_data/daily_forward"
                for day, chunk in data.groupby("time"):
                    _write_partition(
                        kline_root, pd.Timestamp(day).strftime("%Y%m%d"), chunk
                    )
                instruments = []
                for symbol in symbols:
                    native = records[symbol]
                    instruments.append(
                        {
                            "symbol": symbol,
                            "name": native["baseAsset"],
                            "venue": "binance",
                            "product_type": product_type,
                            "base_asset": native["baseAsset"],
                            "underlying_market": SPOT_PRODUCTS[symbol][1],
                            "underlying_symbol": SPOT_PRODUCTS[symbol][2],
                            "quote_asset": native["quoteAsset"],
                            "status": native["status"],
                            "first_observed_date": quality["symbols"][symbol]["first"],
                            "metadata_as_of": info["provenance"]["collected_at"],
                            "filters_json": json.dumps(
                                native["filters"], sort_keys=True
                            ),
                            "release_id": release_id,
                        }
                    )
                _atomic_parquet(
                    pd.DataFrame(instruments),
                    staged / "2_base_sector/instrument_detail/instrument_list.parquet",
                )
                _json(staged / "exchange_info.json", info)
                _json(staged / "quality.json", quality)
                files = {
                    str(p.relative_to(staged)): _sha(p)
                    for p in sorted(staged.rglob("*"))
                    if p.is_file()
                }
                manifest = {
                    **MANIFEST_SEMANTICS,
                    "schema_version": 1,
                    "status": "complete",
                    "release_id": release_id,
                    "columns": KLINE_COLS,
                    "venue": "binance",
                    "product_type": product_type,
                    "symbols": symbols,
                    "frequency": "1d",
                    "timezone": "UTC",
                    "published_at": published,
                    "requested_start": start.isoformat(),
                    "end_exclusive": end.isoformat(),
                    "data_start": str(data["time"].min()),
                    "data_end": str(data["time"].max()),
                    "data_digest": digest,
                    "instrument_digest": instrument_digest,
                    "raw_path": str(cache.relative_to(root)),
                    "previous_release_id": previous.get("release_id"),
                    "revised_rows": changed_rows,
                    "quality": quality,
                    "files": files,
                }
                _json(staged / "manifest.json", manifest)
                final = releases / release_id
                staged.rename(final)
                _json(
                    root / "CURRENT.json",
                    {
                        "schema_version": 1,
                        "release_id": release_id,
                        "path": str(final.relative_to(root)),
                        "manifest_sha256": _sha(final / "manifest.json"),
                    },
                )
            result.update(release_id=release_id, unchanged=False, data_dir=str(final))
        attempt.update(
            status="completed",
            release_id=result["release_id"],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            _json(last_path, attempt)
        except OSError as exc:
            # CURRENT is the commit point. A later journal failure cannot roll it back.
            result["journal_warning"] = str(exc)
            log.warning("Release committed; could not update attempt journal: %s", exc)
        return result
    except Exception as exc:
        attempt.update(
            status="failed",
            error=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            _json(last_path, attempt)
        except OSError:
            log.exception("Could not record failed intake")
        raise


def run(
    *,
    days: int = 365,
    symbols: str | None = None,
    skip_valuation: bool = False,
    minute_freqs: tuple[str, ...] | None = None,
    minute_days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str = "rest",
    product_type: str = "crypto_spot",
    refresh_history: bool = False,
) -> dict:
    """Publish a validated daily release; legacy valuation flags are ignored."""
    if minute_freqs:
        raise ValueError(
            "Versioned intake currently accepts daily bars only; minute data needs a separate dataset"
        )
    if product_type not in {"crypto_spot", "tokenized_equity_spot"}:
        raise ValueError(
            "This collector is Spot-only; derivatives require a separate dataset"
        )
    syms = (
        sorted({s.strip().upper() for s in symbols.split(",") if s.strip()})
        if symbols
        else list(DEFAULT_SYMBOLS)
    )
    if not syms or days < 1:
        raise ValueError("Require symbols and positive days")
    if any(s not in SPOT_PRODUCTS or SPOT_PRODUCTS[s][0] != product_type for s in syms):
        raise ValueError(
            "Instrument product classification requires catalogue review; do not mix stocks and crypto"
        )
    today = datetime.now(timezone.utc).date()
    end = date.fromisoformat(end_date) if end_date else today
    start = date.fromisoformat(start_date) if start_date else end - timedelta(days=days)
    if not start < end <= today:
        raise ValueError("Require start < end <= today's UTC boundary")
    root = _data_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _publish_daily(
            root,
            syms,
            start,
            end,
            source=source,
            product_type=product_type,
            refresh_history=refresh_history,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantBC 区块链/加密货币数据摄取")
    parser.add_argument(
        "--days", type=int, default=365, help="同步最近多少个自然日（日线）"
    )
    parser.add_argument(
        "--symbols", default=None, help="逗号分隔交易对（默认 BTCUSDT,ETHUSDT）"
    )
    parser.add_argument("--skip-valuation", action="store_true", help="跳过估值快照")
    parser.add_argument(
        "--minute", action="store_true", help="同步分钟线（5m+1m，最近 90 天）"
    )
    parser.add_argument(
        "--minute-days",
        type=int,
        default=None,
        help="分钟线拉取天数（默认 min(days,90)）",
    )
    parser.add_argument(
        "--start-date", help="UTC 起始日（含）；首次全历史可设 2010-01-01"
    )
    parser.add_argument(
        "--end-date", help="UTC 截止日（不含）；默认今天，只采已收盘K线"
    )
    parser.add_argument("--data-dir", help="明确指定数据根目录")
    parser.add_argument("--source", choices=("rest", "auto", "archive"), default="rest")
    parser.add_argument(
        "--product-type",
        choices=("crypto_spot", "tokenized_equity_spot"),
        default="crypto_spot",
    )
    parser.add_argument(
        "--refresh-history",
        action="store_true",
        help="重新核验全部历史；默认只回看最近7日修订",
    )
    args = parser.parse_args()

    try:
        if args.data_dir:
            os.environ[_QUANTBC_DATA_DIR_ENV] = args.data_dir
        minute_freqs = ("5m", "1m") if args.minute else None
        result = run(
            days=args.days,
            symbols=args.symbols,
            skip_valuation=args.skip_valuation,
            minute_freqs=minute_freqs,
            minute_days=args.minute_days,
            start_date=args.start_date,
            end_date=args.end_date,
            source=args.source,
            product_type=args.product_type,
            refresh_history=args.refresh_history,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        log.error("同步失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
