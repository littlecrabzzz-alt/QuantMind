"""Contract tests for the published-program historical/paper boundary."""
import hashlib
from datetime import date

import pytest

from backend.services.simulation.replay.etf_input_package import build_fixture_package, load_etf_input_package
from backend.services.simulation.replay.strategy_program import FIXED_ALLOCATION_SOURCE, evaluate_program, execution_digest
from backend.services.simulation.replay.strategy_program import DYNAMIC_ALLOCATION_SOURCE
from backend.services.simulation.replay.strategy_run import compute_run
from backend.services.tests.test_r01_virtual_run_pipeline import Harness, make_config


def revision(pkg):
    return {"group": "A", "strategy_id": "61", "version": 1, "revision_id": "r"*64,
        "name": "test", "user_id": "10000001", "tenant_id": "default", "research_case_id": "c"*32,
        "code": FIXED_ALLOCATION_SOURCE, "code_sha256": hashlib.sha256(FIXED_ALLOCATION_SOURCE.encode()).hexdigest(),
        "engine_sha256": execution_digest(),
        "parameters": {"symbols": ["510300.SH", "518880.SH"],
            "target_weights": {"510300.SH": .6, "518880.SH": .4}, "frequency": "monthly"},
        "execution": {"initial_cash": 30000, "commission_rate": .0003, "commission_min": .1,
            "slippage_bps": 0, "loss_line_amount": 9000, "drawdown_pct": .3,
            "price_mode": "open", "stale_mark_limit": 5, "sublot_rule_effective": "2014-08-01"},
        "data_binding": {"manifest_sha256": pkg.manifest_sha256, "development_end": "2025-10-01"}}


def test_same_published_program_historical_paper_restart(tmp_path):
    pkg = build_fixture_package(tmp_path / "pkg")
    r = revision(pkg)
    end = date(2025, 10, 1)
    bounded = load_etf_input_package(pkg.root, read_through=end)
    bt = compute_run(r, {"start_date": "2025-09-11", "end_date": str(end), "backtest_id": "test"}, bounded)
    config = make_config(commission_min=.1, sublot_rule_effective="2014-08-01",
        program={k: r[k] for k in ("revision_id", "code", "code_sha256", "parameters", "engine_sha256")},
        execution_mode="post_close_next_open_accounting", decision_cutoff="16:15", execution_time="15:45")
    h = Harness(pkg, config)
    days = [d for d in pkg.trade_dates() if date(2025,9,10) <= d < end]
    for d in days:
        assert h.decide(d, "16:15").outcome == "pending_execute"
        assert h.execute(d, "09:31").outcome == "pending_execute"
        assert h.execute(d, "15:45").outcome == "completed"
        assert h.execute(d, "15:45").outcome == "completed"  # replay is idempotent
    checkpoint = h.ledger_state()  # each h.pipeline() above is a new instance
    assert len(checkpoint["equity"]) == len(bt["equity_curve"])
    assert [s["nav_exact"] for s in checkpoint["equity"]] == [p["value"] for p in bt["equity_curve"]]
    assert [d["targets"] for d in bt["strategy_decisions"]] == [h.store.get_stage(config.ledger_run_id, str(d), "signal")["targets"] for d in days]


def test_no_future_development_and_no_engine_drift(tmp_path):
    pkg = build_fixture_package(tmp_path / "pkg")
    r = revision(pkg)
    with pytest.raises(ValueError, match="holdout_access_denied"):
        compute_run(r, {"start_date":"2025-09-11", "end_date":"2025-10-02"}, pkg)
    r["engine_sha256"] = "wrong"
    with pytest.raises(ValueError, match="execution_engine_changed"):
        compute_run(r, {}, pkg)


@pytest.mark.parametrize("source", [
    'import os\ndef on_signal(ctx): return {}',
    'def on_signal(ctx): return {"targets": {"510300.SH": 1.1}}',
    'def on_signal(ctx): return {"targets": {"510300.SH": float("nan")}}',
    'def on_signal(ctx): return {"targets": {"BAD": .2}}',
])
def test_program_cannot_import_or_emit_invalid_weights(source):
    with pytest.raises(ValueError):
        evaluate_program(source, {"symbols": ["510300.SH"]})


def test_dynamic_signal_ties_negative_momentum_and_volatility_cap():
    symbols = ["510300.SH", "511010.SH", "518880.SH"]
    ctx = {"is_month_end": True, "symbols": symbols, "state": {"gates": {"510300.SH": 1}},
        "parameters": {"rule": "sma", "target_weights": dict(zip(symbols, [.4,.5,.1]))},
        "monthly_prices": {symbols[0]: [100, 100], symbols[1]: [100, 90], symbols[2]: [100, 110]}}
    out = evaluate_program(DYNAMIC_ALLOCATION_SOURCE, ctx)
    assert out["targets"] == {symbols[0]: .4, symbols[1]: 0., symbols[2]: .1}
    assert out["state"]["gates"] == {symbols[0]: 1, symbols[1]: 0, symbols[2]: 1}
    ctx["parameters"] = {"rule": "momentum", "top_n": 2}
    ctx["monthly_prices"] = {s: [100, 90] for s in symbols}
    out = evaluate_program(DYNAMIC_ALLOCATION_SOURCE, ctx)
    assert out["targets"] == {symbols[0]: .5, symbols[1]: .5, symbols[2]: 0.}
    ctx["parameters"] = {"rule": "vol_target", "target_weights": dict(zip(symbols, [.4,.5,.1])), "annualization": 252, "volatility_target": .1}
    ctx["history"] = {s: [100.,100.,100.] for s in symbols}
    out = evaluate_program(DYNAMIC_ALLOCATION_SOURCE, ctx)
    assert out["targets"] == ctx["parameters"]["target_weights"]


def test_paper_decision_must_precede_open_even_with_late_accounting(tmp_path):
    pkg = build_fixture_package(tmp_path / "pkg")
    r = revision(pkg)
    config = make_config(program={k:r[k] for k in ("code","code_sha256","engine_sha256","parameters","revision_id")},
        execution_mode="post_close_next_open_accounting", decision_cutoff="16:15",
        execution_time="15:45", decision_deadline_time="09:25", window_timeout_minutes=1050)
    h = Harness(pkg, config)
    d = date(2025,9,10)
    h.clock.set_shanghai(date(2025,9,11), "09:26")
    assert h.pipeline().run_day(d).outcome == "missed_decision_window"
    assert h.store.get_stage(config.ledger_run_id, str(d), "signal") is None


def test_daily_calendar_extends_beyond_earliest_package(tmp_path):
    import pandas as pd
    from backend.services.simulation.virtual_run.gating import DailyIncrementProvider
    roots = []
    for i, rows in enumerate([
        [{"cal_date":"20250910", "is_open":1}],
        [{"cal_date":"20250910", "is_open":1}, {"cal_date":"20250911", "is_open":1}],
    ]):
        path = tmp_path / str(i); path.mkdir()
        pd.DataFrame(rows).to_parquet(path / "calendar.parquet")
        roots.append((str(i), {"absolute_path":str(path)}, {}))
    provider = object.__new__(DailyIncrementProvider)
    import json
    provider._json = json
    provider._registry_path = tmp_path / "missing-registry.json"
    provider._daily_entries_sorted = lambda: roots
    assert provider.next_open_trade_date(date(2025,9,10)) == date(2025,9,11)


def test_published_pg_carrier_recovers_complete_frozen_config():
    from types import SimpleNamespace
    from backend.services.engine.tasks.r01_virtual_run_scheduler import virtual_run_config_from_pg_row
    cfg = make_config(program={"code":FIXED_ALLOCATION_SOURCE}, execution_mode="post_close_next_open_accounting")
    row = SimpleNamespace(execution_window={"config": cfg.to_dict()}, ledger_run_id=cfg.ledger_run_id,
        strategy_id=cfg.strategy_id, strategy_version=cfg.strategy_version, group=cfg.group, initial_cash=cfg.initial_cash)
    assert virtual_run_config_from_pg_row(row).to_dict() == cfg.to_dict()
    row.strategy_version += 1
    with pytest.raises(ValueError, match="identity mismatch"):
        virtual_run_config_from_pg_row(row)


def test_observed_calendar_extension_is_hash_bound(tmp_path):
    import json
    from backend.services.simulation.virtual_run.gating import DailyIncrementProvider
    raw = json.dumps({'data': {'fields':['exchange','cal_date','is_open'],
        'items':[['SSE','20250911',1]]}}).encode()
    path = tmp_path / 'calendar.json'; path.write_bytes(raw)
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'calendar_snapshot': {'path':str(path),
        'sha256':hashlib.sha256(raw).hexdigest(), 'obtained_at':'2025-09-10T00:00:00Z',
        'source':'tushare:trade_cal'}}))
    def provider():
        p = object.__new__(DailyIncrementProvider); p._json=json; p._registry_path=registry
        p._daily_entries_sorted=lambda: []
        return p
    p=provider()
    assert p.next_open_trade_date(date(2025,9,10)) == date(2025,9,11)
    assert p.calendar_binding['sha256'] == hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError, match='checksum_mismatch'):
        provider().next_open_trade_date(date(2025,9,10))


def test_overnight_accounting_wait_is_retryable_before_next_open(tmp_path):
    pkg=build_fixture_package(tmp_path/'pkg'); r=revision(pkg)
    cfg=make_config(program={k:r[k] for k in ('code','code_sha256','engine_sha256','parameters','revision_id')},
        commission_min=.1,sublot_rule_effective='2014-08-01',execution_mode='post_close_next_open_accounting',
        decision_cutoff='16:15',execution_time='15:45',decision_deadline_time='09:25',window_timeout_minutes=1050)
    h=Harness(pkg,cfg)
    first,second=date(2025,9,10),date(2025,9,11)
    assert h.decide(first,'16:15').outcome=='pending_execute'
    assert h.decide(second,'16:15').outcome=='data_blocked'
    assert h.store.get_day(cfg.ledger_run_id,str(second))['outcome']=='data_blocked'
    h.clock.set_shanghai(date(2025,9,12),'00:20')
    assert h.pipeline().run_day(first).outcome=='completed'
    assert h.pipeline().run_day(second).outcome=='pending_execute'
    assert h.execute(second,'15:45').outcome=='completed'
    assert len(h.ledger_state()['equity'])==2

