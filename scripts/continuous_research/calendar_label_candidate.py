"""Offline calendar-label-candidate-v1; never used by the current loader/worker.

Rows supply symbol, date, close and price_contract (valid/invalid/unknown).
The caller's price-contract declaration is not proof of source availability.
The explicit calendar is authoritative only for this calculation, not verified
against an exchange. Lag and holding horizon are both fixed at one market step.
"""
from collections import Counter, defaultdict
from datetime import date
from math import isfinite

CANDIDATE_ID = "calendar-label-candidate-v1"


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected a canonical YYYY-MM-DD date")
    return value


def _raw(value):
    return str(value) if isinstance(value, float) and not isfinite(value) else value


def calendar_labels(rows, calendar):
    """Return every supplied signal row, explicit exclusions and rank accounting.

    No price fill, per-symbol date shift, suspension inference or IO is allowed.
    Missing price_contract is unknown, never implicitly admitted. Availability
    stays unknown because this function cannot establish historical publication.
    """
    calendar = [_date(day) for day in calendar]
    if not calendar or calendar != sorted(set(calendar)):
        raise ValueError("Calendar must be nonempty, strictly ordered and unique")
    positions = {day: index for index, day in enumerate(calendar)}
    observations = {}
    for row in rows:
        symbol, day = row["symbol"], _date(row["date"])
        if not isinstance(symbol, str) or not symbol or day not in positions:
            raise ValueError("Each observation requires a symbol and calendar date")
        key = symbol, day
        if key in observations:
            raise ValueError("Duplicate symbol/date observation")
        if row.get("price_contract", "unknown") not in {"valid", "invalid", "unknown"}:
            raise ValueError("Unknown price_contract declaration")
        observations[key] = row

    def endpoint(symbol, day, role):
        if day is None:
            return None, None, f"{role}_outside_calendar"
        observation = observations.get((symbol, day))
        if observation is None:
            return None, None, f"{role}_missing_observation"
        raw = observation.get("close")
        contract = observation.get("price_contract", "unknown")
        if contract != "valid":
            return _raw(raw), None, f"{role}_price_contract_{contract}"
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError):
            value = float("nan")
        if isinstance(raw, bool) or not isfinite(value) or value <= 0:
            return _raw(raw), None, f"{role}_close_not_finite_positive"
        return _raw(raw), value, None

    output = []
    for (symbol, day), observation in sorted(observations.items()):
        index = positions[day]
        entry_day = calendar[index + 1] if index + 1 < len(calendar) else None
        exit_day = calendar[index + 2] if index + 2 < len(calendar) else None
        entry_raw, entry, entry_error = endpoint(symbol, entry_day, "entry")
        exit_raw, exit_value, exit_error = endpoint(symbol, exit_day, "exit")
        reasons = [reason for reason in (entry_error, exit_error) if reason]
        raw_return = None if reasons else exit_value / entry - 1.0
        if raw_return is not None and not isfinite(raw_return):
            reasons.append("return_not_finite")
            raw_return = None
        output.append({
            "symbol": symbol, "signal_date": day,
            "signal_close_raw": _raw(observation.get("close")),
            "entry_date": entry_day, "exit_date": exit_day,
            "entry_close_raw": entry_raw, "exit_close_raw": exit_raw,
            "entry_close": entry, "exit_close": exit_value,
            "raw_return": raw_return, "valid_label": not reasons,
            "exclusion_reasons": reasons, "rank_label": None,
            "rank_count": 0, "rank_dependency_end": None,
            "source_availability": "unknown",
        })

    by_day = defaultdict(list)
    for row in output:
        by_day[row["signal_date"]].append(row)
    rank_ledger = []
    for day, group in sorted(by_day.items()):
        valid = [row for row in group if row["valid_label"]]
        values = sorted(row["raw_return"] for row in valid)
        dependency = max((row["exit_date"] for row in valid), default=None)
        for row in group:
            row["rank_count"] = len(valid)
            row["rank_dependency_end"] = dependency
            if row["valid_label"]:
                ranks = [i + 1 for i, value in enumerate(values) if value == row["raw_return"]]
                row["rank_label"] = sum(ranks) / len(ranks) / len(valid) - 0.5
        rank_ledger.append({
            "signal_date": day, "observed_signal_rows": len(group),
            "rank_count": len(valid), "excluded_rows": len(group) - len(valid),
            "exclusion_reason_counts": dict(Counter(
                reason for row in group for reason in row["exclusion_reasons"])),
            "rank_dependency_end": dependency, "source_availability": "unknown",
        })
    return {"candidate_id": CANDIDATE_ID, "calendar": calendar,
            "lag_market_steps": 1, "holding_market_steps": 1,
            "rows": output, "rank_ledger": rank_ledger,
            "source_availability": "unknown"}


def purge_ledger(result, segment_end):
    """Separate invalid labels from valid labels whose rank dependency is late."""
    segment_end = _date(segment_end)
    if segment_end not in result["calendar"]:
        raise ValueError("Segment end must be in the explicit calendar")
    ledger = []
    for row in result["rows"]:
        if row["signal_date"] > segment_end:
            continue
        status = ("invalid_label" if not row["valid_label"] else
                  "purged_dependency" if row["rank_dependency_end"] > segment_end else "kept")
        ledger.append({"symbol": row["symbol"], "signal_date": row["signal_date"],
                       "status": status, "rank_dependency_end": row["rank_dependency_end"]})
    return {"segment_end": segment_end, "rows": ledger,
            "counts": dict(Counter(row["status"] for row in ledger))}
