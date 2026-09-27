"""GLM personal Coding Plan quota, using the vendor's usage-query endpoint.

Source: zai-org/zai-coding-plugins / glm-plan-usage / query-usage.mjs.
The API reports percentages, not a reliable count of remaining tokens.
Credentials stay in the caller; only normalized, non-secret data is returned.
"""

from __future__ import annotations

import math
import re
import time
from email.utils import parsedate_to_datetime

QUOTA_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def normalize_quota(payload, now=None):
    now = time.time() if now is None else now
    unknown = {
        "status": "unknown",
        "observed_at": now,
        "remaining_percent": None,
        "used_percent": None,
        "reset_at": None,
        "weekly": None,
        "tools": None,
        "source": QUOTA_URL,
    }
    if (
        not isinstance(payload, dict)
        or payload.get("success") is False
        or str(payload.get("code", 200)) not in ("200", "0")
    ):
        return dict(unknown, reason="provider_rejected_quota_query")
    data = payload.get("data", payload)
    if not isinstance(data, dict) or not isinstance(data.get("limits"), list):
        return dict(unknown, reason="quota_response_missing_limits")
    windows = [w for w in data["limits"] if isinstance(w, dict)]
    tokens = [w for w in windows if w.get("type") == "TOKENS_LIMIT"]
    hourly = [
        w
        for w in tokens
        if str(w.get("unit")) == "3" and str(w.get("number", 5)) == "5"
    ]
    # Older personal plans had one unlabelled TOKENS_LIMIT. Never guess among
    # multiple unlabelled windows or confuse monthly MCP usage with model quota.
    if not hourly and len(tokens) == 1 and tokens[0].get("unit") is None:
        hourly = tokens
    if len(hourly) != 1:
        return dict(unknown, reason="five_hour_window_ambiguous")

    def window(w):
        used = number(w.get("percentage"))
        if used is None or not 0 <= used <= 100:
            return None
        reset = number(w.get("nextResetTime"))
        if reset and reset > 10**11:
            reset /= 1000
        return {
            "used_percent": used,
            "remaining_percent": 100 - used,
            "reset_at": reset if reset and reset > 0 else None,
        }

    five = window(hourly[0])
    if five is None:
        return dict(unknown, reason="invalid_quota_percentage")
    weekly = [
        window(w)
        for w in tokens
        if str(w.get("name", "")).lower() in ("weekly", "week", "周额度")
    ]
    tools = [window(w) for w in windows if w.get("type") == "TIME_LIMIT"]
    return dict(
        unknown,
        **five,
        status="known",
        plan=str(data.get("level", "unknown")),
        weekly=weekly[0] if len(weekly) == 1 else None,
        tools=tools[0] if len(tools) == 1 else None,
    )


def fetch_quota(api_key, session=None, now=None):
    import requests

    session = session or requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            QUOTA_URL,
            headers={"Authorization": api_key, "Accept": "application/json"},
            timeout=(5, 15),
            allow_redirects=False,
        )
        if response.status_code != 200:
            return {
                "status": "unknown",
                "observed_at": now or time.time(),
                "remaining_percent": None,
                "reason": f"quota_http_{response.status_code}",
                "source": QUOTA_URL,
            }
        return normalize_quota(response.json(), now)
    except Exception as exc:
        # Exceptions/response bodies can contain credentials or gateway HTML.
        return {
            "status": "unknown",
            "observed_at": now or time.time(),
            "remaining_percent": None,
            "reason": "quota_query_" + type(exc).__name__,
            "source": QUOTA_URL,
        }


def quota_decision(quota, now=None, reserve_percent=1):
    now = time.time() if now is None else now
    if (
        quota.get("status") != "known"
        or now - quota.get("observed_at", 0) > 180
        or quota.get("observed_at", 0) > now + 30
    ):
        return "quota_unknown", now + 60
    for w in (quota, quota.get("weekly")):
        if w and (
            number(w.get("remaining_percent")) is None
            or w["remaining_percent"] <= reserve_percent
        ):
            # Reset timestamps are hints. Always recheck before resuming; rolling
            # restoration may release capacity sooner than a full-window reset.
            return "waiting_quota", now + min(
                300, max(30, (w.get("reset_at") or now + 300) - now)
            )
    return "available", None


def failure_kind(message):
    text = str(message).lower()
    if re.search(
        r"\b(401|403|1000|1001|1002|1309|1311|1313)\b|invalid.*(key|credential)|authentication",
        text,
    ):
        return "auth_error"
    if re.search(r"\b(1308|1310)\b", text) or re.search(
        r"quota|usage.limit|额度|使用上限|限额.*重置|套餐.*(不足|耗尽)|token.*(exceed|limit)|insufficient.*balance",
        text,
    ):
        return "waiting_quota"
    if re.search(
        r"\b(429|500|502|503|504|1302|1303|1305|1312)\b|overload|rate.limit|fetch failed|stream_read|timeout|econnreset",
        text,
    ):
        return "retrying"
    return "failed"


def retry_delay(attempt, retry_after=None, now=None):
    now = time.time() if now is None else now
    value = number(retry_after)
    if value is None and retry_after:
        try:
            value = parsedate_to_datetime(retry_after).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            pass
    # Respect a real server wait; never spend a model call polling a timer.
    return max(1, value) if value is not None else min(900, 30 * 2 ** min(attempt, 5))
