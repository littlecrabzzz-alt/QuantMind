#!/usr/bin/env python3
"""Offline index_basic cap recovery; retained responses only, no credentials."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module  # noqa: E402


CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_text())
PUBLISHERS = ("中证指数有限公司", "中证指数有限公司、上海证券交易所")


class IndexBasicSaturation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pipeline = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)

    def response(self, _request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": ["ts_code", "publisher", "market"],
                    "items": [
                        ["000300.CSI", PUBLISHERS[0], "CSI"],
                        ["000905.CSI", PUBLISHERS[1], "CSI"],
                    ],
                    "has_more": True,
                },
            },
        )

    def capture(self, requests, handler=None):
        with httpx.Client(
            transport=httpx.MockTransport(handler or self.response)
        ) as client:
            return self.pipeline.run(
                client,
                "fixture-only",
                {"priority_start": "20200101"},
                max_requests=requests,
                pause=0,
            )

    def children(self, parent):
        return [
            json.loads(row[0])["params"]
            for row in self.pipeline.db.execute(
                "SELECT child.job FROM partition_children AS edge "
                "JOIN jobs AS child ON child.id=edge.child_id "
                "WHERE edge.parent_id=? ORDER BY child.id",
                (parent,),
            )
        ]

    def test_live_cap_partitions_by_observed_publishers(self):
        parent = self.pipeline.enqueue("index_basic", {"market": "CSI"})
        self.pipeline.db.commit()
        with patch.dict(module.EXTENDED_CONTRACTS["index_basic"], {"row_cap": 2}):
            report = self.capture(1)
        self.assertEqual(report["requests"], 1)
        self.assertEqual(
            self.children(parent),
            [
                {"market": "CSI", "publisher": publisher}
                for publisher in PUBLISHERS
            ],
        )
        split = self.pipeline.db.execute(
            "SELECT * FROM partition_splits WHERE parent_id=?", (parent,)
        ).fetchone()
        evidence = json.loads(split["evidence"])
        self.assertEqual(split["method"], "observed_value_fanout")
        self.assertEqual(split["coverage_proven"], 0)
        self.assertEqual(evidence["value_kind"], "supplier_text")
        self.assertEqual(evidence["observed_values"], list(PUBLISHERS))

    def test_legacy_blocked_parent_recovers_without_http(self):
        parent = self.pipeline.enqueue("index_basic", {"market": "CSI"})
        self.pipeline.db.commit()
        spec = module.EXTENDED_CONTRACTS["index_basic"]
        with patch.dict(
            spec,
            {
                "row_cap": 2,
                "saturation_fallback": None,
                "saturation_partition_param": None,
            },
        ):
            self.capture(1)
        before = self.pipeline.db.execute(
            "SELECT tries,result FROM jobs WHERE id=?", (parent,)
        ).fetchone()
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (parent,)
            ).fetchone()[0],
            "blocked",
        )
        report = self.capture(
            0,
            lambda _request: self.fail("legacy recovery must not call HTTP"),
        )
        self.assertTrue(report["partition_work"]["legacy_parent_recovered"])
        self.assertEqual(report["partition_work"]["upstream_calls"], 0)
        self.assertEqual(len(self.children(parent)), 2)
        after = self.pipeline.db.execute(
            "SELECT state,tries,result FROM jobs WHERE id=?", (parent,)
        ).fetchone()
        self.assertEqual(after["state"], "split_pending")
        self.assertEqual(after["tries"], before["tries"])
        self.assertEqual(
            json.loads(after["result"])["partition_recovery"]["upstream_calls"], 0
        )


if __name__ == "__main__":
    unittest.main()
