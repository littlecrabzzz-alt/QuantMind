"""Single-writer Tushare acquisition, durable checkpoints and immutable releases.

Acquisition uses reviewed contracts and durable family queues. The public
catalogue remains a separate coverage obligation. Readers never acquire data.
"""

from __future__ import annotations

import fcntl
import atexit
import hashlib
import itertools
import json
import os
import re
import shutil
import sqlite3
import stat
import time
from collections import deque
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
import multiprocessing
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from backend.shared.tushare_registry import (
    REALTIME_RUNTIME_CONTRACTS, REALTIME_SOURCE_FAMILIES,
    realtime_runtime_prerequisites, realtime_dispatch_status, project_realtime_row,
    ACCOUNT_HISTORY_RUNTIME_CONTRACTS,
    account_history_prerequisites,
    project_account_period,
    SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS,
    securities_lending_history_prerequisites,
    HISTORY_MINUTES_RUNTIME_CONTRACTS,
    MINUTE_SOURCE_FAMILIES,
    history_minutes_runtime_prerequisites,
    CALENDAR_EXTRA_RUNTIME_CONTRACTS,
    FACTOR_LIBRARY_RUNTIME_CONTRACTS,
    calendar_extra_prerequisites,
    factor_library_prerequisites,
    BOND_EXTRA_RUNTIME_CONTRACTS,
    bond_extra_runtime_prerequisites,
    CROSS_ASSET_RUNTIME_CONTRACTS,
    cross_asset_runtime_prerequisites,
    cross_asset_identifiers,
    MARKET_SENTIMENT_RUNTIME_CONTRACTS,
    market_sentiment_prerequisites,
    PORTFOLIO_READ_RUNTIME_CONTRACTS,
    portfolio_read_prerequisites,
    portfolio_read_snapshot_epoch,
    EXTENDED_CONTRACTS,
    PLANNERS,
    APPEND_PLANNERS,
    ANNOUNCEMENTS,
    MARKET_MEMBER_APIS,
    MARKET_MEMBER_DEPENDENCIES,
    market_member_prerequisites,
    contract_for,
    risk_event_runtime_prerequisites,
    technical_extra_runtime_prerequisites,
    STOCK_CONTEXT_RUNTIME_CONTRACTS,
    stock_context_runtime_prerequisites,
    TECHNICAL_EXTRA_RUNTIME_CONTRACTS,
    FOREIGN_FINANCIAL_RUNTIME_CONTRACTS,
    foreign_financial_runtime_prerequisites,
    catalog_delta_prerequisites,
)


_CAPTURE_PROCESS_CLIENT = None
_CAPTURE_PROCESS_TOKEN = None
_CAPTURE_PROCESS_ROOT = None


def _close_capture_process_client():
    global _CAPTURE_PROCESS_CLIENT
    if _CAPTURE_PROCESS_CLIENT is not None:
        _CAPTURE_PROCESS_CLIENT.close()
        _CAPTURE_PROCESS_CLIENT = None


def _initialize_capture_process(token, root, api_root):
    """Create one persistent HTTP client without putting the token in argv."""
    global _CAPTURE_PROCESS_CLIENT, _CAPTURE_PROCESS_TOKEN, _CAPTURE_PROCESS_ROOT
    from backend.shared import tushare_intake

    tushare_intake.API_ROOT = api_root
    _CAPTURE_PROCESS_CLIENT = httpx.Client(
        trust_env=False, timeout=30, follow_redirects=False
    )
    _CAPTURE_PROCESS_TOKEN = token
    _CAPTURE_PROCESS_ROOT = Path(root)
    atexit.register(_close_capture_process_client)


def _capture_in_process(job):
    if (
        _CAPTURE_PROCESS_CLIENT is None
        or _CAPTURE_PROCESS_TOKEN is None
        or _CAPTURE_PROCESS_ROOT is None
    ):
        raise RuntimeError("Capture process is not initialized")
    started = time.perf_counter()
    result = capture_sample(
        _CAPTURE_PROCESS_CLIENT,
        _CAPTURE_PROCESS_TOKEN,
        job,
        _CAPTURE_PROCESS_ROOT,
    )
    return result, time.perf_counter() - started


def _pagination_for_params(spec, params):
    pagination = spec.get("pagination")
    required = spec.get("pagination_required_param")
    if pagination and required and required not in params:
        return None
    forbidden = spec.get("pagination_forbidden_params", ())
    if pagination and any(name in params for name in forbidden):
        return None
    return pagination


from backend.shared.tushare_global_contracts import (
    GLOBAL_CONTRACTS,
    global_prerequisites,
)
from backend.shared.tushare_other_contracts import OTHER_CONTRACTS, other_prerequisites
from backend.shared.tushare_supplement_contracts import supplement_prerequisites
from backend.shared.tushare_equity_event_contracts import (
    EQUITY_EVENT_CONTRACTS,
    equity_event_prerequisites,
)
from backend.shared.tushare_futures_extra_contracts import futures_extra_prerequisites
from backend.shared.tushare_research_extra_contracts import (
    fina_mainbz_vip_prerequisites,
    research_extra_prerequisites,
)
from backend.shared.tushare_etf_basket_contracts import etf_basket_prerequisites
from backend.shared.tushare_credit_extra_contracts import (
    credit_identifiers,
    credit_extra_prerequisites,
)
from backend.shared.tushare_connect_contracts import (
    CONNECT_CONTRACTS,
    connect_prerequisites,
)
from backend.shared.tushare_calendar_extra_contracts import (
    ECO_CAL_OBSERVED_FANOUT,
)
from backend.shared.tushare_trading_event_contracts import trading_event_prerequisites
from backend.shared.tushare_listing_extra_contracts import (
    DAILY_INFO_STARTS,
    listing_extra_prerequisites,
)
from backend.shared.tushare_limit_extra_contracts import limit_extra_prerequisites
from backend.shared.tushare_concept_extra_contracts import concept_extra_prerequisites
from backend.shared.tushare_dc_extra_contracts import dc_extra_prerequisites
from backend.shared.runtime_secrets import get_secret
from backend.shared.stock_utils import StockCodeUtil
from backend.shared.tushare_intake import (
    capture_sample, digest, json_bytes, utc_now, validate_request_shape,
)
from backend.shared.tushare_market_contracts import iter_market_date_refresh
from backend.shared.tushare_rrg_contracts import RRG_CONTRACTS
from backend.shared.tushare_stock_lifecycle import valid_date
from backend.shared.tushare_text_contracts import normalize_anns_d_ts_code

STOCK_IDENTIFIER_SOURCE_APIS = (
    "stock_basic",
    *sorted(SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS),
)
ANNOUNCEMENT_IDENTIFIER_SOURCE_APIS = STOCK_IDENTIFIER_SOURCE_APIS
IDENTIFIER_SPLIT_SOURCE_APIS = {
    "stocks": STOCK_IDENTIFIER_SOURCE_APIS,
    "announcement_securities": ANNOUNCEMENT_IDENTIFIER_SOURCE_APIS,
    "dc_indices": ("dc_index", "dc_member", "dc_daily"),
    "otc_bonds": ("bc_otcqt", "bc_bestotcqt"),
    "tdx_indices": ("tdx_index", "tdx_member", "tdx_daily"),
    "kpl_concepts": ("kpl_concept_cons",),
}
LEGACY_IDENTIFIER_RECOVERY_APIS = tuple(
    sorted(
        api
        for api, spec in EXTENDED_CONTRACTS.items()
        if spec.get("recover_legacy_blocked_identifier_fanout")
    )
)
LEGACY_OBSERVED_RECOVERY_APIS = tuple(
    sorted(
        api
        for api, spec in EXTENDED_CONTRACTS.items()
        if spec.get("recover_legacy_blocked_observed_fanout")
    )
)
LEGACY_DATE_RECOVERY_APIS = tuple(
    sorted(
        api
        for api, spec in EXTENDED_CONTRACTS.items()
        if spec.get("recover_legacy_blocked_date_bisection")
    )
)
IDENTIFIER_CACHE_VERSION = 4
RANGE_REPLACEMENT_GAP = "replaced_by_stock_range_plan_v1"
INDEX_PERIOD_REPLACEMENT_GAP = "replaced_by_index_period_plan_v1"
REPLACEMENT_GAPS = frozenset(
    (RANGE_REPLACEMENT_GAP, INDEX_PERIOD_REPLACEMENT_GAP)
)
ROOT = Path(os.getenv("QM_TUSHARE_ARCHIVE_ROOT", "/data/tushare"))
MAX_DOCUMENT_REGISTRATION_RECORDS = 200_000
DOCUMENT_REGISTRATION_CHUNK_RECORDS = 1_000
CONTRACTS = {
    api: (spec["row_cap"], spec["required_fields"])
    for api, spec in RRG_CONTRACTS.items()
}


def _saturation_partition_axis(spec, params):
    """Return the first legal response-derived partition not already applied."""
    axes = spec.get("saturation_partition_axes")
    if axes is None:
        param = spec.get("saturation_partition_param")
        if not param:
            return None
        axes = [
            {
                "param": param,
                "values": spec.get("saturation_partition_values", []),
                "value_kind": spec.get("saturation_partition_value_kind", "code"),
            }
        ]
    if not isinstance(axes, (list, tuple)) or not axes:
        raise ValueError("Invalid saturation partition axes")
    seen, normalized = set(), []
    for index, axis in enumerate(axes):
        if not isinstance(axis, dict) or set(axis) - {
            "param",
            "output_field",
            "values",
            "value_kind",
        }:
            raise ValueError("Invalid saturation partition axis")
        param = axis.get("param")
        output_field = axis.get("output_field", param)
        values = axis.get("values", [])
        value_kind = axis.get("value_kind", "code")
        if (
            not isinstance(param, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", param)
            or not isinstance(output_field, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", output_field)
            or param in seen
            or not isinstance(values, (list, tuple))
            or value_kind not in ("code", "supplier_text")
        ):
            raise ValueError("Invalid saturation partition axis")
        seen.add(param)
        normalized.append(
            {
                "param": param,
                "output_field": output_field,
                "values": values,
                "value_kind": value_kind,
                "index": index,
                "count": len(axes),
            }
        )
    for axis in normalized:
        param = axis["param"]
        if param not in params:
            return axis
    return None


def _planning_inputs(family, config, identifiers):
    """Only request-planner dependencies affect a family's enumeration.

    Saturation-only universes remain live in date_children; they do not change
    the planner stream and must not restart it. Legacy structured declarations
    omit two direct dependencies, so retain those explicit adapter mappings.
    """
    contracts = {
        api: spec for api, spec in EXTENDED_CONTRACTS.items() if spec["group"] == family
    }
    if family == "market_members":
        contracts = {api: EXTENDED_CONTRACTS[api] for api in MARKET_MEMBER_APIS}
    if family == "stock_rewards_periods":
        contracts = {"stk_rewards": EXTENDED_CONTRACTS["stk_rewards"]}
    if family == "equity_announcements":
        contracts = {api: EXTENDED_CONTRACTS[api] for api in ANNOUNCEMENTS}
    if family == "fund_share_history":
        contracts = {"fund_share": EXTENDED_CONTRACTS["fund_share"]}
    selected = (
        ("stk_rewards",)
        if family == "stock_rewards_periods"
        else ("fund_share",)
        if family == "fund_share_history"
        else tuple(
            api
            for api in config.get("equity_event_apis", EQUITY_EVENT_CONTRACTS)
            if api in ANNOUNCEMENTS
        )
        if family == "equity_announcements"
        else config.get(family + "_apis", tuple(contracts))
    )
    if any(api not in contracts for api in selected):
        raise ValueError("Unknown " + family + " API")
    contracts = {api: contracts[api] for api in selected}
    dependencies = {
        dep
        for api, spec in contracts.items()
        for dep in (
            spec["planning_dependencies_by_value_mode"].get(
                config.get("factor_library_value_mode", "factor_name"), spec.get("dependencies", ())
            ) if family == "factor_library" and api == "factor_value"
            and "planning_dependencies_by_value_mode" in spec else spec.get("dependencies", ())
        )
    }
    for api, dependency in (("namechange", "stocks"), ("index_daily", "indexes")):
        if api in contracts:
            dependencies.add(dependency)
    if family == "market_members":
        dependencies.update(MARKET_MEMBER_DEPENDENCIES[api] for api in contracts)
    keys = {"history_start", family + "_apis"}
    if family == "market":
        keys.add("fund_nav_recent_date_pagination")
    if family == "portfolio_read":
        keys = {"portfolio_read_apis", "portfolio_read_snapshot_epoch"}
    if family == "market_members":
        keys.remove("history_start")
    if family not in ("structured", "market", "portfolio_read"):
        # This family name already ends in history; its public scope key does not
        # repeat that suffix. Hash the key actually consumed by its pure planner.
        keys.add(
            "securities_lending_history_start"
            if family == "securities_lending_history"
            else family + "_history_start"
        )
    if family in ("realtime_extra", "realtime_replay"):
        keys.update((family + "_frequencies", family + "_snapshot_epoch"))
        if family == "realtime_replay":
            keys.add("realtime_replay_futures_scope")
    if family == "history_minutes":
        keys.add("history_minutes_frequencies")
    if family == "factor_library":
        keys.add("factor_library_value_mode")
        # Omitted/explicit daily preserve existing policy hashes and cursors.
        # Switching to month is an explicit policy migration, never offset reuse.
        if config.get("factor_library_history_window", "daily") != "daily":
            keys.add("factor_library_history_window")
    if family == "foreign_financial":
        keys.add("foreign_financial_recent_days")
    if family == "text":
        keys.update(("text_history_starts", "text_history_window"))
    if family == "stock_rewards_periods":
        # Internal append scope: only actual pairs affect its finite stream.
        # Parent stock_context validation/selection gates it; no new config keys.
        dependencies = {"stock_context_reward_periods"}
        keys = set()
    if family == "equity_announcements":
        # Reuse the parent contracts and source request identities while keeping
        # its large per-stock cursor immutable.
        dependencies = set()
        keys = {"history_start", "equity_event_apis", "equity_event_history_start"}
    if family == "fund_share_history":
        dependencies = set()
        keys = {"history_start"}
    policy = digest(
        json_bytes(
            {
                "config": {key: config[key] for key in sorted(keys) if key in config},
                "contracts": contracts,
            }
        )
    )
    # Copy only necessary discovery. Stored snapshots survive process restarts;
    # no contracts or configuration values are repeated in manifest planning.
    frozen = {key: identifiers.get(key, []) for key in sorted(dependencies)}
    return policy, frozen


def _planning_snapshot(state):
    if state is None:
        return None
    try:
        value = json.loads(state["signature"])
    except (ValueError, TypeError):
        return None  # Legacy global digest: one conservative, idempotent replay.
    return value if isinstance(value, dict) and value.get("version") == 1 else None


def atomic_json(path, value):
    atomic_bytes(path, json_bytes(value))


def atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with tmp.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def serialize_manifest_file(directory, content, timing=None):
    """Write the same CPython JSON chunks without joining the whole manifest.

    _one_shot=True keeps the C encoder used by json.dumps. It still builds an
    eager sequence, sometimes containing one manifest-sized Unicode string.
    Bound the later UTF-8/write buffer by slicing each encoder chunk; this does
    not change the C encoder's O(manifest) Unicode memory.
    """
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Unsafe release directory")
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (".manifest-" + uuid4().hex + ".tmp")
    stream = temporary.open("xb")
    timing = {} if timing is None else timing
    started = time.monotonic()
    try:
        with stream:
            chunks = json.JSONEncoder(ensure_ascii=False, sort_keys=True).iterencode(
                content, _one_shot=True
            )
            timing["chunk_generation_seconds"] = time.monotonic() - started
            timing["eager_chunks"] = isinstance(chunks, (list, tuple))
            sha = hashlib.sha256()
            size, count, maximum = 0, 0, 0
            for chunk in chunks:
                for offset in range(0, len(chunk), 1 << 20):
                    raw = chunk[offset : offset + (1 << 20)].encode("utf-8")
                    stream.write(raw)
                    sha.update(raw)
                    size += len(raw)
                    count += 1
                    maximum = max(maximum, len(raw))
            stream.flush()
            os.fsync(stream.fileno())
            timing.update(bytes=size, chunks=count, largest_chunk_bytes=maximum)
            timing["total_seconds"] = time.monotonic() - started
        return temporary, sha.hexdigest()
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def authority():
    if os.getenv("QM_NODE_ROLE") == "authority" and (ROOT / "ARCHIVE_RELOCATED.json").exists():
        raise ValueError("Cloud archive acquisition has been relocated to Mac/NAS")
    if os.getenv("QM_NODE_ROLE") == "archive":
        import socket
        marker = ROOT / "ARCHIVE_AUTHORITY.json"
        if not ROOT.is_absolute() or ROOT.resolve() != ROOT or marker.is_symlink():
            raise ValueError("Invalid archive authority directory")
        state = json.loads(marker.read_bytes())
        if state.get("owner_hostname") != socket.gethostname() or state.get("migration_verified") is not True:
            raise ValueError("Archive authority migration is not verified")
        return
    if (
        os.getenv("QM_NODE_ROLE") != "authority"
        or not Path("/.dockerenv").exists()
        or not Path("/data").is_mount()
        or ROOT.resolve() != ROOT
    ):
        raise ValueError("Acquisition requires the verified cloud authority mount")


def blocked_obligations_status(db):
    """Classify retained blocked jobs without changing their evidence."""
    rows = db.execute(
        """
        SELECT json_extract(job.job,'$.api_name') AS api_name,
               CASE
                 WHEN split.status='blocked'
                      AND split.gap GLOB 'replaced_by_*'
                   THEN 'replacement_plan_retained_parent'
                 WHEN json_extract(job.result,'$.status')='api_error'
                      AND json_extract(job.result,'$.code')=40101
                      AND json_extract(job.result,'$.supplier_api_unavailable')=1
                   THEN 'supplier_api_unavailable'
                 WHEN json_extract(job.result,'$.status')='rate_limited'
                   THEN 'retained_rate_limit_probe'
                 WHEN json_extract(job.result,'$.status')='possibly_truncated'
                      AND split.gap IS NOT NULL
                   THEN 'retained_partition_gap'
                 WHEN json_extract(job.result,'$.status')='possibly_truncated'
                   THEN 'unsplittable_source_cap'
                 ELSE 'unclassified'
               END AS kind,
               count(*) AS jobs
        FROM jobs AS job INDEXED BY jobs_pending
        LEFT JOIN partition_splits AS split ON split.parent_id=job.id
        WHERE job.state='blocked'
        GROUP BY api_name,kind
        ORDER BY kind,api_name
        """
    )
    by_kind = {}
    total = 0
    for row in rows:
        jobs = row["jobs"]
        total += jobs
        group = by_kind.setdefault(row["kind"], {"jobs": 0, "apis": {}})
        group["jobs"] += jobs
        group["apis"][row["api_name"]] = jobs
    unclassified = by_kind.get("unclassified", {}).get("jobs", 0)
    return {
        "total": total,
        "by_kind": by_kind,
        "unclassified": unclassified,
        "all_blocked_jobs_classified": unclassified == 0,
        "changes_job_state": False,
    }


class Pipeline:
    def __init__(self, root, catalog):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = catalog
        self.db = sqlite3.connect(self.root / "pipeline.sqlite", timeout=10)
        requested_journal = os.getenv(
            "QM_TUSHARE_SQLITE_JOURNAL_MODE", "WAL"
        ).strip().upper()
        if requested_journal not in ("WAL", "DELETE"):
            self.db.close()
            raise ValueError("Invalid Tushare SQLite journal mode")
        try:
            journal = self.db.execute("PRAGMA journal_mode").fetchone()[0]
            if str(journal).upper() != requested_journal:
                journal = self.db.execute(
                    "PRAGMA journal_mode=" + requested_journal
                ).fetchone()[0]
            self.db.execute("PRAGMA synchronous=FULL")
        except BaseException:
            self.db.close()
            raise
        if str(journal).upper() != requested_journal:
            self.db.close()
            raise ValueError("Tushare SQLite journal mode unavailable")
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("pragma user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, 4, 5, 6):
            raise ValueError("Unsupported pipeline schema version")
        # Version 1 migration: SQLite is acquisition state, never copied live.
        if version == 0:
            self.db.executescript("""
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, epoch TEXT NOT NULL,
                    job TEXT NOT NULL, priority INTEGER NOT NULL, state TEXT NOT NULL,
                    tries INTEGER NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
                    result TEXT, expanded INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX jobs_pending ON jobs(state, priority, retry_after);
                PRAGMA user_version=1;
            """)

        if version < 2:
            # v2: rate reservations survive worker replacement; one cloud writer.
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS request_gates (
                    scope TEXT PRIMARY KEY, next_at REAL NOT NULL);
                PRAGMA user_version=2;
            """)

        if version < 3:
            self.db.executescript("""
                ALTER TABLE jobs ADD COLUMN group_name TEXT NOT NULL DEFAULT 'rrg';
                CREATE INDEX jobs_group_pending ON jobs(state,group_name,priority,retry_after);
                CREATE TABLE IF NOT EXISTS planning_state (
                    name TEXT PRIMARY KEY, anchor TEXT NOT NULL, signature TEXT NOT NULL,
                    offset INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS attempts (
                    job_id TEXT NOT NULL, attempt INTEGER NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(job_id,attempt));
                INSERT OR IGNORE INTO attempts SELECT id,tries,result FROM jobs WHERE result IS NOT NULL;
                CREATE TABLE IF NOT EXISTS capability (
                    scope TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL, reason TEXT);
                CREATE TABLE IF NOT EXISTS scheduler_state (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
                PRAGMA user_version=3;
            """)
        if version < 4:
            self.db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS partition_splits (
                    parent_id TEXT PRIMARY KEY, method TEXT NOT NULL,
                    expected_children INTEGER NOT NULL, coverage_proven INTEGER NOT NULL,
                    evidence TEXT NOT NULL, status TEXT NOT NULL, gap TEXT);
                CREATE TABLE IF NOT EXISTS partition_children (
                    parent_id TEXT NOT NULL, child_id TEXT NOT NULL,
                    PRIMARY KEY(parent_id,child_id), CHECK(parent_id<>child_id));
                CREATE INDEX IF NOT EXISTS partition_child_parent
                    ON partition_children(child_id,parent_id);
                CREATE INDEX IF NOT EXISTS jobs_partition_lookup
                    ON jobs(epoch,json_extract(job,'$.api_name'));
            """)
            self.recover_legacy_partitions()
            self.db.execute("PRAGMA user_version=4")
            self.db.commit()
        if version < 5:
            # Partial indexes keep priority,rowid order without sorting every
            # equal-priority pending job; expansion visits only unexpanded rows.
            try:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE INDEX IF NOT EXISTS jobs_ready_group
                        ON jobs(group_name,priority) WHERE state='pending';
                    CREATE INDEX IF NOT EXISTS jobs_ready_order
                        ON jobs(priority) WHERE state='pending';
                    CREATE INDEX IF NOT EXISTS jobs_unexpanded
                        ON jobs(state,group_name,priority,retry_after)
                        WHERE expanded=0 AND state IN ('done','quality','empty');
                    PRAGMA user_version=5;
                    COMMIT;
                """)
            except BaseException:
                self.db.rollback()
                self.db.close()
                raise
        if version < 6:
            # API seeks and bucket heads avoid scanning the structured backlog.
            # No job, observation or planning cursor is rewritten by migration.
            try:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE INDEX IF NOT EXISTS jobs_ready_api_history
                        ON jobs(group_name,json_extract(job,'$.api_name'),
                                (epoch='history'),priority)
                        WHERE state='pending';
                    PRAGMA user_version=6;
                    COMMIT;
                """)
            except BaseException:
                self.db.rollback()
                self.db.close()
                raise
        discovery_indexes = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('jobs_discovery_api','attempts_discovery_api')"
        ).fetchall()
        if len(discovery_indexes) != 2:
            # Discovery reads only completed results and historical attempts;
            # millions of pending jobs must not be scanned for each fanout.
            # Tables/rows retain the v6 contract used by offline batch tools.
            try:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE INDEX IF NOT EXISTS jobs_discovery_api
                        ON jobs(json_extract(job,'$.api_name'))
                        WHERE result IS NOT NULL;
                    CREATE INDEX IF NOT EXISTS attempts_discovery_api
                        ON attempts(json_extract(result,'$.api_name'));
                    COMMIT;
                """)
            except BaseException:
                self.db.rollback()
                self.db.close()
                raise
        if self.db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='index' AND name='jobs_open_logical'"
        ).fetchone() is None:
            # Recent observation epochs may overlap while a large saturation
            # fanout is still pending. Seek the already-open logical request
            # before adding another daily root; history remains independent.
            try:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE INDEX IF NOT EXISTS jobs_open_logical
                        ON jobs(logical_key)
                        WHERE state IN ('pending','split_pending');
                    COMMIT;
                """)
            except BaseException:
                self.db.rollback()
                self.db.close()
                raise
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS identifier_discovery_cache (
                version INTEGER PRIMARY KEY, attempt_rowid INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL, result TEXT NOT NULL,
                objects TEXT NOT NULL)
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS contract_reassessments (
                job_id TEXT PRIMARY KEY,
                reassessed_at TEXT NOT NULL,
                contract_sha256 TEXT NOT NULL,
                result TEXT NOT NULL)
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS normalization_recoveries (
                job_id TEXT PRIMARY KEY,
                recovered_at TEXT NOT NULL,
                normalizer_sha256 TEXT NOT NULL,
                result TEXT NOT NULL)
        """)
        # A pipelined request is made durable before HTTP. If the process dies
        # after that reservation, the next owner may safely retry the job; the
        # account/API gate remains conservative and is never rolled back.
        self.recovered_inflight = self.db.execute(
            "UPDATE jobs SET state='pending' WHERE state='inflight'"
        ).rowcount
        self.db.commit()
        cursor = self.db.execute(
            "SELECT value FROM scheduler_state WHERE name='family_turn'"
        ).fetchone()
        self._fair_turn = cursor[0] if cursor else 0
        self._partition_artifact_checks = {}
        self.fields = {}
        for entry in catalog["entries"]:
            for api in entry.get("api_names", []):
                self.fields.setdefault(api, set()).update(
                    entry.get("output_fields", [])
                )

    def _next_structured_job(self, now, check_gates=True):
        return self._next_family_job("structured", now, check_gates)

    def _next_exact_task_job(self, now, check_gates=True):
        """Round-robin APIs only inside the connection-local exact task scope."""
        prefix = "exact_batch_api_turn:"
        previous = self.db.execute(
            "SELECT name,value FROM scheduler_state WHERE name GLOB ? "
            "ORDER BY value DESC,name LIMIT 1",
            (prefix + "*",),
        ).fetchone()
        cursor = previous["name"][len(prefix) :] if previous else None
        turn = previous["value"] + 1 if previous else 1
        seen = set()
        while True:
            candidate = self.db.execute(
                "SELECT json_extract(j.job,'$.api_name') AS api "
                "FROM exact_task_scope s CROSS JOIN jobs j ON j.id=s.task_id "
                "WHERE j.state='pending' "
                + (
                    "AND json_extract(j.job,'$.api_name')>? "
                    if cursor is not None
                    else ""
                )
                + "ORDER BY json_extract(j.job,'$.api_name') LIMIT 1",
                (cursor,) if cursor is not None else (),
            ).fetchone()
            if candidate is None and cursor is not None:
                cursor = None
                continue
            if candidate is None:
                return None, []
            api = candidate["api"]
            if not isinstance(api, str) or not api:
                raise ValueError("Exact pending job has missing/invalid api_name")
            if api in seen:
                return None, []
            seen.add(api)
            cursor = api
            if check_gates:
                gate = self.db.execute(
                    "SELECT next_at FROM request_gates WHERE scope=?", ("api:" + api,)
                ).fetchone()
                if gate and gate[0] > now:
                    continue
            row = self.db.execute(
                "SELECT j.* FROM exact_task_scope s CROSS JOIN jobs j ON j.id=s.task_id "
                "WHERE j.state='pending' AND json_extract(j.job,'$.api_name')=? "
                "AND j.retry_after<=? ORDER BY j.priority,j.rowid LIMIT 1",
                (api, now),
            ).fetchone()
            if row:
                return row, [(prefix + api, turn)]

    def _next_family_job(self, family, now, check_gates=True):
        """Seek pending APIs; preserve structured keys and isolate other families."""
        namespace = (
            "structured_"
            if family == "structured"
            else "family:" + family.encode("utf-8").hex() + ":"
        )
        prefix = namespace + "api_turn:"
        previous = self.db.execute(
            "SELECT name,value FROM scheduler_state WHERE name GLOB ? ORDER BY value DESC,name LIMIT 1",
            (prefix + "*",),
        ).fetchone()
        cursor = previous["name"][len(prefix) :] if previous else None
        turn = previous["value"] + 1 if previous else 1
        seen = set()
        while True:
            sql = """SELECT json_extract(job,'$.api_name') AS api
                FROM jobs INDEXED BY jobs_ready_api_history
                WHERE state='pending' AND group_name=? {after}
                ORDER BY json_extract(job,'$.api_name') LIMIT 1"""
            candidate = self.db.execute(
                sql.format(
                    after="AND json_extract(job,'$.api_name')>?"
                    if cursor is not None
                    else ""
                ),
                (family, cursor) if cursor is not None else (family,),
            ).fetchone()
            if candidate is None and cursor is not None:
                cursor = None
                continue
            if candidate is None:
                return None, []
            api = candidate["api"]
            if not isinstance(api, str) or not api:
                raise ValueError(
                    f"{family} pending job has missing/invalid api_name; queue preserved"
                )
            if api in seen:
                return None, []
            seen.add(api)
            cursor = api
            if check_gates:
                gate = self.db.execute(
                    "SELECT next_at FROM request_gates WHERE scope=?", ("api:" + api,)
                ).fetchone()
                if gate and gate[0] > now:
                    continue
            phase_name = namespace + "phase:" + api
            phase_row = self.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?", (phase_name,)
            ).fetchone()
            phase = phase_row[0] % 4 if phase_row else 0
            history = int(phase == 3)
            for bucket in (history, 1 - history):
                row = self.db.execute(
                    """SELECT * FROM jobs INDEXED BY jobs_ready_api_history
                    WHERE state='pending' AND group_name=?
                      AND json_extract(job,'$.api_name')=? AND (epoch='history')=?
                      AND retry_after<=? ORDER BY priority,rowid LIMIT 1""",
                    (family, api, bucket, now),
                ).fetchone()
                if row:
                    # Advance the scheduled opportunity even when an empty bucket
                    # borrowed the other one, or the ensuing request later fails.
                    return row, [(prefix + api, turn), (phase_name, (phase + 1) % 4)]

    def _next_throughput_job(self, apis, now):
        """Round-robin an explicitly reviewed fast lane without starving families."""
        prefix = "throughput_api_turn:"
        previous = self.db.execute(
            "SELECT name,value FROM scheduler_state WHERE name GLOB ? "
            "ORDER BY value DESC,name LIMIT 1",
            (prefix + "*",),
        ).fetchone()
        cursor = previous["name"][len(prefix) :] if previous else None
        turn = previous["value"] + 1 if previous else 1
        start = (apis.index(cursor) + 1) if cursor in apis else 0
        for offset in range(len(apis)):
            api = apis[(start + offset) % len(apis)]
            gate = self.db.execute(
                "SELECT next_at FROM request_gates WHERE scope=?", ("api:" + api,)
            ).fetchone()
            if gate and gate[0] > now:
                continue
            family = contract_for(api).get("group")
            phase_name = "throughput_phase:" + api
            phase_row = self.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?", (phase_name,)
            ).fetchone()
            phase = phase_row[0] % 4 if phase_row else 0
            history = int(phase == 3)
            for bucket in (history, 1 - history):
                row = self.db.execute(
                    """SELECT * FROM jobs INDEXED BY jobs_ready_api_history
                    WHERE state='pending' AND group_name=?
                      AND json_extract(job,'$.api_name')=? AND (epoch='history')=?
                      AND retry_after<=? ORDER BY priority,rowid LIMIT 1""",
                    (family, api, bucket, now),
                ).fetchone()
                if row:
                    return row, [
                        (prefix + api, turn),
                        (phase_name, (phase + 1) % 4),
                    ]
        return None, []

    def next_job(self, config, deadline, *, task_scope=False, mark_inflight=False):
        # Preserve legacy structured fallback behavior; extend only enabled families.
        fair_families = {"structured"} | {
            name for name in PLANNERS if name != "rrg" and config.get("enable_" + name)
        }
        from backend.shared.tushare_rate_policy import enabled, positive_int, resolved_api_rate

        rpm = config.get("requests_per_minute")
        if enabled(config) and rpm is None:
            raise ValueError("Tiered rate policy requires an account ceiling")
        if enabled(config) and config.get("rollout_account_rpm") is not None:
            rollout = positive_int(config["rollout_account_rpm"], "rollout account rate")
            if rpm is None:
                raise ValueError("Tiered rate policy requires an account ceiling")
            rpm = min(positive_int(rpm, "account request rate"), rollout)
        if rpm is None:
            now = time.time()
            if task_scope:
                row = self.db.execute(
                    "SELECT j.* FROM exact_task_scope s CROSS JOIN jobs j "
                    "ON j.id=s.task_id WHERE j.state='pending' AND j.retry_after<=? "
                    "ORDER BY j.priority,j.rowid LIMIT 1",
                    (now,),
                ).fetchone()
            else:
                row = self.db.execute(
                    "SELECT * FROM jobs INDEXED BY jobs_ready_order "
                    "WHERE state='pending' AND retry_after<=? "
                    "ORDER BY priority,rowid LIMIT 1",
                    (now,),
                ).fetchone()
            checkpoints = []
            if row and task_scope:
                row, checkpoints = self._next_exact_task_job(
                    now, check_gates=False
                )
            elif row and row["group_name"] in fair_families:
                row, checkpoints = self._next_family_job(
                    row["group_name"], now, check_gates=False
                )
            if row:
                try:
                    validate_request_shape(json.loads(row["job"]))
                except ValueError:
                    return row  # run records the gap without a rate/fairness reservation.
            if checkpoints or (row and mark_inflight):
                try:
                    if checkpoints:
                        self.db.executemany(
                            "INSERT INTO scheduler_state(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                            checkpoints,
                        )
                    if row and mark_inflight:
                        updated = self.db.execute(
                            "UPDATE jobs SET state='inflight' "
                            "WHERE id=? AND state='pending'",
                            (row["id"],),
                        ).rowcount
                        if updated != 1:
                            raise RuntimeError("Failed to reserve selected job")
                    self.db.commit()
                except BaseException:
                    self.db.rollback()
                    raise
            return row
        if not 1 <= int(rpm) <= 500:
            raise ValueError("Invalid account request rate")
        throughput_apis = config.get("throughput_fast_lane_apis", [])
        throughput_every = config.get("throughput_fast_lane_every")
        if throughput_apis:
            if (
                not isinstance(throughput_apis, list)
                or not 1 <= len(throughput_apis) <= 32
                or any(not isinstance(api, str) or not api for api in throughput_apis)
                or len(throughput_apis) != len(set(throughput_apis))
                or isinstance(throughput_every, bool)
                or not isinstance(throughput_every, int)
                or not 2 <= throughput_every <= 100
            ):
                raise ValueError("Invalid throughput fast lane configuration")
            for api in throughput_apis:
                spec = contract_for(api)
                resolved = resolved_api_rate(api, spec, config)
                if (
                    not isinstance(spec.get("group"), str)
                    or not spec["group"]
                    or (
                        spec["group"] not in ("rrg", "structured")
                        and not config.get("enable_" + spec["group"])
                    )
                    or resolved.get("review_required")
                    or resolved.get("rpm") != int(rpm)
                ):
                    raise ValueError(
                        "Throughput fast lane requires reviewed account-rate APIs"
                    )
        elif throughput_every is not None:
            raise ValueError("Throughput cadence requires a non-empty API list")
        while time.monotonic() < deadline:
            now = time.time()
            account = self.db.execute(
                "SELECT next_at FROM request_gates WHERE scope='account'"
            ).fetchone()
            account_wait = max(0, account[0] - now) if account else 0
            if account_wait:
                if account_wait >= deadline - time.monotonic():
                    return None
                wait_started = time.perf_counter()
                profile = getattr(self, "_selection_profile", None)
                if profile is not None:
                    profile["seconds"]["account_gate_requested_sleep"] += account_wait
                try:
                    time.sleep(account_wait)
                finally:
                    if profile is not None:
                        profile["seconds"]["account_gate_sleep"] += (
                            time.perf_counter() - wait_started
                        )
                        profile["counts"]["account_gate_sleeps"] += 1
                continue
            if not task_scope:
                groups = ["rrg"] + [
                    name for name in PLANNERS if config.get("enable_" + name)
                ]
                weights = config.get("group_weights", {})
                if any(not 1 <= int(weights.get(name, 1)) <= 10 for name in groups):
                    raise ValueError("Invalid family scheduling weight")
                groups = [
                    name for name in groups for _ in range(int(weights.get(name, 1)))
                ]
                group = groups[self._fair_turn % len(groups)]
            else:
                group = None
            sql = """SELECT j.* FROM jobs j INDEXED BY {ready_index} LEFT JOIN request_gates g
                ON g.scope='api:' || json_extract(j.job,'$.api_name')
                WHERE j.state='pending' AND j.retry_after<=? AND COALESCE(g.next_at,0)<=?
                {group_filter} ORDER BY j.priority,j.rowid LIMIT 1"""
            checkpoints = []
            if task_scope:
                # An exact batch is fair across its APIs regardless of the normal
                # family policy. The same account/API gates and reservations below
                # still apply, and priority remains ordered within each API.
                row, checkpoints = self._next_exact_task_job(now)
            elif throughput_apis and self._fair_turn % throughput_every == 0:
                row, checkpoints = self._next_throughput_job(
                    throughput_apis, now
                )
                if row is None:
                    if group in fair_families:
                        row, checkpoints = self._next_family_job(group, now)
                    else:
                        row = self.db.execute(
                            sql.format(
                                group_filter="AND j.group_name=?",
                                ready_index="jobs_ready_group",
                            ),
                            (now, now, group),
                        ).fetchone()
            elif group in fair_families:
                row, checkpoints = self._next_family_job(group, now)
            else:
                row = self.db.execute(
                    sql.format(
                        group_filter="AND j.group_name=?",
                        ready_index="jobs_ready_group",
                    ),
                    (now, now, group),
                ).fetchone()
            if row is None and not task_scope:
                row = self.db.execute(
                    sql.format(group_filter="", ready_index="jobs_ready_order"),
                    (now, now),
                ).fetchone()
                if row and row["group_name"] in fair_families:
                    row, checkpoints = self._next_family_job(row["group_name"], now)
            if row:
                job = json.loads(row["job"])
                try:
                    validate_request_shape(job)
                except ValueError:
                    return row  # No rate or fairness budget for a locally invalid request.
                api = job["api_name"]
                resolved = resolved_api_rate(api, contract_for(api), config)
                api_rpm = resolved["rpm"]
                if not 1 <= api_rpm <= 500:
                    raise ValueError("Invalid API request rate")
                interval = config.get("api_min_interval_seconds", {}).get(api, 0)
                if (
                    isinstance(interval, bool)
                    or not isinstance(interval, (int, float))
                    or not 0 <= interval <= 86400
                ):
                    raise ValueError("Invalid API minimum request interval")
                quota = self.db.execute(
                    "SELECT reason FROM capability WHERE scope=? AND status='rate_limit_observed'",
                    ("quota:" + api,),
                ).fetchone()
                if quota:
                    interval = max(interval, json.loads(quota[0])["interval_seconds"])
                self.rate_gate_status = {
                    "last_api": api, "resolved_api_cap": resolved,
                    "effective_min_interval_seconds": max(60 / api_rpm, interval),
                    "effective_account_rpm": int(rpm),
                    "observed_quota_preserved": quota is not None,
                }
                reservation_started = time.perf_counter()
                try:
                    self.db.executemany(
                        "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=excluded.next_at",
                        [
                            ("account", now + 60 / int(rpm)),
                            ("api:" + api, now + max(60 / api_rpm, interval)),
                        ],
                    )
                    self.db.executemany(
                        "INSERT INTO scheduler_state(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                        checkpoints + [("family_turn", self._fair_turn + 1)],
                    )
                    if mark_inflight:
                        updated = self.db.execute(
                            "UPDATE jobs SET state='inflight' "
                            "WHERE id=? AND state='pending'",
                            (row["id"],),
                        ).rowcount
                        if updated != 1:
                            raise RuntimeError("Failed to reserve selected job")
                    self.db.commit()  # reserve before the request, including failures
                except BaseException:
                    self.db.rollback()
                    raise
                finally:
                    profile = getattr(self, "_selection_profile", None)
                    if profile is not None:
                        profile["seconds"]["gate_reservation_commit"] += (
                            time.perf_counter() - reservation_started
                        )
                        profile["counts"]["gate_reservations"] += 1
                self._fair_turn += 1
                return row
            earliest_sql = """
                SELECT MIN(MAX(j.retry_after,COALESCE(g.next_at,0)))
                FROM {source} LEFT JOIN request_gates g
                  ON g.scope='api:' || json_extract(j.job,'$.api_name')
                WHERE j.state='pending'
            """.format(
                source=(
                    "exact_task_scope s CROSS JOIN jobs j ON j.id=s.task_id"
                    if task_scope
                    else "jobs j"
                )
            )
            earliest = self.db.execute(earliest_sql).fetchone()[0]
            delay = max(0.01, earliest - now) if earliest is not None else None
            if delay is None or delay >= deadline - time.monotonic():
                return None
            wait_started = time.perf_counter()
            try:
                time.sleep(delay)
            finally:
                profile = getattr(self, "_selection_profile", None)
                if profile is not None:
                    profile["seconds"]["empty_queue_sleep"] += (
                        time.perf_counter() - wait_started
                    )
                    profile["counts"]["empty_queue_sleeps"] += 1
        return None

    def close(self):
        self.db.close()

    def enqueue(
        self,
        api,
        params,
        priority=10,
        epoch="history",
        *,
        reuse_recent_open=False,
    ):
        spec = contract_for(api)
        pagination = _pagination_for_params(spec, params)
        if pagination and (
            spec.get("group") == "global" or spec.get("pagination_live_verified")
        ):
            params = dict(params)
            params.setdefault(pagination["limit_param"], pagination["page_size"])
        cap, required = (
            CONTRACTS[api]
            if api in CONTRACTS
            else (spec["row_cap"], spec["required_fields"])
        )
        fields = sorted(
            self.fields.get(spec.get("catalog_api", api), set())
            | set(spec.get("extra_fields", []))
            | set(required)
        )
        if api in REALTIME_RUNTIME_CONTRACTS:
            fields = sorted(set(spec["extra_fields"]) | set(required))
        if not fields:
            raise ValueError("Missing reviewed schema")
        job = {
            "api_name": api,
            "params": params,
            "fields": ",".join(fields),
            "row_cap": cap,
            "required_fields": required,
            "nullable_fields": spec.get(
                "nullable_fields",
                ["out_date"]
                if api == "ci_index_member"
                else ["list_date"]
                if api == "etf_basic" and params.get("list_status") == "P"
                else [],
            ),
            "positive_fields": spec.get(
                "positive_fields",
                [f for f in ("open", "close", "adj_factor") if f in required],
            ),
        }
        logical = digest(json_bytes(job))
        key = digest(json_bytes([logical, epoch]))
        if reuse_recent_open and epoch != "history":
            existing = self.db.execute(
                "SELECT id FROM jobs INDEXED BY jobs_open_logical "
                "WHERE logical_key=? AND epoch<>'history' "
                "AND state IN ('pending','split_pending') ORDER BY rowid DESC LIMIT 1",
                (logical,),
            ).fetchone()
            if existing:
                return existing["id"]
        scope = api + ":" + str(params.get("src", ""))
        capability = self.db.execute(
            "SELECT status FROM capability WHERE scope=?",
            (scope,),
        ).fetchone()
        initial_state = (
            "permission_blocked"
            if capability and capability[0] == "permission_denied"
            else "blocked"
            if capability and capability[0] == "api_unavailable"
            else "pending"
        )
        self.db.execute(
            "INSERT OR IGNORE INTO jobs(id,logical_key,epoch,job,priority,state,group_name) VALUES(?,?,?,?,?,?,?)",
            (
                key,
                logical,
                epoch,
                json.dumps(job),
                priority,
                initial_state,
                spec.get("group", "rrg"),
            ),
        )
        return key

    def records(self, result, *, fields=None):
        if not result or "object_sha256" not in result:
            return []
        # Complete HTTP error bodies are immutable evidence, never market rows.
        if (
            result.get("status")
            in (
                "transport_error",
                "rate_limited",
                "permission_denied",
                "api_error",
                "invalid_response",
            )
            or result.get("response_format") == "non_json"
        ):
            return []
        payload = json.loads(
            (self.root / "objects" / (result["object_sha256"] + ".json")).read_bytes()
        )
        data = payload.get("data") or {}
        if fields is None:
            return [
                dict(zip(data.get("fields", []), row, strict=True))
                for row in data.get("items", [])
            ]
        source_fields = data.get("fields", [])
        # Last duplicate wins, exactly as dict(zip(...)). Validate every field's
        # hashability even when it is not requested by discovery.
        positions = {name: index for index, name in enumerate(source_fields)}
        selected = [(name, index) for name, index in positions.items() if name in fields]
        rows = []
        for row in data.get("items", []):
            if not isinstance(row, list) or len(row) != len(source_fields):
                # Preserve strict row-length errors and legacy non-array behavior.
                complete = dict(zip(source_fields, row, strict=True))
                rows.append(
                    {name: value for name, value in complete.items() if name in fields}
                )
            else:
                rows.append({name: row[index] for name, index in selected})
        return rows

    def normalize(self, result):
        import pyarrow as pa
        import pyarrow.parquet as pq

        rows = self.records(result)
        if not rows:
            return result
        observed = json.loads(
            (self.root / "observations" / result["observation"]).read_bytes()
        )
        identity_fields = contract_for(result["api_name"]).get(
            "request_identity_fields", []
        )
        if not isinstance(identity_fields, (list, tuple)) or any(
            not isinstance(field, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field)
            for field in identity_fields
        ):
            raise ValueError("Invalid contract request identity fields")
        request = observed.get("request")
        params = request.get("params", {}) if isinstance(request, dict) else {}
        params = params if isinstance(params, dict) else {}
        request_identity = {field: params.get(field) for field in identity_fields}
        missing = [
            field
            for field in identity_fields
            if (params.get(field) is None or params.get(field) == "")
            and field not in contract_for(result["api_name"]).get("optional_request_identity_fields", [])
        ]
        request_json = json_bytes(request_identity).decode("utf-8")
        for row in rows:
            raw_identity = digest(json_bytes(row))
            row["_row_identity"] = raw_identity
            if identity_fields:
                row["_raw_row_identity"] = raw_identity
                row["_request_identity"] = request_json
                row["_request_identity_status"] = (
                    "incomplete" if missing else "complete"
                )
                row["_request_identity_missing"] = json_bytes(missing).decode("utf-8")
                row["_row_identity"] = digest(
                    (raw_identity + "\n" + request_json).encode("utf-8")
                )
            row["_source"] = (
                params.get("src") or row.get("src") or row.get("src_site") or ""
            )
            row["_api_name"] = result["api_name"]
            if contract_for(result["api_name"]).get("group") == "etf_basket":
                # Arrow cannot hold numeric and '-' scalars in one column. Keep
                # queryable text plus exact original JSON types, after raw hashing.
                numeric = {
                    field: row[field]
                    for field in contract_for(result["api_name"])["raw_numeric_fields"]
                    if field in row
                }
                row["_raw_numeric_json"] = json_bytes(numeric).decode("utf-8")
                for field, value in numeric.items():
                    if value is not None and not isinstance(value, str):
                        row[field] = json_bytes(value).decode("utf-8")
            if contract_for(result["api_name"]).get("group") in (
                "concept_extra",
                "dc_extra",
            ):
                for field in ("con_code", "leading_code"):
                    if isinstance(row.get(field), str):
                        row["source_" + field] = row[field]
            if result["api_name"] in REALTIME_RUNTIME_CONTRACTS:
                project_realtime_row(result["api_name"], row, params)
            if result["api_name"] == "stk_account_old":
                try:
                    begin, end = project_account_period(row.get("date"))
                except ValueError:
                    begin, end = None, None
                row["_period_start"] = begin
                row["_period_end"] = end
                row["_period_projection_status"] = (
                    "projected" if begin else "period_projection_unverified"
                )
            if result["api_name"] in SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS:
                code = row.get("ts_code")
                if not isinstance(code, str) or not re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", code):
                    raise ValueError("Lending source stock code requires schema review")
            if result["api_name"] == "factor_value":
                code, name = row.get("ts_code"), row.get("factor_name")
                if (
                    not isinstance(code, str)
                    or not re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", code)
                    or not isinstance(name, str) or not name.strip()
                ):
                    raise ValueError("Factor value requires a source STK code and factor_name; schema review required")
            if result["api_name"] in BOND_EXTRA_RUNTIME_CONTRACTS:
                value = row.get("ts_code")
                if not isinstance(value, str) or not value:
                    raise ValueError("Bond source code must be a string; schema review required")
                row["source_ts_code"] = value
                row["ts_code"] = BOND_EXTRA_RUNTIME_CONTRACTS[result["api_name"]]["source_namespace"] + value
            if result["api_name"] in MARKET_SENTIMENT_RUNTIME_CONTRACTS:
                api = result["api_name"]
                namespace = (
                    "TDX" if api.startswith("tdx_") else
                    "KP" if api == "kpl_concept_cons" else
                    "CN" if api == "kpl_list" else
                    {
                        "热股": "CN", "A股市场": "CN",
                        "ETF": "FUND", "ETF基金": "FUND", "热基": "FUND",
                        "可转债": "CB", "行业板块": "THS:I",
                        "概念板块": "THS:N", "期货": "FUT",
                        "港股": "HK", "港股市场": "HK",
                        "美股": "US", "美股市场": "US",
                    }.get(params.get("market"), "UNVERIFIED_MARKET")
                )
                for field in ("ts_code", "con_code"):
                    value = row.get(field)
                    if not isinstance(value, str):
                        continue
                    row["source_" + field] = value
                    kind = "CN" if field == "con_code" else namespace
                    if kind == "CN" and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", value):
                        symbol, exchange = value.rsplit(".", 1)
                        row[field] = exchange + symbol
                    elif kind == "HK" and re.fullmatch(r"[0-9]{5}(?:![A-Z]{0,8})?\.HK", value):
                        row[field] = "HK" + value.removesuffix(".HK")
                    elif kind == "US":
                        row[field] = "US" + value
                    else:
                        # Unknown spellings keep an explicit asset namespace;
                        # only the immutable request can identify a ranking market.
                        row[field] = kind + ":" + value
            if result["api_name"] == "stk_ah_comparison":
                value = row.get("hk_code")
                if isinstance(value, str):
                    row["source_hk_code"] = value
                    if re.fullmatch(r"[0-9]{5}(?:![A-Z]{0,8})?\.HK", value):
                        row["hk_code"] = "HK" + value.removesuffix(".HK")
            code_fields = (
                "ts_code",
                "symbol",
                "l1_code",
                "l2_code",
                "l3_code",
                "index_code",
            )
            if result["api_name"] == "index_weight":
                code_fields += ("con_code",)
            for key in code_fields:
                if result["api_name"] in REALTIME_RUNTIME_CONTRACTS:
                    continue  # Already projected using source API/request asset identity.
                if result["api_name"] in PORTFOLIO_READ_RUNTIME_CONTRACTS:
                    # User-defined components may only look like securities. Keep
                    # the supplier spelling and use request identity for portfolio
                    # context instead of inventing an exchange or asset namespace.
                    if key == "ts_code" and isinstance(row.get(key), str):
                        row["source_ts_code"] = row[key]
                    continue
                if result["api_name"] in CALENDAR_EXTRA_RUNTIME_CONTRACTS or result["api_name"] in ACCOUNT_HISTORY_RUNTIME_CONTRACTS or result["api_name"] == "factor_list":
                    continue  # Calendar/factor taxonomy labels are not securities.
                if result["api_name"] == "factor_value" and key != "ts_code":
                    continue
                if key == "ts_code" and (result["api_name"] in MARKET_SENTIMENT_RUNTIME_CONTRACTS or result["api_name"] in BOND_EXTRA_RUNTIME_CONTRACTS):
                    continue
                value = row.get(key)
                if isinstance(value, str):
                    row["source_" + key] = value
                    if key == "ts_code" and result["api_name"] in HISTORY_MINUTES_RUNTIME_CONTRACTS:
                        kind = HISTORY_MINUTES_RUNTIME_CONTRACTS[result["api_name"]]["source_namespace"]
                        if kind == "CN" and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", value):
                            symbol, exchange = value.rsplit(".", 1)
                            row[key] = exchange + symbol
                        elif kind == "HK" and re.fullmatch(r"[0-9]{5}(?:![A-Z]{0,8})?\.HK", value):
                            row[key] = "HK" + value.removesuffix(".HK")
                        else:
                            row[key] = kind + ":" + value
                    elif (
                        key == "ts_code"
                        and result["api_name"] in CROSS_ASSET_RUNTIME_CONTRACTS
                    ):
                        # This asset family uses opaque, explicit namespaces before
                        # any generic stock-shaped code handling; raw code is retained.
                        row[key] = (
                            CROSS_ASSET_RUNTIME_CONTRACTS[result["api_name"]][
                                "source_namespace"
                            ]
                            + value
                        )
                    elif key == "ts_code" and (
                        result["api_name"] == "limit_cpt_list"
                        or contract_for(result["api_name"]).get("group")
                        in ("concept_extra", "dc_extra")
                    ):
                        # Supplier concept codes are opaque within this dataset;
                        # even stock-shaped future labels are not equity identities.
                        row[key] = value
                    elif result["api_name"] in OTHER_CONTRACTS and result[
                        "api_name"
                    ].startswith(("opt_", "sge_", "fx_")):
                        # Asset namespace precedes any stock-shaped symbol. Supplier
                        # values remain in source_* and the immutable raw response.
                        namespace = {"opt": "OPT:", "sge": "SGE:", "fx": "FX:"}[
                            result["api_name"].split("_", 1)[0]
                        ]
                        row[key] = namespace + value
                    elif (
                        key == "ts_code"
                        and (
                            result["api_name"] in GLOBAL_CONTRACTS
                            or result["api_name"] in FOREIGN_FINANCIAL_RUNTIME_CONTRACTS
                        )
                        and result["api_name"].startswith("us_")
                    ):
                        # US symbols are opaque supplier tickers, not suffix codes.
                        row[key] = "US" + value
                    elif (
                        key == "ts_code"
                        and (
                            result["api_name"] in GLOBAL_CONTRACTS
                            or result["api_name"] in FOREIGN_FINANCIAL_RUNTIME_CONTRACTS
                        )
                        and re.fullmatch(r"[0-9]{5}(?:![A-Z]{0,8})?\.HK", value)
                    ):
                        row[key] = "HK" + value.removesuffix(".HK")
                    elif re.fullmatch(r"T[0-9]{6}\.(SH|SZ|BJ)", value):
                        # Opaque historical supplier identity; T must not collapse
                        # into the ordinary numeric listing of the same exchange.
                        symbol, exchange = value.rsplit(".", 1)
                        row[key] = exchange + symbol
                    elif re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", value):
                        row[key] = StockCodeUtil.to_prefix(value)
                    elif (
                        key == "ts_code"
                        and (
                            result["api_name"] in GLOBAL_CONTRACTS
                            or result["api_name"] == "mkt_idx_bmk"
                        )
                        and re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", value)
                    ):
                        symbol, exchange = value.rsplit(".", 1)
                        row[key] = exchange + symbol
                    elif re.fullmatch(r"CI\d+\.CI", value):
                        row[key] = value.removesuffix(".CI")
                    elif (
                        key == "ts_code"
                        and result["api_name"] in ("irm_qa_sh", "irm_qa_sz")
                        and re.fullmatch(r"\d{6}", value)
                    ):
                        row[key] = (
                            "SH" if result["api_name"] == "irm_qa_sh" else "SZ"
                        ) + value
            row["_fetched_at"] = observed["fetched_at"]
            row["_observation"] = result["observation"]
        folder = self.root / "parquet"
        folder.mkdir(exist_ok=True)
        tmp = folder / (uuid4().hex + ".tmp")
        try:
            pq.write_table(pa.Table.from_pylist(rows), tmp, compression="zstd")
            sha = digest(tmp.read_bytes())
            destination = folder / (sha + ".parquet")
            if destination.exists() and digest(destination.read_bytes()) != sha:
                raise ValueError("Existing Parquet object is corrupt")
            if not destination.exists():
                tmp.replace(destination)
            result["parquet"] = {
                "path": "parquet/" + destination.name,
                "sha256": sha,
                "bytes": destination.stat().st_size,
            }
            if result["api_name"] == "stk_account_old":
                unverified = sum(row["_period_projection_status"] != "projected" for row in rows)
                result["period_projection_unverified_rows"] = unverified
                if unverified:
                    # Keep the complete Parquet and raw evidence. The existing run
                    # error path records blocked plus this explicit reason.
                    result["period_projection_gap"] = "period_projection_unverified"
                    raise ValueError("period_projection_unverified: raw periods retained")
            return result
        finally:
            tmp.unlink(missing_ok=True)

    def initialize(self, config, today):
        """One durable history queue plus explicit daily revision generations."""
        start = datetime.strptime(config["history_start"], "%Y%m%d").date()
        priority_start = config["priority_start"]
        end = today - timedelta(days=1)
        epoch = today.strftime("%Y%m%d")
        # Existing immutable probes bootstrap identifiers without re-fetching them.
        seed = config["seed_release"]
        manifest = json.loads(
            (self.root / "releases" / seed / "manifest.json").read_bytes()
        )
        industries = set()
        funds = {}
        for result in manifest["results"]:
            rows = self.records(result)
            if result["api_name"] == "ci_index_member":
                industries.update(r["l1_code"] for r in rows)
            if result["api_name"] == "etf_basic":
                funds.update({r["ts_code"]: r.get("list_date") for r in rows})
        # Industry discovery is refreshed from both current and historical members.
        for row in self.db.execute(
            "SELECT result FROM jobs WHERE result IS NOT NULL AND expanded=1 AND json_extract(job,'$.api_name') IN ('ci_index_member','etf_basic')"
        ):
            result = json.loads(row[0])
            if result["api_name"] == "ci_index_member":
                industries.update(r["l1_code"] for r in self.records(result))
            elif result["api_name"] == "etf_basic":
                funds.update(
                    {r["ts_code"]: r.get("list_date") for r in self.records(result)}
                )
        for year in range(start.year, end.year + 1):
            lo, hi = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            if lo > hi:
                continue
            a, b = lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")
            current = epoch if year == end.year else "history"
            priority = 5 if a >= priority_start else 50
            self.enqueue(
                "trade_cal",
                {"exchange": "SSE", "start_date": a, "end_date": b},
                priority - 1,
                current,
                reuse_recent_open=current != "history",
            )
            for code in sorted(industries):
                self.enqueue(
                    "ci_daily",
                    {"ts_code": code, "start_date": a, "end_date": b},
                    priority,
                    current,
                    reuse_recent_open=current != "history",
                )
        for status in ("L", "D", "P"):
            self.enqueue(
                "etf_basic",
                {"list_status": status},
                0,
                epoch,
                reuse_recent_open=True,
            )
        for code in sorted(industries):
            for current in ("Y", "N"):
                self.enqueue(
                    "ci_index_member",
                    {"l1_code": code, "is_new": current},
                    1,
                    epoch,
                    reuse_recent_open=True,
                )
        # Recent revisions are rechecked independently of historical checkpoints.
        for days in range(1, 8):
            d = (today - timedelta(days=days)).strftime("%Y%m%d")
            self.enqueue(
                "trade_cal",
                {"exchange": "SSE", "start_date": d, "end_date": d},
                0,
                epoch,
                reuse_recent_open=True,
            )
        # Holdings: all available fund identifiers, from listing (unknown -> full start).
        # Pending/empty periods remain explicit gaps, not evidence of complete exposure.
        for code, listed in sorted(funds.items()):
            begin = max(
                config["history_start"],
                (listed[:4] + "0101") if listed else config["history_start"],
            )
            for year in range(int(begin[:4]), end.year + 1):
                for quarter in ("0331", "0630", "0930", "1231"):
                    period = str(year) + quarter
                    if begin <= period <= end.strftime("%Y%m%d"):
                        self.enqueue(
                            "fund_portfolio",
                            {"ts_code": code, "period": period},
                            30 if period >= priority_start else 60,
                            epoch=(today - timedelta(days=today.weekday())).strftime(
                                "%Y%m%d"
                            )
                            if period
                            >= (today - timedelta(days=400)).strftime("%Y%m%d")
                            else "history",
                            reuse_recent_open=(
                                period
                                >= (today - timedelta(days=400)).strftime("%Y%m%d")
                            ),
                        )
        self.db.commit()

    def maintain_announcement_saturation(self):
        """Close legacy announcement states without discarding any capture.

        A stable historical ``anns_d`` identifier fanout owns the completeness
        obligation for its logical request. Older capped recent observations are
        still useful revision evidence, but keeping each one ``blocked`` repeats
        the same gap. Date-bisection parents created before normalization failed
        are likewise recoverable when their exact child relationship is already
        durable and exhaustive.
        """
        recovered = []
        for row in self.db.execute("""
            SELECT job.id,job.epoch,job.job,job.result,
                   split.expected_children,split.coverage_proven,split.method
            FROM partition_splits AS split
            JOIN jobs AS job ON job.id=split.parent_id
            WHERE job.state='blocked' AND job.epoch='history'
              AND split.method='date_bisection'
              AND json_extract(job.job,'$.api_name')='anns_d'
        """):
            try:
                job = json.loads(row["job"])
                result = json.loads(row["result"] or "{}")
                expected = self.date_children(job)
                children = self.db.execute(
                    "SELECT child.id,child.epoch,child.job "
                    "FROM partition_children AS edge "
                    "JOIN jobs AS child ON child.id=edge.child_id "
                    "WHERE edge.parent_id=?",
                    (row["id"],),
                ).fetchall()
                actual = []
                valid_children = True
                for child in children:
                    saved = json.loads(child["job"])
                    if (
                        child["epoch"] != row["epoch"]
                        or saved.get("api_name") != job.get("api_name")
                    ):
                        valid_children = False
                        break
                    actual.append(saved.get("params"))

                def canonical(values):
                    return {
                        json.dumps(value, sort_keys=True, separators=(",", ":"))
                        for value in values
                    }
                eligible = (
                    result.get("status") == "possibly_truncated"
                    and isinstance(result.get("normalization_error"), str)
                    and isinstance(result.get("object_sha256"), str)
                    and isinstance(result.get("observation"), str)
                    and result.get("split")
                    == {"method": "date_bisection", "children": len(expected)}
                    and row["coverage_proven"] == 1
                    and row["expected_children"] == len(expected)
                    and len(children) == len(expected)
                    and valid_children
                    and canonical(actual) == canonical(expected)
                )
            except (KeyError, TypeError, ValueError):
                eligible = False
            if eligible:
                recovered.append(row["id"])

        canonical_history = {
            row["logical_key"]
            for row in self.db.execute("""
                SELECT job.logical_key
                FROM partition_splits AS split
                JOIN jobs AS job ON job.id=split.parent_id
                WHERE job.epoch='history'
                  AND job.state IN ('split_pending','resolved')
                  AND split.method='identifier_fanout'
                  AND split.expected_children>0
                  AND json_extract(job.job,'$.api_name')='anns_d'
            """)
        }
        retired = []
        if canonical_history:
            for row in self.db.execute("""
                SELECT job.id,job.logical_key,job.result
                FROM jobs AS job INDEXED BY jobs_pending
                WHERE job.state='blocked' AND job.epoch<>'history'
                  AND json_extract(job.job,'$.api_name')='anns_d'
                  AND NOT EXISTS (
                      SELECT 1 FROM partition_children AS edge
                      WHERE edge.parent_id=job.id
                  )
            """):
                try:
                    result = json.loads(row["result"] or "{}")
                except (TypeError, ValueError):
                    continue
                if (
                    row["logical_key"] in canonical_history
                    and result.get("status") == "possibly_truncated"
                    and isinstance(result.get("object_sha256"), str)
                    and isinstance(result.get("observation"), str)
                ):
                    retired.append(row["id"])

        selected = [*recovered, *retired]
        report = {
            "status": "no_action",
            "recovered_date_split_parents": len(recovered),
            "superseded_recent_caps": len(retired),
            "preserved_result_jobs": 0,
            "preserved_attempts": 0,
            "upstream_calls": 0,
        }
        if not selected:
            return report
        placeholders = ",".join("?" for _ in selected)
        before = {
            row["id"]: (row["state"], row["tries"], row["result"])
            for row in self.db.execute(
                f"SELECT id,state,tries,result FROM jobs WHERE id IN ({placeholders})",
                selected,
            )
        }
        attempt_counts = dict(
            self.db.execute(
                f"SELECT job_id,count(*) FROM attempts WHERE job_id IN ({placeholders}) "
                "GROUP BY job_id",
                selected,
            )
        )
        try:
            self.db.execute("BEGIN IMMEDIATE")
            for task_id in recovered:
                changed = self.db.execute(
                    "UPDATE jobs SET state='split_pending' "
                    "WHERE id=? AND state='blocked'",
                    (task_id,),
                ).rowcount
                if changed != 1:
                    raise ValueError("Announcement date parent changed during recovery")
            for task_id in retired:
                changed = self.db.execute(
                    "UPDATE jobs SET state='superseded' "
                    "WHERE id=? AND state='blocked'",
                    (task_id,),
                ).rowcount
                if changed != 1:
                    raise ValueError("Announcement recent cap changed during retirement")
            reason = json.dumps(
                {
                    "recovered_date_split_parents": len(recovered),
                    "superseded_recent_caps": len(retired),
                    "attempts_preserved": sum(attempt_counts.values()),
                    "results_preserved": sum(
                        before[task_id][2] is not None for task_id in selected
                    ),
                    "upstream_calls": 0,
                },
                sort_keys=True,
            )
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) "
                "VALUES('planning:anns_d:saturation_maintenance',?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET "
                "status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                ("applied", utc_now(), reason),
            )
            after = {
                row["id"]: (row["state"], row["tries"], row["result"])
                for row in self.db.execute(
                    f"SELECT id,state,tries,result FROM jobs WHERE id IN ({placeholders})",
                    selected,
                )
            }
            for task_id in selected:
                if before[task_id][1:] != after[task_id][1:]:
                    raise ValueError("Announcement evidence changed during maintenance")
            after_attempts = dict(
                self.db.execute(
                    f"SELECT job_id,count(*) FROM attempts "
                    f"WHERE job_id IN ({placeholders}) GROUP BY job_id",
                    selected,
                )
            )
            if after_attempts != attempt_counts:
                raise ValueError("Announcement attempt ledger changed during maintenance")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        for task_id in recovered:
            self.reconcile_partitions(child_id=task_id)
        report.update(
            status="maintained",
            preserved_result_jobs=sum(
                before[task_id][2] is not None for task_id in selected
            ),
            preserved_attempts=sum(attempt_counts.values()),
        )
        return report

    def maintain_permission_states(self):
        """Move retained permission denials into the permission gap bucket."""
        rows = self.db.execute("""
            SELECT id,tries,result
            FROM jobs INDEXED BY jobs_pending
            WHERE state='blocked'
              AND json_extract(result,'$.status')='permission_denied'
        """).fetchall()
        report = {
            "status": "no_action",
            "reclassified_jobs": 0,
            "preserved_result_jobs": 0,
            "preserved_attempts": 0,
            "upstream_calls": 0,
        }
        if not rows:
            return report
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        before = {row["id"]: (row["tries"], row["result"]) for row in rows}
        attempts = dict(
            self.db.execute(
                f"SELECT job_id,count(*) FROM attempts WHERE job_id IN ({placeholders}) "
                "GROUP BY job_id",
                ids,
            )
        )
        try:
            self.db.execute("BEGIN IMMEDIATE")
            changed = self.db.execute("""
                UPDATE jobs SET state='permission_blocked'
                WHERE state='blocked'
                  AND json_extract(result,'$.status')='permission_denied'
            """).rowcount
            if changed != len(rows):
                raise ValueError("Permission state changed during maintenance")
            reason = json.dumps(
                {
                    "reclassified_jobs": changed,
                    "results_preserved": sum(row["result"] is not None for row in rows),
                    "attempts_preserved": sum(attempts.values()),
                    "upstream_calls": 0,
                },
                sort_keys=True,
            )
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) "
                "VALUES('planning:permission_state_maintenance',?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET "
                "status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                ("applied", utc_now(), reason),
            )
            after = {
                row["id"]: (row["tries"], row["result"])
                for row in self.db.execute(
                    f"SELECT id,tries,result FROM jobs WHERE id IN ({placeholders})",
                    ids,
                )
            }
            if after != before:
                raise ValueError("Permission evidence changed during maintenance")
            after_attempts = dict(
                self.db.execute(
                    f"SELECT job_id,count(*) FROM attempts WHERE job_id IN ({placeholders}) "
                    "GROUP BY job_id",
                    ids,
                )
            )
            if after_attempts != attempts:
                raise ValueError("Permission attempt ledger changed during maintenance")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        report.update(
            status="maintained",
            reclassified_jobs=changed,
            preserved_result_jobs=sum(row["result"] is not None for row in rows),
            preserved_attempts=sum(attempts.values()),
        )
        return report

    def maintain_api_unavailable_capabilities(self):
        """Index retained supplier-invalid API evidence without changing attempts."""
        report = {
            "status": "no_action",
            "examined_jobs": 0,
            "recorded_scopes": 0,
            "preserved_result_jobs": 0,
            "preserved_attempts": 0,
            "upstream_calls": 0,
        }
        rows = self.db.execute("""
            SELECT id,job,result,tries
            FROM jobs INDEXED BY jobs_pending
            WHERE state='blocked'
              AND json_extract(result,'$.status')='api_error'
              AND json_type(result,'$.object_sha256')='text'
              AND json_type(result,'$.observation')='text'
        """).fetchall()
        report["examined_jobs"] = len(rows)
        selected = {}
        for row in rows:
            job, result = json.loads(row["job"]), json.loads(row["result"])
            object_sha = result["object_sha256"]
            observation_name = result["observation"]
            try:
                payload = json.loads(
                    (self.root / "objects" / (object_sha + ".json")).read_bytes()
                )
                observation = json.loads(
                    (self.root / "observations" / observation_name).read_bytes()
                )
            except (OSError, TypeError, ValueError):
                continue
            if not (
                isinstance(payload, dict)
                and payload.get("code") == 40101
                and str(payload.get("msg", "")).strip() == "请指定正确的接口名"
                and isinstance(observation, dict)
                and isinstance(observation.get("fetched_at"), str)
            ):
                continue
            try:
                fetched = datetime.fromisoformat(observation["fetched_at"])
            except ValueError:
                continue
            if fetched.tzinfo is None:
                continue
            scope = job["api_name"] + ":" + str(job.get("params", {}).get("src", ""))
            candidate = selected.get(scope)
            if candidate is None or fetched > candidate[0]:
                selected[scope] = (fetched, row, object_sha, observation_name)
        if not selected:
            return report
        before = {
            row["id"]: (row["tries"], row["result"])
            for _, row, _, _ in selected.values()
        }
        attempts = {
            row["id"]: self.db.execute(
                "SELECT count(*) FROM attempts WHERE job_id=?", (row["id"],)
            ).fetchone()[0]
            for _, row, _, _ in selected.values()
        }
        recorded = 0
        try:
            self.db.execute("BEGIN IMMEDIATE")
            for scope, (fetched, _row, object_sha, observation_name) in selected.items():
                current = self.db.execute(
                    "SELECT status,checked_at FROM capability WHERE scope=?", (scope,)
                ).fetchone()
                if current is not None:
                    try:
                        current_at = datetime.fromisoformat(current["checked_at"])
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Invalid API capability time") from exc
                    if current_at.tzinfo is None:
                        raise ValueError("Naive API capability time")
                    if current_at >= fetched:
                        continue
                reason = json.dumps(
                    {
                        "supplier_code": 40101,
                        "evidence": "retained_raw_response",
                        "object_sha256": object_sha,
                        "observation": observation_name,
                    },
                    sort_keys=True,
                )
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) "
                    "VALUES(?,'api_unavailable',?,?) ON CONFLICT(scope) DO UPDATE SET "
                    "status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                    (scope, fetched.isoformat(), reason),
                )
                recorded += 1
            after = {
                row["id"]: (row["tries"], row["result"])
                for _, row, _, _ in selected.values()
                for row in self.db.execute(
                    "SELECT id,tries,result FROM jobs WHERE id=?", (row["id"],)
                )
            }
            if after != before:
                raise ValueError("Unavailable API evidence changed during maintenance")
            for _, row, _, _ in selected.values():
                if self.db.execute(
                    "SELECT count(*) FROM attempts WHERE job_id=?", (row["id"],)
                ).fetchone()[0] != attempts[row["id"]]:
                    raise ValueError("Unavailable API attempts changed during maintenance")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        report.update(
            status="maintained" if recorded else "no_action",
            recorded_scopes=recorded,
            preserved_result_jobs=len(before),
            preserved_attempts=sum(attempts.values()),
        )
        return report

    def schedule_permission_reprobes(self, config, *, now=None):
        """Recheck stale permission and supplier-unavailable API scopes."""
        interval = config.get("permission_reprobe_interval_seconds", 7 * 86400)
        limit = config.get("permission_reprobe_max_scopes", 4)
        if (
            isinstance(interval, bool)
            or not isinstance(interval, int)
            or not 3600 <= interval <= 365 * 86400
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 16
        ):
            raise ValueError("Invalid permission reprobe bounds")
        now = int(time.time()) if now is None else now
        if isinstance(now, bool) or not isinstance(now, int) or now < 0:
            raise ValueError("Invalid permission reprobe time")
        report = {
            "status": "no_action",
            "interval_seconds": interval,
            "max_scopes": limit,
            "eligible_scopes": 0,
            "already_pending_scopes": 0,
            "missing_job_scopes": 0,
            "scheduled": [],
            "preserved_result_jobs": 0,
            "preserved_attempts": 0,
            "upstream_calls": 0,
            "api_unavailable_maintenance": self.maintain_api_unavailable_capabilities(),
        }
        selected = []
        for row in self.db.execute(
            "SELECT scope,status,checked_at FROM capability "
            "WHERE status IN ('permission_denied','api_unavailable') "
            "ORDER BY checked_at,scope"
        ):
            try:
                checked = datetime.fromisoformat(row["checked_at"])
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid permission capability time") from exc
            if checked.tzinfo is None:
                raise ValueError("Naive permission capability time")
            scope = row["scope"]
            api_name, separator, src = scope.partition(":")
            if not separator or not api_name:
                raise ValueError("Invalid permission capability scope")
            capability_status = row["status"]
            blocked_state = (
                "permission_blocked"
                if capability_status == "permission_denied"
                else "blocked"
            )
            checkpoint = (
                "permission_reprobe:"
                if capability_status == "permission_denied"
                else "api_unavailable_reprobe:"
            ) + digest(scope.encode())
            saved = self.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?", (checkpoint,)
            ).fetchone()
            if saved and (
                isinstance(saved[0], bool)
                or not isinstance(saved[0], int)
                or saved[0] < 0
            ):
                raise ValueError("Invalid permission reprobe checkpoint")
            last = max(int(checked.timestamp()), saved[0] if saved else 0)
            if now < last or now - last < interval:
                continue
            report["eligible_scopes"] += 1
            if self.db.execute(
                "SELECT 1 FROM jobs INDEXED BY jobs_pending "
                "WHERE state='pending' AND json_extract(job,'$.api_name')=? "
                "AND COALESCE(json_extract(job,'$.params.src'),'')=? LIMIT 1",
                (api_name, src),
            ).fetchone():
                report["already_pending_scopes"] += 1
                continue
            job = self.db.execute(
                "SELECT id,tries,result FROM jobs INDEXED BY jobs_pending "
                "WHERE state=? "
                "AND json_extract(job,'$.api_name')=? "
                "AND COALESCE(json_extract(job,'$.params.src'),'')=? "
                "ORDER BY (epoch='history') DESC,priority,rowid LIMIT 1",
                (blocked_state, api_name, src),
            ).fetchone()
            if job is None:
                report["missing_job_scopes"] += 1
                continue
            selected.append((scope, capability_status, blocked_state, checkpoint, job))
            if len(selected) == limit:
                break
        if not selected:
            return report
        attempt_counts = {
            job["id"]: self.db.execute(
                "SELECT count(*) FROM attempts WHERE job_id=?", (job["id"],)
            ).fetchone()[0]
            for _, _, _, _, job in selected
        }
        try:
            self.db.execute("BEGIN IMMEDIATE")
            for _scope, _capability_status, blocked_state, checkpoint, job in selected:
                changed = self.db.execute(
                    "UPDATE jobs SET state='pending',retry_after=0 "
                    "WHERE id=? AND state=?",
                    (job["id"], blocked_state),
                ).rowcount
                if changed != 1:
                    raise ValueError("Capability reprobe job changed during scheduling")
                self.db.execute(
                    "INSERT INTO scheduler_state(name,value) VALUES(?,?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (checkpoint, now),
                )
                saved = self.db.execute(
                    "SELECT tries,result FROM jobs WHERE id=?", (job["id"],)
                ).fetchone()
                if tuple(saved) != (job["tries"], job["result"]):
                    raise ValueError("Permission reprobe changed retained evidence")
                if self.db.execute(
                    "SELECT count(*) FROM attempts WHERE job_id=?", (job["id"],)
                ).fetchone()[0] != attempt_counts[job["id"]]:
                    raise ValueError("Permission reprobe changed attempt evidence")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        report.update(
            status="scheduled",
            scheduled=[
                {
                    "scope": scope,
                    "capability_status": capability_status,
                    "job_id": job["id"],
                }
                for scope, capability_status, _, _, job in selected
            ],
            preserved_result_jobs=sum(
                job["result"] is not None for _, _, _, _, job in selected
            ),
            preserved_attempts=sum(attempt_counts.values()),
        )
        return report

    def compact_stale_recent_roots(self, epoch, *, force=False):
        """Supersede older unexecuted recent roots and their private split trees.

        An epoch labels an observation attempt; it cannot recreate a missed past
        observation. When the same top-level logical request is still open in
        several non-history epochs, only the newest root can add evidence now.
        Completed results and the stable history graph are never changed.
        """
        if not isinstance(epoch, str) or not re.fullmatch(r"\d{8}", epoch):
            raise ValueError("Invalid recent queue compaction epoch")
        checkpoint = "recent_queue_compaction_v2:" + epoch
        announcement_saturation = self.maintain_announcement_saturation()
        permission_states = self.maintain_permission_states()
        if not force and self.db.execute(
            "SELECT 1 FROM scheduler_state WHERE name=?", (checkpoint,)
        ).fetchone():
            return {
                "status": "already_compacted",
                "epoch": epoch,
                "announcement_saturation": announcement_saturation,
                "permission_states": permission_states,
            }
        temporary = (
            "temp.stale_recent_roots",
            "temp.stale_recent_duplicates",
            "temp.stale_recent_jobs",
            "temp.protected_stale_jobs",
            "temp.eligible_stale_jobs",
        )
        for table in temporary:
            self.db.execute("DROP TABLE IF EXISTS " + table)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "CREATE TEMP TABLE stale_recent_roots(id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            self.db.execute("""
                INSERT INTO stale_recent_roots
                WITH ranked AS (
                    SELECT j.id,
                           row_number() OVER (
                               PARTITION BY j.logical_key ORDER BY j.rowid DESC
                           ) AS position
                    FROM jobs AS j INDEXED BY jobs_open_logical
                    WHERE j.state IN ('pending','split_pending')
                      AND j.epoch<>'history'
                      AND NOT EXISTS (
                          SELECT 1 FROM partition_children AS edge
                          WHERE edge.child_id=j.id
                      )
                )
                SELECT id FROM ranked WHERE position>1
            """)
            stale_roots = self.db.execute(
                "SELECT count(*) FROM stale_recent_roots"
            ).fetchone()[0]
            self.db.execute(
                "CREATE TEMP TABLE stale_recent_duplicates(id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            self.db.execute("""
                INSERT INTO stale_recent_duplicates
                WITH duplicate_groups AS (
                    SELECT logical_key,max(rowid) AS newest_rowid
                    FROM jobs AS j INDEXED BY jobs_open_logical
                    WHERE j.state IN ('pending','split_pending')
                      AND j.epoch<>'history'
                    GROUP BY logical_key HAVING count(*)>1
                ), candidates AS (
                    SELECT j.id,j.logical_key,j.rowid,duplicate.newest_rowid,
                           EXISTS (
                               SELECT 1
                               FROM partition_children AS edge
                               JOIN jobs AS parent ON parent.id=edge.parent_id
                               WHERE edge.child_id=j.id
                                 AND parent.state='split_pending'
                           ) AS active_parent
                    FROM duplicate_groups AS duplicate
                    CROSS JOIN jobs AS j INDEXED BY jobs_open_logical
                    WHERE j.state IN ('pending','split_pending')
                      AND j.epoch<>'history'
                      AND j.logical_key=duplicate.logical_key
                ), annotated AS (
                    SELECT *,max(active_parent) OVER (
                        PARTITION BY logical_key
                    ) AS has_active_parent
                    FROM candidates
                )
                SELECT candidate.id
                FROM annotated AS candidate
                WHERE NOT candidate.active_parent
                  AND (candidate.has_active_parent
                       OR candidate.rowid<candidate.newest_rowid)
            """)
            stale_duplicates = self.db.execute(
                "SELECT count(*) FROM stale_recent_duplicates"
            ).fetchone()[0]
            self.db.execute(
                "CREATE TEMP TABLE stale_recent_jobs(id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            self.db.execute("""
                INSERT OR IGNORE INTO stale_recent_jobs
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM stale_recent_roots
                    UNION
                    SELECT id FROM stale_recent_duplicates
                    UNION
                    SELECT edge.child_id
                    FROM partition_children AS edge
                    JOIN descendants ON edge.parent_id=descendants.id
                )
                SELECT id FROM descendants
            """)
            # A split leaf may exceptionally be shared by another live root.
            # Protect that leaf and everything below it before changing states.
            self.db.execute(
                "CREATE TEMP TABLE protected_stale_jobs(id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            self.db.execute("""
                INSERT OR IGNORE INTO protected_stale_jobs
                WITH RECURSIVE protected(id) AS (
                    SELECT stale.id
                    FROM stale_recent_jobs AS stale
                    WHERE EXISTS (
                        SELECT 1
                        FROM partition_children AS edge
                        JOIN jobs AS parent ON parent.id=edge.parent_id
                        WHERE edge.child_id=stale.id
                          AND parent.state='split_pending'
                          AND edge.parent_id NOT IN (
                              SELECT id FROM stale_recent_jobs
                          )
                    )
                    UNION
                    SELECT edge.child_id
                    FROM partition_children AS edge
                    JOIN protected ON edge.parent_id=protected.id
                )
                SELECT id FROM protected
            """)
            protected = self.db.execute(
                "SELECT count(*) FROM protected_stale_jobs"
            ).fetchone()[0]
            self.db.execute(
                "CREATE TEMP TABLE eligible_stale_jobs(id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            # CROSS JOIN fixes the small temporary set as the outer loop; each
            # candidate then uses the jobs primary key instead of scanning every
            # pending row and rewriting several partial indexes needlessly.
            self.db.execute("""
                INSERT INTO eligible_stale_jobs
                SELECT job.id
                FROM stale_recent_jobs AS stale
                CROSS JOIN jobs AS job INDEXED BY sqlite_autoindex_jobs_1
                LEFT JOIN protected_stale_jobs AS protected
                  ON protected.id=stale.id
                WHERE job.id=stale.id
                  AND job.state IN ('pending','split_pending')
                  AND protected.id IS NULL
            """)
            eligible = self.db.execute(
                "SELECT count(*) FROM eligible_stale_jobs"
            ).fetchone()[0]
            self.db.execute("""
                UPDATE jobs SET state='superseded'
                WHERE id IN (SELECT id FROM eligible_stale_jobs)
            """)
            self.db.execute(
                "DELETE FROM scheduler_state WHERE name GLOB 'recent_queue_compaction*:*'"
            )
            self.db.execute(
                "INSERT INTO scheduler_state(name,value) VALUES(?,?)",
                (checkpoint, int(time.time())),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            for table in temporary:
                self.db.execute("DROP TABLE IF EXISTS " + table)
        return {
            "status": "compacted",
            "epoch": epoch,
            "stale_roots": stale_roots,
            "stale_duplicate_jobs": stale_duplicates,
            "superseded_open_jobs": eligible,
            "protected_shared_jobs": protected,
            "announcement_saturation": announcement_saturation,
            "permission_states": permission_states,
        }

    def compact_financial_vip_coverage(self):
        """Retire exact per-stock leaves only after a complete VIP page chain."""
        apis = (
            "income_vip",
            "balancesheet_vip",
            "cashflow_vip",
            "forecast_vip",
        )
        page_size = 1000
        rows = []
        for api in apis:
            rows.extend(
                self.db.execute(
                    "SELECT id,epoch,state,job,result FROM jobs "
                    "INDEXED BY jobs_discovery_api "
                    "WHERE json_extract(job,'$.api_name')=? AND result IS NOT NULL "
                    "AND json_extract(job,'$.params.limit')=? "
                    "AND json_type(job,'$.params.ts_code') IS NULL",
                    (api, page_size),
                ).fetchall()
            )

        chains, invalid = {}, 0
        for row in rows:
            try:
                job = json.loads(row["job"])
                params = job["params"]
                api = job["api_name"]
                period = params["period"]
                report_type = params.get("report_type")
                offset = params.get("offset", 0)
                expected = {"period", "limit"}
                if api != "forecast_vip":
                    expected.add("report_type")
                if "offset" in params:
                    expected.add("offset")
                parsed = datetime.strptime(period, "%Y%m%d").date()
                if (
                    api not in apis
                    or set(params) != expected
                    or params["limit"] != page_size
                    or (
                        api != "forecast_vip"
                        and report_type not in {str(n) for n in range(1, 13)}
                    )
                    or (api == "forecast_vip" and report_type is not None)
                    or (parsed.month, parsed.day)
                    not in ((3, 31), (6, 30), (9, 30), (12, 31))
                    or isinstance(offset, bool)
                    or not isinstance(offset, int)
                    or offset < 0
                    or offset % page_size
                ):
                    raise ValueError
                key = (api, row["epoch"], period, report_type, offset)
                if key in chains:
                    chains[key] = None
                    invalid += 1
                    continue
                chains[key] = row
            except (KeyError, TypeError, ValueError):
                invalid += 1

        complete, open_chains = {}, 0
        roots = {
            (api, epoch, period, report_type)
            for api, epoch, period, report_type, offset in chains
            if offset == 0
        }
        invalid += sum(
            offset > 0 and (api, epoch, period, report_type, 0) not in chains
            for api, epoch, period, report_type, offset in chains
        )
        for api, epoch, period, report_type in roots:
            offset, fields = 0, None
            while True:
                row = chains.get((api, epoch, period, report_type, offset))
                if row is None or row["state"] != "done" or not row["result"]:
                    open_chains += 1
                    break
                try:
                    job = json.loads(row["job"])
                    result = json.loads(row["result"])
                    count = result["row_count"]
                    if fields is None:
                        fields = job["fields"]
                    elif fields != job["fields"]:
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    invalid += 1
                    open_chains += 1
                    break
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or not 0 <= count <= page_size
                ):
                    invalid += 1
                    open_chains += 1
                    break
                if count == page_size:
                    if result.get("pagination_end"):
                        invalid += 1
                        open_chains += 1
                        break
                    offset += page_size
                    continue
                if result.get("pagination_end") is not True or any(
                    saved_api == api
                    and saved_epoch == epoch
                    and saved_period == period
                    and saved_type == report_type
                    and saved_offset > offset
                    for saved_api, saved_epoch, saved_period, saved_type, saved_offset in chains
                ):
                    invalid += 1
                    open_chains += 1
                    break
                complete.setdefault((api, period, report_type), set()).add(fields)
                break

        report = {
            "status": "no_complete_scopes",
            "pagination_pages": len(rows),
            "complete_scopes": len(complete),
            "open_chains": open_chains,
            "invalid_pages": invalid,
            "superseded_leaf_jobs": 0,
            "superseded_legacy_roots": 0,
            "terminal_jobs_action": "unchanged",
            "attempts_action": "preserved",
        }
        if not complete:
            return report

        leaves, legacy = [], []
        for api in apis:
            for row in self.db.execute(
                "SELECT id,job FROM jobs INDEXED BY jobs_ready_api_history "
                "WHERE state='pending' AND group_name='structured' "
                "AND json_extract(job,'$.api_name')=?",
                (api,),
            ):
                try:
                    job = json.loads(row["job"])
                    params = job["params"]
                    report_type = params.get("report_type")
                    expected = {"period", "ts_code"}
                    if api != "forecast_vip":
                        expected.add("report_type")
                    scopes = complete.get((api, params["period"], report_type), set())
                    if set(params) == expected and job.get("fields") in scopes:
                        leaves.append(row["id"])
                except (KeyError, TypeError, ValueError):
                    continue
            for row in self.db.execute(
                "SELECT id,job FROM jobs INDEXED BY jobs_pending "
                "WHERE state='split_pending' "
                "AND json_extract(job,'$.api_name')=?",
                (api,),
            ):
                try:
                    job = json.loads(row["job"])
                    params = job["params"]
                    report_type = params.get("report_type")
                    expected = {"period"}
                    if api != "forecast_vip":
                        expected.add("report_type")
                    scopes = complete.get((api, params["period"], report_type), set())
                    if set(params) == expected and job.get("fields") in scopes:
                        legacy.append(row["id"])
                except (KeyError, TypeError, ValueError):
                    continue

        with self.db:
            self.db.executemany(
                "UPDATE jobs SET state='superseded' WHERE id=? AND state='pending'",
                ((job_id,) for job_id in leaves),
            )
            self.db.executemany(
                "UPDATE jobs SET state='superseded' WHERE id=? AND state='split_pending'",
                ((job_id,) for job_id in legacy),
            )
            now = utc_now()
            for api in apis:
                api_scopes = sum(1 for scope in complete if scope[0] == api)
                if not api_scopes:
                    continue
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                    "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,"
                    "checked_at=excluded.checked_at,reason=excluded.reason",
                    (
                        f"planning:structured:{api}:legacy_fanout",
                        "replaced_by_verified_pagination",
                        now,
                        json.dumps(
                            {
                                "complete_scopes": api_scopes,
                                "page_size": page_size,
                                "upstream_calls": 0,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
        report.update(
            status="compacted" if leaves or legacy else "covered_no_open_jobs",
            superseded_leaf_jobs=len(leaves),
            superseded_legacy_roots=len(legacy),
        )
        return report

    def compact_fina_mainbz_vip_coverage(self):
        """Retire covered legacy VIP roots and full-year stock jobs."""
        rows = self.db.execute(
            "SELECT id,state,job,result FROM jobs INDEXED BY jobs_partition_lookup "
            "WHERE epoch='history' "
            "AND json_extract(job,'$.api_name')='fina_mainbz_vip' "
            "AND json_extract(job,'$.params.limit')=10000"
        ).fetchall()
        chains, fields, invalid = {}, set(), 0
        for row in rows:
            try:
                job = json.loads(row["job"])
                params = job["params"]
                period, kind = params["period"], params["type"]
                offset = params.get("offset", 0)
                expected = {"period", "type", "limit"} | (
                    {"offset"} if "offset" in params else set()
                )
                parsed = datetime.strptime(period, "%Y%m%d").date()
                if (
                    set(params) != expected
                    or params["limit"] != 10000
                    or kind not in ("P", "D", "I")
                    or (parsed.month, parsed.day)
                    not in ((3, 31), (6, 30), (9, 30), (12, 31))
                    or isinstance(offset, bool)
                    or not isinstance(offset, int)
                    or offset < 0
                    or offset % 10000
                ):
                    raise ValueError
                key = (period, kind, offset)
                if key in chains:
                    chains[key] = None
                    invalid += 1
                    continue
                chains[key] = row
                fields.add(job["fields"])
            except (KeyError, TypeError, ValueError):
                invalid += 1

        complete, open_chains, empty_roots = set(), 0, 0
        roots = {(period, kind) for period, kind, offset in chains if offset == 0}
        invalid += sum(
            offset > 0 and (period, kind, 0) not in chains
            for period, kind, offset in chains
        )
        for period, kind in roots:
            offset = 0
            while True:
                row = chains.get((period, kind, offset))
                if row is None or row["state"] != "done" or not row["result"]:
                    if offset == 0 and row is not None and row["state"] == "empty":
                        empty_roots += 1
                    open_chains += 1
                    break
                try:
                    result = json.loads(row["result"])
                    count = result["row_count"]
                except (KeyError, TypeError, ValueError):
                    invalid += 1
                    open_chains += 1
                    break
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or not 0 <= count <= 10000
                ):
                    invalid += 1
                    open_chains += 1
                    break
                if count == 10000:
                    offset += 10000
                    continue
                if any(
                    saved_period == period
                    and saved_kind == kind
                    and saved_offset > offset
                    for saved_period, saved_kind, saved_offset in chains
                ):
                    invalid += 1
                    open_chains += 1
                    break
                complete.add((period, kind))
                break

        covered_year_types = []
        years = {period[:4] for period, _kind in complete}
        for year in sorted(years):
            for kind in ("P", "D", "I"):
                required = {
                    (year + suffix, kind) for suffix in ("0331", "0630", "0930", "1231")
                }
                if required <= complete:
                    covered_year_types.append((year, kind))

        report = {
            "status": "no_complete_years",
            "vip_pages": len(rows),
            "vip_complete_period_types": len(complete),
            "vip_open_or_empty_chains": open_chains,
            "vip_empty_roots": empty_roots,
            "vip_invalid_pages": invalid,
            "vip_field_schemas": len(fields),
            "covered_year_types": len(covered_year_types),
            "superseded_open_jobs": 0,
            "legacy_vip_blocked_jobs": 0,
            "legacy_vip_eligible_jobs": 0,
            "superseded_legacy_vip_jobs": 0,
            "recent_jobs_action": "unchanged",
            "terminal_jobs_action": "unchanged",
        }
        if invalid or len(fields) != 1:
            report["status"] = "blocked_invariant"
            return report
        legacy_rows = self.db.execute(
            "SELECT id,job,result FROM jobs INDEXED BY jobs_pending "
            "WHERE state='blocked' AND epoch='history' "
            "AND json_extract(job,'$.api_name')='fina_mainbz_vip' "
            "AND json_type(job,'$.params.limit') IS NULL"
        ).fetchall()
        legacy_candidates = []
        field_schema = next(iter(fields))
        for row in legacy_rows:
            try:
                job = json.loads(row["job"])
                params = job["params"]
                result = json.loads(row["result"] or "{}")
                parquet = result.get("parquet") or {}
                eligible = (
                    set(params) == {"period", "type"}
                    and (params["period"], params["type"]) in complete
                    and job.get("row_cap") == 100
                    and job.get("fields") == field_schema
                    and result.get("status") == "possibly_truncated"
                    and isinstance(result.get("row_count"), int)
                    and not isinstance(result.get("row_count"), bool)
                    and result["row_count"] > 100
                    and isinstance(result.get("object_sha256"), str)
                    and isinstance(result.get("observation"), str)
                    and isinstance(parquet.get("path"), str)
                    and isinstance(parquet.get("sha256"), str)
                )
            except (KeyError, TypeError, ValueError):
                eligible = False
            if eligible:
                legacy_candidates.append(row["id"])
        report.update(
            legacy_vip_blocked_jobs=len(legacy_rows),
            legacy_vip_eligible_jobs=len(legacy_candidates),
        )
        if not covered_year_types and not legacy_candidates:
            return report

        attempts = self.db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        result_jobs = self.db.execute(
            "SELECT count(*) FROM jobs WHERE result IS NOT NULL"
        ).fetchone()[0]
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "CREATE TEMP TABLE fina_mainbz_vip_year_coverage("
                "year TEXT NOT NULL,kind TEXT NOT NULL,PRIMARY KEY(year,kind)) "
                "WITHOUT ROWID"
            )
            self.db.executemany(
                "INSERT INTO fina_mainbz_vip_year_coverage VALUES(?,?)",
                covered_year_types,
            )
            self.db.execute(
                "CREATE TEMP TABLE fina_mainbz_vip_retire(id TEXT PRIMARY KEY) "
                "WITHOUT ROWID"
            )
            self.db.execute(
                "CREATE TEMP TABLE fina_mainbz_vip_legacy_retire("
                "id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            self.db.executemany(
                "INSERT INTO fina_mainbz_vip_legacy_retire VALUES(?)",
                ((task_id,) for task_id in legacy_candidates),
            )
            self.db.execute(
                "INSERT INTO fina_mainbz_vip_retire "
                "SELECT job.id FROM jobs AS job INDEXED BY jobs_ready_api_history "
                "JOIN fina_mainbz_vip_year_coverage AS coverage "
                "ON coverage.year=substr(json_extract(job.job,'$.params.end_date'),1,4) "
                "AND coverage.kind=json_extract(job.job,'$.params.type') "
                "WHERE job.state='pending' AND job.group_name='research_extra' "
                "AND job.epoch='history' "
                "AND json_extract(job.job,'$.api_name')='fina_mainbz' "
                "AND json_extract(job.job,'$.row_cap')=100 "
                "AND json_extract(job.job,'$.fields')=? "
                "AND (SELECT count(*) FROM json_each(job.job,'$.params'))=4 "
                "AND json_type(job.job,'$.params.ts_code')='text' "
                "AND json_extract(job.job,'$.params.start_date')=coverage.year||'0101' "
                "AND json_extract(job.job,'$.params.end_date')=coverage.year||'1231'",
                (field_schema,),
            )
            protected = self.db.execute(
                "DELETE FROM fina_mainbz_vip_retire WHERE id IN ("
                "SELECT edge.child_id FROM partition_children AS edge "
                "JOIN jobs AS parent ON parent.id=edge.parent_id "
                "WHERE parent.state='split_pending')"
            ).rowcount
            legacy_protected = self.db.execute(
                "DELETE FROM fina_mainbz_vip_legacy_retire WHERE id IN ("
                "SELECT edge.child_id FROM partition_children AS edge "
                "JOIN jobs AS parent ON parent.id=edge.parent_id "
                "WHERE parent.state='split_pending')"
            ).rowcount
            retired_attempts = self.db.execute(
                "SELECT count(*) FROM attempts WHERE job_id IN "
                "(SELECT id FROM fina_mainbz_vip_retire)"
            ).fetchone()[0]
            legacy_retired_attempts = self.db.execute(
                "SELECT count(*) FROM attempts WHERE job_id IN "
                "(SELECT id FROM fina_mainbz_vip_legacy_retire)"
            ).fetchone()[0]
            superseded = self.db.execute(
                "UPDATE jobs SET state='superseded' WHERE state='pending' "
                "AND id IN (SELECT id FROM fina_mainbz_vip_retire)"
            ).rowcount
            legacy_superseded = self.db.execute(
                "UPDATE jobs SET state='superseded' WHERE state='blocked' "
                "AND id IN (SELECT id FROM fina_mainbz_vip_legacy_retire)"
            ).rowcount
            if legacy_superseded:
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) "
                    "VALUES('planning:fina_mainbz_vip:legacy_contract',?,?,?) "
                    "ON CONFLICT(scope) DO UPDATE SET "
                    "status=excluded.status,checked_at=excluded.checked_at,"
                    "reason=excluded.reason",
                    (
                        "replaced_by_verified_pagination",
                        utc_now(),
                        json.dumps(
                            {
                                "complete_period_types": len(complete),
                                "superseded_jobs": legacy_superseded,
                                "attempts_preserved": legacy_retired_attempts,
                                "task_ids_sha256": digest(
                                    json_bytes(sorted(legacy_candidates))
                                ),
                                "upstream_calls": 0,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
            if (
                self.db.execute("SELECT count(*) FROM attempts").fetchone()[0]
                != attempts
            ):
                raise ValueError(
                    "Attempt ledger changed during VIP coverage compaction"
                )
            if (
                self.db.execute(
                    "SELECT count(*) FROM jobs WHERE result IS NOT NULL"
                ).fetchone()[0]
                != result_jobs
            ):
                raise ValueError("Result jobs changed during VIP coverage compaction")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self.db.execute("DROP TABLE IF EXISTS fina_mainbz_vip_retire")
            self.db.execute("DROP TABLE IF EXISTS fina_mainbz_vip_legacy_retire")
            self.db.execute("DROP TABLE IF EXISTS fina_mainbz_vip_year_coverage")
        report.update(
            status=(
                "compacted"
                if superseded or legacy_superseded
                else "no_covered_open_jobs"
            ),
            superseded_open_jobs=superseded,
            protected_shared_jobs=protected,
            superseded_legacy_vip_jobs=legacy_superseded,
            protected_legacy_vip_jobs=legacy_protected,
            legacy_vip_attempts_preserved=legacy_retired_attempts,
            retired_job_attempts_preserved=(
                retired_attempts + legacy_retired_attempts
            ),
        )
        return report

    def _load_identifier_cache(self):
        row = self.db.execute(
            "SELECT * FROM identifier_discovery_cache WHERE version=?",
            (IDENTIFIER_CACHE_VERSION,),
        ).fetchone()
        if row is None:
            return None
        retained = self.db.execute(
            "SELECT count(*) FROM attempts WHERE rowid<=?", (row["attempt_rowid"],)
        ).fetchone()[0]
        if retained != row["attempt_count"]:
            return None
        objects = json.loads(row["objects"])
        valid, workers, seconds = _verify_identifier_object_stats(
            self.root, objects
        )
        self.identifier_cache_timing = {
            "verified_objects": len(objects),
            "stat_workers": workers,
            "stat_seconds": seconds,
        }
        if not valid:
            return None
        return json.loads(row["result"]), row["attempt_rowid"], objects

    def _save_identifier_cache(self, result, attempt_rowid, attempt_count, objects):
        self.db.execute(
            "DELETE FROM identifier_discovery_cache WHERE version<>?",
            (IDENTIFIER_CACHE_VERSION,),
        )
        self.db.execute(
            "INSERT INTO identifier_discovery_cache VALUES(?,?,?,?,?) "
            "ON CONFLICT(version) DO UPDATE SET "
            "attempt_rowid=excluded.attempt_rowid,attempt_count=excluded.attempt_count,"
            "result=excluded.result,objects=excluded.objects",
            (
                IDENTIFIER_CACHE_VERSION,
                attempt_rowid,
                attempt_count,
                json_bytes(result).decode(),
                json_bytes(objects).decode(),
            ),
        )

    def identifiers(self, *, _source_apis=None, _use_cache=False):
        bond_source_apis = ("cb_daily", "cb_issue", "cb_call", "cb_rate", "cb_price_chg", "cb_share")
        factor_records = {}
        reward_period_records = {}
        stock_lifecycle_records = {}
        index_lifecycle_records = {}
        fund_lifecycle_records = {}
        observed_index_starts = {}
        observed_fund_starts = {}
        families = {
            **dict.fromkeys(REALTIME_RUNTIME_CONTRACTS, "realtime_source_only"),
            **dict.fromkeys(SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS, "stocks"),
            "eco_cal": "eco_cal_countries",
            "factor_list": "factor_library_factors",
            "factor_value": "factor_library_stocks",
            **dict.fromkeys(bond_source_apis, "bond_extra_convertibles"),
            **{api: spec.get("saturation_fallback", "bond_extra_convertibles") for api, spec in BOND_EXTRA_RUNTIME_CONTRACTS.items()},
            "tdx_index": "tdx_indices",
            "tdx_member": "tdx_indices",
            "tdx_daily": "tdx_indices",
            "kpl_concept_cons": "kpl_concepts",
            "kpl_list": "market_sentiment_stocks",
            **{
                api: spec["saturation_fallback"]
                for api, spec in CROSS_ASSET_RUNTIME_CONTRACTS.items()
            },
            "ci_daily": "cross_asset_indexes",
            "ci_index_member": "cross_asset_indexes",
            **{
                api: spec["dependencies"][0]
                for api, spec in FOREIGN_FINANCIAL_RUNTIME_CONTRACTS.items()
            },
            **dict.fromkeys(STOCK_CONTEXT_RUNTIME_CONTRACTS, "stock_context_stocks"),
            **dict.fromkeys(TECHNICAL_EXTRA_RUNTIME_CONTRACTS, "technical_stocks"),
            "daily": "technical_stocks",
            "daily_basic": "technical_stocks",
            "adj_factor": "technical_stocks",
            "stock_st": "risk_stocks",
            "st": "risk_stocks",
            "stk_shock": "risk_stocks",
            "stk_high_shock": "risk_stocks",
            "stk_alert": "risk_securities",
            "ths_index": "ths_indices",
            "ths_daily": "ths_indices",
            "ths_member": "ths_indices",
            "dc_index": "dc_indices",
            "dc_member": "dc_indices",
            "dc_daily": "dc_indices",
            **{api: "connect_" + api for api in CONNECT_CONTRACTS},
            "limit_list_ths": "limit_securities",
            "limit_list_d": "limit_securities",
            "limit_step": "limit_securities",
            "limit_cpt_list": "limit_concepts",
            "bak_basic": "historical_listing_securities",
            "new_share": "historical_listing_securities",
            "daily_info": "market_stat_categories",
            "bse_mapping": "bse_old_codes",
            "top_list": "trading_event_securities",
            "top_inst": "trading_event_securities",
            "hm_detail": "trading_event_securities",
            "hm_list": "hot_money_names",
            "stock_basic": "stocks",
            "margin_secs": "credit_securities",
            "hk_basic": "hk_stocks",
            "us_basic": "us_stocks",
            "index_basic": "indexes",
            "mkt_idx_bmk": "indexes",
            "etf_basic": "funds",
            "fund_basic": "funds",
            "cb_basic": "bonds",
            "index_classify": "sw_l3",
            "fut_basic": "futures",
            "fut_daily_adj": "futures_continuous",
            "fut_index_daily": "futures_indexes",
            "opt_basic": "options",
            "opt_daily": "options",
            "sge_basic": "spot_metals",
            "sge_daily": "spot_metals",
            "fx_obasic": "fx_instruments",
            "fx_daily": "fx_instruments",
            "index_weight": "minute_source_only",
            "fund_nav": "minute_source_only",
        }
        # Additional sources enter only the minute projection, never an old universe.
        families = {**dict.fromkeys(MINUTE_SOURCE_FAMILIES, "minute_source_only"), **families}
        self.identifier_cache_timing = None
        cached = self._load_identifier_cache() if _use_cache and _source_apis is None else None
        if cached:
            cached_result, cached_attempt_rowid, object_stats = cached
            factor_records = {
                json_bytes(item): item
                for item in cached_result.pop("factor_library_factors", [])
            }
            reward_period_records = {
                json_bytes(item): item
                for item in cached_result.pop("stock_context_reward_periods", [])
            }
            stock_lifecycle_records = {
                item["ts_code"]: item
                for item in cached_result.pop("stock_lifecycles", [])
            }
            index_lifecycle_records = {
                item["ts_code"]: item.get("start_date")
                for item in cached_result.pop("index_lifecycles", [])
            }
            fund_lifecycle_records = {
                item["ts_code"]: item.get("start_date")
                for item in cached_result.pop("fund_lifecycles", [])
            }
            result = {key: set(values) for key, values in cached_result.items()}
        else:
            cached_attempt_rowid, object_stats = 0, {}
            result = {name: set() for name in families.values()}
            result.update({name: set() for name in MINUTE_SOURCE_FAMILIES.values()})
            result.update({name: set() for name in REALTIME_SOURCE_FAMILIES.values()})
            result["announcement_securities"] = set()
            result["minute_futures_unmapped"] = set()
            result.update(
                sw_indexes=set(),
                futures_continuous=set(),
                futures_products=set(),
                etfs=set(),
                bse_new_codes=set(),
            )
        # All columns used below, including cross-market/member discovery. Raw
        # JSON is still fully decoded; only temporary row dictionaries narrow.
        discovery_fields = frozenset(
            (
                "ts_code", "index_code", "level", "fut_code", "o_code", "n_code",
                "name", "hm_name", "l1_code", "l2_code", "l3_code", "con_code",
                "factor_name", "asset_type", "mapping_ts_code", "code", "end_date",
                "country", "list_date", "base_date", "found_date", "issue_date",
                "setup_date", "purc_startdate", "redm_startdate", "trade_date",
                "nav_date",
            )
        )
        if _source_apis is None:
            source_apis = tuple(families)
        elif tuple(_source_apis) in IDENTIFIER_SPLIT_SOURCE_APIS.values():
            source_apis = tuple(_source_apis)
        else:
            raise ValueError("Unsupported identifier source projection")
        placeholders = ",".join("?" for _ in source_apis)
        attempt_rowid, attempt_count = self.db.execute(
            "SELECT COALESCE(max(rowid),0),count(*) FROM attempts"
        ).fetchone()
        seen = set()
        discovery = {"results": 0, "duplicate_bodies": 0, "bypassed": 0, "body_reads": 0}
        if cached:
            discovery.update(
                cache_hit=True,
                cached_attempt_rowid=cached_attempt_rowid,
                cached_objects=len(object_stats),
            )
            discovery.update(self.identifier_cache_timing or {})
        self.identifier_timing = discovery
        if cached:
            # Every new response is appended to attempts in the same transaction
            # that updates jobs.result. The initial scan includes legacy job
            # variants; the durable attempt rowid is sufficient thereafter.
            rows = self.db.execute(
                "SELECT result FROM attempts NOT INDEXED WHERE rowid>? AND rowid<=? "
                "AND json_extract(result,'$.api_name') IN (" + placeholders + ") "
                "ORDER BY rowid",
                (cached_attempt_rowid, attempt_rowid, *source_apis),
            )
        else:
            rows = self.db.execute(
                "SELECT result FROM jobs WHERE result IS NOT NULL AND json_extract(job,'$.api_name') IN ("
                + placeholders
                + ") UNION SELECT result FROM attempts WHERE json_extract(result,'$.api_name') IN ("
                + placeholders
                + ")",
                source_apis + source_apis,
            )
        for row in rows:
            saved = json.loads(row[0])
            discovery["results"] += 1
            api, sha = saved.get("api_name"), saved.get("object_sha256")
            # Request-aware discovery must opt in separately. Current hot-list
            # market labels live in immutable requests, not necessarily the body.
            bypass = api in ("ths_hot", "dc_hot") or bool(
                contract_for(api).get("request_identity_fields")
            )
            eligible = (
                sha
                and saved.get("status")
                not in (
                    "transport_error",
                    "rate_limited",
                    "permission_denied",
                    "api_error",
                    "invalid_response",
                )
                and saved.get("response_format") != "non_json"
            )
            if eligible:
                stat = (self.root / "objects" / (sha + ".json")).stat()
                object_stats[sha] = [
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                ]
            if eligible and not bypass:
                key = (
                    api,
                    sha,
                    saved.get("status"),
                    saved.get("response_format"),
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
                if key in seen:
                    discovery["duplicate_bodies"] += 1
                    continue
                seen.add(key)
            discovery["bypassed"] += int(bypass)
            discovery["body_reads"] += int(bool(eligible))
            realtime_params = {}
            if api == "stk_auction":
                observed = json.loads((self.root / "observations" / saved["observation"]).read_bytes())
                realtime_params = observed.get("request", {}).get("params", {})
            for record in self.records(saved, fields=discovery_fields):
                if saved["api_name"] == "stock_basic":
                    code = record.get("ts_code")
                    if isinstance(code, str) and re.fullmatch(
                        r"T?[0-9]{6}\.(SH|SZ|BJ)", code
                    ):
                        list_date = record.get("list_date")
                        list_date = list_date if valid_date(list_date) else None
                        previous = stock_lifecycle_records.get(code)
                        previous_date = previous.get("list_date") if previous else None
                        stock_lifecycle_records[code] = {
                            "ts_code": code,
                            "list_date": (
                                min(previous_date, list_date)
                                if previous_date and list_date
                                else previous_date or list_date
                            ),
                        }
                if saved["api_name"] == "index_basic":
                    code = record.get("ts_code")
                    if isinstance(code, str) and re.fullmatch(
                        r"[A-Za-z0-9]+\.[A-Z]+", code
                    ):
                        dates = [
                            record.get(field)
                            for field in ("base_date", "list_date")
                            if valid_date(record.get(field))
                        ]
                        if dates:
                            start_date = min(dates)
                            current = index_lifecycle_records.get(code)
                            index_lifecycle_records[code] = (
                                min(current, start_date) if current else start_date
                            )
                        else:
                            index_lifecycle_records.setdefault(code, None)
                if saved["api_name"] in ("fund_basic", "etf_basic"):
                    code = record.get("ts_code")
                    if isinstance(code, str) and re.fullmatch(
                        r"[A-Za-z0-9]+\.[A-Z]+", code
                    ):
                        dates = [
                            record.get(field)
                            for field in (
                                "issue_date", "found_date", "setup_date", "list_date",
                                "purc_startdate", "redm_startdate",
                            )
                            if valid_date(record.get(field))
                        ]
                        if dates:
                            start_date = min(dates)
                            current = fund_lifecycle_records.get(code)
                            fund_lifecycle_records[code] = (
                                min(current, start_date) if current else start_date
                            )
                        else:
                            fund_lifecycle_records.setdefault(code, None)
                if saved["api_name"] in ("index_daily", "index_weight"):
                    code = record.get("ts_code") or record.get("index_code")
                    trade_date = record.get("trade_date")
                    if (
                        isinstance(code, str)
                        and re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", code)
                        and valid_date(trade_date)
                    ):
                        observed_index_starts[code] = min(
                            trade_date, observed_index_starts.get(code, trade_date)
                        )
                if saved["api_name"] == "fund_nav":
                    code, nav_date = record.get("ts_code"), record.get("nav_date")
                    if (
                        isinstance(code, str)
                        and re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", code)
                        and valid_date(nav_date)
                    ):
                        observed_fund_starts[code] = min(
                            nav_date, observed_fund_starts.get(code, nav_date)
                        )
                if api == "stk_rewards":
                    # Body-only actual pairs, including capped historical attempts.
                    # Invalid/missing dates remain evidence for a prerequisite gap.
                    identity = {field: record.get(field) for field in ("ts_code", "end_date")}
                    reward_period_records[json_bytes(identity)] = identity
                if api in REALTIME_RUNTIME_CONTRACTS:
                    code = record.get(REALTIME_RUNTIME_CONTRACTS[api]["source_code_field"])
                    family = REALTIME_SOURCE_FAMILIES[api]
                    if api == "stk_auction":
                        family = {"STK": "realtime_stocks", "ETF": "realtime_etfs"}.get(realtime_params.get("ts_type"), family)
                    if isinstance(code, str) and code:
                        result[family].add(code)
                    continue

                minute_family = MINUTE_SOURCE_FAMILIES.get(api)
                if minute_family:
                    field = "mapping_ts_code" if api == "fut_mapping" else "index_code" if api == "index_classify" else "ts_code"
                    code = record.get(field)
                    if isinstance(code, str) and code:
                        if minute_family == "minute_futures" and code.split(".")[0].endswith(("L", "L1", "L2", "L3", "8888", "9999")):
                            result["minute_futures_unmapped"].add(code)
                        else:
                            result[minute_family].add(code)
                if families[api] == "minute_source_only":
                    continue
                if saved["api_name"] == "factor_list":
                    # Actual list identity only, not descriptions/demo IDs or
                    # factor_value outputs that cannot establish asset_type.
                    identity = {field: record.get(field) for field in ("factor_name", "asset_type")}
                    factor_records[json_bytes(identity)] = identity
                    continue
                if saved["api_name"] == "factor_value":
                    code = record.get("ts_code")
                    if isinstance(code, str) and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", code):
                        result["factor_library_stocks"].add(code)
                    continue
                if saved["api_name"] == "eco_cal":
                    country = record.get("country")
                    if (
                        isinstance(country, str)
                        and 0 < len(country) <= 128
                        and country == country.strip()
                        and not any(ord(char) < 32 or ord(char) == 127 for char in country)
                    ):
                        result["eco_cal_countries"].add(country)
                    continue
                if saved["api_name"] == "ci_index_member":
                    for field in ("l1_code", "l2_code", "l3_code"):
                        value = record.get(field)
                        if isinstance(value, str) and value:
                            result["cross_asset_indexes"].add(value)
                            result["minute_indexes"].add(value)
                    continue  # Constituent ts_code is not an index identifier.
                if saved["api_name"] == "index_classify" and record.get("index_code"):
                    result["sw_indexes"].add(record["index_code"])
                if saved["api_name"] == "fut_basic":
                    if record.get("fut_code"):
                        result["futures_products"].add(record["fut_code"])
                    if (
                        str(record.get("ts_code", ""))
                        .split(".")[0]
                        .endswith(("L", "L1", "L2", "L3"))
                    ):
                        result["futures_continuous"].add(record["ts_code"])
                if saved["api_name"] == "index_classify" and record.get("level") != "L3":
                    continue
                if saved["api_name"] == "bse_mapping":
                    for field, family in (
                        ("o_code", "bse_old_codes"),
                        ("n_code", "bse_new_codes"),
                    ):
                        code = record.get(field)
                        if isinstance(code, str) and code:
                            result[family].add(code)
                    continue
                if saved["api_name"] == "hm_list":
                    if isinstance(record.get("name"), str) and record["name"]:
                        result["hot_money_names"].add(record["name"])
                    continue
                if (
                    saved["api_name"] == "hm_detail"
                    and isinstance(record.get("hm_name"), str)
                    and record["hm_name"]
                ):
                    result["hot_money_names"].add(record["hm_name"])
                if saved["api_name"] in ("tdx_member", "kpl_concept_cons"):
                    member = record.get("con_code")
                    if isinstance(member, str) and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", member):
                        result["market_sentiment_stocks"].add(member)
                if saved["api_name"] in BOND_EXTRA_RUNTIME_CONTRACTS or saved["api_name"] in bond_source_apis:
                    code = record.get("ts_code")
                    # Numeric/malformed schemas remain raw/quality evidence, not
                    # invented request codes or mixed-type global sort failures.
                    if isinstance(code, str) and code:
                        result[families[saved["api_name"]]].add(code)
                    continue
                if saved["api_name"] in SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS:
                    code = record.get("ts_code")
                    if isinstance(code, str) and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", code):
                        result["stocks"].add(code)
                    continue  # Malformed source remains raw/quality, not guessed discovery.
                code = record.get("ts_code") or record.get("index_code")
                if code:
                    result[families[saved["api_name"]]].add(code)
                    if saved["api_name"] == "etf_basic":
                        result["etfs"].add(code)
        # Retain historical/T stock identities and securities discovered in any
        # saved event response, including saturated attempts and retired codes.
        result["trading_event_securities"].update(result["stocks"])
        result["historical_listing_securities"].update(
            result["stocks"] | result["bse_old_codes"] | result["bse_new_codes"]
        )
        result["market_stat_categories"].update(DAILY_INFO_STARTS)
        result["limit_securities"].update(
            result["stocks"]
            | result["historical_listing_securities"]
            | result["trading_event_securities"]
        )
        result["risk_stocks"].update(
            result["stocks"]
            | result["historical_listing_securities"]
            | result["trading_event_securities"]
        )
        # Keep technical history wider than current listings, in its own namespace.
        # Source attempts include retired/T codes and saturated observations.
        result["technical_stocks"].update(
            result["risk_stocks"] | result["limit_securities"]
        )
        result["factor_library_stocks"].update(result["technical_stocks"])
        result["stock_context_stocks"].update(result["technical_stocks"])
        result["market_sentiment_stocks"].update(result["stock_context_stocks"])
        result["risk_securities"].update(
            result["risk_stocks"] | result["funds"] | result["etfs"]
        )
        result.setdefault("announcement_securities", set()).update(result["stocks"])
        # Isolated discovery unions: never widen old-family stocks/funds/bonds.
        result["cross_asset_indexes"].update(result["indexes"] | result["sw_indexes"])
        result["cross_asset_funds"].update(result["funds"] | result["etfs"])
        result["cross_asset_bonds"].update(result["bonds"])
        result["bond_extra_convertibles"].update(result["cross_asset_bonds"])
        result["cross_asset_etfs"].update(result["etfs"])
        result = {key: sorted(values) for key, values in result.items()}
        result["factor_library_factors"] = [factor_records[key] for key in sorted(factor_records)]
        result["stock_context_reward_periods"] = [reward_period_records[key] for key in sorted(reward_period_records)]
        result["stock_lifecycles"] = [
            stock_lifecycle_records[key] for key in sorted(stock_lifecycle_records)
        ]
        for code, observed in observed_index_starts.items():
            if index_lifecycle_records.get(code):
                index_lifecycle_records[code] = min(
                    index_lifecycle_records[code], observed
                )
        for code, observed in observed_fund_starts.items():
            if fund_lifecycle_records.get(code):
                fund_lifecycle_records[code] = min(
                    fund_lifecycle_records[code], observed
                )
        result["index_lifecycles"] = [
            {"ts_code": code, "start_date": index_lifecycle_records[code]}
            for code in sorted(index_lifecycle_records)
        ]
        result["fund_lifecycles"] = [
            {"ts_code": code, "start_date": fund_lifecycle_records[code]}
            for code in sorted(fund_lifecycle_records)
        ]
        for api, spec in CROSS_ASSET_RUNTIME_CONTRACTS.items():
            family = spec["saturation_fallback"]
            logical = EXTENDED_CONTRACTS[api].get("discovery_dependencies", [family])[0]
            try:
                result[family] = cross_asset_identifiers(
                    {logical: result[family]}, [api]
                )[logical]
            except ValueError:
                # Preserve malformed source evidence for family-local validation.
                pass
        try:
            result.update(credit_identifiers(result))
        except ValueError:
            # Keep raw discovery for family-local validation below; malformed
            # credit inputs must not block unrelated families in identifiers().
            pass
        if _use_cache and _source_apis is None:
            self._save_identifier_cache(
                result, attempt_rowid, attempt_count, object_stats
            )
        return result

    def portfolio_read_identifier(self, epoch):
        """Return the durable successful unfiltered list observation for one epoch."""
        if epoch is None:
            return None
        row = self.db.execute(
            "SELECT job,epoch,state,result FROM jobs INDEXED BY jobs_partition_lookup "
            "WHERE epoch=? AND json_extract(job,'$.api_name')='p_list' "
            "AND group_name='portfolio_read' AND state IN ('done','empty') "
            "ORDER BY rowid DESC LIMIT 1",
            (epoch,),
        ).fetchone()
        if row is None:
            return None
        job, saved = json.loads(row["job"]), json.loads(row["result"])
        return {
            "api_name": "p_list",
            "params": job["params"],
            "epoch": row["epoch"],
            "status": row["state"],
            # Planning needs the exact request name and source ID only. Private
            # descriptions and holdings do not enter the planning checkpoint.
            "rows": self.records(saved, fields=frozenset(("id", "name"))),
        }

    def record_global_planning_gaps(self, config, identifiers):
        # Nonempty discovery and an explicit 1990 scope are not completeness proof.
        # Keep planning evidence in the existing portable capability inventory.
        global_prerequisites(identifiers, config=config)  # validate before mutation
        selected = config.get("global_apis", tuple(GLOBAL_CONTRACTS))
        setting = config.get("global_history_start")
        for api in selected:
            spec = GLOBAL_CONTRACTS[api]
            evidence = []
            if spec.get("history_gap"):
                explicit = setting.get(api) if isinstance(setting, dict) else setting
                evidence.append(
                    (
                        "history",
                        "unknown_history_bound",
                        {
                            "reason": spec["history_gap"],
                            "requested_start": explicit or config.get("history_start"),
                            "scope_is_full_history_proof": False,
                        },
                    )
                )
            family = spec.get("saturation_fallback")
            if family:
                count = len(identifiers.get(family, []))
                evidence.append(
                    (
                        "discovery",
                        "discovery_unverified" if count else "awaiting_discovery",
                        {
                            "family": family,
                            "observed_codes": count,
                            "universe_complete": False,
                        },
                    )
                )
            for kind, status, reason in evidence:
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                    "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason "
                    "WHERE capability.status<>excluded.status OR capability.reason<>excluded.reason",
                    (
                        f"planning:global:{api}:{kind}",
                        status,
                        utc_now(),
                        json.dumps(reason, sort_keys=True),
                    ),
                )

    def record_other_planning_gaps(self, config, identifiers):
        gaps = other_prerequisites(identifiers, config=config)
        selected = config.get("other_apis", tuple(OTHER_CONTRACTS))
        evidence = []
        for api in selected:
            spec = OTHER_CONTRACTS[api]
            family = spec.get("saturation_fallback") or {
                "opt_basic": "options",
                "sge_basic": "spot_metals",
                "fx_obasic": "fx_instruments",
            }.get(api)
            if family:
                count = len(identifiers.get(family, []))
                evidence.append(
                    (
                        api,
                        "discovery",
                        "discovery_unverified" if count else "awaiting_discovery",
                        {
                            "family": family,
                            "observed_codes": count,
                            "universe_complete": False,
                        },
                    )
                )
            if not spec["row_cap_verified"]:
                evidence.append(
                    (
                        api,
                        "cap",
                        "row_cap_unverified",
                        {"reason": spec["cap_note"], "row_cap": spec["row_cap"]},
                    )
                )
        setting = config.get("other_history_start")
        for gap in gaps:
            if gap["dependencies"]:
                continue  # Discovery evidence above is retained even after first rows.
            api = gap["api_name"]
            explicit = setting.get(api) if isinstance(setting, dict) else setting
            evidence.append(
                (
                    api,
                    "history",
                    "history_scope_unverified",
                    {
                        "reason": gap["reason"],
                        "requested_start": explicit or config.get("history_start"),
                        "scope_is_full_history_proof": False,
                    },
                )
            )
        for api, kind, status, reason in evidence:
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason "
                "WHERE capability.status<>excluded.status OR capability.reason<>excluded.reason",
                (
                    f"planning:other:{api}:{kind}",
                    status,
                    utc_now(),
                    json.dumps(reason, sort_keys=True),
                ),
            )

    def record_supplement_planning_gaps(self, config, identifiers):
        for gap in supplement_prerequisites(identifiers, config=config):
            kind = "discovery" if gap["dependencies"] else "history"
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason "
                "WHERE capability.status<>excluded.status OR capability.reason<>excluded.reason",
                (
                    "planning:supplement:" + gap["api_name"] + ":" + kind,
                    "discovery_unverified"
                    if kind == "discovery"
                    else "history_scope_unverified",
                    utc_now(),
                    json.dumps(gap, sort_keys=True),
                ),
            )

    def record_equity_event_planning_gaps(self, config, identifiers):
        for gap in equity_event_prerequisites(identifiers, config=config):
            if gap["dependencies"]:
                kind, status = "discovery", "discovery_unverified"
            elif gap["reason"] == "cap_note":
                kind, status = "cap", "row_cap_unverified"
            elif gap["reason"] == "refresh_gap":
                kind, status = "revision", "revision_coverage_unverified"
            else:
                kind, status = "history", "history_scope_unverified"
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason "
                "WHERE capability.status<>excluded.status OR capability.reason<>excluded.reason",
                (
                    f"planning:equity_event:{gap['api_name']}:{kind}",
                    status,
                    utc_now(),
                    json.dumps(gap, sort_keys=True),
                ),
            )

    def record_extra_planning_gaps(self, family, config, identifiers):
        prerequisites = {
            "realtime_auction": lambda ids, config: realtime_runtime_prerequisites(ids, config, family="realtime_auction"),
            "realtime_extra": realtime_runtime_prerequisites,
            "realtime_replay": lambda ids, config: realtime_runtime_prerequisites(ids, config, family="realtime_replay"),
            "account_history": account_history_prerequisites,
            "securities_lending_history": securities_lending_history_prerequisites,
            "history_minutes": history_minutes_runtime_prerequisites,
            "calendar_extra": calendar_extra_prerequisites,
            "factor_library": factor_library_prerequisites,
            "cross_asset_extra": cross_asset_runtime_prerequisites,
            "bond_extra": bond_extra_runtime_prerequisites,
            "market_sentiment": market_sentiment_prerequisites,
            "market_members": market_member_prerequisites,
            "foreign_financial": foreign_financial_runtime_prerequisites,
            "stock_context": stock_context_runtime_prerequisites,
            "technical_extra": technical_extra_runtime_prerequisites,
            "risk_event": risk_event_runtime_prerequisites,
            "dc_extra": dc_extra_prerequisites,
            "concept_extra": concept_extra_prerequisites,
            "limit_extra": limit_extra_prerequisites,
            "listing_extra": listing_extra_prerequisites,
            "trading_event": trading_event_prerequisites,
            "connect": connect_prerequisites,
            "portfolio_read": portfolio_read_prerequisites,
            "etf_basket": etf_basket_prerequisites,
            "credit_extra": credit_extra_prerequisites,
            "futures_extra": futures_extra_prerequisites,
            "catalog_delta": catalog_delta_prerequisites,
            "research_extra": research_extra_prerequisites,
            "fina_mainbz_vip": fina_mainbz_vip_prerequisites,
        }[family]
        # Validate the complete list before recording any of this family's gaps.
        gaps = prerequisites(identifiers, config=config)
        for gap in gaps:
            kind = "discovery" if gap.get("dependencies") else gap["reason"]
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason "
                "WHERE capability.status<>excluded.status OR capability.reason<>excluded.reason",
                (
                    f"planning:{family}:{gap['api_name']}:{kind}",
                    "discovery_unverified"
                    if gap.get("dependencies")
                    else "coverage_unverified",
                    utc_now(),
                    json.dumps(gap, sort_keys=True),
                ),
            )

    def plan_extended(self, config, today):
        started = time.monotonic()
        self.planning_timing = {
            "stage_seconds": {},
            "families": {},
            "active_stage": "identifiers",
            "failed_stage": None,
        }
        try:
            return self._plan_extended(config, today)
        except BaseException:
            self.planning_timing["failed_stage"] = self.planning_timing["active_stage"]
            raise
        finally:
            self.planning_timing["total_elapsed_seconds"] = max(
                0.0, time.monotonic() - started
            )

    def _plan_extended(self, config, today):
        started = time.monotonic()
        self.identifier_timing = None
        try:
            identifiers = self.identifiers(_use_cache=True)
            if config.get("enable_portfolio_read") is True:
                identifiers["portfolio_read_list"] = self.portfolio_read_identifier(
                    portfolio_read_snapshot_epoch(config, today)
                )
        finally:
            if isinstance(self.identifier_timing, dict):
                self.planning_timing["discovery"] = self.identifier_timing
            self.planning_timing["stage_seconds"]["identifiers"] = max(
                0.0, time.monotonic() - started
            )
        self.planning_timing["active_stage"] = "validation_and_snapshots"
        blocked_families = set()
        for family, validate in (
            ("realtime_auction", lambda cfg, ids: self.record_extra_planning_gaps("realtime_auction", cfg, ids)),
            ("realtime_extra", lambda cfg, ids: self.record_extra_planning_gaps("realtime_extra", cfg, ids)),
            ("realtime_replay", lambda cfg, ids: self.record_extra_planning_gaps("realtime_replay", cfg, ids)),
            (
                "account_history",
                lambda cfg, ids: self.record_extra_planning_gaps("account_history", cfg, ids),
            ),
            (
                "securities_lending_history",
                lambda cfg, ids: self.record_extra_planning_gaps("securities_lending_history", cfg, ids),
            ),
            ("history_minutes", lambda cfg, ids: self.record_extra_planning_gaps("history_minutes", cfg, ids)),
            (
                "calendar_extra",
                lambda cfg, ids: self.record_extra_planning_gaps("calendar_extra", cfg, ids),
            ),
            (
                "factor_library",
                lambda cfg, ids: self.record_extra_planning_gaps("factor_library", cfg, ids),
            ),
            (
                "market_members",
                lambda cfg, ids: self.record_extra_planning_gaps("market_members", cfg, ids),
            ),
            (
                "bond_extra",
                lambda cfg, ids: self.record_extra_planning_gaps("bond_extra", cfg, ids),
            ),
            (
                "cross_asset_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "cross_asset_extra", cfg, ids
                ),
            ),
            (
                "market_sentiment",
                lambda cfg, ids: self.record_extra_planning_gaps("market_sentiment", cfg, ids),
            ),
            (
                "foreign_financial",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "foreign_financial", cfg, ids
                ),
            ),
            (
                "stock_context",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "stock_context", cfg, ids
                ),
            ),
            (
                "technical_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "technical_extra", cfg, ids
                ),
            ),
            (
                "risk_event",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "risk_event", cfg, ids
                ),
            ),
            (
                "dc_extra",
                lambda cfg, ids: self.record_extra_planning_gaps("dc_extra", cfg, ids),
            ),
            (
                "concept_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "concept_extra", cfg, ids
                ),
            ),
            (
                "limit_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "limit_extra", cfg, ids
                ),
            ),
            (
                "listing_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "listing_extra", cfg, ids
                ),
            ),
            (
                "trading_event",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "trading_event", cfg, ids
                ),
            ),
            (
                "connect",
                lambda cfg, ids: self.record_extra_planning_gaps("connect", cfg, ids),
            ),
            (
                "portfolio_read",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "portfolio_read", cfg, ids
                ),
            ),
            (
                "etf_basket",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "etf_basket", cfg, ids
                ),
            ),
            (
                "credit_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "credit_extra", cfg, ids
                ),
            ),
            ("other", self.record_other_planning_gaps),
            ("global", self.record_global_planning_gaps),
            ("supplement", self.record_supplement_planning_gaps),
            ("equity_event", self.record_equity_event_planning_gaps),
            (
                "futures_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "futures_extra", cfg, ids
                ),
            ),
            (
                "catalog_delta",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "catalog_delta", cfg, ids
                ),
            ),
            (
                "research_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "research_extra", cfg, ids
                ),
            ),
            (
                "fina_mainbz_vip",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "fina_mainbz_vip", cfg, ids
                ),
            ),
        ):
            if not config.get("enable_" + family, False):
                continue
            scope = "planning:" + family
            try:
                validate(config, identifiers)
            except ValueError as error:
                # A malformed discovery blocks only its family, not independent
                # acquisition. Do not advance its cursor or rewrite persistent config.
                blocked_families.add(family)
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'validation_blocked',?,?) "
                    "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                    (
                        scope,
                        utc_now(),
                        json.dumps(
                            {"error_type": type(error).__name__, "reason": str(error)},
                            sort_keys=True,
                        ),
                    ),
                )
            else:
                self.db.execute(
                    "UPDATE capability SET status='validation_passed',checked_at=?,reason=? WHERE scope=? AND status='validation_blocked'",
                    (
                        utc_now(),
                        json.dumps({"reason": "family_validation_recovered"}),
                        scope,
                    ),
                )
        budget = int(config.get("plan_jobs_per_tick", 2000))
        if not 1 <= budget <= 10000:
            raise ValueError("Invalid planner batch size")
        history_scan_limit = config.get("history_plan_scan_limit", 100000)
        history_seconds = config.get("history_plan_seconds", 1.0)
        if type(history_scan_limit) is not int or not 1 <= history_scan_limit <= 100000:
            raise ValueError("Invalid historical planner scan limit")
        if (
            isinstance(history_seconds, bool)
            or not isinstance(history_seconds, (int, float))
            or not 0 < history_seconds <= 5
        ):
            raise ValueError("Invalid historical planner time limit")
        stats = {}
        if (
            "market" in PLANNERS
            and config.get("enable_market")
            and "market" not in blocked_families
        ):
            self.planning_timing["active_stage"] = "recent_dates:market"
            recent = {"planned": 0, "new_jobs": 0, "promoted_jobs": 0}
            for job in iter_market_date_refresh(config, today):
                before = self.db.total_changes
                key = self.enqueue(
                    job["api_name"], job["params"], 5, job["epoch"],
                    reuse_recent_open=True,
                )
                recent["new_jobs"] += self.db.total_changes - before
                recent["promoted_jobs"] += self.db.execute(
                    "UPDATE jobs SET priority=5 WHERE id=? AND state='pending' AND priority>5",
                    (key,),
                ).rowcount
                recent["planned"] += 1
            self.db.commit()
            stats["recent_dates:market"] = recent
        # Commit observed-period supplements before expensive ordinary families.
        # Repeated dictionary keys keep their first insertion position.
        priority_append = {
            name: APPEND_PLANNERS[name]
            for name in (
                "stock_rewards_periods",
                "equity_announcements",
                "fund_share_history",
            )
            if name in APPEND_PLANNERS
        }
        planners = {
            **priority_append,
            **PLANNERS,
            **APPEND_PLANNERS,
        }
        for family, planner in planners.items():
            self.planning_timing["active_stage"] = family + ":policy"
            if family == "stock_rewards_periods":
                if (
                    "stock_context" in blocked_families
                    or not config.get("enable_stock_context", False)
                    or "stk_rewards" not in config.get("stock_context_apis", STOCK_CONTEXT_RUNTIME_CONTRACTS)
                ):
                    continue
            elif family == "equity_announcements":
                selected = config.get("equity_event_apis", EQUITY_EVENT_CONTRACTS)
                if (
                    "equity_event" in blocked_families
                    or not config.get("enable_equity_event", False)
                    or not set(selected).intersection(ANNOUNCEMENTS)
                ):
                    continue
            elif family == "fund_share_history":
                selected = config.get("market_apis", tuple(EXTENDED_CONTRACTS))
                if (
                    "market" in blocked_families
                    or not config.get("enable_market", False)
                    or "fund_share" not in selected
                ):
                    continue
            elif family in blocked_families or not config.get("enable_" + family, False):
                continue
            policy, current_ids = _planning_inputs(family, config, identifiers)
            append_only = family in (
                "stock_rewards_periods",
                "equity_announcements",
                "fund_share_history",
            )
            modes = ("history",) if append_only else ("recent", "history")
            family_budget = min(budget, 500) if append_only else budget
            for mode in modes:
                name = mode + ":" + family
                self.planning_timing["active_stage"] = name + ":snapshot"
                epoch = (
                    datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d%H")
                    if family == "text"
                    else today.strftime("%Y%m%d")
                )
                refresh = epoch if mode == "recent" else "history"
                if (
                    mode == "history"
                    and family == "global"
                    and set(config.get("global_apis", GLOBAL_CONTRACTS)).intersection(
                        ("weekly", "monthly", "index_weekly", "index_monthly")
                    )
                ):
                    refresh = (
                        "periods:"
                        + str(today - timedelta(days=today.weekday() + 1))
                        + ":"
                        + str(today.replace(day=1) - timedelta(days=1))
                    )
                state = self.db.execute(
                    "SELECT * FROM planning_state WHERE name=?", (name,)
                ).fetchone()
                snapshot = _planning_snapshot(state)
                policy_changed = snapshot is None or snapshot["policy"] != policy
                # Finish one finite input/date snapshot before incorporating
                # discoveries or rolling the clock. Otherwise growth can starve
                # the historical tail (and a large recent universe) forever.
                refresh_due = snapshot is not None and (
                    snapshot["identifiers"] != current_ids
                    or snapshot["refresh"] != refresh
                    or (
                        mode == "recent" and state["anchor"] != today.strftime("%Y%m%d")
                    )
                )
                reset = policy_changed or (state["done"] and refresh_due)
                reset_reason = None
                if reset:
                    anchor = today
                    if mode == "recent" and not policy_changed:
                        # Every current planner covers at least six preceding
                        # calendar days. Catch up in overlapping windows if a
                        # finite sweep crossed >6 days, without creating holes.
                        previous = datetime.strptime(state["anchor"], "%Y%m%d").date()
                        anchor = min(today, previous + timedelta(days=6))
                    snapshot = {
                        "version": 1,
                        "policy": policy,
                        "identifiers": current_ids,
                        "refresh": refresh,
                        "epoch": epoch,
                    }
                    reset_reason = (
                        "policy_or_legacy_change"
                        if policy_changed
                        else "completed_snapshot_refresh"
                    )
                    self.db.execute(
                        "INSERT INTO planning_state(name,anchor,signature,offset,done) VALUES(?,?,?,0,0) ON CONFLICT(name) DO UPDATE SET anchor=excluded.anchor,signature=excluded.signature,offset=0,done=0",
                        (
                            name,
                            anchor.strftime("%Y%m%d"),
                            json_bytes(snapshot).decode(),
                        ),
                    )
                    state = self.db.execute(
                        "SELECT * FROM planning_state WHERE name=?", (name,)
                    ).fetchone()
                if state["done"]:
                    continue
                anchor = datetime.strptime(state["anchor"], "%Y%m%d").date()
                plan_config = {
                    **config,
                    "planning_epoch": snapshot["epoch"]
                    if mode == "recent"
                    else state["anchor"],
                }
                started = time.monotonic()
                timing = {
                    "initial_next_seconds": 0.0,
                    "source_next_seconds": 0.0,
                    "enqueue_seconds": 0.0,
                    "checkpoint_seconds": 0.0,
                    "initial_offset": state["offset"],
                    "source_items": 0,
                }
                self.planning_timing["families"][name] = timing
                self.planning_timing["active_stage"] = name + ":source_setup"
                stream = iter(planner(plan_config, anchor, snapshot["identifiers"]))
                stream = itertools.islice(stream, state["offset"], None)
                count, done = 0, False
                attempted, inserted = 0, 0
                stop_reason = "job_budget"
                # Only this append scope budgets new jobs; existing history IDs
                # still consume the shared scan/time bounds and advance offset.
                while (
                    inserted if append_only
                    else attempted if mode == "history" else count
                ) < family_budget:
                    if mode == "history":
                        if count >= history_scan_limit:
                            stop_reason = "scan_limit"
                            break
                        if time.monotonic() - started >= history_seconds:
                            stop_reason = "time_limit"
                            break
                    # Cooperative bounds: a synchronous next() (including the
                    # existing islice replay) must return before time is checked.
                    # Count every consumed item, even intentionally skipped recent
                    # entries, so persisted offsets retain their absolute meaning.
                    self.planning_timing["active_stage"] = name + ":source_next"
                    next_started = time.monotonic()
                    try:
                        job = next(stream, None)
                    finally:
                        elapsed = max(0.0, time.monotonic() - next_started)
                        timing["source_next_seconds"] += elapsed
                        if count == 0:
                            timing["initial_next_seconds"] += elapsed
                    if job is None or (mode == "recent" and job["epoch"] == "history"):
                        done = True
                        stop_reason = "stream_end"
                        break
                    if mode != "history" or job["epoch"] == "history":
                        attempted += 1
                        before = self.db.total_changes
                        self.planning_timing["active_stage"] = name + ":enqueue"
                        enqueue_started = time.monotonic()
                        try:
                            self.enqueue(
                                job["api_name"],
                                job["params"],
                                job["priority"],
                                job["epoch"],
                                reuse_recent_open=mode == "recent",
                            )
                        finally:
                            timing["enqueue_seconds"] += max(
                                0.0, time.monotonic() - enqueue_started
                            )
                        inserted += self.db.total_changes - before
                    count += 1
                    timing["source_items"] = count
                self.planning_timing["active_stage"] = name + ":checkpoint"
                checkpoint_started = time.monotonic()
                try:
                    self.db.execute(
                        "UPDATE planning_state SET offset=offset+?,done=? WHERE name=?",
                        (count, int(done), name),
                    )
                    self.db.commit()
                finally:
                    timing["checkpoint_seconds"] = max(
                        0.0, time.monotonic() - checkpoint_started
                    )
                    timing["total_elapsed_seconds"] = max(0.0, time.monotonic() - started)
                stats[name] = {
                    "planned": count,
                    "new_jobs": inserted,
                    "existing_jobs": attempted - inserted,
                    "skipped_recent": count - attempted,
                    "done": done,
                    "anchor": state["anchor"],
                    "reset_reason": reset_reason,
                    "discovery_refresh_pending": snapshot["identifiers"] != current_ids,
                    "stop_reason": stop_reason,
                }
        self.planning_timing["active_stage"] = "final_commit"
        self.db.commit()  # Persist validation gaps even when every family is blocked.
        self.planning_timing["active_stage"] = "complete"
        return stats

    def date_children(self, job):
        """The exact date partition rule used by both v3 and v4."""
        params = job["params"]
        split = contract_for(job["api_name"]).get("split")
        if "pub_start" in params and "pub_end" in params:
            split = {
                "start_param": "pub_start",
                "end_param": "pub_end",
                "precision": "second",
            }
        if (
            not split
            or split["start_param"] not in params
            or split["end_param"] not in params
        ):
            return None
        fmt = "%Y-%m-%d %H:%M:%S" if split["precision"] == "second" else "%Y%m%d"
        left = datetime.strptime(params[split["start_param"]], fmt)
        right = datetime.strptime(params[split["end_param"]], fmt)
        step = (
            timedelta(seconds=1)
            if split["precision"] == "second"
            else timedelta(days=1)
        )
        units = int((right - left) / step)
        if units <= 0:
            return None
        middle = left + (units // 2) * step
        children = [
            {**params, split["end_param"]: middle.strftime(fmt)},
            {**params, split["start_param"]: (middle + step).strftime(fmt)},
        ]
        if split["precision"] == "second" and units > 1:
            children[1][split["start_param"]] = middle.strftime(fmt)
        return children

    def record_partition(self, parent_id, children, method, coverage_proven, evidence):
        """Record a complete immutable split plan in the caller's transaction."""
        children = sorted(set(children))
        parent = self.db.execute(
            "SELECT epoch,job FROM jobs WHERE id=?", (parent_id,)
        ).fetchone()
        if not parent:
            raise ValueError("Missing parent job")
        if not children or parent_id in children:
            raise ValueError("A partition requires distinct children")
        for child in children:
            saved_child = self.db.execute(
                "SELECT epoch,job FROM jobs WHERE id=?", (child,)
            ).fetchone()
            if not saved_child:
                raise ValueError("Missing child job")
            if (
                saved_child["epoch"] != parent["epoch"]
                or json.loads(saved_child["job"])["api_name"]
                != json.loads(parent["job"])["api_name"]
            ):
                raise ValueError(
                    "Child belongs to a different API or observation epoch"
                )
            cycle = self.db.execute(
                "WITH RECURSIVE descendants(id) AS (SELECT child_id FROM partition_children WHERE parent_id=? "
                "UNION SELECT c.child_id FROM partition_children c JOIN descendants d ON c.parent_id=d.id) "
                "SELECT 1 FROM descendants WHERE id=? LIMIT 1",
                (child, parent_id),
            ).fetchone()
            if cycle:
                raise ValueError("Partition relationship would create a cycle")
        existing = self.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (parent_id,)
        ).fetchone()
        if (
            existing
            and json.loads(existing["evidence"]).get("origin") != "legacy_unverified"
        ):
            old = [
                r[0]
                for r in self.db.execute(
                    "SELECT child_id FROM partition_children WHERE parent_id=? ORDER BY child_id",
                    (parent_id,),
                )
            ]
            if (
                old != children
                or existing["method"] != method
                or existing["coverage_proven"] != int(coverage_proven)
            ):
                raise ValueError("Existing partition plan differs")
            return
        self.db.execute(
            "INSERT INTO partition_splits VALUES(?,?,?,?,?,'pending',NULL) "
            "ON CONFLICT(parent_id) DO UPDATE SET method=excluded.method,expected_children=excluded.expected_children,"
            "coverage_proven=excluded.coverage_proven,evidence=excluded.evidence,status='pending',gap=NULL",
            (
                parent_id,
                method,
                len(children),
                int(coverage_proven),
                json.dumps(evidence, sort_keys=True),
            ),
        )
        self.db.executemany(
            "INSERT OR IGNORE INTO partition_children VALUES(?,?)",
            [(parent_id, child) for child in children],
        )

    def recover_legacy_partitions(self):
        """Recover only exact, unique v3 date children; never infer a universe."""
        for row in self.db.execute("SELECT * FROM jobs WHERE state='split_pending'"):
            recovered = False
            method = "unknown"
            try:
                job, result = json.loads(row["job"]), json.loads(row["result"] or "{}")
                method = result.get("split", {}).get("method", "unknown")
                expected = (
                    self.date_children(job) if method == "date_bisection" else None
                )
                if expected and result.get("split", {}).get("children") == 2:
                    matches = []
                    for params in expected:
                        candidates = []
                        filters = [
                            (key, value)
                            for key, value in params.items()
                            if value is None or isinstance(value, (str, int, float))
                        ]
                        where = " AND json_extract(job,?) IS ?" * len(filters)
                        values = [
                            item
                            for key, value in filters
                            for item in ("$.params." + json.dumps(key), value)
                        ]
                        for child in self.db.execute(
                            "SELECT id,job FROM jobs WHERE epoch=? AND json_extract(job,'$.api_name')=? AND id<>?"
                            + where,
                            (row["epoch"], job["api_name"], row["id"], *values),
                        ):
                            candidate = json.loads(child["job"])
                            if candidate == {**job, "params": params}:
                                candidates.append(child["id"])
                        if len(candidates) != 1:
                            break
                        matches.extend(candidates)
                    if len(matches) == 2:
                        self.record_partition(
                            row["id"],
                            matches,
                            method,
                            True,
                            {"origin": "v3_exact_job_match"},
                        )
                        recovered = True
            except (ValueError, KeyError, TypeError):
                pass
            if not recovered:
                self.db.execute(
                    "INSERT OR IGNORE INTO partition_splits VALUES(?,?,0,0,?,'gap',?)",
                    (
                        row["id"],
                        method,
                        json.dumps({"origin": "legacy_unverified"}),
                        "legacy_relationship_unverified",
                    ),
                )

    def split_observed_futures(self, row, job, result, existing):
        """Only source-observed partitions; no complete-universe inference."""
        api, params = job["api_name"], job["params"]
        fields = (
            ("exchange", "symbol")
            if api == "fut_holding"
            else ("exchange", "prd")
            if "week" in params
            else ("week",)
        )
        saved = result if result is not None else json.loads(row["result"] or "{}")
        records = self.records(saved) if saved.get("object_sha256") else []
        issues = {}
        observed = {}

        def gap(kind):
            issues[kind] = issues.get(kind, 0) + 1

        def usable(field, value):
            if (
                field == "week"
                and isinstance(value, int)
                and not isinstance(value, bool)
            ):
                return value > 0
            return (
                isinstance(value, str)
                and 0 < len(value) <= 128
                and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            )

        for record in records:
            # Check only explicit equality constraints, never reinterpret range
            # bounds or derive a supplier week from week_date.
            constrained = tuple(
                field
                for field in ("trade_date", "week", "exchange", "symbol", "prd")
                if field in params
            )
            required = set(fields) | set(constrained)
            if any(field not in record or record[field] is None for field in required):
                gap("missing_partition_fields")
                continue
            if any(not usable(field, record[field]) for field in required):
                gap("invalid_partition_values")
                continue
            if any(record[field] != params[field] for field in constrained):
                gap("parent_filter_mismatch")
                continue
            child = {**params, **{field: record[field] for field in fields}}
            if child == params:
                gap("saturated_terminal_partition")
                continue
            observed[json_bytes(child)] = child
        if not records:
            gap("missing_source_partition_rows")
        previous = {
            child[0]
            for child in self.db.execute(
                "SELECT child_id FROM partition_children WHERE parent_id=?",
                (row["id"],),
            )
        }
        children = previous | {
            self.enqueue(api, child, row["priority"] + 1, row["epoch"])
            for _, child in sorted(observed.items())
        }
        evidence = (
            json.loads(existing["evidence"])
            if existing
            else {"origin": "observed_futures"}
        )
        evidence.update(universe_complete=False, partition_fields=list(fields))
        sources = evidence.setdefault("source_observations", {})
        observation_key = digest(
            json_bytes([saved.get("observation"), saved.get("object_sha256")])
        )
        sources.setdefault(
            observation_key,
            {
                "observation": saved.get("observation"),
                "object_sha256": saved.get("object_sha256"),
                "observed_partitions": len(observed),
                "gaps": issues,
            },
        )
        # Per-observation gaps remain independent even if reconciliation later
        # reports the encompassing universe_unverified gap.
        if existing:
            for child in children - previous:
                cycle = self.db.execute(
                    "WITH RECURSIVE descendants(id) AS (SELECT child_id FROM partition_children WHERE parent_id=? "
                    "UNION SELECT c.child_id FROM partition_children c JOIN descendants d ON c.parent_id=d.id) "
                    "SELECT 1 FROM descendants WHERE id=? LIMIT 1",
                    (child, row["id"]),
                ).fetchone()
                if child == row["id"] or cycle:
                    raise ValueError("Partition relationship would create a cycle")
            self.db.executemany(
                "INSERT OR IGNORE INTO partition_children VALUES(?,?)",
                [(row["id"], child) for child in sorted(children - previous)],
            )
            self.db.execute(
                "UPDATE partition_splits SET method='observed_futures_fanout',expected_children=?,coverage_proven=0,evidence=?,status='gap',gap='universe_unverified' WHERE parent_id=?",
                (len(children), json.dumps(evidence, sort_keys=True), row["id"]),
            )
        elif children:
            self.record_partition(
                row["id"], sorted(children), "observed_futures_fanout", False, evidence
            )
        else:
            self.db.execute(
                "INSERT INTO partition_splits VALUES(?,'observed_futures_fanout',0,0,?,'gap','universe_unverified')",
                (row["id"], json.dumps(evidence, sort_keys=True)),
            )
        return {
            "method": "observed_futures_fanout",
            "children": len(children),
            "universe_complete": False,
            "observed_partitions": len(observed),
            "added_children": len(children - previous),
            "gaps": issues,
        }

    def split_request(self, row, job, result=None, *, max_new_jobs=None):
        spec = contract_for(job["api_name"])
        if max_new_jobs is not None and (
            type(max_new_jobs) is not int or not 1 <= max_new_jobs <= 10000
        ):
            raise ValueError("Invalid saturation fanout budget")
        params = job["params"]
        if spec.get("group") == "global" and spec.get("pagination"):
            return None
        existing = self.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (row["id"],)
        ).fetchone()
        observed_rule = (
            ECO_CAL_OBSERVED_FANOUT if job["api_name"] == "eco_cal" else {}
        )
        family = spec.get("saturation_fallback") or observed_rule.get("family")
        param = spec.get("saturation_param") or observed_rule.get(
            "param", "ts_code"
        )
        fanout = (
            family
            and param not in params
            and not (
                spec.get("saturation_date_first") and self.date_children(job)
            )
            and not (
                spec.get("saturation_history_only")
                and row["epoch"] != "history"
            )
        )
        partition_axis = _saturation_partition_axis(spec, params)
        if partition_axis:
            partition_param = partition_axis["param"]
            output_field = partition_axis["output_field"]
            saved = result if result is not None else json.loads(row["result"] or "{}")
            if saved.get("object_sha256"):
                configured = partition_axis["values"]
                value_kind = partition_axis["value_kind"]

                def valid_partition_value(value):
                    if value_kind == "code":
                        return isinstance(value, str) and bool(
                            re.fullmatch(r"[A-Z0-9]{2,16}", value)
                        )
                    if value_kind == "supplier_text":
                        return (
                            isinstance(value, str)
                            and value == value.strip()
                            and 1 <= len(value) <= 128
                            and all(ord(char) >= 32 and ord(char) != 127 for char in value)
                        )
                    raise ValueError("Invalid saturation partition value kind")

                if not isinstance(configured, (list, tuple)) or any(
                    not valid_partition_value(value) for value in configured
                ):
                    raise ValueError("Invalid saturation partition values")
                observed, invalid = set(), 0
                for record in self.records(saved, fields={output_field}):
                    value = record.get(output_field)
                    if valid_partition_value(value):
                        observed.add(value)
                    else:
                        invalid += 1
                values = sorted(set(configured) | observed)
                if values:
                    previous = {
                        child[0]
                        for child in self.db.execute(
                            "SELECT child_id FROM partition_children WHERE parent_id=?",
                            (row["id"],),
                        )
                    }
                    children = {
                        self.enqueue(
                            job["api_name"],
                            {**params, partition_param: value},
                            row["priority"] + 1,
                            row["epoch"],
                        )
                        for value in values
                    }
                    evidence = {
                        "origin": "documented_union_parent_observation",
                        "partition_param": partition_param,
                        "output_field": output_field,
                        "configured_values": list(configured),
                        "observed_values": sorted(observed),
                        "value_kind": value_kind,
                        "partition_axis_index": partition_axis["index"],
                        "partition_axis_count": partition_axis["count"],
                        "invalid_parent_values": invalid,
                        "parent_observation": saved.get("observation"),
                        "parent_object_sha256": saved.get("object_sha256"),
                        "universe_complete": False,
                    }
                    retired = previous - children
                    if existing:
                        evidence["replaced_method"] = existing["method"]
                        evidence["replaced_children"] = len(previous)
                        self.db.execute(
                            "DELETE FROM partition_children WHERE parent_id=?",
                            (row["id"],),
                        )
                        self.db.execute(
                            "UPDATE partition_splits SET method='observed_value_fanout',expected_children=?,coverage_proven=0,evidence=?,status='pending',gap=NULL WHERE parent_id=?",
                            (len(children), json.dumps(evidence, sort_keys=True), row["id"]),
                        )
                    else:
                        self.record_partition(
                            row["id"],
                            sorted(children),
                            "observed_value_fanout",
                            False,
                            evidence,
                        )
                    if existing:
                        self.db.executemany(
                            "INSERT OR IGNORE INTO partition_children VALUES(?,?)",
                            [(row["id"], child) for child in sorted(children)],
                        )
                    retired_open = 0
                    if retired:
                        self.db.execute(
                            "CREATE TEMP TABLE IF NOT EXISTS retired_partition_children "
                            "(id TEXT PRIMARY KEY) WITHOUT ROWID"
                        )
                        self.db.execute("DELETE FROM retired_partition_children")
                        self.db.executemany(
                            "INSERT INTO retired_partition_children VALUES(?)",
                            ((child,) for child in retired),
                        )
                        retired_open = self.db.execute("""
                            UPDATE jobs SET state='superseded'
                            WHERE id IN (SELECT id FROM retired_partition_children)
                              AND state IN ('pending','split_pending')
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM partition_children AS edge
                                  JOIN jobs AS parent ON parent.id=edge.parent_id
                                  WHERE edge.child_id=jobs.id
                                    AND parent.state='split_pending'
                              )
                        """).rowcount
                    return {
                        "method": "observed_value_fanout",
                        "partition_param": partition_param,
                        "children": len(children),
                        "universe_complete": False,
                        "observed_values": sorted(observed),
                        "retired_open_children": retired_open,
                    }
        if (
            existing
            and existing["expected_children"]
            and not (existing["method"] == "identifier_fanout" and fanout)
            and not (
                existing["method"] == "observed_futures_fanout"
                and job["api_name"] in ("fut_holding", "fut_weekly_detail")
            )
        ):
            return {
                "method": existing["method"],
                "children": existing["expected_children"],
                "universe_complete": bool(existing["coverage_proven"]),
            }
        children = self.date_children(job)
        if children:
            ids = [
                self.enqueue(job["api_name"], child, row["priority"], row["epoch"])
                for child in children
            ]
            self.record_partition(
                row["id"],
                ids,
                "date_bisection",
                True,
                {"origin": "v4", "date_coverage": "exhaustive"},
            )
            return {"method": "date_bisection", "children": len(ids)}
        if job["api_name"] in ("fut_holding", "fut_weekly_detail"):
            return self.split_observed_futures(row, job, result, existing)
        if fanout:

            def normalize(code):
                if job["api_name"] == "anns_d":
                    return normalize_anns_d_ts_code(code)
                return code

            def usable(code):
                if observed_rule:
                    return (
                        isinstance(code, str)
                        and 0 < len(code) <= 128
                        and code == code.strip()
                        and not any(ord(char) < 32 or ord(char) == 127 for char in code)
                    )
                return (
                    isinstance(code, str)
                    and bool(code)
                    and not any(
                        char.isspace() or ord(char) < 32 or ord(char) == 127
                        for char in code
                    )
                )

            identifiers = (
                self.identifiers(_source_apis=IDENTIFIER_SPLIT_SOURCE_APIS[family])
                if family in IDENTIFIER_SPLIT_SOURCE_APIS
                else self.identifiers()
            )
            discovered = {
                normalized
                for code in identifiers.get(family, [])
                if usable(normalized := normalize(code))
            }
            saved = result if result is not None else json.loads(row["result"] or "{}")
            observed = (
                {
                    normalized
                    for record in self.records(saved)
                    if usable(normalized := normalize(record.get(param)))
                }
                if saved.get("object_sha256")
                else set()
            )
            codes = discovered | observed
            previous_ids = {
                child[0]
                for child in self.db.execute(
                    "SELECT child_id FROM partition_children WHERE parent_id=?",
                    (row["id"],),
                )
            }
            limit = spec.get("saturation_jobs_per_run") or observed_rule.get(
                "jobs_per_run"
            )
            if limit is not None and (
                type(limit) is not int or not 1 <= limit <= 10000
            ):
                raise ValueError("Invalid contract saturation fanout budget")
            if max_new_jobs is not None:
                limit = min(limit or max_new_jobs, max_new_jobs)
            if limit is None:
                selected_codes = sorted(codes)
                remaining = 0
            else:
                previous_codes = {
                    json.loads(child[0])["params"].get(param)
                    for child in self.db.execute(
                        "SELECT j.job FROM partition_children c "
                        "JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                        (row["id"],),
                    )
                }
                new_codes = sorted(codes - previous_codes)
                selected_codes = new_codes[:limit]
                remaining = len(new_codes) - len(selected_codes)
            ids = previous_ids | {
                self.enqueue(
                    job["api_name"],
                    {**params, param: code},
                    row["priority"] + 1,
                    row["epoch"],
                )
                for code in selected_codes
            }
            if ids:
                evidence = (
                    json.loads(existing["evidence"]) if existing else {"origin": "v4"}
                )
                evidence.update(family=family, universe_complete=False)
                if limit is not None:
                    evidence.update(
                        new_job_budget=limit,
                        observed_values_remaining=remaining,
                    )
                if saved.get("object_sha256"):
                    evidence.update(
                        parent_observed_code_count=len(observed),
                        parent_observed_added_count=len(observed - discovered),
                        parent_observation=saved.get("observation"),
                    )
                if existing:
                    # Identifier discovery can grow. Append relationships instead of
                    # replacing the immutable date partition contract in record_partition.
                    for child in ids - previous_ids:
                        cycle = self.db.execute(
                            "WITH RECURSIVE descendants(id) AS (SELECT child_id FROM partition_children WHERE parent_id=? "
                            "UNION SELECT c.child_id FROM partition_children c JOIN descendants d ON c.parent_id=d.id) "
                            "SELECT 1 FROM descendants WHERE id=? LIMIT 1",
                            (child, row["id"]),
                        ).fetchone()
                        if child == row["id"] or cycle:
                            raise ValueError(
                                "Partition relationship would create a cycle"
                            )
                    self.db.execute(
                        "UPDATE partition_splits SET method='identifier_fanout',expected_children=?,coverage_proven=0,evidence=?,status='pending',gap=NULL WHERE parent_id=?",
                        (len(ids), json.dumps(evidence, sort_keys=True), row["id"]),
                    )
                    self.db.executemany(
                        "INSERT OR IGNORE INTO partition_children VALUES(?,?)",
                        [(row["id"], child) for child in sorted(ids - previous_ids)],
                    )
                else:
                    self.record_partition(
                        row["id"], sorted(ids), "identifier_fanout", False, evidence
                    )
                # An unchanged re-entry must not erase a prior unresolved gap/status.
                if (
                    existing
                    and ids == previous_ids
                    and not existing["coverage_proven"]
                    and existing["status"] != "resolved"
                ):
                    self.db.execute(
                        "UPDATE partition_splits SET status=?,gap=? WHERE parent_id=?",
                        (existing["status"], existing["gap"], row["id"]),
                    )
                response = {
                    "method": "identifier_fanout",
                    "children": len(ids),
                    "universe_complete": False,
                    "parent_observed_added_count": evidence.get(
                        "parent_observed_added_count", 0
                    ),
                }
                if limit is not None:
                    response["remaining_observed_values"] = remaining
                return response
        return None

    def partition_artifact_gap(self, parquet):
        """Stream-verify immutable bytes; cache only while file identity is unchanged."""
        name, expected_sha, expected_bytes = (
            parquet.get(k) for k in ("path", "sha256", "bytes")
        )
        if (
            not isinstance(name, str)
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or not isinstance(expected_sha, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_sha)
            or type(expected_bytes) is not int
            or expected_bytes <= 0
        ):
            return "child_artifact_evidence_invalid"
        path = self.root / name

        def identity(value):
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or not path.resolve().is_relative_to(
                self.root.resolve()
            ):
                return "child_artifact_invalid"
            signature = (identity(before), expected_sha, expected_bytes)
            cached = self._partition_artifact_checks.get(name)
            if cached and cached[0] == signature:
                return cached[1]
            gap = "child_artifact_corrupt"
            if before.st_size == expected_bytes:
                with path.open("rb") as stream:
                    if identity(os.fstat(stream.fileno())) != identity(before):
                        return "child_artifact_changed"
                    checksum = hashlib.sha256()
                    observed_bytes = 0
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        observed_bytes += len(chunk)
                        if observed_bytes > expected_bytes:
                            return "child_artifact_changed"
                        checksum.update(chunk)
                    if identity(os.fstat(stream.fileno())) != identity(before):
                        return "child_artifact_changed"
                if identity(path.lstat()) != identity(before):
                    return "child_artifact_changed"
                gap = None if checksum.hexdigest() == expected_sha else gap
            # Bound memory even when historical reconciliation visits millions of files.
            if len(self._partition_artifact_checks) >= 4096:
                self._partition_artifact_checks.clear()
            self._partition_artifact_checks[name] = (signature, gap)
            return gap
        except FileNotFoundError:
            self._partition_artifact_checks.pop(name, None)
            return "child_artifact_missing"
        except OSError:
            self._partition_artifact_checks.pop(name, None)
            return "child_artifact_unreadable"

    def reconcile_partitions(
        self, max_parents=1000, child_id=None, deadline=None, parent_state=None
    ):
        """Bounded, restartable closure; descendants must carry positive evidence.

        A done pagination page or empty-unverified terminator is not a complete
        partition. Resolved children are acceptable only while their split evidence
        still holds. The single writer never promotes an incomplete universe.
        """
        if not 1 <= max_parents <= 10000:
            raise ValueError("Invalid partition reconciliation budget")
        if deadline is not None and type(deadline) not in (int, float):
            raise ValueError("Invalid partition reconciliation deadline")
        if parent_state not in (None, "split_pending", "resolved"):
            raise ValueError("Invalid partition reconciliation parent state")
        if child_id is not None and parent_state is not None:
            raise ValueError("Child reconciliation cannot filter parent state")
        selected = []
        cursor = None
        if child_id is None:
            cursor_name = (
                "partition_cursor"
                if parent_state is None
                else "partition_cursor:" + parent_state
            )
            saved = self.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?", (cursor_name,)
            ).fetchone()
            cursor = saved[0] if saved else 0
            if parent_state is None:
                selected = self.db.execute(
                    "SELECT rowid AS split_rowid,parent_id FROM partition_splits "
                    "WHERE rowid>? ORDER BY rowid LIMIT ?",
                    (cursor, max_parents),
                ).fetchall()
            else:
                selected = self.db.execute(
                    "SELECT p.rowid AS split_rowid,p.parent_id "
                    "FROM partition_splits p JOIN jobs j ON j.id=p.parent_id "
                    "WHERE p.rowid>? AND j.state=? ORDER BY p.rowid LIMIT ?",
                    (cursor, parent_state, max_parents),
                ).fetchall()
            if len(selected) < max_parents:
                if parent_state is None:
                    wrapped = self.db.execute(
                        "SELECT rowid AS split_rowid,parent_id FROM partition_splits "
                        "WHERE rowid<=? ORDER BY rowid LIMIT ?",
                        (cursor, max_parents - len(selected)),
                    ).fetchall()
                else:
                    wrapped = self.db.execute(
                        "SELECT p.rowid AS split_rowid,p.parent_id "
                        "FROM partition_splits p JOIN jobs j ON j.id=p.parent_id "
                        "WHERE p.rowid<=? AND j.state=? ORDER BY p.rowid LIMIT ?",
                        (cursor, parent_state, max_parents - len(selected)),
                    ).fetchall()
                selected.extend(wrapped)
            pending = deque(
                (row["parent_id"], row["split_rowid"]) for row in selected
            )
        else:
            pending = deque(
                (r[0], None)
                for r in self.db.execute(
                    "SELECT parent_id FROM partition_children WHERE child_id=? UNION SELECT parent_id FROM partition_splits WHERE parent_id=?",
                    (child_id, child_id),
                )
            )
        checked = resolved = changed_count = newly_resolved = 0
        reaffirmed_resolved = 0
        last_cursor = cursor
        while pending and checked < max_parents:
            if deadline is not None and time.monotonic() >= deadline:
                break
            parent_id, cursor_rowid = pending.popleft()
            if cursor_rowid is not None:
                last_cursor = cursor_rowid
            split = self.db.execute(
                "SELECT * FROM partition_splits WHERE parent_id=?", (parent_id,)
            ).fetchone()
            if not split:
                continue
            parent = self.db.execute(
                "SELECT state FROM jobs WHERE id=?", (parent_id,)
            ).fetchone()
            if not parent:
                continue
            gap = None
            children = self.db.execute(
                "SELECT c.child_id,j.state,j.result,s.status AS split_status FROM partition_children c "
                "LEFT JOIN jobs j ON j.id=c.child_id LEFT JOIN partition_splits s ON s.parent_id=c.child_id WHERE c.parent_id=?",
                (parent_id,),
            ).fetchall()
            evidence = json.loads(split["evidence"])
            replacement_gap = evidence.get("replacement_gap")
            preserve_replacement = (
                replacement_gap in REPLACEMENT_GAPS
                and parent["state"] == "blocked"
            )
            if preserve_replacement:
                gap = replacement_gap
            elif evidence.get("origin") == "legacy_unverified":
                gap = "legacy_relationship_unverified"
            elif parent["state"] not in ("split_pending", "resolved"):
                gap = "parent_not_split_pending"
            elif not split["coverage_proven"]:
                gap = "universe_unverified"
            elif not children or len(children) != split["expected_children"]:
                gap = "child_relationship_incomplete"
            else:
                for child in children:
                    try:
                        result = json.loads(child["result"] or "{}")
                    except (ValueError, TypeError):
                        gap = "child_evidence_invalid"
                        break
                    if (
                        child["state"] == "resolved"
                        and child["split_status"] == "resolved"
                    ):
                        continue
                    parquet = result.get("parquet") or {}
                    if (
                        child["state"] != "done"
                        or result.get("status") != "sample_ok"
                        or result.get("pagination_error")
                        or not result.get("row_count", 0)
                    ):
                        gap = "child_not_verified"
                        break
                    gap = self.partition_artifact_gap(parquet)
                    if gap:
                        break
            status = (
                "blocked"
                if preserve_replacement
                else "gap"
                if gap
                else "resolved"
            )
            was_resolved = (
                parent["state"] == "resolved"
                and split["status"] == "resolved"
                and split["gap"] is None
            )
            next_parent_state = "split_pending" if gap else "resolved"
            changed = (
                split["status"] != status
                or split["gap"] != gap
                or (
                    parent["state"] in ("split_pending", "resolved")
                    and parent["state"] != next_parent_state
                )
            )
            self.db.execute(
                "UPDATE partition_splits SET status=?,gap=? WHERE parent_id=?",
                (status, gap, parent_id),
            )
            if parent["state"] in ("split_pending", "resolved"):
                self.db.execute(
                    "UPDATE jobs SET state=? WHERE id=?",
                    (next_parent_state, parent_id),
                )
            if changed:
                pending.extend(
                    (r[0], None)
                    for r in self.db.execute(
                        "SELECT parent_id FROM partition_children WHERE child_id=?",
                        (parent_id,),
                    )
                )
            checked += 1
            resolved += int(not gap)
            changed_count += int(changed)
            newly_resolved += int(not gap and not was_resolved)
            reaffirmed_resolved += int(not gap and was_resolved)
        if child_id is None:
            self.db.execute(
                "INSERT INTO scheduler_state VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (cursor_name, 0 if not selected else last_cursor),
            )
        self.db.commit()
        return {
            "checked": checked,
            "resolved": resolved,
            "changed": changed_count,
            "newly_resolved": newly_resolved,
            "reaffirmed_resolved": reaffirmed_resolved,
        }

    def partition_inventory(self):
        entries = []
        for row in self.db.execute(
            "SELECT split.* FROM partition_splits AS split "
            "LEFT JOIN jobs AS parent ON parent.id=split.parent_id "
            "WHERE COALESCE(parent.state,'')<>'superseded' ORDER BY split.parent_id"
        ):
            item = dict(row)
            item["evidence"] = json.loads(item["evidence"])
            item["children"] = [
                r[0]
                for r in self.db.execute(
                    "SELECT edge.child_id FROM partition_children AS edge "
                    "LEFT JOIN jobs AS child ON child.id=edge.child_id "
                    "WHERE edge.parent_id=? "
                    "AND COALESCE(child.state,'')<>'superseded' "
                    "ORDER BY edge.child_id",
                    (row["parent_id"],),
                )
            ]
            entries.append(item)
        return {"schema_version": 1, "splits": entries}

    def expand(self, config):
        for row in self.db.execute(
            "SELECT * FROM jobs INDEXED BY jobs_unexpanded WHERE expanded=0 AND state IN ('done','quality','empty')"
        ).fetchall():
            job, result = json.loads(row["job"]), json.loads(row["result"])
            if job["api_name"] == "trade_cal":
                for record in self.records(result):
                    if str(record["is_open"]) == "1":
                        day = record["cal_date"]
                        priority = 10 if day >= config["priority_start"] else 55
                        # Historical partitions use a stable key; recent rechecks use date epochs.
                        epoch = (
                            row["epoch"]
                            if job["params"]["start_date"] == job["params"]["end_date"]
                            else "history"
                        )
                        self.enqueue("fund_daily", {"trade_date": day}, priority, epoch)
                        self.enqueue(
                            "fund_adj",
                            {"trade_date": day, "offset": 0, "limit": 1000},
                            priority,
                            epoch,
                        )
            self.db.execute("UPDATE jobs SET expanded=1 WHERE id=?", (row["id"],))
        self.db.commit()

    def identifier_split_needs_discovery(self, job, *, epoch=None):
        spec = contract_for(job["api_name"])
        observed_rule = (
            ECO_CAL_OBSERVED_FANOUT if job["api_name"] == "eco_cal" else {}
        )
        partition_axis = _saturation_partition_axis(spec, job["params"])
        return bool(
            (spec.get("saturation_fallback") or observed_rule.get("family"))
            and not (
                spec.get("saturation_history_only") and epoch != "history"
            )
            and (
                spec.get("saturation_param")
                or observed_rule.get("param", "ts_code")
            )
            not in job["params"]
            and not partition_axis
            and job["api_name"] not in ("fut_holding", "fut_weekly_detail")
            and not (spec.get("group") == "global" and spec.get("pagination"))
            and not self.date_children(job)
        )

    def deferred_split_kind(self, job, result, *, epoch=None):
        if self.identifier_split_needs_discovery(job, epoch=epoch):
            return "identifier_fanout"
        if (
            job["api_name"] in ("fut_holding", "fut_weekly_detail")
            and result.get("object_sha256")
        ):
            return "observed_futures_fanout"
        spec = contract_for(job["api_name"])
        partition_axis = _saturation_partition_axis(spec, job["params"])
        if (
            partition_axis
            and result.get("object_sha256")
        ):
            return "observed_value_fanout"
        if spec.get("recover_legacy_blocked_date_bisection") and self.date_children(
            job
        ):
            return "date_bisection"
        return None

    def resume_identifier_split(self, deadline, config):
        # Existing state index limits this read to unresolved parents, not the
        # millions of pending acquisition jobs. The result is already durable.
        row = self.db.execute(
            "SELECT * FROM jobs WHERE state='split_pending' "
            "AND json_type(result,'$.partition_deferred') IS NOT NULL "
            "ORDER BY priority,rowid LIMIT 1"
        ).fetchone()
        recovered_legacy = False
        if row is None:
            # Selected older caps were terminal only because a now-reviewed
            # identifier fanout was absent. Reuse retained responses; never
            # repeat their HTTP calls. Other blocked parents may have been
            # deliberately retired by a later range plan and stay excluded.
            legacy_apis = tuple(
                dict.fromkeys(
                    (
                        "eco_cal",
                        *LEGACY_IDENTIFIER_RECOVERY_APIS,
                        *LEGACY_OBSERVED_RECOVERY_APIS,
                        *LEGACY_DATE_RECOVERY_APIS,
                    )
                )
            )
            placeholders = ",".join("?" for _ in legacy_apis)
            candidates = self.db.execute(
                "SELECT * FROM jobs WHERE state='blocked' "
                f"AND json_extract(job,'$.api_name') IN ({placeholders}) "
                "AND json_extract(result,'$.status')='possibly_truncated' "
                "AND json_type(result,'$.object_sha256')='text' "
                "AND json_type(result,'$.observation')='text' "
                "ORDER BY priority,rowid",
                legacy_apis,
            ).fetchall()
            for candidate in candidates:
                candidate_job = json.loads(candidate["job"])
                candidate_result = json.loads(candidate["result"])
                if self.deferred_split_kind(
                    candidate_job,
                    candidate_result,
                    epoch=candidate["epoch"],
                ):
                    row = candidate
                    recovered_legacy = True
                    break
        if row is None:
            return None
        if time.monotonic() >= deadline:
            return {"status": "deadline_deferred", "job_id": row["id"], "upstream_calls": 0}
        job, result = json.loads(row["job"]), json.loads(row["result"])
        deferred_kind = self.deferred_split_kind(job, result, epoch=row["epoch"])
        if recovered_legacy:
            result["partition_deferred"] = {
                "version": 1,
                "kind": deferred_kind,
            }
            result["partition_recovery"] = {
                "version": 1,
                "source_state": "blocked",
                "upstream_calls": 0,
            }
        if (
            not deferred_kind
            or result.get("partition_deferred")
            != {"version": 1, "kind": deferred_kind}
            or result.get("status") != "possibly_truncated"
        ):
            raise ValueError(
                "Unsupported deferred identifier partition; evidence preserved"
            )
        try:
            max_new_jobs = (
                config.get("plan_jobs_per_tick", 2000)
                if job["api_name"] == "eco_cal"
                else None
            )
            split = self.split_request(
                row, job, result, max_new_jobs=max_new_jobs
            )
            if not split or not split.get("remaining_observed_values"):
                result.pop("partition_deferred")
            if split:
                result["split"] = split
            else:
                result["partition_error"] = "no_legal_identifier_children"
            self.db.execute(
                "UPDATE jobs SET state=?,result=? WHERE id=?",
                (
                    "split_pending"
                    if split and not result.get("normalization_error")
                    else "blocked",
                    json.dumps(result),
                    row["id"],
                ),
            )
            # Reconcile the exact parent before commit: unknown-universe evidence
            # remains a gap. The original capture attempt is never overwritten.
            self.reconcile_partitions(child_id=row["id"], deadline=deadline)
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {
            "status": (
                "partition_progress"
                if split and split.get("remaining_observed_values")
                else "partitioned"
                if split
                else "blocked"
            ),
            "job_id": row["id"],
            "split": split,
            "local_only": bool(
                split
                and split.get("method")
                in ("observed_value_fanout", "observed_futures_fanout")
            ),
            "legacy_parent_recovered": recovered_legacy,
            "discovery_family": (
                contract_for(job["api_name"]).get("saturation_fallback")
                or (
                    ECO_CAL_OBSERVED_FANOUT.get("family")
                    if job["api_name"] == "eco_cal"
                    else None
                )
            ),
            "upstream_calls": 0,
        }

    def _install_exact_task_scope(self, task_ids):
        task_ids = list(task_ids)
        if not task_ids or len(task_ids) > 5000 or len(set(task_ids)) != len(task_ids):
            raise ValueError("Exact task scope must contain 1..5000 unique task IDs")
        if any(not isinstance(task_id, str) or not task_id for task_id in task_ids):
            raise ValueError("Exact task scope contains an invalid task ID")
        self.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS exact_task_scope "
            "(task_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        self.db.execute("DELETE FROM exact_task_scope")
        self.db.executemany(
            "INSERT INTO exact_task_scope(task_id) VALUES(?)",
            ((task_id,) for task_id in task_ids),
        )
        self.db.commit()
        return len(task_ids)

    def _apply_capture_result(
        self, row, job, result, deadline, work_counts, work_seconds
    ):
        if result.get("local_daily_quota"):
            work_counts["local_quota_deferrals"] += 1
            daily = result["local_daily_quota"]
            self.daily_quota_status = daily
            self.db.execute(
                "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                ("api:" + job["api_name"], daily["retry_at"]),
            )
            self.db.execute(
                "UPDATE jobs SET state='pending' WHERE id=?", (row["id"],)
            )
            self.db.commit()
            # No HTTP, result/tries/attempt rows or inferred supplier quota.
            return False
        phase_started = time.perf_counter()
        status = result["status"]
        state = "done" if status == "sample_ok" else "quality"
        if status == "empty_unverified":
            state = "empty"
        if status in (
            "transport_error",
            "api_error",
            "invalid_response",
            "rate_limited",
        ):
            state = "blocked" if row["tries"] >= 4 else "pending"
        if status == "rate_limited":
            state = "pending"  # A quota wait is not a terminal data failure.
            scoped = result.get("rate_limit_api") == job["api_name"]
            scope = "api:" + job["api_name"] if scoped else "account"
            cooldown = result.get("rate_limit_window_seconds", 60) if scoped else 60
            self.db.execute(
                "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                (scope, time.time() + cooldown),
            )
            if scoped:
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'rate_limit_observed',?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                    (
                        "quota:" + job["api_name"],
                        utc_now(),
                        json.dumps(
                            {
                                "window_seconds": cooldown,
                                "requests": result["rate_limit_requests"],
                                "interval_seconds": cooldown
                                / result["rate_limit_requests"],
                            }
                        ),
                    ),
                )
        if status in (
            "sample_ok",
            "schema_gap",
            "invalid_values",
            "possibly_truncated",
            "empty_unverified",
        ) and not result.get("supplier_empty_hint"):
            # An explicit supplier no-data error stops duplicate retries,
            # but its nonzero business code does not prove API availability.
            scope = job["api_name"] + ":" + str(job["params"].get("src", ""))
            previous_capability = self.db.execute(
                "SELECT status FROM capability WHERE scope=?", (scope,)
            ).fetchone()
            if previous_capability and previous_capability[0] == "permission_denied":
                recovered = self.db.execute(
                    "UPDATE jobs SET state='pending',retry_after=0 "
                    "WHERE state='permission_blocked' "
                    "AND json_extract(job,'$.api_name')=? "
                    "AND COALESCE(json_extract(job,'$.params.src'),'')=?",
                    (job["api_name"], str(job["params"].get("src", ""))),
                ).rowcount
                result["permission_recovery"] = {
                    "scope": scope,
                    "requeued_jobs": recovered,
                    "trigger_status": status,
                }
            elif previous_capability and previous_capability[0] == "api_unavailable":
                recovered = self.db.execute(
                    "UPDATE jobs SET state='pending',retry_after=0 "
                    "WHERE state='blocked' "
                    "AND json_extract(job,'$.api_name')=? "
                    "AND COALESCE(json_extract(job,'$.params.src'),'')=? "
                    "AND (result IS NULL OR json_extract(result,'$.status')='api_error')",
                    (job["api_name"], str(job["params"].get("src", ""))),
                ).rowcount
                result["api_unavailable_recovery"] = {
                    "scope": scope,
                    "requeued_jobs": recovered,
                    "trigger_status": status,
                }
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                (
                    scope,
                    "available",
                    utc_now(),
                    status,
                ),
            )
        if (
            status == "api_error"
            and result.get("code") == 40101
            and result.get("supplier_api_unavailable") is True
        ):
            state = "blocked"
            scope = job["api_name"] + ":" + str(job["params"].get("src", ""))
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,"
                "checked_at=excluded.checked_at,reason=excluded.reason",
                (
                    scope,
                    "api_unavailable",
                    utc_now(),
                    json.dumps(
                        {
                            "supplier_code": 40101,
                            "evidence": "current_raw_response",
                            "object_sha256": result.get("object_sha256"),
                            "observation": result.get("observation"),
                        },
                        sort_keys=True,
                    ),
                ),
            )
            self.db.execute(
                "UPDATE jobs SET state='blocked' WHERE state='pending' AND id<>? "
                "AND json_extract(job,'$.api_name')=? "
                "AND COALESCE(json_extract(job,'$.params.src'),'')=?",
                (row["id"], job["api_name"], str(job["params"].get("src", ""))),
            )
        if status == "permission_denied":
            state = "permission_blocked"
            scope = job["api_name"] + ":" + str(job["params"].get("src", ""))
            self.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                (
                    scope,
                    "permission_denied",
                    utc_now(),
                    "upstream_permission_denied",
                ),
            )
            self.db.execute(
                "UPDATE jobs SET state='permission_blocked' WHERE state='pending' AND id<>? AND json_extract(job,'$.api_name')=? AND COALESCE(json_extract(job,'$.params.src'),'')=?",
                (row["id"], job["api_name"], str(job["params"].get("src", ""))),
            )
        spec = contract_for(job["api_name"])
        pagination = _pagination_for_params(spec, job["params"])
        if status == "possibly_truncated" and not pagination:
            state = "blocked"
            if self.identifier_split_needs_discovery(
                job, epoch=row["epoch"]
            ):
                # Commit capture/normalization/attempt below before any full
                # discovery scan. A resumed parent never repeats its HTTP call.
                result["partition_deferred"] = {
                    "version": 1,
                    "kind": "identifier_fanout",
                }
                state = "split_pending"
            else:
                split = self.split_request(row, job, result)
                if split:
                    result["split"] = split
                    state = "split_pending"
        if job["api_name"] == "fund_adj":
            pagination = {"offset_param": "offset", "limit_param": "limit"}
        if pagination:
            offset_key, limit_key = (
                pagination["offset_param"],
                pagination["limit_param"],
            )
            params = job["params"]
            offset, limit = int(params.get(offset_key, 0)), int(params[limit_key])
            count = result.get("row_count", 0)
            if count >= limit:
                previous = self.db.execute(
                    "SELECT job,result FROM jobs WHERE result IS NOT NULL AND id<>? AND epoch=? AND json_extract(job,'$.api_name')=?",
                    (row["id"], row["epoch"], job["api_name"]),
                )
                base = {k: v for k, v in params.items() if k != offset_key}
                repeated = any(
                    {
                        k: v
                        for k, v in json.loads(x["job"])["params"].items()
                        if k != offset_key
                    }
                    == base
                    and json.loads(x["result"]).get("object_sha256")
                    == result.get("object_sha256")
                    for x in previous
                )
                if count != limit or repeated:
                    state = "blocked"
                    result["pagination_error"] = (
                        "row_cap_mismatch" if count != limit else "repeated_page"
                    )
                else:
                    self.enqueue(
                        job["api_name"],
                        {**params, offset_key: offset + limit},
                        row["priority"],
                        row["epoch"],
                    )
                    state = (
                        "done"
                        if status in ("sample_ok", "possibly_truncated")
                        else "quality"
                    )
            elif count < limit and status in (
                "sample_ok",
                "empty_unverified",
            ):
                if offset > 0:
                    state = "done"
                result["pagination_end"] = True
        if result.get("row_count", 0) and status not in (
            "invalid_response",
            "api_error",
            "permission_denied",
        ):
            try:
                result = self.normalize(result)
            except Exception as exc:
                # Split children independently normalize the exact covered
                # partitions, so a parent conversion failure must not strand
                # their already-durable completeness obligation.
                state = (
                    "split_pending"
                    if result.get("partition_deferred") or result.get("split")
                    else "blocked"
                )
                result["normalization_error"] = type(exc).__name__
        self.db.execute(
            "INSERT OR IGNORE INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (row["id"], row["tries"] + 1, json.dumps(result)),
        )
        self.db.execute(
            "UPDATE jobs SET state=?,result=?,tries=tries+1,retry_after=? WHERE id=?",
            (
                state,
                json.dumps(result),
                time.time() + min(3600, 60 * 2 ** row["tries"]),
                row["id"],
            ),
        )
        self.db.commit()  # response + object references checkpoint before next request
        self.reconcile_partitions(child_id=row["id"], deadline=deadline)
        work_seconds["result_processing"] += time.perf_counter() - phase_started
        return True

    def run(
        self,
        client,
        token,
        config,
        max_requests=100,
        max_seconds=100,
        pause=0.6,
        *,
        task_ids=None,
    ):
        started = time.monotonic()
        deadline = started + max_seconds
        work_seconds = {
            "partition_work": 0.0,
            "partition_reconciliation": 0.0,
            "queue_expansion": 0.0,
            "job_selection": 0.0,
            "capture": 0.0,
            "result_processing": 0.0,
        }
        work_counts = {
            "capture_invocations": 0,
            "dispatch_rejections": 0,
            "local_quota_deferrals": 0,
        }
        self._selection_profile = {
            "seconds": {
                "account_gate_requested_sleep": 0.0,
                "account_gate_sleep": 0.0,
                "empty_queue_sleep": 0.0,
                "gate_reservation_commit": 0.0,
            },
            "counts": {
                "account_gate_sleeps": 0,
                "empty_queue_sleeps": 0,
                "gate_reservations": 0,
            },
        }

        def work_timing():
            return {
                "seconds": {
                    name: round(value, 6)
                    for name, value in work_seconds.items()
                },
                "counts": dict(work_counts),
                "job_selection_detail": {
                    "seconds": {
                        name: round(value, 6)
                        for name, value in self._selection_profile[
                            "seconds"
                        ].items()
                    },
                    "counts": dict(self._selection_profile["counts"]),
                },
            }

        task_scope = task_ids is not None
        scoped_jobs = self._install_exact_task_scope(task_ids) if task_scope else 0
        phase_started = time.perf_counter()
        partition_work = (
            None if task_scope else self.resume_identifier_split(deadline, config)
        )
        work_seconds["partition_work"] += time.perf_counter() - phase_started
        if partition_work is not None:
            # Full discovery remains isolated. Proven source projections may
            # use only the unspent original deadline for unrelated acquisition.
            # Observed-value partitions read only the retained parent object,
            # so they can continue into acquisition without a discovery scan.
            if (
                not partition_work.get("local_only")
                and (
                    partition_work.get("discovery_family")
                    not in IDENTIFIER_SPLIT_SOURCE_APIS
                    or time.monotonic() >= deadline
                )
            ):
                return {
                    "requests": 0,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "partition_work": partition_work,
                    "work_timing": work_timing(),
                    **self.status(),
                }
        if not task_scope:
            reconciliation_parents = config.get(
                "reconciliation_parents_per_tick", 64
            )
            if (
                type(reconciliation_parents) is not int
                or not 1 <= reconciliation_parents <= 1000
            ):
                raise ValueError("Invalid partition reconciliation budget")
            resolved_audit_parents = config.get(
                "reconciliation_resolved_audit_per_tick",
                min(4, reconciliation_parents),
            )
            if (
                type(resolved_audit_parents) is not int
                or not 0 <= resolved_audit_parents <= reconciliation_parents
            ):
                raise ValueError("Invalid resolved partition audit budget")
            phase_started = time.perf_counter()
            try:
                empty_reconciliation = {
                    "checked": 0,
                    "resolved": 0,
                    "changed": 0,
                    "newly_resolved": 0,
                    "reaffirmed_resolved": 0,
                }
                open_parents = reconciliation_parents - resolved_audit_parents
                open_report = (
                    self.reconcile_partitions(
                        max_parents=open_parents,
                        deadline=deadline,
                        parent_state="split_pending",
                    )
                    if open_parents
                    else dict(empty_reconciliation)
                )
                audit_report = (
                    self.reconcile_partitions(
                        max_parents=resolved_audit_parents,
                        deadline=deadline,
                        parent_state="resolved",
                    )
                    if resolved_audit_parents
                    and time.monotonic() < deadline
                    else dict(empty_reconciliation)
                )
                partition_reconciliation = {
                    name: open_report[name] + audit_report[name]
                    for name in empty_reconciliation
                }
                partition_reconciliation.update(
                    split_pending=open_report, resolved_audit=audit_report
                )
            finally:
                work_seconds["partition_reconciliation"] += (
                    time.perf_counter() - phase_started
                )
        else:
            partition_reconciliation = None
        pipeline_depth = config.get("acquisition_pipeline_depth", 1)
        if type(pipeline_depth) is not int or not 1 <= pipeline_depth <= 4:
            raise ValueError("Invalid acquisition pipeline depth")
        capture_execution = config.get("acquisition_capture_execution", "thread")
        if capture_execution not in ("thread", "process"):
            raise ValueError("Invalid acquisition capture execution")
        capture_workers = config.get("acquisition_capture_workers", 1)
        if type(capture_workers) is not int or not 1 <= capture_workers <= 4:
            raise ValueError("Invalid acquisition capture workers")
        if capture_execution == "process" and pipeline_depth == 1:
            raise ValueError("Process capture requires pipeline depth above one")
        if capture_workers > 1 and capture_execution != "process":
            raise ValueError("Concurrent capture requires process execution")
        if capture_workers > pipeline_depth:
            raise ValueError("Capture workers exceed pipeline depth")
        completed = 0
        invalid_requests = 0

        def select_dispatch(mark_inflight):
            nonlocal invalid_requests
            while time.monotonic() < deadline:
                if not task_scope:
                    phase_started = time.perf_counter()
                    try:
                        self.expand(config)
                    finally:
                        work_seconds["queue_expansion"] += (
                            time.perf_counter() - phase_started
                        )
                if time.monotonic() >= deadline:
                    return None
                phase_started = time.perf_counter()
                try:
                    row = self.next_job(
                        config,
                        deadline,
                        task_scope=task_scope,
                        mark_inflight=mark_inflight,
                    )
                finally:
                    work_seconds["job_selection"] += (
                        time.perf_counter() - phase_started
                    )
                if row is None:
                    return None
                if time.monotonic() >= deadline:
                    if mark_inflight:
                        self.db.execute(
                            "UPDATE jobs SET state='pending' WHERE id=?", (row["id"],)
                        )
                        self.db.commit()
                    return None
                job = json.loads(row["job"])
                try:
                    validate_request_shape(job)
                except ValueError as error:
                    # Old planner jobs keep their request/result/attempt identities.
                    # Corrected contract policies replay the configured date scope;
                    # this local rejection is an explicit gap, never a data success.
                    with self.db:
                        self.db.execute(
                            "UPDATE jobs SET state='blocked' WHERE id=?",
                            (row["id"],),
                        )
                        self.db.execute(
                            "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                            "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                            (
                                "dispatch:" + row["id"],
                                "request_contract_blocked",
                                utc_now(),
                                json.dumps({
                                    "api_name": job["api_name"],
                                    "reason": str(error),
                                    "upstream_calls": 0,
                                    "coverage_proven": False,
                                }),
                            ),
                        )
                    invalid_requests += 1
                    continue
                rejected = realtime_dispatch_status(
                    job["api_name"], row["epoch"], config, time.time()
                )
                if rejected:
                    work_counts["dispatch_rejections"] += 1
                    self.db.execute(
                        "UPDATE jobs SET state=? WHERE id=?", (rejected, row["id"])
                    )
                    self.db.execute(
                        "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                        "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                        (
                            "dispatch:" + row["id"],
                            rejected,
                            utc_now(),
                            json.dumps(
                                {
                                    "api_name": job["api_name"],
                                    "epoch": row["epoch"],
                                    "reason": rejected,
                                    "upstream_calls": 0,
                                }
                            ),
                        ),
                    )
                    self.db.commit()
                    continue
                return row, job
            return None

        def timed_capture(job):
            phase_started = time.perf_counter()
            result = capture_sample(client, token, job, self.root)
            return result, time.perf_counter() - phase_started

        def record_capture(future_result):
            result, capture_seconds = future_result
            work_seconds["capture"] += capture_seconds
            work_counts["capture_invocations"] += 1
            return result

        if pipeline_depth == 1:
            while completed < max_requests and time.monotonic() < deadline:
                selected = select_dispatch(False)
                if selected is None:
                    break
                row, job = selected
                result = record_capture(timed_capture(job))
                if self._apply_capture_result(
                    row, job, result, deadline, work_counts, work_seconds
                ):
                    completed += 1
                if pause:
                    time.sleep(pause)
        else:
            pending_captures = []
            dispatch_open = True
            high_watermark = 0
            if capture_execution == "process":
                from backend.shared import tushare_intake

                pool = ProcessPoolExecutor(
                    max_workers=capture_workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_initialize_capture_process,
                    initargs=(token, str(self.root), tushare_intake.API_ROOT),
                )
                capture_callable = _capture_in_process
            else:
                pool = ThreadPoolExecutor(
                    max_workers=capture_workers, thread_name_prefix="tushare-capture"
                )
                capture_callable = timed_capture
            with pool:
                while completed < max_requests and (dispatch_open or pending_captures):
                    while (
                        dispatch_open
                        and len(pending_captures) < pipeline_depth
                        and completed + len(pending_captures) < max_requests
                        and time.monotonic() < deadline
                    ):
                        selected = select_dispatch(True)
                        if selected is None:
                            dispatch_open = False
                            break
                        row, job = selected
                        pending_captures.append(
                            (row, job, pool.submit(capture_callable, job))
                        )
                        high_watermark = max(high_watermark, len(pending_captures))
                    if not pending_captures:
                        break
                    done, _ = wait(
                        (item[2] for item in pending_captures),
                        return_when=FIRST_COMPLETED,
                    )
                    finished = next(
                        item for item in pending_captures if item[2] in done
                    )
                    pending_captures.remove(finished)
                    row, job, future = finished
                    result = record_capture(future.result())
                    if self._apply_capture_result(
                        row, job, result, deadline, work_counts, work_seconds
                    ):
                        completed += 1
                    if pause:
                        time.sleep(pause)
            work_timing_pipeline = {
                "depth": pipeline_depth,
                "http_workers": capture_workers,
                "capture_execution": capture_execution,
                "completion_order": "first_completed",
                "queue_high_watermark": high_watermark,
                "crash_recovered_jobs": self.recovered_inflight,
            }
        if not task_scope and time.monotonic() < deadline:
            phase_started = time.perf_counter()
            try:
                self.expand(config)
            finally:
                work_seconds["queue_expansion"] += (
                    time.perf_counter() - phase_started
                )
        report = {
            "requests": completed,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "work_timing": work_timing(),
            **self.status(),
        }
        if pipeline_depth > 1:
            report["acquisition_pipeline"] = work_timing_pipeline
        if partition_work is not None:
            report["partition_work"] = partition_work
        if partition_reconciliation is not None:
            report["partition_reconciliation"] = partition_reconciliation
        if invalid_requests:
            report["invalid_requests_blocked"] = invalid_requests
        if task_scope:
            report.update(exact_task_scope=True, scoped_jobs=scoped_jobs)
        return report

    def register_documents(self, max_observations=20, *, max_records=500, max_seconds=5):
        from backend.shared.tushare_documents import enqueue_documents

        if (
            type(max_observations) is not int
            or not 0 <= max_observations <= 1000
        ):
            raise ValueError("Invalid document observation limit")
        if (
            type(max_records) is not int
            or not 1 <= max_records <= MAX_DOCUMENT_REGISTRATION_RECORDS
        ):
            raise ValueError("Invalid document record limit")
        if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 90:
            raise ValueError("Invalid document registration budget")
        started = time.monotonic()
        deadline = started + max_seconds
        apis = {
            api: spec["attachment_fields"]
            for api, spec in EXTENDED_CONTRACTS.items()
            if spec.get("attachment_fields")
        }
        report = {
            "budget": {
                "max_observations": max_observations,
                "max_records": max_records,
                "max_seconds": max_seconds,
                "chunk_records": DOCUMENT_REGISTRATION_CHUNK_RECORDS,
            },
            "observations": 0,
            "processed_records": 0,
            "scanned_attempts": 0,
            "status": "bounded_batch_complete",
            "cursor": None,
            "partial_attempt": None,
            "record_offset": 0,
        }
        if not apis:
            report.update(status="no_attachment_apis", elapsed_seconds=0.0)
            return report
        prefix = "document_offset:"
        original_timeout = self.db.execute("PRAGMA busy_timeout").fetchone()[0]
        self.db.execute("PRAGMA busy_timeout=50")
        self.db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)

        def checkpoint(cursor, partial=None, offset=0):
            # Docs commit first. A failed pipeline checkpoint simply replays the
            # same deterministic reference IDs; no committed row is skipped.
            self.db.set_progress_handler(None, 0)
            with self.db:
                self.db.execute(
                    "INSERT INTO scheduler_state(name,value) VALUES('document_cursor',?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (cursor,),
                )
                self.db.execute(
                    "DELETE FROM scheduler_state WHERE name GLOB 'document_offset:*'"
                )
                if partial is not None:
                    self.db.execute(
                        "INSERT INTO scheduler_state(name,value) VALUES(?,?)",
                        (partial, offset),
                    )
            report.update(
                cursor=cursor,
                partial_attempt=int(partial.split(":")[1]) if partial else None,
                record_offset=offset if partial else 0,
            )
            self.db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)

        try:
            last = self.db.execute(
                "SELECT value FROM scheduler_state WHERE name='document_cursor'"
            ).fetchone()
            cursor = last[0] if last else 0
            saved = self.db.execute(
                "SELECT name,value FROM scheduler_state WHERE name GLOB 'document_offset:*'"
            ).fetchall()
            if type(cursor) is not int or cursor < 0 or len(saved) > 1:
                raise ValueError("Invalid document registration checkpoint")
            partial = saved[0]["name"] if saved else None
            offset = saved[0]["value"] if saved else 0
            if partial and (
                not re.fullmatch(r"document_offset:[1-9][0-9]*:[a-f0-9]{64}", partial)
                or type(offset) is not int
                or offset < 0
                or int(partial.split(":")[1]) <= cursor
            ):
                raise ValueError("Invalid partial document checkpoint")
            report.update(
                cursor=cursor,
                partial_attempt=int(partial.split(":")[1]) if partial else None,
                record_offset=offset,
            )
            def attempt_rows():
                """Page the contiguous attempt tail within the existing hard budget."""
                scan_after = cursor
                while True:
                    if (
                        time.monotonic() >= deadline
                        or report["observations"] >= max_observations
                        or report["processed_records"] >= max_records
                    ):
                        report["status"] = "deferred_budget"
                        return
                    rows = self.db.execute(
                        "SELECT rowid,result FROM attempts "
                        "WHERE rowid>? ORDER BY rowid LIMIT 1000",
                        (scan_after,),
                    ).fetchall()
                    if not rows:
                        if partial:
                            raise ValueError("Partial document attempt is missing")
                        return
                    yield from rows
                    if cursor != report["cursor"]:
                        checkpoint(cursor, partial, offset)
                    scan_after = rows[-1]["rowid"]

            for row in attempt_rows():
                if (
                    time.monotonic() >= deadline
                    or report["observations"] >= max_observations
                    or report["processed_records"] >= max_records
                ):
                    report["status"] = "deferred_budget"
                    break
                result = json.loads(row["result"])
                report["scanned_attempts"] += 1
                if partial and int(partial.split(":")[1]) < row["rowid"]:
                    raise ValueError("Partial document attempt is missing")
                eligible = (
                    result.get("api_name") in apis
                    and result.get("observation")
                    and result.get("object_sha256")
                )
                if not eligible:
                    if partial and int(partial.split(":")[1]) == row["rowid"]:
                        raise ValueError("Partial document source changed")
                    cursor = row["rowid"]
                    continue
                fields = apis[result["api_name"]]
                key = (
                    prefix + str(row["rowid"]) + ":" + digest(json_bytes([result, fields]))
                )
                if partial and partial != key:
                    raise ValueError("Partial document identity changed")
                records = self.records(result)
                if offset > len(records):
                    raise ValueError("Partial document offset exceeds source")
                while True:
                    if (
                        time.monotonic() >= deadline
                        or report["processed_records"] >= max_records
                    ):
                        checkpoint(cursor, key, offset)
                        report["status"] = "deferred_budget"
                        return report
                    chunk = records[
                        offset : offset
                        + min(
                            DOCUMENT_REGISTRATION_CHUNK_RECORDS,
                            max_records - report["processed_records"],
                        )
                    ]
                    done = enqueue_documents(
                        self.root,
                        result["observation"],
                        result["api_name"],
                        chunk,
                        fields,
                        deadline=deadline,
                    )
                    offset += done["processed_records"]
                    report["processed_records"] += done["processed_records"]
                    complete = done["complete"] and offset == len(records)
                    if complete:
                        cursor = row["rowid"]
                        checkpoint(cursor)
                        partial, offset = None, 0
                        report["observations"] += 1
                        break
                    checkpoint(cursor, key, offset)
                    partial = key
                    if not done["complete"]:
                        report["status"] = done["status"]
                        return report
                del records
            if cursor != report["cursor"]:
                checkpoint(cursor, partial, offset)
            return report
        except sqlite3.OperationalError as exc:
            if not (
                str(exc) == "interrupted"
                or str(exc).startswith(
                    (
                        "database is locked",
                        "database table is locked",
                        "database schema is locked",
                    )
                )
            ):
                raise
            self.db.set_progress_handler(None, 0)
            self.db.rollback()
            report["status"] = (
                "deferred_budget" if str(exc) == "interrupted" else "deferred_database_busy"
            )
            report["checkpoint_pending"] = True
            return report
        finally:
            self.db.set_progress_handler(None, 0)
            self.db.execute("PRAGMA busy_timeout=" + str(original_timeout))
            report["elapsed_seconds"] = round(max(0, time.monotonic() - started), 6)

    def status(self):
        return {
            r[0]: r[1]
            for r in self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state")
        }

    def blocked_obligations(self):
        return blocked_obligations_status(self.db)

    def _publication_intent(self, release_id):
        """Commit identity before exposing CURRENT; caller holds pipeline.lock."""
        if not re.fullmatch(r"data-[a-f0-9]{64}", release_id):
            raise ValueError("Invalid publication intent identity")
        started_at = int(time.time())
        if started_at < 0:
            raise ValueError("Invalid publication intent time")
        with self.db:
            self.db.execute("DELETE FROM scheduler_state WHERE name GLOB 'publish_intent:*'")
            self.db.execute(
                "INSERT INTO scheduler_state(name,value) VALUES(?,?)",
                ("publish_intent:" + release_id, started_at),
            )

    def _publication_success(self, release_id, successful_at):
        """Checkpoint a caller-verified CURRENT; no filesystem mtime inference."""
        pointer = self.root / "CURRENT.json"
        if pointer.is_symlink():
            raise ValueError("Unsafe current pointer")
        current = json.loads(pointer.read_bytes())
        if (
            not re.fullmatch(r"data-[a-f0-9]{64}", release_id)
            or current.get("release_id") != release_id
            or current.get("manifest_sha256") != release_id[5:]
            or type(successful_at) is not int
            or successful_at < 0
        ):
            raise ValueError("Publication identity changed before checkpoint")
        with self.db:
            self.db.execute(
                "INSERT INTO scheduler_state(name,value) VALUES('publish_success_at',?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (successful_at,),
            )
            self.db.execute("DELETE FROM scheduler_state WHERE name GLOB 'publish_success:*'")
            self.db.execute(
                "INSERT INTO scheduler_state(name,value) VALUES(?,?)",
                ("publish_success:" + release_id, successful_at),
            )
            self.db.execute("DELETE FROM scheduler_state WHERE name GLOB 'publish_intent:*'")

    def publish(self):
        from contextlib import contextmanager

        publish_started = time.monotonic()
        timing = self.publish_timing = {
            "stage_seconds": {},
            "completed_stages": [],
            "failed_stage": None,
        }

        @contextmanager
        def measure(name):
            started = time.monotonic()
            try:
                yield
            except BaseException:
                timing["failed_stage"] = name
                raise
            else:
                timing["completed_stages"].append(name)
            finally:
                finished = time.monotonic()
                timing["stage_seconds"][name] = max(0.0, finished - started)
                timing["total_elapsed_seconds"] = max(0.0, finished - publish_started)

        with measure("read_current"):
            previous_id, previous = None, None
            pointer = self.root / "CURRENT.json"
            if pointer.exists():
                previous_id = json.loads(pointer.read_bytes())["release_id"]
                if previous_id.startswith("data-"):
                    previous = manifest_at(self.root, previous_id)

        def preserve_release_mapping(archive):
            known = (
                ((previous or {}).get("archive") or {})
                .get("recovery", {})
                .get("archived_releases", [])
            )
            if not known:
                return archive
            archive = archive or {
                "gaps": [],
                "recovery": {"status": "not_started", "historical_complete": False},
            }
            recovery = dict(archive["recovery"])
            mappings = {}
            for item in known + recovery.get("archived_releases", []):
                key = item["release_id"]
                if key in mappings and mappings[key] != item:
                    raise ValueError("Conflicting archived release mapping")
                mappings[key] = item
            recovery["archived_releases"] = [mappings[key] for key in sorted(mappings)]
            return {**archive, "recovery": recovery}

        with measure("scan_gaps"):
            files = dict(previous["files"]) if previous else {}
            active, gaps = {}, []
            for row in self.db.execute(
                "SELECT * FROM jobs "
                "WHERE state NOT IN ('done','pending','superseded') ORDER BY rowid"
            ):
                result = json.loads(row["result"]) if row["result"] else {}
                if row["state"] not in ("done", "pending", "resolved"):
                    gaps.append(
                        {
                            "id": row["id"],
                            "state": row["state"],
                            "api_name": json.loads(row["job"])["api_name"],
                            "params": json.loads(row["job"])["params"],
                            "assessment": result.get("status"),
                        }
                    )
        with measure("scan_attempts_and_stat"):
            # Repeated attempts and prior revisions remain queryable in the latest
            # release; migration can recover only the attempts v1 had retained.
            timing["attempt_scan"] = _scan_attempt_artifacts(
                self.root,
                self.db.execute(
                    "SELECT result FROM attempts ORDER BY job_id,attempt"
                ),
                files,
                active,
            )
        with measure("contract_reassessment_overlays"):
            for row in self.db.execute(
                "SELECT result FROM contract_reassessments ORDER BY job_id"
            ):
                result = json.loads(row[0])
                parquet = result.get("parquet")
                reassessment = result.get("contract_reassessment")
                retirement = result.get("capability_probe_retirement")
                annotation = "contract_reassessment"
                marker = reassessment
                if reassessment is None and isinstance(retirement, dict):
                    capability = retirement.get("capability")
                    production = retirement.get("production_plan")
                    if (
                        retirement.get("version") != 1
                        or retirement.get("previous_state") != "quality"
                        or retirement.get("previous_status") != result.get("status")
                        or retirement.get("reason")
                        != "non_authoritative_capability_probe"
                        or retirement.get("source_attempt_preserved") is not True
                        or retirement.get("artifact_evidence_preserved") is not True
                        or retirement.get("coverage_proven") is not False
                        or retirement.get("upstream_calls") != 0
                        or not isinstance(capability, dict)
                        or capability.get("status") != "available"
                        or not isinstance(capability.get("checked_at"), str)
                        or not capability["checked_at"]
                        or not isinstance(production, dict)
                        or type(production.get("jobs")) is not int
                        or production["jobs"] < 1
                        or type(production.get("attempted_jobs")) is not int
                        or not 1 <= production["attempted_jobs"] <= production["jobs"]
                    ):
                        raise ValueError("Invalid capability probe retirement overlay")
                    annotation = "capability_probe_retirement"
                    marker = retirement
                if (
                    not isinstance(parquet, dict)
                    or parquet.get("path") not in active
                    or not isinstance(marker, dict)
                    or (
                        annotation == "contract_reassessment"
                        and marker.get("reassessed_status") != result.get("status")
                    )
                    or marker.get("upstream_calls") != 0
                    or (reassessment is not None and retirement is not None)
                ):
                    raise ValueError("Invalid contract reassessment overlay")
                dataset = active[parquet["path"]]
                if dataset["api_name"] != result.get("api_name"):
                    raise ValueError("Contract reassessment API mismatch")
                dataset["quality_state"] = result["status"]
                dataset[annotation] = marker
        with measure("normalization_recovery_overlays"):
            for row in self.db.execute(
                "SELECT r.job_id,r.normalizer_sha256,r.result,j.job,j.state,"
                "j.result AS job_result FROM normalization_recoveries r "
                "JOIN jobs j ON j.id=r.job_id ORDER BY r.job_id"
            ):
                result = json.loads(row["result"])
                marker = result.get("normalization_recovery")
                parquet = result.get("parquet")
                job = json.loads(row["job"])
                if (
                    row["state"] != "done"
                    or row["job_result"] != row["result"]
                    or not isinstance(marker, dict)
                    or marker.get("recovered_status") != result.get("status")
                    or marker.get("normalizer_sha256") != row["normalizer_sha256"]
                    or marker.get("source_attempt_preserved") is not True
                    or marker.get("upstream_calls") != 0
                    or result.get("status") != "sample_ok"
                    or result.get("api_name") != job.get("api_name")
                    or not isinstance(parquet, dict)
                ):
                    raise ValueError("Invalid normalization recovery overlay")
                relative = parquet.get("path")
                sha = parquet.get("sha256")
                size = parquet.get("bytes")
                if (
                    not isinstance(relative, str)
                    or not re.fullmatch(r"parquet/[a-f0-9]{64}\.parquet", relative)
                    or sha != Path(relative).stem
                    or type(size) is not int
                    or size <= 0
                ):
                    raise ValueError("Invalid normalization recovery artifact")
                artifact = self.root / relative
                if (
                    artifact.is_symlink()
                    or not artifact.is_file()
                    or artifact.stat().st_size != size
                    or digest(artifact.read_bytes()) != sha
                ):
                    raise ValueError("Normalization recovery artifact mismatch")
                source = self.db.execute(
                    "SELECT 1 FROM attempts WHERE job_id=? "
                    "AND json_extract(result,'$.normalization_error')=? LIMIT 1",
                    (row["job_id"], marker.get("previous_error")),
                ).fetchone()
                if source is None:
                    raise ValueError("Normalization recovery source attempt missing")
                files[relative] = {"sha256": sha, "bytes": size}
                active[relative] = {
                    "api_name": result["api_name"],
                    "quality_state": result["status"],
                    **parquet,
                    "normalization_recovery": marker,
                }
        with measure("schema_metadata"):
            # Ship the reviewed catalog/contract field definitions with every pinned
            # release; code availability must not substitute for offline metadata.
            metadata = {"catalog": self.catalog, "contracts": EXTENDED_CONTRACTS}
            raw = json_bytes(metadata)
            schema_name = "schemas/" + digest(raw) + ".json"
            if not (self.root / schema_name).exists():
                atomic_bytes(self.root / schema_name, raw)
            files[schema_name] = {"sha256": digest(raw), "bytes": len(raw)}
        with measure("archive_inventory_before"):
            archive = None
            self_archive_verified = False
            if (self.root / "archive.sqlite").exists():
                from backend.shared.tushare_archive import archive_inventory

                archived = archive_inventory(self.root)
                self_archive_verified = bool(
                    previous_id
                    and "archives/" + previous_id.removeprefix("data-") + ".json"
                    in archived["files"]
                )
                files.update(archived["files"])
                for dataset in archived["datasets"]:
                    active.setdefault(dataset["path"], dataset)
                archive = {"recovery": archived["recovery"], "gaps": archived["gaps"]}
        with measure("document_index"):
            documents = None
            if (self.root / "documents.sqlite").exists():
                from backend.shared.tushare_documents import document_index

                inventory = document_index(self.root)
                for item in inventory["files"]:
                    files[item["path"]] = {"sha256": item["sha256"], "bytes": item["bytes"]}
                documents = {
                    "path": inventory["path"],
                    "schema_version": inventory["schema_version"],
                    "counts": inventory["counts"],
                    "reference_counts": inventory["reference_counts"],
                    "totals": inventory["totals"],
                }
                del inventory
        with measure("metadata_inventory"):
            # Retain prior immutable metadata versions as well as the current index.
            # A fresh Mac must not depend on having mirrored every earlier release.
            for family in ("documents", "schemas", "archives"):
                if (self.root / family).is_symlink():
                    raise ValueError("Unsafe immutable metadata directory")
                for path in (self.root / family).glob("*.json"):
                    if not re.fullmatch(r"[a-f0-9]{64}", path.stem):
                        continue
                    if path.is_symlink():
                        raise ValueError("Unsafe immutable metadata symlink")
                    files[path.relative_to(self.root).as_posix()] = {
                        "sha256": path.stem,
                        "bytes": path.stat().st_size,
                    }
        with measure("coverage_and_closure"):
            # One complete aggregation also supplies status totals and scope.
            # SQL ordering preserves DISTINCT's SQLite ordering, including NULL
            # and unknown API names; no fixed state/API allowlist can omit gaps.
            coverage_by_api = [
                dict(r)
                for r in self.db.execute(
                    "SELECT json_extract(job, '$.api_name') AS api_name,state,count(*) AS partitions FROM jobs GROUP BY api_name,state ORDER BY api_name,state"
                )
            ]
            coverage = {}
            scope = []
            for row in coverage_by_api:
                state = row["state"]
                coverage[state] = coverage.get(state, 0) + row["partitions"]
                if not scope or scope[-1] != row["api_name"]:
                    scope.append(row["api_name"])
            content = {
                "schema_version": 1,
                "files": files,
                "datasets": list(active.values()),
                "coverage": coverage,
                "coverage_by_api": coverage_by_api,
                "gaps": gaps,
                "history_complete": False,
                "partition_closure": self.partition_inventory(),
                "rrg_status": "blocked_data",
                "scope": scope,
                "implemented_contracts": sorted(set(CONTRACTS) | set(EXTENDED_CONTRACTS)),
                "schema_path": schema_name,
                "documents": documents,
                "archive": preserve_release_mapping(archive),
                "historical_versions_complete": False,
                "retained_observations_included": True,
                "capabilities": [
                    dict(r)
                    for r in self.db.execute("SELECT * FROM capability ORDER BY scope")
                ],
                "planning": [
                    dict(r)
                    for r in self.db.execute("SELECT * FROM planning_state ORDER BY name")
                ],
                "catalogued_interfaces": len(self.catalog["entries"]),
                "unimplemented_catalog_scope": True,
            }
        with measure("compare_previous"):
            if previous:
                # A crash after retaining CURRENT must not manufacture a new release
                # solely because CURRENT's own archived manifest now exists.
                def comparable(document):
                    value = dict(document)
                    own_path = "archives/" + previous_id[5:] + ".json"
                    if own_path in document["files"]:
                        own = self.root / own_path
                        expected = document["files"][own_path]
                        if (
                            expected
                            != {"sha256": previous_id[5:], "bytes": own.stat().st_size}
                            or digest(own.read_bytes()) != previous_id[5:]
                        ):
                            raise ValueError("Invalid archived CURRENT manifest")
                    value["files"] = {
                        name: metadata
                        for name, metadata in document["files"].items()
                        if name != own_path
                    }
                    archive = document.get("archive")
                    if archive:
                        archive = {**archive, "recovery": dict(archive["recovery"])}
                        recovery = archive["recovery"]
                        releases = recovery.get("archived_releases", [])
                        retained = [r for r in releases if r["release_id"] != previous_id]
                        if len(retained) != len(releases):
                            recovery["archived_releases"] = retained
                            if any(
                                r
                                != {
                                    "release_id": previous_id,
                                    "path": own_path,
                                    "sha256": previous_id[5:],
                                }
                                for r in releases
                                if r["release_id"] == previous_id
                            ):
                                raise ValueError("Invalid archived CURRENT mapping")
                        if self_archive_verified and own_path in document["files"]:
                            recovery["files"] -= 1
                        if archive == {
                            "gaps": [],
                            "recovery": {
                                "status": "not_started",
                                "remaining": 0,
                                "tasks": 0,
                                "files": 0,
                                "open_gaps": 0,
                                "scan_count": 0,
                                "historical_complete": False,
                                "archived_releases": [],
                            },
                        }:
                            archive = None
                        value["archive"] = archive
                    return value

                if comparable(content) == comparable(previous):
                    # A successful no-op can also be interrupted while its large
                    # local containers are being released on function return.
                    self._publication_intent(previous_id)
                    return previous_id
        if previous_id:
            from backend.shared.tushare_archive import archive_inventory, retain_release

            with measure("retain_previous"):
                retention_timing = timing["retention"] = {}
                retained = retain_release(
                    self.root, previous_id,
                    _verified_predecessor=previous,
                    _inherited_files=files,
                    timing=retention_timing,
                )
                for name, metadata in retained["files"].items():
                    if name in files and files[name] != metadata:
                        raise ValueError("Conflicting inherited file metadata")
                    files[name] = metadata
                del retained  # Do not overlap an inherited map with JSON encoding.
            with measure("archive_inventory_after"):
                archived = archive_inventory(self.root)
                files.update(archived["files"])
                content["archive"] = preserve_release_mapping(
                    {
                        "recovery": archived["recovery"],
                        "gaps": archived["gaps"],
                    }
                )
        with measure("serialize_manifest"):
            # Comparison and the final inherited archive mapping are finished.
            # Keep needed shared file/mapping entries through content, but release
            # the old manifest's other containers before building JSON chunks.
            previous = None
            temporary, sha = serialize_manifest_file(
                self.root / "releases", content, timing.setdefault("serialization", {})
            )
            release = "data-" + sha
            destination = self.root / "releases" / release / "manifest.json"
        try:
            with measure("write_manifest"):
                if destination.is_symlink() or destination.parent.is_symlink():
                    raise ValueError("Unsafe manifest destination")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    # A retry may find its sealed manifest. Never hide a damaged
                    # existing file just because its filename has the right SHA.
                    existing = hashlib.sha256()
                    with destination.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            existing.update(chunk)
                    if existing.hexdigest() != sha:
                        raise ValueError("Existing manifest checksum mismatch")
                else:
                    temporary.replace(destination)
                # Persist the immutable file and new release directory before
                # the atomic pointer can make it visible to readers.
                for parent in (destination.parent, destination.parent.parent):
                    fd = os.open(parent, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                self._publication_intent(release)
                atomic_json(
                    self.root / "CURRENT.json", {"release_id": release, "manifest_sha256": sha}
                )
        finally:
            temporary.unlink(missing_ok=True)
        return release


def _planning_config_fingerprint(config):
    """Hash only settings that can change acquisition planning.

    Document consumption owns a separate queue and lock. Changing its bounded
    runtime controls must not consume an acquisition cycle rebuilding the same
    Tushare job plan.
    """
    planning_config = {
        key: value
        for key, value in config.items()
        if not key.startswith("document_")
        and key not in {
            "enable_documents",
            "documents_per_tick",
            "archive_worker_acquire_after_planning",
            "reconciliation_parents_per_tick",
            "reconciliation_resolved_audit_per_tick",
        }
    }
    return digest(json_bytes({"version": 2, "config": planning_config}))


PUBLISH_ATTEMPT_STAT_WORKERS = 8
PUBLISH_ATTEMPT_STAT_BATCH = 8192


def _scan_attempt_artifacts(
    root, rows, files, active, *, max_workers=None, batch_size=None
):
    """Rebuild the complete attempt inventory with bounded parallel stat calls."""
    started = time.monotonic()
    if max_workers is None:
        max_workers = PUBLISH_ATTEMPT_STAT_WORKERS
    if batch_size is None:
        batch_size = PUBLISH_ATTEMPT_STAT_BATCH
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError("max_workers must be positive")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be positive")
    pending = []
    attempts_scanned = 0
    artifacts_checked = 0
    stat_batches = 0
    stat_workers = 0

    def stat_chunk(chunk):
        return [(name, sha, (root / name).stat().st_size) for name, sha in chunk]

    def flush(pool):
        nonlocal artifacts_checked, stat_batches, stat_workers
        if not pending:
            return
        workers = min(max_workers, len(pending))
        width = (len(pending) + workers - 1) // workers
        chunks = [
            pending[start : start + width]
            for start in range(0, len(pending), width)
        ]
        results = (
            (stat_chunk(pending),)
            if workers == 1
            else pool.map(stat_chunk, chunks)
        )
        for chunk in results:
            for name, sha, size in chunk:
                files[name] = {"sha256": sha, "bytes": size}
        artifacts_checked += len(pending)
        stat_batches += 1
        stat_workers = max(stat_workers, workers)
        pending.clear()

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="tushare-publish-stat"
    ) as pool:
        for row in rows:
            attempts_scanned += 1
            result = json.loads(row[0])
            if "observation" in result:
                pending.extend(
                    (
                        (
                            "observations/" + result["observation"],
                            result["observation_sha256"],
                        ),
                        (
                            "objects/" + result["object_sha256"] + ".json",
                            result["object_sha256"],
                        ),
                    )
                )
                if "parquet" in result:
                    pending.append(
                        (result["parquet"]["path"], result["parquet"]["sha256"])
                    )
                if len(pending) >= batch_size:
                    flush(pool)
            if "parquet" in result:
                active[result["parquet"]["path"]] = {
                    "api_name": result["api_name"],
                    "quality_state": result["status"],
                    **result["parquet"],
                }
        flush(pool)
    return {
        "attempts_scanned": attempts_scanned,
        "artifacts_checked": artifacts_checked,
        "stat_batches": stat_batches,
        "stat_workers": stat_workers,
        "elapsed_seconds": max(0.0, time.monotonic() - started),
    }


def _verify_identifier_object_stats(root, objects, max_workers=8):
    """Validate every cached object fingerprint using bounded local I/O."""
    started = time.monotonic()
    items = tuple(objects.items())
    workers = min(max_workers, len(items))

    def verify(chunk):
        for sha, expected in chunk:
            current = (root / "objects" / (sha + ".json")).stat()
            observed = [
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
                current.st_ctime_ns,
            ]
            if observed != expected:
                return False
        return True

    if workers <= 1:
        valid = verify(items)
    else:
        chunks = tuple(items[index::workers] for index in range(workers))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="tushare-identifier-stat"
        ) as pool:
            valid = all(list(pool.map(verify, chunks)))
    return valid, workers, max(0.0, time.monotonic() - started)


def _legacy_planning_config_fingerprint(config):
    return digest(json_bytes({"version": 1, "config": config}))


def tick(max_requests=None, max_seconds=None, *, before_nonpublication_work=None):
    from contextlib import contextmanager

    tick_started = time.monotonic()
    authority()
    if not (ROOT / "ENABLED").exists():
        return {"status": "disabled"}
    catalog = json.loads(
        (
            Path(__file__).resolve().parents[2] / "config/tushare-catalog.json"
        ).read_bytes()
    )
    with (ROOT / "pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running"}
        pending_migration = ROOT / "factor-month-migration.pending.json"
        if pending_migration.exists() or pending_migration.is_symlink():
            return {"status": "blocked_pending_migration", "migration": "factor_month"}
        config = json.loads((ROOT / "pipeline-config.json").read_bytes())
        config.setdefault("requests_per_minute", 240)
        max_requests = (
            max_requests
            if max_requests is not None
            else config.get("batch_requests", 360)
        )
        max_seconds = (
            max_seconds if max_seconds is not None else config.get("batch_seconds", 100)
        )
        if not 1 <= int(max_requests) <= 1000 or not 1 <= float(max_seconds) <= 100:
            raise ValueError("Invalid bounded batch limits")
        publish_interval = config.get("publish_interval_seconds", 0)
        if type(publish_interval) is not int or publish_interval < 0:
            raise ValueError("Invalid publication interval")
        planning_interval = config.get("planning_interval_seconds", 0)
        if type(planning_interval) is not int or planning_interval < 0:
            raise ValueError("Invalid planning interval")
        if planning_interval and not publish_interval:
            raise ValueError(
                "Planning cadence requires a positive publication interval"
            )
        if shutil.disk_usage(ROOT).free < (300 if os.getenv("QM_NODE_ROLE") == "archive" else 100) * 2**30:
            return {"status": "blocked_disk_reserve"}
        token = None
        if not publish_interval:
            token = get_secret("TUSHARE_TOKEN")
            if not token:
                return {"status": "blocked_missing_token"}
        publication = {
            "interval_seconds": publish_interval,
            "status": "not_attempted",
            "performed": False,
            "pending": True,
            "current_release_id": None,
            "mirror_status": "not_checked",
        }
        from backend.shared.tushare_rate_policy import policy_report

        planning_cadence = {
            "interval_seconds": planning_interval,
            "status": "not_checked" if planning_interval else "legacy_every_tick",
            "performed": False,
        }
        report = {
            "publication": publication,
            "rate_policy": policy_report(config),
            "planning_cadence": planning_cadence,
        }
        nonpublication_work_started = False

        def start_nonpublication_work():
            nonlocal nonpublication_work_started
            if nonpublication_work_started:
                return
            nonpublication_work_started = True
            if before_nonpublication_work is not None:
                before_nonpublication_work()

        stage_seconds = {}
        completed_stages = []
        failed_stage = None

        @contextmanager
        def measure(name):
            nonlocal failed_stage
            started = time.monotonic()
            try:
                yield
            except BaseException:
                failed_stage = name
                raise
            else:
                completed_stages.append(name)
            finally:
                stage_seconds[name] = max(0.0, time.monotonic() - started)

        def publish_existing():
            document_lock = None
            with measure("publish_lock"):
                lock_path = ROOT / "documents.lock"
                if lock_path.is_symlink():
                    raise ValueError("Unsafe document lock")
                descriptor = os.open(
                    lock_path,
                    os.O_RDWR
                    | os.O_CREAT
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                document_lock = os.fdopen(descriptor, "a+")
                try:
                    fcntl.flock(
                        document_lock, fcntl.LOCK_EX | fcntl.LOCK_NB
                    )
                except BlockingIOError:
                    document_lock.close()
                    publication["status"] = "deferred_documents_active"
                    publication["performed"] = False
                    publication["pending"] = True
                    return False
            with measure("publish"):
                try:
                    publication["status"] = "publishing"
                    release_id = pipeline.publish()
                    report["release_id"] = release_id
                    publication.update(
                        status="published",
                        performed=True,
                        pending=False,
                        current_release_id=release_id,
                    )
                    if publish_interval:
                        successful_at = int(time.time())
                        pipeline._publication_success(release_id, successful_at)
                        publication.update(
                            last_success_at=successful_at,
                            next_due_at=successful_at + publish_interval,
                        )
                finally:
                    document_lock.close()
            return True

        pipeline = None
        failed = False
        try:
            try:
                today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
                if publish_interval:
                    # A due interval tick publishes durable work before spending the
                    # acquisition budget. Do not stack the two bounded operations.
                    with measure("open"):
                        pipeline = Pipeline(ROOT, catalog)
                    with measure("publication_check"):
                        due = True
                        pointer = ROOT / "CURRENT.json"
                        if pointer.exists() or pointer.is_symlink():
                            if pointer.is_symlink():
                                raise ValueError("Unsafe current pointer")
                            current = json.loads(pointer.read_bytes())
                            release_id = current["release_id"]
                            if current.get("manifest_sha256") != release_id[5:]:
                                raise ValueError("Current manifest identity mismatch")
                            verify_manifest_identity_at(ROOT, release_id)
                            publication["current_release_id"] = release_id
                            saved = pipeline.db.execute(
                                "SELECT value FROM scheduler_state WHERE name='publish_success_at'"
                            ).fetchone()
                            if saved and (type(saved[0]) is not int or saved[0] < 0):
                                raise ValueError("Invalid publication checkpoint")
                            intent = pipeline.db.execute(
                                "SELECT value FROM scheduler_state WHERE name=?",
                                ("publish_intent:" + release_id,),
                            ).fetchone()
                            if intent:
                                completed_at = intent[0]
                                if type(completed_at) is not int or completed_at < 0:
                                    raise ValueError("Invalid publication intent time")
                                now = time.time()
                                if completed_at > now or (saved and saved[0] > now):
                                    publication["checkpoint_recovery"] = "clock_rollback"
                                elif not saved or completed_at >= saved[0]:
                                    # manifest_at above verified the immutable body;
                                    # recheck the pointer inside the commit helper.
                                    pipeline._publication_success(release_id, completed_at)
                                    saved = (completed_at,)
                                    publication["checkpoint_recovery"] = "verified_current_intent"
                                    publication["recovered_release_id"] = release_id
                                else:
                                    publication["checkpoint_recovery"] = "older_intent"
                            if saved:
                                last_success = saved[0]
                                publication["last_success_at"] = last_success
                                publication["next_due_at"] = (
                                    last_success + publish_interval
                                )
                                # Clock rollback forces a real publication check, never
                                # an unbounded postponement based on a future timestamp.
                                elapsed = time.time() - last_success
                                due = (
                                    not 0 <= elapsed < publish_interval
                                    or publication.get("checkpoint_recovery") == "clock_rollback"
                                )
                    if due:
                        report.update(status="publish_only", requests=0)
                        publication["mode"] = "publish_only"
                        if not publish_existing():
                            report["status"] = "publish_deferred_documents_active"
                        return report
                    report["release_id"] = publication["current_release_id"]
                    publication["status"] = "deferred"
                    publication["mode"] = "acquire_only"
                    start_nonpublication_work()
                planning_due = not planning_interval
                if planning_interval:
                    with measure("planning_check"):
                        # Document consumption has its own durable queue. Its bounded
                        # controls cannot change the acquisition plan and are excluded
                        # so a throughput change does not discard one API cycle.
                        # Only our last successful planning policy is retained;
                        # A -> B -> A must not reuse A's old successful checkpoint.
                        fingerprint = _planning_config_fingerprint(config)
                        checkpoint_name = "planning_success:" + fingerprint
                        legacy_checkpoint_name = (
                            "planning_success:"
                            + _legacy_planning_config_fingerprint(config)
                        )
                        saved = pipeline.db.execute(
                            "SELECT name,value FROM scheduler_state "
                            "WHERE name GLOB 'planning_success:*'"
                        ).fetchall()
                        planning_due = True
                        reason = "first_enabled"
                        if len(saved) > 1:
                            raise ValueError("Ambiguous planning checkpoint")
                        if saved:
                            name, last_success = saved[0]
                            if (
                                not re.fullmatch(r"planning_success:[a-f0-9]{64}", name)
                                or type(last_success) is not int
                                or last_success < 0
                            ):
                                raise ValueError("Invalid planning checkpoint")
                            if (
                                name == legacy_checkpoint_name
                                and name != checkpoint_name
                            ):
                                # A v1 checkpoint matching the exact current config
                                # proves this is only a fingerprint-scope migration.
                                # Preserve its clock and do not manufacture a plan.
                                with pipeline.db:
                                    pipeline.db.execute(
                                        "DELETE FROM scheduler_state WHERE name=?",
                                        (name,),
                                    )
                                    pipeline.db.execute(
                                        "INSERT INTO scheduler_state(name,value) "
                                        "VALUES(?,?)",
                                        (checkpoint_name, last_success),
                                    )
                                name = checkpoint_name
                                planning_cadence["checkpoint_migration"] = (
                                    "whole_config_v1_to_planning_config_v2"
                                )
                            elapsed = time.time() - last_success
                            planning_cadence.update(
                                last_success_at=last_success,
                                next_due_at=last_success + planning_interval,
                            )
                            if name != checkpoint_name:
                                reason = "configuration_changed"
                            elif elapsed < 0:
                                reason = "clock_rollback"
                            else:
                                planning_due = elapsed >= planning_interval
                                reason = (
                                    "interval_due"
                                    if planning_due
                                    else "interval_not_due"
                                )
                        planning_cadence.update(
                            config_fingerprint=fingerprint,
                            due=planning_due,
                            reason=reason,
                            status="due" if planning_due else "deferred",
                        )
                if not planning_interval or not planning_due:
                    if publish_interval:
                        token = get_secret("TUSHARE_TOKEN")
                        if not token:
                            report.update(status="blocked_missing_token", requests=0)
                            return report
                if planning_due:
                    planning_cadence["status"] = "planning"
                    with measure("initialize"):
                        if pipeline is None:
                            pipeline = Pipeline(ROOT, catalog)
                        pipeline.initialize(config, today)
                    with measure("planning"):
                        report["planning"] = pipeline.plan_extended(config, today)
                    with measure("queue_compaction"):
                        report["queue_compaction"] = (
                            pipeline.compact_stale_recent_roots(
                                today.strftime("%Y%m%d")
                            )
                        )
                    with measure("permission_reprobe"):
                        report["permission_reprobe"] = (
                            pipeline.schedule_permission_reprobes(config)
                        )
                    with measure("financial_vip_compaction"):
                        report["financial_vip_compaction"] = (
                            pipeline.compact_financial_vip_coverage()
                        )
                    with measure("fina_mainbz_vip_compaction"):
                        report["fina_mainbz_vip_compaction"] = (
                            pipeline.compact_fina_mainbz_vip_coverage()
                        )
                    if planning_interval:
                        # Do not checkpoint partial initialize/planning work on any
                        # failure. Existing family cursors retain their own semantics.
                        with measure("planning_checkpoint"):
                            successful_at = int(time.time())
                            with pipeline.db:
                                pipeline.db.execute(
                                    "DELETE FROM scheduler_state "
                                    "WHERE name GLOB 'planning_success:*'"
                                )
                                pipeline.db.execute(
                                    "INSERT INTO scheduler_state(name,value) VALUES(?,?)",
                                    (checkpoint_name, successful_at),
                                )
                            planning_cadence.update(
                                last_success_at=successful_at,
                                next_due_at=successful_at + planning_interval,
                            )
                    planning_cadence.update(status="planned", performed=True)
                    if planning_interval:
                        report.update(status="planning_only", requests=0)
                        publication["mode"] = "planning_only"
                        return report
                with measure("archive"):
                    from backend.shared.tushare_archive import recover_archive

                    report["archive"] = recover_archive(
                        ROOT,
                        max_items=int(config.get("archive_items_per_tick", 200)),
                        max_seconds=5,
                    )
                # run retains its existing budget and reconciliation calls.
                with measure("acquire"):
                    with httpx.Client(
                        trust_env=False, timeout=30, follow_redirects=False
                    ) as client:
                        report.update(
                            pipeline.run(
                                client,
                                token,
                                config,
                                max_requests,
                                max_seconds,
                                pause=0,
                            )
                        )
                if config.get("enable_documents", False):
                    with measure("document_registration"):
                        report["document_registration"] = pipeline.register_documents(
                            max_observations=config.get(
                                "document_registration_max_observations", 20
                            ),
                            max_records=config.get(
                                "document_registration_max_records", 500
                            ),
                            max_seconds=config.get(
                                "document_registration_max_seconds", 5
                            ),
                        )
                    if config.get("document_execution") != "worker":
                        with measure("documents"):
                            from backend.shared.tushare_documents import run_documents

                            report["documents"] = run_documents(
                                ROOT,
                                max_documents=int(config.get("documents_per_tick", 3)),
                                max_seconds=min(
                                    20, float(config.get("document_seconds", 20))
                                ),
                            )
                if not publish_interval:
                    if not publish_existing():
                        report["status"] = "publish_deferred_documents_active"
            finally:
                if pipeline is not None:
                    with measure("close"):
                        pipeline.close()
            return report
        except BaseException as exc:
            failed = True
            if publication["status"] == "publishing":
                publication["status"] = "failed"
            if planning_cadence["status"] == "planning":
                planning_cadence["status"] = "failed"
            report.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            report.update(
                updated_at=utc_now(),
                timing={
                    "stage_seconds": stage_seconds,
                    "completed_stages": completed_stages,
                    "failed_stage": failed_stage,
                    "included_stages": {"reconciliation": "acquire"},
                    # Includes setup and close; excludes serializing this report.
                    "total_elapsed_seconds": max(0.0, time.monotonic() - tick_started),
                },
            )
            from backend.shared.tushare_daily_quota import status as daily_quota_report

            daily_status = daily_quota_report(ROOT, config)
            if daily_status is not None:
                report["rate_policy"]["daily_quota_ledger"] = daily_status
            daily_quota_status = getattr(pipeline, "daily_quota_status", None)
            if isinstance(daily_quota_status, dict):
                report["rate_policy"]["daily_quota"] = daily_quota_status
            rate_gate_status = getattr(pipeline, "rate_gate_status", None)
            if isinstance(rate_gate_status, dict):
                report["rate_policy"]["last_gate"] = rate_gate_status
            planning_timing = getattr(pipeline, "planning_timing", None)
            if isinstance(planning_timing, dict):
                report["timing"]["planning"] = planning_timing
            publish_timing = getattr(pipeline, "publish_timing", None)
            if isinstance(publish_timing, dict):
                report["timing"]["publish"] = publish_timing
            if failed:
                try:
                    atomic_json(ROOT / "pipeline-status.json", report)
                except Exception:
                    pass  # Reporting failure must not mask the original exception.
            else:
                atomic_json(ROOT / "pipeline-status.json", report)


def _manifest_path_at(root, release_id):
    if not re.fullmatch(r"data-[a-f0-9]{64}", release_id):
        raise ValueError("Invalid release ID")
    root = Path(root).resolve()
    path = root / "releases" / release_id / "manifest.json"
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Unsafe manifest path")
    if not path.exists():
        path = root / "archives" / (release_id.removeprefix("data-") + ".json")
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Unsafe archived manifest path")
    return path


def verify_manifest_identity_at(root, release_id):
    path = _manifest_path_at(root, release_id)
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != release_id.removeprefix("data-"):
        raise ValueError("Manifest checksum mismatch")


def manifest_at(root, release_id):
    path = _manifest_path_at(root, release_id)
    raw = path.read_bytes()
    if digest(raw) != release_id.removeprefix("data-"):
        raise ValueError("Manifest checksum mismatch")
    manifest = json.loads(raw)
    for path in manifest["files"]:
        if not (
            re.fullmatch(
                r"(?:objects|observations|parquet|schemas|attachments|extracted|documents|archives)/[a-f0-9]+\.(?:json|parquet|pdf|html)",
                path,
            )
            or re.fullmatch(r"attachments/[a-f0-9]{64}\.bin", path)
        ):
            raise ValueError("Invalid object path")
    return manifest


def verify_data(root, release_id):
    root = Path(root)
    manifest = manifest_at(root, release_id)
    for name, expected in manifest["files"].items():
        path = root / name
        if (
            path.is_symlink()
            or path.stat().st_size != expected["bytes"]
            or digest(path.read_bytes()) != expected["sha256"]
        ):
            raise ValueError("Dataset object checksum mismatch")
    return manifest
