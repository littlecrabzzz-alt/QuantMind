"""按收盘信号、次日开盘执行的逐日撮合。"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data.market import MarketData
from .strategy import Strategy


@dataclass
class CostModel:
    """交易费用、滑点和手数。"""

    commission: float = 0.00025
    transfer: float = 0.00001
    stamp_before: float = 0.001
    stamp_after: float = 0.0005
    stamp_switch: str = "2023-08-28"
    slippage: float = 0.001
    lot: int = 100
    impact_k: float = 0.0
    impact_window: int = 20
    max_participation: float | None = None


@dataclass
class BacktestConfig:
    """回测区间与初始资金。"""

    start: str
    end: str
    initial_cash: float = 1e7
    costs: CostModel = field(default_factory=CostModel)
    execution: str = "open"
    stamp_exempt: tuple[str, ...] = ()
    fixed_cash_targets: bool = False
    transfer_exempt: tuple[str, ...] = ()


@dataclass
class BacktestResult:
    """逐日账户、成交与信号记录。"""

    nav: pd.Series
    cash: pd.Series
    positions: pd.DataFrame
    trades: pd.DataFrame
    exposure: pd.Series
    target: pd.DataFrame
    signals: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_backtest(
    strategy: Strategy, data: MarketData, config: BacktestConfig,
) -> BacktestResult:
    """执行逐日撮合，限制策略只能读取当日及以前的数据。"""
    calendar = data.calendar
    rows = np.flatnonzero(
        (calendar >= pd.Timestamp(config.start)) & (calendar <= pd.Timestamp(config.end))
    )
    dates = calendar[rows]
    codes = data.close.columns
    n = len(codes)
    costs = config.costs
    fee_rate = np.full(n, costs.commission + costs.transfer)
    fee_rate[codes.isin(config.transfer_exempt)] = costs.commission
    stamp_switch = pd.Timestamp(costs.stamp_switch)
    if config.execution not in ("open", "close"):
        raise ValueError("execution must be open or close")
    opens = getattr(data, config.execution).to_numpy(dtype=float)
    closes = data.close.ffill().to_numpy(dtype=float)
    adjustments = data.adj.ffill().to_numpy(dtype=float)
    impact_enabled = costs.impact_k > 0 or costs.max_participation is not None
    if impact_enabled:
        # shift(1) 排除执行日；不足两个收益时波动率为零。
        sigma = np.log(pd.DataFrame(closes * adjustments)).diff().rolling(
            costs.impact_window, min_periods=2,
        ).std(ddof=1).shift(1).fillna(0.0).to_numpy()
        amounts = data.amount.fillna(0.0).to_numpy(dtype=float)
    up = data.up_limit.to_numpy(dtype=float)
    down = data.down_limit.to_numpy(dtype=float)
    suspended = data.suspended.to_numpy(dtype=bool)
    delist = pd.to_datetime(data.delist_date.reindex(codes)).to_numpy(dtype="datetime64[ns]")
    rebalances = set(strategy.rebalance_dates(dates))

    shares = np.zeros(n)
    held = np.zeros(n, dtype=bool)
    pending = np.zeros(n, dtype=bool)
    weights = np.zeros(n)
    remaining = None
    base = pd.Series(dtype=float)
    last_exposure = 1.0
    cash = float(config.initial_cash)
    nav_history = np.empty(len(dates))
    cash_history = np.empty(len(dates))
    exposure_history = np.empty(len(dates))
    positions = np.zeros((len(dates), n))
    trades: list[tuple] = []
    targets: list[pd.Series] = []
    target_dates: list[pd.Timestamp] = []
    signal_rows, signal_dates = [], []

    for day, row in enumerate(rows):
        date = dates[day]
        previous_close = closes[row - 1] if row else np.full(n, np.nan)
        if row:
            ratio = np.ones(n)
            valid = (
                np.isfinite(adjustments[row]) & np.isfinite(adjustments[row - 1])
                & (adjustments[row - 1] != 0)
            )
            np.divide(adjustments[row], adjustments[row - 1], out=ratio, where=valid)
            shares *= ratio

        retired = delist <= date.to_datetime64()
        for j in np.flatnonzero(retired & (shares > 0)):
            price = previous_close[j]
            if not np.isfinite(price):
                raise ValueError(f"{codes[j]} 退市前缺少有效收盘价")
            value = shares[j] * price
            cash += value
            trades.append((date, codes[j], "delist", shares[j], price, value, 0.0))
            shares[j] = 0.0
        pending[retired] = False

        if pending.any():
            px = np.where(np.isnan(opens[row]), previous_close, opens[row])
            current_value = np.multiply(shares, px, out=np.zeros(n), where=shares != 0)
            nav_open = cash + current_value.sum()
            delta = weights * nav_open - current_value
            if config.fixed_cash_targets:
                if remaining is None:
                    remaining = delta.copy()
                delta = remaining.copy()
                delta[weights == 0] = -current_value[weights == 0]
            tradable = ~suspended[row] & np.isfinite(opens[row]) & (opens[row] > 0)
            if impact_enabled:
                adv = (amounts[max(0, row - costs.impact_window):row].mean(axis=0)
                       if row else np.zeros(n))
                valid_adv = np.isfinite(adv) & (adv > 0)
                tradable &= valid_adv
                planned = np.abs(delta)
                capped = (np.minimum(planned, costs.max_participation * adv)
                          if costs.max_participation is not None else planned)
                limited = valid_adv & (capped < planned)
                participation = np.divide(capped, adv, out=np.zeros(n), where=valid_adv)
                impact = costs.impact_k * sigma[row] * np.sqrt(participation)
            can_sell = tradable & (np.isnan(down[row]) | (opens[row] > down[row] + 1e-6))
            can_buy = tradable & (np.isnan(up[row]) | (opens[row] < up[row] - 1e-6))
            selling = pending & (shares > 0) & ((delta < 0) | (weights == 0))
            buying = pending & (delta > 0)
            retry = (selling & ~can_sell) | (buying & ~can_buy)
            if impact_enabled:
                retry |= (selling | buying) & limited

            stamp = costs.stamp_after if date >= stamp_switch else costs.stamp_before
            for j in np.flatnonzero(selling & can_sell):
                price = opens[row, j] * (1 - costs.slippage)
                quantity = shares[j] if weights[j] == 0 else min(
                    shares[j], np.floor(-delta[j] / price / costs.lot) * costs.lot,
                )
                if impact_enabled:
                    price = opens[row, j] * (1 - costs.slippage - impact[j])
                    quantity = shares[j] if weights[j] == 0 and not limited[j] else min(
                        shares[j], np.floor(capped[j] / price / costs.lot) * costs.lot,
                    )
                if quantity <= 0:
                    continue
                value = quantity * price
                fee = value * (fee_rate[j] + (0.0 if codes[j] in config.stamp_exempt else stamp))
                cash += value - fee
                shares[j] -= quantity
                trades.append((date, codes[j], "sell", quantity, price, value, fee))
                if config.fixed_cash_targets:
                    remaining[j] += value

            buy_indices = np.flatnonzero(buying & can_buy)
            buy_prices = opens[row, buy_indices] * (1 + costs.slippage)
            if impact_enabled:
                buy_prices = opens[row, buy_indices] * (1 + costs.slippage + impact[buy_indices])
            unit_cost = buy_prices * (1 + fee_rate[buy_indices])
            quantities = np.floor(delta[buy_indices] / unit_cost / costs.lot) * costs.lot
            if impact_enabled:
                quantities = np.floor(capped[buy_indices] / unit_cost / costs.lot) * costs.lot
            required_cash = float(np.dot(quantities, unit_cost))
            if required_cash > cash:
                quantities = np.floor(quantities * (cash / required_cash) / costs.lot) * costs.lot
            for j, price, quantity in zip(buy_indices, buy_prices, quantities):
                if quantity <= 0:
                    continue
                value = quantity * price
                fee = value * fee_rate[j]
                # 浮点尾差也不能让现金为负。
                if value + fee > cash:
                    quantity = np.floor(cash / (price * (1 + fee_rate[j])) / costs.lot) * costs.lot
                    value = quantity * price
                    fee = value * fee_rate[j]
                if quantity <= 0:
                    continue
                cash = max(0.0, cash - (value + fee))
                shares[j] += quantity
                trades.append((date, codes[j], "buy", quantity, price, value, fee))
                if config.fixed_cash_targets:
                    remaining[j] -= value + fee
            pending = retry
            if config.fixed_cash_targets:
                pending |= ((remaining > px * costs.lot * (1 + fee_rate)) |
                            ((remaining < -px * costs.lot) & (shares > 0)))
                pending[retired] = False

        held |= shares > 0
        if ((shares != 0) & (~np.isfinite(closes[row]) | (closes[row] <= 0))).any():
            raise ValueError(f"{date}: held security has no valid mark")
        positions[day] = shares
        cash_history[day] = cash
        nav_history[day] = cash + np.multiply(
            shares, closes[row], out=np.zeros(n), where=shares != 0,
        ).sum()

        history = data.truncate(date)
        exposure = float(strategy.exposure(date, history))
        if not np.isfinite(exposure) or not 0 <= exposure <= 1:
            raise ValueError("exposure 必须在 [0, 1] 内")
        exposure_history[day] = exposure
        rebalance = date in rebalances
        if rebalance:
            base = strategy.target_weights(date, history).astype(float)
            if (
                not base.index.is_unique or not base.index.isin(codes).all()
                or not np.isfinite(base.to_numpy()).all()
                or (base < 0).any() or base.sum() > 1 + 1e-10
            ):
                raise ValueError("目标权重须对应已知代码，非负且合计不超过一")
        if rebalance or exposure != last_exposure:
            last_exposure = exposure
            signal_rows.append(base * exposure)
            signal_dates.append(date)
            if day + 1 < len(dates):
                target = base * exposure
                weights = target.reindex(codes, fill_value=0.0).to_numpy()
                pending = (codes.isin(target.index) | (shares > 0)) & ~retired
                remaining = None
                targets.append(target)
                target_dates.append(dates[day + 1])

    return BacktestResult(
        nav=pd.Series(nav_history, index=dates),
        cash=pd.Series(cash_history, index=dates),
        positions=pd.DataFrame(positions[:, held], index=dates, columns=codes[held]),
        trades=pd.DataFrame(trades, columns=["date", "code", "side", "shares", "price", "value", "fee"]),
        exposure=pd.Series(exposure_history, index=dates),
        target=pd.DataFrame(targets, index=pd.DatetimeIndex(target_dates)).fillna(0.0),
        signals=pd.DataFrame(signal_rows, index=pd.DatetimeIndex(signal_dates)).fillna(0),
    )


def run_futures_account(prices, settlements, mapping, multiplier, targets, config):
    """Integer-contract observation ledger, daily settlement, explicit two-leg rolls.

    Targets are product weights signalled at the last weekly session and executed
    next session CLOSE. Maintain those weights daily; collateral/margin is not
    modelled. Cash equals settled equity, not an equity-like contract market value.
    """
    dates = prices.index[(prices.index >= pd.Timestamp(config.start)) &
                         (prices.index <= pd.Timestamp(config.end))]
    cash = float(config.initial_cash)
    held, marks, weights = {}, {}, pd.Series(dtype=float)
    nav, positions, trades, exposures, signals = [], [], [], [], []

    def quote(frame, date, code):
        value = float(frame.at[date, code])
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{date} {code}: missing actual execution/settlement quote")
        return value

    for i, date in enumerate(dates):
        # Settle yesterday's real contracts; no missing-return zero fill.
        for code, quantity in held.items():
            settle = quote(settlements, date, code)
            cash += quantity * multiplier[code] * (settle - marks[code])
        if i and dates[i - 1] in targets:
            weights = targets[dates[i - 1]].copy()
            signals.append((date, weights.copy()))
        close_equity = cash - sum(q * multiplier[c] *
            (quote(settlements, date, c) - quote(prices, date, c))
            for c, q in held.items())
        desired = {}
        for product, weight in weights.items():
            if not weight:
                continue
            code = mapping.at[date, product]
            if pd.isna(code) or code not in multiplier.index:
                raise ValueError(f"{date} {product}: missing mapping or multiplier")
            price = quote(prices, date, code)
            desired[code] = int(np.trunc(weight * close_equity / (price * multiplier[code])))
        # Iterate old and new contracts separately: rolling always closes the old
        # and opens the new, charging both legs even on a weekly rebalance date.
        for code in sorted(set(held) | set(desired)):
            old, new = held.get(code, 0), desired.get(code, 0)
            delta = new - old
            if delta:
                price = quote(prices, date, code)
                settle = quote(settlements, date, code)
                nominal = abs(delta) * price * multiplier[code]
                fee = nominal * config.costs.commission
                cash += delta * multiplier[code] * (settle - price) - fee
                trades.append((date, code, "buy" if delta > 0 else "sell",
                               abs(delta), price, nominal, fee))
        held = {c: q for c, q in desired.items() if q}
        marks = {c: quote(settlements, date, c) for c in held}
        if not np.isfinite(cash) or cash <= 0:
            raise ValueError(f"{date}: nonpositive settled paper equity")
        nav.append(cash)
        positions.append(held.copy())
        exposures.append(sum(abs(q) * quote(prices, date, c) * multiplier[c]
                             for c, q in held.items()) / cash)
    return BacktestResult(
        nav=pd.Series(nav, index=dates), cash=pd.Series(nav, index=dates),
        positions=pd.DataFrame(positions, index=dates).fillna(0),
        trades=pd.DataFrame(trades, columns=["date", "code", "side", "shares",
                                            "price", "value", "fee"]),
        exposure=pd.Series(exposures, index=dates),
        target=pd.DataFrame([w for _, w in signals],
                            index=pd.DatetimeIndex([t for t, _ in signals])).fillna(0),
        signals=pd.DataFrame([w for t, w in sorted(targets.items())
                             if t in dates], index=pd.DatetimeIndex(
                                 [t for t in sorted(targets) if t in dates])).fillna(0),
    )
