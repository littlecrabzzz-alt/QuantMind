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
# Explicit category audit, never the complement of the registered API set.
# docs/tushare-general-rate-refinement.json SHA256
# f0e1b6adca065edf6a77eecd9f72029308872fe9f7055603e83b45584af53bbe
REGULAR_APIS = frozenset(
    [
        "adj_factor",
        "bak_basic",
        "bak_daily",
        "balancesheet_vip",
        "bc_bestotcqt",
        "bc_otcqt",
        "block_trade",
        "bond_blk",
        "bond_blk_detail",
        "bse_mapping",
        "cashflow_vip",
        "cb_basic",
        "cb_call",
        "cb_daily",
        "cb_issue",
        "cb_rate",
        "cb_rating",
        "cb_share",
        "ci_daily",
        "ci_index_member",
        "cn_cpi",
        "cn_gdp",
        "cn_m",
        "cn_pmi",
        "cn_ppi",
        "cn_schedule",
        "daily_basic",
        "daily_info",
        "dc_daily",
        "dc_hot",
        "dc_index",
        "dc_member",
        "disclosure_date",
        "dividend",
        "eco_cal",
        "etf_basic",
        "etf_index",
        "etf_limit",
        "etf_sh_cons",
        "etf_share_size",
        "etf_sz_cons",
        "express_vip",
        "fina_audit",
        "fina_indicator_vip",
        "fina_mainbz",
        "forecast_vip",
        "ft_limit",
        "fund_adj",
        "fund_basic",
        "fund_company",
        "fund_daily",
        "fund_div",
        "fund_manager",
        "fund_nav",
        "fund_share",
        "fut_basic",
        "fut_daily",
        "fut_daily_adj",
        "fut_holding",
        "fut_index_daily",
        "fut_mapping",
        "fut_settle",
        "fut_trade_cal",
        "fut_weekly_detail",
        "fut_wsr",
        "fx_daily",
        "fx_obasic",
        "gz_index",
        "hibor",
        "hm_list",
        "idx_anns",
        "income_vip",
        "index_basic",
        "index_classify",
        "index_daily",
        "index_dailybasic",
        "index_global",
        "index_member_all",
        "index_monthly",
        "index_weekly",
        "index_weight",
        "kpl_concept_cons",
        "libor",
        "margin",
        "margin_detail",
        "margin_secs",
        "mkt_idx_bmk",
        "moneyflow",
        "moneyflow_cnt_ths",
        "moneyflow_dc",
        "moneyflow_ind_dc",
        "moneyflow_ind_ths",
        "moneyflow_mkt_dc",
        "moneyflow_ths",
        "monthly",
        "new_share",
        "opt_basic",
        "opt_daily",
        "pledge_detail",
        "pledge_stat",
        "repo_daily",
        "repurchase",
        "sf_month",
        "sge_basic",
        "sge_daily",
        "share_float",
        "shibor",
        "shibor_lpr",
        "shibor_quote",
        "st",
        "stk_account",
        "stk_account_old",
        "stk_alert",
        "stk_high_shock",
        "stk_holdernumber",
        "stk_holdertrade",
        "stk_limit",
        "stk_managers",
        "stk_rewards",
        "stk_shock",
        "stk_week_month_adj",
        "stk_weekly_monthly",
        "stock_company",
        "stock_hsgt",
        "stock_st",
        "suspend_d",
        "sw_daily",
        "sz_daily_info",
        "tdx_daily",
        "tdx_index",
        "tdx_member",
        "ths_daily",
        "ths_hot",
        "ths_index",
        "top10_cb_holders",
        "top10_floatholders",
        "top10_holders",
        "top_inst",
        "top_list",
        "trade_cal",
        "us_tbr",
        "us_tltr",
        "us_trltr",
        "us_trycr",
        "us_tycr",
        "weekly",
        "wz_index",
    ]
)
UNKNOWN_APIS = {
    "namechange",
    "us_tradecal",
    "us_basic",
    "hm_detail",
    "hk_tradecal",
    "hsgt_top10",
    "fut_weekly_monthly",
    "hk_basic",
}
SPECIAL = {
    "broker_recommend",
    "cyq_chips",
    "stk_ah_comparison",
    "stk_surv",
    "report_rc",
    "stk_nineturn",
    "cyq_perf",
}


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
            (
                300
                if points >= 10000
                else min(
                    200 if points >= 5000 else 50,
                    int(spec.get("requests_per_minute", 200)),
                )
            ),
            "points_special_doc290"
            if points >= 10000
            else "special_points_review_required",
        )
    elif independent or api in UNKNOWN_APIS or api in ("factor_value", "factor_list"):
        rpm, source = (
            min(200, int(spec.get("requests_per_minute", 200))),
            "unknown_permission_conservative",
        )
    elif api in REGULAR_APIS:
        rpm, source = (
            (500 if points >= 5000 else 200 if points >= 2000 else 50),
            "points_regular_allowlist_doc290",
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
    minimum = spec.get("minimum_points")
    unmet = type(minimum) is int and points < minimum
    review = unmet or source.startswith(
        (
            "unknown_",
            "special_points_review",
            "independent_expired",
            "points_unspecified",
        )
    )
    return {
        "rpm": positive_int(rpm, "resolved API rate"),
        "source": source,
        "review_required": review,
        "review_reason": "points_below_documented_minimum"
        if unmet
        else "entitlement_or_leaf_requires_review"
        if review
        else None,
    }


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
