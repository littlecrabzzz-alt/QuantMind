"""Offline projection of an existing calendar target ledger; no target recompute.

This adapter preserves pre-pool ranks and missing features. It does not establish
training, source/PIT, inference or execution eligibility, and performs no IO.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import re

TARGET_CONTRACT = "calendar-label-candidate-v1"
RANK_POLICY = "all_loaded_valid_targets_before_pool"
MISSING_POLICY = "exclude_missing_target_without_date_shift"
RESERVED = {
    "symbol", "signal_date", "trade_date", "label", "_label_end_date",
    "forward_return", "label_end", "raw_return", "rank_label",
    "rank_dependency_end", "valid_label", "entry_date", "exit_date",
}


def canonical_sha256(value):
    """Python sorted compact JSON; NaN/Infinity feature tokens remain distinct.

    Target prices/labels are finite; nonfinite features are retained, not filled.
    This encoding is explicitly bound in the adapter result, not raw-file SHA.
    """
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=True)
    return hashlib.sha256(data.encode()).hexdigest()


def project_targets(ledger, feature_rows, *, features, pool, identity):
    required = {
        "source_revision", "input_manifest_sha256", "config_sha256",
        "target_code_sha256", "target_contract_id", "rank_policy",
        "missing_target_policy", "calendar_sha256", "target_ledger_sha256",
        "feature_rows_sha256", "feature_order", "pool_sha256", "development_end",
    }
    if not isinstance(identity, dict) or any(key not in identity for key in required):
        raise ValueError("missing_identity")
    for key in required:
        if key.endswith("sha256") and not re.fullmatch(r"[0-9a-f]{64}", str(identity[key])):
            raise ValueError("invalid_identity_hash:" + key)
    if not re.fullmatch(r"[0-9a-f]{40}", str(identity["source_revision"])):
        raise ValueError("invalid_source_revision")
    def canonical_date(value, field):
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("invalid_date:" + field) from None
        return value

    cutoff = canonical_date(identity["development_end"], "development_end")
    dated_values = [("calendar", value) for value in ledger["calendar"]]
    dated_values += [(field, row[field]) for row in ledger["rows"]
                     for field in ("signal_date", "entry_date", "exit_date", "rank_dependency_end")
                     if row[field] is not None]
    for field, value in dated_values:
        if canonical_date(value, field) > cutoff:
            raise ValueError("ledger_date_exceeds_development_end:" + field)
    if (identity["target_contract_id"] != TARGET_CONTRACT or
            ledger.get("candidate_id") != TARGET_CONTRACT or
            ledger.get("lag_market_steps") != 1 or ledger.get("holding_market_steps") != 1 or
            identity["rank_policy"] != RANK_POLICY or
            identity["missing_target_policy"] != MISSING_POLICY):
        raise ValueError("unsupported_target_contract")
    if not features or len(set(features)) != len(features) or any(
            not isinstance(feature, str) or not feature or feature in RESERVED for feature in features):
        raise ValueError("invalid_or_reserved_features")
    if identity["feature_order"] != features:
        raise ValueError("feature_order_mismatch")
    if len(set(pool)) != len(pool) or any(not isinstance(symbol, str) or not symbol for symbol in pool):
        raise ValueError("invalid_pool")
    for name, value in [("calendar", ledger["calendar"]), ("target_ledger", ledger),
                        ("feature_rows", feature_rows), ("pool", pool)]:
        if canonical_sha256(value) != identity[name + "_sha256"]:
            raise ValueError(name + "_hash_mismatch")

    def keyed(rows, date_field):
        indexed = {}
        for row in rows:
            key = row["symbol"], row[date_field]
            if not all(isinstance(value, str) and value for value in key):
                raise ValueError("invalid_join_key")
            if key in indexed:
                raise ValueError("duplicate_join_key")
            indexed[key] = row
        return indexed

    targets = keyed(ledger["rows"], "signal_date")
    supplied_features = keyed(feature_rows, "trade_date")
    if supplied_features.keys() - targets.keys():
        raise ValueError("orphan_feature_rows")
    if targets.keys() - supplied_features.keys():
        raise ValueError("missing_feature_rows")
    pool_members = set(pool)
    training, diagnostic, sidecar = [], [], []
    for key, target in targets.items():
        if type(target["valid_label"]) is not bool:
            raise ValueError("invalid_target_valid_flag")
        row = supplied_features[key]
        values = {feature: row.get(feature) for feature in features}
        feature_status = {
            feature: ("absent" if feature not in row else "null" if row[feature] is None else
                      "nonfinite" if isinstance(row[feature], float) and not math.isfinite(row[feature]) else "present")
            for feature in features
        }
        selected = target["valid_label"] and key[0] in pool_members
        record = deepcopy(target)
        record["adapter"] = {
            "pool_member": key[0] in pool_members, "projected": selected,
            "projection_reason": "included" if selected else "invalid_target" if not target["valid_label"] else "outside_pool",
            "feature_values": deepcopy(values), "feature_status": feature_status,
            "features_imputed": False, "source_availability": "unknown",
        }
        sidecar.append(record)
        if not selected:
            continue
        for field in ("rank_label", "raw_return"):
            value = target[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("invalid_projected_target:" + field)
        if target["rank_dependency_end"] not in ledger["calendar"] or target["exit_date"] not in ledger["calendar"]:
            raise ValueError("invalid_dependency_date")
        training.append({"symbol": key[0], "trade_date": key[1],
                         "label": target["rank_label"], "_label_end_date": target["rank_dependency_end"],
                         **deepcopy(values)})
        diagnostic.append({"symbol": key[0], "trade_date": key[1],
                           "forward_return": target["raw_return"], "label_end": target["exit_date"],
                           **deepcopy(values)})
    return {
        "adapter_contract": "calendar-target-adapter-v1",
        "identity": deepcopy(identity), "hash_encoding": "python-json-sort-compact-utf8-nonfinite-tokens-v1",
        "feature_order": list(features), "pool": list(pool),
        "training_frame": training, "diagnostic_frame": diagnostic, "sidecar": sidecar,
        "source_availability": "unknown",
        "scope": "projection_only_not_training_or_execution_eligibility",
    }
