#!/usr/bin/env python3
"""Run and resume a local research baseline through QuantMind's normal APIs.

Credentials: QM_TOKEN, or QM_USERNAME / QM_PASSWORD (interactive password if absent).
Artifacts contain requests/results, never authentication tokens. No trading API is called.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def submit_once(out: Path, name: str, request: dict, submit):
    """Retain intent before POST; a lost response requires reconciliation, not retry."""
    intent = out / f"{name}-submission-intent.json"
    response = out / f"{name}-submission.json"
    if intent.exists():
        if json.loads(intent.read_text()) != request:
            raise RuntimeError(f"{name} request changed; use a new experiment directory")
        if not response.exists():
            raise RuntimeError(
                f"{name} submission outcome unknown; inspect platform records and recover "
                f"the response into {response.name} before resuming. No POST was retried."
            )
    if response.exists():
        return json.loads(response.read_text())
    dump(intent, request)
    result = submit()
    dump(response, result)
    return result


class Client:
    def __init__(self, api: str, session: Path | None):
        self.api = api.rstrip("/")
        self.token = os.getenv("QM_TOKEN", "")
        if session:
            self.token = json.loads(session.read_text())["token"]
        if not self.token:
            login = self.request("/auth/login", {
                "username": os.getenv("QM_USERNAME", "admin"),
                "password": os.getenv("QM_PASSWORD") or getpass.getpass("QuantMind password: "),
                "tenant_id": "default",
            })
            self.token = login.get("access_token") or login.get("data", {}).get("access_token")
            if not self.token:
                raise RuntimeError("Login returned no access token")

    def request(self, path: str, payload=None, *, method=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(
            self.api + "/api/v1" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{req.get_method()} {path}: HTTP {exc.code}: {detail[:1500]}") from None


def main(argv=None, client=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["run", "prepare", "train", "status", "infer", "backtest", "backtest-status", "verify"])
    parser.add_argument("--config", type=Path, help="Defaults to saved experiment config, then config/baseline_cn_l1.json")
    parser.add_argument("--output", type=Path, required=True, help="Use the same directory to resume")
    parser.add_argument("--session", type=Path, help="Optional private JSON containing token")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    config_path = args.config or (out / "baseline-config.json" if (out / "baseline-config.json").exists() else ROOT / "config/baseline_cn_l1.json")
    cfg = json.loads(config_path.read_text())
    state_path = out / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    digest = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    if state.get("config_sha256", digest) != digest:
        raise RuntimeError("Configuration changed: use a new output directory for a new experiment")
    state["config_sha256"] = digest
    dump(out / "baseline-config.json", cfg)
    if args.stage == "verify":
        from verify_quant_baseline import verify
        verify(out)
        return
    api = args.api.rstrip("/")
    if state.get("api", api) != api:
        raise RuntimeError("API endpoint changed: use a new output directory")
    state["api"] = api
    # Freeze configuration before the first network request, even if it fails.
    dump(state_path, state)
    client = client or Client(args.api, args.session)

    def save():
        dump(state_path, state)

    if args.stage == "run":
        def stage(name):
            main([name, *argv[1:]], client=client)

        for name in ("prepare", "train"):
            stage(name)
        for poll_stage, status_key in (("status", "training_status"), ("backtest-status", "backtest_status")):
            if poll_stage == "backtest-status":
                stage("infer")
                stage("backtest")
            deadline = time.monotonic() + 1800
            while True:
                stage(poll_stage)
                latest = json.loads(state_path.read_text())
                status = latest.get(status_key)
                if status == "completed":
                    break
                if status in {"failed", "cancelled"}:
                    raise RuntimeError(f"{poll_stage} {status}; artifacts retained in {out}")
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Waiting timed out; rerun the same command to resume: {out}")
                time.sleep(10)
        stage("verify")
        return
    if args.stage == "prepare":
        if (out / "catalog.json").exists():
            print("Reusing frozen factor catalog:", json.loads((out / "catalog.json").read_text())["version_id"])
            save()
            return
        source = cfg["factor_source"]
        if not (out / "sources.json").exists():
            dump(out / "sources.json", client.request("/admin/training-data/sources/refresh?market=CN", {}))
        sources = json.loads((out / "sources.json").read_text())["sources"]
        if not sources[source]["ready"]:
            raise RuntimeError(f"Source is not ready: {sources[source].get('reason')}")
        missing = set(cfg["features"]) - set(sources[source]["columns"])
        if missing:
            raise RuntimeError(f"Missing baseline factors: {sorted(missing)}")
        catalog = client.request(f"/models/feature-catalog?market=CN&factor_source={source}")
        available = {f["key"] for c in catalog.get("categories", []) for f in c["features"] if f.get("enabled", True)}
        if not set(cfg["features"]) <= available:
            if catalog.get("feature_count", 0):
                raise RuntimeError("An existing catalog lacks requested features; review it before replacing")
            if not state.get("catalog_version"):
                version = client.request("/admin/training-data/versions?market=CN", {
                    "version_name": cfg["job_name"], "source_dataset": source,
                })
                state["catalog_version"] = version["version_id"]
                save()
            version_id = state["catalog_version"]
            for i, feature in enumerate(cfg["features"]):
                client.request(f"/admin/training-data/versions/{version_id}/mappings", {
                    "mapping": {"source_dataset": source, "source_column": feature,
                                "feature_key": feature, "display_name": feature,
                                "category_id": "baseline", "category_name": "基线价量因子",
                                "enabled": True, "default_selected": True, "sort_order": i}
                }, method="PUT")
            client.request(f"/admin/training-data/versions/{version_id}/publish", {})
            catalog = client.request(f"/models/feature-catalog?market=CN&factor_source={source}")
        dump(out / "catalog.json", catalog)
        print("Catalog ready:", catalog.get("feature_count"), "features")
    elif args.stage == "train":
        if state.get("run_id"):
            print("Existing training run:", state["run_id"], "(use status)")
            return
        catalog = json.loads((out / "catalog.json").read_text())
        request = {**cfg, "factor_catalog_version": catalog["version_id"], "deploy_to_production": False}
        dump(out / "training-request.json", request)
        response = submit_once(out, "training", request,
                               lambda: client.request("/models/run-training", request))
        state["run_id"] = response.get("runId") or response.get("run_id")
        if not state["run_id"]:
            raise RuntimeError("Training response has no run ID; inspect training-submission.json")
        print("Training submitted:", state["run_id"])
    elif args.stage == "status":
        response = client.request(f"/models/training-runs/{state['run_id']}")
        dump(out / "training-status.json", response)
        state["training_status"] = response["status"]
        result = response.get("result") or {}
        if response["status"] == "completed":
            registration = result.get("model_registration") or {}
            if registration.get("status") != "ready" or not registration.get("model_id"):
                raise RuntimeError("Training completed but model registration is not ready")
            state["model_id"] = registration["model_id"]
        print("Training:", response["status"], response.get("progress"), "model:", state.get("model_id"))
        print("\n".join((response.get("logs") or "").splitlines()[-8:]))
    elif args.stage == "infer":
        if not state.get("model_id"):
            raise RuntimeError("Run status after training completes to obtain model_id")
        if state.get("inference_done"):
            saved = json.loads((out / "inference-result.json").read_text())
            if saved.get("effective_model_id") == state["model_id"] and saved.get("success") and not saved.get("fallback_used") and saved.get("signals_count", 0) > 0:
                if not (out / "inference-detail.json").exists():
                    dump(out / "inference-detail.json", client.request(f"/models/inference/runs/{saved['run_id']}"))
                print("Inference already verified:", saved.get("run_id"))
                return
            raise RuntimeError("Saved inference does not match the registered model; preserve it and use a new experiment directory")
        request = {"model_id": state["model_id"], "inference_date": cfg["test_end"]}
        dump(out / "inference-request.json", request)
        result = submit_once(out, "inference", request,
                             lambda: client.request("/models/inference/run", request))
        dump(out / "inference-result.json", result)
        if not result.get("success") or result.get("effective_model_id") != state["model_id"] or result.get("fallback_used") or result.get("signals_count", 0) <= 0:
            raise RuntimeError("Inference failed, used a different model, or produced no signals; inspect inference-result.json")
        state["inference_done"] = True
        save()
        dump(out / "inference-detail.json", client.request(f"/models/inference/runs/{result['run_id']}"))
        print(json.dumps(result, ensure_ascii=False)[:1800])
    elif args.stage == "backtest":
        if not state.get("model_id"):
            raise RuntimeError("No completed model")
        if state.get("backtest_id"):
            print("Existing backtest:", state["backtest_id"])
            return
        request = {
            "user_id": "", "tenant_id": "",
            "model_id": state["model_id"], "strategy_type": "TopkDropout",
            "strategy_params": {"signal": "<PRED>", "topk": 20, "n_drop": 5, "rebalance_days": 1},
            "start_date": cfg["test_start"], "end_date": cfg["test_end"],
            "initial_capital": cfg["context"]["initial_capital"], "benchmark": "SH000300",
            "deal_price": "close", "signal_lag_days": 1, "use_vectorized": False,
            "commission": 0.00025, "min_commission": 5, "stamp_duty": 0.0005,
            "transfer_fee": 0.00001, "impact_cost_coefficient": 0.0005,
            "allow_feature_signal_fallback": False, "seed": 42,
        }
        dump(out / "backtest-request.json", request)
        result = submit_once(out, "backtest", request,
                             lambda: client.request("/qlib/backtest?async_mode=true", request))
        state["backtest_id"] = result["backtest_id"]
        print("Backtest submitted:", state["backtest_id"])
    elif args.stage == "backtest-status":
        result = client.request(f"/qlib/results/{state['backtest_id']}")
        dump(out / "backtest-result.json", result)
        state["backtest_status"] = result.get("status")
        print(json.dumps({k: v for k, v in result.items() if k in {
            "status", "error_message", "total_return", "annual_return", "sharpe_ratio",
            "max_drawdown", "total_trades", "benchmark_return", "execution_time"
        }}, ensure_ascii=False))
    save()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as exc:
        print(f"Baseline stopped: {exc}", file=sys.stderr)
        sys.exit(1)
