"""Finite, synthetic preflight for the R01 one-trading-step submission study.

This checks target sequences, not returns, fills, or all possible strategy inputs.
It never constructs a market package or calls the replay/accounting engine.
"""

from __future__ import annotations

import hashlib
import json
import math

from backend.services.simulation.replay.strategy_program import evaluate_program


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _same_targets(actual, expected):
    if actual is None or expected is None:
        return actual is expected
    return actual.keys() == expected.keys() and all(
        math.isclose(actual[s], expected[s], rel_tol=0, abs_tol=1e-12) for s in expected
    )


def _contexts(parameters, entry_on):
    """An explicitly artificial trading sequence, including closure gaps."""
    symbols = parameters["symbols"]
    gate = parameters["gate_symbol"]
    # date, month end, latest monthly value, latest daily value
    rows = [
        (
            "2019-12-31" if entry_on else "2020-01-30",
            entry_on,
            120 if entry_on else 90,
            100,
        ),
        ("2020-01-31", True, 90, 90),
        ("2020-02-03", False, 90, 120),
        ("2020-02-04", False, 90, 120),
        ("2020-02-10", False, 90, 80),
        ("2020-02-28", True, 120 if entry_on else 90, 100),
        ("2020-03-02", False, 100, 80),
        ("2020-03-31", True, 100, 100),  # equality retains the previous gate
        ("2020-04-01", False, 100, 80),
        ("2020-04-30", True, 90, 90),  # pending target must not be flushed
    ]
    for i, (day, month_end, monthly_last, daily_last) in enumerate(rows):
        history = {s: [100.0] * 61 for s in symbols}
        monthly = {s: [100.0] * 10 for s in symbols}
        history[gate][-1] = monthly_last if month_end else daily_last
        monthly[gate][-1] = monthly_last
        yield {
            "date": day,
            "month": int(day[5:7]),
            "is_entry": i == 0,
            "is_month_end": month_end,
            "symbols": sorted(symbols),
            "parameters": parameters,
            "history": history,
            "monthly_prices": monthly,
            "snapshot": {}
            if i == 0
            else {
                "nav_exact": 30000.0 + i,
                "cash": 30000.0,
                "positions": {},
                "risk_status": "active",
            },
        }


def check_delayed_targets(
    candidate_code, candidate_parameters, baseline_code, baseline_parameters
):
    """Reject parameter drift or wrong one-step targets; return JSON evidence.

    The caller must bind the baseline to the authorized reference revision and
    invoke this before submitting a new public calculation. Additional candidate
    parameters are reported, but cannot replace any frozen baseline parameter.
    """
    try:
        baseline_parameters = json.loads(_json(baseline_parameters))
        candidate_parameters = json.loads(_json(candidate_parameters))
        if not isinstance(baseline_parameters, dict) or not isinstance(
            candidate_parameters, dict
        ):
            raise ValueError("parameters_must_be_objects")
        drift = [
            k
            for k, v in baseline_parameters.items()
            if k not in candidate_parameters
            or _json(candidate_parameters[k]) != _json(v)
        ]
        if drift:
            raise ValueError("parameter_drift:" + ",".join(sorted(drift)))
        symbols = baseline_parameters.get("symbols")
        if (
            not isinstance(symbols, list)
            or not symbols
            or not all(isinstance(s, str) for s in symbols)
            or len(symbols) != len(set(symbols))
            or baseline_parameters.get("gate_symbol") not in symbols
            or baseline_parameters.get("lookback") != 61
            or baseline_parameters.get("monthly_lookback") != 10
            or type(baseline_parameters.get("daily_reentry")) is not bool
            or baseline_parameters.get("signal_on_month_end") is not False
        ):
            raise ValueError("unsupported_baseline_contract")
        cases = []
        for entry_on in (False, True):
            base_state, candidate_state, pending = {}, {}, None
            inputs, trace = [], []
            empty = nonempty = 0
            for i, ctx in enumerate(_contexts(baseline_parameters, entry_on)):
                inputs.append(ctx)
                baseline = evaluate_program(baseline_code, dict(ctx, state=base_state))
                candidate = evaluate_program(
                    candidate_code,
                    dict(ctx, parameters=candidate_parameters, state=candidate_state),
                )
                expected = baseline["targets"] if ctx["is_entry"] else pending
                if not _same_targets(candidate["targets"], expected):
                    raise ValueError(
                        f"target_sequence_mismatch:entry_on={entry_on}:step={i}:date={ctx['date']}"
                    )
                pending = None if ctx["is_entry"] else baseline["targets"]
                base_state = baseline.get("state", base_state)
                candidate_state = candidate.get("state", candidate_state)
                empty += not ctx["is_entry"] and baseline["targets"] is None
                nonempty += not ctx["is_entry"] and baseline["targets"] is not None
                trace.append(
                    {
                        "date": ctx["date"],
                        "is_entry": ctx["is_entry"],
                        "baseline_reason": baseline["reason"],
                        "baseline_targets": baseline["targets"],
                        "checked_delayed_targets": candidate["targets"],
                    }
                )
            if not empty or not nonempty or pending is None:
                raise ValueError("synthetic_baseline_coverage_insufficient")
            cases.append(
                {
                    "entry_on": entry_on,
                    "steps": len(trace),
                    "trace": trace,
                    "terminal_expected_pending_target": pending,
                    "input_sha256": hashlib.sha256(_json(inputs).encode()).hexdigest(),
                }
            )
        return {
            "ok": True,
            "check_version": "one-trading-step-synthetic-v1",
            "candidate_code_sha256": hashlib.sha256(
                candidate_code.encode()
            ).hexdigest(),
            "baseline_code_sha256": hashlib.sha256(baseline_code.encode()).hexdigest(),
            "candidate_parameters_sha256": hashlib.sha256(
                _json(candidate_parameters).encode()
            ).hexdigest(),
            "baseline_parameters_sha256": hashlib.sha256(
                _json(baseline_parameters).encode()
            ).hexdigest(),
            "additional_candidate_parameters": sorted(
                set(candidate_parameters) - set(baseline_parameters)
            ),
            "cases": cases,
            "internal_state_equivalence": "not_checked_no_required_state_schema",
            "limitations": [
                "Only the listed finite synthetic target trajectories were checked; not universal equivalence.",
                "Internal state and stored terminal queue are not proven without an observable state schema.",
                "No real calendar, prices, fills, performance, or historical decision-path acceptance.",
                "Caller must validate bound identities and later compare real saved decisions, including pending targets.",
            ],
        }
    except Exception as exc:
        raise ValueError(f"delayed_target_check:{exc}") from exc
