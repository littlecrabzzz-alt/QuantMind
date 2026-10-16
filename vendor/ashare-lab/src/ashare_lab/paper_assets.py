"""Frozen observation inputs; no fetching, selection search or weekday calendars."""
from pathlib import Path

import numpy as np
import pandas as pd

from .data.market import MarketData
from .ideas_cb import select_double_low
from .ideas_cta import (continuous_returns, trend_signal, carry_signal,
                        roll_yield, size_positions)
from .strategy import Strategy


def require_columns(frame, fields, source):
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"{source} missing required source fields: {sorted(missing)}")


class FixedTargets(Strategy):
    def __init__(self, targets):
        self.targets = targets

    def rebalance_dates(self, calendar):
        return pd.DatetimeIndex([t for t in calendar if t in self.targets])

    def target_weights(self, t, data):
        return self.targets[t]


def exchange_days(path, exchange, end):
    frame = pd.read_parquet(path)
    column = "cal_date" if "cal_date" in frame else "date"
    require_columns(frame, ("exchange", "is_open", column), "trade_cal")
    selected = frame.loc[frame.exchange.eq(exchange)]
    if selected.empty or pd.to_numeric(selected.is_open).isna().any():
        raise ValueError(f"Missing real {exchange} exchange calendar")
    dates = pd.DatetimeIndex(pd.to_datetime(selected.loc[
        pd.to_numeric(selected.is_open).eq(1), column].astype(str), format="mixed"))
    dates = dates.drop_duplicates().sort_values()
    if not (dates > pd.Timestamp(end)).any():
        raise ValueError(f"{exchange} calendar must include an open session after cutoff")
    return dates


def i7_calendar_context(path, start, end):
    """Prove TOM month boundaries from real daily SSE rows, never sample tails."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    month_end = end.to_period("M").end_time.normalize()
    next_month = month_end + pd.Timedelta(days=1)
    proof = {"exchange": "SSE", "replay_start": str(start.date()),
             "usable_date": str(end.date()), "calendar_through": None,
             "required_month_end": str(month_end.date()),
             "next_month_first_session": None, "next_two_sessions": [],
             "complete": False, "state": "pending", "reason": ""}
    frame = pd.read_parquet(path)
    column = "cal_date" if "cal_date" in frame else "date"
    require_columns(frame, ("exchange", "is_open", column), "trade_cal")
    selected = frame.loc[frame.exchange.eq("SSE")].copy()
    selected["date"] = pd.to_datetime(selected[column].astype(str), format="mixed")
    selected["open"] = pd.to_numeric(selected.is_open, errors="raise")
    if (selected.empty or selected.date.isna().any() or
            selected.date.duplicated().any() or not selected.open.isin((0, 1)).all()):
        proof["reason"] = "I7 requires unique real SSE calendar dates with is_open 0/1"
        return proof
    dates = pd.DatetimeIndex(selected.date)
    opens = pd.DatetimeIndex(selected.loc[selected.open.eq(1), "date"]).sort_values()
    proof["calendar_through"] = str(dates.max().date())
    proof["next_two_sessions"] = [str(t.date()) for t in opens[opens > end][:2]]
    next_opens = opens[opens.to_period("M") == next_month.to_period("M")]
    if len(next_opens):
        proof["next_month_first_session"] = str(next_opens[0].date())
    required = pd.date_range(start.to_period("M").start_time, month_end, freq="D")
    if not required.isin(dates).all():
        proof["reason"] = f"I7 calendar lacks complete daily month context through {month_end.date()}"
    elif not len(next_opens):
        proof["reason"] = "I7 calendar lacks a confirmed next-month first open session"
    elif not pd.date_range(next_month, next_opens[0], freq="D").isin(dates).all():
        proof["reason"] = "I7 next-month first open is not proven by complete preceding daily rows"
    elif len(proof["next_two_sessions"]) < 2:
        proof["reason"] = "I7 frozen TOM targets require two real open sessions after cutoff"
    else:
        proof.update(complete=True, state="ready", reason="")
    return proof


def period_ends(days, period):
    # Full exchange calendar, not the truncated price sample: no false Friday/month-end.
    return set(days[:-1][days[:-1].to_period(period) != days[1:].to_period(period)])


def bond_market(directory, days, start, end):
    directory = Path(directory)
    basic = pd.read_parquet(directory / "cb_basic.parquet")
    require_columns(basic, ("cb_type", "ts_code", "list_date", "maturity_date", "delist_date"), "cb_basic")
    basic = basic.loc[basic.cb_type.eq("CB")].set_index("ts_code")
    for field in ("list_date", "maturity_date", "delist_date"):
        basic[field] = pd.to_datetime(basic[field].astype(str), format="mixed", errors="coerce")
    dates = days[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]
    frames = [pd.read_parquet(directory / "cb_daily" / f"{t:%Y%m%d}.parquet") for t in dates]
    daily = pd.concat(frames, ignore_index=True).rename(columns={"ts_code": "code", "trade_date": "date"})
    require_columns(daily, ("date", "code", "open", "close", "amount", "cb_over_rate"), "cb_daily")
    daily["date"] = pd.to_datetime(daily.date.astype(str), format="mixed")
    if daily.duplicated(["date", "code"]).any():
        raise ValueError("Duplicate bond date/code")
    daily = daily.loc[daily.code.isin(basic.index)].copy()
    if daily.empty:
        raise ValueError("No actual convertible bond observations")
    daily["amount"] = pd.to_numeric(daily.amount) * 10000
    daily["premium"] = pd.to_numeric(daily.cb_over_rate) / 100
    calls = pd.read_parquet(directory / "cb_call.parquet")
    require_columns(calls, ("ann_date", "call_type", "is_call", "ts_code"), "cb_call")
    calls["ann_date"] = pd.to_datetime(calls.ann_date.astype(str), format="mixed", errors="coerce")
    first = calls.loc[calls.call_type.eq("强赎") & calls.is_call.isin(
        ["公告实施强赎", "公告提示强赎"])].groupby("ts_code").ann_date.min()
    daily["call_announced"] = daily.code.map(first) <= daily.date
    listing = daily.code.map(basic.list_date)
    daily["listed_days"] = days.searchsorted(daily.date, side="right") - days.searchsorted(listing, side="left")
    daily["days_to_maturity"] = (daily.code.map(basic.maturity_date) - daily.date).dt.days
    weekly = period_ends(days, "W-FRI")
    for t, group in daily.groupby("date"):
        if t in weekly and not np.isfinite(group.premium).any():
            raise ValueError(f"{t.date()}: cb_over_rate unavailable for the whole signal session")
    targets = {t: select_double_low(g.set_index("code"), 20)
               for t, g in daily.groupby("date") if t in weekly}
    if not set(dates).issubset(set(daily.date)):
        raise ValueError("Bond input missing whole sessions; refusing empty cash signals")
    codes = pd.Index(sorted(daily.code.unique()))
    def panel(field):
        return daily.pivot(index="date", columns="code", values=field).reindex(index=dates, columns=codes)
    close, open_, amount = panel("close"), panel("open"), panel("amount")
    close = close.where(np.isfinite(close) & close.gt(0))
    empty = pd.DataFrame(np.nan, index=dates, columns=codes)
    one = pd.DataFrame(1.0, index=dates, columns=codes)
    false = pd.DataFrame(False, index=dates, columns=codes)
    # Terminal sample absence is NOT evidence of delisting. Only dated source metadata retires a bond.
    market = MarketData(open_, close, empty.copy(), empty.copy(), one, amount.copy(), amount,
                        open_.isna() | amount.isna() | amount.le(0), false,
                        basic.list_date.reindex(codes), basic.delist_date.reindex(codes), {},
                        pd.DataFrame(index=dates))
    return market, FixedTargets(targets)


def futures_inputs(directory, days, end, start):
    directory = Path(directory)
    basic = pd.read_parquet(directory / "basic.parquet").set_index("ts_code")
    require_columns(basic, ("normalized_multiplier", "list_date", "delist_date", "d_month", "fut_code"), "fut_basic")
    if not basic.index.is_unique:
        raise ValueError("Duplicate futures contract metadata")
    products = {
        "SHF": "CU AL ZN PB NI SN AU AG RB HC RU BU FU SP SS",
        "DCE": "A M Y P C CS JD L V PP J JM I EG EB PG",
        "ZCE": "SR CF TA MA FG RM OI ZC SA UR AP SF SM", "INE": "SC",
    }
    codes = [f"{p}.{e}" for e, names in products.items() for p in names.split()]
    missing = {code.split(".")[0] for code in codes} - set(basic.fut_code)
    if missing:
        raise ValueError(f"Frozen 45-product commodity metadata missing {sorted(missing)}; CFFEX is not a substitute")
    # Commodity raw fut_basic.multiplier may legitimately be null (doc 135).
    # The source normalizer owns unit conversion and its per-contract evidence.
    multiplier = pd.to_numeric(basic["normalized_multiplier"], errors="coerce")
    for field in ("list_date", "delist_date"):
        basic[field] = pd.to_datetime(basic[field].astype(str), format="mixed", errors="raise")
    basic["delivery"] = pd.to_datetime(basic.d_month.astype(str).str.replace(r"\.0$", "", regex=True), format="%Y%m")
    daily = pd.concat([pd.read_parquet(directory / "contracts" / f"{c}.parquet")
                       for c in basic.index], ignore_index=True)
    require_columns(daily, ("trade_date", "ts_code", "close", "settle", "oi"), "fut_daily")
    daily["date"] = pd.to_datetime(daily.trade_date.astype(str), format="mixed")
    if daily.duplicated(["date", "ts_code"]).any():
        raise ValueError("Duplicate futures quotes")
    dates = days[days <= pd.Timestamp(end)]
    def panel(field):
        return daily.pivot(index="date", columns="ts_code", values=field).reindex(dates)
    raw, settle, oi = panel("close"), panel("settle"), panel("oi")
    raw = raw.where(raw.notna(), settle)
    mappings = pd.read_parquet(directory / "mapping.parquet")
    require_columns(mappings, ("trade_date", "ts_code", "mapping_ts_code"), "fut_mapping")
    mappings["date"] = pd.to_datetime(mappings.trade_date.astype(str), format="mixed")
    if mappings.duplicated(["date", "ts_code"]).any():
        raise ValueError("Duplicate futures mappings")
    observation_days = dates[dates >= pd.Timestamp(start)]
    for t in observation_days:
        if (not raw.loc[t].gt(0).any() or not settle.loc[t].gt(0).any() or
                not mappings.date.eq(t).any()):
            raise ValueError(f"{t.date()}: actual futures quotes/settlements/mapping missing; cannot create a flat fake observation")
    mapping = mappings.pivot(index="date", columns="ts_code", values="mapping_ts_code").reindex(index=dates, columns=codes).ffill()
    # Keep all signal history unchanged; only executable/warmup contract units
    # are mandatory. Include 251 preceding sessions and the held-contract anchor.
    unit_start = max(0, dates.searchsorted(pd.Timestamp(start)) - 252)
    required_units = set(mapping.iloc[unit_start:].stack().dropna())
    ret, observed = {}, {}
    for code in codes:
        contracts = basic.index[basic.fut_code.eq(code.split(".")[0])]
        prices = raw.reindex(columns=contracts)
        obs, _ = continuous_returns(prices, mapping[code])
        observed[code] = obs.notna().cumsum()
        ret[code], _ = continuous_returns(prices.ffill(), mapping[code])
    ret, observed = pd.DataFrame(ret), pd.DataFrame(observed)
    if observed.empty or not observed.iloc[-1].ge(250).any():
        raise ValueError("No commodity has the frozen 250 observed-return warmup; refusing a fake flat account")
    targets = {"cta_trend": {}, "cta_combined": {}}
    for t in sorted(period_ends(days, "W-FRI") & set(dates)):
        window = ret.loc[:t].tail(60).fillna(0)
        vol = window.std(ddof=1) * np.sqrt(252)
        eligible = observed.loc[t].ge(250) & vol.gt(0)
        trend = trend_signal(ret, t).where(eligible).dropna()
        yields = pd.Series(np.nan, index=ret.columns)
        for product in ret.columns[eligible]:
            near = mapping.at[t, product]
            if near not in basic.index or near not in raw:
                continue
            info = basic.loc[near]
            far = basic.loc[(basic.fut_code == info.fut_code) & (basic.delivery > info.delivery)
                            & (basic.list_date <= t) & (basic.delist_date > t)]
            far = far.loc[oi.loc[t].reindex(far.index).fillna(0).gt(0)]
            if t >= pd.Timestamp(start):
                required_units.update(far.index)
            if far.empty:
                continue
            far = far.sort_index().sort_values(["delivery", "delist_date"], kind="stable")
            yields[product] = roll_yield(raw.at[t, near], raw.at[t, far.index[0]],
                                       (far.iloc[0].delist_date - info.delist_date).days)
        carry = carry_signal(yields)
        for name, signal in (("cta_trend", trend), ("cta_combined", ((trend + carry) / 2).dropna())):
            signal = signal[vol.reindex(signal.index).gt(0)]
            weights = signal * .10 / vol.reindex(signal.index) / max(len(signal), 1)
            port_vol = window.reindex(columns=signal.index).mul(weights).sum(axis=1).std(ddof=1) * np.sqrt(252)
            targets[name][t] = size_positions(signal, vol, port_vol, .10, 3.0)
    required_multiplier = multiplier.reindex(sorted(required_units))
    invalid = ~np.isfinite(required_multiplier) | required_multiplier.le(0)
    if invalid.any():
        raise ValueError("Missing/nonpositive source normalized futures multiplier "
                         f"in required warmup/replay mapping/carry closure: {required_multiplier.index[invalid].tolist()}")
    return raw, settle, mapping, multiplier, targets
