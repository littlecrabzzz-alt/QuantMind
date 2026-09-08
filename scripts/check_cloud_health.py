#!/usr/bin/env python3
"""Fail closed if any OSS child service is down, even when the API is alive."""
import urllib.request


def healthy():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in (8000, 8001, 8002, 8003):
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                if response.status != 200:
                    return False
        except OSError:
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
