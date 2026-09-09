"""Single-writer Tushare acquisition, durable checkpoints and immutable releases.

Acquisition uses reviewed contracts and durable family queues. The public
catalogue remains a separate coverage obligation. Readers never acquire data.
"""

from __future__ import annotations

import fcntl
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
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from backend.shared.tushare_registry import (
    EXTENDED_CONTRACTS,
    PLANNERS,
    contract_for,
    risk_event_runtime_prerequisites,
    technical_extra_runtime_prerequisites,
    TECHNICAL_EXTRA_RUNTIME_CONTRACTS,
)
from backend.shared.tushare_global_contracts import (
    GLOBAL_CONTRACTS,
    global_prerequisites,
)
from backend.shared.tushare_other_contracts import OTHER_CONTRACTS, other_prerequisites
from backend.shared.tushare_supplement_contracts import supplement_prerequisites
from backend.shared.tushare_equity_event_contracts import equity_event_prerequisites
from backend.shared.tushare_futures_extra_contracts import futures_extra_prerequisites
from backend.shared.tushare_research_extra_contracts import research_extra_prerequisites
from backend.shared.tushare_etf_basket_contracts import etf_basket_prerequisites
from backend.shared.tushare_credit_extra_contracts import (
    credit_identifiers,
    credit_extra_prerequisites,
)
from backend.shared.tushare_connect_contracts import (
    CONNECT_CONTRACTS,
    connect_prerequisites,
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
from backend.shared.tushare_intake import capture_sample, digest, json_bytes, utc_now

ROOT = Path("/data/tushare")
CONTRACTS = {
    "trade_cal": (6000, ["cal_date", "is_open"]),
    "ci_daily": (4000, ["ts_code", "trade_date", "open", "close"]),
    "ci_index_member": (5000, ["l1_code", "ts_code", "in_date", "out_date"]),
    "etf_basic": (5000, ["ts_code", "list_status", "list_date"]),
    "fund_daily": (5000, ["ts_code", "trade_date", "open", "close", "vol", "amount"]),
    "fund_adj": (2000, ["ts_code", "trade_date", "adj_factor"]),
    "fund_portfolio": (2000, ["ts_code", "ann_date", "end_date", "symbol", "mkv"]),
}


def _planning_inputs(family, config, identifiers):
    """Only request-planner dependencies affect a family's enumeration.

    Saturation-only universes remain live in date_children; they do not change
    the planner stream and must not restart it. Legacy structured declarations
    omit two direct dependencies, so retain those explicit adapter mappings.
    """
    contracts = {
        api: spec for api, spec in EXTENDED_CONTRACTS.items() if spec["group"] == family
    }
    selected = config.get(family + "_apis", tuple(contracts))
    if any(api not in contracts for api in selected):
        raise ValueError("Unknown " + family + " API")
    contracts = {api: contracts[api] for api in selected}
    dependencies = {
        dep for spec in contracts.values() for dep in spec.get("dependencies", ())
    }
    for api, dependency in (("namechange", "stocks"), ("index_daily", "indexes")):
        if api in contracts:
            dependencies.add(dependency)
    keys = {"history_start", family + "_apis"}
    if family not in ("structured", "market"):
        keys.add(family + "_history_start")
    if family == "text":
        keys.update(("text_history_starts", "text_history_window"))
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


def authority():
    if (
        os.getenv("QM_NODE_ROLE") != "authority"
        or not Path("/.dockerenv").exists()
        or not Path("/data").is_mount()
        or ROOT.resolve() != ROOT
    ):
        raise ValueError("Acquisition requires the verified cloud authority mount")


class Pipeline:
    def __init__(self, root, catalog):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = catalog
        self.db = sqlite3.connect(self.root / "pipeline.sqlite", timeout=10)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("pragma user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, 4, 5):
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

    def next_job(self, config, deadline):
        rpm = config.get("requests_per_minute")
        if rpm is None:
            return self.db.execute(
                "SELECT * FROM jobs INDEXED BY jobs_ready_order WHERE state='pending' AND retry_after<=? ORDER BY priority,rowid LIMIT 1",
                (time.time(),),
            ).fetchone()
        if not 1 <= int(rpm) <= 500:
            raise ValueError("Invalid account request rate")
        while time.monotonic() < deadline:
            now = time.time()
            account = self.db.execute(
                "SELECT next_at FROM request_gates WHERE scope='account'"
            ).fetchone()
            account_wait = max(0, account[0] - now) if account else 0
            if account_wait:
                if account_wait >= deadline - time.monotonic():
                    return None
                time.sleep(account_wait)
                continue
            groups = ["rrg"] + [
                name for name in PLANNERS if config.get("enable_" + name)
            ]
            weights = config.get("group_weights", {})
            if any(not 1 <= int(weights.get(name, 1)) <= 10 for name in groups):
                raise ValueError("Invalid family scheduling weight")
            groups = [name for name in groups for _ in range(int(weights.get(name, 1)))]
            group = groups[self._fair_turn % len(groups)]
            sql = """SELECT j.* FROM jobs j INDEXED BY {ready_index} LEFT JOIN request_gates g
                ON g.scope='api:' || json_extract(j.job,'$.api_name')
                WHERE j.state='pending' AND j.retry_after<=? AND COALESCE(g.next_at,0)<=?
                {group_filter} ORDER BY j.priority,j.rowid LIMIT 1"""
            row = self.db.execute(
                sql.format(
                    group_filter="AND j.group_name=?", ready_index="jobs_ready_group"
                ),
                (now, now, group),
            ).fetchone()
            if row is None:
                row = self.db.execute(
                    sql.format(group_filter="", ready_index="jobs_ready_order"),
                    (now, now),
                ).fetchone()
            if row:
                api = json.loads(row["job"])["api_name"]
                api_rpm = min(
                    int(config.get("api_requests_per_minute", {}).get(api, 200)),
                    int(contract_for(api).get("requests_per_minute", 500)),
                )
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
                self.db.executemany(
                    "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=excluded.next_at",
                    [
                        ("account", now + 60 / int(rpm)),
                        ("api:" + api, now + max(60 / api_rpm, interval)),
                    ],
                )
                self._fair_turn += 1
                self.db.execute(
                    "INSERT INTO scheduler_state(name,value) VALUES('family_turn',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (self._fair_turn,),
                )
                self.db.commit()  # reserve before issuing the request, including failures
                return row
            earliest = self.db.execute("""
                SELECT MIN(MAX(j.retry_after,COALESCE(g.next_at,0)))
                FROM jobs j LEFT JOIN request_gates g ON g.scope='api:' || json_extract(j.job,'$.api_name')
                WHERE j.state='pending'
            """).fetchone()[0]
            delay = max(0.01, earliest - now) if earliest is not None else None
            if delay is None or delay >= deadline - time.monotonic():
                return None
            time.sleep(delay)
        return None

    def close(self):
        self.db.close()

    def enqueue(self, api, params, priority=10, epoch="history"):
        spec = contract_for(api)
        if spec.get("group") == "global" and spec.get("pagination"):
            params = dict(params)
            pagination = spec["pagination"]
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
        scope = api + ":" + str(params.get("src", ""))
        denied = self.db.execute(
            "SELECT 1 FROM capability WHERE scope=? AND status='permission_denied'",
            (scope,),
        ).fetchone()
        self.db.execute(
            "INSERT OR IGNORE INTO jobs(id,logical_key,epoch,job,priority,state,group_name) VALUES(?,?,?,?,?,?,?)",
            (
                key,
                logical,
                epoch,
                json.dumps(job),
                priority,
                "permission_blocked" if denied else "pending",
                spec.get("group", "rrg"),
            ),
        )
        return key

    def records(self, result):
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
        return [
            dict(zip(data.get("fields", []), row, strict=True))
            for row in data.get("items", [])
        ]

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
            if params.get(field) is None or params.get(field) == ""
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
            for key in (
                "ts_code",
                "symbol",
                "l1_code",
                "l2_code",
                "l3_code",
                "index_code",
            ):
                value = row.get(key)
                if isinstance(value, str):
                    row["source_" + key] = value
                    if key == "ts_code" and (
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
                        and result["api_name"] in GLOBAL_CONTRACTS
                        and result["api_name"].startswith("us_")
                    ):
                        # US symbols are opaque supplier tickers, not suffix codes.
                        row[key] = "US" + value
                    elif (
                        key == "ts_code"
                        and result["api_name"] in GLOBAL_CONTRACTS
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
            )
            for code in sorted(industries):
                self.enqueue(
                    "ci_daily",
                    {"ts_code": code, "start_date": a, "end_date": b},
                    priority,
                    current,
                )
        for status in ("L", "D", "P"):
            self.enqueue("etf_basic", {"list_status": status}, 0, epoch)
        for code in sorted(industries):
            for current in ("Y", "N"):
                self.enqueue(
                    "ci_index_member", {"l1_code": code, "is_new": current}, 1, epoch
                )
        # Recent revisions are rechecked independently of historical checkpoints.
        for days in range(1, 8):
            d = (today - timedelta(days=days)).strftime("%Y%m%d")
            self.enqueue(
                "trade_cal",
                {"exchange": "SSE", "start_date": d, "end_date": d},
                0,
                epoch,
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
                        )
        self.db.commit()

    def identifiers(self):
        families = {
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
        }
        result = {name: set() for name in families.values()}
        result.update(
            sw_indexes=set(),
            futures_continuous=set(),
            futures_products=set(),
            etfs=set(),
            bse_new_codes=set(),
        )
        placeholders = ",".join("?" for _ in families)
        for row in self.db.execute(
            "SELECT result FROM jobs WHERE result IS NOT NULL AND json_extract(job,'$.api_name') IN ("
            + placeholders
            + ") UNION SELECT result FROM attempts WHERE json_extract(result,'$.api_name') IN ("
            + placeholders
            + ")",
            tuple(families) + tuple(families),
        ):
            saved = json.loads(row[0])
            for record in self.records(saved):
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
                if (
                    saved["api_name"] == "index_classify"
                    and record.get("level") != "L3"
                ):
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
        result["risk_securities"].update(
            result["risk_stocks"] | result["funds"] | result["etfs"]
        )
        result = {key: sorted(values) for key, values in result.items()}
        try:
            result.update(credit_identifiers(result))
        except ValueError:
            # Keep raw discovery for family-local validation below; malformed
            # credit inputs must not block unrelated families in identifiers().
            pass
        return result

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
            "technical_extra": technical_extra_runtime_prerequisites,
            "risk_event": risk_event_runtime_prerequisites,
            "dc_extra": dc_extra_prerequisites,
            "concept_extra": concept_extra_prerequisites,
            "limit_extra": limit_extra_prerequisites,
            "listing_extra": listing_extra_prerequisites,
            "trading_event": trading_event_prerequisites,
            "connect": connect_prerequisites,
            "etf_basket": etf_basket_prerequisites,
            "credit_extra": credit_extra_prerequisites,
            "futures_extra": futures_extra_prerequisites,
            "research_extra": research_extra_prerequisites,
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
        identifiers = self.identifiers()
        blocked_families = set()
        for family, validate in (
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
                "research_extra",
                lambda cfg, ids: self.record_extra_planning_gaps(
                    "research_extra", cfg, ids
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
        stats = {}
        for family, planner in PLANNERS.items():
            if family in blocked_families or not config.get("enable_" + family, False):
                continue
            policy, current_ids = _planning_inputs(family, config, identifiers)
            for mode in ("recent", "history"):
                name = mode + ":" + family
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
                stream = iter(planner(plan_config, anchor, snapshot["identifiers"]))
                stream = itertools.islice(stream, state["offset"], None)
                count, done = 0, False
                attempted, inserted = 0, 0
                for _ in range(budget):
                    job = next(stream, None)
                    if job is None or (mode == "recent" and job["epoch"] == "history"):
                        done = True
                        break
                    if mode != "history" or job["epoch"] == "history":
                        attempted += 1
                        before = self.db.total_changes
                        self.enqueue(
                            job["api_name"],
                            job["params"],
                            job["priority"],
                            job["epoch"],
                        )
                        inserted += self.db.total_changes - before
                    count += 1
                self.db.execute(
                    "UPDATE planning_state SET offset=offset+?,done=? WHERE name=?",
                    (count, int(done), name),
                )
                self.db.commit()
                stats[name] = {
                    "planned": count,
                    "new_jobs": inserted,
                    "existing_jobs": attempted - inserted,
                    "skipped_recent": count - attempted,
                    "done": done,
                    "anchor": state["anchor"],
                    "reset_reason": reset_reason,
                    "discovery_refresh_pending": snapshot["identifiers"] != current_ids,
                }
        self.db.commit()  # Persist validation gaps even when every family is blocked.
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

    def split_request(self, row, job, result=None):
        spec = contract_for(job["api_name"])
        params = job["params"]
        if spec.get("group") == "global" and spec.get("pagination"):
            return None
        existing = self.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (row["id"],)
        ).fetchone()
        family = spec.get("saturation_fallback")
        param = spec.get("saturation_param", "ts_code")
        fanout = family and param not in params
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

            def usable(code):
                return (
                    isinstance(code, str)
                    and bool(code)
                    and not any(
                        char.isspace() or ord(char) < 32 or ord(char) == 127
                        for char in code
                    )
                )

            discovered = {
                code for code in self.identifiers().get(family, []) if usable(code)
            }
            saved = result if result is not None else json.loads(row["result"] or "{}")
            observed = (
                {
                    record.get(param)
                    for record in self.records(saved)
                    if usable(record.get(param))
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
            ids = previous_ids | {
                self.enqueue(
                    job["api_name"],
                    {**params, param: code},
                    row["priority"] + 1,
                    row["epoch"],
                )
                for code in sorted(codes)
            }
            if ids:
                evidence = (
                    json.loads(existing["evidence"]) if existing else {"origin": "v4"}
                )
                evidence.update(family=family, universe_complete=False)
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
                return {
                    "method": "identifier_fanout",
                    "children": len(ids),
                    "universe_complete": False,
                    "parent_observed_added_count": evidence.get(
                        "parent_observed_added_count", 0
                    ),
                }
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

    def reconcile_partitions(self, max_parents=1000, child_id=None):
        """Bounded, restartable closure; descendants must carry positive evidence.

        A done pagination page or empty-unverified terminator is not a complete
        partition. Resolved children are acceptable only while their split evidence
        still holds. The single writer never promotes an incomplete universe.
        """
        if not 1 <= max_parents <= 10000:
            raise ValueError("Invalid partition reconciliation budget")
        if child_id is None:
            saved = self.db.execute(
                "SELECT value FROM scheduler_state WHERE name='partition_cursor'"
            ).fetchone()
            cursor = saved[0] if saved else 0
            selected = self.db.execute(
                "SELECT rowid,parent_id FROM partition_splits WHERE rowid>? ORDER BY rowid LIMIT ?",
                (cursor, max_parents),
            ).fetchall()
            self.db.execute(
                "INSERT INTO scheduler_state VALUES('partition_cursor',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (selected[-1]["rowid"] if selected else 0,),
            )
            pending = deque(row["parent_id"] for row in selected)
        else:
            pending = deque(
                r[0]
                for r in self.db.execute(
                    "SELECT parent_id FROM partition_children WHERE child_id=? UNION SELECT parent_id FROM partition_splits WHERE parent_id=?",
                    (child_id, child_id),
                )
            )
        checked, resolved = 0, 0
        while pending and checked < max_parents:
            parent_id = pending.popleft()
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
            if json.loads(split["evidence"]).get("origin") == "legacy_unverified":
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
            status = "gap" if gap else "resolved"
            changed = split["status"] != status or split["gap"] != gap
            self.db.execute(
                "UPDATE partition_splits SET status=?,gap=? WHERE parent_id=?",
                (status, gap, parent_id),
            )
            if parent["state"] in ("split_pending", "resolved"):
                self.db.execute(
                    "UPDATE jobs SET state=? WHERE id=?",
                    ("split_pending" if gap else "resolved", parent_id),
                )
            if changed:
                pending.extend(
                    r[0]
                    for r in self.db.execute(
                        "SELECT parent_id FROM partition_children WHERE child_id=?",
                        (parent_id,),
                    )
                )
            checked += 1
            resolved += int(not gap)
        self.db.commit()
        return {"checked": checked, "resolved": resolved}

    def partition_inventory(self):
        entries = []
        for row in self.db.execute("SELECT * FROM partition_splits ORDER BY parent_id"):
            item = dict(row)
            item["evidence"] = json.loads(item["evidence"])
            item["children"] = [
                r[0]
                for r in self.db.execute(
                    "SELECT child_id FROM partition_children WHERE parent_id=? ORDER BY child_id",
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

    def run(self, client, token, config, max_requests=100, max_seconds=100, pause=0.6):
        started = time.monotonic()
        self.reconcile_partitions()
        completed = 0
        while completed < max_requests and time.monotonic() - started < max_seconds:
            self.expand(config)
            row = self.next_job(config, started + max_seconds)
            if row is None:
                break
            job = json.loads(row["job"])
            result = capture_sample(client, token, job, self.root)
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
            ):
                self.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                    (
                        job["api_name"] + ":" + str(job["params"].get("src", "")),
                        "available",
                        utc_now(),
                        status,
                    ),
                )
            if status == "permission_denied":
                state = "blocked"
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
            if status == "possibly_truncated":
                state = "blocked"
                split = self.split_request(row, job, result)
                if split:
                    result["split"] = split
                    state = "split_pending"
            pagination = contract_for(job["api_name"]).get("pagination")
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
                elif status == "empty_unverified" and offset > 0:
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
                    state = "blocked"
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
            self.reconcile_partitions(child_id=row["id"])
            completed += 1
            if pause:
                time.sleep(pause)
        self.expand(config)
        return {
            "requests": completed,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            **self.status(),
        }

    def register_documents(self, max_observations=20):
        from backend.shared.tushare_documents import enqueue_documents

        apis = [
            api
            for api, spec in EXTENDED_CONTRACTS.items()
            if spec.get("attachment_fields")
        ]
        if not apis:
            return {"observations": 0}
        last = self.db.execute(
            "SELECT value FROM scheduler_state WHERE name='document_cursor'"
        ).fetchone()
        rows = self.db.execute(
            "SELECT rowid,result FROM attempts WHERE rowid>? AND json_extract(result,'$.api_name') IN ("
            + ",".join("?" for _ in apis)
            + ") ORDER BY rowid LIMIT ?",
            (last[0] if last else 0, *apis, max_observations),
        ).fetchall()
        count = 0
        for row in rows:
            result = json.loads(row["result"])
            if result.get("observation") and result.get("object_sha256"):
                enqueue_documents(
                    self.root,
                    result["observation"],
                    result["api_name"],
                    self.records(result),
                    contract_for(result["api_name"])["attachment_fields"],
                )
                count += 1
            self.db.execute(
                "INSERT INTO scheduler_state(name,value) VALUES('document_cursor',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (row["rowid"],),
            )
            self.db.commit()  # Idempotent document refs make crash replay safe.
        return {"observations": count}

    def status(self):
        return {
            r[0]: r[1]
            for r in self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state")
        }

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
                "SELECT * FROM jobs WHERE state NOT IN ('done','pending') ORDER BY rowid"
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
            for row in self.db.execute(
                "SELECT result FROM attempts ORDER BY job_id,attempt"
            ):
                result = json.loads(row[0])
                if "observation" in result:
                    paths = [
                        (
                            "observations/" + result["observation"],
                            result["observation_sha256"],
                        ),
                        (
                            "objects/" + result["object_sha256"] + ".json",
                            result["object_sha256"],
                        ),
                    ]
                    if "parquet" in result:
                        paths.append(
                            (result["parquet"]["path"], result["parquet"]["sha256"])
                        )
                    for name, sha in paths:
                        files[name] = {
                            "sha256": sha,
                            "bytes": (self.root / name).stat().st_size,
                        }
                if "parquet" in result:
                    active[result["parquet"]["path"]] = {
                        "api_name": result["api_name"],
                        "quality_state": result["status"],
                        **result["parquet"],
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
            content = {
                "schema_version": 1,
                "files": files,
                "datasets": list(active.values()),
                "coverage": self.status(),
                "coverage_by_api": [
                    dict(r)
                    for r in self.db.execute(
                        "SELECT json_extract(job, '$.api_name') AS api_name,state,count(*) AS partitions FROM jobs GROUP BY api_name,state"
                    )
                ],
                "gaps": gaps,
                "history_complete": False,
                "partition_closure": self.partition_inventory(),
                "rrg_status": "blocked_data",
                "scope": [
                    r[0]
                    for r in self.db.execute(
                        "SELECT DISTINCT json_extract(job,'$.api_name') AS api FROM jobs ORDER BY api"
                    )
                ],
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
                    return previous_id
        if previous_id:
            from backend.shared.tushare_archive import archive_inventory, retain_release

            with measure("retain_previous"):
                retained = retain_release(self.root, previous_id)
                for name, metadata in retained["files"].items():
                    if name in files and files[name] != metadata:
                        raise ValueError("Conflicting inherited file metadata")
                    files[name] = metadata
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
            raw = json_bytes(content)
            sha = digest(raw)
            release = "data-" + sha
            destination = self.root / "releases" / release / "manifest.json"
        with measure("write_manifest"):
            if not destination.exists():
                atomic_bytes(destination, raw)
            atomic_json(
                self.root / "CURRENT.json", {"release_id": release, "manifest_sha256": sha}
            )
        return release


def tick(max_requests=None, max_seconds=None):
    from contextlib import contextmanager

    tick_started = time.monotonic()
    authority()
    if not (ROOT / "ENABLED").exists():
        return {"status": "disabled"}
    config = json.loads((ROOT / "pipeline-config.json").read_bytes())
    config.setdefault("requests_per_minute", 240)
    max_requests = (
        max_requests if max_requests is not None else config.get("batch_requests", 360)
    )
    max_seconds = (
        max_seconds if max_seconds is not None else config.get("batch_seconds", 100)
    )
    if not 1 <= int(max_requests) <= 1000 or not 1 <= float(max_seconds) <= 100:
        raise ValueError("Invalid bounded batch limits")
    publish_interval = config.get("publish_interval_seconds", 0)
    if type(publish_interval) is not int or publish_interval < 0:
        raise ValueError("Invalid publication interval")
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
        if shutil.disk_usage(ROOT).free < 100 * 2**30:
            return {"status": "blocked_disk_reserve"}
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
        report = {"publication": publication}
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

        pipeline = None
        failed = False
        try:
            try:
                today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
                with measure("initialize"):
                    pipeline = Pipeline(ROOT, catalog)
                    pipeline.initialize(config, today)
                with measure("planning"):
                    report["planning"] = pipeline.plan_extended(config, today)
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
                        report["document_registration"] = pipeline.register_documents()
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
                with measure("publish"):
                    due = True
                    if publish_interval:
                        pointer = ROOT / "CURRENT.json"
                        if pointer.exists() or pointer.is_symlink():
                            if pointer.is_symlink():
                                raise ValueError("Unsafe current pointer")
                            current = json.loads(pointer.read_bytes())
                            release_id = current["release_id"]
                            if current.get("manifest_sha256") != release_id[5:]:
                                raise ValueError("Current manifest identity mismatch")
                            manifest_at(ROOT, release_id)
                            publication["current_release_id"] = release_id
                            saved = pipeline.db.execute(
                                "SELECT value FROM scheduler_state WHERE name='publish_success_at'"
                            ).fetchone()
                            if saved:
                                last_success = saved[0]
                                if type(last_success) is not int or last_success < 0:
                                    raise ValueError("Invalid publication checkpoint")
                                publication["last_success_at"] = last_success
                                publication["next_due_at"] = (
                                    last_success + publish_interval
                                )
                                # Clock rollback forces a real publication check, never
                                # an unbounded postponement based on a future timestamp.
                                elapsed = time.time() - last_success
                                due = not 0 <= elapsed < publish_interval
                    if due:
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
                            pipeline.db.execute(
                                "INSERT INTO scheduler_state(name,value) VALUES('publish_success_at',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                                (successful_at,),
                            )
                            pipeline.db.commit()
                            publication.update(
                                last_success_at=successful_at,
                                next_due_at=successful_at + publish_interval,
                            )
                    else:
                        report["release_id"] = publication["current_release_id"]
                        publication["status"] = "deferred"
            finally:
                if pipeline is not None:
                    with measure("close"):
                        pipeline.close()
            return report
        except BaseException as exc:
            failed = True
            if publication["status"] == "publishing":
                publication["status"] = "failed"
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


def manifest_at(root, release_id):
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
