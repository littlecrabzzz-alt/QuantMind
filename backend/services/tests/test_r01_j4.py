"""R01P0-J4E1 测试：跨包恢复与日增量身份（合并包绑定/前缀兼容/重建）。

场景（合成基线=工程 fixture 包 + 两个日增量 d20251001/d20251002，
d20251002 含 159934 份额折算日）：
- checkpoint → 发布 d+1 包 → 恢复 → 继续运行 == 连续运行（含折算日）
- 未绑定的新包对恢复运行不可见
- 篡改清单/哈希 → 恢复拒绝；非前缀/换基线 → 拒绝
- 绑定捕获/schema v5/extend_binding 显式消费
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
    extend_binding,
    rebuild_bound_package,
)
from backend.services.simulation.replay.etf_input_package import (
    build_fixture_package,
)
from backend.services.simulation.replay.r01_ledger import (
    CheckpointPackageMismatch,
    DaySummary,
    R01Ledger,
    R01LedgerConfig,
)

SYM = "159934.SZ"
D_SEED, D_BASE_END = date(2025, 9, 29), date(2025, 9, 30)
D1, D2 = date(2025, 10, 1), date(2025, 10, 2)
FOLD_MULT = 0.9481


def _config():
    return R01LedgerConfig(
        group="A", strategy_id="j4-daily", strategy_version=1,
        execution_attempt_id=1, initial_cash=20000.0,
        commission_rate=0.0003, commission_min=0.1, slippage_bps=0.0,
    )


def _write_increment(root: Path, day: date, close: float, *, fold: bool = False):
    (root / "daily").mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "factors").mkdir(parents=True, exist_ok=True)
    ds = day.strftime("%Y%m%d")
    rows = [{
        "ts_code": SYM, "trade_date": ds,
        "open": round(close * 0.999, 4), "high": round(close * 1.003, 4),
        "low": round(close * 0.997, 4), "close": close,
        "pre_close": close, "vol_shares": 5_000_000.0, "amount_cny": close * 5_000_000,
    }]
    pd.DataFrame(rows).to_parquet(root / "daily" / f"{SYM}.parquet", index=False)
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


@pytest.fixture()
def env(tmp_path):
    baseline = build_fixture_package(tmp_path / "baseline")
    inc1_root = tmp_path / "inc1"
    inc2_root = tmp_path / "inc2"
    _write_increment(inc1_root, D1, 5.700)
    _write_increment(inc2_root, D2, 6.010, fold=True)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"packages": {
        baseline.package_uri: {
            "absolute_path": str(tmp_path / "baseline"),
            "package_id": baseline.package_id,
            "package_version": baseline.package_version,
        },
        f"node://mac/r01-etf-daily/{dversion(D1)}": {
            "absolute_path": str(inc1_root), "package_id": "r01-daily-20251001",
            "package_version": dversion(D1), "kind": "daily_increment",
        },
        f"node://mac/r01-etf-daily/{dversion(D2)}": {
            "absolute_path": str(inc2_root), "package_id": "r01-daily-20251002",
            "package_version": dversion(D2), "kind": "daily_increment",
        },
    }}, ensure_ascii=False), encoding="utf-8")
    # J5E1：绑定用真实 manifest sha256（空/None 哈希恢复会被拒绝）
    from backend.services.simulation.replay.etf_input_package import sha256_of_file

    sha1 = sha256_of_file(inc1_root / "manifest.json")
    sha2 = sha256_of_file(inc2_root / "manifest.json")
    binding_base = {
        "baseline": {"package_id": baseline.package_id, "manifest_sha256": baseline.manifest_sha256},
        "increments": [],
    }
    b1 = extend_binding(binding_base, {"package_version": dversion(D1), "manifest_sha256": sha1})
    b2 = extend_binding(b1, {"package_version": dversion(D2), "manifest_sha256": sha2})
    return {
        "baseline": baseline, "registry": registry,
        "b0": binding_base, "b1": b1, "b2": b2,
        "sha": {"d1": sha1, "d2": sha2},
        "roots": {"inc1": inc1_root, "inc2": inc2_root},
    }


def _seed_and_run(led, until: date):
    o = led.submit_order(D_SEED, SYM, "buy", 100)
    bars = led.package.load_date(D_SEED)
    led._validate_and_execute(o, D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
    led._eod(D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
    for d in led.package.trade_dates():
        if D_SEED < d <= until:
            led.run_day(d, None)
    return led


class TestCrossPackageRecovery:
    def test_publish_d2_then_restore_continue_equals_continuous(self, env):
        """J3R 第 2 项：checkpoint → 发布 d+1 包 → 恢复 → 继续运行 ==
        连续运行（两日以上，含折算日 d20251002）。"""
        cfg = _config()
        cache = None
        # 连续运行：绑定 [d1,d2] 重建后一次跑完（含折算日）
        pkg_full = rebuild_bound_package(env["b2"], registry_path=env["registry"])
        full = _seed_and_run(R01Ledger(pkg_full, cfg), D2)
        assert full.positions[SYM].qty == pytest.approx(100 * FOLD_MULT)  # 折算已发生

        # 分段运行：先绑定 [d1]（d2 已发布但未消费）
        pkg1 = rebuild_bound_package(env["b1"], registry_path=env["registry"])
        part = _seed_and_run(R01Ledger(pkg1, cfg, input_binding=env["b1"]), D1)
        cp = part.export_checkpoint()
        assert cp["schema_version"] == 5
        assert cp["input_binding"]["increments"][-1]["package_version"] == dversion(D1)

        # 恢复：按绑定清单重建（d2 不可见）→ 恢复成功
        pkg1_again = rebuild_bound_package(env["b1"], registry_path=env["registry"])
        restored = R01Ledger.restore(pkg1_again, cfg, cp)
        # 显式消费 d2：扩展绑定 → 重建扩展包 → 前缀兼容恢复 → 运行折算日
        pkg2 = rebuild_bound_package(env["b2"], registry_path=env["registry"])
        restored.input_binding = env["b2"]  # 消费新阶段：更新绑定
        restored.package = pkg2  # runner 注入扩展视图（已执行日数据不变）
        for d in pkg2.trade_dates():
            if D1 < d <= D2:
                restored.run_day(d, None)

        assert len(restored.equity) == len(full.equity)
        for r, f in zip(restored.equity, full.equity, strict=True):
            assert r["nav"] == pytest.approx(f["nav"], abs=1e-9), f["trade_date"]
        assert restored.positions[SYM].qty == pytest.approx(full.positions[SYM].qty)
        assert restored.equity[-1]["nav"] == pytest.approx(full.equity[-1]["nav"], abs=1e-9)

    def test_unconsumed_new_package_invisible(self, env):
        """未绑定的新包对恢复运行不可见：重建包日历不含 d2、身份不含 +d2。"""
        pkg1 = rebuild_bound_package(env["b1"], registry_path=env["registry"])
        assert pkg1.package_id.endswith(f"+{dversion(D1)}")
        assert not pkg1.is_trade_date(D2)
        led = _seed_and_run(R01Ledger(pkg1, _config(), input_binding=env["b1"]), D1)
        with pytest.raises(Exception, match="not_trade_date"):
            led.run_day(D2, None)  # d2 已发布但未消费 → 不可见

    def test_tampered_binding_rejected(self, env):
        pkg1 = rebuild_bound_package(env["b1"], registry_path=env["registry"])
        led = _seed_and_run(R01Ledger(pkg1, _config(), input_binding=env["b1"]), D1)
        cp = led.export_checkpoint()

        # 篡改清单：换版本
        bad = json.loads(json.dumps(cp))
        bad["input_binding"]["increments"][0]["package_version"] = dversion(D2)
        with pytest.raises(CheckpointPackageMismatch, match="版本不一致"):
            R01Ledger.restore(pkg1, _config(), bad)
        # 篡改基线
        bad2 = json.loads(json.dumps(cp))
        bad2["input_binding"]["baseline"]["package_id"] = "other-baseline"
        with pytest.raises(CheckpointPackageMismatch, match="基线不一致"):
            R01Ledger.restore(pkg1, _config(), bad2)
        # 非前缀：checkpoint 消费 [d1,d2] 而包只有 [d1]
        pkg_full = rebuild_bound_package(env["b2"], registry_path=env["registry"])
        led_full = _seed_and_run(R01Ledger(pkg_full, _config(), input_binding=env["b2"]), D2)
        cp_full = led_full.export_checkpoint()
        with pytest.raises(CheckpointPackageMismatch, match="短于"):
            R01Ledger.restore(pkg1, _config(), cp_full)
        # 缺绑定字段（旧 schema）
        bad3 = json.loads(json.dumps(cp))
        bad3.pop("input_binding")
        with pytest.raises(CheckpointPackageMismatch, match="input_binding"):
            R01Ledger.restore(pkg1, _config(), bad3)

    def test_baseline_only_checkpoint_restores_on_baseline(self, env):
        """基线期检查点：绑定无增量 → 基线包恢复 OK；扩展到 [d1] 前缀兼容。"""
        cfg = _config()
        base = env["baseline"]
        led = R01Ledger(base, cfg, input_binding=env["b0"])
        o = led.submit_order(D_SEED, SYM, "buy", 100)
        bars = base.load_date(D_SEED)
        led._validate_and_execute(o, D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
        led._eod(D_SEED, bars, DaySummary(trade_date=D_SEED.isoformat()))
        led.run_day(D_BASE_END, None)
        cp = led.export_checkpoint()
        assert cp["input_binding"]["increments"] == []
        # 基线包恢复
        r1 = R01Ledger.restore(base, cfg, cp)
        assert r1.package.package_id == base.package_id
        # 扩展 [d1]：前缀兼容（空清单是任意清单前缀）
        pkg1 = rebuild_bound_package(env["b1"], registry_path=env["registry"])
        r2 = R01Ledger.restore(pkg1, cfg, cp)
        r2.input_binding = env["b1"]
        r2.package = pkg1
        for d in pkg1.trade_dates():
            if d > D_BASE_END:
                r2.run_day(d, None)
        assert D1.isoformat() in r2._executed_dates

    def test_capture_and_compatible_semantics(self, env):
        pkg2 = rebuild_bound_package(env["b2"], registry_path=env["registry"])
        cap = capture_binding(pkg2)
        assert cap["baseline"]["package_id"] == env["baseline"].package_id
        assert [i["package_version"] for i in cap["increments"]] == [dversion(D1), dversion(D2)]
        # 前缀兼容矩阵
        ok, _ = binding_compatible(capture_binding(pkg2), env["b1"])
        assert ok  # [d1] ⊆ [d1,d2]
        ok, _ = binding_compatible(capture_binding(pkg2), env["b2"])
        assert ok
        pkg1 = rebuild_bound_package(env["b1"], registry_path=env["registry"])
        ok, why = binding_compatible(capture_binding(pkg1), env["b2"])
        assert not ok and "短于" in why
        # extend_binding 不改原绑定（真实哈希）
        b1 = extend_binding(
            env["b0"],
            {"package_version": dversion(D1), "manifest_sha256": env["sha"]["d1"]},
        )
        assert env["b0"]["increments"] == []
        assert b1["increments"][-1]["package_version"] == dversion(D1)
        # J5E1：空/None 哈希 → 拒绝（不跳过校验）
        bad_none = extend_binding(env["b0"], {"package_version": dversion(D1), "manifest_sha256": None})
        ok, why = binding_compatible(cap, bad_none)
        assert not ok and "缺失/为空" in why
