"""Single-writer Tushare acquisition, durable checkpoints and immutable releases.

Acquisition uses reviewed contracts and durable family queues. The public
catalogue remains a separate coverage obligation. Readers never acquire data.
"""

from __future__ import annotations

import fcntl
import itertools
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from backend.shared.tushare_registry import EXTENDED_CONTRACTS, PLANNERS, contract_for
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


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with tmp.open("wb") as stream:
        stream.write(json_bytes(value))
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
        if version not in (0, 1, 2, 3):
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
        cursor = self.db.execute(
            "SELECT value FROM scheduler_state WHERE name='family_turn'"
        ).fetchone()
        self._fair_turn = cursor[0] if cursor else 0
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
                "SELECT * FROM jobs WHERE state='pending' AND retry_after<=? ORDER BY priority,rowid LIMIT 1",
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
            sql = """SELECT j.* FROM jobs j LEFT JOIN request_gates g
                ON g.scope='api:' || json_extract(j.job,'$.api_name')
                WHERE j.state='pending' AND j.retry_after<=? AND COALESCE(g.next_at,0)<=?
                {group_filter} ORDER BY j.priority,j.rowid LIMIT 1"""
            row = self.db.execute(
                sql.format(group_filter="AND j.group_name=?"), (now, now, group)
            ).fetchone()
            if row is None:
                row = self.db.execute(
                    sql.format(group_filter=""), (now, now)
                ).fetchone()
            if row:
                api = json.loads(row["job"])["api_name"]
                api_rpm = min(
                    int(config.get("api_requests_per_minute", {}).get(api, 200)),
                    int(contract_for(api).get("requests_per_minute", 500)),
                )
                if not 1 <= api_rpm <= 500:
                    raise ValueError("Invalid API request rate")
                self.db.executemany(
                    "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=excluded.next_at",
                    [
                        ("account", now + 60 / int(rpm)),
                        ("api:" + api, now + 60 / api_rpm),
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
        for row in rows:
            row["_row_identity"] = digest(json_bytes(row))
            row["_source"] = (
                observed["request"]["params"].get("src")
                or row.get("src")
                or row.get("src_site")
                or ""
            )
            row["_api_name"] = result["api_name"]
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
                    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", value):
                        row[key] = StockCodeUtil.to_prefix(value)
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
            "stock_basic": "stocks",
            "index_basic": "indexes",
            "etf_basic": "funds",
            "fund_basic": "funds",
            "cb_basic": "bonds",
            "index_classify": "sw_l3",
            "fut_basic": "futures",
        }
        result = {name: set() for name in families.values()}
        result.update(
            sw_indexes=set(), futures_continuous=set(), futures_products=set()
        )
        placeholders = ",".join("?" for _ in families)
        for row in self.db.execute(
            "SELECT result FROM jobs WHERE result IS NOT NULL AND json_extract(job,'$.api_name') IN ("
            + placeholders
            + ")",
            tuple(families),
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
                code = record.get("ts_code") or record.get("index_code")
                if code:
                    result[families[saved["api_name"]]].add(code)
        return {key: sorted(values) for key, values in result.items()}

    def plan_extended(self, config, today):
        identifiers = self.identifiers()
        budget = int(config.get("plan_jobs_per_tick", 2000))
        if not 1 <= budget <= 10000:
            raise ValueError("Invalid planner batch size")
        signature = digest(
            json_bytes(
                {
                    "config": {
                        k: v
                        for k, v in config.items()
                        if k
                        in (
                            "history_start",
                            "text_history_start",
                            "text_history_starts",
                            "text_history_window",
                            "text_apis",
                            "structured_apis",
                            "market_apis",
                        )
                    },
                    "identifiers": identifiers,
                    "contracts": EXTENDED_CONTRACTS,
                }
            )
        )
        stats = {}
        for family, planner in PLANNERS.items():
            if not config.get("enable_" + family, False):
                continue
            for mode in ("recent", "history"):
                name = mode + ":" + family
                epoch = (
                    datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d%H")
                    if family == "text"
                    else today.strftime("%Y%m%d")
                )
                revision = signature + ":" + epoch if mode == "recent" else signature
                state = self.db.execute(
                    "SELECT * FROM planning_state WHERE name=?", (name,)
                ).fetchone()
                if state is None or state["signature"] != revision:
                    self.db.execute(
                        "INSERT INTO planning_state(name,anchor,signature,offset,done) VALUES(?,?,?,0,0) ON CONFLICT(name) DO UPDATE SET anchor=excluded.anchor,signature=excluded.signature,offset=0,done=0",
                        (name, today.strftime("%Y%m%d"), revision),
                    )
                    state = self.db.execute(
                        "SELECT * FROM planning_state WHERE name=?", (name,)
                    ).fetchone()
                if state["done"]:
                    continue
                anchor = datetime.strptime(state["anchor"], "%Y%m%d").date()
                plan_config = {
                    **config,
                    "planning_epoch": epoch if mode == "recent" else state["anchor"],
                }
                stream = iter(planner(plan_config, anchor, identifiers))
                stream = itertools.islice(stream, state["offset"], None)
                count, done = 0, False
                for _ in range(budget):
                    job = next(stream, None)
                    if job is None or (mode == "recent" and job["epoch"] == "history"):
                        done = True
                        break
                    if mode != "history" or job["epoch"] == "history":
                        self.enqueue(
                            job["api_name"],
                            job["params"],
                            job["priority"],
                            job["epoch"],
                        )
                    count += 1
                self.db.execute(
                    "UPDATE planning_state SET offset=offset+?,done=? WHERE name=?",
                    (count, int(done), name),
                )
                self.db.commit()
                stats[name] = {
                    "planned": count,
                    "done": done,
                    "anchor": state["anchor"],
                }
        return stats

    def split_request(self, row, job):
        spec = contract_for(job["api_name"])
        params = job["params"]
        split = spec.get("split")
        if "pub_start" in params and "pub_end" in params:
            split = {
                "start_param": "pub_start",
                "end_param": "pub_end",
                "precision": "second",
            }
        if split and split["start_param"] in params and split["end_param"] in params:
            fmt = "%Y-%m-%d %H:%M:%S" if split["precision"] == "second" else "%Y%m%d"
            left = datetime.strptime(params[split["start_param"]], fmt)
            right = datetime.strptime(params[split["end_param"]], fmt)
            step = (
                timedelta(seconds=1)
                if split["precision"] == "second"
                else timedelta(days=1)
            )
            units = int((right - left) / step)
            if units > 0:
                middle = left + (units // 2) * step
                children = [
                    {**params, split["end_param"]: middle.strftime(fmt)},
                    {**params, split["start_param"]: (middle + step).strftime(fmt)},
                ]
                # Time inclusivity is undocumented: overlap the boundary second.
                if split["precision"] == "second" and units > 1:
                    children[1][split["start_param"]] = middle.strftime(fmt)
                for child in children:
                    self.enqueue(job["api_name"], child, row["priority"], row["epoch"])
                return {"method": "date_bisection", "children": len(children)}
        family = spec.get("saturation_fallback")
        param = spec.get("saturation_param", "ts_code")
        if family and param not in params:
            codes = self.identifiers().get(family, [])
            if codes:
                for code in codes:
                    self.enqueue(
                        job["api_name"],
                        {**params, param: code},
                        row["priority"] + 1,
                        row["epoch"],
                    )
                return {
                    "method": "identifier_fanout",
                    "children": len(codes),
                    "universe_complete": False,
                }
        return None

    def expand(self, config):
        for row in self.db.execute(
            "SELECT * FROM jobs WHERE expanded=0 AND state IN ('done','quality','empty')"
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
                self.db.execute(
                    "INSERT INTO request_gates(scope,next_at) VALUES('account',?) ON CONFLICT(scope) DO UPDATE SET next_at=excluded.next_at",
                    (time.time() + 60,),
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
                split = self.split_request(row, job)
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
        files, active, gaps = {}, {}, []
        rows = self.db.execute("SELECT * FROM jobs ORDER BY rowid").fetchall()
        for row in rows:
            result = json.loads(row["result"]) if row["result"] else {}
            if row["state"] not in ("done", "pending"):
                gaps.append(
                    {
                        "id": row["id"],
                        "state": row["state"],
                        "api_name": json.loads(row["job"])["api_name"],
                        "params": json.loads(row["job"])["params"],
                        "assessment": result.get("status"),
                    }
                )
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
        # Ship the reviewed catalog/contract field definitions with every pinned
        # release; code availability must not substitute for offline metadata.
        metadata = {"catalog": self.catalog, "contracts": EXTENDED_CONTRACTS}
        raw = json_bytes(metadata)
        schema_name = "schemas/" + digest(raw) + ".json"
        if not (self.root / schema_name).exists():
            atomic_json(self.root / schema_name, metadata)
        files[schema_name] = {"sha256": digest(raw), "bytes": len(raw)}
        archive = None
        if (self.root / "archive.sqlite").exists():
            from backend.shared.tushare_archive import archive_inventory

            archived = archive_inventory(self.root)
            files.update(archived["files"])
            for dataset in archived["datasets"]:
                active.setdefault(dataset["path"], dataset)
            archive = {"recovery": archived["recovery"], "gaps": archived["gaps"]}
        documents = None
        if (self.root / "documents.sqlite").exists():
            from backend.shared.tushare_documents import document_inventory

            inventory = document_inventory(self.root)
            for item in inventory["files"]:
                files[item["path"]] = {"sha256": item["sha256"], "bytes": item["bytes"]}
            raw_documents = json_bytes(inventory)
            document_name = "documents/" + digest(raw_documents) + ".json"
            if not (self.root / document_name).exists():
                atomic_json(self.root / document_name, inventory)
            files[document_name] = {
                "sha256": digest(raw_documents),
                "bytes": len(raw_documents),
            }
            documents = {
                "path": document_name,
                "counts": inventory["counts"],
                "reference_counts": inventory["reference_counts"],
            }
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
            "rrg_status": "blocked_data",
            "scope": sorted({json.loads(r["job"])["api_name"] for r in rows}),
            "implemented_contracts": sorted(set(CONTRACTS) | set(EXTENDED_CONTRACTS)),
            "schema_path": schema_name,
            "documents": documents,
            "archive": archive,
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
        sha = digest(json_bytes(content))
        release = "data-" + sha
        destination = self.root / "releases" / release / "manifest.json"
        if not destination.exists():
            atomic_json(destination, content)
        atomic_json(
            self.root / "CURRENT.json", {"release_id": release, "manifest_sha256": sha}
        )
        return release


def tick(max_requests=None, max_seconds=None):
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
        pipeline = Pipeline(ROOT, catalog)
        try:
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            pipeline.initialize(config, today)
            planning = pipeline.plan_extended(config, today)
            from backend.shared.tushare_archive import recover_archive

            archive_report = recover_archive(
                ROOT,
                max_items=int(config.get("archive_items_per_tick", 200)),
                max_seconds=5,
            )
            with httpx.Client(
                trust_env=False, timeout=30, follow_redirects=False
            ) as client:
                report = pipeline.run(
                    client, token, config, max_requests, max_seconds, pause=0
                )
            if config.get("enable_documents", False):
                from backend.shared.tushare_documents import run_documents

                report["document_registration"] = pipeline.register_documents()
                report["documents"] = run_documents(
                    ROOT,
                    max_documents=int(config.get("documents_per_tick", 3)),
                    max_seconds=min(20, float(config.get("document_seconds", 20))),
                )
            report.update(
                release_id=pipeline.publish(),
                updated_at=utc_now(),
                planning=planning,
                archive=archive_report,
            )
            atomic_json(ROOT / "pipeline-status.json", report)
            return report
        finally:
            pipeline.close()


def manifest_at(root, release_id):
    if not re.fullmatch(r"data-[a-f0-9]{64}", release_id):
        raise ValueError("Invalid release ID")
    raw = (Path(root) / "releases" / release_id / "manifest.json").read_bytes()
    if digest(raw) != release_id.removeprefix("data-"):
        raise ValueError("Manifest checksum mismatch")
    manifest = json.loads(raw)
    for path in manifest["files"]:
        if not re.fullmatch(
            r"(?:objects|observations|parquet|schemas|attachments|extracted|documents|archives)/[a-f0-9]+\.(?:json|parquet|pdf|html)",
            path,
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
