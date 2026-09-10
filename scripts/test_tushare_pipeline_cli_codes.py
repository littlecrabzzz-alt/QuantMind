"""Offline CLI code-field selection across index, stock and fund datasets."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import Pipeline
from scripts.test_tushare_pipeline import CATALOG, CONFIG


class PipelineCliCodeTest(unittest.TestCase):
    def test_contract_default_and_explicit_source_codes(self):
        rows = {
            "index_weight": (
                ["index_code", "con_code", "trade_date", "weight"],
                [["000300.SH", "600000.SH", "20260901", 1.5]],
            ),
            "daily": (
                ["ts_code", "trade_date", "close"],
                [["600000.SH", "20260901", 10.0]],
            ),
            "fund_adj": (
                ["ts_code", "trade_date", "adj_factor"],
                [["510300.SH", "20260901", 1.0]],
            ),
        }

        def response(request):
            api = json.loads(request.content)["api_name"]
            fields, items = rows[api]
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": items}}
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            pipeline = Pipeline(root, CATALOG)
            pipeline.enqueue(
                "index_weight",
                {
                    "index_code": "000300.SH",
                    "start_date": "20260901",
                    "end_date": "20260901",
                },
            )
            pipeline.enqueue("daily", {"trade_date": "20260901"})
            pipeline.enqueue(
                "fund_adj",
                {"trade_date": "20260901", "offset": 0, "limit": 1000},
            )
            pipeline.db.commit()
            with httpx.Client(transport=httpx.MockTransport(response)) as client:
                pipeline.run(client, "synthetic-token", CONFIG, max_requests=3, pause=0)
            release = pipeline.publish()
            pipeline.close()

            internal = self.cli(
                root, release, "query", "index_weight", "--codes", "SH000300"
            )
            self.assertEqual(internal["rows"], 1)

            source = self.cli(
                root,
                release,
                "query",
                "index_weight",
                "--codes",
                "000300.SH",
                "--code-field",
                "source_index_code",
                "--show-rows",
            )
            self.assertEqual(source["data"][0]["index_code"], "SH000300")
            self.assertEqual(source["data"][0]["source_index_code"], "000300.SH")

            for api, code in (("daily", "SH600000"), ("fund_adj", "SH510300")):
                self.assertEqual(
                    self.cli(root, release, "query", api, "--codes", code)["rows"],
                    1,
                )

            destination = Path(tmp) / "index-weight.jsonl"
            exported = self.cli(
                root,
                release,
                "export",
                "index_weight",
                "--codes",
                "SH000300",
                "--destination",
                str(destination),
            )
            self.assertEqual(exported["rows"], 1)
            self.assertEqual(
                json.loads(destination.read_text())["index_code"], "SH000300"
            )

    def cli(self, root, release, command, api, *arguments):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("tushare_pipeline.py")),
                command,
                "--root",
                str(root),
                "--release-id",
                release,
                "--api-name",
                api,
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
