"""Local durable pre-HTTP reservation; never mirrored or a supplier usage claim."""

import json
import sqlite3
import time
from datetime import datetime, time as daytime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from backend.shared.tushare_rate_policy import enabled, cyq_daily_limit


def reserve(root, api, *, now=None):
    if api != "cyq_perf":
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
    result = {
        "day": day,
        "timezone": "Asia/Shanghai",
        "limit": cyq_daily_limit(config, local),
        "scope": "this_root_capture_sample_only",
        "status": "not_initialized",
        "used": None,
    }
    path = Path(root) / "daily-quota.sqlite"
    if not path.exists():
        return result
    try:
        if path.is_symlink():
            raise ValueError("Invalid daily quota path")
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)
        try:
            first = db.execute(
                "SELECT day FROM activation WHERE api='cyq_perf'"
            ).fetchone()
            row = db.execute(
                "SELECT used FROM daily_quota WHERE api='cyq_perf' AND day=?", (day,)
            ).fetchone()
            latest = db.execute(
                "SELECT day FROM daily_quota WHERE api='cyq_perf' ORDER BY day DESC LIMIT 1"
            ).fetchone()
        finally:
            db.close()
        used = row[0] if row else 0
        if not first or day <= first[0]:
            result["status"] = "activation_guard"
        elif latest and day < latest[0]:
            result["status"] = "clock_rollback_guard"
        else:
            result.update(
                used=used,
                remaining=max(0, result["limit"] - used),
                status="daily_quota_exhausted" if used >= result["limit"] else "ready",
            )
    except (sqlite3.Error, OSError, ValueError) as exc:
        result.update(status="quota_ledger_unavailable", error_type=type(exc).__name__)
    return result


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
        first = db.execute("SELECT day FROM activation WHERE api='cyq_perf'").fetchone()
        if first is None:
            db.execute("INSERT INTO activation VALUES('cyq_perf',?)", (day,))
        elif not enabled(config):
            # Pre-config failure/recovery on a later day cannot use an earlier
            # activation to pretend that legacy HTTPs were already counted.
            day = max(day, first[0])
            db.execute("UPDATE activation SET day=? WHERE api='cyq_perf'", (day,))
        else:
            day = first[0]
        db.commit()
        return {"activation_day": day, "timezone": "Asia/Shanghai", "upstream_calls": 0}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
