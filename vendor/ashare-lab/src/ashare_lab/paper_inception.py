"""Prove original pending signals before any migrated 2026-10-14 ledger append.

The source worker runs preserved paper/forward code against its preserved inputs
in a separate interpreter. Neither source weights nor published reports change.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ORIGINAL = ("lowvol", "b2_lowvol_vt", "b3_lqv_buf_vt")
INCEPTION = "2026-10-13"
FILES = ("meta.json", "nav.csv", "positions.csv", "trades.csv", "targets.csv")
RTOL = ATOL = 1e-12


def _hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def _bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def published_pending(content):
    """Read the existing report's explicit target column, never empty target CSVs."""
    if f"# 虚拟盘日报 · {INCEPTION}" not in content:
        raise ValueError("Published report is not the frozen inception report")
    result = {name: {} for name in ORIGINAL}
    account, pending = None, False
    for line in content.splitlines():
        if line.startswith("## "):
            account = line[3:].strip()
            account = account if account in ORIGINAL else None
            pending = False
        elif line.startswith("### "):
            pending = line.strip() == "### 下一交易日待执行目标"
        elif account and pending and line.startswith("|"):
            fields = [field.strip() for field in line.strip().strip("|").split("|")]
            if len(fields) != 6 or not re.fullmatch(r"\d{6}\.(SH|SZ)", fields[1]):
                continue
            code, weight = fields[1], fields[4]
            if code in result[account] or not re.fullmatch(r"\d+(?:\.\d+)?%", weight):
                raise ValueError(f"Ambiguous published pending row: {account}/{code}")
            result[account][code] = weight
    if any(not rows for rows in result.values()):
        raise ValueError("Missing published original pending signals; empty CSV is not no signal")
    return result


def compare_weights(source, current, published):
    """Keep every code and every full-precision weight in the comparison evidence."""
    rows = []
    for code in sorted(set(source) | set(current) | set(published)):
        old, new, printed = source.get(code), current.get(code), published.get(code)
        full_match = (old is not None and new is not None and
                      math.isfinite(old) and math.isfinite(new) and
                      math.isclose(old, new, rel_tol=RTOL, abs_tol=ATOL))
        publication_match = old is not None and format(old, ".2%") == printed
        rows.append({"code": code,
                     "source_weight": str(old) if old is not None and not math.isfinite(old) else old,
                     "runtime_weight": str(new) if new is not None and not math.isfinite(new) else new,
                     "published_target": printed,
                     "absolute_difference": (abs(old - new) if old is not None and new is not None and
                                             math.isfinite(old) and math.isfinite(new) else None),
                     "source_matches_published": publication_match,
                     "runtime_matches_source": full_match})
    return {"matched": bool(rows) and all(row["source_matches_published"] and
                                           row["runtime_matches_source"] for row in rows),
            "rtol": RTOL, "atol": ATOL, "rows": rows}


def source_evidence(tree):
    tree = Path(tree).resolve()
    if tree.name != "ashare-lab-paper" or tree.parent.name != "trees":
        raise ValueError("Original signal proof requires the preserved ashare-lab-paper tree")
    archive = tree.parent.parent
    identity_path = archive / "identity.json"
    identity = json.loads(identity_path.read_text())
    assembly = json.loads((Path(__file__).resolve().parents[2] / "frozen-source.json").read_text())
    if _hash(identity_path) != assembly["archive_identity_sha256"]:
        raise ValueError("Original archive identity changed")
    captured = next(row for row in identity["trees"] if row["name"] == tree.name)
    manifest = archive / captured["manifest"]
    if _hash(manifest) != captured["manifest_sha256"]:
        raise ValueError("Original paper file manifest changed")
    records = [json.loads(line) for line in manifest.read_text().splitlines() if line]
    mandatory = {"paper/latest.md", "data/live/panel/build_meta.json", "data/live/fundamentals/fin_meta.json",
                 "requirements.txt", "src/ashare_lab/paper.py", "src/ashare_lab/engine.py", "experiments/paper/accounts.py"}
    mandatory.update(f"paper/{name}/{file}" for name in ORIGINAL for file in FILES)
    mandatory.update(f"data/live/panel/{name}.parquet" for name in
                     ("stocks", "calendar", "index_members", "index_daily", "industry", "daily", "basic"))
    mandatory.update(f"data/live/fundamentals/{name}.parquet" for name in
                     ("fin_income", "fin_balance", "fin_cashflow"))
    selected = {}
    for record in records:
        name = record["path"]
        relevant = (name in mandatory or
                    (name.startswith("src/ashare_lab/") and name.endswith(".py")) or
                    (name.startswith("experiments/paper/") and name.endswith(".py")) or
                    name.startswith("data/live/panel/") or name.startswith("data/live/fundamentals/"))
        if not relevant or record["kind"] != "file":
            continue
        path = tree / name
        if _hash(path) != record["sha256"] or path.stat().st_size != record["size"]:
            raise ValueError(f"Frozen source/input/report tamper: {name}")
        selected[name] = record["sha256"]
    if mandatory - set(selected):
        raise ValueError(f"Missing frozen inception evidence: {sorted(mandatory - set(selected))}")
    report = (tree / "paper/latest.md").read_text()
    market = json.loads((tree / "data/live/panel/build_meta.json").read_text())
    fund = json.loads((tree / "data/live/fundamentals/fin_meta.json").read_text())
    if market["end"] != INCEPTION or market["release_id"] not in report or fund["release_id"] not in report:
        raise ValueError("Published pending report and preserved input release identities disagree")
    return {"archive_identity_sha256": _hash(identity_path), "source_commit": captured["commit"],
            "source_branch": captured["branch"], "source_manifest_sha256": captured["manifest_sha256"],
            "market_release_id": market["release_id"], "fundamental_release_id": fund["release_id"],
            "files": selected, "published": published_pending(report)}


def _source_worker(tree, out):
    """Only this branch imports the archived package; it never imports vendor modules."""
    sys.dont_write_bytecode = True
    # -B prevents writes, not reads of archived __pycache__. Redirect cache
    # lookup to a fresh temporary location so the hashed .py is what executes.
    sys.pycache_prefix = str(Path(out).parent / "unused-bytecode-cache")
    tree = Path(tree).resolve()
    sys.path[:0] = [str(tree / "src"), str(tree)]
    import ashare_lab
    import numpy as np
    import pandas as pd
    import pyarrow
    import duckdb
    from ashare_lab.data.market import load_market_data
    from ashare_lab.data.fundamentals import Fundamentals
    from ashare_lab.engine import CostModel
    from ashare_lab.paper import simulate, append_ledger
    from experiments.paper.accounts import make_accounts
    if not Path(ashare_lab.__file__).absolute().is_relative_to(tree / "src"):
        raise ValueError("Independent worker did not import the preserved paper/forward source")
    # Match the actual original update.py invocation exactly: two years before
    # inception, original frozen data/live and its original calendar fallback.
    data = load_market_data(tree / "data/live/panel", start=pd.Timestamp(INCEPTION) - pd.DateOffset(years=2),
                            end=INCEPTION, universe="000906.SH")
    if data.calendar[-1] != pd.Timestamp(INCEPTION):
        raise ValueError("Preserved original inputs do not reach inception")
    fund = Fundamentals.load(tree / "data/live/fundamentals")
    pending = {}
    for name, strategy, meta in make_accounts(data, fund, inception=INCEPTION, open_days=None):
        saved = json.loads((tree / "paper" / name / "meta.json").read_text())
        saved.pop("created_at", None)
        if saved != json.loads(json.dumps(meta, allow_nan=False)):
            raise ValueError(f"Original source does not reproduce frozen meta: {name}")
        result, weights = simulate(strategy, data, INCEPTION, INCEPTION, meta["initial_cash"], CostModel(**meta["costs"]))
        if weights is None or weights.empty or not np.isfinite(weights.to_numpy()).all():
            raise ValueError(f"Original source did not produce its initial pending signal: {name}")
        # Prefix verification writes only a temporary COPY, never archived ledgers.
        check = Path(out).parent / "source-ledger-check" / name
        check.mkdir(parents=True)
        for file in FILES:
            shutil.copyfile(tree / "paper" / name / file, check / file)
        if append_ledger(check, result)["new_dates"]:
            raise ValueError("Original initial ledger was not an exact existing prefix")
        pending[name] = {str(code): float(weight) for code, weight in weights.items()}
    modules = {}
    for module in tuple(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and Path(path).suffix == ".py" and Path(path).absolute().is_relative_to(tree):
            modules[str(Path(path).absolute().relative_to(tree))] = _hash(path)
    payload = {"pending": pending, "imported_source_modules": modules,
               "environment": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__,
                               "pyarrow": pyarrow.__version__, "duckdb": duckdb.__version__},
               "original_initial_ledger_prefix_match": True}
    Path(out).write_bytes(_bytes(payload))


def original_reference(tree):
    """Independently reproduce the original source; no read-through CURRENT/cache."""
    tree = Path(tree).resolve()
    evidence = source_evidence(tree)
    with tempfile.TemporaryDirectory(prefix="paper-source-inception-") as temporary:
        out = Path(temporary) / "source-pending.json"
        command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                   "--source-worker", str(tree), "--out", str(out)]
        process = subprocess.run(command, cwd=temporary,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ""},
            capture_output=True, text=True, check=False)
        if process.returncode:
            raise ValueError(f"Original inception worker failed ({process.returncode}): {process.stderr[-4000:]}")
        reproduced = json.loads(out.read_text())
    if any(path not in evidence["files"] or evidence["files"][path] != sha
           for path, sha in reproduced["imported_source_modules"].items()):
        raise ValueError("Independent worker imported source outside its captured identity")
    comparisons = {name: compare_weights(reproduced["pending"][name], reproduced["pending"][name],
                                         evidence["published"][name]) for name in ORIGINAL}
    return {"schema_version": 1, "inception": INCEPTION, "source": evidence, **reproduced,
            "source_report_comparison": comparisons,
            "source_report_match": all(row["matched"] for row in comparisons.values()),
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "historical_forward_evidence": False}


def runtime_comparison(name, signal_weights, reference, code_hash, input_hash):
    compared = compare_weights(reference["pending"][name], signal_weights, reference["source"]["published"][name])
    return {"schema_version": 1, "account": name, "signal_date": INCEPTION,
            "kind": "original_pending_to_runtime_inception", **compared,
            "matched": compared["matched"] and reference["source_report_match"],
            "source_reference_sha256": hashlib.sha256(_bytes(reference)).hexdigest(),
            "source_commit": reference["source"]["source_commit"],
            "source_manifest_sha256": reference["source"]["source_manifest_sha256"],
            "report_sha256": reference["source"]["files"]["paper/latest.md"],
            "runtime_code_sha256": code_hash, "input_manifest_sha256": input_hash,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "historical_forward_evidence": False}


def reconcile_inception(tree, manifest=None):
    """Independent evidence-only entry point; no account/ledger mutations."""
    from . import paper_runtime as runtime
    from .paper_accounts import make_accounts
    from .data.market import load_market_data
    from .data.fundamentals import Fundamentals
    from .engine import BacktestConfig, CostModel, run_backtest
    import pandas as pd
    tree = Path(tree).resolve()
    reference = original_reference(tree)
    if manifest is None:
        panel, financial = tree / "data/live/panel", tree / "data/live/fundamentals"
        cutoff, days, input_hash = INCEPTION, None, None
    else:
        inputs = runtime.load_inputs(manifest)
        panel, financial, cutoff = inputs["panel"], inputs["fundamentals"], inputs["usable_date"]
        days = runtime.exchange_days(inputs["calendar"], "SSE", cutoff)
        input_hash = inputs["identity_sha256"]
    data = load_market_data(panel, start="2024-01-01", end=cutoff, universe="000906.SH")
    fund = Fundamentals.load(financial)
    comparisons = {}
    code_hash = runtime._source_hash()
    for name, strategy, meta in make_accounts(data, fund, inception=INCEPTION, open_days=days):
        result = run_backtest(strategy, data, BacktestConfig(INCEPTION, INCEPTION, meta["initial_cash"], CostModel()))
        weights = result.signals.loc[pd.Timestamp(INCEPTION)] if pd.Timestamp(INCEPTION) in result.signals.index else pd.Series(dtype=float)
        weights = {str(code): float(weight) for code, weight in weights.items() if weight != 0}
        comparisons[name] = runtime_comparison(name, weights, reference, code_hash, input_hash)
    return {"schema_version": 1, "kind": "independent_inception_signal_reconciliation",
            "source_reference": reference, "accounts": comparisons,
            "matched": set(comparisons) == set(ORIGINAL) and all(row["matched"] for row in comparisons.values()),
            "no_ledger_mutations": True, "historical_forward_evidence": False,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-worker", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    _source_worker(args.source_worker, args.out)
