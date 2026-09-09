"""Exact old/new publisher comparison; temporary roots, retained history, no network.

The old method is loaded from the locally available, reviewed a68c6d9 Git object.
No fetch is performed. This focused regression requires that baseline object.
"""

import ast
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import weakref
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_archive as archive
from backend.shared import tushare_pipeline as module
from scripts.test_tushare_archive import manifest as legacy_manifest

REPO = Path(__file__).resolve().parents[1]
BASELINE = "a68c6d9"


def old_publish():
    source = subprocess.check_output(
        ["git", "show", BASELINE + ":backend/shared/tushare_pipeline.py"],
        cwd=REPO,
        text=True,
    )
    tree = ast.parse(source)
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Pipeline"
    )
    method = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "publish"
    )
    namespace = dict(vars(module))
    exec(
        compile(
            ast.Module(body=[method], type_ignores=[]),
            "reviewed-publish-" + BASELINE,
            "exec",
        ),
        namespace,
    )
    return namespace["publish"]


class PublishEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = staticmethod(old_publish())

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            self.stack.enter_context(
                patch(name, side_effect=AssertionError("offline fixture only"))
            )
        self.stack.enter_context(
            patch.object(module, "utc_now", return_value="2026-09-09T00:00:00Z")
        )
        seed = self.tmp / "seed"
        p = module.Pipeline(seed, {"entries": []})
        try:
            # Two complete immutable observations of the same logical source row.
            for epoch, value in (("old", 1.0), ("revision", 2.0)):
                p.enqueue("fund_adj", {"trade_date": "20260904", "offset": 0, "limit": 1000}, epoch=epoch)
                with httpx.Client(
                    transport=httpx.MockTransport(
                        lambda _, v=value: httpx.Response(
                            200,
                            json={
                                "code": 0,
                                "data": {
                                    "fields": ["ts_code", "trade_date", "adj_factor"],
                                    "items": [["510300.SH", "20260904", v]],
                                },
                            },
                        )
                    )
                ) as client:
                    p.run(
                        client,
                        "fixture-no-secret",
                        {"priority_start": "20200101"},
                        max_requests=1,
                        pause=0,
                    )
            # Include every standard state plus unknown future states/APIs and
            # SQLite NULL scope; no whitelist or Python string sorting is valid.
            states = (
                "done",
                "pending",
                "empty",
                "blocked",
                "permission_blocked",
                "quality",
                "resolved",
                "split_pending",
                "deferred_legacy_period_plan",
                "future_state",
            )
            for i, api in enumerate(
                (None, "A_unknown", "daily", "z_future", "未来接口")
            ):
                for j, state in enumerate(states):
                    identity = f"fixture-{i}-{j}"
                    p.db.execute(
                        "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,result,group_name) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            identity,
                            identity,
                            "history",
                            json.dumps(
                                {
                                    "api_name": api,
                                    "params": {"note": "原始中文", "case": j},
                                },
                                ensure_ascii=False,
                            ),
                            45,
                            state,
                            json.dumps({"status": "saved_unknown_assessment"}),
                            "future_group",
                        ),
                    )
            p.db.execute(
                "INSERT INTO partition_splits VALUES('fixture-parent','date',2,1,?,'gap','child_not_complete')",
                (json.dumps({"dates": ["20260901", "20260902"]}),),
            )
            p.db.executemany(
                "INSERT INTO partition_children VALUES('fixture-parent',?)",
                [("child-z",), ("child-a",)],
            )
            p.db.execute(
                "INSERT INTO planning_state VALUES('history:future','20260909','fixed-signature',123,0)"
            )
            p.db.commit()
            # A legacy probe remains addressable through the immutable closure.
            self.probe, _ = legacy_manifest(
                seed, {"files": {}, "datasets": [], "results": []}, probe=True
            )
            for _ in range(30):
                result = archive.recover_archive(seed, max_items=100, max_seconds=5)
                if result["status"] != "recovering":
                    break
            self.assertNotEqual(result["status"], "recovering")
        finally:
            p.close()
        self.pairs = []
        for name in ("old", "new"):
            root = self.tmp / name
            shutil.copytree(seed, root)
            pipe = module.Pipeline(root, {"entries": []})
            self.addCleanup(pipe.close)
            self.pairs.append(pipe)

    def compare_publish(self):
        old, new = self.pairs
        left, right = self.legacy(old), new.publish()
        self.assertEqual(left, right)
        a = (old.root / f"releases/{left}/manifest.json").read_bytes()
        b = (new.root / f"releases/{right}/manifest.json").read_bytes()
        self.assertEqual(a, b)
        self.assertEqual(
            (old.root / "CURRENT.json").read_bytes(),
            (new.root / "CURRENT.json").read_bytes(),
        )
        return right, json.loads(b)

    def test_three_generations_noop_and_entire_history_are_byte_equal(self):
        releases = []
        for generation in range(3):
            if generation:
                for p in self.pairs:
                    p.db.execute(
                        "UPDATE jobs SET result=? WHERE id='fixture-3-9'",
                        (json.dumps({"status": "revision-" + str(generation)}),),
                    )
                    p.db.commit()
            release, manifest = self.compare_publish()
            releases.append(release)
            self.assertEqual(self.compare_publish()[0], release)
            self.assertEqual(
                manifest["scope"],
                [None, "A_unknown", "daily", "fund_adj", "z_future", "未来接口"],
            )
            self.assertIn("future_state", manifest["coverage"])
            self.assertEqual(
                manifest["partition_closure"]["splits"][0]["children"],
                ["child-a", "child-z"],
            )
            self.assertEqual(len(manifest["datasets"]), 2)
            self.assertEqual(
                sum(path.startswith("observations/") for path in manifest["files"]), 2
            )
            self.assertTrue(
                any(
                    gap["state"] == "deferred_legacy_period_plan"
                    for gap in manifest["gaps"]
                )
            )
            mappings = manifest["archive"]["recovery"]["archived_releases"]
            self.assertIn(self.probe, {item["release_id"] for item in mappings})
            for prior in releases[:-1]:
                self.assertIn(prior, {item["release_id"] for item in mappings})
                self.assertIn("archives/" + prior[5:] + ".json", manifest["files"])
            for name, meta in manifest["files"].items():
                for p in self.pairs:
                    raw = (p.root / name).read_bytes()
                    self.assertEqual(len(raw), meta["bytes"])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), meta["sha256"])
        self.assertEqual(len(set(releases)), 3)

    def test_serialization_failure_preserves_current_and_retry_bytes(self):
        first, _ = self.compare_publish()
        original = module.json_bytes

        def fail(value):
            if isinstance(value, dict) and "coverage_by_api" in value:
                raise MemoryError("synthetic serialization interruption")
            return original(value)

        for p, publish in zip(
            self.pairs, (self.legacy, lambda value: value.publish()), strict=True
        ):
            p.db.execute(
                "UPDATE jobs SET state='another_unknown_state' WHERE id='fixture-3-9'"
            )
            p.db.commit()
            pointer = (p.root / "CURRENT.json").read_bytes()
            # Old method globals are isolated by exec; patch its encoder too.
            with (
                patch.object(module, "json_bytes", side_effect=fail),
                patch.dict(self.legacy.__globals__, {"json_bytes": fail}),
            ):
                with self.assertRaises(MemoryError):
                    publish(p)
            self.assertEqual((p.root / "CURRENT.json").read_bytes(), pointer)
            self.assertEqual(p.publish_timing["failed_stage"], "serialize_manifest")
        second, _ = self.compare_publish()
        self.assertNotEqual(first, second)
        self.assertEqual(self.compare_publish()[0], second)

    def test_previous_manifest_is_released_at_final_serialization_only(self):
        self.compare_publish()
        original_read, original_encode = module.manifest_at, module.json_bytes

        class Tracked(dict):
            pass

        for p, publish, released in zip(
            self.pairs,
            (self.legacy, lambda value: value.publish()),
            (False, True),
            strict=True,
        ):
            refs, observed = [], []

            def tracked(*args, refs=refs):
                obj = Tracked(original_read(*args))
                refs.append(weakref.ref(obj))
                return obj

            def encode(value, refs=refs, observed=observed):
                if isinstance(value, dict) and "coverage_by_api" in value:
                    observed.append(refs[0]() is None)
                return original_encode(value)

            p.db.execute(
                "UPDATE jobs SET state='future_changed' WHERE id='fixture-3-9'"
            )
            p.db.commit()
            with (
                patch.object(module, "manifest_at", side_effect=tracked),
                patch.object(module, "json_bytes", side_effect=encode),
                patch.dict(
                    self.legacy.__globals__,
                    {"manifest_at": tracked, "json_bytes": encode},
                ),
            ):
                publish(p)
            self.assertEqual(observed, [released])
        self.compare_publish()


if __name__ == "__main__":
    unittest.main()
