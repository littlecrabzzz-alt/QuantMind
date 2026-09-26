"""QuantBC 区块链数据平台测试。

策略：
- 不联网；不依赖 Binance API 的真实响应
- 校验 K 线标准化（Binance → QuantDB schema）
- 校验分区写入（dt=YYYYMMDD/data.parquet，增量去重）
- 校验管理控制台 BC 数据集目录（_default_datasets("BC")）
"""

from __future__ import annotations

import pandas as pd
import pytest
from datetime import date

from backend.scripts.blockchain_sync import (
    KLINE_COLS,
    DEFAULT_SYMBOLS,
    _normalise_kline,
    _normalise_minute_kline,
    _write_partition,
    _write_symbol_file,
)


def test_default_symbols_include_major_pairs():
    assert "BTCUSDT" in DEFAULT_SYMBOLS
    assert "ETHUSDT" in DEFAULT_SYMBOLS
    assert DEFAULT_SYMBOLS == ["BTCUSDT", "ETHUSDT"]


def test_normalise_kline_columns_and_values():
    from backend.tests.test_binance_release import frame

    df = _normalise_kline(frame().iloc[:1], symbol="BTCUSDT")
    assert list(df.columns) == KLINE_COLS
    row = df.iloc[0]
    assert row["symbol"] == "BTCUSDT"
    assert row["close"] == 105
    assert row["amount"] == 1025  # Original quote volume; close * volume would be 1050.
    assert str(row["time"]) == "2026-09-22"
    assert str(row["open_time"].tz) == "UTC"


def test_normalise_kline_rejects_missing_native_amount():
    from backend.tests.test_binance_release import frame

    with pytest.raises(ValueError, match="Missing original"):
        _normalise_kline(frame().drop(columns="quote_volume"), symbol="BTCUSDT")


def test_normalise_minute_kline_preserves_timestamp():
    from backend.tests.test_binance_release import frame

    raw = frame().iloc[:2].copy()
    raw["open_time"] = pd.to_datetime(["2026-08-01T00:05:00Z", "2026-08-01T00:10:00Z"])
    df = _normalise_minute_kline(raw, symbol="BTCUSDT")
    assert df["time"].dt.hour.tolist() == [0, 0]
    assert df["time"].dt.minute.tolist() == [5, 10]
    assert len(df) == 2
    assert list(df.columns) == KLINE_COLS


def test_write_symbol_file_dedups_on_full_timestamp(tmp_path):
    root = tmp_path / "min5_kline"
    chunk1 = pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "time": pd.to_datetime(["2026-08-01 00:05:00", "2026-08-01 00:10:00"]),
            "close": [100.0, 101.0],
            "release_id": ["binance", "binance"],
        }
    )
    _write_symbol_file(root, "BTCUSDT", chunk1)
    # 增量：同一根 5m 时间戳应被覆盖，不同时间戳追加
    chunk2 = pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "time": pd.to_datetime(["2026-08-01 00:05:00", "2026-08-01 00:15:00"]),
            "close": [100.5, 102.0],
            "release_id": ["binance", "binance"],
        }
    )
    _write_symbol_file(root, "BTCUSDT", chunk2)
    merged = pd.read_parquet(root / "BTCUSDT.parquet")
    assert len(merged) == 3
    assert (
        merged[merged["time"] == pd.Timestamp("2026-08-01 00:05:00")]["close"].iloc[0]
        == 100.5
    )


def test_write_partition_incremental_dedup(tmp_path):
    root = tmp_path / "1_kline_data" / "daily_forward"
    chunk1 = pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "ETHUSDT"],
            "time": [date(2026, 8, 1), date(2026, 8, 1)],
            "close": [100.0, 5.0],
            "release_id": ["binance", "binance"],
        }
    )
    target = _write_partition(root, "20260801", chunk1)
    assert target.is_file()

    # 增量写入同一分区：同一 (symbol, time) 应被覆盖而非新增
    chunk2 = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"],
            "time": [date(2026, 8, 1)],
            "close": [105.0],
            "release_id": ["binance"],
        }
    )
    _write_partition(root, "20260801", chunk2)
    merged = pd.read_parquet(target)
    assert len(merged) == 2  # BTCUSDT 被覆盖，不新增
    btc = merged[merged["symbol"] == "BTCUSDT"].iloc[0]
    assert btc["close"] == 105.0


def test_market_console_bc_datasets():
    from backend.services.api.routers.admin.global_market_console import (
        _default_datasets,
    )

    specs = _default_datasets("BC")
    names = {s.dataset for s in specs}
    # 区块链数据段精简：日线/估值/标的详情等，无财务/分析师段
    assert "daily_forward" in names
    assert "valuation" in names
    assert "instrument_detail" in names
    assert "min5_kline" in names
    assert "min1_kline" in names
    assert "income" not in names
    assert "recommendations" not in names
    # 日线必须按日分区，估值也是分区；分钟线按标的
    by_name = {s.dataset: s for s in specs}
    assert by_name["daily_forward"].layout == "partition"
    assert by_name["valuation"].layout == "partition"
    assert by_name["min5_kline"].layout == "symbol"
