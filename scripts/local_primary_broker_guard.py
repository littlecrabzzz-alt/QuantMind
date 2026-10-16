#!/usr/bin/env python3
"""Inspect restored broker backlog before starting any business consumers.

Read-only Redis access: no purge, acknowledgement, dequeue, or parameter change.
Task bodies and arguments are never emitted.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import redis


def inspect_broker(client, consumed_queues, consumed_routes):
    queues = {}
    blocked = {}
    for key in client.scan_iter():
        if client.type(key) != b"list":
            continue
        count = client.llen(key)
        name = key.decode("utf-8", errors="backslashreplace")
        queues[name] = count
        base = key.split(b"\x06\x16", 1)[0].decode("utf-8", errors="replace")
        if count and base in consumed_queues:
            blocked[name] = count
    unacknowledged = {}
    for _, raw in client.hscan_iter("unacked"):
        try:
            envelope = json.loads(raw)
            route = envelope[2]
            if not isinstance(route, str):
                route = "<unknown>"
        except (ValueError, IndexError, TypeError):
            route = "<unknown>"
        unacknowledged[route] = unacknowledged.get(route, 0) + 1
    for route, count in unacknowledged.items():
        if route in consumed_routes or route == "<unknown>":
            blocked["unacked:" + route] = count
    return {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "blocked_retained_backlog" if blocked else "safe_to_start_consumers",
        "consumed_queues": sorted(consumed_queues),
        "list_queue_counts": queues,
        "unacknowledged_routing_counts": unacknowledged,
        "blocked_counts": blocked,
        "redis_mutated": False,
        "research_consumers_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    client = redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ.get("REDIS_PASSWORD") or None,
        db=int(os.environ.get("REDIS_DB_BROKER", "3")),
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    queues = {os.environ.get("QLIB_CELERY_QUEUE", "qlib_backtest_srv"), "market_sync"}
    routes = queues | {os.environ.get("QLIB_CELERY_ROUTING_KEY", "qlib.backtest")}
    result = inspect_broker(client, queues, routes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["blocked_counts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
