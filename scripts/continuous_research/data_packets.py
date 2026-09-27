"""Bounded, read-only data evidence for GLM; never expose held-out values.

The two packets contain counts, dates and provenance, not prices, features or
returns. Hash only selected files, not the full frozen Qlib tree. Data writes,
upstream requests, model calls and research-admission changes are absent.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
import sys


def _sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Evidence source must be a physical file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _checked(path, relative, expected, checked):
    actual = _sha(path)
    if expected.get(relative) != actual:
        raise ValueError(f"Frozen input checksum mismatch: {relative}")
    checked.append({"path": relative, "sha256": actual})


def _bounded(path, column, start, end, columns):
    """Arrow filters before pandas parsing/statistics; no full-file fallback."""
    import pyarrow as pa
    import pyarrow.dataset as ds

    dataset = ds.dataset(str(path), format="parquet", partitioning=None)
    if column not in dataset.schema.names:
        raise ValueError(f"Missing date column: {path.name}")
    field = ds.field(column)
    kind = dataset.schema.field(column).type
    if pa.types.is_date(kind):
        expression = (field >= date.fromisoformat(start)) & (
            field <= date.fromisoformat(end)
        )
    elif pa.types.is_timestamp(kind):
        expression = (field >= datetime.combine(date.fromisoformat(start), time())) & (
            field <= datetime.combine(date.fromisoformat(end), time.max)
        )
    elif pa.types.is_integer(kind):
        expression = (field >= int(start.replace("-", ""))) & (
            field <= int(end.replace("-", ""))
        )
    elif pa.types.is_string(kind) or pa.types.is_large_string(kind):
        compact = (field >= start.replace("-", "")) & (field <= end.replace("-", ""))
        iso = (field >= start) & (field <= end + "T23:59:59.999999")
        expression = compact | iso
    else:
        raise ValueError(f"Unsupported date type: {kind}")
    return dataset.to_table(
        columns=[c for c in columns if c in dataset.schema.names],
        filter=expression,
    ).to_pandas()


def _dates(values):
    import pandas as pd

    text = values.astype(str).str.replace("-", "", regex=False).str[:8]
    return pd.to_datetime(text, format="%Y%m%d", errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )


def _numeric_counts(frame, columns):
    import numpy as np
    import pandas as pd

    out = {}
    for column in columns:
        if column not in frame:
            out[column] = {"status": "unknown", "reason": "column_absent"}
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        out[column] = {
            "status": "measured",
            "null_or_non_numeric": int(values.isna().sum()),
            "infinite": int(np.isinf(values).sum()),
            "zero": int((values == 0).sum()),
            "negative": int((values < 0).sum()),
        }
    return out


def _file_summary(checked):
    rows = sorted(checked, key=lambda row: row["path"])
    return {
        "files_verified": len(rows),
        "selected_path_hash_pairs_sha256": _json_hash(rows),
        "selection": "Only files selected by the declared scope; no full-tree audit",
    }


def _etf_packet(root, boundary, expected_manifest_sha256):
    import pandas as pd

    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from backend.services.simulation.replay.etf_input_package import (
        load_etf_input_package,
    )

    sums_path = root / "SHA256SUMS.txt"
    expected = {}
    for line in sums_path.read_text().splitlines():
        digest, relative = line.split(maxsplit=1)
        relative = relative.lstrip("*")
        if relative in expected or not (root / relative).resolve().is_relative_to(root):
            raise ValueError("Invalid ETF checksum inventory")
        expected[relative] = digest
    if expected.get("manifest.json") != expected_manifest_sha256:
        raise ValueError("ETF manifest does not match the research contract")
    checked = []
    _checked(root / "manifest.json", "manifest.json", expected, checked)
    pkg = load_etf_input_package(
        root,
        expect_manifest_sha256=expected_manifest_sha256,
        read_through=date.fromisoformat(boundary),
    )
    calendar_path = root / "calendar.parquet"
    _checked(calendar_path, "calendar.parquet", expected, checked)
    start = min(s["data_start"] for s in pkg.manifest["symbols"])
    calendar = _bounded(
        calendar_path, "cal_date", start, boundary, ["cal_date", "is_open"]
    )
    if "is_open" not in calendar:
        raise ValueError("ETF calendar lacks is_open")
    calendar["day"] = _dates(calendar.cal_date)
    sessions = set(
        calendar.loc[
            pd.to_numeric(calendar.is_open, errors="coerce") == 1, "day"
        ].dropna()
    )
    if not sessions:
        raise ValueError("No admitted ETF trading sessions")
    results = []
    for meta in pkg.manifest["symbols"]:
        symbol = meta["code"]
        left = meta["data_start"]
        if left > boundary:
            continue
        scope = {d for d in sessions if left <= d <= boundary}
        relative = f"daily/{symbol}.parquet"
        _checked(root / relative, relative, expected, checked)
        raw = _bounded(
            root / relative,
            "trade_date",
            left,
            boundary,
            [
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "vol_shares",
                "amount_cny",
            ],
        )
        raw["day"] = _dates(raw.trade_date)
        observed = set(raw.day.dropna())
        factor_relative = f"factors/{symbol}.parquet"
        factor_result = {"status": "unknown", "reason": "factor_file_absent"}
        if (root / factor_relative).is_file():
            _checked(root / factor_relative, factor_relative, expected, checked)
            factors = _bounded(
                root / factor_relative,
                "trade_date",
                left,
                boundary,
                ["trade_date", "adj_factor"],
            )
            factors["day"] = _dates(factors.trade_date)
            factor_dates = set(factors.day.dropna())
            factor_result = {
                "status": "measured",
                "rows": len(factors),
                "duplicate_dates": int(factors.day.duplicated().sum()),
                "missing_for_daily_dates": len(observed - factor_dates),
                "missing_date_examples": sorted(observed - factor_dates)[:12],
                "values": _numeric_counts(factors, ["adj_factor"]),
            }
        event_relative = f"events/{symbol}.parquet"
        if (root / event_relative).is_file():
            _checked(root / event_relative, event_relative, expected, checked)
            events = pkg.events_for(symbol)
            cash = [e for e in events if e.event_type == "cash_dividend"]
            event_result = {
                "status": "parsed_by_public_consumer",
                "events": len(events),
                "cash_dividends": len(cash),
                "blocked_cash_dividends": sum(e.blocked for e in cash),
                "unresolved_events": sum(
                    e.verification.get("method") == "unresolved_gap" for e in events
                ),
                "failed_verification_events": sum(
                    e.verification.get("passed") is not True for e in events
                ),
                "duplicate_event_keys": len(events)
                - len(
                    {
                        e.dividend_idempotency_key
                        if e.event_type == "cash_dividend"
                        else e.idempotency_key
                        for e in events
                    }
                ),
                "record_ex_pay_order_invalid": sum(
                    not (e.record_date <= e.event_date <= e.pay_date)
                    for e in cash
                    if e.record_date and e.pay_date
                ),
                "announcement_availability_verified": False,
            }
        else:
            event_result = {"status": "unknown", "reason": "event_file_absent"}
        results.append(
            {
                "symbol": symbol,
                "scope_start": left,
                "scope_end": boundary,
                "raw_rows": len(raw),
                "observed_days": len(observed),
                "first_observed": min(observed) if observed else None,
                "last_observed": max(observed) if observed else None,
                "expected_open_days": len(scope),
                "missing_open_days": len(scope - observed),
                "missing_day_examples": sorted(scope - observed)[:12],
                "non_calendar_days": len(observed - sessions),
                "duplicate_dates": int(raw.day.duplicated().sum()),
                "invalid_admitted_dates": int(raw.day.isna().sum()),
                "fields": _numeric_counts(
                    raw, ["open", "high", "low", "close", "vol_shares", "amount_cny"]
                ),
                "factors": factor_result,
                "corporate_actions": event_result,
            }
        )
    return {
        "topic": "data_coverage",
        "question": "固定ETF开发段的行情、复权和分红数据是否支持当前研究？哪些缺口会改变结论？",
        "reason": "在原始缺值被执行reader补值之前核验完整性，区分数据洞、零成交与未知可交易性。",
        "evidence": {
            "title": "ETF固定包开发段原始数据审计",
            "boundary": boundary,
            "sources": [
                {"path": "etf/manifest.json", "sha256": expected["manifest.json"]},
                {"path": "etf/SHA256SUMS.txt", "sha256": _sha(sums_path)},
                {"path": "code/data_packets.py", "sha256": _sha(Path(__file__))},
            ],
            "data": {
                "package_id": pkg.package_id,
                "package_version": pkg.package_version,
                "source_release_id": pkg.manifest["source_release_id"],
                "calendar_sessions": len(sessions),
                "symbols": results,
                "source_verification": _file_summary(checked),
                "raw_prices_features_returns_exposed": False,
            },
            "limitations": [
                "data_start为包内首行，不是权威上市日；上市前后及历史全市场完整性未知。",
                "只核验截至boundary的内容，不读取保留段统计或绩效；整文件哈希只是固定身份。",
                "过滤器无法归属日期的原始行不计入窗口；invalid_admitted_dates不代表全文件无坏日期。",
                "零成交或缺行不能单独判定停牌；涨跌停与开盘可成交性未在本包检查中证明。",
                "现金分红按登记日保权，已登记但除息/支付跨界的事件允许保留；不展示跨界日期。",
                "事件可被公共解析器消费，不等于公告在当时已知；PIT及历史修订仍未知。",
                "缺失没有ffill或填零；公共执行reader会补量额及复权，不能用其补值后结果证明原始完整。",
            ],
        },
    }


def _stock_packet(contract, universe_path, expected_universe_sha256):
    from io import BytesIO

    import numpy as np
    import pandas as pd

    root = Path(contract["source"]).resolve()
    boundary = contract["boundary"]
    manifest_path = root / "manifest.json"
    digest = _sha(manifest_path)
    if digest != contract["manifest_sha256"]:
        raise ValueError("Stock manifest does not match the research contract")
    manifest = json.loads(manifest_path.read_text())
    expected = {e["path"]: e["sha256"] for e in manifest["files"]}
    cfg = contract["base_config"]
    features = cfg["features"]
    start = cfg["split"]["train"][0]
    from backend.shared.stock_utils import StockCodeUtil

    universe_bytes = universe_path.read_bytes()
    if hashlib.sha256(universe_bytes).hexdigest() != expected_universe_sha256:
        raise ValueError("Stock universe does not match the frozen baseline artifact")
    universe = pd.read_csv(BytesIO(universe_bytes), usecols=["symbol"])
    symbols = [StockCodeUtil.to_prefix(str(v)) for v in universe.symbol]
    if len(set(symbols)) != len(symbols) or len(symbols) != cfg["universe"]["size"]:
        raise ValueError("Universe differs from frozen research pool size")
    selected = set(symbols)
    checked = []
    calendar_relative = "qlib/calendars/day.txt"
    _checked(
        root / "snapshot" / calendar_relative, calendar_relative, expected, checked
    )
    sessions = {
        line.strip()
        for line in (root / "snapshot" / calendar_relative).read_text().splitlines()
        if start <= line.strip() <= boundary
    }
    if not sessions:
        raise ValueError("Frozen stock calendar has no admitted sessions")
    frames = []
    partitions = []
    # Manifest selects already-frozen partitions, never glob the entire tree.
    for relative in sorted(expected):
        prefix = "quantdb/6_ml_datasets/l1_factors/dt="
        if not relative.startswith(prefix) or not relative.endswith(".parquet"):
            continue
        partition_day = relative[len(prefix) :].split("/", 1)[0]
        if not start.replace("-", "") <= partition_day <= boundary.replace("-", ""):
            continue
        path = root / "snapshot" / relative
        if not path.resolve().is_relative_to(root / "snapshot"):
            raise ValueError("Invalid stock manifest path")
        _checked(path, relative, expected, checked)
        raw = _bounded(
            path,
            "date",
            start,
            boundary,
            ["symbol", "date", "open", "close", "volume", "amount", *features],
        )
        if "symbol" not in raw:
            raise ValueError("Frozen stock factors have no symbol")
        # Public reader canonicalizes symbols only after dropping duplicates;
        # normalize first here to expose alias collisions as raw duplicates.
        valid_symbol = raw.symbol.notna()
        raw = raw.loc[valid_symbol].copy()
        raw["symbol"] = raw.symbol.map(lambda s: StockCodeUtil.to_prefix(str(s)))
        raw = raw[raw.symbol.isin(selected)].copy()
        raw["trade_date"] = _dates(raw.date)
        frames.append(raw)
        partitions.append(partition_day)
    if not frames:
        raise ValueError("No admitted frozen stock factor partitions")
    frame = pd.concat(frames, ignore_index=True)
    duplicate_count = int(frame.duplicated(["symbol", "trade_date"]).sum())
    symbol_coverage = []
    for symbol in symbols:
        group = frame[frame.symbol == symbol]
        observed = set(group.trade_date.dropna())
        symbol_coverage.append(
            {
                "symbol": symbol,
                "rows": len(group),
                "observed_days": len(observed),
                "missing_calendar_days": len(sessions - observed),
                "missing_day_examples": sorted(sessions - observed)[:12],
                "non_calendar_days": len(observed - sessions),
            }
        )
    split_counts = {}
    for name, (left, right) in cfg["split"].items():
        right = min(right, boundary)
        sample = frame[(frame.trade_date >= left) & (frame.trade_date <= right)]
        split_counts[name] = {
            "start": left,
            "end": right,
            "rows": len(sample),
            "duplicate_keys": int(sample.duplicated(["symbol", "trade_date"]).sum()),
            "features": _numeric_counts(sample, features),
        }
    invalid_close = None
    if {"volume", "close"} <= set(frame):
        volume = pd.to_numeric(frame.volume, errors="coerce")
        close = pd.to_numeric(frame.close, errors="coerce")
        invalid_close = int(((volume > 0) & (~np.isfinite(close) | (close <= 0))).sum())
    return {
        "topic": "data_semantics",
        "question": "冻结100股八特征的开发段缺失、重复和时点假设会怎样影响因子研究？应先排除哪些不可证明的解释？",
        "reason": "以现有股票池为分母核验原始因子输入，避免去重、补行情和训练插补掩盖数据问题。",
        "evidence": {
            "title": "固定股票池八特征开发段原始数据审计",
            "boundary": boundary,
            "sources": [
                {"path": "stock/manifest.json", "sha256": digest},
                {"path": "research/universe.csv", "sha256": expected_universe_sha256},
                {"path": "code/data_packets.py", "sha256": _sha(Path(__file__))},
            ],
            "data": {
                "snapshot_id": contract["snapshot_id"],
                "scope_start": start,
                "scope_end": boundary,
                "universe_size": len(symbols),
                "features": features,
                "calendar_sessions": len(sessions),
                "factor_partitions_read": len(partitions),
                "raw_rows": len(frame),
                "duplicate_keys": duplicate_count,
                "invalid_positive_volume_close": invalid_close,
                "fields": _numeric_counts(
                    frame, ["open", "close", "volume", "amount", *features]
                ),
                "splits": split_counts,
                "symbol_coverage": symbol_coverage,
                "source_verification": _file_summary(checked),
                "pit_verified": False,
                "historical_revisions_verified": False,
                "raw_prices_features_returns_exposed": False,
            },
            "limitations": [
                "仅检查已冻结股票池和l1_factors原列；不重选股票池、不调用训练、不计算收益。",
                "分母是固定Qlib日历，不含逐日上市退市/停牌权威分类，缺行不能直接等同采集失败。",
                "source manifest固定文件身份，不证明供应商因子历史版本及当时可得性；PIT未知。",
                "raw统计在公共reader的drop_duplicates、行情COALESCE和训练中位数插补之前计算。",
                "空symbol/不能归属日期的行无法分配到固定池窗口，不计作已验证完整；这部分未知。",
                "未重扫Qlib特征二进制，不证明复权事件覆盖、历史ST/涨跌停、退市幸存偏差或实盘可成交。",
                "只验证所选分区的清单哈希，不重新验全47k文件；未使用2026-03-25之后内容统计。",
            ],
        },
    }


def build_packets(
    etf_root,
    stock_contract,
    universe_path,
    *,
    expected_etf_manifest_sha256,
    expected_universe_sha256,
):
    """Return two JSON evidence packets bound to the caller's accepted identities.

    Expected hashes must come from the programme contract and corresponding
    frozen baseline artifact record, never from the files being inspected.
    """
    boundary = stock_contract["boundary"]
    if boundary != "2026-03-24":
        raise ValueError("This audit is bound to the current development cutoff")
    root = Path(etf_root).resolve()
    universe_path = Path(universe_path)
    # Check both identities before any potentially expensive content scans.
    if _sha(root / "manifest.json") != expected_etf_manifest_sha256:
        raise ValueError("ETF manifest does not match the research contract")
    if _sha(universe_path) != expected_universe_sha256:
        raise ValueError("Stock universe does not match the frozen baseline artifact")
    return [
        _etf_packet(root, boundary, expected_etf_manifest_sha256),
        _stock_packet(stock_contract, universe_path, expected_universe_sha256),
    ]


def _self_test():
    """One small fixture probes raw duplicates/missingness and holdout isolation."""
    import tempfile
    import shutil
    import pandas as pd

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "raw.parquet"
        pd.DataFrame(
            {
                "date": ["20260323", "20260323", "20260324", "20260325"],
                "feature": [1.0, None, 3.0, 999999.0],
            }
        ).to_parquet(path, index=False)
        raw = _bounded(path, "date", "2026-03-01", "2026-03-24", ["date", "feature"])
        assert len(raw) == 3
        assert _dates(raw.date).duplicated().sum() == 1
        assert _numeric_counts(raw, ["feature"])["feature"]["null_or_non_numeric"] == 1
        assert "999999" not in json.dumps(_numeric_counts(raw, ["feature"]))
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-03-24", "2026-03-25"]),
                "feature": [3, 999999],
            }
        ).to_parquet(path, index=False)
        assert len(_bounded(path, "date", "2026-03-01", "2026-03-24", ["date"])) == 1
        checked = []
        _checked(path, "raw.parquet", {"raw.parquet": _sha(path)}, checked)
        try:
            _checked(path, "raw.parquet", {"raw.parquet": "bad"}, checked)
        except ValueError:
            pass
        else:
            raise AssertionError("Changed source was admitted")
        etf = Path(directory) / "etf"
        (etf / "daily").mkdir(parents=True)
        (etf / "factors").mkdir()
        pd.DataFrame(
            {"cal_date": ["20260323", "20260324", "20260325"], "is_open": [1, 1, 1]}
        ).to_parquet(etf / "calendar.parquet", index=False)
        pd.DataFrame(
            {
                "trade_date": ["20260323", "20260323", "20260324", "20260325"],
                "close": [1.0, None, 2.0, 999999.0],
                "vol_shares": [1, 1, 0, 1],
                "amount_cny": [1.0, None, 0.0, 999999.0],
            }
        ).to_parquet(etf / "daily/510300.SH.parquet", index=False)
        pd.DataFrame(
            {"trade_date": ["20260323", "20260325"], "adj_factor": [1.0, 999999.0]}
        ).to_parquet(etf / "factors/510300.SH.parquet", index=False)
        (etf / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "package_id": "fixture-data-packet",
                    "package_version": "v2",
                    "package_uri": "node://test/package",
                    "source_release_id": "fixture",
                    "generated_at": "2026-03-24T00:00:00Z",
                    "generated_by_node": "test",
                    "source_datasets": [{"api_name": "fund_daily", "sha256": "0" * 64}],
                    "unit_conversions": {},
                    "factor_convention": "hfq",
                    "known_gaps": [],
                    "symbols": [{"code": "510300.SH", "data_start": "2026-03-23"}],
                }
            )
        )
        (etf / "SHA256SUMS.txt").write_text(
            "".join(
                f"{_sha(p)}  {p.relative_to(etf).as_posix()}\n"
                for p in sorted(etf.rglob("*"))
                if p.is_file()
            )
        )
        stock = Path(directory) / "stock"
        snapshot = stock / "snapshot"
        (snapshot / "qlib/calendars").mkdir(parents=True)
        (snapshot / "qlib/calendars/day.txt").write_text(
            "2026-03-23\n2026-03-24\n2026-03-25\n"
        )
        partition = snapshot / "quantdb/6_ml_datasets/l1_factors/dt=20260323"
        partition.mkdir(parents=True)
        pd.DataFrame(
            {
                "date": ["20260323", "20260323", "20260324", "20260325"],
                "symbol": ["SH600036", "600036.SH", "SZ000001", "SZ000001"],
                "feature": [1.0, None, 2.0, 999999.0],
                "volume": [1, 1, 0, 999999],
                "close": [1, 1, 2, 999999],
            }
        ).to_parquet(partition / "data.parquet", index=False)
        future = snapshot / "quantdb/6_ml_datasets/l1_factors/dt=20260325"
        future.mkdir()
        (future / "data.parquet").write_bytes(
            b"future partition must not even be opened"
        )
        (stock / "manifest.json").write_text(
            json.dumps(
                {
                    "files": [
                        {"path": p.relative_to(snapshot).as_posix(), "sha256": _sha(p)}
                        for p in sorted(snapshot.rglob("*"))
                        if p.is_file()
                    ]
                }
            )
        )
        universe = Path(directory) / "universe.csv"
        universe.write_text("symbol\nSH600036\nSZ000001\n")
        contract = {
            "source": str(stock),
            "boundary": "2026-03-24",
            "snapshot_id": "fixture",
            "manifest_sha256": _sha(stock / "manifest.json"),
            "base_config": {
                "features": ["feature"],
                "universe": {"size": 2},
                "split": {"train": ["2026-03-23", "2026-03-24"]},
            },
        }
        expected_etf = _sha(etf / "manifest.json")
        expected_universe = _sha(universe)
        packets = build_packets(
            etf,
            contract,
            universe,
            expected_etf_manifest_sha256=expected_etf,
            expected_universe_sha256=expected_universe,
        )
        etf_data = packets[0]["evidence"]["data"]["symbols"][0]
        assert etf_data["raw_rows"] == 3 and etf_data["duplicate_dates"] == 1
        assert etf_data["factors"]["missing_for_daily_dates"] == 1
        assert etf_data["fields"]["close"]["null_or_non_numeric"] == 1
        stock_data = packets[1]["evidence"]["data"]
        assert stock_data["raw_rows"] == 3 and stock_data["duplicate_keys"] == 1
        assert stock_data["factor_partitions_read"] == 1
        assert stock_data["fields"]["feature"]["null_or_non_numeric"] == 1
        assert "999999" not in json.dumps(packets)
        wrong_universe = Path(directory) / "same-size-wrong-pool.csv"
        wrong_universe.write_text("symbol\nSH600036\nSZ000002\n")
        assert len(pd.read_csv(wrong_universe)) == len(pd.read_csv(universe))
        other_etf = Path(directory) / "another-valid-etf"
        shutil.copytree(etf, other_etf)
        other_manifest = json.loads((other_etf / "manifest.json").read_text())
        other_manifest["package_id"] = "fixture-another-data-packet"
        (other_etf / "manifest.json").write_text(json.dumps(other_manifest))
        (other_etf / "SHA256SUMS.txt").write_text(
            "".join(
                f"{_sha(p)}  {p.relative_to(other_etf).as_posix()}\n"
                for p in sorted(other_etf.rglob("*"))
                if p.is_file() and p.name != "SHA256SUMS.txt"
            )
        )
        # The alternate package passes its own checks, but is not this programme's input.
        _etf_packet(
            other_etf.resolve(), contract["boundary"], _sha(other_etf / "manifest.json")
        )
        for etf_input, pool_input, expected_error in (
            (etf, wrong_universe, "Stock universe does not match"),
            (other_etf, universe, "ETF manifest does not match"),
        ):
            try:
                build_packets(
                    etf_input,
                    contract,
                    pool_input,
                    expected_etf_manifest_sha256=expected_etf,
                    expected_universe_sha256=expected_universe,
                )
            except ValueError as exc:
                assert str(exc).startswith(expected_error)
            else:
                raise AssertionError("Valid but unbound input was admitted")
    print(
        "data_packets self-test PASS: two packets, cutoff isolation, raw duplicates/missing, "
        "hashes, same-size wrong pool and alternate valid ETF rejected"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error(
            "Import build_packets(..., expected_etf_manifest_sha256=..., "
            "expected_universe_sha256=...)"
        )
    _self_test()
