#!/usr/bin/env python3
"""Fail closed if any OSS child service is down, even when the API is alive."""

import argparse
import json
import urllib.request


def healthy():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in (8000, 8001, 8002, 8003):
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                if (
                    response.status != 200
                    or json.load(response).get("status") != "healthy"
                ):
                    return False
        except (OSError, ValueError, AttributeError):
            return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Report disk/PG/Redis readiness as JSON; does not restart services",
    )
    args = parser.parse_args()
    if args.readiness:
        from check_storage_readiness import readiness_report

        report = readiness_report()
        print(json.dumps(report, sort_keys=True))
        raise SystemExit(0 if report["ready"] else 1)
    raise SystemExit(0 if healthy() else 1)
