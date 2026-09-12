"""Local durable pre-HTTP reservation; never mirrored or a supplier usage claim."""

import json
import sqlite3
import time
from datetime import datetime, time as daytime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from backend.shared.tushare_rate_policy import enabled, cyq_daily_limit


DAILY_QUOTA_APIS = ("cyq_perf", "cyq_chips")


def reserve(root, api, *, now=None):
    if api not in DAILY_QUOTA_APIS:
        return None
    root = Path(root)
    config_path = root / "pipeline-config.json"
    if not config_path.exists():
        return None
    config = json.loads(config_path.read_bytes())
    if not enabled(config):
        return None
    stamp = time.time() if now is None else now
    local = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai"))
    day = local.date().isoformat()
    tomorrow = datetime.combine(
        local.date() + timedelta(days=1), daytime(), local.tzinfo
    ).timestamp()
    limit = cyq_daily_limit(config, local)
    path = root / "daily-quota.sqlite"
    if path.is_symlink():
        raise ValueError("Invalid daily quota path")
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS daily_quota (api TEXT NOT NULL,day TEXT NOT NULL,used INTEGER NOT NULL,PRIMARY KEY(api,day))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS activation (api TEXT PRIMARY KEY,day TEXT NOT NULL)"
        )
        first = db.execute("SELECT day FROM activation WHERE api=?", (api,)).fetchone()
        if first is None:
            db.execute("INSERT INTO activation VALUES(?,?)", (api, day))
            first = (day,)
        row = db.execute(
            "SELECT used FROM daily_quota WHERE api=? AND day=?", (api, day)
        ).fetchone()
        used = row[0] if row else 0
        if type(used) is not int or used < 0:
            raise ValueError("Invalid daily quota counter")
        latest = db.execute(
            "SELECT day FROM daily_quota WHERE api=? ORDER BY day DESC LIMIT 1", (api,)
        ).fetchone()
        # Unknown pre-activation usage and clock rollback must not be treated as zero.
        reason = (
            "activation_guard"
            if day <= first[0]
            else "clock_rollback_guard"
            if latest and day < latest[0]
            else "daily_quota_exhausted"
            if used >= limit
            else None
        )
        if reason is None:
            db.execute(
                "INSERT INTO daily_quota VALUES(?,?,1) ON CONFLICT(api,day) DO UPDATE SET used=used+1",
                (api, day),
            )
            used += 1
        db.commit()  # Never refund transport failures or an uncertain interrupted HTTP.
        return {
            "api_name": api,
            "day": day,
            "timezone": "Asia/Shanghai",
            "limit": limit,
            "reserved": reason is None,
            "used": used,
            "reason": reason,
            "retry_at": tomorrow,
            "scope": "this_root_capture_sample_only",
        }
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def status(root, config, *, now=None):
    """Small read-only status; missing evidence is never reported as a zero baseline."""
    if not enabled(config):
        return None
    stamp = time.time() if now is None else now
    local = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai"))
    day = local.date().isoformat()
    limit = cyq_daily_limit(config, local)

    def entry():
        return {
            "day": day,
            "timezone": "Asia/Shanghai",
            "limit": limit,
            "scope": "this_root_capture_sample_only",
            "status": "not_initialized",
            "used": None,
        }

    per_api = {api: entry() for api in DAILY_QUOTA_APIS}
    path = Path(root) / "daily-quota.sqlite"
    if not path.exists():
        return {**per_api["cyq_perf"], "apis": per_api}
    try:
        if path.is_symlink():
            raise ValueError("Invalid daily quota path")
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)
        try:
            placeholders = ",".join("?" for _ in DAILY_QUOTA_APIS)
            first = dict(
                db.execute(
                    f"SELECT api,day FROM activation WHERE api IN ({placeholders})",
                    DAILY_QUOTA_APIS,
                ).fetchall()
            )
            rows = dict(
                db.execute(
                    f"SELECT api,used FROM daily_quota WHERE day=? AND api IN ({placeholders})",
                    (day, *DAILY_QUOTA_APIS),
                ).fetchall()
            )
            latest = dict(
                db.execute(
                    f"SELECT api,MAX(day) FROM daily_quota WHERE api IN ({placeholders}) GROUP BY api",
                    DAILY_QUOTA_APIS,
                ).fetchall()
            )
        finally:
            db.close()
        for api, result in per_api.items():
            if api not in first:
                continue
            if day <= first[api]:
                result["status"] = "activation_guard"
                continue
            if api in latest and day < latest[api]:
                result["status"] = "clock_rollback_guard"
                continue
            used = rows.get(api, 0)
            if type(used) is not int or used < 0:
                raise ValueError("Invalid daily quota counter")
            result.update(
                used=used,
                remaining=max(0, result["limit"] - used),
                status="daily_quota_exhausted" if used >= result["limit"] else "ready",
            )
    except (sqlite3.Error, OSError, ValueError) as exc:
        for result in per_api.values():
            result.update(
                status="quota_ledger_unavailable", error_type=type(exc).__name__
            )
    return {**per_api["cyq_perf"], "apis": per_api}


def activate(root, *, now=None):
    """Called by rollout; a failed pre-config activation is refreshed on recovery."""
    root = Path(root)
    stamp = time.time() if now is None else now
    day = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).date().isoformat()
    config = json.loads((root / "pipeline-config.json").read_bytes())
    path = root / "daily-quota.sqlite"
    if path.is_symlink():
        raise ValueError("Invalid daily quota path")
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS daily_quota (api TEXT NOT NULL,day TEXT NOT NULL,used INTEGER NOT NULL,PRIMARY KEY(api,day))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS activation (api TEXT PRIMARY KEY,day TEXT NOT NULL)"
        )
        activation_days = {}
        for api in DAILY_QUOTA_APIS:
            first = db.execute(
                "SELECT day FROM activation WHERE api=?", (api,)
            ).fetchone()
            activation_day = day
            if first is None:
                db.execute("INSERT INTO activation VALUES(?,?)", (api, day))
            elif not enabled(config):
                # Pre-config failure/recovery on a later day cannot use an earlier
                # activation to pretend that legacy HTTPs were already counted.
                activation_day = max(day, first[0])
                db.execute(
                    "UPDATE activation SET day=? WHERE api=?",
                    (activation_day, api),
                )
            else:
                activation_day = first[0]
            activation_days[api] = activation_day
        db.commit()
        return {
            "activation_day": activation_days["cyq_perf"],
            "activation_days": activation_days,
            "timezone": "Asia/Shanghai",
            "upstream_calls": 0,
        }
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
