#!/usr/bin/env python3
"""Offline acceptance for the live-verified fund catalogue pagination."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.shared import tushare_pipeline as module  # noqa: E402


CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_text())


class FundBasicPagination(unittest.TestCase):
    def test_limit_is_added_and_short_tail_is_terminal(self):
        offsets = []

        def handler(request):
            payload = json.loads(request.content)
            params = payload["params"]
            offsets.append(params.get("offset", 0))
            self.assertEqual(params["limit"], 2)
            codes = (
                ["000001.OF", "000002.OF"]
                if params.get("offset", 0) == 0
                else ["000003.OF"]
            )
            fields = payload["fields"].split(",")
            rows = [
                {"ts_code": code, "market": "O", "status": "L"}
                for code in codes
            ]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[row.get(field) for field in fields] for row in rows],
                        "has_more": params.get("offset", 0) == 0,
                    },
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            pagination = module.contract_for("fund_basic")["pagination"]
            with patch.dict(pagination, {"page_size": 2}):
                pipeline = module.Pipeline(tmp, CATALOG)
                self.addCleanup(pipeline.close)
                first = pipeline.enqueue(
                    "fund_basic",
                    {"market": "O", "status": "L"},
                    epoch="20260917",
                )
                stored = json.loads(
                    pipeline.db.execute(
                        "SELECT job FROM jobs WHERE id=?", (first,)
                    ).fetchone()[0]
                )
                self.assertEqual(stored["params"]["limit"], 2)
                pipeline.db.commit()
                with httpx.Client(
                    transport=httpx.MockTransport(handler), trust_env=False
                ) as client:
                    report = pipeline.run(
                        client,
                        "synthetic-test-token",
                        {"priority_start": "20200101"},
                        max_requests=2,
                        max_seconds=2,
                        pause=0,
                    )
                self.assertEqual(report["requests"], 2)
                self.assertEqual(offsets, [0, 2])
                tail = pipeline.db.execute(
                    "SELECT result FROM jobs "
                    "WHERE json_extract(job,'$.params.offset')=2"
                ).fetchone()
                self.assertTrue(json.loads(tail[0])["pagination_end"])
                self.assertEqual(pipeline.status(), {"done": 2})


if __name__ == "__main__":
    unittest.main()
