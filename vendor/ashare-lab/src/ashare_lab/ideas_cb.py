"""I8 point-in-time double-low selection and fractional-unit cash execution."""

import numpy as np
import pandas as pd


def conv_price_asof(t, changes):
    """Latest price known and effective by t; missing dates are not backfilled."""
    frame = changes.copy()
    ann = pd.to_datetime(frame.ann_date, errors="coerce")
    change = pd.to_datetime(frame.change_date, errors="coerce")
    frame["effective"] = pd.concat([ann, change], axis=1).max(axis=1)
    frame = frame[ann.notna() & change.notna() & (frame.effective <= pd.Timestamp(t))]
    # Conflicting records at the same timestamp cannot be resolved without evidence.
    conflicts = frame.groupby(["code", "effective"]).conv_price.nunique()
    if (conflicts > 1).any():
        raise ValueError("Conflicting conversion prices at the same effective timestamp")
    return (frame.sort_values("effective", kind="stable").drop_duplicates("code", keep="last")
            .set_index("code").conv_price)


def premium_rate(close, stock_close, conv_price):
    """Decimal conversion premium, using unadjusted underlying close."""
    return close / (100 / conv_price * stock_close) - 1


def select_double_low(snapshot, n):
    if n <= 0:
        raise ValueError("n must be positive")
    good = ((snapshot.amount > 0) & (snapshot.listed_days >= 5)
            & (snapshot.days_to_maturity > 180) & snapshot.call_announced.eq(False)
            & (snapshot.close > 0) & np.isfinite(snapshot.close)
            & np.isfinite(snapshot.premium))
    score = (snapshot.close + snapshot.premium * 100)[good]
    chosen = score.sort_index().sort_values(kind="stable").head(n).index
    return pd.Series(1 / len(chosen), index=chosen, dtype=float) if len(chosen) else pd.Series(dtype=float)


def run_cb_backtest(open, close, amount, targets, cost, initial_cash,
                    max_participation=None, impact_k=0.0, impact_window=20,
                    return_details=False):
    """Signal at close, execute next open; failed orders retain fixed cash targets.

    On the first execution day freeze W * opening equity. Retry only unfilled
    notional until a new signal replaces it. Amount must be in yuan. Capacity
    uses prior-day ADV and log-return volatility, as in engine.py (B5).
    Returns normalized NAV, optionally with cash, holdings and turnover details.
    """
    if not 0 <= cost < 1 or initial_cash <= 0 or impact_k < 0:
        raise ValueError("Invalid cost, cash or impact")
    if max_participation is not None and not 0 < max_participation <= 1:
        raise ValueError("Invalid participation cap")
    if not close.index.is_monotonic_increasing or not close.index.is_unique:
        raise ValueError("Dates must be sorted and unique")
    close = close.where(np.isfinite(close) & (close > 0))
    dates, codes = close.index, close.columns
    o = open.reindex(index=dates, columns=codes).to_numpy(float)
    a = amount.reindex(index=dates, columns=codes).to_numpy(float)
    c = close.to_numpy(float)
    marked = close.ffill().to_numpy(float)
    valid_close = np.isfinite(c) & (c > 0)
    last = np.where(valid_close, np.arange(len(dates))[:, None], -1).max(axis=0)
    capacity = max_participation is not None or impact_k > 0
    if capacity:
        adv = (pd.DataFrame(a).fillna(0).rolling(impact_window, min_periods=1)
               .mean().shift(1).fillna(0).to_numpy())
        sigma = (np.log(close.ffill()).diff().rolling(impact_window, min_periods=2)
                 .std(ddof=1).shift(1).fillna(0).to_numpy())
    shares = np.zeros(len(codes))
    remaining = np.zeros(len(codes))
    liquidate = np.zeros(len(codes), dtype=bool)
    pending_weights = None
    cash = float(initial_cash)
    records = []
    for i, date in enumerate(dates):
        previous = marked[i - 1] if i else np.full(len(codes), np.nan)
        retired = i > last
        exiting = retired & (shares > 0)
        cash += float(np.sum(shares[exiting] * previous[exiting]))
        shares[retired] = 0
        remaining[retired] = 0
        px = np.where(np.isfinite(o[i]) & (o[i] > 0), o[i], previous)
        value = np.multiply(shares, px, out=np.zeros(len(codes)), where=shares > 0)
        equity = cash + value.sum()
        if pending_weights is not None:
            liquidate = pending_weights == 0
            remaining = pending_weights * equity - value
            remaining[retired] = 0
            pending_weights = None
        # A zero-weight exit sells the remaining units, including price changes
        # during a suspension; cash-sized buy orders retain their original budget.
        remaining[liquidate] = -value[liquidate]
        tradable = np.isfinite(o[i]) & (o[i] > 0) & np.isfinite(a[i]) & (a[i] > 0) & ~retired
        planned = np.abs(remaining)
        if capacity:
            tradable &= np.isfinite(adv[i]) & (adv[i] > 0)
            if max_participation is not None:
                planned = np.minimum(planned, adv[i] * max_participation)
        planned[~tradable] = 0
        sell = np.where(remaining < 0, np.minimum(planned, value), 0)
        impact = np.zeros(len(codes))
        if capacity:
            participation = np.divide(sell, adv[i], out=np.zeros(len(codes)), where=adv[i] > 0)
            impact = impact_k * sigma[i] * np.sqrt(participation)
        proceeds = sell * (1 - cost - impact)
        if (proceeds < 0).any():
            raise ValueError("Impact exceeds sale proceeds")
        cash += proceeds.sum()
        sold_units = np.divide(sell, o[i], out=np.zeros(len(codes)), where=tradable)
        shares = np.maximum(0, shares - sold_units)
        shares[tradable & (remaining < 0) & (sell >= value)] = 0
        remaining += sell
        # Fully liquidated positions have no residual sell order after price moves.
        remaining[(shares == 0) & (remaining < 0)] = 0
        buy = np.where(remaining > 0, planned, 0)
        total = buy.sum()
        if total > cash:
            buy *= cash / total
        if capacity:
            participation = np.divide(buy, adv[i], out=np.zeros(len(codes)), where=adv[i] > 0)
            impact = impact_k * sigma[i] * np.sqrt(participation)
        else:
            impact = np.zeros(len(codes))
        # Base fees use the specified net-of-cost notional; B5 square-root
        # impact increases the execution price, reducing acquired units.
        shares += np.divide(buy * (1 - cost), o[i] * (1 + impact),
                            out=np.zeros(len(codes)), where=tradable)
        cash = max(0.0, cash - buy.sum())
        remaining -= buy
        remaining[np.abs(remaining) < initial_cash * 1e-12] = 0
        closing_value = np.multiply(shares, marked[i], out=np.zeros(len(codes)), where=shares > 0)
        nav = cash + closing_value.sum()
        realized = (np.divide(sell + buy, adv[i], out=np.zeros(len(codes)), where=adv[i] > 0).max()
                    if capacity else 0.0)
        records.append((nav / initial_cash, cash, int((shares > 0).sum()),
                        (sell.sum() + buy.sum()) / (2 * equity) if equity > 0 else 0, realized))
        if date in targets:
            weights = pd.Series(targets[date], dtype=float)
            if (not weights.index.is_unique or not weights.index.isin(codes).all()
                    or not np.isfinite(weights).all() or (weights < 0).any()
                    or weights.sum() > 1 + 1e-10):
                raise ValueError(f"Invalid target on {date}")
            pending_weights = weights.reindex(codes, fill_value=0).to_numpy()
    details = pd.DataFrame(records, index=dates,
                           columns=["nav", "cash", "holdings", "turnover", "max_participation"])
    return details if return_details else details.nav
