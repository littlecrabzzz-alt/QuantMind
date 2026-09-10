"""Reviewed legacy Connect contracts with deliberately bounded acquisition.

The official pages now return a missing-document body.  Only fields and inputs
preserved by archived primary evidence are represented; unknown columns,
history and point-in-time semantics remain explicit gaps.
"""

from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse


FIELDS = {
    "moneyflow_hsgt": [
        "trade_date",
        "ggt_ss",
        "ggt_sz",
        "hgt",
        "sgt",
        "north_money",
        "south_money",
    ],
    "ggt_daily": [
        "trade_date",
        "buy_amount",
        "buy_volume",
        "sell_amount",
        "sell_volume",
    ],
    "ggt_top10": [
        "trade_date",
        "ts_code",
        "name",
        "close",
        "p_change",
        "rank",
        "market_type",
        "amount",
        "net_amount",
        "sh_amount",
        "sh_net_amount",
        "sh_buy",
        "sh_sell",
        "sz_amount",
        "sz_net_amount",
        "sz_buy",
        "sz_sell",
    ],
}

INPUT_FIELDS = {
    # trade_date is also proven by the archived successful request.  The range
    # names come from a historical official-page cache, so the planner stays on
    # exact days until range behavior is validated again.
    "moneyflow_hsgt": ["trade_date", "start_date", "end_date"],
    "ggt_daily": ["trade_date", "start_date", "end_date"],
    "ggt_top10": ["trade_date"],
}

_DOCS = {"moneyflow_hsgt": 47, "ggt_daily": 196, "ggt_top10": 49}
_MISSING_BODY_SHA256 = (
    "bbf4318386ca0ea4c5072fc5e67fe0302f473ccbeba7238c45607226236dfadf"
)

LEGACY_CONNECT_CONTRACTS = {}
for _api in FIELDS:
    _keys = (
        ("trade_date", "ts_code", "market_type")
        if _api == "ggt_top10"
        else ("trade_date",)
    )
    _spec = _contract(
        1000,
        _keys,
        required=_keys,
        nullable=tuple(field for field in FIELDS[_api] if field not in _keys),
        split=False,
        rpm=30,
        extra=FIELDS[_api],
        cap_verified=False,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_DOCS[_api]}",
        source_content_status="document_missing_http_200",
        source_html_sha256=_MISSING_BODY_SHA256,
        source_evidence="config/tushare-coverage-ledger.json",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api],
        hidden_fields=[],
        date_field="trade_date",
        permission_status="available_observed",
        independent_permission=None,
        minimum_points=None,
        documented_requests_per_minute=None,
        rate_note="30/min is a local conservative ceiling; no current official minute quota or points threshold is retained for this API.",
        row_cap_basis="local_guard; 1000 is not a verified supplier maximum",
        history_bound_verified=False,
        history_gap="No exact oldest source record or complete historical revision/deletion coverage is proven.",
        pit_gap="trade_date is a source data date. The retained fetch time does not prove historical publication availability or revisions.",
        hidden_field_gap="The successful raw request used fields='' and proves only the returned default columns. Hidden/default-N and future columns remain unknown and must be preserved if observed.",
        field_gaps={
            field: [
                "type_unit_nullable_semantics_unverified",
                "historical_revision_semantics_unverified",
            ]
            for field in FIELDS[_api]
        },
        saturation_gap="A response at the 1000-row local guard remains incomplete. No offset or unverified range parameter may be invented.",
        refresh_gap="A later observation cannot certify corrections or deletions outside the finite overlap window.",
        dependencies=[],
        saturation_dependencies=[],
    )
    LEGACY_CONNECT_CONTRACTS[_api] = _spec

LEGACY_CONNECT_CONTRACTS["moneyflow_hsgt"].update(
    observed_request={"trade_date": "20260904"},
    observed_default_fields=FIELDS["moneyflow_hsgt"],
    observed_rows=1,
    observed_probe_release_id="probe-bf606f5acd14434db107a47f29051143",
    observed_range_request={"start_date": "20260903", "end_date": "20260904"},
    observed_range_rows=2,
    observed_probe_report_sha256="198c728ab4ccdc189c758c1be22d2d447ef375ae0c1740408551acaee12fc380",
    date_filter_status="trade_date_observed; start_date/end_date_historical_cache_only",
    unit_gap="The retained evidence does not define currency/scales or gross/net relationships. Preserve supplier numbers without deriving totals or filling nulls.",
)
LEGACY_CONNECT_CONTRACTS["ggt_daily"].update(
    observed_request={"trade_date": "20260904"},
    observed_default_fields=FIELDS["ggt_daily"],
    observed_rows=1,
    observed_has_more=False,
    observed_date_span=["20220523", "20260904"],
    observed_probe_report_sha256="198c728ab4ccdc189c758c1be22d2d447ef375ae0c1740408551acaee12fc380",
    previous_unfiltered_observation={
        "rows": 1000,
        "has_more": True,
        "date_span": ["20220526", "20260907"],
        "probe_release_id": "probe-bf606f5acd14434db107a47f29051143",
    },
    date_filter_status="trade_date and bounded start_date/end_date observed",
    unit_gap="Amount and volume scales/currencies are absent from retained primary evidence. Daily values must not be aggregated into the distinct ggt_monthly obligation.",
)
LEGACY_CONNECT_CONTRACTS["ggt_top10"].update(
    observed_request={"trade_date": "20260904"},
    observed_default_fields=FIELDS["ggt_top10"],
    observed_rows=20,
    observed_has_more=False,
    observed_probe_report_sha256="198c728ab4ccdc189c758c1be22d2d447ef375ae0c1740408551acaee12fc380",
    date_filter_status="trade_date observed",
    unit_gap="The retained response does not define currency, amount scale, market_type enumeration or adjusted-price semantics. Preserve values and request identity without cross-market aggregation.",
)


def _selected(config):
    selected = config.get("legacy_connect_apis", [])
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(api, str) or api not in LEGACY_CONNECT_CONTRACTS
        for api in selected
    ):
        raise ValueError(
            "legacy_connect_apis must list reviewed LEGACY_CONNECT_CONTRACTS APIs"
        )
    return list(dict.fromkeys(selected))


def iter_legacy_connect_jobs(config, today, identifiers=None):
    """Default-empty planner; exact-day history only where the input is proven."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    selected = _selected(config)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    if not selected:
        return
    setting = config.get("legacy_connect_history_start", config.get("history_start"))
    start = _parse(setting) if setting is not None else None
    if start and start > today:
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    for api in selected:
        day = recent
        while day <= today:
            yield {
                "api_name": api,
                "params": {"trade_date": day.strftime("%Y%m%d")},
                "priority": 20,
                "epoch": epoch,
            }
            day += timedelta(days=1)
    if start is None:
        return
    for api in selected:
        day = start
        while day < recent:
            yield {
                "api_name": api,
                "params": {"trade_date": day.strftime("%Y%m%d")},
                "priority": 40,
                "epoch": "history",
            }
            day += timedelta(days=1)


def legacy_connect_prerequisites(config=None):
    gaps = []
    for api in _selected(config or {}):
        spec = LEGACY_CONNECT_CONTRACTS[api]
        for reason in (
            "hidden_field_gap",
            "history_gap",
            "pit_gap",
            "saturation_gap",
            "refresh_gap",
            "unit_gap",
            "acquisition_gap",
        ):
            if spec.get(reason):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": reason,
                        "detail": spec[reason],
                    }
                )
    return gaps
