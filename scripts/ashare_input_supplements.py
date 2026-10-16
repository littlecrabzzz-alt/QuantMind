#!/usr/bin/env python3
"""Bounded frozen-input supplementation through the existing native Pipeline.

No independent collector, token store, daemon or strategy evaluation. Execute
only in the authority owner's granted window. Never edits the nine old trees.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

PRODUCTS = {
    "SHFE": "CU AL ZN PB NI SN AU AG RB HC RU BU FU SP SS".split(),
    "DCE": "A M Y P C CS JD L V PP J JM I EG EB PG".split(),
    "CZCE": "SR CF TA MA FG RM OI ZC SA UR AP SF SM".split(),
    "INE": ["SC"],
}
SUFFIX = {"SHFE": "SHF", "DCE": "DCE", "CZCE": "ZCE", "INE": "INE"}
ETFS = ("510300.SH", "511010.SH", "518880.SH")
APIS = {"trade_cal", "etf_limit", "fund_daily", "fund_adj", "cb_basic", "cb_call",
        "cb_daily", "fut_basic", "fut_daily", "fut_mapping", "fund_div"}


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def datasets(path):
    """Stream the native sorted manifest's datasets array, not its multi-GB files map."""
    decoder = json.JSONDecoder()
    with Path(path).open() as stream:
        buf = ""
        while '"datasets":' not in buf:
            more = stream.read(1024 * 1024)
            if not more:
                raise ValueError("Native manifest lacks datasets")
            buf = buf[-32:] + more
        buf = buf.split('"datasets":', 1)[1].lstrip()
        if not buf.startswith("["):
            raise ValueError("Invalid native datasets array")
        buf = buf[1:]
        while True:
            buf = buf.lstrip(" \r\n\t,")
            if buf.startswith("]"):
                return
            try:
                item, end = decoder.raw_decode(buf)
            except json.JSONDecodeError:
                more = stream.read(1024 * 1024)
                if not more:
                    raise ValueError("Incomplete native datasets array") from None
                buf += more
                continue
            yield item
            buf = buf[end:]


def source_refs(root, pointer):
    current = json.loads((root / pointer).read_bytes())
    manifest = root / "releases" / current["release_id"] / "manifest.json"
    if sha(manifest) != current["manifest_sha256"]:
        raise ValueError("Native source manifest hash mismatch")
    refs = {api: [] for api in APIS}
    for item in datasets(manifest):
        if item.get("api_name") in refs and item.get("quality_state") in ("sample_ok", "schema_gap", "possibly_truncated"):
            refs[item["api_name"]].append(item)
    return current, refs


def raw_rows(root, refs):
    import pyarrow.parquet as pq
    rows = []
    for ref in refs:
        path = root / ref["path"]
        if path.stat().st_size != ref["bytes"] or sha(path) != ref["sha256"]:
            raise ValueError("Native input identity mismatch: " + ref["path"])
        for row in pq.read_table(path).to_pylist():
            if row.get("source_ts_code") is not None:
                row["ts_code"] = row["source_ts_code"]
            rows.append(row)
    return rows


def latest(rows, keys):
    selected = {}
    for row in rows:
        key = tuple(str(row.get(k)) for k in keys)
        prior = selected.get(key)
        stamp = (str(row.get("_fetched_at", "")), str(row.get("_observation", "")))
        if prior is None or stamp >= prior[0]:
            selected[key] = (stamp, row)
    return [item[1] for _, item in sorted(selected.items())]


def prepare_plan(args, current, refs):
    calendar = latest(raw_rows(args.root, refs["trade_cal"]), ("exchange", "cal_date"))
    dates = sorted({str(r["cal_date"]) for r in calendar if r.get("exchange") == "SSE"
                    and int(r.get("is_open", 0)) == 1 and args.start <= str(r["cal_date"]) <= args.end})
    future = [r for r in calendar if r.get("exchange") == "SSE" and int(r.get("is_open", 0)) == 1
              and str(r["cal_date"]) > args.end]
    if not dates:
        raise ValueError("No observed SSE open dates in requested finite window")
    jobs = []
    if not future:
        jobs.append({"api": "trade_cal", "params": {"exchange": "SSE", "start_date": args.start, "end_date": "20261231"}})
    for code in ETFS:
        jobs.append({"api": "etf_limit", "params": {"ts_code": code, "start_date": args.start, "end_date": args.end}})
    for exchange, products in PRODUCTS.items():
        jobs.append({"api": "fut_basic", "params": {"exchange": exchange, "fut_type": "1"}})
        for product in products:
            jobs.append({"api": "fut_mapping", "params": {"ts_code": f"{product}.{SUFFIX[exchange]}", "start_date": args.start, "end_date": args.end}})
        for day in dates:
            jobs.append({"api": "fut_daily", "params": {"exchange": exchange, "trade_date": day}})
    cb = args.artifact_root / "ashare-takeover/trees/ashare-lab-ideas-cb/data/extra/cb_daily"
    for day in dates:
        if not (cb / f"{day}.parquet").exists():
            jobs.append({"api": "cb_daily", "params": {"trade_date": day}})
    if len(jobs) > 128 or len(dates) > 15:
        raise ValueError("Finite supplement scope exceeded")
    return {"schema_version": 1, "created_at": utc_now(), "source": current,
            "window": {"start": args.start, "end": args.end, "observed_sse_dates": dates},
            "future_calendar_already_present": bool(future), "products": PRODUCTS,
            "scope_counts": dict(Counter(j["api"] for j in jobs)), "jobs": jobs,
            "config_sha256": sha(args.root / "pipeline-config.json"),
            "catalog_sha256": sha(args.client / "config/tushare-catalog.json"),
            "max_requests": 128, "max_seconds": 90}


def execute(args, plan):
    import httpx
    from backend.shared import tushare_pipeline as native
    native.authority()
    if not (args.root / "ENABLED").is_file():
        raise RuntimeError("Native ENABLED absent; no restoration permitted here")
    with (args.root / "pipeline.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sha(args.root / "pipeline-config.json") != plan["config_sha256"]:
            raise ValueError("Authority config changed since bounded plan")
        current = json.loads((args.root / "CURRENT.json").read_bytes())
        if current != plan["source"]:
            raise ValueError("Source publication changed since bounded plan")
        if shutil.disk_usage(args.root).free < 300 * 2**30:
            raise RuntimeError("Native 300GiB reserve would be violated")
        catalog = json.loads((args.client / "config/tushare-catalog.json").read_bytes())
        pipeline = native.Pipeline(args.root, catalog)
        try:
            token = native.get_secret("TUSHARE_TOKEN")
            if not token:
                raise RuntimeError("Native private token unavailable")
            ids = [pipeline.enqueue(j["api"], j["params"], epoch=plan.get("epoch", args.out.name)) for j in plan["jobs"]]
            pipeline.db.commit()
            config = json.loads((args.root / "pipeline-config.json").read_bytes())
            with httpx.Client(trust_env=False, timeout=30, follow_redirects=False) as client:
                run = pipeline.run(client, token, config, max_requests=128, max_seconds=90, pause=0, task_ids=ids)
            outcomes = []
            new_refs = {api: [] for api in APIS}
            for task_id in ids:
                row = pipeline.db.execute("SELECT job,state,result,retry_after FROM jobs WHERE id=?", (task_id,)).fetchone()
                result = json.loads(row["result"]) if row["result"] else {}
                job = json.loads(row["job"])
                entry = {"task_id": task_id, "api": job["api_name"], "params": job["params"],
                         "state": row["state"], "retry_after": row["retry_after"],
                         "result": {k: result.get(k) for k in ("status", "error_type", "row_count", "http_status", "missing_fields", "object_sha256", "observation", "observation_sha256", "parquet", "rate_limit_window_seconds", "rate_limit_requests", "normalization_error")}}
                if result.get("object_sha256"):
                    payload = json.loads((args.root / "objects" / (result["object_sha256"] + ".json")).read_bytes())
                    entry["supplier_code"] = payload.get("code")
                    entry["supplier_message"] = str(payload.get("msg", "")).replace(token, "[REDACTED]")
                outcomes.append(entry)
                if result.get("parquet"):
                    new_refs[job["api_name"]].append({"api_name": job["api_name"], "quality_state": result["status"], **result["parquet"]})
            dump(args.out / "native-outcomes.json", {"created_at": utc_now(), "requests": run["requests"], "outcomes": outcomes})
            # The native worker owns the configured full/research publication
            # cadence. Supplemental assets bind committed raw closure hashes;
            # a 15-minute recipe must not rescan the entire archive each time.
            interval = config.get("publish_interval_seconds", 0)
            publish_now = bool(run["requests"] and not interval)
            release_id = pipeline.publish(research=False) if publish_now else current["release_id"]
            last = pipeline.db.execute("SELECT value FROM scheduler_state WHERE name='publish_success_at'").fetchone()
            dump(args.out / "native-publication.json", {"created_at": utc_now(), "release_id": release_id,
                 "manifest_path": f"releases/{release_id}/manifest.json", "manifest_sha256": release_id.removeprefix("data-"),
                 "root_contract": "archive-root", "requests": run["requests"], "published": publish_now,
                 "publication_policy": "existing native worker cadence; raw observations already committed",
                 "configured_interval_seconds": interval,
                 "next_native_due_at": int(last[0]) + interval if last and interval else None,
                 "publication_timing": getattr(pipeline, "publish_timing", {})})
            return new_refs
        finally:
            pipeline.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", default="20261001")
    parser.add_argument("--end", default="20261015")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.root, args.client, args.artifact_root, args.out = (p.resolve() for p in (args.root, args.client, args.artifact_root, args.out))
    if args.out.parent != args.artifact_root / "ashare-input-supplements":
        parser.error("Output must be a fresh ashare-input-supplements version directory")
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ["QM_NODE_ROLE"] = "archive"
    os.environ["QM_TUSHARE_ARCHIVE_ROOT"] = str(args.root)
    os.environ["QM_RUNTIME_ENV_FILE"] = str(args.client / "config/archive.env")
    sys.path.insert(0, str(args.client))
    current, refs = source_refs(args.root, "CURRENT.json")
    plan = prepare_plan(args, current, refs)
    dump(args.out / "plan.json", plan)
    dump(args.out / "source-refs.json", refs)
    if not args.execute:
        print(json.dumps({"status": "plan_only", "scope_counts": plan["scope_counts"], "plan": str(args.out / "plan.json")}))
        return 0
    try:
        new_refs = execute(args, plan)
    except BlockingIOError:
        dump(args.out / "blocked.json", {"state": "pending", "reason": "native pipeline.lock busy; no request/queue/config change by this operation", "created_at": utc_now()})
        return 75
    dump(args.out / "new-source-refs.json", new_refs)
    print(json.dumps({"status": "native_observations_committed", "out": str(args.out), "scope_counts": plan["scope_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
