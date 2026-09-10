"""Current official public read-only contracts found outside the frozen index."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse


FIELDS = {
    "film_record": "rec_no film_name rec_org script_writer rec_result rec_area classified date_range ann_date".split(),
    "teleplay_record": "name classify types org report_date license_key episodes shooting_date prod_cycle content pro_opi dept_opi remarks".split(),
    "bo_monthly": "date name list_date avg_price month_amount list_day p_pc wom_index m_ratio rank".split(),
    "bo_weekly": "date name avg_price week_amount total list_day p_pc wom_index up_ratio rank".split(),
    "bo_daily": "date name avg_price day_amount total list_day p_pc wom_index up_ratio rank".split(),
    "bo_cinema": "date c_name aud_count att_ratio day_amount day_showcount avg_price p_pc rank".split(),
    "fund_sales_ratio": "year bank sec_comp fund_comp indep_comp rests".split(),
    "fund_sales_vol": "year quarter inst_name fund_scale scale rank".split(),
}

INPUT_FIELDS = {
    "film_record": ["ann_date", "start_date", "end_date"],
    "teleplay_record": ["report_date", "start_date", "end_date", "org", "name"],
    "bo_monthly": ["date"],
    "bo_weekly": ["date"],
    "bo_daily": ["date"],
    "bo_cinema": ["date"],
    # The current table labels this input in Chinese and the example is
    # unfiltered. Do not invent a wire name from the output column.
    "fund_sales_ratio": [],
    "fund_sales_vol": ["year", "quarter", "name"],
}

_DOCS = {
    "film_record": (
        156,
        500,
        120,
        None,
        "ae01d7d43283ddce615b2396b8128c727c242cb8dc1ea803470c8b6bcdb874d9",
        "9e1db3aacbc3fcea52490d79e0091ac1375cece7e432cdaf88f342ee6f1a1253",
    ),
    "teleplay_record": (
        180,
        1000,
        600,
        "20090101",
        "d9006e0885d400b25a844d0a09673bc6a9f769c8fde513868b4e3d8b923dc152",
        "25a717294d849869bd32c726a6b5fc1a081266808b301f70ad782d7c41a76ee1",
    ),
    "bo_monthly": (
        113,
        1000,
        500,
        "20080101",
        "ce6deb35f51c0b9589643f3b36adc5d58dfc2098b3b5df42391361302e17a579",
        "a32a92a05ef308d82127f3be47daf298eef25b59e34a06b5b067439fa495f799",
    ),
    "bo_weekly": (
        114,
        1000,
        500,
        "20080101",
        "b239a24ae7e8ccad2a020494c6f956ed43f256ee70fa2b985011fc2686e12c38",
        "c53b5175a2c71ab5d9b5ff8a071d4badd8948a651f96fcb40d1230b11a483bb5",
    ),
    "bo_daily": (
        115,
        1000,
        500,
        "20180901",
        "3ba68a95f550a4142feb94aa99159cc61985ec4d1c0bedd3efdecfc0326be78f",
        "9a519590a676cb87e838d4fa55ba0cad49df8c2031e99dbc6d96ba6ae4386fb3",
    ),
    "bo_cinema": (
        116,
        1000,
        500,
        "20180901",
        "a3c1aa247402a93124a924884f6d199b6977228a44b6706f7928a79983962855",
        "a4fd1ebe9b704f524d4031b4e5578b181218d3e09cb658d5aef2b28cf295cf95",
    ),
    "fund_sales_ratio": (
        265,
        100,
        None,
        "20150101",
        "12265eab1aeaf510fb51956d7a695ecec808ce8f52fa16fc4429b00046bd6de0",
        "4404527d1f1fc1fabb661ee34ec2ea12198bf1c1d9849128c9d8f6fa9f723b9a",
    ),
    "fund_sales_vol": (
        266,
        500,
        None,
        "20210101",
        "2b39c7688fe216b9e1cdd52cf0490c39454868f09dfa5108e997850eff5ff6cf",
        "d0663b517e919e7384c1636231cc4c8da0bf71b4703c37d8bf6945434b6143e9",
    ),
}

_KEYS = {
    "film_record": ("rec_no", "film_name", "ann_date"),
    "teleplay_record": ("report_date", "license_key", "name", "org"),
    "bo_monthly": ("date", "name", "rank"),
    "bo_weekly": ("date", "name", "rank"),
    "bo_daily": ("date", "name", "rank"),
    "bo_cinema": ("date", "c_name", "rank"),
    "fund_sales_ratio": ("year",),
    "fund_sales_vol": ("year", "quarter", "inst_name", "rank"),
}

OFFCATALOG_CONTRACTS = {}
for _api, (_doc, _cap, _points, _start, _markdown_sha, _html_sha) in _DOCS.items():
    _spec = _contract(
        _cap,
        _KEYS[_api],
        nullable=tuple(field for field in FIELDS[_api] if field not in _KEYS[_api]),
        split=_api == "film_record",
        start=_start,
        rpm=30,
        extra=FIELDS[_api],
        cap_verified=_api
        in ("film_record", "teleplay_record", "fund_sales_ratio", "fund_sales_vol"),
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_markdown_url=f"https://tushare.pro/wctapi/documents/{_doc}.md",
        source_markdown_sha256=_markdown_sha,
        source_html_sha256=_html_sha,
        official_reference_commit="b68d5517e0cbe84d61774de26ad366d900c7eb92",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api],
        hidden_fields=[],
        permission_status="unprobed",
        independent_permission=False,
        minimum_points=_points,
        documented_requests_per_minute=None,
        rate_note="30/min is a conservative local ceiling; the current page publishes no numeric minute rate.",
        date_field=(
            "ann_date"
            if _api == "film_record"
            else "report_date"
            if _api == "teleplay_record"
            else "year"
            if _api.startswith("fund_sales_")
            else "date"
        ),
        documented_history_start=_start,
        history_bound_verified=False,
        history_gap=(
            "The current page gives no earliest record. Configured scope and later observations cannot prove earlier absence."
            if _start is None
            else "The documented lower bound does not prove every period, later corrections, deletions or historical availability."
        ),
        pit_gap="Source dates/periods and observed_at remain separate. Neither proves original publication time, revision time or historical point-in-time availability.",
        field_selection_note="Request every current documented output field explicitly; preserve additional returned columns and nullable source values.",
        field_gaps={
            field: ["live_presence_nullable_revision_semantics_unverified"]
            for field in FIELDS[_api]
        },
        dependencies=[],
        preserve_distinct_rows=True,
        saturation_dependencies=[],
        refresh_gap="Finite recent overlap does not certify older corrections or removed source rows.",
    )
    OFFCATALOG_CONTRACTS[_api] = _spec

for _api in ("bo_monthly", "bo_weekly", "bo_daily", "bo_cinema"):
    OFFCATALOG_CONTRACTS[_api].update(
        row_cap_verified=False,
        row_cap_basis="local 1000-row saturation alarm; the current page states no numerical cap",
        saturation_gap="No offset or additional legal partition is documented beyond exact date. A saturated date remains incomplete.",
        ranking_note="Ranks and title/cinema names are source labels, not stable entity identifiers. Keep distinct rows and observations.",
    )
OFFCATALOG_CONTRACTS["film_record"].update(
    required_one_of=["ann_date", "start_date"],
    saturation_gap="Bisect only the documented announcement date range. A saturated exact day remains incomplete; no offset exists.",
    identity_gap="No immutable item ID is documented beyond filing number and labels. Preserve distinct source rows and revisions.",
)
OFFCATALOG_CONTRACTS["teleplay_record"].update(
    date_precision="month",
    saturation_gap="A saturated exact month remains incomplete. Organization and title are optional filters, but no exhaustive value universe is documented.",
    unit_gap="episodes is documented as text and production/shooting periods are supplier labels; do not coerce them into numeric dates or durations.",
)
for _api in ("bo_monthly", "bo_weekly", "bo_daily"):
    OFFCATALOG_CONTRACTS[_api]["unit_note"] = (
        "Ticket price and box office amounts retain the documented source units; "
        "ratios are percentages and must not be rescaled or filled."
    )
OFFCATALOG_CONTRACTS["bo_cinema"]["unit_note"] = (
    "avg_price is CNY and att_ratio is a source ratio; the page gives no unit for "
    "day_amount. Preserve source values without inferred conversion."
)
OFFCATALOG_CONTRACTS["fund_sales_ratio"].update(
    acquisition_gap="The current input table labels the optional parameter as Chinese '年份'; only the documented unfiltered example is planned until the actual wire name is verified.",
    saturation_gap="A 100-row unfiltered response at cap remains incomplete because no verified wire parameter or pagination exists.",
    unit_note="All five channel values are percentages. Do not force a total of 100 or fill missing categories.",
)
OFFCATALOG_CONTRACTS["fund_sales_vol"].update(
    saturation_gap="A saturated year-quarter remains incomplete. The optional name filter has no exhaustive institution universe and cannot prove full coverage.",
    quarter_note="quarter is a source label such as Q1. fund_scale and scale are CNY 100-million; rank is based on fund_scale rounded to 0.01 according to the page.",
)


def _selected(config):
    selected = config.get("offcatalog_apis", [])
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(api, str) or api not in OFFCATALOG_CONTRACTS for api in selected
    ):
        raise ValueError("offcatalog_apis must list reviewed OFFCATALOG_CONTRACTS APIs")
    return tuple(dict.fromkeys(selected))


def _month_start(value):
    return value.replace(day=1)


def _previous_month(value):
    return (value.replace(day=1) - timedelta(days=1)).replace(day=1)


def _months(start, end):
    value = _month_start(start)
    while value <= end:
        yield value
        value = (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _quarters(start, end):
    value = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    while value <= end:
        yield value
        month = value.month + 3
        value = date(value.year + (month > 12), month - 12 if month > 12 else month, 1)


def _job(api, params, priority, epoch):
    return {"api_name": api, "params": params, "priority": priority, "epoch": epoch}


def _recent(api, today, epoch):
    if api == "fund_sales_ratio":
        yield _job(api, {}, 20, epoch)
    elif api == "fund_sales_vol":
        for value in list(_quarters(date(today.year - 1, 1, 1), today))[-2:]:
            yield _job(
                api,
                {"year": str(value.year), "quarter": f"Q{(value.month - 1) // 3 + 1}"},
                20,
                epoch,
            )
    elif api in ("film_record", "teleplay_record", "bo_monthly"):
        for value in (_previous_month(today), _month_start(today)):
            if api == "film_record":
                end = min(
                    today, value.replace(day=monthrange(value.year, value.month)[1])
                )
                params = {
                    "start_date": value.strftime("%Y%m%d"),
                    "end_date": end.strftime("%Y%m%d"),
                }
            elif api == "teleplay_record":
                params = {"report_date": value.strftime("%Y%m")}
            else:
                params = {"date": value.strftime("%Y%m01")}
            yield _job(api, params, 20, epoch)
    elif api == "bo_weekly":
        monday = today - timedelta(days=today.weekday())
        for value in (monday - timedelta(days=7), monday):
            yield _job(api, {"date": value.strftime("%Y%m%d")}, 20, epoch)
    else:
        for offset in range(6, -1, -1):
            value = today - timedelta(days=offset)
            yield _job(api, {"date": value.strftime("%Y%m%d")}, 20, epoch)


def _history(api, start, today):
    if api == "fund_sales_ratio":
        return
    recent_month = _previous_month(today)
    if api == "film_record":
        for value in _months(start, recent_month - timedelta(days=1)):
            yield _job(
                api,
                {
                    "start_date": value.strftime("%Y%m%d"),
                    "end_date": value.replace(
                        day=monthrange(value.year, value.month)[1]
                    ).strftime("%Y%m%d"),
                },
                40,
                "history",
            )
    elif api in ("teleplay_record", "bo_monthly"):
        for value in _months(start, recent_month - timedelta(days=1)):
            key = "report_date" if api == "teleplay_record" else "date"
            fmt = "%Y%m" if api == "teleplay_record" else "%Y%m01"
            yield _job(api, {key: value.strftime(fmt)}, 40, "history")
    elif api == "fund_sales_vol":
        current = list(_quarters(date(today.year - 1, 1, 1), today))[-2]
        for value in _quarters(start, current - timedelta(days=1)):
            yield _job(
                api,
                {"year": str(value.year), "quarter": f"Q{(value.month - 1) // 3 + 1}"},
                40,
                "history",
            )
    elif api == "bo_weekly":
        value = start + timedelta(days=(-start.weekday()) % 7)
        last = today - timedelta(days=today.weekday() + 14)
        while value <= last:
            yield _job(api, {"date": value.strftime("%Y%m%d")}, 40, "history")
            value += timedelta(days=7)
    else:
        value = start
        last = today - timedelta(days=6)
        while value < last:
            yield _job(api, {"date": value.strftime("%Y%m%d")}, 40, "history")
            value += timedelta(days=1)


def iter_offcatalog_jobs(config, today, identifiers=None):
    """Default-empty, recent-first, lazy historical planning."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    selected = _selected(config)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for api in selected:
        yield from _recent(api, today, epoch)
    histories = {}
    setting = config.get("offcatalog_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("offcatalog_history_start must be a date or API mapping")
    if isinstance(setting, dict) and set(setting) - OFFCATALOG_CONTRACTS.keys():
        raise ValueError("Unknown API in offcatalog_history_start")
    for api in selected:
        raw = setting.get(api) if isinstance(setting, dict) else setting
        raw = raw if raw is not None else OFFCATALOG_CONTRACTS[api]["history_start"]
        start = _parse(raw) if raw is not None else None
        floor = OFFCATALOG_CONTRACTS[api]["history_start"]
        if floor:
            start = max(start or _parse(floor), _parse(floor))
        if start and start > today:
            raise ValueError("History start cannot be after today")
        if start:
            histories[api] = iter(_history(api, start, today))
    while histories:
        for api in tuple(histories):
            job = next(histories[api], None)
            if job is None:
                del histories[api]
            else:
                yield job


def offcatalog_prerequisites(config=None):
    gaps = []
    for api in _selected(config or {}):
        spec = OFFCATALOG_CONTRACTS[api]
        if spec["permission_status"] != "available_observed":
            gaps.append(
                {"api_name": api, "reason": "permission_unprobed", "dependencies": []}
            )
        for reason in (
            "history_gap",
            "pit_gap",
            "saturation_gap",
            "refresh_gap",
            "acquisition_gap",
            "identity_gap",
            "unit_gap",
        ):
            if spec.get(reason):
                gaps.append(
                    {
                        "api_name": api,
                        "reason": reason,
                        "detail": spec[reason],
                        "dependencies": [],
                    }
                )
    return gaps
