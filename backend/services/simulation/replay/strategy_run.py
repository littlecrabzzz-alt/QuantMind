"""Public R01 historical execution adapter, also callable by bounded workers.

Consumes a published strategy revision, never a mutable host script. Exports
the existing ledger view/evidence plus the existing backtest-center contract.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from datetime import date

from backend.services.simulation.replay.r01_ledger import R01Ledger, R01LedgerConfig
from backend.services.simulation.replay.strategy_program import decision_context, evaluate_program, execution_digest
from backend.services.simulation.virtual_run.recovery import reconcile


def ledger_config(revision: dict, *, run_key: str, read_through: date | None,
                  virtual: bool = False) -> R01LedgerConfig:
    cfg = dict(revision["execution"])
    cfg["sublot_rule_effective"] = date.fromisoformat(cfg["sublot_rule_effective"])
    return R01LedgerConfig(
        group=revision["group"], strategy_id=f"s{revision['strategy_id']}-{run_key}",
        strategy_version=revision["version"], execution_attempt_id=1,
        run_kind="virtual" if virtual else "research",
        read_through_bound=read_through, **cfg,
    )


def compute_run(revision: dict, request: dict, package) -> dict:
    if revision["engine_sha256"] != execution_digest():
        raise ValueError("execution_engine_changed: publish a new reviewed version")
    if hashlib.sha256(revision["code"].encode()).hexdigest() != revision["code_sha256"]:
        raise ValueError("published_code_hash_mismatch")
    start, end = date.fromisoformat(request["start_date"]), date.fromisoformat(request["end_date"])
    bound = date.fromisoformat(revision["data_binding"]["development_end"])
    if end > bound or start > end:
        raise ValueError("holdout_access_denied: development runs must end before the frozen holdout")
    if package.read_through != end:
        raise ValueError("input_read_bound_mismatch")
    if package.manifest_sha256 != revision["data_binding"]["manifest_sha256"]:
        raise ValueError("input_manifest_mismatch")
    if not package.is_fixture:
        from backend.services.simulation.replay.etf_input_package import verify_package_files
        verify_package_files(package.root, revision["data_binding"]["package_sums_sha256"])
    days = [d for d in package.trade_dates() if start <= d <= end]
    if not days or package.prev_trade_date(days[0]) is None:
        raise ValueError("execution_window_empty_or_missing_previous_signal_day")
    cfg = ledger_config(revision, run_key=request["backtest_id"], read_through=end)
    ledger = R01Ledger(package, cfg)
    decisions = []
    strategy_state = {}
    for d in days:
        signal_date = package.prev_trade_date(d)
        context = decision_context(
            package, revision["parameters"], signal_date,
            is_entry=not ledger.equity,
            snapshot=ledger.equity[-1] if ledger.equity else None,
            next_trade_date=d,
        )
        context["state"] = strategy_state
        decision = evaluate_program(revision["code"], context)
        strategy_state = decision.get("state", strategy_state)
        ledger.run_day(d, decision["targets"], signal_date=signal_date)
        decisions.append({"decision_date": signal_date.isoformat(),
                          "execution_date": d.isoformat(), **decision})
    check = reconcile(ledger)
    if not check["ok"]:
        raise ValueError("independent_ledger_reconciliation_failed")
    result = backtest_result(ledger, revision, request)
    result["ledger_view"] = ledger.export_view()
    result["ledger_evidence"] = ledger.export_evidence()
    result["strategy_decisions"] = decisions
    result["advanced_stats"] = {
        "reconciliation": {k: v for k, v in check.items() if k != "rows"},
        "actual_max_input_date": package.actual_max_input_date.isoformat(),
        "read_through": end.isoformat(), "engine": "r01_ledger",
        "validation_status": "development_only",
    }
    return result


def backtest_result(ledger, revision: dict, request: dict) -> dict:
    initial = ledger.config.initial_cash
    high = previous = initial
    curve, drawdowns, returns = [], [], []
    for snap in ledger.equity:
        nav = float(snap["nav_exact"])
        high = max(high, nav)
        dd = nav / high - 1
        curve.append({"date": snap["trade_date"], "value": nav})
        drawdowns.append({"date": snap["trade_date"], "value": dd})
        returns.append(nav / previous - 1)
        previous = nav
    total = previous / initial - 1
    years = max(1, (date.fromisoformat(curve[-1]["date"]) - date.fromisoformat(curve[0]["date"])).days + 1) / 365.25
    sd = statistics.stdev(returns) if len(returns) > 1 else 0
    trades = [{**fill.to_dict(), "date": fill.trade_date,
               "type": fill.side.upper(), "amount": fill.quantity * fill.price,
               "fee": fill.total_fee, "order_id": order.client_order_id}
              for order in ledger.orders.values() for fill in order.fills]
    config = {
        "executor_kind": "r01_ledger", "strategy_id": revision["strategy_id"],
        "strategy_revision": revision["revision_id"], "strategy_version": revision["version"],
        "strategy_name": revision["name"], "research_title": revision["name"],
        "research_id": revision["research_case_id"],
        "research_case_id": revision["research_case_id"],
        "initial_cash": initial, "initial_capital": initial,
        "start_date": request["start_date"], "end_date": request["end_date"],
        "data_binding": revision["data_binding"], "code_sha256": revision["code_sha256"],
        "execution": revision["execution"], "parameters": revision["parameters"],
        "ledger_run_id": ledger.ledger_run_id,
        "validation_status": "development_only", "rerun_of": request.get("rerun_of"),
        "metric_convention": "net return from initial cash; drawdown from initial/high-water equity; Sharpe rf=0,252 sessions",
    }
    return {
        "backtest_id": request["backtest_id"], "status": "completed", "config": config,
        "user_id": revision["user_id"], "tenant_id": revision["tenant_id"],
        "total_return": total, "annual_return": (1 + total) ** (1 / years) - 1,
        "max_drawdown": abs(min(p["value"] for p in drawdowns)),
        "sharpe_ratio": statistics.mean(returns) / sd * math.sqrt(252) if sd > 0 else None,
        "volatility": sd * math.sqrt(252) if sd > 0 else None,
        "benchmark_return": None, "alpha": None, "win_rate": None, "profit_factor": None,
        "long_short_is_theoretical": False, "signal_lag_days": 1, "deal_price": "open",
        "total_trades": len(trades), "equity_curve": curve, "drawdown_curve": drawdowns,
        "trades": trades, "positions": list(ledger.equity[-1]["positions"].values()),
    }


def main():
    # The caller supplies server-selected paths; none is accepted from a strategy.
    # Keep the computation process separate from API credentials/DB connections.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (600, 610))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    payload = json.load(sys.stdin)
    from backend.services.simulation.replay.etf_input_package import load_etf_input_package
    package = load_etf_input_package(
        payload["package_root"],
        expect_manifest_sha256=payload["revision"]["data_binding"]["manifest_sha256"],
        read_through=date.fromisoformat(payload["request"]["end_date"]),
    )
    result = compute_run(payload["revision"], payload["request"], package)
    json.dump(result, sys.stdout, ensure_ascii=False, allow_nan=False, default=str)


if __name__ == "__main__":
    main()
