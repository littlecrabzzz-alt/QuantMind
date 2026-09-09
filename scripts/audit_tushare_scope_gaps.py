"""Offline catalog/runtime comparison. No provider, database or live config access."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import CONTRACTS  # noqa: E402
from backend.shared.tushare_portfolio_read_contracts import PORTFOLIO_READ_CONTRACTS  # noqa: E402
from backend.shared.tushare_realtime_extra_contracts import ADJACENT_API_OBLIGATIONS  # noqa: E402
from backend.shared.tushare_registry import EXTENDED_CONTRACTS  # noqa: E402
from backend.shared.tushare_store import KEYS  # noqa: E402

PUBLIC_BLOCKED = {"moneyflow_hsgt", "ggt_top10", "ggt_daily", "ggt_monthly"}
MUTATIONS = {"p_save", "p_delete"}
SDK = {"pro_bar"}


def names(entry):
    # Acquisition names intentionally replace the six financial aliases.
    return entry.get("acquisition_api_names", entry.get("api_names", []))


def audit(ledger, extended, legacy, reader_keys, pure, adjacent):
    pages = ledger["entries"] + ledger.get("discovered_entries", [])
    source_names = {name for entry in pages for name in names(entry)}
    scope = source_names | set(adjacent)
    registered = set(extended) | set(legacy)
    rows = []
    for api in sorted(scope | registered):
        is_registered = api in registered
        if is_registered:
            state = "runtime_readable" if api in reader_keys else "registered_reader_missing"
        elif api in MUTATIONS:
            state = "excluded_mutation"
        elif api in SDK:
            state = "sdk_only"
        elif api in pure:
            state = "pure_contract_only_private"
        elif api in PUBLIC_BLOCKED:
            state = "public_read_only_contract_blocked"
        else:
            state = "unclassified_named_obligation"
        entries = [e for e in pages if api in names(e)]
        spec = extended.get(api, pure.get(api, {}))
        rows.append({
            "api_name": api, "implementation": state,
            "in_frozen_named_scope": api in source_names,
            "in_named_adjacent_scope": api in adjacent,
            "source_doc_ids": [e["doc_id"] for e in entries],
            "permission_evidence": [{"doc_id": e["doc_id"],
                                     "status": e.get("permission_status", "unverified")}
                                    for e in entries],
            "live_enablement": "not_inspected",
            "data_history_pit_document_completeness": "not_proven_by_registration",
            "contract_gap_metadata": {k: v for k, v in spec.items()
                                      if any(t in k for t in ("gap", "note", "history", "permission", "verified", "attachment"))},
            "known_field_gaps": [g for e in entries for g in e.get("known_field_gaps", [])],
            "adjacent_evidence": adjacent.get(api),
        })
    return {
        "schema_version": 1,
        "counts": {
            "baseline_pages": len(ledger["entries"]),
            "discovered_pages": len(ledger.get("discovered_entries", [])),
            "baseline_named_acquisition_apis": len({n for e in ledger["entries"] for n in names(e)}),
            "catalog_and_discovered_named_apis": len(source_names),
            "additional_named_adjacent_apis": len(set(adjacent) - source_names),
            "total_named_scope": len(scope), "registered_extended": len(extended),
            "registered_legacy": len(legacy), "registered_union": len(registered),
            "registered_in_scope": len(registered & scope),
            "not_registered_in_scope": len(scope - registered),
            "reader_keys": len(reader_keys),
            "nameless_pages": sum(not names(e) for e in pages),
            "implementation_classes": dict(sorted(Counter(r["implementation"] for r in rows).items())),
        },
        "apis": rows,
        "reader_only_aliases": sorted(set(reader_keys) - registered),
        "registered_outside_named_scope": sorted(registered - scope),
        "registered_without_reader": sorted(registered - set(reader_keys)),
        # Retain original evidence/status/next_action, even if implementation moved on.
        # These are historical records, not fresh authority/permission assertions.
        "source_ledger": ledger,
        "limitations": [
            "Page counts are not endpoint counts or a scope ceiling.",
            "Unresolved mentions and nameless pages remain in source_ledger; no API is invented.",
            "Registration and reader availability do not prove live enablement, permission, full fields, history, PIT or attachments.",
            "All source ledger evidence and next actions are retained unchanged; this audit does not resolve stale statuses.",
            "Private portfolio reads and SDK wrappers are not public provider HTTP intake candidates.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ledger_path = ROOT / "config/tushare-coverage-ledger.json"
    if args.output.resolve() == ledger_path.resolve():
        parser.error("output must not overwrite the source coverage ledger")
    result = audit(json.loads(ledger_path.read_bytes()), EXTENDED_CONTRACTS,
                   CONTRACTS, KEYS, PORTFOLIO_READ_CONTRACTS, ADJACENT_API_OBLIGATIONS)
    paths = ["config/tushare-catalog.json", "config/tushare-coverage-ledger.json",
             "backend/shared/tushare_registry.py", "backend/shared/tushare_store.py",
             "backend/shared/tushare_pipeline.py",
             "backend/shared/tushare_realtime_extra_contracts.py",
             "backend/shared/tushare_portfolio_read_contracts.py"]
    paths = sorted(set(paths) | {str(p.relative_to(ROOT))
                                 for p in (ROOT / "backend/shared").glob("tushare_*contracts.py")})
    result["source_file_sha256"] = {
        p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
