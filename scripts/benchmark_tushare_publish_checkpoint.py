"""Metadata-only temporary benchmark, not a source completeness or SLA proof."""

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as m


def benchmark(count):
    if not 1 <= count <= 200000:
        raise ValueError("Fixture count must be bounded to 1..200000")
    with ExitStack() as stack:
        root = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix="publish-stage-bench-")
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
        seed = root / "seed"
        seed.mkdir()
        files = {
            f"objects/{i:064x}.json": {"sha256": f"{i:064x}", "bytes": 100}
            for i in range(count)
        }
        raw = m.json_bytes(
            {
                "schema_version": 1,
                "files": files,
                "datasets": [],
                "gaps": [],
                "archive": None,
            }
        )
        release = "data-" + hashlib.sha256(raw).hexdigest()
        m.atomic_bytes(seed / "releases" / release / "manifest.json", raw)
        m.atomic_json(
            seed / "CURRENT.json",
            {"release_id": release, "manifest_sha256": release[5:]},
        )
        del files, raw
        p = m.Pipeline(seed, {"entries": []})
        p.db.execute(
            "INSERT INTO partition_splits VALUES('fixture-parent','date',?,1,'{}','gap','fixture_missing_children')",
            (count,),
        )
        p.db.executemany(
            "INSERT INTO partition_children VALUES('fixture-parent',?)",
            ((f"{i:064x}",) for i in range(count)),
        )
        p.db.commit()
        p.close()
        reports = {}
        for mode in ("legacy", "staged"):
            target = root / mode
            shutil.copytree(seed, target)
            stages = []
            for _ in range(3 if mode == "staged" else 1):
                p = m.Pipeline(target, {"entries": []})
                try:
                    started = time.monotonic()
                    current = p.publish(staged=mode == "staged")
                    stages.append(
                        {
                            "seconds": time.monotonic() - started,
                            "release_id": current,
                            "step": p.publication_step,
                            "timing": p.publish_timing,
                        }
                    )
                finally:
                    p.close()
            path = target / "releases" / current / "manifest.json"
            reports[mode] = {
                "calls": stages,
                "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "manifest_bytes": path.stat().st_size,
            }
        equal = (
            reports["legacy"]["manifest_sha256"] == reports["staged"]["manifest_sha256"]
        )
        if not equal:
            raise AssertionError("Final manifest bytes differ")
        return {
            "scope": "synthetic metadata references, no physical source objects; not cloud timing",
            "files": count,
            "closure_children": count,
            "upstream_calls": 0,
            "manifest_bytes_equal": equal,
            "reports": reports,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists() or output.parent != Path("/tmp").resolve():
        raise ValueError("Benchmark output must be a new direct /tmp file")
    report = benchmark(args.count)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "manifest_bytes_equal": report["manifest_bytes_equal"],
            }
        )
    )
