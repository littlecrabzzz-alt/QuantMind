#!/usr/bin/env python3
"""Offline fixed-release coordinate acceptance using the frozen author's algorithm."""

import argparse
from contextlib import ExitStack
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import socket
import sys
import types
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from verify_tushare_rrg_slice import read_dataset, verify  # noqa: E402

AUTHOR_REVISION = "558536af13715aa13fd2131eaf90c70d32108a38"
AUTHOR_SHA256 = "e40e22afe36ad61215f66a48e0e16d64f384ac04c465cf4db28f24388dd78402"


def load_author(path):
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != AUTHOR_SHA256:
        raise ValueError("Frozen author factor_algo.py fingerprint mismatch")
    module = types.ModuleType("frozen_rrg_factor_algo")
    # Compile verified bytes directly: no source-directory import or pycache writes.
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def price_panel(rows, days, codes):
    frame = pd.DataFrame(rows)
    if frame.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("Duplicate price observation")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    prices = frame.pivot(index="trade_date", columns="ts_code", values="close")
    prices = prices.reindex(index=days, columns=codes).astype(float)
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError("Missing or invalid price; filling is forbidden")
    return prices


def check_coordinates(prices, author, parameters):
    kwargs = {
        "lookback_ratio": parameters["ratio_lookback"],
        "lookback_mom": parameters["momentum_lookback"],
        "smooth_window": parameters["smooth_window"],
    }
    warmup = (
        kwargs["lookback_ratio"]
        + kwargs["lookback_mom"]
        + 2 * (kwargs["smooth_window"] - 1)
    )

    def compute(frame):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            return author.compute_rrg(
                frame, author.equal_weight_benchmark(frame), **kwargs
            )

    ratio, momentum = compute(prices)
    if not momentum.iloc[:warmup].isna().all().all():
        raise ValueError("Unexpected pre-warmup momentum")
    for result in (ratio, momentum):
        if not np.isfinite(result.iloc[warmup:].to_numpy()).all():
            raise ValueError("Nonfinite coordinate after warmup")

    cutoffs = sorted({warmup, (warmup + len(prices) - 1) // 2, len(prices) - 2})
    for end in cutoffs:
        prefix = compute(prices.iloc[: end + 1])
        changed = prices.copy()
        changed.iloc[end + 1 :] *= np.linspace(0.2, 8.0, len(prices.columns))
        perturbed = compute(changed)
        for reference, truncated, mutated in zip(
            (ratio, momentum), prefix, perturbed, strict=True
        ):
            pd.testing.assert_frame_equal(reference.iloc[: end + 1], truncated)
            pd.testing.assert_frame_equal(
                reference.iloc[: end + 1], mutated.iloc[: end + 1]
            )
    scaled = compute(prices * np.linspace(0.3, 11, len(prices.columns)))
    for reference, result in zip((ratio, momentum), scaled, strict=True):
        pd.testing.assert_frame_equal(reference, result, rtol=1e-10, atol=1e-10)
    identical = pd.DataFrame(
        dict.fromkeys(prices.columns, prices.iloc[:, 0]), index=prices.index
    )
    for result in compute(identical):
        np.testing.assert_allclose(result.iloc[warmup:], 100, rtol=1e-10, atol=1e-10)
    try:
        compute(prices.iloc[:warmup])
    except ValueError:
        pass
    else:
        raise AssertionError("Author accepted fewer than minimum observations")
    return (
        ratio,
        momentum,
        {
            "first_valid_momentum": prices.index[warmup].strftime("%Y-%m-%d"),
            "warmup_sessions": warmup,
            "truncation_and_future_perturbation_cutoffs": [
                prices.index[end].strftime("%Y-%m-%d") for end in cutoffs
            ],
            "per_industry_scale_invariance": True,
            "identical_paths_center_100": True,
            "insufficient_history_rejected": True,
        },
    )


def consume(root, release_id, config, author):
    protocol = config["protocol"]
    if config["source"]["revision"] != AUTHOR_REVISION:
        raise ValueError("Research config author revision differs")
    if protocol["benchmark"] != "同分类行业日收益等权累乘":
        raise ValueError("Unsupported benchmark protocol")
    if protocol["min_price_observations"] != protocol["warmup_sessions"] + 1:
        raise ValueError("Inconsistent minimum observations")
    audit = verify(root, release_id, config)
    if audit["status"] != "slice_structure_passed":
        raise ValueError("Fixed price/calendar slice has unresolved structural gaps")
    table = read_dataset(root, release_id, "ci_daily", **audit["queries"]["ci_daily"])
    calendar = read_dataset(
        root, release_id, "trade_cal", **audit["queries"]["trade_cal"]
    )
    start = audit["calendar"]["warmup_start"]
    days = pd.DatetimeIndex(
        sorted(
            {
                pd.to_datetime(row["cal_date"], format="%Y%m%d")
                for row in calendar.to_pylist()
                if row["exchange"] == "SSE"
                and str(row["is_open"]) == "1"
                and str(row["cal_date"]) >= start
            }
        )
    )
    rows = table.to_pylist()
    prices = price_panel(rows, days, audit["included_codes"])
    pd.testing.assert_frame_equal(
        prices, price_panel(list(reversed(rows)), days, audit["included_codes"])
    )
    included = [row for row in rows if row["ts_code"] in audit["included_codes"]]
    for missing in (included[1:], [{**row, "close": None} for row in included]):
        try:
            price_panel(missing, days, audit["included_codes"])
        except ValueError:
            pass
        else:
            raise AssertionError("Missing-price fixture accepted")
    ratio, momentum, checks = check_coordinates(prices, author, protocol["parameters"])
    checks.update(row_order_invariance=True, missing_and_null_prices_rejected=True)
    first, last = protocol["comparison_window"]
    ratio, momentum = ratio.loc[first:last], momentum.loc[first:last]
    coordinates = ratio.stack().rename("rs_ratio").to_frame()
    coordinates["rs_momentum"] = momentum.stack()
    coordinates = coordinates.reset_index().rename(columns={"level_0": "trade_date"})
    coordinates["trade_date"] = coordinates["trade_date"].dt.strftime("%Y%m%d")
    coordinates["release_id"] = release_id
    month_ends = (
        pd.Series(ratio.index, index=ratio.index)
        .groupby(ratio.index.to_period("M"))
        .last()
    )
    mapping = []
    for day in month_ends:
        following = days[days > day]
        mapping.append(
            {
                "signal_close_date": day.strftime("%Y-%m-%d"),
                "next_open_date": following[0].strftime("%Y-%m-%d")
                if len(following)
                else None,
                "status": "calendar_mapped_only"
                if len(following)
                else "next_session_outside_verified_slice",
            }
        )
    report = {
        "status": "coordinate_consumer_passed",
        "rrg_status": "blocked_data",
        "release_id": release_id,
        "author_revision": AUTHOR_REVISION,
        "author_sha256": AUTHOR_SHA256,
        "parameters": protocol["parameters"],
        "comparison_window": protocol["comparison_window"],
        "included_codes": audit["included_codes"],
        "excluded_codes": audit["excluded_codes"],
        "price_rows": len(prices) * len(prices.columns),
        "coordinate_rows": len(coordinates),
        "checks": checks,
        "slice_audit": audit,
        "month_end_mapping": mapping,
        "remaining_gaps": [
            "Official historical CITIC definitions, price methodology and revisions",
            "Member known_at, adjusted stock prices and free-float capitalization for breadth",
            "Historical ETF universe, exposures and executable open-price semantics",
            "Next session after final comparison month-end is outside this verified slice",
            "Quadrant boundaries, ties, portfolio/cash weights and independent test period",
        ],
    }
    return report, coordinates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--author-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    if output.exists() or any(
        base == output or base in output.parents for base in (root, REPO)
    ):
        raise ValueError("Output must be new and outside input/repository directories")
    with ExitStack() as guards:
        mocks = [
            guards.enter_context(
                patch.object(
                    socket.socket,
                    "connect",
                    side_effect=AssertionError("Network forbidden"),
                )
            ),
            guards.enter_context(
                patch.object(
                    socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
                )
            ),
            guards.enter_context(
                patch(
                    "backend.shared.runtime_secrets.get_secret",
                    side_effect=AssertionError("Credentials forbidden"),
                )
            ),
            guards.enter_context(
                patch(
                    "backend.shared.tushare_pipeline.get_secret",
                    side_effect=AssertionError("Credentials forbidden"),
                )
            ),
        ]
        report, coordinates = consume(
            root,
            args.release_id,
            json.loads(args.config.read_bytes()),
            load_author(args.author_source),
        )
        for mock in mocks:
            mock.assert_not_called()
    report.update(upstream_calls=0, credentials_accessed=False)
    report["runtime"] = {
        "python": sys.version.split()[0],
        **{
            package: version(package)
            for package in ("pandas", "numpy", "duckdb", "pyarrow")
        },
    }
    report["source_hashes"] = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in {
            "config": args.config,
            "consumer": Path(__file__),
            "slice_verifier": REPO / "scripts/verify_tushare_rrg_slice.py",
            "store": REPO / "backend/shared/tushare_store.py",
        }.items()
    }
    output.mkdir(parents=True, exist_ok=False)
    coordinates.to_csv(output / "coordinates.csv", index=False)
    report["coordinates_sha256"] = hashlib.sha256(
        (output / "coordinates.csv").read_bytes()
    ).hexdigest()
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "rows": len(coordinates),
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    main()
