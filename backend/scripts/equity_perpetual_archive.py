#!/usr/bin/env python3
"""Archive-only USD-M equity perpetual daily bars; never call a Futures API.

Only a complete requested bar window advances CURRENT. Missing archive files
produce an immutable partial release, with missing.json, without changing the
last complete pointer. These are derivative observations, never stock prices or
crypto_spot research input. Funding/mark/index/corporate actions are not fetched.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts import blockchain_sync as publication
from backend.services.engine.rd_agent.data_pipeline import crypto_data as source

ARCHIVE_ROOT = "https://data.binance.vision/data/futures/um"
PRODUCT_TYPE = "equity_perpetual"
MISSING_DATASETS = ["funding_rate", "mark_price", "index_price", "corporate_actions"]
REGISTRY = {
    "CXMTUSDT": {
        "underlying_symbol": "688825.SH",
        "underlying_market": "CN",
        "listing_time": "2026-08-18T05:00:00Z",
        "listing_source": "https://www.binance.com/en-NG/support/announcement/detail/0872245db74c4daaabd4f11984ba52c1",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
        "product_type": PRODUCT_TYPE,
    },
    "UNITREEUSDT": {
        "underlying_symbol": "688836.SH",
        "underlying_market": "CN",
        "listing_time": "2026-08-19T02:45:00Z",
        "listing_source": "https://www.binance.com/en/support/announcement/detail/3e662272597c44b7939f5db5c8c86d4f",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
        "product_type": PRODUCT_TYPE,
    },
}


def _reviewed_registry(symbols, registry):
    symbols = sorted({source._symbol(item) for item in symbols})
    if not symbols or any(item not in registry for item in symbols):
        raise ValueError(
            "Every requested symbol needs an explicit reviewed listing registry"
        )
    selected = {}
    for symbol in symbols:
        record = dict(registry[symbol])
        if set(REGISTRY["CXMTUSDT"]) - set(record):
            raise ValueError(f"Incomplete listing registry: {symbol}")
        listing = pd.Timestamp(record["listing_time"])
        url = urlparse(record["listing_source"])
        if (
            pd.isna(listing)
            or listing.tzinfo is None
            or record["product_type"] != PRODUCT_TYPE
            or record["quote_asset"] != "USDT"
            or record["settlement_asset"] != "USDT"
            or not record["underlying_symbol"]
            or not record["underlying_market"]
            or url.scheme != "https"
            or url.hostname != "www.binance.com"
            or "/support/announcement/detail/" not in url.path
        ):
            raise ValueError(f"Invalid reviewed equity perpetual listing: {symbol}")
        record["listing_time"] = listing.tz_convert("UTC").isoformat()
        selected[symbol] = record
    return selected


def _windows(start, end, now):
    """Past UTC months use monthly ZIPs; the current month uses daily ZIPs."""
    month = start.replace(day=1)
    while month < end:
        next_month = month + pd.offsets.MonthBegin(1)
        if next_month <= now.normalize().replace(day=1):
            yield "monthly", month, next_month
        else:
            for day in pd.date_range(
                max(start, month), min(end, next_month), inclusive="left"
            ):
                yield "daily", day, day + pd.Timedelta(days=1)
        month = next_month


def _download(symbol, period, left, right, cache_dir, max_retries):
    suffix = left.strftime("%Y-%m" if period == "monthly" else "%Y-%m-%d")
    filename = f"{symbol}-1d-{suffix}.zip"
    url = f"{ARCHIVE_ROOT}/{period}/klines/{symbol}/1d/{filename}"
    options = {"cache_dir": cache_dir, "max_retries": max_retries}
    body, receipt = source._request_bytes(url, **options)
    checksum, checksum_receipt = source._request_bytes(url + ".CHECKSUM", **options)
    fields = checksum.decode().strip().split()
    digest = hashlib.sha256(body).hexdigest()
    if (
        len(fields) != 2
        or fields[1].lstrip("*") != filename
        or fields[0].lower() != digest
        or receipt["sha256"] != digest
    ):
        raise ValueError(f"Archive checksum mismatch: {filename}")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        expected = filename.removesuffix(".zip") + ".csv"
        if (
            archive.namelist() != [expected]
            or archive.getinfo(expected).file_size > 10_000_000
        ):
            raise ValueError(f"Unexpected daily-bar archive contents: {filename}")
        with archive.open(expected) as handle:
            rows = pd.read_csv(
                handle, header=None, dtype=str, keep_default_na=False
            ).values.tolist()
    # USD-M files have a header; old headerless archives are also unambiguous.
    if rows and rows[0][0].lstrip("\ufeff") == "open_time":
        header = [item.lstrip("\ufeff") for item in rows.pop(0)]
        futures_header = [
            "count" if item == "trades" else item for item in source._RAW_COLUMNS
        ]
        if header not in (source._RAW_COLUMNS, futures_header):
            raise ValueError(f"Unexpected archive CSV header: {filename}")
    frame = source._parse_klines(rows, symbol, "1d", receipt, timestamp_unit="ms")
    if not frame.empty and (
        (frame["open_time"] < left).any() or (frame["open_time"] >= right).any()
    ):
        raise ValueError(f"Archive rows outside their declared period: {filename}")
    return frame, {
        "symbol": symbol,
        "url": url,
        "sha256": digest,
        "checksum_sha256": checksum_receipt["sha256"],
        "collected_at": receipt["collected_at"],
    }


def _verify_raw_files(root, manifest):
    for name, digest in manifest.get("raw_files", {}).items():
        target = root / name
        if (
            not target.resolve().is_relative_to(root / "raw")
            or target.is_symlink()
            or publication._sha(target) != digest
        ):
            raise ValueError("Published raw archive checksum mismatch")


def _previous(root, registry, start, end):
    pointer = root / "CURRENT.json"
    if not pointer.exists():
        if (root / "1_kline_data").exists():
            raise ValueError("Use a separate versioned equity perpetual root")
        return None, {}
    current = json.loads(pointer.read_text())
    release_id = current.get("release_id")
    if (
        current.get("schema_version") != 1
        or not isinstance(release_id, str)
        or Path(release_id).name != release_id
        or release_id in {"", ".", ".."}
        or current.get("path") != f"releases/{release_id}"
        or any(
            p.is_symlink() for p in (pointer, root / "releases", root / current["path"])
        )
    ):
        raise ValueError("Invalid equity perpetual CURRENT pointer")
    path, manifest, _ = publication._previous(root)
    if (
        manifest.get("product_type") != PRODUCT_TYPE
        or manifest.get("registry") != registry
    ):
        raise ValueError(
            "Refusing to mix product types, symbols, or listing registries"
        )
    if start > source._utc(manifest["requested_start"]) or end < source._utc(
        manifest["end_exclusive"]
    ):
        raise ValueError("Refusing to narrow the last complete archive window")
    _verify_raw_files(root, manifest)
    return path, manifest


def run(
    *,
    data_dir,
    symbols="CXMTUSDT,UNITREEUSDT",
    registry=None,
    start_date="2010-01-01",
    end_date=None,
    max_retries=3,
    now=None,
):
    """Publish archive observations; 404 is explicit partial coverage, not success."""
    reviewed = _reviewed_registry(
        symbols.split(","), REGISTRY if registry is None else registry
    )
    observed = source._utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    start = source._utc(start_date)
    end = source._utc(end_date) if end_date else observed.normalize()
    if (
        start != start.normalize()
        or end != end.normalize()
        or not start < end <= observed.normalize()
    ):
        raise ValueError(
            "Require UTC midnight start < exclusive end <= today's UTC boundary"
        )
    if any(
        source._utc(item["listing_time"]).normalize() >= end
        for item in reviewed.values()
    ):
        raise ValueError("Requested window ends before a selected listing day")
    root = Path(data_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "releases").is_symlink() or (root / "raw").is_symlink():
        raise ValueError("Archive storage directories must not be symlinks")
    with (root / ".sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous_path, previous = _previous(root, reviewed, start, end)
        attempt_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ")
        raw = root / "raw" / attempt_id
        raw.mkdir(parents=True)
        attempt = {
            "status": "running",
            "product_type": PRODUCT_TYPE,
            "raw_path": str(raw.relative_to(root)),
            "started_at": observed.isoformat(),
            "symbols": list(reviewed),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        publication._json(root / "last_attempt.json", attempt)
        try:
            frames, missing, archives, coverage = [], [], [], {}
            for symbol, record in reviewed.items():
                listing = source._utc(record["listing_time"])
                first = max(start, listing.normalize())
                symbol_frames = []
                for period, left, right in _windows(first, end, observed):
                    try:
                        frame, receipt = _download(
                            symbol, period, left, right, raw / symbol, max_retries
                        )
                    except requests.HTTPError as exc:
                        if exc.response is None or exc.response.status_code != 404:
                            raise  # Restriction/auth failures stop this entire run; no fallback.
                        missing.append(
                            {
                                "symbol": symbol,
                                "period": period,
                                "start": left.isoformat(),
                                "end": right.isoformat(),
                                "url": exc.response.url,
                                "http_status": 404,
                                "reason": "expected_archive_not_published",
                            }
                        )
                        continue
                    archives.append(receipt)
                    if not frame.empty:
                        if (frame["open_time"] < listing.normalize()).any():
                            raise ValueError(
                                f"Archive predates reviewed listing: {symbol}"
                            )
                        frame = frame[
                            (frame.open_time >= first) & (frame.open_time < end)
                        ].copy()
                        if not frame.empty:
                            symbol_frames.append(frame)
                frame = source._combine_klines(symbol_frames, first, end, observed)
                expected = pd.date_range(first, end, inclusive="left")
                actual = (
                    pd.DatetimeIndex(frame["open_time"])
                    if not frame.empty
                    else pd.DatetimeIndex([], tz="UTC")
                )
                missing_days = expected.difference(actual).strftime("%Y-%m-%d").tolist()
                coverage[symbol] = {
                    "expected_rows": len(expected),
                    "rows": len(frame),
                    "missing_days": missing_days,
                    "listing_time": listing.isoformat(),
                    "first": str(actual.min().date()) if len(actual) else None,
                    "last": str(actual.max().date()) if len(actual) else None,
                }
                if frame.empty:
                    continue
                normal = publication._normalise_kline(frame, symbol)
                normal["product_type"] = PRODUCT_TYPE
                for key, value in record.items():
                    normal[key] = value
                normal["listing_time"] = listing
                normal["partial_listing_bar"] = (
                    normal["open_time"] == listing.normalize()
                ) & (listing != listing.normalize())
                normal["trading_start_lower_bound"] = normal["open_time"].where(
                    normal["open_time"] >= listing, listing
                )
                frames.append(normal)
            data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            complete = not missing and all(
                not item["missing_days"] for item in coverage.values()
            )
            if complete:
                publication.validate_daily(
                    data,
                    list(reviewed),
                    end.date(),
                    {
                        symbol: max(
                            start, source._utc(record["listing_time"]).normalize()
                        ).date()
                        for symbol, record in reviewed.items()
                    },
                )
            quality = {
                "status": "passed" if complete else "partial",
                "timezone": "UTC",
                "window_complete": complete,
                "history_complete": complete
                and all(
                    start <= source._utc(record["listing_time"]).normalize()
                    for record in reviewed.values()
                ),
                "rows": len(data),
                "symbols": coverage,
                "missing_archive_count": len(missing),
                "research_ready": False,
            }
            contract = {
                "schema_version": 1,
                "product_type": PRODUCT_TYPE,
                "venue": "binance",
                "frequency": "1d",
                "timezone": "UTC",
                "requested_start": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "symbols": list(reviewed),
                "registry": reviewed,
                "available_at_semantics": "bar_period_end_lower_bound",
                "point_in_time_verified": False,
                "history_complete_scope": "reviewed_listing_to_cutoff_public_archive_daily_bar_coverage",
                "numeric_semantics": publication.MANIFEST_SEMANTICS[
                    "numeric_semantics"
                ],
                "research_ready": False,
                "missing_datasets": MISSING_DATASETS,
                "price_adjustment": "none",
                "archive_source": ARCHIVE_ROOT,
                "quality": quality,
            }
            # Raw ZIP hashes bind all economic values; receipt times do not create revisions.
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        **contract,
                        "archives": [
                            {k: v for k, v in item.items() if k != "collected_at"}
                            for item in archives
                        ],
                        "missing": missing,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            if complete and previous.get("content_fingerprint") == fingerprint:
                result = {
                    "status": "completed",
                    "unchanged": True,
                    "release_id": previous["release_id"],
                    "data_dir": str(previous_path),
                    "quality": previous["quality"],
                    "research_ready": False,
                }
            else:
                release_id = f"equity-perpetual-{fingerprint[:24]}"
                final = root / "releases" / release_id
                reused = final.exists()
                final.parent.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(
                    prefix=".staging-", dir=root
                ) as directory:
                    staged = Path(directory) / release_id
                    staged.mkdir()
                    if not data.empty:
                        data["release_id"] = release_id
                        data["published_at"] = pd.Timestamp.now(tz="UTC").isoformat()
                        for day, chunk in data.groupby("time"):
                            publication._write_partition(
                                staged / "1_kline_data/daily_forward",
                                f"{day:%Y%m%d}",
                                chunk,
                            )
                    publication._json(staged / "quality.json", quality)
                    publication._json(
                        staged / "missing.json", {"files": missing, "symbols": coverage}
                    )
                    publication._json(staged / "registry.json", reviewed)
                    publication._json(staged / "archives.json", {"archives": archives})
                    manifest = {
                        **contract,
                        "status": "complete" if complete else "partial",
                        "release_id": release_id,
                        "content_fingerprint": fingerprint,
                        "data_start": str(data.time.min()) if not data.empty else None,
                        "data_end": str(data.time.max()) if not data.empty else None,
                        "columns": list(data.columns),
                        "published_at": pd.Timestamp.now(tz="UTC").isoformat(),
                        "raw_path": str(raw.relative_to(root)),
                        "raw_files": {
                            str(p.relative_to(root)): publication._sha(p)
                            for p in raw.rglob("*")
                            if p.is_file()
                        },
                        "files": {
                            str(p.relative_to(staged)): publication._sha(p)
                            for p in staged.rglob("*")
                            if p.is_file()
                        },
                    }
                    publication._json(staged / "manifest.json", manifest)
                    if reused:
                        # Identical partial replays retain their first immutable evidence.
                        prior = json.loads((final / "manifest.json").read_text())
                        if prior.get("content_fingerprint") != fingerprint or any(
                            prior.get(key) != value for key, value in contract.items()
                        ):
                            raise ValueError("Archive release identifier collision")
                        if (
                            final.is_symlink()
                            or any(p.is_symlink() for p in final.rglob("*"))
                            or {
                                str(p.relative_to(final))
                                for p in final.rglob("*")
                                if p.is_file() and p != final / "manifest.json"
                            }
                            != set(prior["files"])
                        ):
                            raise ValueError(
                                "Existing archive release inventory mismatch"
                            )
                        for name, digest in prior["files"].items():
                            target = final / name
                            if (
                                not target.resolve().is_relative_to(final)
                                or publication._sha(target) != digest
                            ):
                                raise ValueError(
                                    "Existing archive release checksum mismatch"
                                )
                        _verify_raw_files(root, prior)
                    else:
                        staged.rename(final)
                    if complete:
                        publication._json(
                            root / "CURRENT.json",
                            {
                                "schema_version": 1,
                                "release_id": release_id,
                                "path": str(final.relative_to(root)),
                                "manifest_sha256": publication._sha(
                                    final / "manifest.json"
                                ),
                            },
                        )
                result = {
                    "status": "completed" if complete else "partial",
                    "release_id": release_id,
                    "unchanged": reused,
                    "data_dir": str(final),
                    "quality": quality,
                    "research_ready": False,
                }
            attempt.update(result, finished_at=pd.Timestamp.now(tz="UTC").isoformat())
            try:
                publication._json(root / "last_attempt.json", attempt)
            except OSError as exc:
                result["journal_warning"] = str(exc)
            return result
        except Exception as exc:
            attempt.update(
                status="failed",
                error=str(exc),
                finished_at=pd.Timestamp.now(tz="UTC").isoformat(),
            )
            publication._json(root / "last_attempt.json", attempt)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True, help="Separate equity perpetual archive root"
    )
    parser.add_argument("--symbols", default="CXMTUSDT,UNITREEUSDT")
    parser.add_argument(
        "--registry", type=Path, help="Reviewed symbol-to-listing JSON mapping"
    )
    parser.add_argument("--start-date", default="2010-01-01")
    parser.add_argument("--end-date", help="Exclusive UTC day; default today")
    parser.add_argument("--max-retries", type=int, default=3)
    args = vars(parser.parse_args())
    if args["registry"]:
        args["registry"] = json.loads(args["registry"].read_text())
    result = run(**args)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
