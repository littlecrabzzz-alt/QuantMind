"""Bounded fresh-process JSON benchmark; metadata fixture, no network or database."""

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as m


def worker(mode, kind, count):
    text = {"ascii": "original", "bmp": "原始中文", "astral": "原始中文🙂"}[kind]
    value = {
        "files": {
            f"objects/{i:064x}.json": {"sha256": f"{i:064x}", "bytes": 4567}
            for i in range(count)
        },
        "partition_closure": {
            "schema_version": 1,
            "splits": [
                {
                    "parent_id": "a" * 64,
                    "children": [f"{i:064x}" for i in range(count * 3)],
                    "evidence": {"gap": text},
                }
            ],
        },
        "gaps": [
            {
                "id": str(i),
                "api_name": "unknown",
                "state": "gap",
                "params": {"code": text},
                "assessment": "empty",
            }
            for i in range(count // 4)
        ],
        "history_complete": False,
    }
    rss_unit = 1 if platform.system() == "Darwin" else 1024
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * rss_unit
    with ExitStack() as stack:
        root = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix="manifest-serialization-bench-")
            )
        )
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            stack.enter_context(
                patch(target, side_effect=AssertionError("offline only"))
            )
        start = time.monotonic()
        if mode == "legacy":
            raw = m.json_bytes(value)
            encoding = time.monotonic() - start
            sha = m.digest(raw)
            path = root / "manifest.json"
            m.atomic_bytes(path, raw)
            details = {"bytes": len(raw), "chunks": 1, "largest_chunk_bytes": len(raw)}
        else:
            details = {}
            path, sha = m.serialize_manifest_file(root, value, details)
            encoding = details["chunk_generation_seconds"]
        elapsed = time.monotonic() - start
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * rss_unit
        actual = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                actual.update(chunk)
        if actual.hexdigest() != sha:
            raise AssertionError("Written bytes differ from encoded digest")
        return {
            "mode": mode,
            "kind": kind,
            "files": count,
            "children": count * 3,
            "gaps": count // 4,
            "serialize_hash_write_fsync_seconds": elapsed,
            "largest_encoder_call_seconds": encoding,
            "rss_before_bytes": before,
            "rss_peak_bytes": peak,
            "sha256": sha,
            "details": details,
        }


def benchmark(count, repeats):
    rows = []
    for kind in ("ascii", "bmp", "astral"):
        for run in range(repeats):
            # Alternate order while each run has an isolated heap/process.
            for mode in ("legacy", "chunks") if run % 2 == 0 else ("chunks", "legacy"):
                result = subprocess.run(
                    [
                        sys.executable,
                        __file__,
                        "--worker",
                        mode,
                        "--kind",
                        kind,
                        "--count",
                        str(count),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                row = json.loads(result.stdout)
                rows.append({**row, "run": run})
    summaries = {}
    for kind in ("ascii", "bmp", "astral"):
        subset = [r for r in rows if r["kind"] == kind]
        if len({r["sha256"] for r in subset}) != 1:
            raise AssertionError("Legacy/chunks bytes mismatch")
        summaries[kind] = {}
        for mode in ("legacy", "chunks"):
            group = [r for r in subset if r["mode"] == mode]
            summaries[kind][mode] = {
                "median_seconds": statistics.median(
                    r["serialize_hash_write_fsync_seconds"] for r in group
                ),
                "max_seconds": max(
                    r["serialize_hash_write_fsync_seconds"] for r in group
                ),
                "max_encoder_call_seconds": max(
                    r["largest_encoder_call_seconds"] for r in group
                ),
                "max_rss_bytes": max(r["rss_peak_bytes"] for r in group),
            }
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scope": "synthetic large metadata, not production throughput/SLA",
        "upstream_calls": 0,
        "same_bytes_all_runs": True,
        "summaries": summaries,
        "runs": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=250000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output")
    parser.add_argument("--worker", choices=("legacy", "chunks"))
    parser.add_argument("--kind", choices=("ascii", "bmp", "astral"))
    args = parser.parse_args()
    if not 1 <= args.count <= 300000 or not 1 <= args.repeats <= 3:
        parser.error("Bounded count1..300000/repeats1..3 required")
    if args.worker:
        if not args.kind:
            parser.error("worker requires kind")
        print(json.dumps(worker(args.worker, args.kind, args.count)))
    else:
        if not args.output:
            parser.error("output required")
        output = Path(args.output).resolve()
        if output.exists() or output.parent != Path("/tmp").resolve():
            parser.error("output must be a new direct /tmp file")
        report = benchmark(args.count, args.repeats)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"output": str(output), "summaries": report["summaries"]}))
