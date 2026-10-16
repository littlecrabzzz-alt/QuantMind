"""Fixed-spec commodity CTA signals and close-to-close futures accounting."""
import numpy as np
import pandas as pd


def continuous_returns(prices, mapping):
    """Earn the previous close's contract return, then roll at today's close.

    A missing current quote remains NaN; the next quote uses the last valid
    price of the same contract, never a price from a different contract.
    """
    prices = prices.sort_index()
    mapping = mapping.reindex(prices.index).ffill()
    held = mapping.shift()
    changes = prices / prices.ffill().shift() - 1
    ret = pd.Series(np.nan, index=prices.index, dtype=float)
    for code in held.dropna().unique():
        if code in changes:
            mask = held.eq(code)
            ret.loc[mask] = changes.loc[mask, code]
    rolled = (mapping.notna() & held.notna() & mapping.ne(held)).astype(bool)
    return ret, rolled


def trend_signal(ret_frame, t):
    history = ret_frame.loc[:t]
    valid = history.notna().sum() >= 250
    result = pd.Series(np.nan, index=ret_frame.columns, dtype=float)
    for code in result.index[valid]:
        recent = history[code].tail(250)
        if recent.notna().all():
            result[code] = np.mean([
                np.sign((1 + recent.tail(window)).prod() - 1)
                for window in (20, 60, 120, 250)])
    return result


def roll_yield(f_near, f_far, days):
    if not (np.isfinite(f_near) and np.isfinite(f_far) and
            np.isfinite(days) and f_near > 0 and f_far > 0 and days > 0):
        return np.nan
    return float(np.log(f_near / f_far) * 365 / days)


def carry_signal(roll_yield_series):
    valid = roll_yield_series.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    ordered = valid.sort_values(ascending=False, kind="stable")
    result = pd.Series(0.0, index=valid.index)
    k = len(valid) // 3
    if k:
        result.loc[ordered.index[:k]] = 1.0
        result.loc[ordered.index[-k:]] = -1.0
    return result


def size_positions(signal, vol, port_vol, target=0.10, max_gross=3.0):
    valid = signal.notna() & np.isfinite(signal) & (vol.reindex(signal.index) > 0)
    valid &= np.isfinite(vol.reindex(signal.index))
    signal = signal[valid]
    if signal.empty:
        return pd.Series(dtype=float)
    raw = signal * target / vol.reindex(signal.index) / len(signal)
    gross = raw.abs().sum()
    if gross == 0:
        return raw
    if not np.isfinite(port_vol) or port_vol < 0:
        return raw * 0
    scale = min(max_gross / gross, target / port_vol if port_vol > 0 else np.inf)
    return raw * scale


def run_futures_portfolio(ret, targets, rolled, cost=0.0002):
    """Signal t -> execute t+1 close -> first P&L t+2.

    Fixed daily target weights approximate costless maintenance rebalancing.
    Roll old positions first, then charge scheduled weight changes on the
    remaining equity; simultaneous events pay both costs conservatively.
    Missing returns contribute zero. Audit tables are attached to nav.attrs.
    """
    ret = ret.sort_index()
    values = ret.fillna(0).to_numpy(float)
    rolls = rolled.reindex(index=ret.index, columns=ret.columns).fillna(False).to_numpy(bool)
    weight = np.zeros(len(ret.columns))
    equity = 1.0
    nav, weights, trades, fees = [], [], [], []
    for i, date in enumerate(ret.index):
        equity *= 1 + weight @ values[i]
        roll_nominal = 2 * np.abs(weight[rolls[i]]).sum() * equity
        fee = roll_nominal * cost
        equity -= fee
        traded = roll_nominal
        if i and ret.index[i - 1] in targets:
            new = targets[ret.index[i - 1]].reindex(ret.columns).fillna(0).to_numpy(float)
            amount = np.abs(new - weight).sum() * equity
            traded += amount
            equity -= amount * cost
            fee += amount * cost
            weight = new
        if not np.isfinite(equity) or equity <= 0:
            raise ValueError(f"Nonpositive/nonfinite equity on {date}")
        nav.append(equity)
        weights.append(weight.copy())
        trades.append(traded)
        fees.append(fee)
    result = pd.Series(nav, index=ret.index, name="nav")
    result.attrs["weights"] = pd.DataFrame(weights, index=ret.index, columns=ret.columns)
    result.attrs["traded_notional"] = pd.Series(trades, index=ret.index)
    result.attrs["costs"] = pd.Series(fees, index=ret.index)
    return result
