#!/usr/bin/env python3
"""Independently reconcile the saved CSVs and observable QuantBot tool evidence."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import agent_research_tool as tool
from run_quantbot_session import summarize_events


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def reconcile(directory, name, capital, reported):
    equity = read_csv(directory / f"{name}-equity.csv")
    fills = read_csv(directory / f"{name}-trades.csv")
    holdings = read_csv(directory / f"{name}-positions.csv")
    values = {}
    for h in holdings:
        values[h["date"]] = values.get(h["date"], 0) + float(h["adjusted_quantity"]) * float(h["adjusted_price"])
    cash, fees, max_cash_error = capital, 0.0, 0.0
    for fill in fills:
        assert fill["action"] in ("buy", "sell")
        cost = float(fill["cost"])
        cash += (1 if fill["action"] == "sell" else -1) * float(fill["amount"]) - cost
        fees += cost
        max_cash_error = max(max_cash_error, abs(cash - float(fill["cash_after"])))
        assert cash >= -.01
    peak, previous, drawdown, max_asset_error, cost_from_equity = capital, capital, 0.0, 0.0, 0.0
    for row in equity:
        nav = float(row["account"])
        assert math.isfinite(nav) and nav > 0
        assert abs(nav / previous - 1 - (float(row["return"]) - float(row["cost"]))) < 1e-8
        cost_from_equity += previous * float(row["cost"])
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1)
        max_asset_error = max(max_asset_error, abs(nav - float(row["cash"]) - values.get(row["date"], 0)))
        previous = nav
    net = previous / capital - 1
    assert max_cash_error < .01 and max_asset_error < .01
    assert abs(cash - float(equity[-1]["cash"])) < .01
    assert abs(fees - cost_from_equity) < .01
    assert abs(net - reported["total_return"]) < 1e-10
    assert abs(drawdown - reported["max_drawdown"]) < 1e-10
    assert abs(fees - reported["transaction_cost"]) < .01
    assert len(fills) == reported["trades"]
    return {"net_return": net, "max_drawdown": drawdown, "fees": fees,
            "fills": len(fills), "cash_error": max_cash_error, "asset_error": max_asset_error}


def verify(session):
    contract, source = tool.checked_contract(session)
    tool.frozen.verify(source)
    decision = tool.frozen.read(session / "decision.json")
    assert decision["research_status"] == "needs_independent_validation"
    assert decision["automatic_trading_authorized"] is False
    assert (session / "REPORT.md").read_text().strip(), "Agent report is missing"
    correction = session / "scope-correction.json"
    if correction.exists():
        scope = tool.frozen.read(correction)
        assert {p.parent.name for p in tool.experiments(session)} == set(scope["existing_experiments"]), \
            "New experiments were submitted after the user requested closeout"
    checked = []
    for path in tool.experiments(session):
        result = tool.refresh(session, path.parent.name)
        assert result["status"] == "completed"
        proposal = result["proposal"]
        config = tool.frozen.read(path.parent / "config.json")
        if result["kind"] == "stress":
            origin = tool.experiment_dir(session, proposal["origin"])
            expected = tool.frozen.read(origin / "config.json")
            for key in ("commission", "min_commission", "stamp_duty", "transfer_fee",
                        "min_transfer_fee", "impact_cost_coefficient"):
                expected["exchange"][key] *= 2
            for name in ("model.lgb", "signals.parquet", "daily-replay.parquet", "universe.csv"):
                assert tool.frozen.sha256(path.parent / name) == tool.frozen.sha256(origin / name), name
        else:
            expected = tool.candidate_config(contract["base_config"], proposal.get("changes", {}))
            if result["kind"] == "candidate":
                for name in ("universe.csv", "single_factor-equity.csv", "equal_weight-equity.csv"):
                    assert tool.frozen.sha256(path.parent / name) == tool.frozen.sha256(session / "experiments/E00" / name), name
        assert config == expected
        rows = {name: reconcile(path.parent, name, config["portfolio"]["initial_capital"], metrics)
                for name, metrics in result["summary"]["comparison"].items()}
        checked.append({"id": result["id"], "portfolios": rows})
    transcripts = {p.parent.name: summarize_events(p) for p in session.glob("agent-run-*/events.sse")}
    assert any(t["tool_call_count"] > 0 and t["agent_response_status"] == "completed" for t in transcripts.values())
    result = {"verification_passed": True, "experiments": checked, "agent_transcripts": transcripts,
              "research_status": "needs_independent_validation",
              "note": "Checks verify computation and recorded execution, not historical PIT data quality or investment value"}
    tool.frozen.write(session / "verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.session.resolve()), ensure_ascii=False, indent=2))
