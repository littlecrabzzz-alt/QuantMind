"""Pure same-session replay requests; not general historical minute access."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from itertools import zip_longest
import re

from backend.shared.tushare_discovered_contracts import _epoch
from backend.shared.tushare_realtime_extra_contracts import (
    FREQUENCIES,
    REALTIME_EXTRA_CONTRACTS,
    _source_codes,
)

BASE_APIS = {
    "rt_idx_min_daily": "rt_idx_min",
    "rt_fut_min_daily": "rt_fut_min",
    "rt_etf_min_daily": "rt_etf_min",
}
REALTIME_REPLAY_CONTRACTS = {}
for _api, _base in BASE_APIS.items():
    spec = deepcopy(REALTIME_EXTRA_CONTRACTS[_base])
    spec.update(
        group="realtime_replay",
        default_enabled=False,
        acquisition_mode="current_session_replay",
        snapshot_only=True,
        source_api=_api,
        read_only=True,
        request_identity_fields=["ts_code", "freq"]
        + (["date_str"] if _api == "rt_fut_min_daily" else []),
        documented_row_cap=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        row_cap_verified=False,
        permission_status="unprobed",
        minimum_points=None,
        field_scope_gap="The shared official output table follows the named daily replay endpoint on the same page; all known columns are requested, but actual replay schema/presence and unknown columns remain unprobed. Do not silently equate a sibling's sample permission or cap with this named API.",
        history_gap="Only current-session replay, with narrowly gated prior-day futures replay. No start_date/end_date/trade_date/date/offset inputs; no arbitrary old epoch or unbounded historical backfill.",
        saturation_gap="One actual source identifier per request. No documented pagination or smaller intraday time filter; even single-code/frequency replay reaching the local1000 guard or has_more remains incomplete. Never switch frequency to claim missing finer bars recovered.",
        timing_gap="Opening-to-now replay may include unfinished/revised bars and no PIT/publication guarantee. Actual source timezone, session boundaries, night-trading dates, bar-label convention and observation time remain unverified; request epoch is idempotence only. Expired queued snapshots must not execute as if captured earlier.",
        permission_gap="Daily replay is a separately named endpoint requiring independently verified permission. Points do not imply access. Separate real-time permission is described on the page; daily quota/cap inheritance is not established. Local30rpm is a conservative ceiling only.",
        namespace_gap="Source identifiers come only from actual index/futures discovery. Keep source spelling/case and IDX:/FUT: asset context; index symbols are not stocks and futures have no stock trading-session assumptions.",
    )
    spec.pop("catalog_gap", None)
    REALTIME_REPLAY_CONTRACTS[_api] = spec
REALTIME_REPLAY_CONTRACTS["rt_idx_min_daily"].update(
    required_params=["ts_code", "freq"],
    allowed_params=["ts_code", "freq"],
    input_metadata={
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "仅支持一个个指数提取，不同同时提取多个（官方正文原字）",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "1MIN,5MIN,15MIN,30MIN,60MIN （大写）",
        },
    },
    named_api_evidence="Page420 explicitly names rt_idx_min_daily and calls it with one ts_code and freq. Scope:当日开盘以来的所有历史分钟; no date input documented.",
    documented_scope="current opening-to-now, one actual index per request",
    sibling_limit_note="Page420 opening paragraph says rt_idx_min single-request1000 rows. Scope of that cap for the separately named daily endpoint is not explicit; do not certify daily completeness using it.",
    update_time_gap="No update clock, final-bar availability or closed-day behavior specified. Current-day text does not establish a calendar or archived daily replay.",
)
REALTIME_REPLAY_CONTRACTS["rt_fut_min_daily"].update(
    required_params=["ts_code", "freq"],
    allowed_params=["ts_code", "freq", "date_str"],
    input_metadata={
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "股票代码，e.g.CU2310.SHF，仅支持一次一个合约的回放",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1MIN/5MIN/15MIN/30MIN/60MIN）",
        },
        "date_str": {
            "type": "str",
            "required": "N",
            "description": "回放日期（格式：YYYY-MM-DD，默认为交易当日，支持回溯一天）",
        },
    },
    named_api_evidence="Page340 separately names rt_fut_min_daily with its own3-row input table before the shared output schema; one actual contract only.",
    documented_scope="当日开市以来所有历史分钟（分钟快照回放）；date_str默认为交易当日，支持回溯一天",
    previous_day_gap="回溯一天 does not specify calendar versus trading day, holiday handling or night-session rollover. Default omit date_str uses supplier current trading day. Prior-day planning additionally requires a same-epoch, per-contract verified replay window; never compute today-1 or infer eligibility from a stock calendar.",
    sibling_limit_note="Page340 says rt_fut_min500 requests/minute; daily endpoint inheritance is unconfirmed. No numeric row cap disclosed. Local1000 guard cannot prove completion.",
    discovery_window_gap="Verified previous-day windows are not invented from master codes or prose. Runtime must retain actual request/response/date-filter evidence and relevant exchange calendar/session mapping; missing or stale windows only block prior-day requests, not default current replay.",
    update_time_gap="No exact minute publication schedule/finality or timezone given. The planner does not synthesize night-session rows or determine the supplier trading day.",
)
REALTIME_REPLAY_CONTRACTS["rt_etf_min_daily"].update(
    required_params=["ts_code", "freq"],
    allowed_params=["ts_code", "freq"],
    input_metadata={
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "仅支持一次提取一个ETF代码",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "1MIN,5MIN,15MIN,30MIN,60MIN （大写）",
        },
    },
    named_api_evidence="Page416 explicitly names rt_etf_min_daily, limits it to one ETF code and describes current-opening-to-now minute history.",
    documented_scope="current opening-to-now, one actual ETF per request",
    history_gap="Only the current opening-to-now session is documented. There is no date/range input and no arbitrary historical replay or reconstruction of an earlier observation.",
    sibling_limit_note="Page416 states a 1000-row cap for rt_etf_min; it does not explicitly assign that cap to the separately named daily endpoint. Local1000 remains a saturation alarm, not completeness proof.",
    update_time_gap="No update clock, source timezone, final-bar availability or closed-day behavior is specified. The endpoint does not provide arbitrary historical dates.",
    namespace_gap="Use only actual stored ETF identifiers and retain FUND: plus the supplier code. A suffix or current ETF list does not establish historical listing, tradability, holdings or PIT membership.",
)
FIELDS = {api: list(spec["fields"]) for api, spec in REALTIME_REPLAY_CONTRACTS.items()}
INPUT_FIELDS = {
    api: list(spec["allowed_params"]) for api, spec in REALTIME_REPLAY_CONTRACTS.items()
}


def _settings(config):
    enabled = config.get("enable_realtime_replay", False)
    if not isinstance(enabled, bool):
        raise ValueError("enable_realtime_replay must be boolean")
    apis = config.get("realtime_replay_apis", tuple(BASE_APIS))
    if not isinstance(apis, (list, tuple)) or any(
        not isinstance(api, str) or api not in BASE_APIS for api in apis
    ):
        raise ValueError("realtime_replay_apis must contain reviewed read APIs")
    frequencies = config.get("realtime_replay_frequencies", FREQUENCIES)
    if not isinstance(frequencies, (list, tuple)) or any(
        not isinstance(freq, str) or freq not in FREQUENCIES for freq in frequencies
    ):
        raise ValueError("Exact uppercase replay frequencies required")
    scope = config.get("realtime_replay_futures_scope", "current")
    if scope not in ("current", "current_and_verified_previous"):
        raise ValueError("Only current or current_and_verified_previous replay allowed")
    return (
        tuple(dict.fromkeys(apis)) if enabled else (),
        tuple(dict.fromkeys(frequencies)),
        scope,
    )


def _previous_day(identifiers, code, epoch):
    """Only per-contract observed eligibility; no weekday/calendar inference.

    The future runtime authenticates these source-derived assertions. A pure
    helper cannot prove evidence authenticity; config dates never qualify.
    """
    windows = (identifiers or {}).get("realtime_replay_futures_windows", {})
    if not isinstance(windows, dict):
        raise ValueError("Futures replay windows require per-contract observations")
    window = windows.get(code)
    if window is None:
        return None, "awaiting_verified_previous_replay_window"
    if not isinstance(window, dict):
        raise ValueError("Futures replay window requires source metadata")
    if window.get("epoch") != epoch or epoch is None:
        return None, "awaiting_same_epoch_replay_window"
    if window.get("lookback_verified") is not True:
        return None, "previous_replay_eligibility_unverified"
    if window.get("source_api") != "rt_fut_min_daily":
        raise ValueError(
            "Previous replay eligibility requires actual endpoint evidence"
        )
    dates = []
    for key in ("current_trade_date", "previous_trade_date"):
        value = window.get(key)
        if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
        ):
            raise ValueError("Replay window dates must be exact YYYY-MM-DD")
        dates.append(date.fromisoformat(value))
    current, previous = dates
    if not re.fullmatch(r"snapshot-[0-9]{8}T[0-9]{6}Z", epoch):
        raise ValueError("Verified replay window requires a valid snapshot epoch")
    local_day = (
        datetime.strptime(epoch, "snapshot-%Y%m%dT%H%M%SZ") + timedelta(hours=8)
    ).date()
    if current != local_day:
        return None, "replay_session_calendar_boundary_unverified"
    if previous >= current:
        raise ValueError("Previous replay day must precede current trading day")
    # Evidence must attest immediate predecessor, not merely any older date.
    if window.get("immediate_previous_trading_day_verified") is not True:
        return None, "previous_trading_day_relation_unverified"
    return previous.isoformat(), None


def realtime_replay_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    config["enable_realtime_replay"] = True
    if enabled_apis is not None:
        config["realtime_replay_apis"] = enabled_apis
    apis, _, scope = _settings(config)
    raw_epoch = config.get("realtime_replay_snapshot_epoch")
    epoch = "snapshot-" + raw_epoch if isinstance(raw_epoch, str) else None
    gaps = []
    for api in apis:
        spec = REALTIME_REPLAY_CONTRACTS[api]
        codes, unsupported = _source_codes(BASE_APIS[api], identifiers or {})
        gaps.append(
            {
                "api_name": api,
                "reason": "stored_discovery_completeness_unverified"
                if codes
                else "awaiting_stored_discovery",
                "observed_codes": len(codes),
                "unsupported_codes": len(unsupported),
                "universe_complete": False,
            }
        )
        if epoch is None:
            gaps.append({"api_name": api, "reason": "explicit_snapshot_epoch_required"})
        for key in (
            "field_scope_gap",
            "history_gap",
            "saturation_gap",
            "timing_gap",
            "permission_gap",
            "namespace_gap",
        ):
            gaps.append({"api_name": api, "reason": key, "detail": spec[key]})
        if api == "rt_fut_min_daily":
            gaps.append(
                {
                    "api_name": api,
                    "reason": "previous_day_gap",
                    "detail": spec["previous_day_gap"],
                }
            )
            if scope == "current_and_verified_previous":
                blocked = sum(
                    _previous_day(identifiers, code, epoch)[0] is None for code in codes
                )
                if blocked:
                    gaps.append(
                        {
                            "api_name": api,
                            "reason": "awaiting_verified_previous_replay_window",
                            "blocked_codes": blocked,
                        }
                    )
    return gaps


def _requests(api, codes, frequencies, scope, identifiers, epoch):
    for code in codes:
        previous = None
        if api == "rt_fut_min_daily" and scope == "current_and_verified_previous":
            previous, _ = _previous_day(identifiers, code, epoch)
        for freq in frequencies:
            yield {"ts_code": code, "freq": freq}
            if previous:
                yield {"ts_code": code, "freq": freq, "date_str": previous}


def iter_realtime_replay_jobs(config, today, identifiers=None):
    """Lazily replay current data; explicit verified prior-day futures only."""
    apis, frequencies, scope = _settings(config)
    if not apis:
        return
    epoch = _epoch(
        {"discovered_snapshot_epoch": config.get("realtime_replay_snapshot_epoch")},
        today,
    )
    if epoch is None:
        return
    streams = []
    for api in apis:
        codes, _ = _source_codes(BASE_APIS[api], identifiers or {})
        streams.append(
            (api, _requests(api, codes, frequencies, scope, identifiers, epoch))
        )
    for row in zip_longest(*(stream for _, stream in streams)):
        for (api, _), params in zip(streams, row, strict=True):
            if params is not None:
                yield {
                    "api_name": api,
                    "params": params,
                    "priority": 20,
                    "epoch": epoch,
                }
