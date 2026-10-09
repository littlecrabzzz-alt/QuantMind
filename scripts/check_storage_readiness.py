#!/usr/bin/env python3
"""Read-only storage readiness report. Run inside the configured application container.

The launcher uses only stdlib (python -S). Isolated dependency probes load installed
asyncpg/redis without running sitecustomize or importing application settings.
No writes, service restarts, credentials, or raw dependency errors are emitted.
"""

import json
import os
import shutil
import subprocess
import sys


# Credentials are read in the child environment, never interpolated into argv.
_PROBE = r"""
import asyncio, json, os, site, sys
sys.path.extend(site.getsitepackages())
async def probe():
    if sys.argv[1] == "postgres":
        import asyncpg
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "db")),
            port=int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
            user=os.getenv("DB_USER", os.getenv("POSTGRES_USER", "quantmind")),
            password=os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
            database=os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "quantmind")),
            timeout=3, command_timeout=3)
        try:
            return {"ok": await conn.fetchval("SELECT 1") == 1}
        finally:
            await conn.close(timeout=1)
    import redis
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        socket_timeout=3, socket_connect_timeout=3)
    try:
        info = client.info("persistence")
        fields = ("aof_enabled", "aof_last_write_status",
                  "aof_last_bgrewrite_status", "rdb_last_bgsave_status")
        return {"ok": True, "persistence": {k: info.get(k) for k in fields}}
    finally:
        client.close()
try:
    result = asyncio.run(probe())
except Exception as exc:
    result = {"ok": False, "error": type(exc).__name__}
print(json.dumps(result))
"""


def redis_persistence_ready(info):
    """Cloud Redis requires AOF; PING alone cannot detect failed persistence."""
    return info.get("aof_enabled") == 1 and all(
        info.get(field) == "ok"
        for field in (
            "aof_last_write_status",
            "aof_last_bgrewrite_status",
            "rdb_last_bgsave_status",
        )
    )


def probe_dependency(name):
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _PROBE, name],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        report = json.loads(result.stdout)
        if name == "redis" and report.get("ok"):
            report["ok"] = redis_persistence_ready(report.get("persistence", {}))
        return report
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"ok": False, "error": "probe_failed"}


def readiness_report(min_free_bytes=None):
    if min_free_bytes is None:
        try:
            min_free_bytes = int(
                os.getenv("QM_STORAGE_MIN_FREE_BYTES", str(2 * 1024**3))
            )
        except ValueError:
            return {"ready": False, "error": "invalid_storage_threshold"}
    if min_free_bytes < 0:
        return {"ready": False, "error": "invalid_storage_threshold"}
    disks = {}
    for path in ("/", "/data"):
        try:
            usage = shutil.disk_usage(path)
            disks[path] = {
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "used_bytes": usage.used,
                "min_free_bytes": min_free_bytes,
                "ok": usage.free >= min_free_bytes,
            }
        except OSError:
            disks[path] = {"ok": False, "error": "disk_unavailable"}
    postgres = probe_dependency("postgres")
    redis = probe_dependency("redis")
    return {
        "ready": all(v["ok"] for v in disks.values())
        and postgres.get("ok") is True
        and redis.get("ok") is True,
        "disks": disks,
        "postgres": postgres,
        "redis": redis,
    }


if __name__ == "__main__":
    report = readiness_report()
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["ready"] else 1)
