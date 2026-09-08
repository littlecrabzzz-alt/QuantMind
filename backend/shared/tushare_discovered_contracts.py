"""Documented real-time snapshots only; missing discovery pages remain gaps.

No I/O or credentials. A planning epoch is an idempotence label, never evidence
that a delayed request observed an earlier time. No historical requests exist.
"""

from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest
import re

from backend.shared.tushare_structured_contracts import _contract

FIELDS = {
    "rt_k": "ts_code name pre_close high open low close vol amount num ask_price1 ask_volume1 bid_price1 bid_volume1 trade_time".split(),
    "rt_etf_k": "ts_code name pre_close high open low close vol amount num ask_volume1 bid_volume1 trade_time".split(),
}
INPUT_FIELDS = {"rt_k": ["ts_code"], "rt_etf_k": ["ts_code", "topic"]}
DISCOVERED_CONTRACTS = {}
for _api, _doc, _guard, _cap, _family in (
    ("rt_k", 372, 6000, 6000, "stocks"),
    ("rt_etf_k", 400, 1000, None, "etfs"),
):
    _spec = _contract(
        _guard,
        ("ts_code", "trade_time", "_observation"),
        required=("ts_code",),
        nullable=tuple(f for f in FIELDS[_api] if f != "ts_code"),
        extra=FIELDS[_api],
        split=False,
        rpm=50,
        cap_verified=False,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        reviewed_on="20260909",
        input_fields=INPUT_FIELDS[_api],
        hidden_fields=[f for f in FIELDS[_api] if f.startswith(("ask_", "bid_"))]
        + ["trade_time"],
        documented_row_cap=_cap,
        permission_status="unprobed",
        independent_permission=True,
        minimum_points=None,
        permission_note="Independent real-time entitlement. 10100 points and purchased text permissions do not establish access.",
        dependencies=[_family],
        saturation_fallback=_family,
        saturation_param="ts_code",
        saturation_dependencies=[_family],
        preserve_distinct_rows=True,
        generated_identity_fields=["_observation"],
        date_field="trade_time",
        split_axis="none_realtime_snapshot",
        acquisition_mode="realtime_snapshot",
        history_start=None,
        history_bound_verified=False,
        history_gap="No historical date/range parameter; previously unobserved intraday snapshots cannot be backfilled by this API.",
        row_identity_note="Keep ts_code, optional raw trade_time, immutable _observation and generated raw _row_identity. Different observations remain separate even for identical payloads; do not send generated fields upstream.",
        revision_note="close is the latest intraday price, not a confirmed final close. vol/amount/num are cumulative session values. Preserve every observation and source timestamp; missing trade_time remains null, never inferred from the job epoch.",
        timing_gap="Requests across stocks are not an atomic market snapshot. Parent must record actual request/response times and reject stale planned jobs; replaying an old epoch cannot recreate past prices. Source timestamp format/timezone and post-close finality remain unprobed.",
        pagination_gap="No offset/limit/date split. On saturation subdivide only through documented code filters and the full stored discovery universe; retain a gap for missing universe or a saturated single code.",
        units={"vol": "shares", "amount": "CNY", "num": "trades"},
    )
    DISCOVERED_CONTRACTS[_api] = _spec

DISCOVERED_CONTRACTS["rt_etf_k"].update(
    parameter_gap="topic is marked required but omitted by the official SZ example; SH explicitly needs HQ_FND_TICK. Planner follows those examples. BJ/other topic semantics remain unverified.",
    cap_note="The page specifies no row limit. 1000 is a conservative operational saturation alarm, not a measured supplier cap or a proof of completeness below it.",
)
DISCOVERED_CONTRACTS["rt_k"]["parameter_note"] = (
    "ts_code supports comma-separated codes and wildcard examples. Planner batches "
    "100 known source codes; that batch size is operational, not a documented limit."
)

# Search caches previously displayed these APIs, but live official pages now fail.
# Do not promote cached input/output claims into a current executable contract.
DISCOVERED_GAPS = {
    "hk_hold": {
        "doc_id": "188",
        "source_url": "https://tushare.pro/document/2?doc_id=188",
        "reason": "official_document_missing",
        "checked_on": "20260909",
        "http_status": 200,
        "body_sha256": "bbf4318386ca0ea4c5072fc5e67fe0302f473ccbeba7238c45607226236dfadf",
        "permission_status": "unverified",
        "history_gap": "Earlier official search cache mentioned a northbound daily-to-quarterly disclosure change from 2024-08-20; current fields, availability, publication timing and historical access must be reconfirmed. Do not substitute current holdings or invent quarterly dates.",
    },
    "dc_concept_cons": {
        "doc_id": "422",
        "source_url": "https://tushare.pro/document/2?doc_id=422",
        "reason": "official_document_missing",
        "checked_on": "20260909",
        "http_status": 200,
        "body_sha256": "bbf4318386ca0ea4c5072fc5e67fe0302f473ccbeba7238c45607226236dfadf",
        "permission_status": "unverified",
        "history_gap": "Earlier official search cache claimed history from 20260203, 3000 rows and 6000 points. Live documentation no longer confirms that contract; do not treat the cached start as verified history or alias dc_member/kpl_concept_cons.",
    },
}


def _enabled(config):
    values = config.get("discovered_apis", tuple(DISCOVERED_CONTRACTS))
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(v, str)
        or v not in (DISCOVERED_CONTRACTS.keys() | DISCOVERED_GAPS.keys())
        for v in values
    ):
        raise ValueError("discovered_apis must contain reviewed API or gap names")
    return tuple(dict.fromkeys(values))


def _codes(identifiers, family):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map families to source codes/records")
    values = identifiers.get(family, ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("discovery family must contain codes or records")
    codes = set()
    for value in values:
        code = value.get("ts_code") if isinstance(value, dict) else value
        if not isinstance(code, str) or not re.fullmatch(
            r"[A-Z0-9]+\.(SH|SZ|BJ)", code
        ):
            raise ValueError("Expected opaque supplier code with SH/SZ/BJ suffix")
        codes.add(code)
    return sorted(codes)


def _epoch(config, today):
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError("today must be the Asia/Shanghai calendar date")
    value = config.get("discovered_snapshot_epoch")
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}T\d{6}Z", value):
        raise ValueError("discovered_snapshot_epoch must be UTC YYYYMMDDTHHMMSSZ")
    stamp = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if stamp.astimezone(timezone(timedelta(hours=8))).date() != today:
        raise ValueError("snapshot epoch must belong to today's Asia/Shanghai date")
    return "snapshot-" + value


def discovered_prerequisites(identifiers=None, enabled_apis=None, config=None):
    """No requests for unavailable contracts; enumerate every discovery gap."""
    config = dict(config or {})
    if enabled_apis is not None:
        config["discovered_apis"] = enabled_apis
    enabled = _enabled(config)
    identifiers = identifiers if identifiers is not None else {}
    gaps = [dict(api_name=api, **gap) for api, gap in DISCOVERED_GAPS.items()]
    for api in enabled:
        if api in DISCOVERED_GAPS:
            continue
        spec = DISCOVERED_CONTRACTS[api]
        family = spec["dependencies"][0]
        codes = _codes(identifiers, family)
        gaps.append(
            {
                "api_name": api,
                "reason": "stored_discovery_completeness_unverified"
                if codes
                else "awaiting_stored_discovery",
                "dependencies": [family],
                "observed_codes": len(codes),
                "universe_complete": False,
            }
        )
        if config.get("discovered_snapshot_epoch") is None:
            gaps.append({"api_name": api, "reason": "explicit_snapshot_epoch_required"})
        for key in (
            "history_gap",
            "timing_gap",
            "pagination_gap",
            "parameter_gap",
            "cap_note",
        ):
            if spec.get(key):
                gaps.append({"api_name": api, "reason": key, "detail": spec[key]})
        gaps.append({"api_name": api, "reason": "independent_permission_unprobed"})
    return gaps


def _requests(api, codes):
    if api == "rt_k":
        for offset in range(0, len(codes), 100):
            yield {"ts_code": ",".join(codes[offset : offset + 100])}
    else:
        # These two broad patterns are explicitly demonstrated by doc400. Do not
        # assume they cover exceptional supplier identifiers or future exchanges.
        yield {"ts_code": "5*.SH", "topic": "HQ_FND_TICK"}
        yield {"ts_code": "1*.SZ"}
        for code in codes:
            if (code.startswith("5") and code.endswith(".SH")) or (
                code.startswith("1") and code.endswith(".SZ")
            ):
                continue
            params = {"ts_code": code}
            if code.endswith(".SH"):
                params["topic"] = "HQ_FND_TICK"
            yield params


def iter_discovered_jobs(config, today, identifiers=None):
    """Lazy current-snapshot plan; no history epoch and no invented date filter.

    Parent supplies a current UTC epoch after permission/authority checks, handles
    time budgets/expiry and stores actual observed times. Retired and exceptional
    discovered identifiers are retained; empty replies cannot prove a delisting.
    """
    enabled = _enabled(config)
    epoch = _epoch(config, today)
    identifiers = identifiers if identifiers is not None else {}
    streams = []
    for api in enabled:
        if api not in DISCOVERED_CONTRACTS:
            continue
        codes = _codes(identifiers, DISCOVERED_CONTRACTS[api]["dependencies"][0])
        if epoch is not None:
            streams.append((api, iter(_requests(api, codes))))
    for row in zip_longest(*(stream for _, stream in streams)):
        for (api, _), params in zip(streams, row, strict=True):
            if params is not None:
                yield {
                    "api_name": api,
                    "params": params,
                    "priority": 20,
                    "epoch": epoch,
                }
