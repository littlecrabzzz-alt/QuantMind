"""Engineering checks only; synthetic quotes never become observation artifacts."""
import json

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import BacktestConfig, CostModel, run_backtest, run_futures_account
from ashare_lab.paper import LedgerMismatch, append_ledger, _read_frames
from ashare_lab.paper_assets import FixedTargets, exchange_days, i7_calendar_context, period_ends
from ashare_lab.paper_runtime import (_initialize, _transaction, _recover, _assert_seal,
                                      frozen_specs, file_hash)
from ashare_lab.data.market import MarketData


def sample_bindings(code_hash):
    return {"user_id": "10000001", "tenant_id": "default", "accounts": {
        name: {"strategy_id": str(i), "frozen_source_id": "fixture-source-" + name,
               "runtime_code_sha256": code_hash, "strategy_code_sha256": "fixture-code"}
        for i, name in enumerate(frozen_specs(), 1)}}


def test_new_account_has_no_fabricated_nav_and_refuses_changed_code(tmp_path):
    directory = tmp_path / "cta_trend"
    _initialize(directory, "cta_trend", tmp_path, {"replay_start": "2026-10-14"},
                "frozen-code", sample_bindings("frozen-code"))
    assert not (directory / "nav.csv").exists()
    _assert_seal(directory)
    with pytest.raises(LedgerMismatch, match="Frozen spec/code/start"):
        _initialize(directory, "cta_trend", tmp_path, {"replay_start": "2026-10-14"}, "changed-code", sample_bindings("changed-code"))


def test_transaction_resumes_and_refuses_historical_tamper(tmp_path, monkeypatch):
    import ashare_lab.paper_runtime as runtime
    directory = tmp_path / "account"
    directory.mkdir()
    (directory / "nav.csv").write_bytes(b"old\n")
    original = runtime._recover
    monkeypatch.setattr(runtime, "_recover", lambda _: None)
    _transaction(directory, {"nav.csv": b"old\nnew\n", "positions.csv": b"positions\n"})
    assert (directory / "nav.csv").read_bytes() == b"old\n"
    monkeypatch.setattr(runtime, "_recover", original)
    # Simulate a crash after the first replacement but before other replacements.
    plan = json.loads((directory / "pending.json").read_text())
    first = plan[0]
    (directory / first["name"]).write_bytes((directory / first["staged"]).read_bytes())
    _recover(directory)
    assert (directory / "positions.csv").read_bytes() == b"positions\n"
    assert not (directory / "pending.json").exists()
    monkeypatch.setattr(runtime, "_recover", lambda _: None)
    _transaction(directory, {"nav.csv": b"old\nnew\nthird\n"})
    (directory / "nav.csv").write_bytes(b"tampered\n")
    with pytest.raises(LedgerMismatch, match="tampered"):
        original(directory)


def test_real_calendar_does_not_infer_weekdays(tmp_path):
    path = tmp_path / "calendar.parquet"
    pd.DataFrame({"exchange": ["SSE"] * 3, "cal_date": ["20260929", "20260930", "20261009"],
                  "is_open": [1, 1, 1]}).to_parquet(path)
    days = exchange_days(path, "SSE", "2026-09-30")
    assert pd.Timestamp("2026-09-30") in period_ends(days, "M")
    assert pd.Timestamp("2026-09-30") in period_ends(days, "W-FRI")
    with pytest.raises(ValueError, match="after cutoff"):
        exchange_days(path, "SSE", "2026-10-09")
    with pytest.raises(ValueError, match="Missing real"):
        exchange_days(path, "DCE", "2026-09-30")


def october_calendar(tmp_path, through):
    dates = pd.date_range("2026-10-01", through, freq="D")
    # Explicit fixture sessions; production must read real SSE open/closed rows.
    opens = pd.to_datetime([
        "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
        "2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22",
        "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
        "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"])
    path = tmp_path / "calendar.parquet"
    pd.DataFrame({"exchange": "SSE", "cal_date": dates.strftime("%Y%m%d"),
                  "is_open": dates.isin(opens).astype(int)}).to_parquet(path)
    return path


def test_i7_partial_october_context_is_pending_not_a_false_month_end(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import ashare_lab.paper_runtime as runtime
    path = october_calendar(tmp_path, "2026-10-16")
    context = i7_calendar_context(path, "2026-10-14", "2026-10-15")
    assert context["state"] == "pending"
    assert context["complete"] is False
    assert context["required_month_end"] == "2026-10-31"
    assert context["next_two_sessions"] == ["2026-10-16"]
    days = exchange_days(path, "SSE", "2026-10-15")
    inputs = {"usable_date": "2026-10-15", "replay_start": "2026-10-14",
              "calendar": str(path), "panel": "unused", "fundamentals": "unused"}
    monkeypatch.setattr(runtime, "load_inputs", lambda _: inputs)
    monkeypatch.setattr(runtime, "load_market_data", lambda *a, **k:
                        SimpleNamespace(calendar=days[days <= pd.Timestamp("2026-10-15")]))
    monkeypatch.setattr(runtime.Fundamentals, "load", lambda _: None)
    monkeypatch.setattr(runtime, "_source_hash", lambda: "fixture-code")
    initialized = []
    def other_account(*args, **kwargs):
        initialized.append(args[1])
        raise ValueError("other account reached its independent gate")
    monkeypatch.setattr(runtime, "_initialize", other_account)
    monkeypatch.setattr(runtime, "_result", lambda *a, **k: pytest.fail("I7 must not create a false 10/15 close order"))
    root = tmp_path / "ledgers"
    reports = runtime.update(root, tmp_path, "unused",
        ("i7_turn_of_month", "cb_double_low"), bindings=sample_bindings("fixture-code"))
    assert reports["i7_turn_of_month"]["state"] == "pending"
    assert reports["i7_turn_of_month"]["calendar_context"]["calendar_sha256"] == file_hash(path)
    assert not (root / "i7_turn_of_month").exists()
    assert initialized == ["cb_double_low"]


def test_i7_complete_october_proves_actual_thirtieth_month_end(tmp_path):
    from ashare_lab.ideas_calendar import calendar_holdings
    path = october_calendar(tmp_path, "2026-11-04")
    context = i7_calendar_context(path, "2026-10-14", "2026-10-15")
    assert context["state"] == "ready"
    assert context["complete"] is True
    assert context["next_month_first_session"] == "2026-11-02"
    days = exchange_days(path, "SSE", "2026-10-15")
    holdings = calendar_holdings(days, "tom")
    assert not holdings.loc["2026-10-16"]
    assert holdings.loc["2026-10-30"]
    assert pd.Timestamp("2026-10-30") in period_ends(days, "M")
    assert pd.Timestamp("2026-10-16") not in period_ends(days, "M")


def test_i7_requires_closed_day_coverage_and_two_future_sessions(tmp_path):
    path = october_calendar(tmp_path, "2026-11-04")
    frame = pd.read_parquet(path)
    frame.loc[frame.cal_date.ne("20261017")].to_parquet(path)
    assert i7_calendar_context(path, "2026-10-14", "2026-10-15")["state"] == "pending"
    path = october_calendar(tmp_path, "2026-11-02")
    context = i7_calendar_context(path, "2026-10-14", "2026-10-30")
    assert context["next_month_first_session"] == "2026-11-02"
    assert context["state"] == "pending"
    assert "two real open sessions" in context["reason"]


def test_etf_zero_stamp_and_close_execution():
    dates = pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-14"])
    columns = ["510300.SH"]
    frame = lambda value: pd.DataFrame(value, index=dates, columns=columns)
    data = MarketData(frame(8.), frame(10.), frame(20.), frame(1.), frame(1.),
                      frame(1e6), frame(1e8), frame(False), frame(False),
                      pd.Series(pd.Timestamp("2010-01-01"), index=columns),
                      pd.Series(pd.NaT, index=columns), {}, pd.DataFrame(index=dates))
    targets = {dates[0]: pd.Series({columns[0]: 1.}), dates[1]: pd.Series({columns[0]: 0.})}
    costs = CostModel(commission=.0002, transfer=.00001, slippage=0)
    result = run_backtest(FixedTargets(targets), data, BacktestConfig(
        str(dates[0].date()), str(dates[-1].date()), 10000, costs,
        execution="close", stamp_exempt=tuple(columns), transfer_exempt=tuple(columns)))
    assert (result.trades.price == 10).all()
    assert np.allclose(result.trades.fee, result.trades.value * .0002)
    assert result.positions.iloc[-1].sum() == 0
    assert result.signals.index.equals(dates[:2])


def test_futures_integer_mtm_roll_both_legs_and_signed_ledger(tmp_path):
    dates = pd.to_datetime(["2026-10-09", "2026-10-12", "2026-10-13"])
    prices = pd.DataFrame({"CU1": [100., 100., 110.], "CU2": [120., 120., 120.]}, index=dates)
    settle = pd.DataFrame({"CU1": [100., 101., 111.], "CU2": [120., 120., 121.]}, index=dates)
    mapping = pd.DataFrame({"CU.SHF": ["CU1", "CU1", "CU2"]}, index=dates)
    multiplier = pd.Series({"CU1": 10., "CU2": 10.})
    targets = {dates[0]: pd.Series({"CU.SHF": -.5})}
    costs = CostModel(commission=.0002)
    result = run_futures_account(prices, settle, mapping, multiplier, targets,
                                 BacktestConfig("2026-10-09", "2026-10-13", 10000, costs))
    # Five short lots opened day two; cash settles the 1-point adverse move.
    assert result.positions.at[dates[1], "CU1"] == -5
    assert result.cash.loc[dates[1]] == pytest.approx(9949.)
    rolled = result.trades.loc[result.trades.date.eq(dates[2])]
    assert set(rolled.code) == {"CU1", "CU2"}
    assert np.allclose(rolled.fee, rolled.value * .0002)
    assert (result.positions.fillna(0) % 1 == 0).all().all()
    append_ledger(tmp_path, result)
    ledger = _read_frames(tmp_path)
    assert (ledger["positions"].shares < 0).any()
    before = file_hash(tmp_path / "nav.csv")
    assert append_ledger(tmp_path, result)["new_dates"] == []
    assert file_hash(tmp_path / "nav.csv") == before
    broken = settle.copy()
    broken.at[dates[2], "CU1"] = np.nan
    with pytest.raises(ValueError, match="missing actual"):
        run_futures_account(prices, broken, mapping, multiplier, targets,
                            BacktestConfig("2026-10-09", "2026-10-13", 10000, costs))


def test_only_timely_consecutive_daily_rows_can_be_forward_evidence():
    from datetime import datetime, timezone
    from ashare_lab.paper_runtime import observation_records

    now = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)
    days = pd.to_datetime(["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"])
    identity = {"created_at": "2026-10-14T12:00:00+00:00", "code_sha256": "frozen"}
    inputs = {"version": "actual-release", "identity_sha256": "actual-manifest"}
    previous = [{"date": "2026-10-15", "recorded_at": "2026-10-15T11:00:00+00:00"}]
    records = observation_records(identity, days[:3], days, previous, inputs, "daily", now)
    assert [r["kind"] for r in records] == ["replay", "replay", "forward_paper_observation"]
    assert observation_records(identity, days[2:3], days, [], inputs, "daily", now)[0]["kind"] == "replay"
    assert observation_records(identity, days[2:3], days, previous, inputs, "replay", now)[0]["kind"] == "replay"
    created_now = {**identity, "created_at": now.isoformat()}
    assert observation_records(created_now, days[2:3], days, previous, inputs, "daily", now)[0]["kind"] == "replay"


def test_original_source_ledger_bytes_and_opening_identity_are_preserved(tmp_path):
    from types import SimpleNamespace
    from ashare_lab.paper_runtime import _inception_gate, digest
    source = tmp_path / "source" / "lowvol"
    source.mkdir(parents=True)
    original = {
        "meta.json": b'{"created_at":"2026-10-14T12:56:07+00:00","inception":"2026-10-13","frozen":true}\n',
        "nav.csv": b"date,nav,cash,exposure\n2026-10-13,1000000.0,1000000.0,1.0\n",
        "positions.csv": b"date,code,shares\n",
        "trades.csv": b"date,code,side,shares,price,value,fee\n",
        "targets.csv": b"date,code,weight\n",
    }
    for name, content in original.items():
        (source / name).write_bytes(content)
    destination = tmp_path / "destination" / "lowvol"
    reference = {"inception": "2026-10-13", "source_report_match": True,
        "pending": {"lowvol": {"000001.SZ": 1.0}},
        "source": {"source_commit": "fixture-original-commit", "source_manifest_sha256": "fixture-manifest",
            "published": {"lowvol": {"000001.SZ": "100.00%"}},
            "files": {**{f"paper/lowvol/{name}": digest(content) for name, content in original.items()},
                      "paper/latest.md": "fixture-published-report"}}}
    with pytest.raises(LedgerMismatch, match="independently match"):
        _initialize(destination, "lowvol", source.parent, {"replay_start": "2026-10-14"},
                    "frozen", sample_bindings("frozen"))
    identity = _initialize(destination, "lowvol", source.parent, {"replay_start": "2026-10-14"},
                           "frozen", sample_bindings("frozen"), source_reference=reference)
    assert identity["source_created_at"] == "2026-10-14T12:56:07+00:00"
    for name, content in original.items():
        assert (destination / name).read_bytes() == content
    observations = [json.loads(line) for line in (destination / "observations.jsonl").read_text().splitlines()]
    assert observations[0]["historical_forward_evidence"] is False
    restored = [json.loads(line) for line in (destination / "signals.jsonl").read_text().splitlines()]
    assert restored == [{"date": "2026-10-13", "weights": {"000001.SZ": 1.0}}]
    result = SimpleNamespace(signals=pd.DataFrame({"000001.SZ": [1.0]}, index=pd.to_datetime(["2026-10-13"])))
    _inception_gate(destination, "lowvol", result, {"identity_sha256": "fixture-input"}, "frozen")
    proof = destination / "inception_reconciliation.jsonl"
    before = proof.read_bytes()
    _inception_gate(destination, "lowvol", result, {"identity_sha256": "fixture-input"}, "frozen")
    assert proof.read_bytes() == before
    assert json.loads(before)["matched"] is True
    result.signals.iloc[0, 0] = .5
    with pytest.raises(LedgerMismatch, match="refusing financial append"):
        _inception_gate(destination, "lowvol", result, {"identity_sha256": "fixture-input"}, "frozen")
    assert [json.loads(line)["matched"] for line in proof.read_text().splitlines()] == [True, False]
    _assert_seal(destination)
    for name, content in original.items():
        assert (destination / name).read_bytes() == (source / name).read_bytes() == content
    (destination / "nav.csv").write_bytes(original["nav.csv"] + b"tamper")
    with pytest.raises(LedgerMismatch, match="tamper"):
        _assert_seal(destination)


@pytest.mark.parametrize("known_dividend", [False, True])
def test_etf_preparation_reads_raw_fund_limits_and_preserves_units(tmp_path, known_dividend):
    from ashare_lab.paper_inputs import _etf_panel

    archive = tmp_path / "archive"
    release = archive / "releases" / "data-fixture"
    release.mkdir(parents=True)
    fetched = "2026-10-16T10:00:00Z"
    common = {"source_ts_code": ["510300.SH"], "trade_date": ["20261016"],
              "_fetched_at": [fetched]}
    frames = {
        "fund_daily": pd.DataFrame({**common, "open": [4.], "close": [4.1],
                                   "amount": [12.], "vol": [3.]}),
        "fund_adj": pd.DataFrame({**common, "adj_factor": [1.2]}),
        "etf_limit": pd.DataFrame({**common, "up_limit": [4.4], "down_limit": [3.6]}),
    }
    if known_dividend:
        frames["fund_div"] = pd.DataFrame({"source_ts_code": ["510300.SH"], "ex_date": ["20261016"]})
    datasets = []
    for api, frame in frames.items():
        path = archive / f"{api}.parquet"
        frame.to_parquet(path, index=False)
        datasets.append({"api_name": api, "path": path.name})
    manifest = release / "manifest.json"
    manifest.write_text(json.dumps({"datasets": datasets}))
    cache = tmp_path / "cache"
    cache.mkdir()
    out = tmp_path / "etf.parquet"
    metadata = _etf_panel(manifest, out, cache, pd.Timestamp("2026-10-16").date())
    row = pd.read_parquet(out).iloc[0]
    assert row.amount == 12000
    assert row.volume == 300
    assert row.up_limit == 4.4
    assert row.down_limit == 3.6
    assert row.adj == 1.2
    assert bool(row.cash_dividend_event) is known_dividend
    assert metadata["cash_dividend_source_available"] is known_dividend
    assert metadata["cash_dividend_history_verified"] is False


def test_cffex_data_cannot_create_a_flat_commodity_observation(tmp_path):
    from ashare_lab.paper_assets import futures_inputs
    pd.DataFrame({"ts_code": ["IF2612.CFX"], "fut_code": ["IF"], "normalized_multiplier": [300.],
                  "list_date": ["20260101"], "delist_date": ["20261231"],
                  "d_month": ["202612"]}).to_parquet(tmp_path / "basic.parquet")
    with pytest.raises(ValueError, match="CFFEX is not a substitute"):
        futures_inputs(tmp_path, pd.to_datetime(["2026-10-15", "2026-10-16"]),
                       "2026-10-16", "2026-10-14")


def test_futures_consumer_requires_normalized_units_only_in_actual_contract_closure(tmp_path):
    from ashare_lab.paper_assets import futures_inputs
    products = {"SHF": "CU AL ZN PB NI SN AU AG RB HC RU BU FU SP SS",
                "DCE": "A M Y P C CS JD L V PP J JM I EG EB PG",
                "ZCE": "SR CF TA MA FG RM OI ZC SA UR AP SF SM", "INE": "SC"}
    dates = pd.bdate_range("2025-08-01", periods=310)
    metadata, mappings = [], []
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    for exchange, names in products.items():
        for product in names.split():
            code = f"{product}2612.{exchange}"
            metadata.append({"ts_code": code, "fut_code": product, "multiplier": np.nan,
                "normalized_multiplier": 10., "list_date": "20250101",
                "delist_date": "20261231", "d_month": "202612"})
            prices = 100. + np.arange(len(dates)) * .1 + np.sin(np.arange(len(dates)))
            pd.DataFrame({"trade_date": dates.strftime("%Y%m%d"), "ts_code": code,
                          "close": prices, "settle": prices, "oi": 100.}).to_parquet(contracts / f"{code}.parquet")
            mappings.extend({"trade_date": str(t.date()), "ts_code": f"{product}.{exchange}",
                             "mapping_ts_code": "JD2601.DCE" if product == "JD" and i < 10 else code}
                            for i, t in enumerate(dates))
    # A genuinely historical mapping has unknown units outside the real warmup;
    # preserving its price history must not block the current executable account.
    metadata.append({"ts_code": "JD2601.DCE", "fut_code": "JD", "multiplier": np.nan,
        "normalized_multiplier": np.nan, "list_date": "20250101",
        "delist_date": "20260130", "d_month": "202601"})
    pd.DataFrame({"trade_date": dates[:10].strftime("%Y%m%d"), "ts_code": "JD2601.DCE",
                  "close": np.arange(10) + 100., "settle": np.arange(10) + 100.,
                  "oi": 100.}).to_parquet(contracts / "JD2601.DCE.parquet")
    basic = pd.DataFrame(metadata)
    basic.to_parquet(tmp_path / "basic.parquet")
    pd.DataFrame(mappings).to_parquet(tmp_path / "mapping.parquet")
    end, start = str(dates[-1].date()), str(dates[-3].date())
    _, _, mapping, multiplier, _ = futures_inputs(tmp_path, dates, end, start)
    assert len(mapping.columns) == 45
    assert multiplier["JD2612.DCE"] == 10.
    assert pd.isna(multiplier["JD2601.DCE"])
    basic.loc[basic.ts_code.eq("JD2612.DCE"), "normalized_multiplier"] = np.nan
    basic.to_parquet(tmp_path / "basic.parquet")
    with pytest.raises(ValueError, match="normalized futures multiplier.*JD2612.DCE"):
        futures_inputs(tmp_path, dates, end, start)


def test_inception_comparison_does_not_accept_rounded_weight_parity():
    from ashare_lab.paper_inception import compare_weights, published_pending, ORIGINAL
    report = "# 虚拟盘日报 · 2026-10-13\n" + "".join(
        f"## {name}\n### 下一交易日待执行目标\n"
        "| buy | 000001.SZ | 样本 | 0.00% | 2.00% | +2.00% |\n" for name in ORIGINAL)
    published = published_pending(report)
    comparison = compare_weights({"000001.SZ": .0200001}, {"000001.SZ": .0200002}, published["lowvol"])
    assert comparison["matched"] is False
    assert comparison["rows"][0]["source_matches_published"] is True
    assert comparison["rows"][0]["runtime_matches_source"] is False
    assert not compare_weights({"000001.SZ": .02}, {}, published["lowvol"])["matched"]
    assert not compare_weights({"000001.SZ": .02}, {"000001.SZ": .02, "600000.SH": .01}, published["lowvol"])["matched"]
    with pytest.raises(ValueError, match="Missing published"):
        published_pending("# 虚拟盘日报 · 2026-10-13\n")


@pytest.mark.parametrize("adjustments,events", [
    ([1., 1., 2.], [False, False, False]),
    ([1., 1., 1.], [False, False, True]),
    ([1., 1., np.nan], [False, False, False]),
])
def test_held_etf_adjustment_or_known_dividend_blocks_without_cash_model(adjustments, events):
    from types import SimpleNamespace
    from ashare_lab.paper_runtime import _etf_cash_guard
    dates = pd.to_datetime(["2026-10-14", "2026-10-15", "2026-10-16"])
    result = SimpleNamespace(positions=pd.DataFrame({"511010.SH": [0., 100., 100.]}, index=dates))
    frame = pd.DataFrame({"adj": adjustments, "cash_dividend_event": events}, index=dates)
    with pytest.raises(ValueError, match="cash-dividend accounting is not implemented"):
        _etf_cash_guard(result, SimpleNamespace(calendar=dates), {"511010.SH": frame})
    for name in ("i7_turn_of_month", "s1_invvol_etf"):
        assert frozen_specs()[name]["etf_cash_dividend_history_verified"] is False


def test_etf_events_before_actual_holding_do_not_invent_dividend_entitlement():
    from types import SimpleNamespace
    from ashare_lab.paper_runtime import _etf_cash_guard
    dates = pd.to_datetime(["2026-10-14", "2026-10-15", "2026-10-16"])
    result = SimpleNamespace(positions=pd.DataFrame({"511010.SH": [0., 100., 100.]}, index=dates))
    frame = pd.DataFrame({"adj": [1., 2., 2.], "cash_dividend_event": [False, True, False]}, index=dates)
    _etf_cash_guard(result, SimpleNamespace(calendar=dates), {"511010.SH": frame})


@pytest.mark.parametrize("engine", ["equity", "futures"])
@pytest.mark.parametrize("invalid_field", [None, "shares", "price", "value", "fee"])
def test_real_engine_cash_only_is_valid_but_nan_trade_never_appends(tmp_path, monkeypatch, engine, invalid_field):
    import ashare_lab.paper_runtime as runtime
    dates = pd.to_datetime(["2026-10-14", "2026-10-15"])
    frame = lambda value: pd.DataFrame(value, index=dates, columns=["510300.SH"])
    market = MarketData(frame(10.), frame(10.), frame(20.), frame(1.), frame(1.),
        frame(1e6), frame(1e8), frame(False), frame(False),
        pd.Series(pd.Timestamp("2010-01-01"), index=["510300.SH"]),
        pd.Series(pd.NaT, index=["510300.SH"]), {}, pd.DataFrame(index=dates))
    if engine == "equity":
        name = "i7_turn_of_month"
        targets = {dates[0]: pd.Series({"510300.SH": 1.})} if invalid_field else {}
        result = run_backtest(FixedTargets(targets), market,
            BacktestConfig("2026-10-14", "2026-10-15", 1e6,
                CostModel(commission=.00075, transfer=0, stamp_before=0, stamp_after=0, slippage=0),
                execution="close", stamp_exempt=("510300.SH",)))
    else:
        name = "cta_trend"
        prices = pd.DataFrame({"CU2612.SHF": [100., 101.]}, index=dates)
        mapping = pd.DataFrame({"CU.SHF": ["CU2612.SHF"] * 2}, index=dates)
        targets = {dates[0]: pd.Series({"CU.SHF": .5})} if invalid_field else {}
        result = run_futures_account(prices, prices, mapping, pd.Series({"CU2612.SHF": 10.}),
            targets, BacktestConfig("2026-10-14", "2026-10-15", 1e6,
                CostModel(commission=.0002, transfer=0, stamp_before=0, stamp_after=0, slippage=0, lot=1)))
    if invalid_field:
        assert len(result.trades) == 1
        result.trades.loc[0, invalid_field] = np.nan
    else:
        assert result.trades.empty
        assert result.trades[["shares", "price", "value", "fee"]].to_numpy().dtype == object
    calendar = october_calendar(tmp_path, "2026-11-04")
    manifest = tmp_path / "inputs.json"
    manifest.write_text(json.dumps({"fixture": "real-engine-financial-boundary"}))
    inputs = {"usable_date": "2026-10-15", "replay_start": "2026-10-14",
        "calendar": str(calendar), "panel": "unused", "fundamentals": "unused",
        "manifest_path": str(manifest), "identity_sha256": file_hash(manifest), "version": "fixture-engine"}
    monkeypatch.setattr(runtime, "load_inputs", lambda _: inputs)
    monkeypatch.setattr(runtime, "load_market_data", lambda *a, **k: market)
    monkeypatch.setattr(runtime.Fundamentals, "load", lambda _: None)
    monkeypatch.setattr(runtime, "_source_hash", lambda: "fixture-code")
    # Only input loading is isolated: the actual engine result crosses the real
    # pre-append financial gate and ledger writer, not a substitute empty schema.
    monkeypatch.setattr(runtime, "_result", lambda *a, **k: (result, None))
    root = tmp_path / "ledger"
    reports = runtime.update(root, tmp_path, manifest, (name,), bindings=sample_bindings("fixture-code"))
    if invalid_field:
        assert reports[name]["state"] == "blocked"
        assert "Invalid real ledger valuation" in reports[name]["error"]
        assert not (root / name / "nav.csv").exists()
    else:
        assert reports[name]["state"] == "reconciled"
        nav = pd.read_csv(root / name / "nav.csv")
        assert nav.date.tolist() == ["2026-10-14", "2026-10-15"]
        assert nav.nav.eq(1e6).all() and nav.cash.eq(1e6).all()
        assert pd.read_csv(root / name / "trades.csv").empty


def captured_paper_fixture(name):
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def frozen_descriptor_accounts(monkeypatch):
    from types import SimpleNamespace
    from ashare_lab import paper_accounts
    monkeypatch.setattr(paper_accounts, "compute_b3_factors", lambda *a, **k: {})
    monkeypatch.setattr(paper_accounts, "composite", lambda *a, **k: pd.DataFrame())
    data = SimpleNamespace(calendar=pd.to_datetime(["2026-10-13", "2026-10-14", "2026-10-15"]))
    return {name: (strategy, meta) for name, strategy, meta in paper_accounts.make_accounts(data, None)}


@pytest.mark.parametrize("name", ["b2_lowvol_vt", "b3_lqv_buf_vt"])
def test_original_vol_target_metadata_is_exact_and_bytes_never_rewritten(tmp_path, monkeypatch, name):
    from ashare_lab.paper import init_account
    strategy, meta = frozen_descriptor_accounts(monkeypatch)[name]
    original = captured_paper_fixture("original_vol_target_meta.json")[name]
    content = original["content"].encode()
    path = tmp_path / "meta.json"
    path.write_bytes(content)
    assert file_hash(path) == original["sha256"]
    assert (strategy.cut_delay, strategy.cut_scale, strategy.downside) == (0, 1.0, False)
    assert set(meta["strategy"]["params"]) == {"target_vol", "window", "step", "max_exposure", "base"}
    saved = json.loads(content)
    saved.pop("created_at")
    assert meta == saved
    init_account(tmp_path, meta)
    assert path.read_bytes() == content
    for field, changed in (("target_vol", .17), ("window", 61), ("step", .2), ("max_exposure", .9)):
        drift = json.loads(json.dumps(meta))
        drift["strategy"]["params"][field] = changed
        with pytest.raises(LedgerMismatch, match="meta.strategy"):
            init_account(tmp_path, drift)
        assert path.read_bytes() == content


@pytest.mark.parametrize("field,value", [("cut_delay", 1), ("cut_scale", .5), ("downside", True)])
def test_non_neutral_vol_target_modes_cannot_claim_original_descriptor(monkeypatch, field, value):
    from ashare_lab import paper_accounts
    original = paper_accounts.VolTarget
    class NonNeutral(original):
        def __post_init__(self):
            super().__post_init__()
            setattr(self, field, value)
    monkeypatch.setattr(paper_accounts, "VolTarget", NonNeutral)
    with pytest.raises(ValueError, match="requires only neutral"):
        frozen_descriptor_accounts(monkeypatch)


def test_unknown_vol_target_fields_are_not_silently_discarded(monkeypatch):
    from dataclasses import dataclass
    from ashare_lab import paper_accounts
    @dataclass
    class AdditionalMode(paper_accounts.VolTarget):
        unknown_mode: int = 0
    monkeypatch.setattr(paper_accounts, "VolTarget", AdditionalMode)
    with pytest.raises(ValueError, match="requires only neutral"):
        frozen_descriptor_accounts(monkeypatch)


def real_i7_inputs(tmp_path):
    captured = captured_paper_fixture("i7_real_510300_2026.json")
    quotes = pd.DataFrame(captured["quotes"])
    quotes["date"] = pd.to_datetime(quotes.date)
    quotes["code"] = captured["provenance"]["instrument"]
    path = tmp_path / "real-etf.parquet"
    quotes.to_parquet(path)
    dates = pd.DatetimeIndex(quotes.date)
    empty = pd.DataFrame(index=dates, dtype=float)
    market = MarketData(*(empty.copy() for _ in range(9)),
        pd.Series(dtype="datetime64[ns]"), pd.Series(dtype="datetime64[ns]"),
        {}, pd.DataFrame(index=dates))
    return quotes.set_index("date"), pd.to_datetime(captured["sessions"]), market, {
        "usable_date": "2026-10-15", "asset_inputs": {"i7_turn_of_month": str(path)}}


@pytest.mark.parametrize("start", ["2026-10-14", "2026-09-28"])
def test_i7_real_prices_sparse_cash_and_month_boundary_nav(tmp_path, start):
    from ashare_lab.paper_runtime import _result
    from ashare_lab.ideas_calendar import calendar_holdings, calendar_nav
    quotes, days, market, inputs = real_i7_inputs(tmp_path)
    result, _ = _result("i7_turn_of_month", {"replay_start": start}, inputs, days, market, None)
    close = (quotes.close * quotes.adj).reindex(result.nav.index)
    reference = calendar_nav((quotes.open * quotes.adj).reindex(result.nav.index),
                             close, calendar_holdings(days, "tom"))
    if start == "2026-10-14":
        assert quotes.loc["2026-10-14", "close"] == 4.294
        assert quotes.loc["2026-10-15", "close"] == 4.242
        assert "510300.SH" not in result.positions  # Actual engine's sparse cash-only schema.
        assert result.trades.empty
        assert result.nav.eq(1e6).all() and result.cash.eq(1e6).all()
        assert reference.eq(1.).all()
    else:
        cost, cash, lot = .00075, 1e6, 100
        buy_date, sell_date = pd.Timestamp("2026-09-29"), pd.Timestamp("2026-10-12")
        buy, sell = quotes.at[buy_date, "close"], quotes.at[sell_date, "close"]
        quantity = int(np.floor(cash / (buy * (1 + cost)) / lot)) * lot
        after_buy = cash - quantity * buy - quantity * buy * cost
        after_sell = after_buy + quantity * sell - quantity * sell * cost
        expected = [cash if t < buy_date else
                    after_buy + quantity * quotes.at[t, "close"] if t < sell_date else
                    after_sell for t in result.nav.index]
        np.testing.assert_allclose(result.nav.to_numpy(), expected, rtol=1e-12, atol=1e-12)
        assert result.trades.date.tolist() == [buy_date, sell_date]
        assert result.trades.side.tolist() == ["buy", "sell"]
        assert result.trades.shares.eq(quantity).all()
        np.testing.assert_allclose(result.trades.fee, result.trades.value * cost, rtol=1e-12, atol=1e-12)
        assert reference.iloc[-1] == pytest.approx((sell / buy) * (1 - cost) ** 2, rel=1e-12, abs=1e-12)
        assert result.nav.iloc[-1] != cash and reference.iloc[-1] != 1


def test_i7_cash_only_still_requires_real_510300_cutoff_price(tmp_path):
    from ashare_lab.paper_runtime import _result
    quotes, days, market, inputs = real_i7_inputs(tmp_path)
    quotes.loc["2026-10-15", "close"] = np.nan
    quotes.reset_index().to_parquet(inputs["asset_inputs"]["i7_turn_of_month"])
    with pytest.raises(ValueError, match="no actual quote"):
        _result("i7_turn_of_month", {"replay_start": "2026-10-14"}, inputs, days, market, None)
