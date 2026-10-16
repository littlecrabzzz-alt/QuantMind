"""Trade announcement cohorts at the next open using the existing engine."""

import numpy as np
import pandas as pd

from ashare_lab.strategy import Strategy


class _ChangeDate:
    """A scheduled date enabled only after its close has changed the name list.

    The engine freezes rebalance dates into a set before running. Its membership
    query follows exposure(), allowing a failed entry to cancel the next-open
    retry without also rebalancing every successful entry on its second day.
    """

    def __init__(self, date, strategy):
        self.date, self.strategy = date, strategy

    def __hash__(self):
        return hash(self.date)

    def __eq__(self, other):
        return self.date == other and self.strategy._changed


class EventPortfolio(Strategy):
    def __init__(self, events, hold=20, max_names=50, universe="000906.SH"):
        if hold < 1 or max_names < 1:
            raise ValueError("hold and max_names must be positive")
        self.events = events.copy()
        self.events["effective_date"] = pd.to_datetime(self.events.effective_date)
        self.hold, self.max_names, self.universe = hold, max_names, universe
        groups = self.events.group.unique() if "group" in self.events else []
        group = groups[0] if len(groups) == 1 else "events"
        self.name = f"s3_{group}_h{hold}"

    def rebalance_dates(self, calendar):
        self._calendar = pd.DatetimeIndex(calendar)
        self._entries = {date: list(group.code.drop_duplicates())
                         for date, group in self.events.groupby("effective_date")}
        self._active = {}  # code -> (entry position, expiry signal position)
        self._changed = False
        self._last_date = None
        return [_ChangeDate(date, self) for date in self._calendar]

    def exposure(self, t, data):
        if t == self._last_date:
            return 1.0
        self._last_date = t
        pos = self._calendar.get_loc(t)
        previous = set(self._active)
        for code, (entry, expiry) in list(self._active.items()):
            failed = False
            if entry == pos:
                opening = data.open.at[t, code]
                limit = data.up_limit.at[t, code]
                failed = (data.suspended.at[t, code] or not np.isfinite(opening)
                          or opening <= 0 or opening >= limit - 1e-6)
            retired = pd.notna(data.delist_date[code]) and data.delist_date[code] <= t
            if failed or retired or expiry <= pos:
                del self._active[code]
        if pos + 1 < len(self._calendar):
            effective = self._calendar[pos + 1]
            candidates = [code for code in self._entries.get(effective, [])
                          if code in data.close.columns and code not in self._active]
            if candidates:
                member = data.members[self.universe].loc[t]
                candidates = [code for code in candidates if member[code]
                              and (pd.isna(data.delist_date[code]) or data.delist_date[code] > t)]
                adv = data.amount.loc[:t, candidates].tail(20).mean()
                ranked = adv.sort_values(ascending=False, kind="stable", na_position="last")
                vacancies = max(0, self.max_names - len(self._active))
                for code in ranked.index[:vacancies]:
                    self._active[code] = (pos + 1, pos + self.hold)
        self._changed = previous != set(self._active)
        return 1.0

    def target_weights(self, t, data):
        names = list(self._active)
        return pd.Series(1 / len(names), index=names, dtype=float) if names else pd.Series(dtype=float)
