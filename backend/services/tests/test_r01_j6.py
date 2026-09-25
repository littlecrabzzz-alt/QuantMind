"""R01P0-J6E2 测试：daily_binding 热缓存命中路径的篡改拒绝。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backend.services.simulation.replay.daily_binding import (
    dversion,
    extend_binding,
    rebuild_bound_package,
)
from backend.services.simulation.replay.etf_input_package import (
    EtfInputPackageError,
    build_fixture_package,
    sha256_of_file,
)

SYM = "159934.SZ"
D1 = date(2025, 10, 1)


def _write_increment(root: Path, day: date, close: float = 5.7):
    (root / "daily").mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "factors").mkdir(parents=True, exist_ok=True)
    ds = day.strftime("%Y%m%d")
    pd.DataFrame([{
        "ts_code": SYM, "trade_date": ds,
        "open": round(close * 0.999, 4), "high": round(close * 1.003, 4),
        "low": round(close * 0.997, 4), "close": close,
        "pre_close": close, "vol_shares": 5_000_000.0, "amount_cny": close * 5_000_000,
    }]).to_parquet(root / "daily" / f"{SYM}.parquet", index=False)
    pd.DataFrame([{"ts_code": SYM, "trade_date": ds, "adj_factor": 1.05}]).to_parquet(
        root / "factors" / f"{SYM}.parquet", index=False
    )
    pd.DataFrame([], columns=["symbol", "event_date", "event_type"]).to_parquet(
        root / "events" / f"{SYM}.parquet", index=False
    )
    manifest = {
        "schema_version": 3, "package_id": f"r01-daily-{ds}",
        "package_version": dversion(day),
        "package_uri": f"node://mac/r01-etf-daily/{dversion(day)}",
        "source_release_id": "fixture-release", "generated_at": "2026-10-01T00:00:00Z",
        "generated_by_node": "mac",
        "source_datasets": [{"api_name": "fund_daily", "sha256": "0" * 64}],
        "unit_conversions": {
            "vol": "lot(100 shares) -> shares, multiply by 100",
            "amount": "thousand CNY -> CNY, multiply by 1000", "rules": "fixture",
        },
        "factor_convention": {
            "formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
            "verified_cases": [],
        },
        "symbols": [{
            "code": SYM, "class": "gold", "role": "regression-only",
            "data_start": day.isoformat(), "data_end": day.isoformat(),
            "missing_days": [], "warmup_start": day.isoformat(),
        }],
        "known_gaps": [], "data_as_of": day.isoformat(),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.fixture()
def env(tmp_path):
    baseline = build_fixture_package(tmp_path / "baseline")
    inc1 = tmp_path / "inc1"
    _write_increment(inc1, D1)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"packages": {
        baseline.package_uri: {
            "absolute_path": str(tmp_path / "baseline"),
            "package_id": baseline.package_id,
            "package_version": baseline.package_version,
        },
        f"node://mac/r01-etf-daily/{dversion(D1)}": {
            "absolute_path": str(inc1), "package_id": "r01-daily-20251001",
            "package_version": dversion(D1), "kind": "daily_increment",
        },
    }}, ensure_ascii=False), encoding="utf-8")
    b0 = {
        "baseline": {"package_id": baseline.package_id, "manifest_sha256": baseline.manifest_sha256},
        "increments": [],
    }
    b1 = extend_binding(
        b0,
        {"package_version": dversion(D1), "manifest_sha256": sha256_of_file(inc1 / "manifest.json")},
    )
    return {"baseline": baseline, "registry": registry, "b1": b1, "inc1": inc1, "tmp": tmp_path}


class TestWarmCacheTamperRejection:
    def test_cache_hit_rejects_tampered_increment(self, env):
        """先正常加载入缓存 → 篡改包内容（manifest）→ 再次加载 → 拒绝。"""
        cache = env["tmp"] / "cache"
        pkg_a = rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)
        assert (cache).is_dir() and any(cache.glob("*/manifest.json"))  # 已入缓存

        # 热缓存命中且未篡改：正常返回（校验通过）
        pkg_b = rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)
        assert pkg_b.package_id == pkg_a.package_id

        # 篡改增量 manifest 内容（绑定不变）
        mpath = env["inc1"] / "manifest.json"
        m = json.loads(mpath.read_text(encoding="utf-8"))
        m["data_as_of"] = "2025-10-01Ttampered"
        mpath.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

        # 再次加载（缓存仍在）：命中路径必须执行期望绑定校验 → 拒绝
        with pytest.raises(EtfInputPackageError, match="热缓存命中同样校验"):
            rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)

    def test_cache_hit_rejects_swapped_registry_target(self, env):
        """换包：注册表条目改指另一目录 → 命中路径拒绝。"""
        cache = env["tmp"] / "cache2"
        rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)
        other = env["tmp"] / "inc-other"
        _write_increment(other, date(2025, 10, 2), close=6.0)  # 不同内容
        data = json.loads(env["registry"].read_text(encoding="utf-8"))
        data["packages"][f"node://mac/r01-etf-daily/{dversion(D1)}"]["absolute_path"] = str(other)
        env["registry"].write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EtfInputPackageError, match="不一致"):
            rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)

    def test_untampered_hit_returns_cached_identity(self, env):
        """未篡改命中：同缓存对象、清单哈希仍为真实值。"""
        from backend.services.simulation.replay.daily_binding import capture_binding

        cache = env["tmp"] / "cache3"
        pkg1 = rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)
        pkg2 = rebuild_bound_package(env["b1"], registry_path=env["registry"], cache_dir=cache)
        cap = capture_binding(pkg2)
        assert cap["increments"][0]["manifest_sha256"] == env["b1"]["increments"][0]["manifest_sha256"]
        assert pkg1.manifest_sha256 == pkg2.manifest_sha256  # 缓存确定性
