"""Opt-in local ceilings. Published limits are not proof of account permission."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

POLICY = "tiered_v1"
PURCHASED_RPM = {
    "news": 400,
    "major_news": 400,
    "cctv_news": 400,
    "anns_d": 500,
    "irm_qa_sh": 500,
    "irm_qa_sz": 500,
    "npr": 500,
    "research_report": 500,
    "monetary_policy": 200,
}
# Specific official pages override the general points table (doc290).
PAGE_RPM = {
    "daily": 500,
    "stock_basic": 50,
    "cyq_chips": 200,
    "limit_step": 500,
    "kpl_list": 500,
}
UNKNOWN_APIS = {"fut_weekly_monthly", "hsgt_top10", "namechange"}
SPECIAL = {"report_rc", "cyq_perf", "cyq_chips", "broker_recommend"}


def enabled(config):
    mode = config.get("rate_policy")
    if mode not in (None, "legacy", POLICY):
        raise ValueError("Invalid rate policy")
    return mode == POLICY


def positive_int(value, name, maximum=500):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("Invalid " + name)
    return value


def entitlement(config, now=None):
    today = (
        (now or datetime.now(ZoneInfo("Asia/Shanghai")))
        .astimezone(ZoneInfo("Asia/Shanghai"))
        .date()
    )
    evidence = config.get("account_entitlement", {})
    tranches = evidence.get(
        "point_tranches",
        [
            {"points": 8000, "expires": "2027-09-08"},
            {"points": 2000, "expires": "2026-12-05"},
            {"points": 100, "expires": None},
        ],
    )
    if not isinstance(tranches, list) or not 1 <= len(tranches) <= 20:
        raise ValueError("Invalid point tranches")
    active, reported, notices, expiries, sanitized = 0, 0, [], [], []
    for item in tranches:
        points = positive_int(item["points"], "point tranche", 1000000)
        reported += points
        expiry = date.fromisoformat(item["expires"]) if item.get("expires") else None
        sanitized.append(
            {"points": points, "expires": expiry.isoformat() if expiry else None}
        )
        days = (expiry - today).days if expiry else None
        if days is None or days > 0:
            active += points
        if expiry:
            expiries.append((expiry, points))
            if days <= 90:
                notices.append(
                    {
                        "points": points,
                        "expires": expiry.isoformat(),
                        "days": days,
                        "window_days": 0
                        if days <= 0
                        else 7
                        if days <= 7
                        else 30
                        if days <= 30
                        else 90,
                    }
                )
    if evidence.get("reported_points", reported) != reported:
        raise ValueError("Reported points do not match tranches")
    next_expiry = min((x for x in expiries if x[0] >= today), default=None)
    expiry = (
        next_expiry[0] if next_expiry else max((x[0] for x in expiries), default=today)
    )
    future_points = sum(
        item["points"]
        for item in tranches
        if not item.get("expires") or date.fromisoformat(item["expires"]) > expiry
    )
    independent_expiry = date.fromisoformat(
        evidence.get("independent_permissions_expiry", "2027-09-08")
    )
    independent_days = (independent_expiry - today).days
    return {
        "source": "user_reported_not_supplier_verified",
        "reported_points": reported,
        "effective_points_conservative": active,
        "expected_points_after_expiry": future_points,
        "points_expiry_date": expiry.isoformat(),
        "days_until_expiry": (expiry - today).days,
        "point_tranches": sanitized,
        "notices": notices,
        "notice": "expired_reverify_entitlement"
        if any(n["days"] <= 0 for n in notices)
        else "expires_within_90_days"
        if notices
        else None,
        "independent_permissions_expiry": independent_expiry.isoformat(),
        "independent_days_until_expiry": independent_days,
        "independent_notice_window_days": (
            0
            if independent_days <= 0
            else 7
            if independent_days <= 7
            else 30
            if independent_days <= 30
            else 90
            if independent_days <= 90
            else None
        ),
    }


def resolved_api_rate(api, spec, config, now=None):
    if not enabled(config):
        rpm = min(
            int(config.get("api_requests_per_minute", {}).get(api, 200)),
            int(spec.get("requests_per_minute", 500)),
        )
        if not 1 <= rpm <= 500:
            raise ValueError("Invalid API request rate")
        return {"rpm": rpm, "source": "legacy_contract_and_config"}
    rights = entitlement(config, now)
    points = rights["effective_points_conservative"]
    independent = bool(spec.get("independent_permission")) or spec.get("group") in (
        "text",
        "history_minutes",
        "foreign_financial",
    )
    if api in PURCHASED_RPM:
        rpm, source = PURCHASED_RPM[api], "user_purchased_permission_family"
        if (now or datetime.now(ZoneInfo("Asia/Shanghai"))).astimezone(
            ZoneInfo("Asia/Shanghai")
        ).date() >= date.fromisoformat(rights["independent_permissions_expiry"]):
            rpm, source = (
                min(rpm, int(spec.get("requests_per_minute", 200))),
                "independent_expired_reverify",
            )
    elif api in SPECIAL:
        rpm, source = (
            (300 if points >= 10000 else 200 if points >= 5000 else 50),
            "points_special_doc290",
        )
    elif independent or api in UNKNOWN_APIS or api in ("factor_value", "factor_list"):
        rpm, source = (
            min(200, int(spec.get("requests_per_minute", 200))),
            "unknown_permission_conservative",
        )
    else:
        rpm, source = (
            (300 if points >= 10000 else 200 if points >= 2000 else 50),
            "points_unspecified_leaf_conservative",
        )
    page = spec.get("documented_requests_per_minute")
    tiers = spec.get("documented_rate_tiers", [])
    if tiers:
        qualified = [x["rpm"] for x in tiers if points >= x["minimum_points"]]
        page = max(qualified) if qualified else None
    if isinstance(page, dict):
        # Known contract metadata keys; unknown forms cannot lift a ceiling.
        import re

        qualified = [
            v
            for k, v in page.items()
            if re.fullmatch(r"\d+(?:_plus)?_points", k)
            and points >= int(k.split("_")[0])
        ]
        page = max(qualified) if qualified else None
    if api in PAGE_RPM:
        page = min(page, PAGE_RPM[api]) if type(page) is int else PAGE_RPM[api]
        if api in ("limit_step", "kpl_list") and points < 8000:
            page = 200
    if type(page) is int:
        page = positive_int(page, "documented API rate")
        if source.startswith("points_"):
            rpm = min(page, 500 if points >= 5000 else 200 if points >= 2000 else 50)
        else:
            rpm = min(rpm, page)
        source += "+per_page"
    override = config.get("api_requests_per_minute", {}).get(api)
    if override is not None:
        rpm = min(rpm, positive_int(override, "configured API rate"))
        source += "+config_ceiling"
    return {"rpm": positive_int(rpm, "resolved API rate"), "source": source}


def policy_report(config, now=None):
    if not enabled(config):
        return {"mode": "legacy"}
    return {
        "mode": POLICY,
        "account_ceiling": config.get("requests_per_minute", 240),
        "rollout_account_rpm": config.get("rollout_account_rpm"),
        "entitlement": entitlement(config, now),
        "cyq_perf_daily_cap": cyq_daily_limit(config, now),
        "daily_timezone": "Asia/Shanghai",
        "permission_grant": False,
    }


def cyq_daily_limit(config, now=None):
    points = entitlement(config, now)["effective_points_conservative"]
    return 200000 if points >= 10000 else 20000 if points >= 5000 else 0
