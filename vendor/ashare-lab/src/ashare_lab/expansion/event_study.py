"""Announcement selection and vectorized open-to-close event returns (S3)."""

import numpy as np
import pandas as pd

from ashare_lab.industry import industry_at


GROUPS = ("fc_pos", "fc_neg", "buyback", "increase", "decrease", "regulatory")


def select_events(events, calendar, gap=20):
    calendar = pd.DatetimeIndex(calendar)
    out = events.copy()
    out["effective_date"] = pd.to_datetime(out.effective_date)
    kind, sub = out.event_type, out.subtype
    forecast = (kind == "earnings_forecast") & (sub == "initial")
    out["group"] = np.select([
        forecast & out.fc_type.isin(["预增", "略增", "扭亏", "续盈"]),
        forecast & out.fc_type.isin(["预减", "略减", "首亏", "续亏", "增亏", "减亏"]),
        (kind == "buyback") & sub.isin(["plan", "first"]),
        (kind == "insider_increase") & sub.isin(["plan", "complete", "other"]),
        (kind == "insider_decrease") & (sub == "plan"),
        (kind == "regulatory") & sub.isin(["investigation", "penalty", "discipline", "warning"]),
    ], GROUPS, default="")
    out = out[(out.group != "") & out.effective_date.isin(calendar)].sort_values(
        ["code", "group", "effective_date"], kind="stable").reset_index(drop=True)
    positions = calendar.get_indexer(out.effective_date)
    keep = np.zeros(len(out), dtype=bool)
    # Greedy cooldown refers to the last retained event, not the previous raw row.
    last_key, last_day = None, -gap - 1
    for i, (code, group) in enumerate(zip(out.code.to_numpy(), out.group.to_numpy())):
        key = (code, group)
        if key != last_key or positions[i] - last_day > gap:
            keep[i] = True
            last_key, last_day = key, positions[i]
    return out.loc[keep].sort_values(["effective_date", "code"], kind="stable").reset_index(drop=True)


def _liquid(data):
    cal = data.calendar
    listed = pd.to_datetime(data.list_date.reindex(data.close.columns))
    listed_pos = cal.searchsorted(listed)
    listed_pos = np.where(listed < cal[0], -60, listed_pos)
    age = np.arange(len(cal))[:, None] - listed_pos[None, :]
    adv = data.amount.rolling(20, min_periods=1).mean().shift(1).to_numpy()
    return ((age >= 60) & listed.notna().to_numpy()[None, :]
            & ~data.is_st.to_numpy(dtype=bool) & (adv >= 5e7))


def event_returns(selected, data, bench_close, industry, universe, horizons):
    horizons = tuple(horizons)
    if universe not in ("csi800", "liquid"):
        raise ValueError(f"Unknown event universe: {universe}")
    cal, codes = data.calendar, data.close.columns
    out = selected[["code", "effective_date", "group"]].copy().reset_index(drop=True)
    out["effective_date"] = pd.to_datetime(out.effective_date)
    rows, cols = cal.get_indexer(out.effective_date), codes.get_indexer(out.code)
    known = (rows >= 0) & (cols >= 0)
    rr, cc = np.maximum(rows, 0), np.maximum(cols, 0)
    liquid = _liquid(data)
    opens = data.open.to_numpy()
    limits = data.up_limit.to_numpy()
    suspended = data.suspended.to_numpy(dtype=bool)
    if universe == "csi800":
        membership = data.members["000906.SH"].to_numpy(dtype=bool)
        eligible = known & (rows > 0) & membership[np.maximum(rows - 1, 0), cc]
    else:
        eligible = known & liquid[rr, cc]
    skip = np.full(len(out), None, dtype=object)
    skip[~eligible] = "not_in_universe"
    skip[eligible & suspended[rr, cc]] = "suspended"
    valid_open = np.isfinite(opens[rr, cc]) & (opens[rr, cc] > 0)
    skip[eligible & ~suspended[rr, cc] & ~valid_open] = "no_open"
    skip[eligible & ~suspended[rr, cc] & valid_open
         & (opens[rr, cc] >= limits[rr, cc] - 1e-6)] = "limit_up"
    out["skip"] = skip
    usable = pd.isna(skip)
    adjustment = data.adj.ffill().to_numpy()
    adjusted_open = opens * adjustment
    # Freeze the last adjusted close at delisting, including later adjustment gaps.
    prices = data.close.ffill().to_numpy() * adjustment
    delist = pd.to_datetime(data.delist_date.reindex(codes)).to_numpy(dtype="datetime64[ns]")
    retired = cal.to_numpy()[:, None] >= delist[None, :]
    prices[retired] = np.nan
    prices = pd.DataFrame(prices).ffill().to_numpy()
    max_end = np.minimum(rr + max(horizons, default=1) - 1, len(cal) - 1)
    out["delisted"] = (usable & (delist[cc] >= out.effective_date.to_numpy())
                       & (delist[cc] <= cal.to_numpy()[max_end]))
    bench = bench_close.reindex(cal).ffill().to_numpy()
    entry = adjusted_open[rr, cc]
    for h in horizons:
        end = rr + h - 1
        valid = usable & (end < len(cal))
        end_safe = np.minimum(end, len(cal) - 1)
        stock_ret = prices[end_safe, cc] / entry - 1
        benchmark_ret = bench[end_safe] / bench[np.maximum(rr - 1, 0)] - 1
        out[f"car_bench_{h}"] = np.where(valid & (rows > 0), stock_ret - benchmark_ret, np.nan)
        out[f"car_ind_{h}"] = np.nan

    # One batch per entry date: all horizons and all peers, never per-event price reads.
    for day, indices in out.loc[usable].groupby("effective_date", sort=False).groups.items():
        idx = np.asarray(indices)
        row = rows[idx[0]]
        labels, names = pd.factorize(industry_at(day, industry, codes), sort=True)
        n_groups = len(names)
        ends = row + np.asarray(horizons) - 1
        available = ends < len(cal)
        if not available.any():
            continue
        returns = prices[ends[available]] / adjusted_open[row][None, :] - 1
        peers = liquid[row] & np.isfinite(adjusted_open[row]) & (adjusted_open[row] > 0)
        valid = peers[None, :] & np.isfinite(returns)
        bins = labels[None, :] + np.arange(available.sum())[:, None] * n_groups
        sums = np.bincount(bins[valid], weights=returns[valid],
                           minlength=available.sum() * n_groups).reshape(-1, n_groups)
        counts = np.bincount(bins[valid], minlength=available.sum() * n_groups).reshape(-1, n_groups)
        event_cols = cols[idx]
        own_ret = returns[:, event_cols]
        own_valid = valid[:, event_cols]
        sums = sums[:, labels[event_cols]] - np.where(own_valid, own_ret, 0)
        counts = counts[:, labels[event_cols]] - own_valid
        peer_ret = np.divide(sums, counts, out=np.full_like(sums, np.nan), where=counts > 0)
        for k, h in enumerate(np.asarray(horizons)[available]):
            out.loc[idx, f"car_ind_{h}"] = own_ret[k] - peer_ret[k]
    return out


def summarize(per_event, horizons, benchmark, periods):
    rows = []
    dates = pd.to_datetime(per_event.effective_date)
    valid = per_event.skip.isna()
    for group in per_event.group.unique():
        for period, (start, end) in periods.items():
            subset = per_event.loc[valid & (per_event.group == group)
                                   & dates.between(pd.Timestamp(start), pd.Timestamp(end))]
            months = pd.to_datetime(subset.effective_date).dt.to_period("M")
            for h in horizons:
                x = subset[f"car_{benchmark}_{h}"].dropna()
                n, mean = len(x), x.mean()
                sums = (x - mean).groupby(months.loc[x.index]).sum()
                g = len(sums)
                se = np.sqrt(g / (g - 1) * sums.pow(2).sum()) / n if g > 1 else np.nan
                t = mean / se if se > 0 else np.nan
                rows.append({"group": group, "period": period, "h": h, "n": n,
                             "mean": mean, "median": x.median(),
                             "frac_pos": (x > 0).mean() if n else np.nan, "t_stat": t})
    return pd.DataFrame(rows, columns=["group", "period", "h", "n", "mean", "median", "frac_pos", "t_stat"])
