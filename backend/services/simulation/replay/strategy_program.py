"""One stateless strategy program for R01 historical and continuous runs.

Only causal, plain-data context is exposed. Matching, fees, company actions,
risk and accounting remain in R01Ledger. The Strategy Lab AST gate is reused;
this deliberately smaller entry point permits no imports or filesystem access.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import statistics
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

from backend.services.engine.strategy_lab.runner.ast_checker import assert_safe, ASTCheckError
from backend.shared.stock_utils import StockCodeUtil


class ProgramLimitError(BaseException):
    pass


def execution_digest() -> str:
    root = Path(__file__).resolve().parents[4]
    files = sorted((root / "backend/services/simulation/replay").glob("*.py"))
    files += sorted((root / "backend/services/simulation/virtual_run").glob("*.py"))
    files += [root / "backend/shared/stock_utils.py",
              root / "backend/services/simulation/services/ashare_matcher.py",
              root / "backend/services/simulation/services/local_market_data.py",
              root / "backend/services/engine/tasks/r01_virtual_run_scheduler.py",
              root / "backend/services/engine/strategy_lab/runner/ast_checker.py"]
    content = [(str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()


@lru_cache(maxsize=64)
def compile_program(source: str):
    if not source or len(source.encode()) > 64_000:
        raise ValueError("strategy_source_size: expected 1..64000 bytes")
    try:
        assert_safe(source, allowed_modules=(), require_hooks=False)
    except (ASTCheckError, SyntaxError) as exc:
        raise ValueError(f"strategy_validation: {exc}") from None
    tree = ast.parse(source)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "on_signal" for n in tree.body):
        raise ValueError("strategy requires on_signal(ctx)")
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef,
                          ast.Global, ast.Nonlocal, ast.While, ast.Pow)):
            raise ValueError(f"unsupported strategy construct: {type(n).__name__}")
        if isinstance(n, ast.Attribute) and n.attr.startswith("_"):
            raise ValueError("private attributes are unavailable")
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)) and len(n.value) > 8000:
            raise ValueError("strategy literal too large")
        if isinstance(n, ast.Constant) and isinstance(n.value, int) and abs(n.value) > 10000:
            raise ValueError("strategy integer literal too large")
    filename = "<r01-strategy:" + hashlib.sha256(source.encode()).hexdigest()[:16] + ">"
    return compile(tree, filename, "exec"), filename


def evaluate_program(source: str, context: dict) -> dict:
    compiled, filename = compile_program(source)
    # Fresh globals on every decision: hidden Python state cannot diverge across
    # restart or between historical and virtual execution.
    namespace = {"__builtins__": {"abs": abs, "min": min, "max": max, "sum": sum,
        "len": len, "float": float, "int": int, "dict": dict, "list": list,
        "sorted": sorted, "enumerate": enumerate, "zip": zip, "round": round,
        "all": all, "any": any, "range": range, "sqrt": math.sqrt,
        "fsum": math.fsum, "stdev": statistics.stdev, "ValueError": ValueError}}
    remaining = 20_000

    def trace(frame, event, arg):
        nonlocal remaining
        if frame.f_code.co_filename == filename:
            remaining -= 1
            if remaining < 0:
                raise ProgramLimitError("strategy_instruction_limit")
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        exec(compiled, namespace, namespace)
        out = namespace["on_signal"](json.loads(json.dumps(context, allow_nan=False)))
    except ProgramLimitError as exc:
        raise ValueError(str(exc)) from None
    finally:
        sys.settrace(previous)
    if not isinstance(out, dict) or set(out) - {"targets", "reason", "state"}:
        raise ValueError("on_signal must return targets and reason")
    targets = out.get("targets")
    if targets is not None:
        if not isinstance(targets, dict):
            raise ValueError("targets must be a weights mapping or null")
        allowed = set(context["symbols"])
        normalized = {}
        for code, value in targets.items():
            code = StockCodeUtil.to_suffix(code)
            if code not in allowed or code in normalized or isinstance(value, bool):
                raise ValueError("target outside frozen universe or duplicate symbol")
            value = float(value)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("weights must be finite and between zero and one")
            normalized[code] = value
        if sum(normalized.values()) > 1 + 1e-9:
            raise ValueError("leverage is not allowed")
        # Missing targets mean liquidation, not retaining a prior holding.
        targets = {code: normalized.get(code, 0.0) for code in sorted(allowed)}
    result = {"targets": targets, "reason": str(out.get("reason") or "")[:1000]}
    if "state" in out:
        state = json.dumps(out["state"], allow_nan=False)
        if not isinstance(out["state"], dict) or len(state) > 8000:
            raise ValueError("strategy state must be a small JSON mapping")
        result["state"] = json.loads(state)
    return result


def decision_context(package, parameters: dict, decision_date: date, *,
                     is_entry: bool, snapshot: dict | None = None,
                     next_trade_date: date | None = None) -> dict:
    symbols = sorted({StockCodeUtil.to_suffix(s) for s in parameters["symbols"]})
    lookback = int(parameters.get("lookback", 1))
    if not 1 <= lookback <= 504:
        raise ValueError("lookback must be 1..504 trading days")
    all_days = [d for d in package.trade_dates() if d <= decision_date]
    days = all_days[-lookback:]
    nxt = next_trade_date or package.next_trade_date(decision_date)
    month_end = nxt is not None and (nxt.year, nxt.month) != (decision_date.year, decision_date.month)
    need_signal_data = not parameters.get("signal_on_month_end") or month_end
    histories = {}
    if lookback > 1 and need_signal_data:
        for s in symbols:
            values = [package.adjusted_close(s, d) for d in days]
            if len(values) != lookback or any(v is None or not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError(f"signal_data_gap:{s}:{decision_date}")
            histories[s] = values
    monthly_prices = {}
    months = int(parameters.get("monthly_lookback", 0))
    if months and need_signal_data:
        if not 1 <= months <= 24:
            raise ValueError("monthly_lookback must be 1..24")
        endpoints = {(d.year, d.month): d for d in all_days}
        month_keys = []
        y, m = decision_date.year, decision_date.month
        for _ in range(months):
            month_keys.insert(0, (y, m))
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        if any(k not in endpoints for k in month_keys):
            raise ValueError("signal_data_gap: missing consecutive month endpoint")
        for s in symbols:
            values = [package.adjusted_close(s, endpoints[k]) for k in month_keys]
            if any(v is None or not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError(f"signal_data_gap:month_end:{s}")
            monthly_prices[s] = values
    return {"date": decision_date.isoformat(), "month": decision_date.month,
            "is_entry": is_entry,
            "is_month_end": month_end, "monthly_prices": monthly_prices,
            "symbols": symbols, "parameters": parameters, "history": histories,
            "snapshot": snapshot or {}}


FIXED_ALLOCATION_SOURCE = '''# QuantMind R01 fixed allocation: used unchanged by both execution modes.
def on_signal(ctx):
    p = ctx["parameters"]
    due = ctx["is_entry"]
    frequency = p.get("frequency", "monthly")
    if frequency != "buy_hold" and ctx["is_month_end"]:
        due = frequency != "quarterly" or ctx["month"] in (3, 6, 9, 12)
    if not due:
        return {"targets": None, "reason": "daily_review_no_rebalance"}
    if frequency == "band" and not ctx["is_entry"]:
        snap = ctx["snapshot"]
        nav = snap["nav_exact"]
        positions = snap["positions"]
        deviations = [abs(positions.get(s, {}).get("market_value", 0) / nav - w)
                      for s, w in p["target_weights"].items()]
        if max(deviations) <= p["band"]:
            return {"targets": None, "reason": "within_rebalance_band"}
    return {"targets": p["target_weights"], "reason": "entry" if ctx["is_entry"] else "scheduled_rebalance"}
'''


DYNAMIC_ALLOCATION_SOURCE = '''# R01SELF B1/B2/B3 signal adapter; matching/accounting remain in R01Ledger.
def on_signal(ctx):
    p = ctx["parameters"]
    state = ctx.get("state", {})
    if not ctx["is_month_end"]:
        return {"targets": None, "reason": "daily_review_no_rebalance", "state": state}
    kind = p["rule"]
    if kind == "sma":
        gates = {}
        for symbol, values in ctx["monthly_prices"].items():
            average = fsum(values) / len(values)
            gates[symbol] = 1 if values[-1] > average else 0 if values[-1] < average else state.get("gates", {}).get(symbol, 0)
        weights = {s: w * gates[s] for s, w in p["target_weights"].items()}
        return {"targets": weights, "reason": "monthly_sma_filter", "state": {"gates": gates}}
    if kind == "momentum":
        scores = {s: values[-1] / values[0] - 1 for s, values in ctx["monthly_prices"].items()}
        ranked = sorted(ctx["symbols"], key=lambda s: (-scores[s], s))
        picked = ranked[:p["top_n"]]
        return {"targets": {s: 1 / len(picked) if s in picked else 0 for s in ctx["symbols"]}, "reason": "monthly_relative_momentum", "state": {}}
    if kind == "vol_target":
        history = ctx["history"]
        returns = []
        for i in range(1, len(history[ctx["symbols"][0]])):
            value = 0.0
            for s, w in p["target_weights"].items():
                value += w * (history[s][i] / history[s][i-1] - 1)
            returns.append(value)
        volatility = stdev(returns) * sqrt(p["annualization"])
        scale = min(1.0, p["volatility_target"] / max(volatility, 0.000001))
        return {"targets": {s: w * scale for s, w in p["target_weights"].items()}, "reason": "monthly_volatility_target", "state": {}}
    raise ValueError("unknown frozen rule")
'''
