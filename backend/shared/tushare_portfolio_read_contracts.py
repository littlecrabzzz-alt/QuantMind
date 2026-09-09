"""Pure account-private portfolio reads; never create, edit or delete a portfolio."""

import unicodedata

from backend.shared.tushare_discovered_contracts import _epoch
from backend.shared.tushare_structured_contracts import _contract

SOURCE_HTML_SHA256 = {
    "p_list": "0da5b3515d7edeea480afb0da2c88ec91572513d0d3dbacdc233561a1ac98d12",
    "p_get": "2d5ea23348bca63430b672300ce7200328736bc753a56b4bd351b09b9c067039",
}
FIELD_METADATA = {
    "p_list": {
        "id": {"type": "int", "default": "Y", "description": "主键"},
        "name": {"type": "str", "default": "Y", "description": "名称"},
        "desc": {"type": "str", "default": "Y", "description": "描述"},
        "create_time": {"type": "datetime", "default": "Y", "description": "创建时间"},
        "update_time": {"type": "datetime", "default": "Y", "description": "修改时间"},
    },
    "p_get": {
        "id": {"type": "int", "default": "Y", "description": "编号"},
        "ts_code": {"type": "str", "default": "Y", "description": "成分代码"},
        "ts_type": {
            "type": "str",
            "default": "Y",
            "description": "成份类型（用户自定义类型，比如按行业、按概念板块或其他）",
        },
        "name": {"type": "str", "default": "Y", "description": "名称"},
        "desc": {"type": "str", "default": "Y", "description": "描述"},
        "weight": {"type": "float", "default": "Y", "description": "权重"},
        "create_time": {"type": "datetime", "default": "Y", "description": "创建时间"},
        "update_time": {"type": "datetime", "default": "Y", "description": "修改时间"},
    },
}
FIELDS = {api: list(fields) for api, fields in FIELD_METADATA.items()}
INPUT_METADATA = {
    api: {"name": {"type": "str", "required": required, "description": "组合名称"}}
    for api, required in (("p_list", "N"), ("p_get", "Y"))
}
INPUT_FIELDS = {api: list(fields) for api, fields in INPUT_METADATA.items()}
PORTFOLIO_READ_CONTRACTS = {}
for _api, _doc in (("p_list", 446), ("p_get", 449)):
    _keys = (
        ("_observation_id", "id")
        if _api == "p_list"
        else ("_observation_id", "_request_identity", "id")
    )
    spec = _contract(
        1000,
        _keys,
        required=FIELDS[_api],
        nullable=FIELDS[_api],
        extra=FIELDS[_api],
        split=False,
        rpm=30,
        cap_verified=False,
    )
    spec.update(
        group="portfolio_read",
        default_enabled=False,
        read_only=True,
        doc_id=_doc,
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        input_metadata=INPUT_METADATA[_api],
        field_metadata=FIELD_METADATA[_api],
        allowed_params=["name"],
        required_params=[] if _api == "p_list" else ["name"],
        fields=FIELDS[_api],
        requested_fields=list(FIELDS[_api]),
        hidden_fields=[],
        request_identity_fields=[] if _api == "p_list" else ["name"],
        preserve_distinct_rows=True,
        date_field=None,
        split_axis=None,
        dependencies=[] if _api == "p_list" else ["portfolio_read_list"],
        permission_status="unprobed",
        minimum_points=None,
        independent_permission=None,
        documented_row_cap=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        history_bound_verified=False,
        snapshot_only=True,
        permission_gap="No points, subscription or quota requirement is documented. Account-private reads need actual authorization evidence;10100 points do not prove access.",
        history_gap="No date, as-of, range or deleted-item/history input. Future snapshots preserve observations, not full history before first capture or changes between captures.",
        pagination_gap="No limit/offset/page or continuation parameter documented.1000 is only a local conservative guard. A saturated list/member response stays incomplete; never invent names or split constituent codes.",
        timing_gap="create_time/update_time are supplier modification metadata, not a snapshot timestamp or membership valid-from/to. Timezone, precision, atomic list/member consistency and correction history are unknown. Store actual request/fetch times and fixed observation identity.",
        identity_gap="IDs are account-private, not globally unique or proven immutable across deletion/restore. Keep observation and request identity, all distinct rows and nullable source values. Equal-valued multiplicity remains unknown.",
        privacy_note="Private account scope only. Never log names/descriptions/holdings/raw request params in status or errors, and never expose these datasets through a public market-data reader. Account credentials are not data fields or discovery identifiers.",
        field_selection_note="Explicitly request all known fields; both examples select only3 member columns and are not full-schema evidence. All13 documented fields defaultY; retain additional unknown fields/nulls unchanged.",
        field_gaps={
            name: ["actual_presence_unprobed", "nullable_semantics_unverified"]
            for name in FIELDS[_api]
        },
    )
    PORTFOLIO_READ_CONTRACTS[_api] = spec
PORTFOLIO_READ_CONTRACTS["p_list"].update(
    discovery_note="Unfiltered p_list is the only seed. A successful empty list is an observation of no custom portfolios, not permission failure; completeness/race/cap limitations still apply.",
)
PORTFOLIO_READ_CONTRACTS["p_get"].update(
    source_namespace="opaque_user_defined_component_preserve_source_code_and_type",
    unit_gap="weight scale/normalization and short/negative/zero meaning are undocumented; preserve original numbers without sum-to-one or positivity assumptions.",
    discovery_gap="Only validated same-epoch successful unfiltered p_list id/name rows may seed name. List IDs are provenance, not valid p_get input. No guessed names/config seeds; ambiguous duplicate names across IDs block planning. Rename/delete between list/get can yield empty and does not prove historical absence.",
    component_note="ts_type is user-defined, not a trusted exchange/asset classifier. ts_code may refer to industries, concepts or other components; do not normalize every value into an A-share security. Returned name is component name, distinct from requested portfolio name.",
)


def _enabled(config):
    selected = config.get("portfolio_read_apis", tuple(PORTFOLIO_READ_CONTRACTS))
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(api, str) or api not in PORTFOLIO_READ_CONTRACTS
        for api in selected
    ):
        raise ValueError("portfolio_read_apis must contain only read APIs")
    return tuple(dict.fromkeys(selected))


def _snapshot_epoch(config, today):
    return _epoch(
        {"discovered_snapshot_epoch": config.get("portfolio_read_snapshot_epoch")},
        today,
    )


def _observed_names(identifiers, epoch):
    """Caller supplies an authenticated stored p_list observation, never config names.

    This pure boundary validates shape; provenance authenticity is the future
    runtime's responsibility. It must not adapt manually entered names as rows.
    No source value is included in exceptions or prerequisite summaries.
    """
    observation = (identifiers or {}).get("portfolio_read_list")
    if observation is None:
        return (), "awaiting_stored_list_observation"
    if not isinstance(observation, dict):
        raise ValueError("Portfolio discovery requires a stored list observation")
    if observation.get("api_name") != "p_list" or observation.get("params") != {}:
        raise ValueError("Portfolio discovery requires unfiltered p_list")
    if epoch is None or observation.get("epoch") != epoch:
        return (), "awaiting_same_epoch_list_observation"
    if observation.get("status") not in ("done", "empty"):
        return (), "awaiting_successful_list_observation"
    rows = observation.get("rows")
    if not isinstance(rows, (list, tuple)):
        raise ValueError("Portfolio discovery requires source rows")
    if (observation["status"] == "empty") != (len(rows) == 0):
        raise ValueError("Portfolio discovery status contradicts row count")
    names, ids = {}, {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Portfolio discovery requires source id and name")
        identifier, name = row.get("id"), row.get("name")
        if isinstance(identifier, bool) or not isinstance(identifier, int):
            raise ValueError("Portfolio source id must be an integer")
        if (
            not isinstance(name, str)
            or not name.strip()
            or any(unicodedata.category(char).startswith("C") for char in name)
        ):
            raise ValueError("Portfolio source name is not a safe nonempty string")
        if name in names and names[name] != identifier:
            raise ValueError("Ambiguous portfolio names cannot seed member reads")
        if identifier in ids and ids[identifier] != name:
            raise ValueError(
                "Conflicting portfolio identities cannot seed member reads"
            )
        names[name] = identifier
        ids[identifier] = name
    return tuple(
        sorted(names)
    ), "observed_no_custom_portfolios" if not names else "observed_list_only"


def portfolio_read_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["portfolio_read_apis"] = enabled_apis
    enabled = _enabled(config)
    # Inspection without a wall clock does not bless source freshness; planner
    # separately validates UTC epoch against its explicit Asia/Shanghai today.
    raw_epoch = config.get("portfolio_read_snapshot_epoch")
    epoch = "snapshot-" + raw_epoch if isinstance(raw_epoch, str) else None
    gaps = []
    for api in enabled:
        spec = PORTFOLIO_READ_CONTRACTS[api]
        for key in (
            "permission_gap",
            "history_gap",
            "pagination_gap",
            "timing_gap",
            "identity_gap",
        ):
            gaps.append({"api_name": api, "reason": key, "detail": spec[key]})
        if epoch is None:
            gaps.append({"api_name": api, "reason": "explicit_snapshot_epoch_required"})
        if api == "p_get":
            names, state = _observed_names(identifiers, epoch)
            gaps.append(
                {
                    "api_name": api,
                    "reason": state,
                    "observed_portfolios": len(names),
                    "universe_complete": False,
                    "is_failure": state
                    not in ("observed_no_custom_portfolios", "observed_list_only"),
                }
            )
    return gaps


def iter_portfolio_read_jobs(config, today, identifiers=None):
    """Only explicit future/current observation epochs; never historical backfill."""
    if config.get("enable_portfolio_read") is not True:
        return
    enabled = _enabled(config)
    epoch = _snapshot_epoch(config, today)
    if epoch is None:
        return
    # Validate discovery before yielding anything; a caller cannot accidentally
    # execute partial reads before a malformed private source raises an error.
    names, _ = _observed_names(identifiers, epoch) if "p_get" in enabled else ((), None)
    if "p_list" in enabled:
        yield {"api_name": "p_list", "params": {}, "priority": 10, "epoch": epoch}
    if "p_get" in enabled:
        for name in names:
            yield {
                "api_name": "p_get",
                "params": {"name": name},
                "priority": 20,
                "epoch": epoch,
            }
