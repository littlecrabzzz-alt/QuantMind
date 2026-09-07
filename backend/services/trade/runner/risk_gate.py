"""
风控闸门模块 (RiskGate)

从 runner/main.py 剥离，集中存放所有风控逻辑：
  - 价格偏离校验
  - 账户回撤全局止损
  - 单笔金额 / 单票持仓上限
  - 换手率拦截
  - 信号指纹 + 幂等锁
"""

import hashlib
import logging
import math
from typing import Any

import redis

logger = logging.getLogger(__name__)


# ─── 内部辅助 ────────────────────────────────────────────────────────────────


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    except Exception:
        return None


def _extract_live_price(snapshot: dict[str, Any]) -> float | None:
    for key in ("Now", "last_price", "current_price", "price", "close"):
        parsed = _to_float(snapshot.get(key))
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _extract_market_pct_change(snapshot: dict[str, Any]) -> float | None:
    for key in (
        "pct_chg",
        "pct_change",
        "change_percent",
        "change_pct",
        "pct",
        "ChgRatio",
    ):
        parsed = _to_float(snapshot.get(key))
        if parsed is None:
            continue
        return parsed / 100.0 if abs(parsed) > 1 else parsed

    live_price = _extract_live_price(snapshot)
    prev_close = _to_float(snapshot.get("prev_close"))
    if live_price is not None and prev_close and prev_close > 0:
        return (live_price - prev_close) / prev_close
    return None


# ─── 公开接口 ─────────────────────────────────────────────────────────────────


class RiskGate:
    """
    无状态风控闸门，所有方法均为类方法，便于直接调用。

    调用示例（runner/main.py）::

        from backend.services.trade.runner.risk_gate import RiskGate

        signals = RiskGate.apply(signals, account, exec_config, market, live_trade_config)
        fingerprint = RiskGate.fingerprint(signals)
        if RiskGate.acquire_lock(redis_client, tenant_id, user_id, strategy, fingerprint):
            ...
    """

    @staticmethod
    def apply(
        signals: list[dict[str, Any]],
        account: dict[str, Any],
        exec_config: dict[str, Any],
        market_snapshot: dict[str, Any],
        live_trade_config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        核心风控闸门 (RC2 增强版)。
        对输入信号列表做多层过滤/缩减，返回合规后的信号列表。
        """
        live_trade_config = live_trade_config or {}
        config = {
            "turnover": exec_config.get("max_turnover_ratio_per_cycle", 0.20),
            "stop_loss": exec_config.get(
                "stop_loss", exec_config.get("global_stop_loss_drawdown", -0.08)
            ),
            "buy_drop": exec_config.get("max_buy_drop", -0.03),
            "stock_ratio": exec_config.get("max_single_stock_ratio", 0.15),
            "order_value": exec_config.get("max_order_value_absolute", 500000),
            "price_deviation": live_trade_config.get(
                "max_price_deviation", exec_config.get("max_price_deviation", 0.02)
            ),
        }
        limits = {key: _to_float(value) for key, value in config.items()}
        if any(value is None for value in limits.values()):
            logger.warning("[Risk] 非有限风控参数，拒绝整个批次")
            return []
        if any(
            limits[key] < 0
            for key in ("turnover", "stock_ratio", "order_value", "price_deviation")
        ):
            return []
        total_value = _to_float(account.get("total_value"))
        drawdown = _to_float(account.get("drawdown", 0))
        positions = account.get("positions") or {}
        close_actions = {"SELL_TO_CLOSE", "BUY_TO_CLOSE"}
        open_actions = {"BUY_TO_OPEN", "SELL_TO_OPEN"}
        passed = []
        reserved = {}
        for original in signals:
            s = dict(original)
            symbol = s.get("symbol")
            price, volume = _to_float(s.get("price")), _to_float(s.get("volume"))
            if (
                not symbol
                or price is None
                or volume is None
                or price <= 0
                or volume <= 0
            ):
                logger.warning("[Risk] %s 价格或数量无效，拒绝", symbol)
                continue
            if not math.isfinite(price * volume):
                continue
            action = str(s.get("action") or "").upper()
            trade_action = str(s.get("trade_action") or "").upper()
            if trade_action and trade_action not in close_actions | open_actions:
                continue
            if action not in {"BUY", "SELL"}:
                continue
            if trade_action and not trade_action.startswith(action + "_"):
                continue
            is_close = trade_action in close_actions
            # Only an explicit close action receives the reduction exemption.
            # Broker/position validation must still enforce closeable quantity.
            if not is_close and (
                total_value is None
                or total_value <= 0
                or drawdown is None
                or drawdown <= limits["stop_loss"]
            ):
                logger.warning("[Risk] %s 账户无效或触发回撤限制，拒绝开仓", symbol)
                continue
            snapshot = market_snapshot.get(symbol) or {}
            live_price = _extract_live_price(snapshot)
            if (
                live_price is not None
                and abs(price - live_price) / live_price > limits["price_deviation"]
            ):
                continue
            pct_change = _extract_market_pct_change(snapshot)
            if not is_close and pct_change is not None:
                if action == "BUY" and pct_change <= limits["buy_drop"]:
                    logger.warning("[Risk] %s 触发多头大跌限制，拒绝开仓", symbol)
                    continue
                if action == "SELL" and pct_change >= abs(limits["buy_drop"]):
                    logger.warning("[Risk] %s 触发空头大涨限制，拒绝开仓", symbol)
                    continue
            allowed = limits["order_value"]
            if not is_close:
                position = positions.get(symbol, {})
                current_value = _to_float(position.get("market_value", 0))
                if current_value is None:
                    continue
                # Reserve every accepted opening order. Do not credit pending
                # closes or opposite-side opens before they have actually filled.
                remaining = (
                    total_value * limits["stock_ratio"]
                    - abs(current_value)
                    - reserved.get(symbol, 0.0)
                )
                allowed = min(allowed, max(0.0, remaining))
            if price * volume > allowed:
                logger.warning(
                    "[Risk] %s 单笔或累计敞口超限，允许金额 %.2f", symbol, allowed
                )
                volume = int((allowed / price) // 100) * 100
            if volume <= 0:
                continue
            s["price"] = price
            s["volume"] = volume
            s["action"] = action
            if trade_action:
                s["trade_action"] = trade_action
            passed.append(s)
            if not is_close:
                reserved[symbol] = reserved.get(symbol, 0.0) + price * volume

        # Reductions retain priority, including global stop-loss closes. Their
        # turnover consumes the opening budget but cannot be scaled away by it.
        closes = sum(
            s["price"] * s["volume"]
            for s in passed
            if s.get("trade_action") in close_actions
        )
        opens = sum(
            s["price"] * s["volume"]
            for s in passed
            if s.get("trade_action") not in close_actions
        )
        budget = max(0.0, (total_value or 0.0) * limits["turnover"] - closes)
        if opens > budget:
            logger.warning(
                "[Risk] 开仓金额 %.2f 超过剩余换手预算 %.2f，缩减开仓", opens, budget
            )
            ratio = budget / opens
            for s in passed:
                if s.get("trade_action") not in close_actions:
                    s["volume"] = int(s["volume"] * ratio // 100) * 100
        result = [s for s in passed if s["volume"] > 0]
        logger.info(
            "[Risk] 原始=%d -> 合规后=%d | Drawdown: %s",
            len(signals),
            len(result),
            drawdown,
        )
        return result

    @staticmethod
    def fingerprint(signals: list[dict[str, Any]]) -> str:
        """计算信号批次指纹，用于幂等锁键。"""
        sorted_sigs = sorted(signals, key=lambda x: x["symbol"] + x["action"])
        raw = "|".join(
            [f"{s['symbol']}:{s['action']}:{s['volume']}" for s in sorted_sigs]
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def acquire_lock(
        redis_client: redis.Redis,
        tenant_id: str,
        user_id: str,
        strategy: str,
        fingerprint: str,
        ttl_seconds: int = 86400,
    ) -> bool:
        """
        获取幂等锁（NX SET）。
        返回 True 表示首次出现（应下单）；False 表示重复（应跳过）。
        """
        lock_key = f"qm:lock:signal:{tenant_id}:{user_id}:{strategy}:{fingerprint}"
        return bool(redis_client.set(lock_key, "1", ex=ttl_seconds, nx=True))
