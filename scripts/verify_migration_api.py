#!/usr/bin/env python3
"""Bounded API acceptance; optional reversible write/inference."""
import argparse
import getpass
import json
import os
import time
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-probe", action="store_true")
    parser.add_argument("--predict", action="store_true", help="Execute one registered model for one stock/day; retain run evidence")
    parser.add_argument("--port", type=int, default=18080, help="Primary API/web entry (default: SSH tunnel 18080)")
    parser.add_argument("--cross-port", type=int, default=8000, help="Second entry used by the write probe")
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    token = None

    def call(path, body=None, method=None, port=None):
        port = args.port if port is None else port
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
            data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        started = time.monotonic()
        with opener.open(req, timeout=240) as response:
            result = json.load(response)
        if result.get("code", 200) != 200:
            raise RuntimeError(f"Business error: {path}")
        print(json.dumps({"path": path, "method": req.get_method(), "port": port,
                          "seconds": round(time.monotonic() - started, 2), "status": "ok"}), flush=True)
        return result.get("data", result)

    password = os.getenv("QM_ACCEPTANCE_PASSWORD") or getpass.getpass("Admin password (not logged): ")
    login = call("/api/v1/auth/login", {"tenant_id": "default", "username": "admin",
                 "email_or_username": "admin", "login": "admin", "password": password})
    token = login["access_token"]
    models = call("/api/v1/research/models")["models"]
    if not models:
        raise RuntimeError("No migrated model")
    kline = call("/api/v1/research/kline/SH600519?days=10")
    if not kline.get("items"):
        raise RuntimeError("No migrated kline data")
    print(json.dumps({"models": len(models), "kline_rows": len(kline["items"])}), flush=True)

    if args.write_probe:
        route = "/api/v1/research/watchlist"
        before = call(route + "?limit=10000")
        if before["total"] != len(before["items"]):
            raise RuntimeError("Watchlist pagination incomplete; no mutation attempted")
        symbol = "SH600036"
        if any(i["symbol"] in (symbol, "600036", "600036.SH") for i in before["items"]):
            raise RuntimeError("Probe stock already belongs to user; no mutation attempted")
        marker = "migration-check-" + uuid.uuid4().hex
        try:
            for _ in range(2):
                call(route + "/" + symbol, {"stock_name": marker})
            after = call(route + "?limit=10000", port=args.cross_port)
            added = [i for i in after["items"] if i["symbol"] == symbol]
            if len(added) != 1 or added[0]["stockName"] != marker or after["total"] != before["total"] + 1:
                raise RuntimeError("Cross-entry visibility/idempotence failed")
            print("DUPLICATE_WRITE_AND_CROSS_ENTRY_READ_PASSED", flush=True)
        finally:
            current = call(route + "?limit=10000")
            if any(i["symbol"] == symbol and i["stockName"] == marker for i in current["items"]):
                call(route + "/" + symbol, method="DELETE")
                restored = call(route + "?limit=10000")
                if any(i["symbol"] == symbol for i in restored["items"]):
                    raise RuntimeError("Probe cleanup failed")
                print("PROBE_REMOVED", flush=True)

    if args.predict:
        predicted = call("/api/v1/research/predict-stock", {"symbol": "SH600519",
                         "model_id": models[0]["modelId"], "date": "2025-06-30",
                         "horizon": 1, "market": "CN", "execute": True})
        if predicted.get("status") != "success" or predicted.get("data_source") != "persisted":
            raise RuntimeError("Prediction did not produce a persisted success")
        print(json.dumps({"prediction": predicted}, ensure_ascii=False), flush=True)
    print("MIGRATION_API_ACCEPTANCE_PASSED", flush=True)


if __name__ == "__main__":
    main()
