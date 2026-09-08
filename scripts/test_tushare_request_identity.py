#!/usr/bin/env python3
"""Offline immutable request provenance and non-collapsing row identity checks."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.shared.tushare_pipeline as pipeline_module  # noqa: E402
import backend.shared.tushare_store as store  # noqa: E402
from backend.shared.tushare_research_extra_contracts import RESEARCH_EXTRA_CONTRACTS  # noqa: E402

SPEC = RESEARCH_EXTRA_CONTRACTS["fina_mainbz"]
API = "fina_mainbz"
ROW = {
    "ts_code": "600018.SH",
    "end_date": "20260630",
    "bz_item": "主营业务",
    "bz_code": None,
    "curr_type": "CNY",
    "bz_sales": 10.0,
    "bz_profit": 2.0,
    "bz_cost": 8.0,
    "update_flag": "0",
}


def raw_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RequestIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.pipeline = pipeline_module.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.pipeline.close)
        original = pipeline_module.contract_for
        guards = [
            patch.object(
                pipeline_module,
                "contract_for",
                side_effect=lambda api: SPEC if api == API else original(api),
            ),
            patch.dict(store.KEYS, {API: tuple(SPEC["keys"])}),
            patch.dict(store.CONTRACTS, {API: SPEC}),
            patch.object(
                socket.socket, "connect", side_effect=AssertionError("No network")
            ),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")),
        ]
        for guard in guards:
            guard.start()
            self.addCleanup(guard.stop)
        self.fixtures = []

    def capture(
        self, kind="P", row=None, legacy=False, fetched="2026-09-09T01:00:00+00:00"
    ):
        row = deepcopy(ROW if row is None else row)
        payload = raw_json(
            {"code": 0, "data": {"fields": list(row), "items": [list(row.values())]}}
        )
        object_sha = sha(payload)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (object_sha + ".json")).write_bytes(payload)
        params = {"ts_code": "600018.SH"}
        if kind is not None:
            params["type"] = kind
        observed = {
            "request": {"api_name": API, "params": params},
            "fetched_at": fetched,
            "object_sha256": object_sha,
        }
        raw = raw_json(observed)
        observation = uuid4().hex + ".json"
        (self.root / "observations").mkdir(exist_ok=True)
        (self.root / "observations" / observation).write_bytes(raw)
        result = {
            "api_name": API,
            "observation": observation,
            "observation_sha256": sha(raw),
            "object_sha256": object_sha,
            "status": "sample_ok",
        }
        self.pipeline.normalize(result)
        if legacy:
            normalized = pq.read_table(
                self.root / result["parquet"]["path"]
            ).to_pylist()[0]
            normalized = {
                k: v
                for k, v in normalized.items()
                if not k.startswith("_request_") and k != "_raw_row_identity"
            }
            normalized["_row_identity"] = sha(raw_json(row))
            result["parquet"] = self.parquet([normalized])
        self.fixtures.append(result)
        return result

    def parquet(self, rows):
        temporary = self.root / "temp.parquet"
        pq.write_table(pa.Table.from_pylist(rows), temporary)
        raw = temporary.read_bytes()
        path = "parquet/" + sha(raw) + ".parquet"
        temporary.rename(self.root / path)
        return {"path": path, "sha256": sha(raw), "bytes": len(raw)}

    def release(self, results=None, omit=()):
        files, datasets = {}, []
        for result in results or self.fixtures:
            pqmeta = result["parquet"]
            datasets.append({"api_name": API, "quality_state": "sample_ok", **pqmeta})
            for name in (
                pqmeta["path"],
                "observations/" + result["observation"],
                "objects/" + result["object_sha256"] + ".json",
            ):
                if name in omit:
                    continue
                raw = (self.root / name).read_bytes()
                files[name] = {"sha256": sha(raw), "bytes": len(raw)}
        raw = raw_json({"files": files, "datasets": datasets})
        release = "data-" + sha(raw)
        destination = self.root / "releases" / release / "manifest.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return release

    def test_pdi_same_payload_separate_but_same_type_reobservation_deduplicates(self):
        captures = [self.capture(kind) for kind in ("P", "D", "I", "P")]
        rows = [
            pq.read_table(self.root / r["parquet"]["path"]).to_pylist()[0]
            for r in captures
        ]
        self.assertEqual(len({r["_raw_row_identity"] for r in rows}), 1)
        self.assertEqual(len({r["_row_identity"] for r in rows}), 3)
        self.assertEqual(rows[0]["source_ts_code"], "600018.SH")
        self.assertEqual(rows[0]["ts_code"], "SH600018")
        self.assertTrue(all(r["bz_code"] is None for r in rows))
        table = store.read_dataset(self.root, self.release(), API)
        self.assertEqual(table.num_rows, 3)
        self.assertEqual(
            {json.loads(r["_request_identity"])["type"] for r in table.to_pylist()},
            {"P", "D", "I"},
        )
        metadata = json.loads(table.schema.metadata[b"tushare"])
        self.assertEqual(
            metadata["request_identity_status"], "verified_from_immutable_observations"
        )
        for captured in captures:
            request = json.loads(
                (self.root / "observations" / captured["observation"]).read_bytes()
            )["request"]
            self.assertFalse(any(k.startswith("_") for k in request["params"]))

    def test_legacy_identity_recovers_without_rewriting_and_matches_new_protocol(self):
        results = [
            self.capture("P", legacy=True),
            self.capture("D", legacy=True),
            self.capture("P"),
        ]
        release = self.release()
        before = {
            p: (self.root / p).read_bytes()
            for p in json.loads(
                (self.root / "releases" / release / "manifest.json").read_bytes()
            )["files"]
        }
        result = store.read_dataset(self.root, release, API)
        self.assertEqual(result.num_rows, 2)
        self.assertEqual(
            {json.loads(r["_request_identity"])["type"] for r in result.to_pylist()},
            {"P", "D"},
        )
        self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})
        self.assertEqual(len(results), 3)

    def test_missing_type_stays_incomplete_and_reader_refuses_to_guess_from_bz_code(
        self,
    ):
        for kind in (None, ""):
            with self.subTest(kind=kind):
                result = self.capture(kind, row={**ROW, "bz_code": "P"})
                row = pq.read_table(self.root / result["parquet"]["path"]).to_pylist()[
                    0
                ]
                self.assertEqual(row["_request_identity_status"], "incomplete")
                self.assertEqual(json.loads(row["_request_identity_missing"]), ["type"])
                with self.assertRaisesRegex(
                    ValueError, "Request identity gap: missing request fields type"
                ):
                    store.read_dataset(self.root, self.release([result]), API)

    def test_missing_outside_release_tampered_and_wrong_api_observations_fail_closed(
        self,
    ):
        captured = self.capture("P", legacy=True)
        name = "observations/" + captured["observation"]
        with self.assertRaisesRegex(ValueError, "observation outside fixed release"):
            store.read_dataset(self.root, self.release(omit=[name]), API)
        release = self.release()
        path = self.root / name
        original = path.read_bytes()
        path.write_bytes(original.replace(b'"type": "P"', b'"type": "D"'))
        self.assertEqual(path.stat().st_size, len(original))
        with self.assertRaisesRegex(ValueError, "observation checksum mismatch"):
            store.read_dataset(self.root, release, API)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "observation unavailable"):
            store.read_dataset(self.root, release, API)
        wrong = json.loads(original)
        wrong["request"]["api_name"] = "report_rc"
        path.write_bytes(raw_json(wrong))
        with self.assertRaisesRegex(ValueError, "observation API mismatch"):
            store.read_dataset(self.root, self.release(), API)

    def test_stored_request_provenance_mismatch_rejected_and_versions_retained(self):
        capture = self.capture("P")
        row = pq.read_table(self.root / capture["parquet"]["path"]).to_pylist()[0]
        row["_request_identity"] = json.dumps({"type": "D"}, sort_keys=True)
        corrupt = {**capture, "parquet": self.parquet([row])}
        with self.assertRaisesRegex(ValueError, "stored provenance conflicts"):
            store.read_dataset(self.root, self.release([corrupt]), API)
        self.capture("P", row={**ROW, "bz_sales": 11.0})
        self.assertEqual(store.read_dataset(self.root, self.release(), API).num_rows, 2)

    def test_partial_modern_provenance_and_symlink_are_not_reinterpreted_as_legacy(
        self,
    ):
        captured = self.capture("P")
        original = pq.read_table(self.root / captured["parquet"]["path"]).to_pylist()[0]
        for field in (
            "_raw_row_identity",
            "_request_identity_status",
            "_request_identity_missing",
        ):
            changed = {k: v for k, v in original.items() if k != field}
            bad = {**captured, "parquet": self.parquet([changed])}
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "Request identity gap"),
            ):
                store.read_dataset(self.root, self.release([bad]), API)
        badrow = {**original, "_row_identity": "a" * 64}
        with self.assertRaisesRegex(ValueError, "inconsistent modern provenance"):
            store.read_dataset(
                self.root,
                self.release([{**captured, "parquet": self.parquet([badrow])}]),
                API,
            )
        release = self.release()
        observation = self.root / "observations" / captured["observation"]
        copy = self.root / "outside.json"
        observation.rename(copy)
        observation.symlink_to(copy)
        with self.assertRaisesRegex(ValueError, "unsafe observation path"):
            store.read_dataset(self.root, release, API)

    def test_non_request_identity_contract_keeps_existing_payload_hash(self):
        with patch.object(pipeline_module, "contract_for", return_value={}):
            result = self.capture("P")
        row = pq.read_table(self.root / result["parquet"]["path"]).to_pylist()[0]
        self.assertEqual(row["_row_identity"], sha(raw_json(ROW)))
        self.assertNotIn("_request_identity", row)


if __name__ == "__main__":
    unittest.main()
