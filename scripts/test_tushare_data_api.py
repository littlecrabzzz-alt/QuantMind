"""Temp-only authenticated API checks against the real offline store.

During parallel development pass --backend-root PATH to the integration tree;
the router under test always comes from this script's own checkout. No secrets
or production paths are read. DuckDB, PyArrow, FastAPI and httpx are required.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

options = argparse.ArgumentParser(add_help=False)
options.add_argument(
    "--backend-root", type=Path, default=Path(__file__).resolve().parents[1]
)
args, remaining = options.parse_known_args()
sys.path.insert(0, str(args.backend_root.resolve()))
sys.argv = [sys.argv[0], *remaining]

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from backend.shared import tushare_pipeline, runtime_secrets  # noqa: E402

source = (
    Path(__file__).resolve().parents[1]
    / "backend/services/engine/routers/tushare_data.py"
)
spec = importlib.util.spec_from_file_location("candidate_tushare_data_api", source)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
PREFIX = "/api/v1/tushare-data"


class DataAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tushare-api-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.files = {}
        self.rows = [
            {
                "ts_code": f"SH{600000 + i}",
                "trade_date": "20260908",
                "close": float(i + 1),
                "title": "example",
                "_fetched_at": "2026-09-08T01:00:00+00:00",
                "_observation": "old",
            }
            for i in range(105)
        ]
        self.rows.append(
            {
                **self.rows[0],
                "close": 999.0,
                "_fetched_at": "2026-09-09T01:00:00+00:00",
                "_observation": "new",
            }
        )
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(self.rows), sink)
        self.parquet = self.put("parquet", "parquet", sink.getvalue().to_pybytes())
        self.html = self.put("attachments", "html", b'<script>alert("unsafe")</script>')
        self.text = self.put(
            "extracted",
            "json",
            json.dumps(
                {
                    "parse_status": "parsed",
                    "pages": [
                        {"page_number": 1, "text": "abcdef"},
                        {"page_number": 2, "text": "second"},
                    ],
                }
            ).encode(),
        )
        doc = self.put(
            "documents",
            "json",
            json.dumps(
                {
                    "files": [
                        {"path": self.html, **self.files[self.html]},
                        {"path": self.text, **self.files[self.text]},
                    ],
                    "mappings": [
                        {"id": 1, "api_name": "anns_d", "parse_status": "parsed"},
                        {"id": 2, "api_name": "anns_d", "parse_status": "failed"},
                    ],
                }
            ).encode(),
        )
        self.manifest = {
            "files": self.files.copy(),
            "datasets": [{"api_name": "fund_daily", "path": self.parquet}],
            "documents": {"path": doc},
            "coverage_by_api": [],
        }
        self.release = self.publish(self.manifest)
        self.addCleanup(patch.stopall)
        patch.object(api, "ROOT", self.root).start()
        # Fail any attempted provider credential access or network connection.
        self.no_connect = patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        ).start()
        self.no_dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        ).start()
        self.no_secret = patch.object(
            tushare_pipeline,
            "get_secret",
            side_effect=AssertionError("Secrets forbidden"),
        ).start()
        patch.object(
            runtime_secrets,
            "get_secret",
            side_effect=AssertionError("Secrets forbidden"),
        ).start()
        app = FastAPI()

        @app.middleware("http")
        async def test_identity(request: Request, call_next):
            if request.headers.get("x-test-identity") == "known":
                request.state.user = {"user_id": "reader", "tenant_id": "test"}
            return await call_next(request)

        app.include_router(api.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"x-test-identity": "known"}

    def tearDown(self):
        self.no_connect.assert_not_called()
        self.no_dns.assert_not_called()
        self.no_secret.assert_not_called()

    def put(self, family, suffix, raw):
        digest = hashlib.sha256(raw).hexdigest()
        path = f"{family}/{digest}.{suffix}"
        target = self.root / path
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(raw)
        self.files[path] = {"sha256": digest, "bytes": len(raw)}
        return path

    def publish(self, manifest):
        raw = json.dumps(manifest, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        release = "data-" + digest
        target = self.root / "releases" / release / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        (self.root / "CURRENT.json").write_text(
            json.dumps({"release_id": release, "manifest_sha256": digest})
        )
        return release

    def get(self, route, **params):
        return self.client.get(
            PREFIX + route,
            params={"release_id": self.release, **params},
            headers=self.headers,
        )

    def query(self, **body):
        return self.client.post(
            PREFIX + "/query",
            json={"release_id": self.release, "api_name": "fund_daily", **body},
            headers=self.headers,
        )

    def test_auth_and_explicit_release(self):
        for route in (
            "/current",
            "/datasets",
            "/datasets/fund_daily/schema",
            "/documents",
            "/documents/text",
        ):
            response = self.client.get(
                PREFIX + route, params={"release_id": self.release, "path": self.text}
            )
            self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(
            self.client.post(
                PREFIX + "/query",
                json={"release_id": self.release, "api_name": "fund_daily"},
            ).status_code,
            401,
        )
        for route in (
            "/datasets",
            "/datasets/fund_daily/schema",
            "/documents",
            "/documents/text",
        ):
            self.assertEqual(
                self.client.get(PREFIX + route, headers=self.headers).status_code, 422
            )
        self.assertEqual(
            self.client.post(
                PREFIX + "/query", json={"api_name": "fund_daily"}, headers=self.headers
            ).status_code,
            422,
        )

    def test_fixed_catalog_schema_and_query(self):
        self.assertEqual(self.get("/current").json()["release_id"], self.release)
        self.assertEqual(self.get("/datasets").json()["datasets"][0]["partitions"], 1)
        schema = self.get("/datasets/fund_daily/schema").json()
        self.assertIn("close", [f["name"] for f in schema["fields"]])
        default = self.query()
        self.assertEqual(default.status_code, 200, default.text)
        self.assertEqual(default.json()["returned_rows"], 100)
        self.assertEqual(default.json()["metadata"]["upstream_calls"], 0)
        selected = {
            "fields": ["ts_code", "close"],
            "codes": ["SH600000"],
            "start_date": "20260908",
            "end_date": "2026-09-08",
        }
        self.assertEqual(
            self.query(**selected).json()["rows"],
            [{"ts_code": "SH600000", "close": 999.0}],
        )
        old = self.query(**selected, as_of="2026-09-08T12:00:00Z")
        self.assertEqual(old.json()["rows"][0]["close"], 1.0)
        new_release = self.publish({"files": {}, "datasets": []})
        self.assertNotEqual(new_release, self.release)
        self.assertEqual(self.get("/current").json()["release_id"], new_release)
        self.assertEqual(self.query(**selected).json()["rows"][0]["close"], 999.0)
        self.assertEqual(self.query(limit=2001).status_code, 422)
        self.assertEqual(self.query(limit=True).status_code, 422)
        self.assertEqual(self.query(url="https://example.com").status_code, 422)

    def test_sql_and_path_escape_rejected(self):
        for filters in (
            {"fields": ["close); DROP TABLE stored;--"]},
            {"date_field": "trade_date OR 1=1", "start_date": "20260908"},
            {"code_field": "ts_code) OR TRUE--", "codes": ["SH600000"]},
            {"keyword_fields": ["title;SELECT 1"], "keyword": "x"},
            {"api_name": "read_parquet('https://example.com')"},
        ):
            response = self.query(**filters)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            self.query(keyword="' OR TRUE --", keyword_fields=["title"]).json()["rows"],
            [],
        )
        self.assertEqual(self.query(codes=["SH600000' OR TRUE --"]).json()["rows"], [])
        for path in (
            "../CURRENT.json",
            "/etc/passwd",
            "https://example.com/a",
            "attachments/../CURRENT.json",
        ):
            self.assertEqual(self.get("/documents/text", path=path).status_code, 422)
        self.assertEqual(
            self.get("/datasets", release_id="../outside").status_code, 422
        )
        orphan = self.put("attachments", "html", b"not included")
        self.assertEqual(self.get("/documents/text", path=orphan).status_code, 404)

    def test_document_metadata_and_complete_text_pagination(self):
        first = self.get("/documents", limit=1).json()
        self.assertEqual(first["next_offset"], 1)
        second = self.get("/documents", offset=1, limit=1).json()
        self.assertEqual(second["items"][0]["parse_status"], "failed")
        self.assertIsNone(second["next_offset"])
        self.assertEqual(self.get("/documents", view="files").json()["total"], 2)
        page = self.get(
            "/documents/text", path=self.text, page_size=1, max_chars=3
        ).json()
        self.assertEqual(page["pages"][0]["text"], "abc")
        self.assertEqual(page["pages"][0]["next_char_offset"], 3)
        self.assertEqual(page["next_page"], 2)
        tail = self.get(
            "/documents/text", path=self.text, page_size=1, char_offset=3
        ).json()
        self.assertEqual(tail["pages"][0]["text"], "def")
        self.assertIsNone(tail["pages"][0]["next_char_offset"])
        self.assertEqual(
            self.get("/documents/text", path=self.text, page=2).json()["pages"][0][
                "text"
            ],
            "second",
        )
        html = self.get("/documents/text", path=self.html)
        self.assertEqual(html.headers["content-type"], "application/json")
        self.assertEqual(html.headers["x-content-type-options"], "nosniff")
        self.assertEqual(
            html.json()["pages"][0]["text"], '<script>alert("unsafe")</script>'
        )

    def test_partition_and_inventory_tampering(self):
        partition = self.root / self.parquet
        raw = partition.read_bytes()
        partition.write_bytes(b"x" * len(raw))
        self.assertEqual(self.query().status_code, 400)
        partition.unlink()
        outside = self.root / "outside.parquet"
        outside.write_bytes(raw)
        partition.symlink_to(outside)
        self.assertEqual(self.query().status_code, 400)
        inventory = self.root / self.manifest["documents"]["path"]
        inventory.write_bytes(b"{}")
        self.assertEqual(self.get("/documents").status_code, 409)
        self.assertEqual(self.query(api_name="stock_basic").status_code, 400)

    def test_corruption_and_symlinks(self):
        target = self.root / self.text
        raw = target.read_bytes()
        target.write_bytes(b"x" * len(raw))
        self.assertEqual(self.get("/documents/text", path=self.text).status_code, 409)
        target.unlink()
        outside = self.root / "outside.json"
        outside.write_bytes(raw)
        target.symlink_to(outside)
        self.assertEqual(self.get("/documents/text", path=self.text).status_code, 409)
        target.unlink()
        target.write_bytes(raw)
        directory = target.parent
        moved = directory.with_name("other-extracted")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.get("/documents/text", path=self.text).status_code, 409)
        manifest = self.root / "releases" / self.release / "manifest.json"
        manifest_raw = manifest.read_bytes()
        manifest.write_bytes(b"x" * len(manifest_raw))
        self.assertEqual(self.get("/datasets").status_code, 400)
        manifest.unlink()
        outside.write_bytes(manifest_raw)
        manifest.symlink_to(outside)
        self.assertEqual(self.get("/datasets").status_code, 409)


if __name__ == "__main__":
    unittest.main()
