"""Causal factor expressions: a small AST interpreter, never Python eval/exec."""
from __future__ import annotations

import ast
import math

FUNCTIONS = {"rank": 1, "abs": 1, "log1p_abs": 1, "lag": 2, "mean": 2, "std": 2}


def validate(expression: str, columns: list[str]) -> dict:
    if not isinstance(expression, str) or not 1 <= len(expression) <= 800:
        raise ValueError("Factor expression must contain 1–800 characters")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("Factor expression is too complex")
    used = set()

    def visit(node):
        if isinstance(node, ast.Name) and node.id in columns:
            used.add(node.id)
            return 0
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if math.isfinite(node.value) and abs(node.value) <= 100:
                return 0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            return max(visit(node.left), visit(node.right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in FUNCTIONS or node.keywords or len(node.args) != FUNCTIONS[name]:
                raise ValueError("Unknown function or incorrect argument count")
            history = visit(node.args[0])
            if name in {"lag", "mean", "std"}:
                window = node.args[1]
                if not isinstance(window, ast.Constant) or type(window.value) is not int or not 1 <= window.value <= 60:
                    raise ValueError("History window must be an integer in 1–60; future shifts are forbidden")
                history += window.value
            return history
        raise ValueError("Only supplied columns, constants, arithmetic and causal functions are allowed")

    lookback = visit(tree.body)
    if not used or lookback > 120:
        raise ValueError("Expression needs a data column and at most 120 historical observations")
    return {"expression": expression, "columns": sorted(used), "lookback": lookback}


def evaluate(frame, expression: str, columns: list[str]):
    import numpy as np
    import pandas as pd

    validate(expression, columns)
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("Duplicate factor observations")
    ordered = frame.sort_values(["symbol", "trade_date"])

    def series(value):
        return value if isinstance(value, pd.Series) else pd.Series(value, index=ordered.index, dtype=float)

    def walk(node):
        if isinstance(node, ast.Name):
            return ordered[node.id].astype(float)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.UnaryOp):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            denominator = series(right).mask(lambda s: s.abs() < 1e-12)
            return left / denominator
        name, value = node.func.id, series(walk(node.args[0]))
        if name == "rank":
            return value.groupby(ordered["trade_date"]).rank(pct=True)
        if name == "abs":
            return value.abs()
        if name == "log1p_abs":
            return np.log1p(value.abs())
        n = node.args[1].value
        grouped = value.groupby(ordered["symbol"], sort=False)
        if name == "lag":
            return grouped.shift(n)
        return grouped.transform(lambda s: getattr(s.rolling(n, min_periods=n), name)(**({"ddof": 0} if name == "std" else {})))

    result = series(walk(ast.parse(expression, mode="eval").body))
    return result.replace([np.inf, -np.inf], np.nan).reindex(frame.index)


def diagnostics(frame, feature: str, base_features: list[str], cfg: dict) -> dict:
    """IC uses actual forward returns supplied separately from ranked training labels."""
    import numpy as np
    import pandas as pd

    def number(value):
        return float(value) if pd.notna(value) and np.isfinite(value) else None

    results = {}
    for split, (start, end) in cfg["split"].items():
        sample = frame[(frame.trade_date >= pd.Timestamp(start)) & (frame.trade_date <= pd.Timestamp(end))
                       & (frame.label_end <= pd.Timestamp(end))]
        valid = sample.dropna(subset=[feature, "forward_return"])
        daily = []
        spreads = []
        for day, group in valid.groupby("trade_date"):
            if len(group) < 10 or group[feature].nunique() < 2 or group.forward_return.nunique() < 2:
                continue
            ic = group[feature].corr(group.forward_return)
            rank_ic = group[feature].rank().corr(group.forward_return.rank())
            daily.append({"date": str(day.date()), "ic": number(ic), "rank_ic": number(rank_ic)})
            ranks = group[feature].rank(pct=True)
            spreads.append(group.loc[ranks > .8, "forward_return"].mean() - group.loc[ranks <= .2, "forward_return"].mean())
        values = pd.DataFrame(daily, columns=["date", "ic", "rank_ic"])
        std = values.rank_ic.std(ddof=1)
        correlations = {name: number(valid[feature].rank().corr(valid[name].rank())) for name in base_features}
        results[split] = {"rows": len(sample), "valid_rows": len(valid),
            "coverage": len(valid)/len(sample) if len(sample) else 0,
            "ic": number(values.ic.mean()), "rank_ic": number(values.rank_ic.mean()),
            "rank_icir": number(values.rank_ic.mean()/std) if pd.notna(std) and std > 0 else None,
            "daily": daily, "positive_rank_ic_fraction": number((values.rank_ic > 0).mean()) if len(values) else None,
            "top_minus_bottom_forward_return": number(pd.Series(spreads, dtype=float).mean()),
            "pooled_rank_correlation": correlations}
    return {"feature": feature, "splits": results,
        "label": "close[T+2] / close[T+1] - 1, actual forward return; purged at split boundaries",
        "rank_icir_definition": "mean daily Rank IC / sample standard deviation, not annualized",
        "spread_definition": "mean daily top-minus-bottom quintile forward return before costs, not a portfolio backtest",
        "research_status": "development_comparison"}
