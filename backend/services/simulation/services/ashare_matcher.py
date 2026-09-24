"""A股模拟撮合器 —— 涨跌停、整手、费用、滑点。

由 SimulationExecutionEngine 调用，不把规则堆在原类里。
所有价格均为不复权实际价格（与 LocalMarketData 的 DailyBar 口径一致）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

from backend.services.simulation.services.local_market_data import DailyBar
from backend.services.simulation.services.market_rules import (
    AssetType,
    asset_type_for_symbol,
    lot_size_for_symbol,
    rules_for_asset_type,
)

logger = logging.getLogger(__name__)

# ── 费用常量 ──────────────────────────────────────────────────────────
_COMMISSION_RATE = 0.0003  # 佣金费率（双向）
_COMMISSION_MIN = 5.0  # 佣金最低 5 元
_STAMP_DUTY_RATE = 0.0005  # 印花税（仅卖出，2023-08-28 降为 0.05%）
_TRANSFER_FEE_RATE = 0.00001  # 过户费（沪深双向，0.001%）
_LOT_SIZE = 100  # A股 1 手 = 100 股


@dataclass(frozen=True)
class MatchConfig:
    """撮合参数（可由前端 SimulationSettings 编辑）。

    asset_type 为空时按 symbol 自动判别（XG-001 代码段）；显式指定时
    以本字段为准（R01 账本对整包 ETF 输入固定传 "etf"）。
    allow_partial：部分成交开关（ledger-contract §4）。默认 False 维持
    既有回放行为（可卖量不足整单拒绝）；R01 研究账本显式开启：
    按当日可成交量部分成交，剩余量由调用方转 expired_unfilled。
    """

    price_mode: str = "close"  # open / close / vwap
    slippage_bps: float = 5.0  # 滑点（基点）
    commission_rate: float = _COMMISSION_RATE
    commission_min: float = _COMMISSION_MIN
    stamp_duty_rate: float = _STAMP_DUTY_RATE
    transfer_fee_rate: float = _TRANSFER_FEE_RATE
    lot_size: int = _LOT_SIZE
    asset_type: str = ""  # "" = auto / "equity" / "etf"
    allow_partial: bool = False

    def asset_rules(self, symbol: str):
        """解析本单适用的资产类别规则（含显式佣金假设覆盖）。"""
        if self.asset_type:
            at = AssetType(self.asset_type)
        else:
            at = asset_type_for_symbol(symbol)
        return rules_for_asset_type(
            at,
            commission_rate=self.commission_rate,
            commission_min=self.commission_min,
        )


@dataclass
class MatchResult:
    """撮合结果。"""

    success: bool
    fill_price: float = 0.0
    fill_quantity: int = 0
    commission: float = 0.0
    stamp_duty: float = 0.0
    transfer_fee: float = 0.0
    total_fee: float = 0.0
    reason: str = ""
    # 部分成交时的剩余量（= qty_target - fill_quantity，恒非负）。
    # allow_partial=False 的整单拒绝不含剩余量语义（success=False 时为 0）。
    qty_remaining: int = 0


def _pick_price(bar: DailyBar, mode: str) -> float:
    if mode == "vwap" and bar.vwap > 0:
        return bar.vwap
    if mode == "open" and bar.open > 0:
        return bar.open
    return bar.close


def _round_to_tick(price: float, tick: float) -> float:
    """向下取整到最小报价单位（买入不高于挂牌价、卖出保守计价）。"""
    if tick <= 0:
        return price
    return round(math.floor(round(price / tick, 6)) * tick, 6)


def _floor_to_lot(shares: float, lot_size: int) -> int:
    if shares <= 0:
        return 0
    return int(shares // lot_size) * lot_size


def _is_etf(symbol: str, cfg_asset_type: str) -> bool:
    if cfg_asset_type:
        return cfg_asset_type == AssetType.ETF.value
    return asset_type_for_symbol(symbol) is AssetType.ETF


def compute_fees(
    quantity: int,
    price: float,
    side: str,
    cfg: MatchConfig,
    symbol: str = "",
) -> tuple[float, float, float, float]:
    """计算费用。返回 (commission, stamp_duty, transfer_fee, total_fee)。

    ETF（TG-006 资产类别规则）：印花税=过户费=0，结构性豁免，不受
    cfg 中费率字段影响；佣金按可配费率与可配最低收费。
    """
    gross = quantity * price
    if _is_etf(symbol, cfg.asset_type):
        rules = cfg.asset_rules(symbol)
        commission = max(gross * rules.commission_rate, rules.commission_min)
        stamp_duty = 0.0
        transfer_fee = 0.0
    else:
        commission = max(gross * cfg.commission_rate, cfg.commission_min)
        stamp_duty = gross * cfg.stamp_duty_rate if side == "sell" else 0.0
        transfer_fee = gross * cfg.transfer_fee_rate
    total_fee = commission + stamp_duty + transfer_fee
    return commission, stamp_duty, transfer_fee, total_fee


def match_order(
    side: str,
    quantity: int,
    bar: DailyBar,
    cfg: MatchConfig,
    available_volume: float | None = None,
    cash_available: float | None = None,
) -> MatchResult:
    """对单笔订单执行 A 股/ETF 撮合规则。

    Args:
        side: "buy" / "sell"
        quantity: 委托数量（股）
        bar: 当日行情（不复权）
        cfg: 撮合参数
        available_volume: T+1 可卖量（仅 sell 时需要）
        cash_available: 可用现金（仅 buy + allow_partial 时用于现金约束
            部分成交；为 None 时不做现金上限约束）
    """
    # ── 停牌 ──
    if bar.suspended:
        return MatchResult(success=False, reason="SUSPENDED")

    # ── 涨跌停 ──
    if side == "buy" and bar.close >= bar.limit_up:
        return MatchResult(success=False, reason="LIMIT_UP")
    if side == "sell" and bar.close <= bar.limit_down:
        return MatchResult(success=False, reason="LIMIT_DOWN")

    asset_rules = cfg.asset_rules(bar.symbol)
    is_etf = asset_rules.asset_type is AssetType.ETF

    # ── T+1 可卖量 ──
    sell_shortfall = 0
    if side == "sell" and available_volume is not None:
        if quantity > available_volume:
            if cfg.allow_partial and available_volume > 0:
                sell_shortfall = quantity - int(available_volume)
                quantity = int(available_volume)
            else:
                return MatchResult(
                    success=False,
                    reason=f"INSUFFICIENT_AVAILABLE_VOLUME:{available_volume:.0f}",
                )

    # ── 整手 ──
    lot_size = max(1, int(lot_size_for_symbol(bar.symbol) or cfg.lot_size or _LOT_SIZE))
    if side == "buy":
        fill_qty = _floor_to_lot(quantity, lot_size)
        if fill_qty <= 0:
            return MatchResult(success=False, reason="BELOW_LOT_SIZE")
        # 现金约束的部分成交：按可负担的最大整手数成交（allow_partial）。
        # 估价口径与最终成交价一致（滑点+价格档+钳制），保证可负担判定
        # 不会因费用口径差异多成交一手。
        if cfg.allow_partial and cash_available is not None:
            est_price = _estimate_fill_price(bar, side, cfg, asset_rules)
            _, _, _, est_fee = compute_fees(fill_qty, est_price, side, cfg, bar.symbol)
            if fill_qty * est_price + est_fee > cash_available:
                affordable = _affordable_lots(
                    cash_available, est_price, lot_size, side, cfg, bar.symbol
                )
                if affordable <= 0:
                    return MatchResult(
                        success=False,
                        reason="INSUFFICIENT_CASH",
                        qty_remaining=quantity,
                    )
                remaining = quantity - affordable * lot_size
                fill_qty = affordable * lot_size
                return _finalize_fill(
                    side, fill_qty, remaining, bar, cfg, asset_rules, is_etf
                )
    else:
        # 卖出允许清仓零头（不满一手也可以卖完）
        fill_qty = quantity

    return _finalize_fill(
        side, fill_qty, sell_shortfall, bar, cfg, asset_rules, is_etf
    )


def _affordable_lots(
    cash: float,
    est_price: float,
    lot_size: int,
    side: str,
    cfg: MatchConfig,
    symbol: str,
) -> int:
    """现金可负担的最大整手数（含费用）。逐手递减，确定性且保守。"""
    if est_price <= 0 or lot_size <= 0:
        return 0
    lots = int(cash // (est_price * lot_size))
    while lots > 0:
        qty = lots * lot_size
        _, _, _, total_fee = compute_fees(qty, est_price, side, cfg, symbol)
        if qty * est_price + total_fee <= cash:
            return lots
        lots -= 1
    return 0


def _estimate_fill_price(bar: DailyBar, side: str, cfg: MatchConfig, asset_rules) -> float:
    """与 _finalize_fill 同口径的估价（滑点+价格档+钳制），买入现金约束用。"""
    base_price = _pick_price(bar, cfg.price_mode)
    if base_price <= 0:
        return 0.0
    slippage = cfg.slippage_bps / 10000
    direction = 1 if side == "buy" else -1
    price = _round_to_tick(base_price * (1 + direction * slippage), asset_rules.price_tick)
    if math.isfinite(bar.limit_up) and price > bar.limit_up:
        price = _round_to_tick(bar.limit_up, asset_rules.price_tick)
    if bar.limit_down > 0 and price < bar.limit_down:
        price = _round_to_tick(bar.limit_down, asset_rules.price_tick)
    return price


def _finalize_fill(
    side: str,
    fill_qty: int,
    qty_remaining: int,
    bar: DailyBar,
    cfg: MatchConfig,
    asset_rules,
    is_etf: bool,
) -> MatchResult:
    """成交价 + 滑点 + 价格档 + 费用，组装 MatchResult。"""
    fill_price = _estimate_fill_price(bar, side, cfg, asset_rules)
    if fill_price <= 0:
        return MatchResult(success=False, reason="INVALID_PRICE")
    fill_price = round(fill_price, 3 if is_etf else 4)

    # ── 费用 ──
    commission, stamp_duty, transfer_fee, total_fee = compute_fees(
        fill_qty, fill_price, side, cfg, bar.symbol
    )

    return MatchResult(
        success=True,
        fill_price=fill_price,
        fill_quantity=fill_qty,
        commission=commission,
        stamp_duty=stamp_duty,
        transfer_fee=transfer_fee,
        total_fee=total_fee,
        qty_remaining=max(0, int(qty_remaining)),
    )
