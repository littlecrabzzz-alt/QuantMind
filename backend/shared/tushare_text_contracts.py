"""Reviewed text contracts and streaming plans; no credentials, I/O or acquisition.

Official documentation checked 2026-09-09. ``history_start=None`` means unknown,
not no history. Source/permission/attachment completion must be measured by the
pipeline; producing a plan does not prove that the supplier returned all rows.
"""

from datetime import date, datetime, timedelta

NEWS_SOURCES = (
    "sina",
    "wallstreetcn",
    "10jqka",
    "eastmoney",
    "yuncaijing",
    "fenghuang",
    "jinrongjie",
    "cls",
    "yicai",
)
MAJOR_NEWS_SOURCES = (
    "新华网",
    "凤凰财经",
    "同花顺",
    "新浪财经",
    "华尔街见闻",
    "中证网",
    "财新网",
    "第一财经",
    "财联社",
)


def _contract(
    cap,
    fields,
    keys,
    *,
    nullable=(),
    rpm=500,
    precision="day",
    history=None,
    attachments=(),
    extra=(),
    split=True,
):
    return {
        "row_cap": cap,
        "required_fields": fields.split(),
        "nullable_fields": list(nullable),
        "positive_fields": [],
        "keys": keys.split(),
        "requests_per_minute": rpm,
        "split": {
            "start_param": "start_date",
            "end_param": "end_date",
            "precision": precision,
        }
        if split
        else None,
        "history_start": history,
        "attachment_fields": list(attachments),
        "extra_fields": list(extra),
    }


TEXT_CONTRACTS = {
    "news": _contract(
        1500,
        "datetime content title channels",
        "_source datetime title content",
        nullable=("title", "channels"),
        rpm=400,
        precision="second",
    ),
    "major_news": _contract(
        400,
        "title content pub_time src",
        "src pub_time title content",
        nullable=("src",),
        rpm=400,
        precision="second",
    ),
    "cctv_news": _contract(
        1000,
        "date title content",
        "date title content",
        rpm=400,
        history="20170101",
        split=False,
    ),
    "anns_d": _contract(
        2000,
        "ann_date ts_code name title url rec_time",
        "ann_date ts_code title url",
        nullable=("name", "rec_time", "url"),
        attachments=("url",),
    ),
    "irm_qa_sh": _contract(
        3000,
        "ts_code name trade_date q a pub_time",
        "ts_code trade_date q a pub_time",
        nullable=("name", "a", "pub_time"),
        history="20230601",
    ),
    "irm_qa_sz": _contract(
        3000,
        "ts_code name trade_date q a pub_time industry",
        "ts_code trade_date q a pub_time",
        nullable=("name", "a", "pub_time", "industry"),
        history="20101001",
    ),
    "npr": _contract(
        500,
        "pubtime title url content_html pcode puborg ptype",
        "pubtime title url content_html",
        nullable=("url", "content_html", "pcode", "puborg", "ptype"),
        precision="second",
        attachments=("url",),
    ),
    "research_report": _contract(
        1000,
        "trade_date abstr title report_type author name ts_code inst_csname ind_name url",
        "trade_date title inst_csname url abstr",
        nullable=(
            "abstr",
            "author",
            "name",
            "ts_code",
            "inst_csname",
            "ind_name",
            "url",
        ),
        history="20170101",
        attachments=("url",),
        extra=("file_name",),
    ),
    "monetary_policy": _contract(
        1000,
        "pub_date title url pdf_url content_html",
        "pub_date title url",
        nullable=("url", "pdf_url", "content_html"),
        rpm=200,
        history="20010101",
        attachments=("url", "pdf_url"),
    ),
}

# Machine-readable exceptions are part of the contract, not completeness waivers.
TEXT_CONTRACT_NOTES = {
    "news": {
        "doc_id": "143",
        "history_status": "unknown_exact_start; description says over 6 years",
        "source_status": "nine documented sources; per-source live permission unverified",
        "hidden_fields": ["channels"],
        "coverage_gaps": ["supplier has no stable news id or independent total"],
    },
    "major_news": {
        "doc_id": "195",
        "history_status": "unknown_exact_start; description says over 8 years",
        "source_status": "nine listed sources plus unfiltered sweep; examples contain other sources",
        "hidden_fields": ["content"],
        "coverage_gaps": [
            "sample uses src_site but output table uses src; inspect returned schema"
        ],
    },
    "cctv_news": {
        "doc_id": "154",
        "history_status": "documented year 2017; first actual day unknown",
        "row_cap_status": "undocumented; 1000 is a conservative truncation alarm, not vendor limit",
        "coverage_gaps": ["date-only API cannot split a capped single day"],
    },
    "anns_d": {
        "doc_id": "176",
        "history_status": "unknown_exact_start; entitlement table says over 10 years",
        "hidden_fields": ["rec_time"],
        "coverage_gaps": [
            "capped day requires exhaustive instrument universe including funds and fixed income",
            "download URL availability is not successful PDF download or parsing",
        ],
    },
    "irm_qa_sh": {
        "doc_id": "366",
        "history_status": "documented month 2023-06; first actual day unknown",
        "coverage_gaps": [
            "sample ann_date conflicts with parameter table; use documented start_date/end_date",
            "pub_start/pub_end filter another time axis; cannot replace trade_date coverage",
            "seven-day lookback does not guarantee capture of very late replies to old questions",
        ],
    },
    "irm_qa_sz": {
        "doc_id": "367",
        "history_status": "documented month 2010-10; entitlement table conflicts (25 years)",
        "coverage_gaps": [
            "sample ann_date conflicts with parameter table; use documented start_date/end_date",
            "pub_time is response time; unanswered and late replies need separate coverage",
            "sample six-digit code requires normalization with known exchange, preserve original",
        ],
    },
    "npr": {
        "doc_id": "406",
        "history_status": "unknown_exact_start",
        "hidden_fields": ["url", "content_html"],
        "source_status": "omit org and ptype to cover all; docs only give partial category examples",
        "coverage_gaps": [
            "HTML may contain linked attachments that need independent discovery"
        ],
    },
    "research_report": {
        "doc_id": "415",
        "history_status": "documented exact start 2017-01-01",
        "source_status": "unfiltered covers stock/industry and unknown future types",
        "coverage_gaps": [
            "file_name appears in official fields example only; request it and audit support",
            "capped single day requires report_type and exhaustive institution/code partitions",
        ],
    },
    "monetary_policy": {
        "doc_id": "465",
        "history_status": "documented year 2001; first actual day unknown",
        "coverage_gaps": [
            "HTML and PDF links must each be saved and validated independently"
        ],
    },
}


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) != 8 or not value.isdecimal():
        raise ValueError("Expected YYYYMMDD date")
    return datetime.strptime(value, "%Y%m%d").date()


def _params(api, day):
    if api == "cctv_news":
        return {"date": day.strftime("%Y%m%d")}
    if TEXT_CONTRACTS[api]["split"]["precision"] == "second":
        # Shared midnight boundaries deliberately overlap: supplier inclusivity
        # is undocumented; storage deduplicates identical rows by identity.
        return {
            "start_date": day.isoformat() + " 00:00:00",
            "end_date": (day + timedelta(days=1)).isoformat() + " 00:00:00",
        }
    value = day.strftime("%Y%m%d")
    return {"start_date": value, "end_date": value}


def iter_text_jobs(config, today):
    """Yield all source/windows, recent first; historical monetary reports yearly.

    ``text_apis`` defaults to all nine. ``history_start`` is required (or use
    ``text_history_start``); ``text_history_starts`` optionally overrides each
    API. These are requested coverage bounds, never inferred supplier bounds.
    Known published beginnings narrow earlier empty windows only. Unknown
    beginnings remain explicit gaps; optional-date APIs also get an unbounded
    prefix query to discover records before the configured start.

    ``planning_epoch`` overrides recent acquisition epochs for intraday refresh.
    Includes today (possibly incomplete) and six previous days in the recent
    epoch. All other days use epoch='history'. Callers persist job identities,
    paginate/split capped responses, and keep ongoing-day coverage incomplete.
    """
    today = _date(today)
    selected = tuple(config.get("text_apis", TEXT_CONTRACTS))
    if len(set(selected)) != len(selected) or set(selected) - TEXT_CONTRACTS.keys():
        raise ValueError("Unknown or duplicate text API")
    overrides = config.get("text_history_starts", {})
    if set(overrides) - TEXT_CONTRACTS.keys():
        raise ValueError("Unknown text history override")
    configured_start = _date(
        config.get("text_history_start", config.get("history_start"))
    )
    starts = {}
    for api in selected:
        start = _date(overrides.get(api, configured_start))
        if start > today:
            raise ValueError("History start is after today")
        documented = TEXT_CONTRACTS[api]["history_start"]
        starts[api] = max(start, _date(documented)) if documented else start
    recent_start = today - timedelta(days=6)
    oldest = min(starts.values(), default=today)
    # Streaming, newest day first. Iteration/resume state belongs to the parent.
    day = today
    while day >= oldest:
        recent = day >= recent_start
        for api in selected:
            if day < starts[api]:
                continue
            sources = (
                NEWS_SOURCES
                if api == "news"
                else ((None,) + MAJOR_NEWS_SOURCES if api == "major_news" else (None,))
            )
            for source in sources:
                if api == "monetary_policy" and not recent:
                    # Four reports/year: one historical year window avoids
                    # thousands of empty daily requests; recent remains daily.
                    end = min(date(day.year, 12, 31), recent_start - timedelta(days=1))
                    if day != end:
                        continue
                    params = {
                        "start_date": max(date(day.year, 1, 1), starts[api]).strftime(
                            "%Y%m%d"
                        ),
                        "end_date": day.strftime("%Y%m%d"),
                    }
                else:
                    params = _params(api, day)
                if source is not None:
                    params["src"] = source
                yield {
                    "api_name": api,
                    "params": params,
                    "priority": 20 if recent else 40,
                    "epoch": str(config.get("planning_epoch", today.strftime("%Y%m%d")))
                    if recent
                    else "history",
                }
            if recent and api in ("irm_qa_sh", "irm_qa_sz"):
                # Catch today's replies to questions outside the seven-day
                # question-date window; neither axis replaces the other.
                yield {
                    "api_name": api,
                    "params": {
                        "pub_start": day.isoformat() + " 00:00:00",
                        "pub_end": (day + timedelta(days=1)).isoformat() + " 00:00:00",
                    },
                    "priority": 20,
                    "epoch": str(
                        config.get("planning_epoch", today.strftime("%Y%m%d"))
                    ),
                }
        day -= timedelta(days=1)
    # Optional-date APIs can query everything before the requested start. Keep
    # capped prefixes unresolved until an earlier bound can be established.
    for api in selected:
        if TEXT_CONTRACTS[api]["history_start"] is not None or api == "news":
            continue
        end = starts[api] - timedelta(days=1)
        precision = TEXT_CONTRACTS[api]["split"]["precision"]
        end_value = (
            end.isoformat() + " 23:59:59"
            if precision == "second"
            else end.strftime("%Y%m%d")
        )
        sources = (None,) + MAJOR_NEWS_SOURCES if api == "major_news" else (None,)
        for source in sources:
            params = {"end_date": end_value}
            if source is not None:
                params["src"] = source
            yield {
                "api_name": api,
                "params": params,
                "priority": 40,
                "epoch": "history",
            }
