"""期货合约选择及逐日保证金账户；全部指令在下一交易日收盘执行。"""

import numpy as np
import pandas as pd


def target_contracts(mapping, basic, calendar, roll_days=5):
    basic = basic.copy()
    for col in ("list_date", "delist_date"):
        basic[col] = pd.to_datetime(basic[col])
    basic = basic.drop_duplicates("ts_code").set_index("ts_code")
    calendar = pd.DatetimeIndex(calendar).sort_values()
    result = mapping.copy()
    for t, code in mapping.items():
        if pd.isna(code):
            continue
        expiry = basic.loc[code, "delist_date"]
        remaining = calendar.searchsorted(expiry, side="right") - calendar.searchsorted(t, side="right")
        # 日历截断不能当成临近到期；覆盖范围以外保留已知主力映射。
        if expiry > calendar[-1]:
            continue
        if remaining <= roll_days:
            product = code[:2]
            candidates = basic[(basic.index.str.startswith(product)) &
                               (basic.list_date <= t) & (basic.delist_date > expiry)]
            if not candidates.empty:
                result.loc[t] = candidates.sort_values("delist_date").index[0]
    return result


def simulate_hedge(long_nav, prices, contracts, ratio, index_close, cash_return=None,
                   margin=0.15, fut_cost=1.23e-4, transfer_cost=0.0015):
    dates = long_nav.dropna().sort_index().index
    long_returns = long_nav.reindex(dates).pct_change(fill_method=None).fillna(0)
    prices = prices.reindex(dates).ffill()
    contracts = contracts.reindex(dates).ffill()
    index_returns = {p: s.reindex(dates).ffill().pct_change(fill_method=None).fillna(0)
                     for p, s in index_close.items()}
    cash_returns = (pd.Series(0.0, index=dates) if cash_return is None else
                    cash_return.reindex(dates).fillna(0))
    L, C, q, excess, traded_total = 0.0, 1.0, 0.0, 1.0, 0.0
    held = None
    rows = []

    def price(t, code):
        value = prices.at[t, code]
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"期货价格不可用: {t} {code}")
        return value

    for i, t in enumerate(dates):
        previous_L, previous_V = L, L + C
        pnl, basis, traded, long_pnl = 0.0, 0.0, 0.0, 0.0
        if i:
            C *= 1 + cash_returns.loc[t]
            long_pnl = L * long_returns.loc[t]
            L += long_pnl
            if held is not None:
                old_price = price(dates[i - 1], held)
                change = price(t, held) - old_price
                pnl = -q * change
                C += pnl
                basis = -q * (change - old_price * index_returns[held[:2]].loc[t]) / previous_V
            signal_day = dates[i - 1]
            desired = contracts.loc[signal_day]
            monthly = signal_day in ratio.index
            old_notional = q * price(t, held) if held is not None else 0.0
            if monthly:
                h = float(ratio.loc[signal_day])
                value = L + C
                new_L = value / (1 + margin * h)
                new_notional = h * new_L
                traded = (old_notional + new_notional if desired != held else
                          abs(new_notional - old_notional))
                C = value - new_L - transfer_cost * abs(new_L - L)
                L = new_L
                held = desired
                q = new_notional / price(t, held)
            elif held is not None and pd.notna(desired) and desired != held:
                # 收盘移仓：当日旧合约计盈亏，新合约自下一日开始计盈亏。
                traded = 2 * old_notional
                held = desired
                q = old_notional / price(t, held)
            fee = traded * fut_cost
            C -= fee
            traded_total += traded
            denominator = previous_L if previous_L > 0 else L
            if denominator > 0:
                excess *= 1 + (long_pnl + pnl - fee) / denominator
        notional = q * price(t, held) if held is not None else 0.0
        rows.append((L + C, excess, basis, held, L, notional, C / (L + C), traded))
    frame = pd.DataFrame(rows, index=dates, columns=["nav", "excess_nav", "basis", "held", "L",
                                                   "hedge_notional", "cash_ratio", "fut_traded"])
    result = {c: frame[c] for c in frame}
    result.update(basis_annual=frame.basis.groupby(dates.year).sum(),
                  min_cash_ratio=float(frame.cash_ratio.min()),
                  fut_turnover=traded_total / frame.nav.mean() * 252 / max(1, len(dates) - 1))
    return result
