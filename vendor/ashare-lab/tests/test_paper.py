"""虚拟盘（前向模拟）验收测试：开户即建仓、只追加账本、待执行目标、指标。"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import CostModel
from ashare_lab.strategy import Strategy, month_end_dates
from ashare_lab.strategies.vol_target import VolTarget
from ashare_lab import paper

from synth import make_data, refresh_limits, ZERO_COST

DATES = pd.bdate_range("2024-01-01", "2024-05-31")
OPEN_DAYS = DATES.union(pd.DatetimeIndex(["2024-06-03"]))
CODES = ["A", "B", "C", "D"]


def market(seed=0):
    rng = np.random.default_rng(seed)
    data = make_data(DATES, CODES)
    for i, c in enumerate(CODES):
        r = rng.normal(0.0005, 0.01 * (i + 1), len(DATES))
        px = 10 * np.exp(np.cumsum(r))
        data.close[c] = px
        data.open[c] = np.r_[10.0, px[:-1]] * (1 + rng.normal(0, 0.002, len(DATES)))
    return refresh_limits(data)


class EqualMonthly(Strategy):
    """月末等权前两只（按代码）；任意日期都能给权重。"""

    name = "eqm"

    def __init__(self):
        self.calls = []

    def rebalance_dates(self, calendar):
        return month_end_dates(calendar)

    def target_weights(self, t, data):
        self.calls.append((pd.Timestamp(t), data.calendar.max()))
        return pd.Series(0.5, index=["A", "B"])


def sim(strategy, inception, end, cash=1e6, data=None):
    data = data if data is not None else market()
    return paper.simulate(strategy, data, inception, end, cash, CostModel(**ZERO_COST))


def files_digest(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.is_file()}


# ---------- 开户即建仓 ----------

def test_inception_rebalance_builds_next_open_and_keeps_month_ends():
    inception = "2024-02-14"  # 月中
    result, _ = sim(paper.InceptionRebalance(EqualMonthly(), inception, open_days=OPEN_DAYS), inception, "2024-04-30")
    first_trade = result.trades["date"].min()
    assert pd.Timestamp(first_trade) == pd.Timestamp("2024-02-15")
    assert result.nav.index[0] == pd.Timestamp(inception)
    assert result.nav.iloc[0] == pytest.approx(1e6)
    # 之后月末仍调仓：目标在 2 月、3 月最后交易日的下一交易日生效
    effective = set(result.target.index)
    assert pd.Timestamp("2024-02-15") in effective
    assert pd.Timestamp("2024-03-01") in effective
    assert pd.Timestamp("2024-04-01") in effective


def test_inception_rebalance_dates_union_and_no_lookahead():
    base = EqualMonthly()
    strat = paper.InceptionRebalance(base, "2024-02-14", open_days=OPEN_DAYS)
    dates = strat.rebalance_dates(DATES)
    assert dates[0] == pd.Timestamp("2024-02-14")
    assert all(d > pd.Timestamp("2024-02-14") for d in dates[1:])
    assert pd.Timestamp("2024-01-31") not in dates
    assert dates.is_monotonic_increasing and dates.is_unique
    sim(strat, "2024-02-14", "2024-04-30")
    assert base.calls and all(t == seen for t, seen in base.calls)
    assert strat.name == base.name


def test_inception_on_month_end_not_duplicated():
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-29", open_days=OPEN_DAYS)
    dates = strat.rebalance_dates(DATES)
    assert list(dates).count(pd.Timestamp("2024-02-29")) == 1


def test_works_inside_vol_target():
    inception = "2024-03-12"
    vt = VolTarget(base=paper.InceptionRebalance(EqualMonthly(), inception, open_days=OPEN_DAYS),
                   target_vol=0.05, window=10, step=0.1)
    result, _ = sim(vt, inception, "2024-05-31")
    assert pd.Timestamp(result.trades["date"].min()) == pd.Timestamp("2024-03-13")
    assert (result.exposure.loc["2024-03-12":] < 1).any()


# ---------- 待执行目标 ----------

def test_pending_target_on_rebalance_day():
    inception = "2024-02-14"
    _, pending = sim(paper.InceptionRebalance(EqualMonthly(), inception, open_days=OPEN_DAYS), inception, "2024-04-30")
    assert pending is not None
    assert pending.to_dict() == pytest.approx({"A": 0.5, "B": 0.5})


def test_no_pending_target_mid_month():
    inception = "2024-02-14"
    _, pending = sim(paper.InceptionRebalance(EqualMonthly(), inception, open_days=OPEN_DAYS), inception, "2024-04-17")
    assert pending is None


def test_pending_target_when_exposure_changes():
    class Exp(EqualMonthly):
        def exposure(self, t, data):
            return 0.5 if pd.Timestamp(t) >= pd.Timestamp("2024-04-17") else 1.0

    inception = "2024-02-14"
    _, pending = sim(paper.InceptionRebalance(Exp(), inception, open_days=OPEN_DAYS), inception, "2024-04-17")
    assert pending is not None
    assert pending.to_dict() == pytest.approx({"A": 0.25, "B": 0.25})
    _, pending = sim(paper.InceptionRebalance(Exp(), inception, open_days=OPEN_DAYS), inception, "2024-04-18")
    assert pending is None


# ---------- 账本：只追加 ----------

META = {"name": "eqm", "params": {"top_n": 2}, "inception": "2024-02-14", "initial_cash": 1e6}


def test_init_account_freezes_meta(tmp_path):
    d = tmp_path / "acct"
    paper.init_account(d, META)
    saved = json.loads((d / "meta.json").read_text())
    assert saved["params"] == {"top_n": 2} and "created_at" in saved
    before = (d / "meta.json").read_bytes()
    paper.init_account(d, dict(META))  # 相同参数：允许，不改文件
    assert (d / "meta.json").read_bytes() == before
    with pytest.raises(paper.LedgerMismatch):
        paper.init_account(d, {**META, "params": {"top_n": 3}})
    assert (d / "meta.json").read_bytes() == before


def test_append_only_and_idempotent(tmp_path):
    d = tmp_path / "acct"
    paper.init_account(d, META)
    strat = lambda: paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS)
    r1, _ = sim(strat(), "2024-02-14", "2024-03-20")
    info = paper.append_ledger(d, r1)
    assert info["new_dates"][0] == pd.Timestamp("2024-02-14")
    assert info["last_date"] == pd.Timestamp("2024-03-20")
    old = {n: (d / n).read_bytes() for n in ("nav.csv", "positions.csv", "trades.csv", "targets.csv")}

    r2, _ = sim(strat(), "2024-02-14", "2024-04-30")
    info = paper.append_ledger(d, r2)
    assert info["new_dates"][0] == pd.Timestamp("2024-03-21")
    assert info["last_date"] == pd.Timestamp("2024-04-30")
    for n, content in old.items():
        assert (d / n).read_bytes().startswith(content), n

    digest = files_digest(d)
    info = paper.append_ledger(d, r2)
    assert info["new_dates"] == []
    assert files_digest(d) == digest

    led = paper.read_ledger(d)
    assert led["nav"].index.equals(r2.nav.index)
    np.testing.assert_allclose(led["nav"]["nav"].to_numpy(), r2.nav.to_numpy(), rtol=1e-9)
    np.testing.assert_allclose(led["nav"]["cash"].to_numpy(), r2.cash.to_numpy(), rtol=1e-9, atol=1e-6)
    assert len(led["trades"]) == len(r2.trades)
    pos = led["positions"]
    last_pos = pos.loc[pos["date"] == led["nav"].index[-1]].set_index("code")["shares"]
    expect = r2.positions.iloc[-1]
    expect = expect[expect > 0]
    assert last_pos.sort_index().to_dict() == expect.sort_index().to_dict()


def test_mismatch_on_history_raises_and_writes_nothing(tmp_path):
    d = tmp_path / "acct"
    paper.init_account(d, META)
    r1, _ = sim(paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS), "2024-02-14", "2024-03-20")
    paper.append_ledger(d, r1)
    digest = files_digest(d)

    data = market()
    data.close.loc["2024-03-01":, "A"] *= 1.05  # 模拟历史数据被修订
    data = refresh_limits(data)
    r2, _ = sim(paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS), "2024-02-14", "2024-04-30",
                data=data)
    with pytest.raises(paper.LedgerMismatch):
        paper.append_ledger(d, r2)
    assert files_digest(d) == digest


def test_shorter_result_raises(tmp_path):
    d = tmp_path / "acct"
    paper.init_account(d, META)
    r1, _ = sim(paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS), "2024-02-14", "2024-03-20")
    paper.append_ledger(d, r1)
    digest = files_digest(d)
    r0, _ = sim(paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS), "2024-02-14", "2024-03-10")
    with pytest.raises(paper.LedgerMismatch):
        paper.append_ledger(d, r0)
    assert files_digest(d) == digest


def test_different_inception_raises(tmp_path):
    d = tmp_path / "acct"
    paper.init_account(d, META)
    r1, _ = sim(paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS), "2024-02-14", "2024-03-20")
    paper.append_ledger(d, r1)
    r2, _ = sim(paper.InceptionRebalance(EqualMonthly(), "2024-02-15", open_days=OPEN_DAYS), "2024-02-15", "2024-04-30")
    with pytest.raises(paper.LedgerMismatch):
        paper.append_ledger(d, r2)


# ---------- 指标 ----------

def test_account_summary():
    idx = pd.bdate_range("2024-01-01", periods=6)
    nav = pd.Series([100.0, 101, 99, 102, 103, 101], index=idx)
    trades = pd.DataFrame({
        "date": [idx[1], idx[3], idx[3]], "code": ["A", "A", "B"],
        "side": ["buy", "sell", "delist"], "shares": [100, 100, 100],
        "price": [1.0, 1.0, 1.0], "value": [100.0, 60.0, 500.0], "fee": [0.1, 0.2, 0.0]})
    bench = pd.DataFrame({"000906.SH": [10.0, 10.1, 9.9, 10.0, 10.2, 10.1],
                          "000906.SH_TR": [10.0, 10.11, 9.92, 10.03, 10.24, 10.15]}, index=idx)
    s = paper.account_summary(nav, trades, bench)
    assert s["days"] == 5
    assert s["total_return"] == pytest.approx(0.01)
    assert s["max_drawdown"] == pytest.approx(99 / 101 - 1)
    assert s["cagr"] == pytest.approx(1.01 ** (252 / 5) - 1)
    assert s["turnover"] == pytest.approx(160 / 2 / nav.mean() * 252 / 5)
    assert s["cost"] == pytest.approx(0.3)
    for b in ("000906.SH", "000906.SH_TR"):
        assert s[f"{b}:return"] == pytest.approx(bench[b].iloc[-1] / bench[b].iloc[0] - 1)
        for k in ("alpha_ann", "beta", "excess_cagr"):
            assert f"{b}:{k}" in s
            assert math.isfinite(s[f"{b}:{k}"])
    for k in ("sharpe", "ann_vol"):
        assert math.isfinite(s[k])


# ---------- 数据末日不是真正月末时不能当调仓日 ----------

def test_partial_month_end_dropped_by_default():
    cal = DATES[DATES <= "2024-04-17"]
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS)
    dates = strat.rebalance_dates(cal)
    assert pd.Timestamp("2024-04-17") not in dates
    assert pd.Timestamp("2024-03-29") in dates


def test_open_days_decide_true_month_end():
    # 交易所日历：假设 2024-04-30 休市，04-29 是 4 月最后交易日
    open_days = DATES[DATES != pd.Timestamp("2024-04-30")]
    cal = DATES[DATES <= "2024-04-29"]
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=open_days)
    assert pd.Timestamp("2024-04-29") in strat.rebalance_dates(cal)
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=OPEN_DAYS)
    assert pd.Timestamp("2024-04-29") not in strat.rebalance_dates(cal)
    # 数据只到 04-26 时，04-26 不是月末
    cal = DATES[DATES <= "2024-04-26"]
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=open_days)
    assert pd.Timestamp("2024-04-26") not in strat.rebalance_dates(cal)


def test_paper_requires_explicit_future_exchange_session():
    cal = DATES[DATES <= "2024-04-29"]
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-14")
    with pytest.raises(ValueError, match="real exchange calendar"):
        strat.rebalance_dates(cal)
    strat = paper.InceptionRebalance(EqualMonthly(), "2024-02-14", open_days=cal)
    with pytest.raises(ValueError, match="extend beyond"):
        strat.rebalance_dates(cal)
