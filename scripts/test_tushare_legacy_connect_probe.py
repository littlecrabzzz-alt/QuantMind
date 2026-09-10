"""Synthetic fixed-file checks; no provider, credential, or production DB access."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from backend.shared.tushare_intake import digest, json_bytes
from backend.shared.tushare_pipeline import Pipeline

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "legacy_connect_probe", REPO / "scripts/tushare_legacy_connect_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LegacyConnectProbeTest(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(prefix="legacy-connect-probe-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / "root"
        root.mkdir()
        fields = ["exchange", "cal_date", "is_open"]
        rows = [
            ["SSE", "20220523", 1],
            ["SSE", "20220527", 1],
            ["SSE", "20260903", 1],
            ["SSE", "20260904", 1],
        ]
        raw = json_bytes({"code": 0, "data": {"fields": fields, "items": rows}})
        object_sha = digest(raw)
        object_name = f"objects/{object_sha}.json"
        (root / "objects").mkdir()
        (root / object_name).write_bytes(raw)
        observation = {
            "request": {"api_name": "trade_cal", "params": {"exchange": "SSE"}},
            "object_sha256": object_sha,
        }
        observed = json_bytes(observation)
        observation_name = "0" * 32 + ".json"
        (root / "observations").mkdir()
        (root / "observations" / observation_name).write_bytes(observed)
        files = {
            object_name: {"sha256": object_sha, "bytes": len(raw)},
            f"observations/{observation_name}": {
                "sha256": digest(observed),
                "bytes": len(observed),
            },
        }
        manifest = json_bytes({"files": files})
        release_id = "data-" + digest(manifest)
        release = root / "releases" / release_id
        release.mkdir(parents=True)
        (release / "manifest.json").write_bytes(manifest)
        recipe = {
            "release_id": release_id,
            "calendar": {
                "observations": {
                    "20220523": observation_name,
                    "20220527": observation_name,
                    "20260903": observation_name,
                    "20260904": observation_name,
                },
                "recent_start": "20260903",
                "recent_end": "20260904",
                "history_start": "20220523",
                "history_end": "20220527",
            },
        }
        seed = Path(temp.name) / "seeds.json"
        seed.write_bytes(json_bytes(recipe))
        return root, seed, digest(seed.read_bytes())

    def test_exact_four_request_plan_uses_fixed_calendar(self):
        root, seed, sha = self.fixture()
        planned, recipe = probe.seed_requests(root, seed, sha)
        self.assertEqual(
            planned,
            [
                ("moneyflow_hsgt", {"start_date": "20260903", "end_date": "20260904"}),
                ("ggt_daily", {"trade_date": "20260904"}),
                ("ggt_daily", {"start_date": "20220523", "end_date": "20220527"}),
                ("ggt_top10", {"trade_date": "20260904"}),
            ],
        )
        self.assertEqual(recipe["release_id"], root.joinpath("releases").iterdir().__next__().name)
        with self.assertRaisesRegex(ValueError, "Invalid frozen"):
            probe.seed_requests(root, seed, "0" * 64)

    def test_unverified_or_wide_dates_are_rejected(self):
        root, seed, _ = self.fixture()
        recipe = json.loads(seed.read_bytes())
        recipe["calendar"]["history_start"] = "20220501"
        seed.write_bytes(json_bytes(recipe))
        with self.assertRaisesRegex(ValueError, "calendar observation"):
            probe.seed_requests(root, seed, digest(seed.read_bytes()))

    def test_unknown_api_is_reserved_raw_only_and_unschedulable(self):
        temp = tempfile.TemporaryDirectory(prefix="legacy-connect-db-")
        self.addCleanup(temp.cleanup)
        pipeline = Pipeline(Path(temp.name), {"entries": []})
        self.addCleanup(pipeline.close)
        key, row = probe.reserve_probe(
            pipeline, "ggt_top10", {"trade_date": "20260904"}, "probe-slot"
        )
        job = json.loads(row["job"])
        self.assertEqual(row["state"], "probe_prepared")
        self.assertEqual(job["fields"], "")
        self.assertEqual(job["required_fields"], [])
        self.assertEqual(
            pipeline.db.execute("SELECT id FROM jobs WHERE state='pending'").fetchall(),
            [],
        )
        self.assertEqual(key, row["id"])

    def test_report_result_is_sanitized(self):
        result = probe.safe_result(
            {
                "status": "api_error",
                "message": "secret provider prose",
                "code": 50101,
                "object_sha256": "a" * 64,
                "observation": "b" * 32 + ".json",
                "observation_sha256": "c" * 64,
            }
        )
        self.assertNotIn("message", result)
        self.assertNotIn("code", result)
        self.assertEqual(result["status"], "api_error")


if __name__ == "__main__":
    unittest.main()
