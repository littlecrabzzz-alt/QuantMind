import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class VectorizedBacktestConfig:
    initial_capital: float = 100000.0
    # Proportional-cost research approximation; no minimum fees or lot rounding.
    commission: float = 0.00025
    slippage: float = 0.0001
    topk: int = 50
    sell_cost: float = 0.00051  # stamp duty + transfer fee (sell-only cost)


@dataclass
class VectorizedBacktestResult:
    success: bool
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    win_rate: float = 0.0
    portfolio_dict: dict | None = None
    indicator_dict: dict | None = None
    error_message: str = ""


class VectorizedBacktestEngine:
    def __init__(self, config: VectorizedBacktestConfig):
        self.config = config
        self.logger = logger

    @staticmethod
    def _get_limit_threshold_vec(stock_ids: pd.Index) -> pd.Series:
        """Return per-stock limit thresholds based on stock code."""
        thresholds = pd.Series(0.095, index=stock_ids)
        for sid in stock_ids:
            code = sid.split(".")[0] if "." in str(sid) else str(sid)
            pure = code.upper()
            for pfx in ("SH", "SZ", "BJ"):
                if pure.startswith(pfx):
                    pure = pure[len(pfx) :]
                    break
            if pure.startswith("68") or pure.startswith("30"):
                thresholds[sid] = 0.195  # ChiNext / STAR ±20%
            elif pure.startswith("8") or pure.startswith("4"):
                thresholds[sid] = 0.295  # Beijing ±30%
        return thresholds

    def run_backtest(
        self,
        signals: pd.DataFrame,
        prices: pd.DataFrame,
        changes: pd.DataFrame | None = None,
    ) -> VectorizedBacktestResult:
        """Close execution with fractional shares and proportional fees.

        Signals must already be lagged to their execution dates. Mark existing
        shares at today's close BEFORE rebalancing; never shift future returns
        into today's report. Missing quotes may mark holdings but cannot trade.
        This diagnostic engine does not reproduce CnExchange execution rules.
        """
        try:
            cfg = self.config
            if not np.isfinite(cfg.initial_capital) or cfg.initial_capital <= 0:
                raise ValueError("initial_capital must be finite and positive")
            if cfg.topk < 1 or int(cfg.topk) != cfg.topk:
                raise ValueError("topk must be a positive integer")
            rates = (cfg.commission, cfg.slippage, cfg.sell_cost)
            if any(not np.isfinite(rate) or rate < 0 for rate in rates):
                raise ValueError("cost rates must be finite and nonnegative")
            buy_rate = cfg.commission + cfg.slippage
            sell_rate = buy_rate + cfg.sell_cost
            if sell_rate >= 1:
                raise ValueError("combined sell cost must be below 100%")
            if isinstance(signals, pd.Series):
                signals = signals.to_frame("score")
            scores = signals["score"].unstack("instrument").sort_index()
            raw = prices["$close"].unstack("instrument").sort_index()
            if scores.empty or raw.empty:
                raise ValueError("signals and prices must be nonempty")
            # Preserve price dates without signals and dates with no valid quote.
            dates = raw.index.union(scores.index).sort_values()
            dates = dates[(dates >= scores.index.min()) & (dates <= raw.index.max())]
            raw = raw.reindex(index=dates, columns=scores.columns)
            raw = raw.where(np.isfinite(raw) & raw.gt(0))
            scores = scores.reindex(index=dates).where(lambda x: np.isfinite(x))
            marked = raw.ffill().fillna(0.0)
            if len(dates) < 2:
                raise ValueError("at least two execution/valuation dates are required")
            can_buy = raw.notna()
            can_sell = raw.notna()
            if changes is not None:
                change = changes["$change"].unstack("instrument").reindex_like(raw)
                known = np.isfinite(change)
                threshold = self._get_limit_threshold_vec(raw.columns)
                can_buy &= known & change.lt(threshold, axis=1)
                can_sell &= known & change.gt(-threshold, axis=1)

            shares = pd.Series(0.0, index=raw.columns)
            cash = previous_nav = float(cfg.initial_capital)
            rows, holdings = [], []
            for dt in dates:
                px = marked.loc[dt]
                values = shares * px
                pre_trade_nav = cash + float(values.sum())
                buy_value = sell_value = fees = 0.0
                # An absent signal day means hold, not liquidate the portfolio.
                if scores.loc[dt].notna().any():
                    eligible = can_buy.loc[dt] | shares.gt(0)
                    ranked = (
                        scores.loc[dt]
                        .where(eligible)
                        .rank(ascending=False, method="first")
                    )
                    selected = ranked.le(cfg.topk)
                    desired = pd.Series(0.0, index=raw.columns)
                    if selected.any():
                        desired.loc[selected] = pre_trade_nav / selected.sum()
                    sells = (values - desired).clip(lower=0).where(can_sell.loc[dt], 0)
                    sell_value = float(sells.sum())
                    shares -= sells.div(px.where(px.gt(0))).fillna(0)
                    cash += sell_value * (1 - sell_rate)
                    buys = (
                        (desired - shares * px).clip(lower=0).where(can_buy.loc[dt], 0)
                    )
                    requested = float(buys.sum())
                    if requested > 0:
                        buys *= min(1.0, max(0.0, cash) / (requested * (1 + buy_rate)))
                    buy_value = float(buys.sum())
                    shares += buys.div(px.where(px.gt(0))).fillna(0)
                    cash -= buy_value * (1 + buy_rate)
                    fees = sell_value * sell_rate + buy_value * buy_rate
                nav = cash + float((shares * px).sum())
                if not np.isfinite(nav) or nav <= 0 or cash < -1e-7:
                    raise ValueError("invalid cash or portfolio value")
                # Qlib: return is BEFORE costs; cost is a ratio of previous NAV.
                rows.append(
                    {
                        "account": nav,
                        "return": (pre_trade_nav - previous_nav) / previous_nav,
                        "cost": fees / previous_nav,
                        "cost_amount": fees,
                        "turnover": (buy_value + sell_value) / previous_nav,
                        "cash": cash,
                        "value": nav - cash,
                    }
                )
                holdings.append(shares.copy())
                previous_nav = nav

            report = pd.DataFrame(rows, index=dates)
            net_returns = report["return"] - report["cost"]
            equity = report["account"]
            total_return = float(equity.iloc[-1] / cfg.initial_capital - 1)
            annual_return = (1 + total_return) ** (252 / len(dates)) - 1
            daily_std = net_returns.std(ddof=1)
            sharpe = (
                (net_returns.mean() - 0.02 / 252) / daily_std * np.sqrt(252)
                if daily_std > 0
                else 0.0
            )
            # Include initial cash in the high-water mark, including day-one fees.
            peak = equity.cummax().clip(lower=cfg.initial_capital)
            max_drawdown = float((equity / peak - 1).min())
            return VectorizedBacktestResult(
                success=True,
                annual_return=float(annual_return),
                sharpe_ratio=float(sharpe),
                max_drawdown=max_drawdown,
                total_return=total_return,
                win_rate=float(net_returns.gt(0).mean()),
                portfolio_dict={
                    "report": report,
                    "final_value": float(equity.iloc[-1]),
                    "account": float(equity.iloc[-1]),
                    "position_value": float(report.iloc[-1]["value"]),
                    "holdings": pd.DataFrame(holdings, index=dates),
                    "execution_model": "fractional_close_proportional_costs",
                },
                indicator_dict={"report": report},
            )
        except Exception as exc:
            self.logger.error("Vectorized backtest failed: %s", exc, exc_info=True)
            return VectorizedBacktestResult(success=False, error_message=str(exc))
