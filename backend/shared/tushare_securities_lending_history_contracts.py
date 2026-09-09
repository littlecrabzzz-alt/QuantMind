"""Stopped securities-lending series: pure, explicitly opt-in acquisition plans.

19900101 is an operational request boundary, not supplier inception or evidence
of complete history. No registration, account check, network or storage occurs.
"""

from datetime import date, datetime, timedelta

from backend.shared.tushare_equity_event_contracts import _stocks
from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "slb_sec": "trade_date ts_code name ope_inv lent_qnt cls_inv end_bal".split(),
    "slb_sec_detail": "trade_date ts_code name tenor fee_rate lent_qnt".split(),
    "slb_len_mm": "trade_date ts_code name ope_inv lent_qnt cls_inv end_bal".split(),
}
INPUT_FIELDS = {api: "trade_date ts_code start_date end_date".split() for api in FIELDS}
SOURCE_HTML_SHA256 = {
    "slb_sec": "28ee66199f7a09a60da2dfa160c062b20eee6560ce72ee3d99aeed9ce19cfaea",
    "slb_sec_detail": "6d3d20309972a86cf7c065093e3001ad4d7c6a8fb653ec5e14ced6b771952f43",
    "slb_len_mm": "74b9eab75f4defc5f25eb1332e97dc8e4b7b4f7b6133a74eb8a9ebbba32059ed",
}
_DOCS = {"slb_sec": 332, "slb_sec_detail": 333, "slb_len_mm": 334}
FIELD_METADATA = {}
SECURITIES_LENDING_HISTORY_CONTRACTS = {}
for _api, _fields in FIELDS.items():
    _descriptions = {
        "trade_date": ("str", "交易日期（YYYYMMDD）"),
        "ts_code": ("str", "股票代码"),
        "name": ("str", "股票名称"),
        "ope_inv": ("float", "期初余量(万股)"),
        "lent_qnt": (
            "float",
            "融出数量(万股)" if _api == "slb_len_mm" else "转融券融出数量(万股)",
        ),
        "cls_inv": ("float", "期末余量(万股)"),
        "end_bal": ("float", "期末余额(万元)"),
        "tenor": ("str", "期限(天)"),
        "fee_rate": ("float", "融出费率(%)"),
    }
    FIELD_METADATA[_api] = {
        field: {
            "type": _descriptions[field][0],
            "default": "Y",
            "description": _descriptions[field][1],
        }
        for field in _fields
    }
    _keys = ["trade_date", "ts_code"]
    if _api == "slb_sec_detail":
        _keys += ["tenor", "fee_rate"]
    _spec = _contract(
        5000,
        _keys,
        required=_fields,
        nullable=[field for field in _fields if field not in ("trade_date", "ts_code")],
        extra=_fields,
        rpm=30,
        cap_verified=False,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_DOCS[_api]}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        field_metadata=FIELD_METADATA[_api],
        input_fields=INPUT_FIELDS[_api],
        allowed_params=INPUT_FIELDS[_api],
        hidden_fields=[],
        default_date_field="trade_date",
        default_enabled=False,
        permission_status="unprobed",
        minimum_points=2000,
        independent_permission=None,
        documented_requests_per_minute={"2000_points": 200, "5000_points": 500},
        permission_note="Documented points tiers are not observed account entitlement; 30 rpm is a conservative operational ceiling, still subject to shared gates.",
        update_status="catalog_marked_stopped",
        stop_date=None,
        stop_note="Exact cessation date and current historical availability are unspecified. Do not infer API denial or a zero-row historical universe from stopped updates.",
        history_bound_verified=False,
        history_gap="official_earliest_date_unspecified",
        request_scope_note="Configured history_start (default 19900101 when explicitly enabled) is only a request boundary. It proves neither inception nor complete historical coverage.",
        dependencies=[],
        saturation_fallback="stocks",
        saturation_param="ts_code",
        saturation_dependencies=["stocks"],
        saturation_gap="Split date ranges first, then a saturated single date by actual observed historical stock codes. Incomplete discovery cannot prove full coverage; a capped single stock/day has no documented offset, limit, tenor or fee_rate partition parameter and stays unresolved.",
        preserve_distinct_rows=True,
        row_identity_note="Preserve all raw/unknown fields and content revisions. Detail natural keys include tenor and fee_rate; different payloads still require _row_identity in offline read keys. Never send derived identity upstream.",
        multiplicity_gap="No supplier row ID is documented. Identical raw rows retain multiplicity in capture, while a content-hash view alone cannot prove event counts.",
        pit_gap="trade_date is the economic date, not publication/known_at. Current historical response and local observed_at do not establish historical availability; no release clock is documented.",
        alias_note="These three datasets are distinct from each other and from financing aggregate slb_len; neither balances nor coverage may be substituted.",
        null_note="Known columns must be requested even when nullable. Null/zero/unknown source columns are retained without fill or coercion; tenor stays a supplier string.",
    )
    SECURITIES_LENDING_HISTORY_CONTRACTS[_api] = _spec


def _enabled(config):
    active = config.get("enable_securities_lending_history", False)
    if not isinstance(active, bool):
        raise ValueError("enable_securities_lending_history must be boolean")
    apis = config.get("securities_lending_history_apis", tuple(FIELDS))
    if not isinstance(apis, (list, tuple)) or any(
        not isinstance(api, str) or api not in FIELDS for api in apis
    ):
        raise ValueError("securities_lending_history_apis must list known APIs")
    return tuple(dict.fromkeys(apis)) if active else ()


def _starts(config, enabled):
    scope = config.get("securities_lending_history_start")
    if scope is not None and not isinstance(scope, (str, dict)):
        raise ValueError(
            "securities_lending_history_start must be a date or API mapping"
        )
    if isinstance(scope, dict) and scope.keys() - FIELDS.keys():
        raise ValueError("Unknown API in securities_lending_history_start")
    result = {}
    for api in enabled:
        value = scope.get(api) if isinstance(scope, dict) else scope
        if value is None:
            value = config.get("history_start", "19900101")
        result[api] = _parse(value)
    return result


def securities_lending_history_identifiers(identifiers=None):
    """Real stock master/observed identities only, including retired/T codes.

    No hardcoded sample, current-listing filter, guessed eligibility or renamed
    code. Parent discovery must union observed source stocks before fanout.
    """
    return {"stocks": _stocks({} if identifiers is None else identifiers)}


def securities_lending_history_prerequisites(
    identifiers=None, enabled_apis=None, config=None
):
    config = dict(config or {})
    if enabled_apis is not None:
        config["securities_lending_history_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    stocks = (
        securities_lending_history_identifiers(identifiers)["stocks"] if enabled else []
    )
    gaps = []
    for api in enabled:
        gaps.append(
            {
                "api_name": api,
                "dependencies": ["stocks"],
                "reason": "historical_universe_unverified"
                if stocks
                else "missing_stocks_for_saturated_day",
                "observed_codes": len(stocks),
            }
        )
        for reason in (
            "permission_unverified",
            "stopped_update_availability_unverified",
            "configured_scope_does_not_prove_earlier_history_absent",
            "pit_gap",
            "saturation_gap",
            "multiplicity_gap",
        ):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": reason,
                    "request_history_start": starts[api].strftime("%Y%m%d"),
                }
            )
    return gaps


def iter_securities_lending_history_jobs(config, today, identifiers=None):
    """Lazy date/API round robin, recent first; no trading-calendar shortcut.

    Stopped-series empty dates remain unverified. An explicit enable is required;
    unknown stop/inception is never replaced with a guessed history cutoff.
    Discovery is needed only for cap fallback, so missing stocks do not suppress
    all-market daily requests. Existing history epoch/logical keys remain stable.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    if not enabled:
        return
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for begin, end, priority, job_epoch in (
        (max(min(starts.values()), recent), today, 20, epoch),
        (min(starts.values()), recent - timedelta(days=1), 40, "history"),
    ):
        day = begin
        while day <= end:
            for api in enabled:
                if day >= starts[api]:
                    yield {
                        "api_name": api,
                        "params": {"trade_date": day.strftime("%Y%m%d")},
                        "priority": priority,
                        "epoch": job_epoch,
                    }
            day += timedelta(days=1)
