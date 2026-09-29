"""Bounded, read-only views of owned, registered ETF development runs.

Metadata is checked before result_json is selected. No model-supplied paths,
SQL, arbitrary JSON keys, or stock/factor results are accepted.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from datetime import date
from pathlib import Path

from sqlalchemy import text

from backend.shared.stock_utils import StockCodeUtil
from backend.shared.utils import normalize_user_id
from scripts.continuous_research.review_packets import validate_run


VIEWS = {"overview", "nav", "decisions", "orders", "fills"}
_ID = re.compile(r"r01bt-[0-9a-f]{32}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_.:/|+-]{1,256}\Z")
_ORIGINAL_FIELDS = {
    "equity_curve",
    "drawdown_curve",
    "trades",
    "positions",
    "ledger_view",
    "ledger_evidence",
    "strategy_decisions",
}


def _fail(reason):
    raise ValueError("evidence_" + reason)


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            _fail("invalid_json")
    if not isinstance(value, dict):
        _fail("invalid_object")
    return value


def _date(value):
    if not isinstance(value, str):
        _fail("invalid_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("invalid_date")
    if parsed.isoformat() != value:
        _fail("invalid_date")
    return value


def _hash(value):
    try:
        raw = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        _fail("non_json_source")
    return hashlib.sha256(raw).hexdigest()


def _symbols(value, allowed):
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(x, str) for x in value)
        or len(set(value)) != len(value)
        or not set(value) <= allowed
    ):
        _fail("symbols_outside_contract")
    return set(value)


def _project(row, numbers=(), labels=(), booleans=()):
    if not isinstance(row, dict):
        _fail("invalid_row")
    out = {}
    for key in numbers:
        if key not in row:
            continue
        value = row[key]
        if value is not None:
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            if not valid:
                _fail("invalid_numeric_field")
        out[key] = value
    for key in labels:
        if key not in row:
            continue
        value = row[key]
        if value is not None and (
            not isinstance(value, str) or not _LABEL.fullmatch(value)
        ):
            _fail("invalid_label_field")
        out[key] = value
    for key in booleans:
        if key in row:
            if row[key] is not None and type(row[key]) is not bool:
                _fail("invalid_boolean_field")
            out[key] = row[key]
    return out


def _rows(value):
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        _fail("missing_original_rows")
    return value


def _trade_date(row, field, start, end):
    day = _date(row.get(field))
    if not start <= day <= end:
        _fail("result_outside_run_dates")
    return day


def _prior_date(row, key, day):
    # Entry signals legitimately use the session before the first execution.
    if row.get(key) is not None and _date(row[key]) > day:
        _fail("future_signal_or_mark")


def _registered_experiment(c, bid):
    found = []
    for task in c["tasks"].values():
        for exp in task.get("experiments", {}).values():
            if exp.get("backtest_id") != bid:
                continue
            if task.get("kind") != "research" or exp.get("action") != "experiment":
                _fail("etf_experiment_required")
            found.append(exp)
    if not found:
        _fail("unregistered_backtest")
    identities = [
        {
            k: e.get(k)
            for k in (
                "strategy_id",
                "revision_id",
                "code",
                "parameters",
                "start_date",
                "end_date",
            )
        }
        for e in found
    ]
    if any(x != identities[0] for x in identities[1:]):
        _fail("ambiguous_registration")
    exp = found[0]
    if not isinstance(exp.get("code"), str) or not 1 <= len(exp["code"]) <= 64000:
        _fail("registered_code_required")
    if not exp.get("strategy_id") or not exp.get("revision_id"):
        _fail("registered_version_required")
    return exp


def _validate_config(cfg, exp, c, ident):
    contract = c["contract"]
    if cfg.get("executor_kind") != "r01_ledger":
        _fail("etf_executor_required")
    binding = _object(cfg.get("data_binding"))
    validate_run("completed", cfg, exp, c, ident)
    if cfg.get("research_case_id") != ident:
        _fail("programme_mismatch")
    if cfg.get("validation_status") != "development_only":
        _fail("development_run_required")
    start, end = _date(cfg.get("start_date")), _date(cfg.get("end_date"))
    if not contract["start_date"] <= start <= end <= contract["end_date"]:
        _fail("run_outside_contract")
    if (start, end) != (exp.get("start_date"), exp.get("end_date")):
        _fail("registered_dates_mismatch")
    if _date(binding.get("development_end")) != contract["end_date"]:
        _fail("development_boundary_mismatch")
    if not isinstance(binding.get("package_id"), str) or not binding["package_id"]:
        _fail("package_identity_required")
    return start, end


def _published_parameters(parameters):
    """Mirror only public.publish's frozen symbol/weight normalization.

    Other parameter keys and values remain exact; no metadata keys are added.
    The registered experiment itself must keep its original hash and ordering.
    """
    normalized = copy.deepcopy(_object(parameters))
    try:
        normalized["symbols"] = sorted(
            {StockCodeUtil.to_suffix(s) for s in normalized["symbols"]}
        )
        if "target_weights" in normalized:
            normalized["target_weights"] = {
                StockCodeUtil.to_suffix(s): float(weight)
                for s, weight in normalized["target_weights"].items()
            }
    except (KeyError, TypeError, ValueError, AttributeError):
        _fail("invalid_registered_parameters")
    return normalized


def _validate_summary(result, cfg, exp, c, ident, auth, bid):
    if (
        result.get("backtest_id") != bid
        or result.get("status") != "completed"
        or str(result.get("tenant_id")) != str(auth.tenant_id)
        or result.get("user_id") is None
        or normalize_user_id(result["user_id"]) != normalize_user_id(auth.user_id)
    ):
        _fail("result_owner_or_run_mismatch")
    rc = _object(result.get("config"))
    _validate_config(rc, exp, c, ident)
    for key in (
        "executor_kind",
        "strategy_id",
        "strategy_revision",
        "strategy_version",
        "research_id",
        "research_case_id",
        "start_date",
        "end_date",
        "code_sha256",
        "data_binding",
        "validation_status",
    ):
        if rc.get(key) != cfg.get(key):
            _fail("result_config_mismatch")
    if _hash(_object(rc.get("parameters"))) != _hash(
        _published_parameters(exp["parameters"])
    ):
        _fail("result_parameters_mismatch")
    return rc


def _local_result_location(bid, auth):
    # Reuse the existing server-selected root/naming without constructing the
    # persistence service (its constructor creates directories and configures COS).
    from backend.services.engine.qlib_app.services.backtest_persistence import (
        BacktestPersistence,
    )

    storage = object.__new__(BacktestPersistence)
    storage._local_result_root = storage._resolve_local_result_root()
    target = storage._build_local_result_path(
        bid, normalize_user_id(auth.user_id), auth.tenant_id
    )
    return storage._local_result_root, target


def _read_originals(file_path, bid, auth):
    root, target = _local_result_location(bid, auth)
    root, target = Path(root), Path(target)
    if not isinstance(file_path, str) or Path(file_path) != target:
        _fail("noncanonical_original_path")
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        _fail("original_path_outside_root")
    if len(parts) != 3 or any(p in {"", ".", ".."} for p in parts):
        _fail("original_path_outside_root")
    # Open each server-derived component without following links. A swapped
    # directory cannot redirect a later relative open outside these descriptors.
    handles = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        handles.append(os.open(root, flags))
        for component in parts[:-1]:
            handles.append(os.open(component, flags, dir_fd=handles[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=handles[-1])
        handles.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
            _fail("invalid_original_file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        after = os.fstat(fd)
        linked = os.stat(parts[-1], dir_fd=handles[-2], follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(raw) != before.st_size
            or any(getattr(before, k) != getattr(after, k) for k in fields)
            or any(getattr(after, k) != getattr(linked, k) for k in fields)
        ):
            _fail("original_changed_during_read")
        payload = _object(raw.decode("utf-8"))
        if set(payload) - _ORIGINAL_FIELDS:
            _fail("unexpected_original_fields")
        return payload, raw, str(target)
    except (OSError, UnicodeError):
        _fail("original_file_unavailable_or_symlink")
    finally:
        for fd in reversed(handles):
            os.close(fd)


def _validate_result(result, cfg, exp, c, ident, auth, bid, allowed):
    rc = _validate_summary(result, cfg, exp, c, ident, auth, bid)
    evidence = _object(result.get("ledger_evidence"))
    session, package = (
        _object(evidence.get("session")),
        _object(evidence.get("package")),
    )
    manifest = c["contract"]["input_manifest_sha256"]
    binding = cfg["data_binding"]
    if (
        session.get("manifest_sha256") != manifest
        or package.get("manifest_sha256") != manifest
        or package.get("package_id") != binding["package_id"]
        or session.get("input_package_id") != binding["package_id"]
        or session.get("is_fixture") is not False
        or package.get("is_fixture") is not False
        or session.get("strategy_id") != f"s{cfg['strategy_id']}-{bid}"
        or session.get("strategy_version") != cfg.get("strategy_version")
        or not session.get("ledger_run_id")
        or session.get("ledger_run_id") != rc.get("ledger_run_id")
        or (session.get("match_assumptions") or {}).get("asset_type") != "etf"
    ):
        _fail("ledger_source_identity_mismatch")
    _symbols(package.get("symbols"), allowed)
    view = _object(result.get("ledger_view"))
    if (view.get("package") or {}).get("manifest_sha256") != manifest or (
        view.get("session") or {}
    ).get("ledger_run_id") != session["ledger_run_id"]:
        _fail("view_source_identity_mismatch")
    start, end = cfg["start_date"], cfg["end_date"]
    for row in _rows(view.get("days")):
        _trade_date(row, "date", start, end)
    for key in ("equity_curve", "drawdown_curve"):
        for row in _rows(result.get(key)):
            _trade_date(row, "date", start, end)
    stats = _object(result.get("advanced_stats") or {})
    if stats.get("actual_max_input_date") is not None:
        if _date(stats["actual_max_input_date"]) > end:
            _fail("result_input_after_boundary")
    if stats.get("read_through") is not None and stats["read_through"] != end:
        _fail("result_read_boundary_mismatch")
    return evidence, session["ledger_run_id"]


def _original_views(result, evidence, ledger_id, symbols, start, end):
    views = {"nav": [], "decisions": [], "orders": [], "fills": []}
    for row in _rows(evidence.get("equity")):
        day = _trade_date(row, "trade_date", start, end)
        out = _project(
            row,
            (
                "cash",
                "dividend_receivable",
                "market_value",
                "nav",
                "nav_exact",
                "fees_today",
                "realized_pnl_today",
                "high_water_mark",
            ),
            ("risk_status",),
            ("valuation_reliable",),
        )
        out["trade_date"] = day
        positions = _object(row.get("positions"))
        out["positions"] = []
        for symbol, pos in sorted(positions.items()):
            pos = _object(pos)
            if symbol not in symbols or pos.get("symbol") != symbol:
                _fail("result_symbol_outside_experiment")
            # Pending T+1 dates may be after this mark and are not projected.
            _prior_date(pos, "last_mark_date", day)
            item = _project(
                pos,
                (
                    "qty",
                    "avg_cost",
                    "available_qty",
                    "pending_t1_qty",
                    "last_mark",
                    "stale_days",
                    "close",
                    "market_value",
                ),
                ("symbol", "mark_source", "last_mark_date"),
            )
            out["positions"].append(item)
        views["nav"].append(out)
    for row in _rows(result.get("strategy_decisions")):
        day = _trade_date(row, "execution_date", start, end)
        decision_date = _date(row.get("decision_date"))
        if decision_date >= day:
            _fail("decision_not_before_execution")
        targets = row.get("targets")
        if targets is not None:
            targets = _object(targets)
            if not set(targets) <= symbols:
                _fail("result_symbol_outside_experiment")
            targets = _project(targets, tuple(targets))
        views["decisions"].append(
            {"execution_date": day, "decision_date": decision_date, "targets": targets}
        )
    for row in _rows(evidence.get("orders")):
        day = _trade_date(row, "trade_date", start, end)
        if row.get("symbol") not in symbols or row.get("ledger_run_id") != ledger_id:
            _fail("order_source_identity_mismatch")
        _prior_date(row, "signal_date", day)
        out = _project(
            row,
            (
                "qty_target",
                "qty_filled",
                "qty_remaining",
                "avg_fill_price",
                "fees",
                "realized_pnl",
                "ideal_weight",
                "realized_weight",
            ),
            (
                "client_order_id",
                "symbol",
                "side",
                "origin",
                "status",
                "reject_reason",
                "signal_date",
            ),
        )
        out["trade_date"] = day
        views["orders"].append(out)
        for fill in _rows(row.get("fills")):
            fill_day = _trade_date(fill, "trade_date", start, end)
            if (
                fill_day != day
                or fill.get("symbol") != row["symbol"]
                or fill.get("side") != row.get("side")
            ):
                _fail("fill_source_identity_mismatch")
            _prior_date(fill, "signal_date", fill_day)
            item = _project(
                fill,
                (
                    "price",
                    "quantity",
                    "commission",
                    "stamp_duty",
                    "transfer_fee",
                    "total_fee",
                    "total_fee_exact",
                    "slippage_bps",
                ),
                ("symbol", "side", "signal_date", "price_source"),
            )
            item.update(trade_date=fill_day, order_id=out["client_order_id"])
            views["fills"].append(item)
    return views


async def inspect_evidence(ident, c, t, request, auth, db):
    """Return one deterministic page; failures raise stable ValueError codes."""
    if not isinstance(request, dict) or set(request) - {
        "action",
        "backtest_id",
        "view",
        "offset",
        "limit",
        "start_date",
        "end_date",
    }:
        _fail("invalid_request")
    bid, view = request.get("backtest_id"), request.get("view")
    if (
        request.get("action") != "inspect_evidence"
        or not isinstance(view, str)
        or view not in VIEWS
    ):
        _fail("invalid_view")
    if not isinstance(bid, str) or not _ID.fullmatch(bid):
        _fail("etf_backtest_id_required")
    if t.get("kind") not in {"research", "evidence_review"}:
        _fail("task_kind_denied")
    if t["kind"] == "evidence_review":
        allowed_ids = (t.get("evidence") or {}).get("allowed_backtest_ids")
        if not isinstance(allowed_ids, list) or bid not in allowed_ids:
            _fail("review_backtest_not_authorized")
    offset, limit = request.get("offset", 0), request.get("limit", 80)
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 120
    ):
        _fail("invalid_pagination")
    contract = c["contract"]
    begin = _date(request.get("start_date", contract["start_date"]))
    finish = _date(request.get("end_date", contract["end_date"]))
    if (
        not _date(contract["start_date"])
        <= begin
        <= finish
        <= _date(contract["end_date"])
    ):
        _fail("request_outside_contract")
    exp = _registered_experiment(c, bid)
    symbols = _symbols(
        _object(exp.get("parameters")).get("symbols"), set(contract["symbols"])
    )
    query = {
        "id": bid,
        "tenant": auth.tenant_id,
        "user": normalize_user_id(auth.user_id),
    }
    row = (
        await db.execute(
            text(
                "SELECT status,config_json FROM qlib_backtest_runs "
                "WHERE backtest_id=:id AND tenant_id=:tenant AND user_id=:user"
            ),
            query,
        )
    ).first()
    if not row:
        _fail("owned_run_missing")
    if row[0] != "completed":
        _fail("completed_run_required")
    cfg = _object(row[1])
    start, end = _validate_config(cfg, exp, c, ident)
    row = (
        await db.execute(
            text(
                "SELECT result_json,result_file_path FROM qlib_backtest_runs "
                "WHERE backtest_id=:id AND tenant_id=:tenant AND user_id=:user "
                "AND status='completed' AND config_json=CAST(:config AS jsonb)"
            ),
            {**query, "config": json.dumps(cfg, ensure_ascii=False, allow_nan=False)},
        )
    ).first()
    if not row:
        _fail("run_changed_during_read")
    summary = _object(row[0])
    _validate_summary(summary, cfg, exp, c, ident, auth, bid)
    result = dict(summary)
    file_source = None
    if row[1] is not None:
        original, raw, original_path = _read_originals(row[1], bid, auth)
        if any(
            k in summary and summary[k] is not None and summary[k] != v
            for k, v in original.items()
        ):
            _fail("inline_original_mismatch")
        result.update(original)
        file_source = (original_path, raw)
    evidence, ledger_id = _validate_result(
        result, cfg, exp, c, ident, auth, bid, set(contract["symbols"])
    )
    views = _original_views(result, evidence, ledger_id, symbols, start, end)
    metadata = {
        "backtest_id": bid,
        "strategy_id": cfg["strategy_id"],
        "revision_id": cfg["strategy_revision"],
        "code_sha256": cfg["code_sha256"],
        "input_manifest_sha256": contract["input_manifest_sha256"],
        "start_date": start,
        "end_date": end,
        "symbols": sorted(symbols),
        "executor_kind": "r01_ledger",
        "validation_status": "development_only",
    }
    if view == "overview":
        rows = [
            {
                "code": exp["code"],
                "parameters": copy.deepcopy(exp["parameters"]),
                "counts": {k: len(v) for k, v in views.items()},
            }
        ]
    else:
        field = "execution_date" if view == "decisions" else "trade_date"
        rows = [r for r in views[view] if begin <= r[field] <= finish]
    page = rows[offset : offset + limit]
    packet = {
        "backtest_id": bid,
        "view": view,
        "boundary": contract["end_date"],
        "metadata": metadata,
        "date_filter": {"start_date": begin, "end_date": finish},
        "sources": [
            {"path": f"db:qlib_backtest_runs/{bid}/config_json", "sha256": _hash(cfg)},
            {
                "path": f"db:qlib_backtest_runs/{bid}/result_json",
                "sha256": _hash(summary),
            },
            {
                "path": f"db:research_drafts/{ident}/continuous/registered_experiments/{bid}",
                "sha256": _hash(exp),
            },
        ],
        "checks": [
            "owned_completed_run",
            "registered_etf_version",
            "config_read_fence",
            "development_dates",
            "ledger_source_identity",
            "allowlisted_page",
        ],
        "limitations": [
            "Development evidence only; not holdout or independent strategy acceptance.",
            "DB hashes use canonical JSON; local file hashes use exact bytes. No provider transport is included.",
            "Rows preserve original order; total is after date filtering; next_offset=null means this view is exhausted.",
            "Reason, arbitrary strategy state, advanced_stats and historical narrative are omitted. Signals can precede the first execution date.",
        ],
        "offset": offset,
        "limit": limit,
        "total": len(rows),
        "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
        "rows": page,
    }
    if file_source:
        packet["sources"].append(
            {
                "path": file_source[0],
                "sha256": hashlib.sha256(file_source[1]).hexdigest(),
                "hash_basis": "exact_original_file_bytes",
            }
        )
    packet["sha256"] = _hash(packet)
    packet["id"] = "etf-evidence-" + packet["sha256"][:32]
    return packet
