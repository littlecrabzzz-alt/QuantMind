"""Project the saved 15h artificial ledger; never recalculate targets or fit."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

from calendar_target_adapter import (
    MISSING_POLICY, RANK_POLICY, TARGET_CONTRACT, canonical_sha256, project_targets,
)


def verify(ledger_path, *, source_revision, target_code, purge_source=None):
    source_bytes = ledger_path.read_bytes()
    original = json.loads(source_bytes)
    features = ["feature_observed", "feature_missing"]
    target_code_sha = hashlib.sha256(target_code.read_bytes()).hexdigest()
    config_sha = canonical_sha256({"target_contract_id": TARGET_CONTRACT, "rank_policy": RANK_POLICY,
                                   "missing_target_policy": MISSING_POLICY, "preprocessing_enabled": False})

    def bind(ledger, rows, pool, order=features):
        return {"source_revision": source_revision, "input_manifest_sha256": original["fixture_sha256"],
                "config_sha256": config_sha, "target_code_sha256": target_code_sha,
                "target_contract_id": TARGET_CONTRACT, "rank_policy": RANK_POLICY,
                "missing_target_policy": MISSING_POLICY, "calendar_sha256": canonical_sha256(ledger["calendar"]),
                "target_ledger_sha256": canonical_sha256(ledger), "feature_rows_sha256": canonical_sha256(rows),
                "feature_order": list(order), "pool_sha256": canonical_sha256(pool),
                "development_end": "2026-03-06"}

    results = {}
    negatives = []
    for name in ("complete", "single_missing_observation"):
        ledger = original["cases"][name]
        # Feature values come only from saved artificial signal prices. None is
        # an explicit missing-feature probe. Extra zero-volume/null-factor values
        # establish that this adapter introduces no inference eligibility filter.
        rows = [{"symbol": target["symbol"], "trade_date": target["signal_date"],
                 "feature_observed": float(target["signal_close_raw"]), "feature_missing": None,
                 "volume": 0, "single_factor": None} for target in ledger["rows"]]
        results[name] = {}
        for selection, pool in [("full_pool", ["SH609991", "SZ009991"]), ("b_only", ["SZ009991"])]:
            bound = bind(ledger, rows, pool)
            before = canonical_sha256([ledger, rows, bound])
            result = project_targets(ledger, rows, features=features, pool=pool, identity=bound)
            assert canonical_sha256([ledger, rows, bound]) == before
            expected = [row for row in ledger["rows"] if row["valid_label"] and row["symbol"] in pool]
            assert len(result["sidecar"]) == len(ledger["rows"])
            for view in ("training_frame", "diagnostic_frame"):
                assert len(result[view]) == len(expected)
                for projected, target in zip(result[view], expected):
                    assert (projected["symbol"], projected["trade_date"]) == (target["symbol"], target["signal_date"])
                    assert projected["feature_missing"] is None
                    assert list(projected)[-2:] == features
                    if view == "training_frame":
                        assert (projected["label"], projected["_label_end_date"]) == (target["rank_label"], target["rank_dependency_end"])
                    else:
                        assert (projected["forward_return"], projected["label_end"]) == (target["raw_return"], target["exit_date"])
            for side, target in zip(result["sidecar"], ledger["rows"]):
                assert {k: v for k, v in side.items() if k != "adapter"} == target
                assert side["adapter"]["features_imputed"] is False
                assert side["adapter"]["feature_status"]["feature_missing"] == "null"
            b = next(row for row in result["training_frame"] if row["symbol"] == "SZ009991" and row["trade_date"] == "2026-03-02")
            assert b["label"] == (0.0 if name == "complete" else 0.5)
            result["assertions"] = {"exact_target_projection": True, "sidecar_lossless": True,
                                    "pool_filter_does_not_rerank": True, "missing_feature_retained": True,
                                    "no_volume_or_single_factor_filter": True, "inputs_unchanged": True}
            results[name][selection] = result

        pool = ["SZ009991"]
        def reject(label, target=ledger, supplied=None, identity=None, order=features):
            supplied = rows if supplied is None else supplied
            identity = bind(target, supplied, pool, order) if identity is None else identity
            try:
                project_targets(target, supplied, features=order, pool=pool, identity=identity)
            except ValueError as exc:
                assert label in str(exc), (label, str(exc))
                negatives.append({"case": name, "expected": label, "actual": str(exc)})
            else:
                raise AssertionError("Expected rejection: " + label)

        reject("duplicate_join_key", supplied=rows + [rows[0]])
        duplicated = deepcopy(ledger); duplicated["rows"].append(duplicated["rows"][0])
        reject("duplicate_join_key", target=duplicated)
        orphan = deepcopy(rows); orphan[0]["symbol"] = "ORPHAN"
        reject("orphan_feature_rows", supplied=orphan)
        reject("missing_feature_rows", supplied=rows[1:])
        identity = bind(ledger, rows, pool); identity.pop("config_sha256")
        reject("missing_identity", identity=identity)
        drift = deepcopy(ledger); drift["rows"][0]["rank_label"] = 0.125
        reject("target_ledger_hash_mismatch", target=drift, identity=bind(ledger, rows, pool))
        drift = deepcopy(ledger); drift["calendar"] = drift["calendar"][::-1]
        reject("calendar_hash_mismatch", target=drift, identity=bind(ledger, rows, pool))
        reject("invalid_or_reserved_features", order=["label"])
        identity = bind(ledger, rows, pool); identity["feature_order"] = features[::-1]
        reject("feature_order_mismatch", identity=identity)
        identity = bind(ledger, rows, pool); identity.pop("development_end")
        reject("missing_identity", identity=identity)
        identity = bind(ledger, rows, pool); identity["development_end"] = "2026-02-30"
        reject("invalid_date:development_end", identity=identity)
        identity = bind(ledger, rows, pool); identity["development_end"] = "2026-03-05"
        reject("ledger_date_exceeds_development_end", identity=identity)

    purge = {"status": "not_run", "reason": "No actual purge source requested"}
    if purge_source is not None:
        import pandas as pd
        spec = importlib.util.spec_from_file_location("adapter_actual_splits", purge_source)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        records = []
        for name, selections in results.items():
            for selection, result in selections.items():
                frame = pd.DataFrame(result["training_frame"])
                frame["trade_date"] = pd.to_datetime(frame["trade_date"])
                frame["_label_end_date"] = pd.to_datetime(frame["_label_end_date"])
                boundary = pd.Timestamp("2026-03-04")
                frame = frame[frame.trade_date <= boundary]
                kept = module._purge_label_tail(frame, {}, end=boundary)
                actual = sorted((row.symbol, str(row.trade_date.date())) for row in kept.itertuples())
                expected = [("SZ009991", "2026-03-02")]
                if name == "complete" and selection == "full_pool":
                    expected.insert(0, ("SH609991", "2026-03-02"))
                assert actual == expected
                records.append({"case": name, "selection": selection, "input_rows": len(frame), "kept_keys": actual})
        purge = {"status": "passed", "function": "_purge_label_tail", "source": str(purge_source),
                 "source_sha256": hashlib.sha256(purge_source.read_bytes()).hexdigest(), "records": records,
                 "scope": "actual helper only; no _split_data, loader, worker or fit invoked"}
    assert ledger_path.read_bytes() == source_bytes
    return {"status": "passed", "source_ledger_file": str(ledger_path),
            "source_ledger_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_revision": source_revision, "cases": results, "negative_checks": negatives,
            "actual_purge": purge, "target_recomputed": False, "training_or_execution_performed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--target-code", required=True, type=Path)
    parser.add_argument("--purge-source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.ledger, source_revision=args.source_revision, target_code=args.target_code, purge_source=args.purge_source)
    result["code_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
                             (Path(__file__), Path(__file__).with_name("calendar_target_adapter.py"))}
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"status": result["status"], "views": 4, "negative_checks": len(result["negative_checks"]),
                      "actual_purge": result["actual_purge"]["status"], "target_recomputed": False}))
