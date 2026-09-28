"""Bounded evidence check on the existing five-date invented input, no providers.

Run with --fixture E0600/clock-semantics-artificial-input.json
--old-output E0600/clock-semantics-output-final --output E0700/candidate-result.json.
Only the explicit output file is written; importing this module does no work.
"""
import argparse
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path

from calendar_label_candidate import calendar_labels, purge_ledger


def verify(fixture_path, old_output):
    fixture = json.loads(fixture_path.read_text())
    calendar = sorted({row["date"] for row in fixture["rows"]})
    assert calendar == ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]
    cases = {}
    inputs = {}
    for mode, presence in [("complete", "present_in_complete"),
                           ("single_missing_observation", "present_in_missing")]:
        # Contract-valid is an explicit declaration for these invented prices,
        # not a claim that their real historical publication time is known.
        rows = [{"symbol": row["symbol"], "date": row["date"],
                 "close": row["close_decimal"], "price_contract": "valid"}
                for row in fixture["rows"] if row[presence]]
        inputs[mode] = rows
        result = calendar_labels(rows, calendar)
        result["purge"] = purge_ledger(result, "2026-03-04")
        old_path = old_output / f"{mode}-loaded.csv"
        old = list(csv.DictReader(old_path.open()))
        result["old_observation_baseline"] = {"sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(), "rows": old}
        cases[mode] = result

    def row(case, symbol, day="2026-03-02"):
        return next(row for row in cases[case]["rows"] if (row["symbol"], row["signal_date"]) == (symbol, day))

    a, b = row("complete", "SH609991"), row("complete", "SZ009991")
    assert (a["entry_date"], a["exit_date"], a["rank_dependency_end"]) == ("2026-03-03", "2026-03-04", "2026-03-04")
    assert abs(a["raw_return"] - 0.1) < 1e-12 and (a["rank_label"], b["rank_label"]) == (0.5, 0)
    assert sum(row["valid_label"] for row in cases["complete"]["rows"]) == 6
    # Complete-input candidate must equal every old actual loader rank/end row.
    for old in cases["complete"]["old_observation_baseline"]["rows"]:
        actual = row("complete", old["symbol"], old["trade_date"])
        assert (actual["rank_label"], actual["rank_dependency_end"]) == (float(old["label"]), old["_label_end_date"])

    missing_a, missing_b = row("single_missing_observation", "SH609991"), row("single_missing_observation", "SZ009991")
    assert (missing_a["entry_date"], missing_a["exit_date"]) == ("2026-03-03", "2026-03-04")
    assert missing_a["exclusion_reasons"] == ["entry_missing_observation"] and missing_a["raw_return"] is None
    assert missing_a["entry_close_raw"] is None and missing_a["exit_close_raw"] == "110"
    assert missing_b["raw_return"] == b["raw_return"]
    assert (missing_b["rank_count"], missing_b["rank_label"], missing_b["rank_dependency_end"]) == (1, 0.5, "2026-03-04")
    assert sum(row["valid_label"] for row in cases["single_missing_observation"]["rows"]) == 4
    old_missing_b = next(row for row in cases["single_missing_observation"]["old_observation_baseline"]["rows"] if row["symbol"] == "SZ009991" and row["trade_date"] == "2026-03-02")
    assert (float(old_missing_b["label"]), old_missing_b["_label_end_date"]) == (0, "2026-03-05")
    assert cases["complete"]["purge"]["counts"] == {"kept": 2, "purged_dependency": 4}
    assert cases["single_missing_observation"]["purge"]["counts"] == {"invalid_label": 1, "purged_dependency": 3, "kept": 1}
    assert all(row["source_availability"] == "unknown" for case in cases.values() for row in case["rows"])

    boundary_checks = []
    for close in [0, -1, float("nan"), float("inf"), None, True]:
        bad = deepcopy(inputs["complete"])
        next(row for row in bad if row["symbol"] == "SH609991" and row["date"] == "2026-03-03")["close"] = close
        rejected = next(row for row in calendar_labels(bad, calendar)["rows"] if row["symbol"] == "SH609991" and row["signal_date"] == "2026-03-02")
        assert rejected["exclusion_reasons"] == ["entry_close_not_finite_positive"] and rejected["rank_label"] is None
        boundary_checks.append({"invalid_entry_close": str(close), "rejected": True})
    unknown = deepcopy(inputs["complete"])
    next(row for row in unknown if row["symbol"] == "SH609991" and row["date"] == "2026-03-03").pop("price_contract")
    assert next(row for row in calendar_labels(unknown, calendar)["rows"] if row["symbol"] == "SH609991" and row["signal_date"] == "2026-03-02")["exclusion_reasons"] == ["entry_price_contract_unknown"]
    for invalid_calendar in [[], calendar[::-1], calendar + [calendar[-1]], ["2026-02-30"]]:
        try:
            calendar_labels(inputs["complete"], invalid_calendar)
        except ValueError:
            boundary_checks.append({"invalid_calendar": invalid_calendar, "rejected": True})
        else:
            raise AssertionError("Invalid calendar was accepted")
    return {"status": "passed", "scope": "synthetic offline candidate only; not execution, training, real-data admission or independent acceptance",
            "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            "cases": cases, "boundary_checks": boundary_checks, "unknown_price_contract_excluded": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--old-output", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.fixture, args.old_output)
    with args.output.open("x") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"status": result["status"], "cases": {name: {"valid_labels": sum(row["valid_label"] for row in case["rows"]), "purge": case["purge"]["counts"]} for name, case in result["cases"].items()}, "boundary_checks": len(result["boundary_checks"])}, ensure_ascii=False))
