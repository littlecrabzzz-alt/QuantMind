"""Reviewed contracts for the original calendar, ETF and CITIC RRG pipeline.

These seven APIs predate the shared registry. Their existing planner remains in
``Pipeline.initialize``/``expand``; this module exposes the complete pinned
catalogue schema and unresolved coverage limits to every layer.
"""

from backend.shared.tushare_structured_contracts import _contract


INPUT_FIELDS = {
    "trade_cal": ["exchange", "start_date", "end_date", "is_open"],
    "ci_daily": ["ts_code", "trade_date", "start_date", "end_date"],
    "ci_index_member": ["l1_code", "l2_code", "l3_code", "ts_code", "is_new"],
    "etf_basic": [
        "ts_code",
        "index_code",
        "list_date",
        "list_status",
        "exchange",
        "mgr",
    ],
    "fund_daily": ["ts_code", "trade_date", "start_date", "end_date"],
    "fund_adj": [
        "ts_code",
        "trade_date",
        "start_date",
        "end_date",
        "offset",
        "limit",
    ],
    "fund_portfolio": [
        "ts_code",
        "symbol",
        "ann_date",
        "period",
        "start_date",
        "end_date",
    ],
}

FIELDS = {
    "trade_cal": ["exchange", "cal_date", "is_open", "pretrade_date"],
    "ci_daily": [
        "ts_code",
        "trade_date",
        "open",
        "low",
        "high",
        "close",
        "pre_close",
        "change",
        "pct_change",
        "vol",
        "amount",
    ],
    "ci_index_member": [
        "l1_code",
        "l1_name",
        "l2_code",
        "l2_name",
        "l3_code",
        "l3_name",
        "ts_code",
        "name",
        "in_date",
        "out_date",
        "is_new",
    ],
    "etf_basic": [
        "ts_code",
        "csname",
        "extname",
        "cname",
        "index_code",
        "index_name",
        "setup_date",
        "list_date",
        "list_status",
        "exchange",
        "mgr_name",
        "custod_name",
        "mgt_fee",
        "etf_type",
    ],
    "fund_daily": [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "fund_adj": ["ts_code", "trade_date", "adj_factor"],
    "fund_portfolio": [
        "ts_code",
        "ann_date",
        "end_date",
        "symbol",
        "mkv",
        "amount",
        "stk_mkv_ratio",
        "stk_float_ratio",
    ],
}

_DOCS = {
    "trade_cal": (
        26,
        "ba19399a37d883c1943a6ef6dc753d1f0b524fb5b51cd5cf89385fe86df74fd3",
    ),
    "ci_daily": (
        308,
        "38a12945900040485d59422d299f23a9b34c331b4f1b38cb289f6480d2a8030b",
    ),
    "ci_index_member": (
        373,
        "7005d63746bfaeb39f4049c3fc54a81410d47e34dfda63d4ac2978f97c683846",
    ),
    "etf_basic": (
        385,
        "2b1dcf47c2df1baef2d88ed9e762cddad37a0a850510f5922ea3b2aa1972827b",
    ),
    "fund_daily": (
        127,
        "ac9f43990cc00bc0b7510a345082e5bdf12461bc0c85b7175d0faf3d602e2024",
    ),
    "fund_adj": (
        199,
        "52094eec8fd55a2cb6579302c3568ffec821f7480716a08cf760a97a1a573fcf",
    ),
    "fund_portfolio": (
        121,
        "887be14e585e842d123d33ab2ad32866e37293197aeb2dedd64da364015ae64f",
    ),
}

_CAPS = {
    "trade_cal": 6000,
    "ci_daily": 4000,
    "ci_index_member": 5000,
    "etf_basic": 5000,
    "fund_daily": 5000,
    "fund_adj": 2000,
    "fund_portfolio": 2000,
}

_KEYS = {
    "trade_cal": ["exchange", "cal_date"],
    "ci_daily": ["ts_code", "trade_date"],
    "ci_index_member": ["l1_code", "l2_code", "l3_code", "ts_code", "in_date"],
    "etf_basic": ["ts_code"],
    "fund_daily": ["ts_code", "trade_date"],
    "fund_adj": ["ts_code", "trade_date"],
    "fund_portfolio": ["ts_code", "ann_date", "end_date", "symbol"],
}

_CORE = {
    "trade_cal": {"exchange", "cal_date", "is_open"},
    "ci_daily": {"ts_code", "trade_date", "open", "close"},
    "ci_index_member": {"l1_code", "ts_code", "is_new"},
    "etf_basic": {"ts_code"},
    "fund_daily": {"ts_code", "trade_date", "open", "close"},
    "fund_adj": {"ts_code", "trade_date", "adj_factor"},
    "fund_portfolio": {"ts_code", "end_date", "symbol", "mkv"},
}

RRG_CONTRACTS = {}
for _api, (_doc_id, _source_sha) in _DOCS.items():
    spec = _contract(
        _CAPS[_api],
        _KEYS[_api],
        required=FIELDS[_api],
        nullable=[field for field in FIELDS[_api] if field not in _CORE[_api]],
        positive=[
            field for field in ("open", "close", "adj_factor") if field in _CORE[_api]
        ],
        split=_api in ("trade_cal", "ci_daily", "fund_daily", "fund_adj"),
        rpm=500,
        extra=FIELDS[_api],
        cap_verified=False,
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc_id}",
        source_html_sha256=_source_sha,
        input_fields=INPUT_FIELDS[_api].copy(),
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[],
        permission_status="unverified",
        independent_permission=False,
        minimum_points=None,
        documented_requests_per_minute=None,
        date_field=(
            "cal_date"
            if _api == "trade_cal"
            else "ann_date"
            if _api == "fund_portfolio"
            else "in_date"
            if _api == "ci_index_member"
            else "list_date"
            if _api == "etf_basic"
            else "trade_date"
        ),
        row_cap_basis="legacy_operational_guard_not_verified_supplier_maximum",
        field_selection_note="Every output column in the pinned catalogue is explicitly requested. Extra returned columns and null source values remain preserved.",
        hidden_field_gap="The pinned catalogue extraction retains field names but not default Y/N flags; no field is silently classified as hidden.",
        field_gaps={
            field: ["field_type_and_revision_semantics_unverified"]
            for field in FIELDS[_api]
        },
        history_bound_verified=False,
        history_gap="Existing persisted partitions prove partial acquisition only; the exact oldest source record, historical revisions and deletion coverage remain unverified.",
        pit_gap="Source dates and observed_at are retained separately. Neither the catalogue nor a later observation proves historical point-in-time availability.",
        saturation_gap="The inherited row cap is an operational alarm, not a verified supplier maximum. Terminal legal partitions remain blocked rather than declared complete.",
    )
    RRG_CONTRACTS[_api] = spec

RRG_CONTRACTS["ci_index_member"].update(
    dependencies=["stocks"],
    saturation_fallback="stocks",
    saturation_param="ts_code",
    date_axis_note="in_date/out_date are membership intervals; is_new is a current-state filter. No known_at or historical publication timestamp is provided.",
)
for _api in ("fund_daily", "fund_adj"):
    RRG_CONTRACTS[_api].update(
        dependencies=["funds"],
        saturation_fallback="funds",
        saturation_param="ts_code",
    )
RRG_CONTRACTS["etf_basic"].update(
    date_axis_note="setup_date and list_date are source lifecycle dates. Current list_status observations do not reconstruct every historical status transition.",
)
RRG_CONTRACTS["fund_portfolio"].update(
    date_axis_note="ann_date is the publication date; end_date is the report period. Local date filters default to ann_date and do not manufacture announcement times.",
    unit_note="mkv, amount and ratios retain supplier values and units; no local rescaling, weight completion or holdings look-through is inferred.",
)
