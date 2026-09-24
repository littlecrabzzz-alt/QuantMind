"""R01-P0.3 测试：ETF 资产类别规则（XG-001 / TG-006 / 撮合价格档与部分成交）。

覆盖：
- StockCodeUtil 裸六位 ETF 前缀自动识别（51/52/56/58→SH、15/16→SZ）
- asset_type 维度规则表：ETF 无印花税/过户费、佣金最低收费可配、
  T+0 品种（债券 511*/跨境 513*/黄金 518*/深市黄金 15993*）
- 撮合器：ETF 价格档 0.001、整手约束、现金约束部分成交（qty_remaining）、
  默认行为不变（allow_partial=False 整单拒绝）
- ETF 固定输入包：manifest 校验、manifest_sha256 校验、typed 事件解析
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.simulation.services.ashare_matcher import (
    MatchConfig,
    compute_fees,
    match_order,
)
from backend.services.simulation.services.local_market_data import DailyBar
from backend.services.simulation.services.market_rules import (
    AssetType,
    asset_type_for_symbol,
    etf_settlement_days_for_symbol,
    rules_for_asset_type,
)
from backend.shared.stock_utils import StockCodeUtil


# ---------------------------------------------------------------------------
# XG-001：ETF 前缀自动识别
# ---------------------------------------------------------------------------


class TestEtfPrefixRecognition:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("510300", "510300.SH"),
            ("510500", "510500.SH"),
            ("520500", "520500.SH"),
            ("560000", "560000.SH"),
            ("588000", "588000.SH"),
            ("159915", "159915.SZ"),
            ("160000", "160000.SZ"),
        ],
    )
    def test_bare_etf_code_to_suffix(self, code, expected):
        assert StockCodeUtil.to_suffix(code) == expected

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("510300", "SH510300"),
            ("588000", "SH588000"),
            ("159915", "SZ159915"),
        ],
    )
    def test_bare_etf_code_to_prefix(self, code, expected):
        assert StockCodeUtil.to_prefix(code) == expected

    # 既有口径不变（防回归）
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("600036", "600036.SH"),
            ("688001", "688001.SH"),
            ("000001", "000001.SZ"),
            ("300750", "300750.SZ"),
            ("830000", "830000.BJ"),
            ("SH600036", "600036.SH"),
        ],
    )
    def test_existing_codes_unchanged(self, code, expected):
        assert StockCodeUtil.to_suffix(code) == expected

    def test_unknown_prefix_still_passthrough(self):
        # 无归属段仍原样返回（不猜测）
        assert StockCodeUtil.to_suffix("730000") == "730000"


# ---------------------------------------------------------------------------
# asset_type 规则表
# ---------------------------------------------------------------------------


class TestAssetTypeRules:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("510300.SH", AssetType.ETF),
            ("159915.SZ", AssetType.ETF),
            ("588000.SH", AssetType.ETF),
            ("600036.SH", AssetType.EQUITY),
            ("300750.SZ", AssetType.EQUITY),
        ],
    )
    def test_asset_type_for_symbol(self, symbol, expected):
        assert asset_type_for_symbol(symbol) is expected

    def test_etf_rules_no_stamp_no_transfer(self):
        rules = rules_for_asset_type(AssetType.ETF)
        assert rules.stamp_duty_rate == 0.0
        assert rules.transfer_fee_rate == 0.0
        assert rules.price_tick == 0.001
        assert rules.lot_size == 100

    def test_etf_commission_min_configurable(self):
        default = rules_for_asset_type(AssetType.ETF)
        assert default.commission_min == 0.0  # 默认无最低档
        # 券商假设：最低 5 元（DG-011 敏感性）
        with_min = rules_for_asset_type(AssetType.ETF, commission_min=5.0)
        assert with_min.commission_min == 5.0
        assert with_min.commission_rate == default.commission_rate
        # 费率也可配
        custom = rules_for_asset_type(AssetType.ETF, commission_rate=0.0001)
        assert custom.commission_rate == 0.0001

    # 验证池 T+0/T+1 口径
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("511010.SH", 0),   # 国债 ETF
            ("511260.SH", 0),   # 国债 ETF
            ("511090.SH", 0),   # 国债 ETF
            ("518880.SH", 0),   # 黄金 ETF
            ("159934.SZ", 0),   # 深市黄金 ETF
            ("513500.SH", 0),   # 跨境 ETF
            ("510300.SH", 1),   # 宽基 T+1
            ("510500.SH", 1),
            ("159915.SZ", 1),
            ("588000.SH", 1),   # 科创宽基 T+1
        ],
    )
    def test_settlement_days(self, symbol, expected):
        assert etf_settlement_days_for_symbol(symbol) == expected


# ---------------------------------------------------------------------------
# 撮合器：ETF 费用 / 价格档 / 部分成交
# ---------------------------------------------------------------------------


def _bar(symbol="510300.SH", open_=4.0, close=4.0, limit_up=None, limit_down=None, volume=1e7):
    return DailyBar(
        symbol=symbol,
        trade_date=date(2025, 9, 10),
        open=open_,
        high=max(open_, close) * 1.005,
        low=min(open_, close) * 0.995,
        close=close,
        volume=volume,
        amount=close * volume,
        vwap=close,
        pre_close=close,
        limit_up=limit_up if limit_up is not None else close * 1.1,
        limit_down=limit_down if limit_down is not None else close * 0.9,
        is_st=False,
        suspended=volume <= 0,
    )


class TestMatcherEtfRules:
    def test_etf_fees_zero_stamp_and_transfer_both_sides(self):
        cfg = MatchConfig(price_mode="open", asset_type="etf")
        for side in ("buy", "sell"):
            commission, stamp, transfer, total = compute_fees(
                10000, 4.0, side, cfg, "510300.SH"
            )
            assert stamp == 0.0
            assert transfer == 0.0
            assert commission == pytest.approx(10000 * 4.0 * 0.0003)
            assert total == commission

    def test_etf_commission_min_applies(self):
        cfg = MatchConfig(price_mode="open", asset_type="etf", commission_min=5.0)
        commission, _, _, _ = compute_fees(100, 4.0, "buy", cfg, "510300.SH")
        # 100×4×0.0003 = 0.12 < 5 → 最低档 5 元
        assert commission == 5.0

    def test_symbol_autodetect_etf_fees_without_asset_type(self):
        # asset_type 为空时按 symbol 自动判别：ETF 结构豁免生效
        cfg = MatchConfig(price_mode="open")
        _, stamp, transfer, _ = compute_fees(10000, 4.0, "sell", cfg, "159915.SZ")
        assert stamp == 0.0
        assert transfer == 0.0
        # 股票不受影响
        _, stamp_eq, transfer_eq, _ = compute_fees(10000, 4.0, "sell", cfg, "600036.SH")
        assert stamp_eq == pytest.approx(10000 * 4.0 * 0.0005)
        assert transfer_eq == pytest.approx(10000 * 4.0 * 0.00001)

    def test_etf_price_tick_001(self):
        # 滑点 7bps：4.0×1.0007=4.0028 → 0.001 档向下取整 = 4.002
        cfg = MatchConfig(price_mode="open", asset_type="etf", slippage_bps=7.0)
        mr = match_order("buy", 1000, _bar(open_=4.0), cfg)
        assert mr.success
        assert mr.fill_price == pytest.approx(4.002)
        # 股票档 0.01：同价 4.0028 → 4.00
        cfg_eq = MatchConfig(price_mode="open", asset_type="equity", slippage_bps=7.0)
        bar_eq = _bar(symbol="600036.SH")
        mr_eq = match_order("buy", 1000, bar_eq, cfg_eq)
        assert mr_eq.fill_price == pytest.approx(4.00)

    def test_buy_lot_constraint(self):
        cfg = MatchConfig(price_mode="open", asset_type="etf")
        mr = match_order("buy", 150, _bar(), cfg)
        assert mr.success and mr.fill_quantity == 100  # 整手向下
        mr0 = match_order("buy", 50, _bar(), cfg)
        assert not mr0.success and mr0.reason == "BELOW_LOT_SIZE"

    def test_partial_fill_by_cash(self):
        cfg = MatchConfig(
            price_mode="open", asset_type="etf", allow_partial=True, slippage_bps=0
        )
        # 现金 2000 元：4.0×1000=4000 买不起 → 成交 400 股，剩余 600
        mr = match_order("buy", 1000, _bar(), cfg, cash_available=2000)
        assert mr.success
        assert mr.fill_quantity == 400
        assert mr.qty_remaining == 600
        # 费用 400×4×0.0003=0.48 ≤ 剩余现金
        assert 400 * 4.0 + mr.total_fee <= 2000

    def test_full_reject_insufficient_cash(self):
        cfg = MatchConfig(
            price_mode="open", asset_type="etf", allow_partial=True, slippage_bps=0
        )
        mr = match_order("buy", 1000, _bar(), cfg, cash_available=300)
        assert not mr.success
        assert mr.reason == "INSUFFICIENT_CASH"
        assert mr.qty_remaining == 1000

    def test_partial_fill_by_available_volume(self):
        cfg = MatchConfig(
            price_mode="open", asset_type="etf", allow_partial=True, slippage_bps=0
        )
        mr = match_order("sell", 1000, _bar(), cfg, available_volume=600)
        assert mr.success
        assert mr.fill_quantity == 600
        assert mr.qty_remaining == 400

    def test_default_no_partial_sell_rejection_unchanged(self):
        # allow_partial=False：既有回放行为不变（整单拒绝）
        cfg = MatchConfig(price_mode="open", asset_type="etf")
        mr = match_order("sell", 1000, _bar(), cfg, available_volume=600)
        assert not mr.success
        assert mr.reason.startswith("INSUFFICIENT_AVAILABLE_VOLUME")

    def test_limit_clamp_on_etf_tick(self):
        # 滑点把价格推过涨停：钳制到涨停并对齐 0.001 档
        cfg = MatchConfig(price_mode="open", asset_type="etf", slippage_bps=200.0)
        bar = _bar(open_=4.398, limit_up=4.400)
        mr = match_order("buy", 1000, bar, cfg)
        assert mr.success
        assert mr.fill_price <= 4.400
        assert round(mr.fill_price * 1000) == mr.fill_price * 1000  # 0.001 整数倍

    def test_suspended_reject(self):
        cfg = MatchConfig(price_mode="open", asset_type="etf")
        bar = _bar(volume=0)
        mr = match_order("buy", 1000, bar, cfg)
        assert not mr.success and mr.reason == "SUSPENDED"


# ---------------------------------------------------------------------------
# 输入包（TG-007 消费侧基础校验；详细账本行为见其他测试文件）
# ---------------------------------------------------------------------------


class TestEtfInputPackageBasics:
    @pytest.fixture()
    def fixture_pkg(self, tmp_path):
        from backend.services.simulation.replay.etf_input_package import (
            build_fixture_package,
        )

        return build_fixture_package(tmp_path / "pkg")

    def test_manifest_valid_and_fixture_flagged(self, fixture_pkg):
        assert fixture_pkg.is_fixture
        assert fixture_pkg.package_id.startswith("fixture-")
        desc = fixture_pkg.describe()
        assert desc["symbols"] and desc["trade_dates"]

    def test_manifest_sha256_enforced(self, tmp_path):
        from backend.services.simulation.replay.etf_input_package import (
            EtfInputPackageError,
            build_fixture_package,
            load_etf_input_package,
        )

        pkg = build_fixture_package(tmp_path / "pkg")
        # 正确哈希 → 通过
        load_etf_input_package(tmp_path / "pkg", expect_manifest_sha256=pkg.manifest_sha256)
        # 篡改 → 拒绝
        with pytest.raises(EtfInputPackageError, match="manifest_sha256 不匹配"):
            load_etf_input_package(
                tmp_path / "pkg", expect_manifest_sha256="0" * 64
            )

    def test_load_date_units_and_pre_close(self, fixture_pkg):
        dates = fixture_pkg.trade_dates()
        bars = fixture_pkg.load_date(dates[3])
        bar = bars["510300.SH"]
        # 手→份 ×100；千元→元 ×1000
        assert bar.volume == pytest.approx(12000 * 100)
        assert bar.amount == pytest.approx(bar.close * 12000 * 100, rel=1e-3)
        prev = fixture_pkg.load_date(dates[2])["510300.SH"]
        assert bar.pre_close == pytest.approx(prev.close)

    def test_typed_events_parsed_and_ordered(self, fixture_pkg):
        evs = fixture_pkg.events_for("518880.SH")
        assert [e.event_type for e in evs if e.event_date == date(2025, 9, 23)] == [
            "share_adjustment",
            "cash_dividend",
        ]  # 同日先份额后现金

    def test_regression_event_values_frozen(self, fixture_pkg):
        ev_159934 = fixture_pkg.events_for("159934.SZ")
        assert ev_159934[0].qty_multiplier == pytest.approx(0.9481)
        ev_510500 = fixture_pkg.events_for("510500.SH")
        assert ev_510500[0].qty_multiplier == pytest.approx(0.2803)

    def test_adjusted_close_signal_convention(self, fixture_pkg):
        d = fixture_pkg.trade_dates()[0]
        bar = fixture_pkg.get_bar("510300.SH", d)
        adj = fixture_pkg.adjusted_close("510300.SH", d)
        assert adj == pytest.approx(bar.close * 1.5)  # fixture adj_factor=1.5
