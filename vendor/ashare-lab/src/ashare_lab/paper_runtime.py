"""One ashare engine, byte-preserved migration and recoverable append-only paper ledgers.

Inputs are an explicit versioned manifest, not a mutable CURRENT pointer. No broker
or account-manager calls are made. The API reads these very same persisted ledgers.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .data.market import load_market_data
from .data.fundamentals import Fundamentals
from .engine import (BacktestConfig, CostModel, run_backtest, run_futures_account)
from .paper import (LedgerMismatch, _publish, append_ledger, init_account, read_ledger,
                    InceptionRebalance)
from .paper_assets import (exchange_days, i7_calendar_context, bond_market,
                           futures_inputs, FixedTargets)
from .strategies.allocation import InverseVolAllocation
from .strategies.lowvol_trend import LowVolTrend

ACCOUNTS = ("lowvol", "b2_lowvol_vt", "b3_lqv_buf_vt", "i7_turn_of_month",
            "s1_invvol_etf", "cb_double_low", "cta_combined", "cta_trend")
ORIGINAL = ACCOUNTS[:3]
FILES = ("meta.json", "nav.csv", "positions.csv", "trades.csv", "targets.csv")
DISCLAIMER = ("Frozen paper observations only; not strategy-pass or trading permission. "
              "Historical backfill is replay, never historical actual forward evidence. "
              "Futures margin, collateral interest and forced liquidation are not modelled.")


def frozen_specs():
    common = {"status": "OBSERVATION", "frozen": True, "trading_permission": False,
              "disclaimer": DISCLAIMER}
    specs = {name: {**common, "name": name, "initial_cash": 1_000_000} for name in ACCOUNTS}
    for name in ORIGINAL:
        specs[name].update(source="paper/forward", migration="byte_preserved_source")
    specs["i7_turn_of_month"].update(symbol="510300.SH", execution="CLOSE",
        rule="last session and first three sessions of month; calendar known before execution",
        per_side_total_cost=.00075, stamp_tax=0, lot=100, source="ideas_calendar.calendar_nav",
        calendar_context="complete real daily month rows, next-month first open and two sessions after cutoff; otherwise I7 pending")
    specs["s1_invvol_etf"].update(initial_cash=10_000_000, source="paper/s1-etf",
        stock="LowVolTrend W250 N50 no timing", sleeves={"bond": "511010.SH", "gold": "518880.SH"},
        window=60, min_obs=20, execution="next session OPEN", costs=asdict(CostModel()),
        etf_stamp_tax=0, etf_stock_transfer_fee=0,
        cost_model_id="s1-etf-secondary-fees-v2",
        commission_slippage="frozen simulation assumptions, not the user's broker agreement",
        fee_evidence=[
            {"url": "https://www.sse.com.cn/assortment/fund/etf/home/c/c_20151111_4011009.shtml",
             "scope": "ETF secondary market: 100-unit lots and no stamp duty"},
            {"url": "https://www.cs.ecitic.com/newsite/xxgs/cgxm_21852/202311/P020231122627702227009.pdf",
             "scope": "Fund secondary trades list commission; ETF creation/redemption basket transfer is a separate business"},
            {"url": "https://m.chinaclear.cn/zdjs/fbzyls/service_tlist/code_0.shtml",
             "scope": "2026-01-01 Shanghai schedule: stock transfer item is A shares; ETF item is creation/redemption baskets, not secondary ETF units"}],
        original_report_unchanged=True, migration="new_account_not_source_migration")
    for name in ("i7_turn_of_month", "s1_invvol_etf"):
        specs[name].update(
            etf_adjustment_model="legacy adjusted-share/reinvestment proxy, NOT a cash-dividend ledger",
            etf_dividend_policy="block held ETF non-unit/missing adj ratio or known fund_div ex-date before append",
            etf_cash_dividend_history_verified=False)
    specs["cb_double_low"].update(source="docs/14", top_n=20, commission=.0002,
        slippage=.001, transfer=0, stamp_tax=0, lot=10, execution="weekly signal next session OPEN",
        migration="new_account_not_source_migration")
    for name in ("cta_combined", "cta_trend"):
        specs[name].update(source="docs/15", commission_per_side=.0002, lot=1,
            multiplier="required positive basic.normalized_multiplier with source units/formula/object hash; commodity raw multiplier may be null",
            multiplier_evidence="https://tushare.pro/document/2?doc_id=135",
            settlement="daily settlement price MTM",
            rollover="close old/open new at CLOSE, both legs charged", execution="weekly signal next session CLOSE; daily maintenance",
            migration="new_account_not_source_migration", margin_modelled=False)
    return specs


def digest(content):
    return hashlib.sha256(content).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


@contextmanager
def ledger_lock(root, exclusive=True):
    root = Path(root)
    if exclusive:
        root.mkdir(parents=True, exist_ok=True)
    with (root / ".paper.lock").open("a+b" if exclusive else "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def _recover(directory):
    journal = directory / "pending.json"
    if not journal.exists():
        return
    plan = json.loads(journal.read_text())
    for item in plan:
        target = directory / item["name"]
        actual = file_hash(target) if target.exists() else None
        if actual == item["new_hash"]:
            continue
        if actual != item["old_hash"]:
            raise LedgerMismatch(f"Interrupted transaction tampered: {target}")
        staged = directory / item["staged"]
        if file_hash(staged) != item["new_hash"]:
            raise LedgerMismatch(f"Interrupted transaction payload tampered: {staged}")
        _publish({target: staged.read_bytes()})
    journal.unlink()
    # Committed payloads remain immutable evidence, including old/new hashes.


def _transaction(directory, contents):
    if not contents:
        return
    token = digest(b"".join(k.encode() + v for k, v in sorted(contents.items())))
    payload = directory / "commits" / token
    payload.mkdir(parents=True, exist_ok=True)
    plan = []
    for name, content in contents.items():
        target = directory / name
        staged = payload / name
        if staged.exists() and staged.read_bytes() != content:
            raise LedgerMismatch("Commit hash collision/tampered payload")
        if not staged.exists():
            _publish({staged: content})
        plan.append({"name": name, "old_hash": file_hash(target) if target.exists() else None,
                     "new_hash": digest(content), "staged": str(staged.relative_to(directory))})
    _publish({payload / "transaction.json": json_bytes(plan),
              directory / "pending.json": json_bytes(plan)})
    _recover(directory)


def _assert_seal(directory):
    seal_path = directory / "seal.json"
    if not seal_path.exists():
        raise LedgerMismatch(f"Unsealed account: {directory}")
    seal = json.loads(seal_path.read_text())
    for name, expected in seal.items():
        path = directory / name
        if not path.exists() or file_hash(path) != expected:
            raise LedgerMismatch(f"Historical tamper refusal: {path}")
    identity_path = directory / "identity.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
        for name, length in identity.get("source_byte_lengths", {}).items():
            with (directory / name).open("rb") as stream:
                prefix = stream.read(length)
            if digest(prefix) != identity["source_files"][name]:
                raise LedgerMismatch(f"Source migration prefix changed: {directory / name}")


def _seal(contents, directory):
    names = [*FILES, "identity.json", "observations.jsonl", "reconciliation.jsonl", "signals.jsonl",
             "inception_source.json", "inception_reconciliation.jsonl"]
    return {name: digest(contents[name]) if name in contents else file_hash(directory / name)
            for name in names if name in contents or (directory / name).exists()}


def load_inputs(path):
    path = Path(path).resolve()
    spec = json.loads(path.read_text())
    for field in ("version", "usable_date", "replay_start", "files", "panel", "fundamentals", "calendar", "asset_inputs"):
        if field not in spec:
            raise ValueError(f"Input manifest missing {field}")
    if not spec["files"]:
        raise ValueError("Empty immutable input identity")
    if set(spec["asset_inputs"]) - set(ACCOUNTS[3:]):
        raise ValueError("Input manifest contains unknown asset account keys")
    def resolve(value):
        return (path.parent / value).resolve()
    files = {}
    for name, expected in spec["files"].items():
        candidate = resolve(name)
        if file_hash(candidate) != expected:
            raise LedgerMismatch(f"Input identity mismatch: {candidate}")
        files[str(candidate)] = expected
    sources = {name: spec[name] for name in ("panel", "fundamentals", "calendar")}
    sources.update(spec["asset_inputs"])
    for name, value in sources.items():
        source = resolve(value)
        expected_paths = sorted(p for p in source.rglob("*") if p.is_file()) if source.is_dir() else [source]
        if not expected_paths or any(str(p.resolve()) not in files for p in expected_paths):
            raise ValueError(f"Unhashed or absent {name} source input")
        if name in ("panel", "fundamentals", "calendar"):
            spec[name] = source
        else:
            spec["asset_inputs"][name] = source
    spec["identity_sha256"] = digest(path.read_bytes())
    spec["manifest_path"] = str(path)
    return spec


def _source_hash():
    root = Path(__file__).resolve().parent
    records = {str(p.relative_to(root)): file_hash(p) for p in sorted(root.rglob("*.py"))}
    return digest(json_bytes(records))


def _initialize(directory, name, source, inputs, code_hash, bindings, *, source_reference=None):
    owner = {"user_id": str(bindings["user_id"]), "tenant_id": str(bindings["tenant_id"])}
    registration = bindings["accounts"][name]
    if registration["runtime_code_sha256"] != code_hash:
        raise LedgerMismatch(f"Registered runtime version changed for {name}")
    if directory.exists():
        _recover(directory)
        if (directory / "seal.json").exists():
            _assert_seal(directory)
            identity = json.loads((directory / "identity.json").read_text())
            if (identity["spec"] != frozen_specs()[name] or
                    identity["code_sha256"] != code_hash or
                    identity["replay_start"] != inputs["replay_start"] or
                    identity["owner"] != owner or identity["registry"] != registration):
                raise LedgerMismatch(f"Frozen spec/code/start changed for {name}")
            if name in ORIGINAL:
                seal = json.loads((directory / "seal.json").read_text())
                if not {"inception_source.json", "inception_reconciliation.jsonl"}.issubset(seal):
                    raise LedgerMismatch(f"{name}: original pending signal source proof is missing")
            return identity
        if any((directory / file).exists() for file in FILES):
            raise LedgerMismatch(f"Unsealed existing ledger cannot be adopted: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = {"name": name, "created_at": now, "spec": frozen_specs()[name],
                "code_sha256": code_hash, "replay_start": inputs["replay_start"],
                "source_files": {}, "source_byte_lengths": {},
                "owner": owner, "registry": registration,
                "original_history_is_forward_evidence": False}
    contents = {}
    if name in ORIGINAL:
        if source_reference is None or not source_reference["source_report_match"]:
            raise LedgerMismatch(f"{name}: original pending signals must independently match the published report")
        contents["inception_source.json"] = json_bytes(source_reference)
        contents["inception_reconciliation.jsonl"] = b""
        identity["inception_source_sha256"] = digest(contents["inception_source.json"])
        account = Path(source) / name
        for file in FILES:
            content = (account / file).read_bytes()
            if digest(content) != source_reference["source"]["files"][f"paper/{name}/{file}"]:
                raise LedgerMismatch(f"{name}: migration source differs from independently verified {file}")
            contents[file] = content
            identity["source_files"][file] = digest(content)
            identity["source_byte_lengths"][file] = len(content)
        identity["migration"] = "source_bytes_preserved"
        identity["source_created_at"] = json.loads(contents["meta.json"])["created_at"]
        identity["source_dates"] = pd.read_csv(account / "nav.csv").date.tolist()
        if json.loads(contents["meta.json"])["inception"] != source_reference["inception"]:
            raise LedgerMismatch(f"{name}: source pending signal date differs from account inception")
    else:
        identity["migration"] = "new_at_actual_creation_time_with_separate_historical_replay"
        contents["meta.json"] = json_bytes({**frozen_specs()[name], "created_at": now,
                                          "inception": inputs["replay_start"]})
    contents["identity.json"] = json_bytes(identity)
    contents["observations.jsonl"] = b"".join(json.dumps({
        "date": date, "kind": "source_snapshot_not_verified_forward",
        "recorded_at": now, "historical_forward_evidence": False},
        sort_keys=True).encode() + b"\n" for date in identity.get("source_dates", []))
    contents["reconciliation.jsonl"] = b""
    contents["signals.jsonl"] = (json.dumps({
        "date": source_reference["inception"], "weights": source_reference["pending"][name]},
        sort_keys=True).encode() + b"\n") if name in ORIGINAL else b""
    contents["seal.json"] = json_bytes(_seal(contents, directory))
    _transaction(directory, contents)
    return identity


def _inception_gate(directory, name, result, inputs, code_hash):
    """Seal full source/publication/runtime comparisons before any financial append."""
    from .paper_inception import runtime_comparison
    reference = json.loads((directory / "inception_source.json").read_text())
    date = pd.Timestamp(reference["inception"])
    weights = result.signals.loc[date] if date in result.signals.index else pd.Series(dtype=float)
    weights = {str(code): float(weight) for code, weight in weights.items() if weight != 0}
    evidence = runtime_comparison(name, weights, reference, code_hash, inputs["identity_sha256"])
    history = directory / "inception_reconciliation.jsonl"
    stable = lambda row: {key: value for key, value in row.items() if key != "recorded_at"}
    existing = [json.loads(line) for line in history.read_text().splitlines()]
    if not any(stable(row) == stable(evidence) for row in existing):
        contents = {"inception_reconciliation.jsonl": history.read_bytes() +
                    json.dumps(evidence, sort_keys=True, allow_nan=False).encode() + b"\n"}
        contents["seal.json"] = json_bytes(_seal(contents, directory))
        _transaction(directory, contents)
    if not evidence["matched"]:
        raise LedgerMismatch(f"{name}: original published/recomputed pending differs from runtime; "
                             f"refusing financial append; evidence: {history}")


def _etfs(data, path, codes, require_limits=False, execution_start=None):
    from .expansion.etf_market import with_etfs
    frame = pd.read_parquet(path)
    required = {"date", "code", "open", "close", "adj", "amount", "volume", "up_limit", "down_limit"}
    if not required.issubset(frame):
        raise ValueError(f"ETF source missing actual frozen fields: {sorted(required - set(frame))}")
    frame["date"] = pd.to_datetime(frame.date)
    if frame.duplicated(["date", "code"]).any():
        raise ValueError("Duplicate ETF date/code")
    if not set(codes).issubset(set(frame.code)):
        raise ValueError("Missing required ETF identity")
    frames = {code: frame.loc[frame.code.eq(code)].set_index("date") for code in codes}
    for code, quotes in frames.items():
        aligned = quotes.reindex(data.calendar)
        last = aligned.iloc[-1]
        if not np.isfinite(last["close"]) or last["close"] <= 0:
            raise ValueError(f"{code}: no actual quote at approved usable cutoff")
        tradable = aligned.open.gt(0) & aligned.close.gt(0)
        if execution_start is not None:
            tradable &= aligned.index >= pd.Timestamp(execution_start)
        if require_limits and aligned.loc[tradable, ["up_limit", "down_limit"]].isna().any().any():
            raise ValueError(f"{code}: S1 ETF actual execution limits unavailable; refusing stock-rule inference")
    data = with_etfs(data, frames)
    # Never use the helper's stock-style inferred limits instead of real inputs.
    for code in codes:
        for field in ("up_limit", "down_limit"):
            getattr(data, field)[code] = frames[code][field].reindex(data.calendar)
    return data, frames


def _etf_cash_guard(result, data, frames):
    """Do not book adjusted synthetic ETF units as genuine dividend accounting."""
    # The engine omits never-held instruments from its sparse position columns.
    positions = result.positions.reindex(columns=list(frames), fill_value=0)
    for code, quotes in frames.items():
        held = positions[code].shift(1, fill_value=0).gt(0)
        adj = quotes.adj.reindex(data.calendar)
        ratio = (adj / adj.shift()).reindex(result.positions.index)
        events = quotes.get("cash_dividend_event", pd.Series(False, index=quotes.index))
        events = events.reindex(result.positions.index).fillna(False).eq(True)
        unsupported = held & (events | ~np.isfinite(ratio) | ratio.ne(1))
        if unsupported.any():
            date = unsupported[unsupported].index[0]
            raise ValueError(f"{code} {date.date()}: held ETF has adj ratio={ratio.loc[date]!r}, "
                             f"known fund_div event={bool(events.loc[date])}; cash-dividend accounting "
                             "is not implemented, refusing append instead of creating cash or synthetic units")


def _result(name, identity, inputs, days, stocks, fund):
    end = inputs["usable_date"]
    start = identity["replay_start"]
    asset = inputs["asset_inputs"].get(name)
    if name not in ORIGINAL and asset is None:
        raise ValueError(inputs.get("input_errors", {}).get(name, f"Missing real {name} source input"))
    if name in ORIGINAL:
        from .paper_accounts import make_accounts
        accounts = make_accounts(stocks, fund, inception="2026-10-13", open_days=days)
        _, strategy, expected = next(a for a in accounts if a[0] == name)
        # Original metadata is kept byte-for-byte, including its obsolete textual
        # weekday-fallback description. Runtime uses only the strict calendar.
        return run_backtest(strategy, stocks, BacktestConfig("2026-10-13", end, 1e6, CostModel())), expected
    if name == "s1_invvol_etf":
        data, frames = _etfs(stocks, asset, ("511010.SH", "518880.SH"),
                     require_limits=True, execution_start=start)
        strategy = InceptionRebalance(InverseVolAllocation(
            LowVolTrend(vol_window=250, top_n=50, timing_index=None),
            {"bond": "511010.SH", "gold": "518880.SH"}, window=60, min_obs=20), start, days)
        result = run_backtest(strategy, data, BacktestConfig(start, end, 1e7, CostModel(),
                              stamp_exempt=("511010.SH", "518880.SH"),
                              transfer_exempt=("511010.SH", "518880.SH")))
        _etf_cash_guard(result, data, frames)
        return result, None
    if name == "i7_turn_of_month":
        from .ideas_calendar import calendar_holdings
        data, frames = _etfs(stocks, asset, ("510300.SH",))
        hold = calendar_holdings(days, "tom")
        targets = {}
        # Publish known calendar targets one session before CLOSE execution.
        for i in range(len(days) - 2):
            targets[days[i]] = pd.Series({"510300.SH": float(hold.loc[days[i + 2]])})
        costs = CostModel(commission=.00075, transfer=0, stamp_before=0, stamp_after=0, slippage=0)
        result = run_backtest(FixedTargets(targets), data, BacktestConfig(
                              start, end, 1e6, costs, execution="close", stamp_exempt=("510300.SH",)))
        _etf_cash_guard(result, data, frames)
        return result, None
    if name == "cb_double_low":
        data, strategy = bond_market(asset, days, start, end)
        costs = CostModel(commission=.0002, transfer=0, stamp_before=0,
                          stamp_after=0, slippage=.001, lot=10)
        return run_backtest(strategy, data, BacktestConfig(
            start, end, 1e6, costs, fixed_cash_targets=True)), None
    raw, settle, mapping, multiplier, targets = futures_inputs(asset, days, end, start)
    costs = CostModel(commission=.0002, transfer=0, stamp_before=0, stamp_after=0, slippage=0, lot=1)
    return run_futures_account(raw, settle, mapping, multiplier, targets[name],
                              BacktestConfig(start, end, 1e6, costs)), None


def observation_records(identity, dates, days, previous, inputs, mode, now=None):
    """Only a timely session with a prior persisted state can be forward evidence."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    created = datetime.fromisoformat(identity["created_at"].replace("Z", "+00:00")).astimezone(local.tzinfo)
    records = []
    for date in dates:
        prior = days[days < date]
        previous_session = str(prior[-1].date()) if len(prior) else None
        prior_was_committed = any(
            row["date"] == previous_session and
            datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00")).astimezone(local.tzinfo).date() < local.date()
            for row in previous)
        forward = (mode == "daily" and date.date() == local.date() and
                   local.hour >= 18 and created.date() < local.date() and prior_was_committed)
        records.append({"date": str(date.date()),
            "kind": "forward_paper_observation" if forward else "replay",
            "recorded_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "input_version": inputs["version"],
            "manifest_sha256": inputs["identity_sha256"], "code_sha256": identity["code_sha256"],
            "historical_forward_evidence": forward})
    return records


def update(root, source, manifest, names=ACCOUNTS, mode="replay", *, bindings):
    """Replay completely; compare historical prefix before committing any added rows."""
    if mode not in ("daily", "replay"):
        raise ValueError("Observation mode must be daily or replay")
    inputs = load_inputs(manifest)
    end = pd.Timestamp(inputs["usable_date"])
    if end.date() > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("Approved cutoff cannot be in the future")
    days = exchange_days(inputs["calendar"], "SSE", end)
    if end not in days:
        raise ValueError("Approved usable_date is not an exchange session")
    stocks = load_market_data(inputs["panel"], start="2024-01-01", end=end, universe="000906.SH")
    expected = days[(days >= stocks.calendar[0]) & (days <= end)]
    if not stocks.calendar.equals(expected):
        raise ValueError("Panel sessions do not reconcile with exchange calendar through approved cutoff")
    fund = Fundamentals.load(inputs["fundamentals"])
    root = Path(root)
    reports = {}
    code_hash = _source_hash()
    source_reference = None
    with ledger_lock(root):
        owner_bindings = root / "bindings.json"
        if owner_bindings.exists() and json.loads(owner_bindings.read_text()) != bindings:
            raise LedgerMismatch("Account root belongs to another native owner/registered version")
        if not owner_bindings.exists():
            _publish({owner_bindings: json_bytes(bindings)})
        for name in names:
            if name not in ACCOUNTS:
                raise ValueError(f"Unauthorized identity {name}")
            directory = root / name
            try:
                calendar_context = None
                if name == "i7_turn_of_month":
                    calendar_context = i7_calendar_context(
                        inputs["calendar"], inputs["replay_start"], end)
                    calendar_context["calendar_sha256"] = file_hash(inputs["calendar"])
                    if not calendar_context["complete"]:
                        reports[name] = {"state": "pending",
                            "error": calendar_context["reason"],
                            "calendar_context": calendar_context}
                        continue
                if name in ORIGINAL and not (directory / "seal.json").exists():
                    if source_reference is None:
                        from .paper_inception import original_reference
                        source_reference = original_reference(Path(source).parent)
                        content = json_bytes(source_reference)
                        proof = root / "source-inception" / f"{digest(content)}.json"
                        proof.parent.mkdir(parents=True, exist_ok=True)
                        _publish({proof: content})
                identity = _initialize(directory, name, source, inputs, code_hash, bindings,
                                       source_reference=source_reference)
                frozen_input = root / "inputs" / f"{inputs['identity_sha256']}.json"
                frozen_input.parent.mkdir(parents=True, exist_ok=True)
                input_content = Path(inputs["manifest_path"]).read_bytes()
                if frozen_input.exists() and frozen_input.read_bytes() != input_content:
                    raise LedgerMismatch("Stored input manifest tampered")
                if not frozen_input.exists():
                    _publish({frozen_input: input_content})
                result, expected_meta = _result(name, identity, inputs, days, stocks, fund)
                if (not np.isfinite(result.nav).all() or (result.nav <= 0).any() or
                        not np.isfinite(result.cash).all() or
                        not np.isfinite(result.positions.to_numpy()).all() or
                        not np.isfinite(result.trades[["shares", "price", "value", "fee"]].to_numpy(dtype=float)).all() or
                        (result.trades[["shares", "price", "value"]] <= 0).any().any() or
                        (result.trades.fee < 0).any()):
                    raise ValueError("Invalid real ledger valuation, execution quote or fee")
                if result.nav.empty or result.nav.index[-1] != end:
                    raise ValueError("Account cannot reach approved usable cutoff")
                if name in ORIGINAL:
                    _inception_gate(directory, name, result, inputs, code_hash)
                # Build and validate in isolation. No partial in-place multi-file append.
                with tempfile.TemporaryDirectory(prefix=".paper-stage-", dir=root) as temp:
                    stage = Path(temp)
                    for file in FILES:
                        if (directory / file).exists():
                            shutil.copyfile(directory / file, stage / file)
                    if expected_meta is not None:
                        init_account(stage, expected_meta)
                    info = append_ledger(stage, result)
                    contents = {file: (stage / file).read_bytes() for file in FILES
                                if not (directory / file).exists() or
                                (stage / file).read_bytes() != (directory / file).read_bytes()}
                signal_rows = [{"date": str(t.date()), "weights": {
                    code: float(weight) for code, weight in row.items() if weight != 0}}
                    for t, row in result.signals.iterrows()]
                old_signals = [json.loads(line) for line in
                    (directory / "signals.jsonl").read_text().splitlines()]
                if signal_rows[:len(old_signals)] != old_signals:
                    raise LedgerMismatch(f"{name}: historical signals changed")
                added_signals = signal_rows[len(old_signals):]
                if added_signals:
                    contents["signals.jsonl"] = (directory / "signals.jsonl").read_bytes() + b"".join(
                        json.dumps(row, sort_keys=True).encode() + b"\n" for row in added_signals)
                if info["new_dates"] or added_signals:
                    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    previous_observations = [json.loads(line) for line in
                        (directory / "observations.jsonl").read_text().splitlines()]
                    records = observation_records(identity, info["new_dates"], days,
                        previous_observations, inputs, mode)
                    observations = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n"
                                            for row in records)
                    contents["observations.jsonl"] = (directory / "observations.jsonl").read_bytes() + observations
                    daily_reconciliation = []
                    observation_kinds = {row["date"]: row["kind"] for row in previous_observations + records}
                    for t in result.nav.index:
                        dated_trades = result.trades.loc[result.trades.date.eq(t)]
                        weights = result.target.loc[t].dropna().to_dict() if t in result.target.index else {}
                        holdings = result.positions.loc[t]
                        holdings = {c: float(q) for c, q in holdings.items() if q}
                        daily_reconciliation.append({
                            "date": str(t.date()), "cash": float(result.cash.loc[t]),
                            "nav": float(result.nav.loc[t]), "holdings": holdings,
                            "fees": float(dated_trades.fee.sum()),
                            "trades": json.loads(dated_trades.to_json(orient="records", date_format="iso")),
                            "execution_targets": weights,
                            "signal": next((s["weights"] for s in signal_rows if s["date"] == str(t.date())), None),
                            "exchange_session": t in days,
                            "observation_kind": observation_kinds.get(str(t.date())),
                            "source_state": ("byte_preserved_reconciled" if str(t.date()) in identity.get("source_dates", [])
                                             else "no_source_observation"),
                        })
                    reconciliation = {"recorded_at": now, "cutoff": str(end.date()),
                        "kind": mode, "input_version": inputs["version"],
                        "manifest_sha256": inputs["identity_sha256"], "calendar_sha256": file_hash(inputs["calendar"]),
                        "calendar_context": calendar_context,
                        "source_prefix_preserved": name in ORIGINAL,
                        "source_files": identity["source_files"],
                        "historical_prefix_replay_match": True,
                        "compared": ["cash", "nav", "positions", "trades", "fees", "targets", "calendar", "code_version"],
                        "new_dates": [str(t.date()) for t in info["new_dates"]],
                        "daily": daily_reconciliation,
                        "ledger_hashes": _seal(contents, directory)}
                    contents["reconciliation.jsonl"] = (directory / "reconciliation.jsonl").read_bytes() + json.dumps(
                        reconciliation, sort_keys=True).encode() + b"\n"
                    contents["seal.json"] = json_bytes(_seal(contents, directory))
                    _transaction(directory, contents)
                reports[name] = {"state": "reconciled", "last_date": str(end.date()),
                                 "new_sessions": len(info["new_dates"])}
                if calendar_context is not None:
                    reports[name]["calendar_context"] = calendar_context
            except (OSError, ValueError, KeyError, LedgerMismatch) as exc:
                reports[name] = {"state": "blocked", "error": str(exc)}
        _publish({root / "last_run.json": json_bytes({"accounts": reports,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "disclaimer": DISCLAIMER})})
    return reports


def snapshot(root):
    """Read-only, shared-locked API view; report missing/blocked accounts, never zero ledgers."""
    root = Path(root)
    result = []
    if not (root / ".paper.lock").exists():
        return {"accounts": [{"name": name, "state": "not_initialized", "spec": frozen_specs()[name]}
                             for name in ACCOUNTS], "scheduler": None}
    with ledger_lock(root, exclusive=False):
        last_run = json.loads((root / "last_run.json").read_text()) if (root / "last_run.json").exists() else {}
        scheduler = json.loads((root / "tick.json").read_text()) if (root / "tick.json").exists() else None
        for name in ACCOUNTS:
            directory = root / name
            item = {"name": name, "spec": frozen_specs()[name], "disclaimer": DISCLAIMER,
                    "run": last_run.get("accounts", {}).get(name),
                    "schedule": (scheduler or {}).get("accounts", {}).get(name)}
            if not directory.exists():
                item["state"] = "not_initialized"
                result.append(item)
                continue
            try:
                if (directory / "pending.json").exists():
                    raise LedgerMismatch("Interrupted transaction; resume daily command before reading")
                _assert_seal(directory)
                if name in ORIGINAL:
                    seal = json.loads((directory / "seal.json").read_text())
                    if not {"inception_source.json", "inception_reconciliation.jsonl"}.issubset(seal):
                        raise LedgerMismatch("Original pending signal source proof is missing")
                    item["inception_reconciliation"] = [
                        json.loads(line) for line in (directory / "inception_reconciliation.jsonl").read_text().splitlines()]
                item["identity"] = json.loads((directory / "identity.json").read_text())
                item["meta"] = json.loads((directory / "meta.json").read_text())
                ledger = read_ledger(directory)
                nav = ledger["nav"].reset_index()
                records = lambda frame: json.loads(frame.to_json(orient="records", date_format="iso"))
                item.update(state="persisted",
                    nav=records(nav), positions=records(ledger["positions"]), trades=records(ledger["trades"]),
                    targets=records(ledger["targets"]),
                    signals=[json.loads(line) for line in (directory / "signals.jsonl").read_text().splitlines()],
                    observations=[json.loads(line) for line in (directory / "observations.jsonl").read_text().splitlines()],
                    reconciliation=[json.loads(line) for line in (directory / "reconciliation.jsonl").read_text().splitlines()])
            except (OSError, ValueError, LedgerMismatch) as exc:
                item.update(state="blocked", error=str(exc))
            result.append(item)
    return {"accounts": result, "scheduler": scheduler}
