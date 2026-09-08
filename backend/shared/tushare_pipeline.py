"""Single-writer Tushare acquisition, durable checkpoints and immutable releases.

The acquisition scope is the reviewed RRG interfaces; the full public catalogue
remains a separate coverage obligation. Readers never acquire upstream data.
"""

from __future__ import annotations

import fcntl
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
        if version not in (0, 1):
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

    def close(self):
        self.db.close()

    def enqueue(self, api, params, priority=10, epoch="history"):
        cap, required = CONTRACTS[api]
        entries = [e for e in self.catalog["entries"] if api in e.get("api_names", [])]
        fields = sorted({f for e in entries for f in e.get("output_fields", [])})
        if not fields:
            raise ValueError("Missing reviewed schema")
        job = {
            "api_name": api,
            "params": params,
            "fields": ",".join(fields),
            "row_cap": cap,
            "required_fields": required,
            "nullable_fields": ["out_date"]
            if api == "ci_index_member"
            else ["list_date"]
            if api == "etf_basic" and params.get("list_status") == "P"
            else [],
            "positive_fields": [
                f for f in ("open", "close", "adj_factor") if f in required
            ],
        }
        logical = digest(json_bytes(job))
        key = digest(json_bytes([logical, epoch]))
        self.db.execute(
            "INSERT OR IGNORE INTO jobs(id,logical_key,epoch,job,priority,state) VALUES(?,?,?,?,?,'pending')",
            (key, logical, epoch, json.dumps(job), priority),
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
            row = self.db.execute(
                "SELECT * FROM jobs WHERE state='pending' AND retry_after<=? ORDER BY priority,rowid LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row is None:
                break
            job = json.loads(row["job"])
            result = capture_sample(client, token, job, self.root)
            status = result["status"]
            state = "done" if status == "sample_ok" else "quality"
            if status == "empty_unverified":
                state = "empty"
            if status in ("transport_error", "api_error", "invalid_response"):
                state = "blocked" if row["tries"] >= 4 else "pending"
            if status == "permission_denied":
                state = "blocked"
            if status == "possibly_truncated":
                state = "blocked"
            if (
                job["api_name"] == "fund_adj"
                and result.get("row_count", 0) >= job["params"]["limit"]
            ):
                # Explicitly documented pagination. Repeated pages halt the chain.
                if result["row_count"] != job["params"]["limit"]:
                    state = "blocked"
                else:
                    previous = self.db.execute(
                        "SELECT result FROM jobs WHERE result IS NOT NULL AND id<>? AND epoch=? AND json_extract(job,'$.api_name')='fund_adj' AND json_extract(job,'$.params.trade_date')=? AND json_extract(job,'$.params.offset')<>?",
                        (
                            row["id"],
                            row["epoch"],
                            job["params"]["trade_date"],
                            job["params"]["offset"],
                        ),
                    )
                    repeated = any(
                        json.loads(x[0]).get("object_sha256")
                        == result.get("object_sha256")
                        for x in previous
                    )
                    if repeated:
                        state = "blocked"
                    else:
                        params = {
                            **job["params"],
                            "offset": job["params"]["offset"] + job["params"]["limit"],
                        }
                        self.enqueue("fund_adj", params, row["priority"], row["epoch"])
                        state = "done"
            if (
                job["api_name"] == "fund_adj"
                and status == "empty_unverified"
                and job["params"]["offset"] > 0
            ):
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
        return {"requests": completed, **self.status()}

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
            if "parquet" in result and row["state"] in ("done", "quality"):
                active[row["logical_key"]] = {
                    "api_name": result["api_name"],
                    "quality_state": row["state"],
                    **result["parquet"],
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
            "scope": sorted(CONTRACTS),
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


def tick(max_requests=100, max_seconds=100):
    authority()
    if not (ROOT / "ENABLED").exists():
        return {"status": "disabled"}
    config = json.loads((ROOT / "pipeline-config.json").read_bytes())
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
            with httpx.Client(
                trust_env=False, timeout=30, follow_redirects=False
            ) as client:
                report = pipeline.run(client, token, config, max_requests, max_seconds)
            report.update(release_id=pipeline.publish(), updated_at=utc_now())
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
            r"(objects|observations|parquet)/[a-f0-9]+\.(json|parquet)", path
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
