#!/usr/bin/env python3
"""Register a reviewed method and retain versioned data audits before experiments.

This first stage inspects availability/schema, not PIT correctness or strategy
performance. Review gates remain unresolved; no experiment or trading is run.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

from run_frozen_research import read, sha256, write

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/rrg_sector_rotation.json"
PHASES = ("signal_layer", "breadth_layer", "etf_execution")


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(cfg):
    if cfg["schema_version"] != 1 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", cfg["case_id"]):
        raise ValueError("Invalid research case identity")
    src = cfg["source"]
    if not re.fullmatch(r"[a-f0-9]{64}", src["fingerprint"]) or not src["url"].startswith("https://"):
        raise ValueError("An archived source fingerprint and HTTPS URL are required")
    protocol = cfg["protocol"]
    if protocol["purpose"] != "development_replication":
        raise ValueError("Previously reported periods are development replication")
    start, end = map(date.fromisoformat, protocol["comparison_window"])
    if start >= end:
        raise ValueError("Comparison dates must be ordered")
    params = protocol["parameters"]
    if any(type(v) is not int or v < 1 for v in params.values()):
        raise ValueError("RRG windows must be positive integers")
    warmup = params["ratio_lookback"] + params["momentum_lookback"] + 2 * (params["smooth_window"] - 1)
    if (protocol["warmup_sessions"], protocol["min_price_observations"]) != (warmup, warmup + 1):
        raise ValueError("RRG requires 318 warm-up intervals / 319 observations with default windows")
    ids = [r["id"] for r in cfg["datasets"] + cfg["review_gates"]]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("Check IDs must be unique")
    for item in cfg["datasets"] + cfg["review_gates"]:
        if item["phase"] not in PHASES:
            raise ValueError("Unknown research phase")
    if {gate["phase"] for gate in cfg["review_gates"]} != set(PHASES):
        raise ValueError("Each research phase must retain its semantic review gate")
    for relative in [src["note"]] + [d["glob"] for d in cfg["datasets"]]:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Input paths must stay within the project")


def archived_source(root, cfg):
    source = cfg["source"]
    catalog = root / "data/research_watch/catalog.sqlite3"
    with closing(sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT payload FROM versions WHERE key=? AND fingerprint=?",
                         (source["key"], source["fingerprint"])).fetchone()
    if not row or hashlib.sha256(row[0].encode()).hexdigest() != source["fingerprint"]:
        raise ValueError("Source version missing or its archived payload changed")
    payload = json.loads(row[0])
    if payload["key"] != source["key"] or payload["url"] != source["url"]:
        raise ValueError("Source identity does not match research contract")
    review = read(root / "data/research_watch/digest_state.json")["reviewed"].get(source["key"])
    if not review or review.get("fingerprint") != source["fingerprint"]:
        raise ValueError("This source version has no matching review record")
    return payload, review


def manifest_files(folder):
    return {p.relative_to(folder).as_posix(): sha256(p)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def verify_files(folder, expected, has_manifest=False):
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*")
              if p.is_file() and not (has_manifest and p == folder / "manifest.json")}
    if actual != set(expected):
        raise ValueError(f"Artifact inventory changed: {folder}")
    for name, digest in expected.items():
        path = folder / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or sha256(path) != digest:
            raise ValueError(f"Artifact changed: {name}")


def register(root, out, cfg):
    validate(cfg)
    if (out / "case.json").exists():
        verify(out)
        if read(out / "registration/protocol.json") != cfg:
            raise ValueError("Research contract changed; use a new output directory")
        return read(out / "case.json")
    payload, review = archived_source(root, cfg)
    folder = out / "registration"
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / "protocol.json", cfg)
    write(folder / "source.json", payload)
    write(folder / "source-review.json", review)
    shutil.copyfile(root / cfg["source"]["note"], folder / "source-note.md")
    case = {"schema_version": 1, "case_id": cfg["case_id"], "title": cfg["title"],
            "registered_at": now(), "source": cfg["source"],
            "registration_artifacts": manifest_files(folder)}
    write(out / "case.json", case)
    write(out / "state.json", {"workflow_stage": "registered", "learning_status": "candidate_experiment",
                              "evidence_level": "source_review", "local_reproduction": False,
                              "automatic_trading_authorized": False, "latest_check": None,
                              "completed_checks": {}})
    return case


def inspect_dataset(root, spec, window=None):
    import pyarrow.parquet as pq

    paths = sorted(root.glob(spec["glob"]))
    files, reasons = [], []
    fields = set(spec.get("inspect_fields", [])) | set(spec.get("nonempty_fields", []))
    fields |= set(spec["required_values"])
    values = {key: set() for key in fields}
    empty = {key: 0 for key in fields}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Data inputs must be physical project files")
        before = sha256(path)
        parquet = pq.ParquetFile(path)
        columns = parquet.schema_arrow.names
        missing = sorted(set(spec["required_columns"]) - set(columns))
        entry = {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                 "sha256": before, "rows": parquet.metadata.num_rows,
                 "columns": columns, "missing_columns": missing}
        if entry["rows"] == 0:
            reasons.append(f"Empty file: {entry['path']}")
        if missing:
            reasons.append("Missing columns: " + ", ".join(missing))
        selected = sorted(fields & set(columns))
        if selected:
            for batch in parquet.iter_batches(batch_size=65536, columns=selected):
                for name, series in batch.to_pydict().items():
                    for value in series:
                        if value is None or str(value).strip() == "":
                            empty[name] += 1
                        else:
                            values[name].add(str(value))
        if before != sha256(path):
            raise ValueError(f"Data changed while inspecting: {path}")
        files.append(entry)
    if not paths:
        reasons.append("No input files matched")
    for name, required in spec["required_values"].items():
        if not set(required) <= values[name]:
            reasons.append(f"Missing required {name}: {', '.join(sorted(set(required) - values[name]))}")
    for name in spec.get("nonempty_fields", []):
        if empty[name] or not values[name]:
            reasons.append(f"Empty or unavailable {name}: {empty[name]} rows")
    if window and "time" in fields:
        try:
            dates = [date.fromisoformat(value[:10]) for value in values["time"]]
            start, end = map(date.fromisoformat, window)
            if not dates or min(dates) > start or max(dates) < end:
                reasons.append(f"Observed dates do not cover {window[0]} through {window[1]}")
        except ValueError:
            reasons.append("Unsupported time values; explicit date normalization required")
    summaries = {key: {"distinct_count": len(v), "min": min(v) if v else None,
                       "max": max(v) if v else None, "empty_rows": empty[key],
                       "values": sorted(v) if len(v) <= 100 else None}
                 for key, v in values.items()}
    return {"id": spec["id"], "phase": spec["phase"], "label": spec["label"],
            "status": "blocked" if reasons else "passed", "scope": "availability_schema_and_coarse_date_range",
            "reasons": sorted(set(reasons)), "next_action": spec["next_action"],
            "file_count": len(files), "row_count": sum(f["rows"] for f in files),
            "fields": summaries, "files": files}


def phase_readiness(checks):
    readiness = {}
    for phase in PHASES:
        own = [c for c in checks if c["phase"] == phase]
        readiness[phase] = "blocked" if any(c["status"] == "blocked" for c in own) else "needs_review"
    # Later layers cannot be ready while their prerequisite is blocked.
    for before, after in zip(PHASES, PHASES[1:]):
        if readiness[before] == "blocked":
            readiness[after] = "blocked"
    return readiness


def report_markdown(cfg, report):
    lines = [f"# {cfg['title']}：数据准入检查", "", f"检查时间：{report['checked_at']}", "",
             "状态：" + report["workflow_stage"], "",
             "本轮只检查文件、字段与可用范围，没有运行信号、回测或交易。passed 仅表示该项结构检查通过。",
             "研究方案已冻结；数据仅保留清单、校验值与检查摘要，尚未冻结用于执行的完整数据。", "",
             "| 阶段 | 状态 |", "| --- | --- |"]
    lines += [f"| {phase} | {state} |" for phase, state in report["readiness"].items()]
    lines += ["", "| 检查 | 状态 | 证据/下一步 |", "| --- | --- | --- |"]
    for check in report["checks"]:
        reason = "; ".join(check.get("reasons", [])) or check["next_action"]
        lines.append(f"| {check['label']} | {check['status']} | {reason.replace('|', '/')} |")
    lines += ["", "## 下一步", "", report["next_action"], "",
              "未解决项先保留，不把当前行业/ETF快照回填为历史；补齐数据并适配读取器后新建检查。",
              "数据准入通过后才冻结实际执行输入并开展最小对照。研究结果须独立复核后回填；不能由本检查改为已验证。", ""]
    return "\n".join(lines)


def check(root, out, cfg):
    register(root, out, cfg)
    previous = verify(out)
    folder = out / "checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), folder / "research_case.py")
    shutil.copyfile(Path(__file__).with_name("run_frozen_research.py"), folder / "run_frozen_research.py")
    results = [inspect_dataset(root, spec, cfg["protocol"]["comparison_window"]) for spec in cfg["datasets"]]
    # Detect synchronization during the whole audit, including earlier files.
    for result in results:
        for entry in result["files"]:
            if sha256(root / entry["path"]) != entry["sha256"]:
                raise ValueError(f"Data changed during audit: {entry['path']}")
    for spec in cfg["datasets"]:
        before = next(r["files"] for r in results if r["id"] == spec["id"])
        if [p.relative_to(root).as_posix() for p in sorted(root.glob(spec["glob"]))] != [f["path"] for f in before]:
            raise ValueError("Input file inventory changed during audit")
    checks = [{k: v for k, v in result.items() if k != "files"} for result in results]
    checks += [{**gate, "status": "unknown", "reasons": ["Requires semantic data validation; not proved by schema inspection"]}
               for gate in cfg["review_gates"]]
    readiness = phase_readiness(checks)
    report = {"schema_version": 1, "case_id": cfg["case_id"], "checked_at": now(),
              "workflow_stage": "blocked_data" if "blocked" in readiness.values() else "awaiting_data_review",
              "learning_status": "candidate_experiment", "evidence_level": "local_data_audit",
              "local_reproduction": False, "automatic_trading_authorized": False,
              "readiness": readiness, "checks": checks,
              "next_action": next(c["next_action"] for c in checks if c["status"] != "passed")}
    write(folder / "inputs.json", results)
    write(folder / "report.json", report)
    (folder / "README.md").write_text(report_markdown(cfg, report))
    import pyarrow
    write(folder / "runtime.json", {"python": sys.version, "pyarrow": pyarrow.__version__,
                                   "case_sha256": sha256(out / "case.json")})
    write(folder / "manifest.json", manifest_files(folder))
    state = {k: v for k, v in report.items() if k != "checks"}
    completed = completed_checks(previous)
    completed[folder.relative_to(out).as_posix()] = sha256(folder / "manifest.json")
    state.update(latest_check=folder.relative_to(out).as_posix(),
                 manifest_sha256=sha256(folder / "manifest.json"), completed_checks=completed)
    write(out / "state.json", state)
    return state


def completed_checks(state):
    # The first local audit predates the history index; its selected manifest
    # was already pinned. Preserve that digest when advancing to later checks.
    return dict(state.get("completed_checks", {
        state["latest_check"]: state["manifest_sha256"]} if state["latest_check"] else {}))


def checked_folder(out, relative):
    path = Path(relative)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "checks" or ".." in path.parts:
        raise ValueError("Invalid audit path")
    return out / path


def verify(out):
    case = read(out / "case.json")
    verify_files(out / "registration", case["registration_artifacts"])
    cfg = read(out / "registration/protocol.json")
    validate(cfg)
    if any(case.get(key) != cfg[key] for key in ("case_id", "title", "source")):
        raise ValueError("Case identity differs from the frozen contract")
    state = read(out / "state.json")
    completed = completed_checks(state)
    for relative, digest in completed.items():
        folder = checked_folder(out, relative)
        if not (folder / "manifest.json").is_file() or sha256(folder / "manifest.json") != digest:
            raise ValueError(f"Completed audit missing or manifest changed: {relative}")
        verify_files(folder, read(folder / "manifest.json"), has_manifest=True)
        if read(folder / "runtime.json")["case_sha256"] != sha256(out / "case.json"):
            raise ValueError("Case identity changed")
    if state["latest_check"]:
        if state["latest_check"] not in completed:
            raise ValueError("Latest audit is not registered")
        folder = checked_folder(out, state["latest_check"])
        if sha256(folder / "manifest.json") != state["manifest_sha256"]:
            raise ValueError("Latest audit manifest changed")
        report = read(folder / "report.json")
        if any(state.get(key) != value for key, value in report.items() if key != "checks"):
            raise ValueError("State does not match checked evidence")
    elif completed or any(state.get(key) != value for key, value in {
            "workflow_stage": "registered", "learning_status": "candidate_experiment",
            "evidence_level": "source_review"}.items()):
        raise ValueError("Unexecuted case must retain its registered state")
    if state["local_reproduction"] or state["automatic_trading_authorized"]:
        raise ValueError("A data audit cannot authorize reproduction or trading")
    return state


def sync_index(root, out):
    state = verify(out)
    case = read(out / "case.json")
    index_path = root / "data/research_watch/research_case_state.json"
    index = read(index_path) if index_path.exists() else {"schema_version": 1, "cases": {}}
    # Each output directory is a distinct frozen version; preserve other cases/runs.
    key = hashlib.sha256(str(out.resolve()).encode()).hexdigest()[:16]
    index["cases"][key] = {"case_id": case["case_id"], "title": case["title"],
                           "source_key": case["source"]["key"],
                           "source_fingerprint": case["source"]["fingerprint"],
                           "case_path": str(out.resolve()), "state": state}
    write(index_path, index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["register", "check", "status", "verify"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cfg = read(args.config)
    validate(cfg)
    out = (args.output or ROOT / "data/research_cases" / cfg["case_id"]).resolve()
    if args.stage in {"status", "verify"}:
        state = verify(out)
        if read(out / "registration/protocol.json") != cfg:
            raise ValueError("Research contract changed; select its original config or a new output directory")
    else:
        lock_path = ROOT / "data/research_watch/.research-case.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # ponytail: one local lock serializes audits and shared-index writes.
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            register(ROOT, out, cfg)
            if args.stage == "check":
                try:
                    check(ROOT, out, cfg)
                except Exception as exc:
                    write(out / "last-error.json", {"at": now(), "error": str(exc),
                                                   "previous_state_retained": True})
                    raise
            sync_index(ROOT, out)
            state = verify(out)
    summary = {"case_path": str(out), **state}
    if (out / "last-error.json").exists():
        summary["last_error"] = read(out / "last-error.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if args.stage == "check" and state["workflow_stage"] != "ready_for_experiment" else 0


if __name__ == "__main__":
    raise SystemExit(main())
