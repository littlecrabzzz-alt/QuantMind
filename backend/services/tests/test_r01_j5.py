"""R01P0-J5E1 测试：绑定哈希必须真实 + 逐包发布逐段恢复（真实注册表）。

- 绑定捕获/重建清单哈希=真实 manifest sha256（None/空 → 恢复拒绝）
- 篡改任一增量内容（manifest 变更）→ 重建期哈希不一致拒绝
- 换包（注册表指向不同内容）→ 拒绝
- checkpoint → 逐包发布 d+1、d+2（真实注册表追加条目）→ 逐段恢复 →
  继续运行 == 连续运行（不手动换包；前缀扩展用真实哈希）
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backend.services.simulation.replay.daily_binding import (
    binding_compatible,
    capture_binding,
    dversion,
    rebuild_bound_package,
)
from backend.services.simulation.replay.etf_input_package import (
    EtfInputPackageError,
    build_fixture_package,
    sha256_of_file,
)
from backend.services.simulation.replay.r01_ledger import (
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
)

SYM = "159934.SZ"
D_SEED = date(2025, 9, 29)
D1, D2 = date(2025, 10, 1), date(2025, 10, 2)
FOLD_MULT = 0.9481


def _config():
    return R01LedgerConfig(
        group="A", strategy_id="j5-daily", strategy_version=1,
        execution_attempt_id=1, initial_cash=20000.0,
        commission_rate=0.0003, commission_min=0.1, slippage_bps=0.0,
    )


def _write_increment(root: Path, day: date, close: float, *, fold: bool = False):
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
    events = []
    if fold:
        events.append({
            "symbol": SYM, "event_date": day.isoformat(),
            "event_type": "share_adjustment", "cash_per_share": 0.0,
            "qty_multiplier": FOLD_MULT,
            "derived_from": {"adj_factor_prev": 1.05, "adj_factor_new": round(1.05 * FOLD_MULT, 6)},
            "verification": {"passed": True, "method": "pre_close_continuity"},
        })
    pd.DataFrame(
        events,
        columns=["symbol", "event_date", "event_type", "cash_per_share",
                 "qty_multiplier", "derived_from", "verification"],
    ).to_parquet(root / "events" / f"{SYM}.parquet", index=False)
    manifest = {
        "schema_version": 3,
        "package_id": f"r01-daily-{ds}",
        "package_version": dversion(day),
        "package_uri": f"node://mac/r01-etf-daily/{dversion(day)}",
        "source_release_id": "fixture-release",
        "generated_at": "2026-10-01T00:00:00Z",
        "generated_by_node": "mac",
        "source_datasets": [{"api_name": "fund_daily", "sha256": "0" * 64}],
        "unit_conversions": {
            "vol": "lot(100 shares) -> shares, multiply by 100",
            "amount": "thousand CNY -> CNY, multiply by 1000",
            "rules": "fixture increment",
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
        "known_gaps": [],
        "data_as_of": day.isoformat(),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _publish(registry: Path, baseline, root: Path, day: date):
    """真实发布：向节点注册表追加日增量条目（uri→absolute_path+kind）。"""
    data = json.loads(registry.read_text(encoding="utf-8"))
    data.setdefault("packages", {})[f"node://mac/r01-etf-daily/{dversion(day)}"] = {
        "absolute_path": str(root), "package_id": f"r01-daily-{day.strftime('%Y%m%d')}",
        "package_version": dversion(day), "kind": "daily_increment",
    }
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _binding_for(baseline_pkg, registry: Path, days: list[date]):
    """从重建包捕获绑定（真实哈希由重建记录）。"""
    binding = {
        "baseline": {
            "package_id": baseline_pkg.package_id,
            "manifest_sha256": baseline_pkg.manifest_sha256,
        },
        "increments": [],
    }
    if not days:
        return binding
    from backend.services.simulation.replay.daily_binding import extend_binding

    for d in days:
        sha = sha256_of_file(_inc_root(registry, d) / "manifest.json")
        binding = extend_binding(binding, {"package_version": dversion(d), "manifest_sha256": sha})
    return binding


def _inc_root(registry: Path, day: date) -> Path:
    data = json.loads(registry.read_text(encoding="utf-8"))
    e = data["packages"][f"node://mac/r01-etf-daily/{dversion(day)}"]
    return Path(e["absolute_path"])


def _seed_and_run(led, until: date):
    o = led.submit_order(D_SEED, SYM, "buy", 100)
    bars = led.package.load_date(D_SEED)
    led._validate_and_execute(o, D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
    led._eod(D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
    for d in led.package.trade_dates():
        if D_SEED < d <= until:
            led.run_day(d, None)
    return led


@pytest.fixture()
def env(tmp_path):
    baseline = build_fixture_package(tmp_path / "baseline")
    inc1 = tmp_path / "inc1"
    inc2 = tmp_path / "inc2"
    _write_increment(inc1, D1, 5.700)
    _write_increment(inc2, D2, 6.010, fold=True)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"packages": {
        baseline.package_uri: {
            "absolute_path": str(tmp_path / "baseline"),
            "package_id": baseline.package_id,
            "package_version": baseline.package_version,
        },
    }}, ensure_ascii=False), encoding="utf-8")
    return {"tmp": tmp_path, "baseline": baseline, "registry": registry,
            "inc1": inc1, "inc2": inc2}


class TestRealHashBinding:
    def test_capture_hashes_are_real(self, env):
        """注册表发布 d1/d2 后：捕获清单哈希=各增量真实 manifest sha256。"""
        _publish(env["registry"], env["baseline"], env["inc1"], D1)
        _publish(env["registry"], env["baseline"], env["inc2"], D2)
        b2 = _binding_for(env["baseline"], env["registry"], [D1, D2])
        pkg2 = rebuild_bound_package(b2, registry_path=env["registry"])
        cap = capture_binding(pkg2)
        assert all(i["manifest_sha256"] for i in cap["increments"])
        assert cap["increments"][0]["manifest_sha256"] == b2["increments"][0]["manifest_sha256"]
        assert cap["increments"][1]["manifest_sha256"] == b2["increments"][1]["manifest_sha256"]

    def test_tampered_increment_content_rejected(self, env):
        """篡改增量内容（manifest 变更）→ 重建期哈希不一致拒绝。"""
        _publish(env["registry"], env["baseline"], env["inc1"], D1)
        b1 = _binding_for(env["baseline"], env["registry"], [D1])
        pkg1 = rebuild_bound_package(b1, registry_path=env["registry"])
        led = _seed_and_run(R01Ledger(pkg1, _config(), input_binding=b1), D1)
        cp = led.export_checkpoint()
        # 篡改：增量 manifest 内容被改（如版本备注/数据字段）
        mpath = env["inc1"] / "manifest.json"
        m = json.loads(mpath.read_text(encoding="utf-8"))
        m["data_as_of"] = "2025-10-01Ttampered"
        mpath.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EtfInputPackageError, match="不一致"):
            rebuild_bound_package(b1, registry_path=env["registry"])

    def test_swapped_package_rejected(self, env):
        """换包：d1 注册表条目改指另一包（d2 内容）→ 哈希不一致拒绝。"""
        _publish(env["registry"], env["baseline"], env["inc1"], D1)
        b1 = _binding_for(env["baseline"], env["registry"], [D1])
        rebuild_bound_package(b1, registry_path=env["registry"])
        # 换包：d1 条目指向 inc2 的目录
        data = json.loads(env["registry"].read_text(encoding="utf-8"))
        data["packages"][f"node://mac/r01-etf-daily/{dversion(D1)}"]["absolute_path"] = str(env["inc2"])
        env["registry"].write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EtfInputPackageError, match="不一致"):
            rebuild_bound_package(b1, registry_path=env["registry"])

    def test_empty_hash_binding_rejected_on_restore(self, env):
        """绑定哈希为空/None → 恢复显式拒绝（不跳过校验）。"""
        _publish(env["registry"], env["baseline"], env["inc1"], D1)
        b1 = _binding_for(env["baseline"], env["registry"], [D1])
        pkg1 = rebuild_bound_package(b1, registry_path=env["registry"])
        led = _seed_and_run(R01Ledger(pkg1, _config(), input_binding=b1), D1)
        cp = led.export_checkpoint()
        # 清洗：抹掉增量哈希 → 恢复拒绝
        bad = json.loads(json.dumps(cp))
        bad["input_binding"]["increments"][0]["manifest_sha256"] = None
        from backend.services.simulation.replay.r01_ledger import CheckpointPackageMismatch

        with pytest.raises(CheckpointPackageMismatch, match="缺失/为空"):
            R01Ledger.restore(pkg1, _config(), bad)


class TestSequentialPublishRecovery:
    def test_publish_d1_then_d2_stage_by_stage_equals_continuous(self, env):
        """逐包发布 d+1、d+2 → 逐段恢复 → 继续 == 连续运行（真实注册表，
        不手动换包；d2 为折算日）。"""
        cfg = _config()
        # 连续基线：先发布两包，一次跑完
        _publish(env["registry"], env["baseline"], env["inc1"], D1)
        _publish(env["registry"], env["baseline"], env["inc2"], D2)
        b2 = _binding_for(env["baseline"], env["registry"], [D1, D2])
        pkg_full = rebuild_bound_package(b2, registry_path=env["registry"])
        full = _seed_and_run(R01Ledger(pkg_full, cfg, input_binding=b2), D2)

        # 逐段：注册表重置回基线 → 发布 d1 → 跑到 d1 → checkpoint
        env["registry"].write_text(json.dumps({"packages": {
            env["baseline"].package_uri: {
                "absolute_path": str(env["tmp"] / "baseline"),
                "package_id": env["baseline"].package_id,
                "package_version": env["baseline"].package_version,
            },
        }}, ensure_ascii=False), encoding="utf-8")
        # 基线段（建仓）
        b0 = _binding_for(env["baseline"], env["registry"], [])
        led = R01Ledger(env["baseline"], cfg, input_binding=b0)
        o = led.submit_order(D_SEED, SYM, "buy", 100)
        bars = env["baseline"].load_date(D_SEED)
        led._validate_and_execute(o, D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
        led._eod(D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
        led.run_day(date(2025, 9, 30), None)
        cp0 = led.export_checkpoint()

        # 发布 d1 → 前缀恢复（空清单前缀）→ 跑 d1 → checkpoint
        _publish(env["registry"], env["baseline"], env["inc1"], D1)
        b1 = _binding_for(env["baseline"], env["registry"], [D1])
        pkg1 = rebuild_bound_package(b1, registry_path=env["registry"])
        r1 = R01Ledger.restore(pkg1, cfg, cp0)
        r1.input_binding = b1
        r1.package = pkg1
        for d in pkg1.trade_dates():
            if date(2025, 9, 30) < d <= D1:
                r1.run_day(d, None)
        cp1 = r1.export_checkpoint()

        # 发布 d2 → 恢复（绑定 [d1]，d2 未消费不可见）→ 扩展 [d1,d2] → 跑折算日
        _publish(env["registry"], env["baseline"], env["inc2"], D2)
        pkg1_again = rebuild_bound_package(b1, registry_path=env["registry"])
        r2 = R01Ledger.restore(pkg1_again, cfg, cp1)
        assert not r2.package.is_trade_date(D2)  # 未消费不可见
        b2b = _binding_for(env["baseline"], env["registry"], [D1, D2])
        pkg2 = rebuild_bound_package(b2b, registry_path=env["registry"])
        r3 = R01Ledger.restore(pkg2, cfg, cp1)  # 前缀恢复（真实哈希链）
        r3.input_binding = b2b
        r3.package = pkg2
        for d in pkg2.trade_dates():
            if D1 < d <= D2:
                r3.run_day(d, None)

        # 与连续运行逐日全等（含折算日）
        assert len(r3.equity) == len(full.equity)
        for a, b in zip(r3.equity, full.equity, strict=True):
            assert a["nav"] == pytest.approx(b["nav"], abs=1e-9), b["trade_date"]
        assert r3.positions[SYM].qty == pytest.approx(full.positions[SYM].qty)
