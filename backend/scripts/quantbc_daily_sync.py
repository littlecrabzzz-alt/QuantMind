#!/usr/bin/env python3
"""区块链数据同步入口 — 套用 QuantDB 同步流程，从 Binance 拉取并落盘 parquet。

用法:
  python backend/scripts/quantbc_daily_sync.py --days 365
  python backend/scripts/quantbc_daily_sync.py --symbols BTCUSDT,ETHUSDT --days 30
  python backend/scripts/quantbc_daily_sync.py --build-research  # 发布后构建日线 Qlib/H5，不启动研究
"""

from __future__ import annotations

import sys
import json

from backend.scripts.blockchain_sync import run as _blockchain_run


def run(
    *,
    days: int = 365,
    symbols: str | None = None,
    skip_valuation: bool = False,
    minute_freqs: tuple[str, ...] | None = None,
    minute_days: int | None = None,
    datasets: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str = "rest",
    product_type: str = "crypto_spot",
    refresh_history: bool = False,
    build_research: bool = False,
) -> dict:
    """供后台管理 API 调用的编程接口。"""
    unsupported = set(datasets or []) - {"daily_forward", "instrument_detail"}
    if unsupported:
        raise ValueError(f"Versioned daily intake does not produce datasets: {sorted(unsupported)}")
    result = _blockchain_run(
        days=days,
        symbols=symbols,
        skip_valuation=skip_valuation,
        minute_freqs=minute_freqs,
        minute_days=minute_days,
        start_date=start_date,
        end_date=end_date,
        source=source,
        product_type=product_type,
        refresh_history=refresh_history,
    )
    if not isinstance(result, dict):
        result = {"result": result}
    # Published raw releases are immutable. Derived research input stays outside them.
    if build_research:
        result["research_data"] = prepare_research_data(result["data_dir"])
    return result


def prepare_research_data(data_dir=None) -> dict:
    """Build only release-bound data artifacts; never start a factor/strategy run."""
    from backend.services.engine.rd_agent.market_adapters.crypto import CryptoAdapter
    from backend.services.engine.rd_agent.rd_loop_wrapper import RDLoopWrapper
    from backend.services.engine.data_platform.quantbc_hub import quantbc_derived_dir

    adapter = CryptoAdapter(data_dir)
    release = adapter.get_release_dir()
    if not adapter.prepare_data() or not adapter.is_data_ready():
        raise RuntimeError("Crypto daily Qlib preparation failed")
    derived = quantbc_derived_dir(release)
    wrapper = RDLoopWrapper("crypto")
    wrapper.adapter = adapter
    for debug, name in ((False, "daily_pv_all.h5"), (True, "daily_pv_debug.h5")):
        if not wrapper._generate_h5_from_parquet(str(release), str(derived / name), debug=debug):
            raise RuntimeError("Crypto daily H5 preparation failed")
    return {
        "status": "complete", "release_id": release.name,
        "qlib_dir": adapter.get_qlib_provider_uri(), "h5_dir": str(derived),
    }


def _cli() -> int:
    from backend.scripts.blockchain_sync import main

    build_research = "--build-research" in sys.argv
    if build_research:
        sys.argv.remove("--build-research")
    result = main()
    if result == 0 and build_research:
        print(json.dumps(prepare_research_data(), ensure_ascii=False))
    return result


if __name__ == "__main__":
    sys.exit(_cli())
