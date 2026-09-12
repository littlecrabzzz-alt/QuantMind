"""Offline intake acceptance: no environment secrets, services or network."""

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_intake import (
    DocParser,
    assess_response,
    capture_sample,
    json_bytes,
    parse_document,
    read_samples,
    verify_release,
)
from scripts.tushare_intake import probe_jobs


class IntakeAcceptance(unittest.TestCase):
    def test_committed_catalog_prepares_all_reviewed_probes(self):
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_text()
        )
        jobs = probe_jobs(catalog, "20260907", "SH510300", "20260630")
        self.assertEqual(len(jobs), 10)
        self.assertEqual(
            {j["params"]["is_new"] for j in jobs if j["api_name"] == "ci_index_member"},
            {"Y", "N"},
        )
        self.assertEqual(
            {j["params"]["list_status"] for j in jobs if j["api_name"] == "etf_basic"},
            {"L", "D", "P"},
        )
        self.assertEqual(jobs[-1]["api_name"], "fund_portfolio")
        self.assertTrue(jobs[-1]["params"]["ts_code"].endswith(".SH"))
        self.assertEqual(jobs[-1]["params"]["period"], "20260630")
        with self.assertRaises(ValueError):
            probe_jobs(catalog, "20260907", "SH510300", "20260629")
        self.assertTrue(
            all(e["coverage_status"] == "not_ingested" for e in catalog["entries"])
        )

    def test_document_and_hidden_fields(self):
        html = """<div id="jstree"><a href="/document/2?doc_id=9">A</a></div>
        <div class="content col-md-9"><p>接口：example<br>描述：text</p>
        <p><strong>输入参数</strong></p><table><tr><th>名称</th></tr>
        <tr><td>date</td></tr></table><p>输出参数</p><table>
        <tr><th>名称</th><th>默认显示</th></tr><tr><td>title</td><td>Y</td></tr>
        <tr><td>content</td><td>N</td></tr>
        <tr><td>1w</td><td>Y</td></tr><tr><td>3day</td><td>N</td></tr>
        <tr><td>1w</td><td>Y</td></tr>
        <tr><td>bad;column</td><td>Y</td></tr></table></div>
        <div class="content">接口：footer</div>"""
        parser = DocParser()
        parser.feed(html)
        self.assertEqual(parser.links, {"9": "A"})
        result = parse_document(html, 9, "A")
        self.assertEqual(result["api_names"], ["example"])
        self.assertEqual(result["input_fields"], ["date"])
        self.assertEqual(result["output_fields"], ["title", "content", "1w", "3day"])

    def test_schema_cap_empty_and_permission_are_distinct(self):
        price_check = assess_response(
            {
                "code": 0,
                "data": {"fields": ["open"], "items": [[0], [-1], [float("nan")]]},
            },
            4000,
            ["open"],
            positive_fields=["open"],
        )
        self.assertEqual(price_check["status"], "invalid_values")
        self.assertEqual(price_check["invalid_positive_counts"], {"open": 3})

        def assess(items, fields=("open",), cap=2, required=("open",), nullable=()):
            return assess_response(
                {"code": 0, "data": {"fields": list(fields), "items": items}},
                cap,
                required,
                nullable,
            )

        self.assertEqual(assess([])["status"], "empty_unverified")
        self.assertEqual(assess([[None]])["status"], "schema_gap")
        self.assertEqual(assess([[1], [2]])["status"], "possibly_truncated")
        self.assertEqual(assess([[1]], fields=("close",))["status"], "schema_gap")
        self.assertEqual(assess([[1, 2]])["status"], "invalid_response")
        self.assertEqual(
            assess(
                [[None]],
                fields=("out_date",),
                required=("out_date",),
                nullable=("out_date",),
            )["status"],
            "sample_ok",
        )
        result = assess([[1]])
        self.assertFalse(result["history_complete"])
        self.assertFalse(result["pit_verified"])
        self.assertEqual(
            assess_response({"code": 2002}, 2, [])["status"], "permission_denied"
        )
        self.assertEqual(
            assess_response({"code": 40203}, 2, [])["status"], "permission_denied"
        )

    def test_supplier_continuation_flag_prevents_false_complete_short_page(self):
        for items in ([[1]], []):
            result = assess_response(
                {
                    "code": 0,
                    "data": {
                        "fields": ["open"],
                        "items": items,
                        "has_more": True,
                        "count": 0,
                    },
                },
                6000,
                ["open"],
            )
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertTrue(result["supplier_has_more"])
            self.assertEqual(result["row_count"], len(items))
        result = assess_response(
            {
                "code": 0,
                "data": {
                    "fields": ["open"],
                    "items": [[1]],
                    "has_more": False,
                },
            },
            6000,
            ["open"],
        )
        self.assertEqual(result["status"], "sample_ok")
        self.assertFalse(result["supplier_has_more"])

    def test_cyq_chips_exact_supplier_empty_is_narrow_and_archived(self):
        empty = {
            "code": 50101,
            "msg": "指定数据不存在，请确认参数！",
            "data": None,
        }

        def capture(api="cyq_chips", params=None, payload=empty, http_status=200):
            job = {
                "api_name": api,
                "params": params
                if params is not None
                else {"ts_code": "600001.SH", "trade_date": "20260904"},
                "fields": "ts_code,trade_date,price,percent",
                "required_fields": ["ts_code", "trade_date", "price", "percent"],
                "row_cap": 6000,
            }
            root = Path(directory)
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(http_status, json=payload)
                )
            ) as client:
                return capture_sample(client, "synthetic-test-token", job, root), root

        with tempfile.TemporaryDirectory() as directory:
            for code in ("600001.SH", "T600001.SH", "830001.BJ"):
                result, root = capture(
                    params={"ts_code": code, "trade_date": "20240229"}
                )
                self.assertEqual(result["status"], "empty_unverified")
                self.assertEqual(result["code"], 50101)
                self.assertEqual(result["row_count"], 0)
                self.assertTrue(result["supplier_empty_hint"])
                self.assertFalse(result["coverage_proven"])
                self.assertFalse(result["history_complete"])
                self.assertFalse(result["pit_verified"])
                observation = json.loads(
                    (root / "observations" / result["observation"]).read_bytes()
                )
                self.assertEqual(observation["assessment"]["code"], 50101)
                raw = json.loads(
                    (
                        root / "objects" / (result["object_sha256"] + ".json")
                    ).read_bytes()
                )
                self.assertEqual(raw, empty)

            negative_cases = (
                ("nearby message", "cyq_chips", None, {**empty, "msg": "指定数据不存在，请检查参数！"}, 200, "api_error"),
                ("nearby code", "cyq_chips", None, {**empty, "code": 50102}, 200, "api_error"),
                ("missing data", "cyq_chips", None, {"code": 50101, "msg": empty["msg"]}, 200, "api_error"),
                ("another api", "cyq_perf", None, empty, 200, "api_error"),
                ("http 429", "cyq_chips", None, empty, 429, "rate_limited"),
                ("http 500", "cyq_chips", None, empty, 500, "transport_error"),
                ("real rows", "cyq_chips", None, {**empty, "data": {"fields": ["ts_code"], "items": [["600001.SH"]]}}, 200, "api_error"),
                ("permission", "cyq_chips", None, {"code": 2002, "msg": "无权限", "data": None}, 200, "permission_denied"),
                ("missing date", "cyq_chips", {"ts_code": "600001.SH"}, empty, 200, "api_error"),
                ("range shape", "cyq_chips", {"ts_code": "600001.SH", "start_date": "20260904", "end_date": "20260904"}, empty, 200, "api_error"),
                ("bad code", "cyq_chips", {"ts_code": "SH600001", "trade_date": "20260904"}, empty, 200, "api_error"),
                ("non-string code", "cyq_chips", {"ts_code": 600001, "trade_date": "20260904"}, empty, 200, "api_error"),
                ("bad date", "cyq_chips", {"ts_code": "600001.SH", "trade_date": "20260229"}, empty, 200, "api_error"),
                ("short date", "cyq_chips", {"ts_code": "600001.SH", "trade_date": "202611"}, empty, 200, "api_error"),
                ("numeric date", "cyq_chips", {"ts_code": "600001.SH", "trade_date": 20260904}, empty, 200, "api_error"),
                ("string code", "cyq_chips", None, {**empty, "code": "50101"}, 200, "api_error"),
                ("boolean code", "cyq_chips", None, {**empty, "code": True}, 200, "api_error"),
                ("data dict", "cyq_chips", None, {**empty, "data": {}}, 200, "api_error"),
                ("extra param", "cyq_chips", {"ts_code": "600001.SH", "trade_date": "20260904", "unknown": "value"}, empty, 200, "api_error"),
            )
            for name, api, params, payload, status, expected in negative_cases:
                with self.subTest(name=name):
                    result, _ = capture(api, params, payload, status)
                    self.assertEqual(result["status"], expected)
                    self.assertNotIn("supplier_empty_hint", result)

            success, _ = capture(
                payload={
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "trade_date", "price", "percent"],
                        "items": [["600001.SH", "20260904", 10.0, 1.0]],
                    },
                }
            )
            self.assertEqual(success["status"], "sample_ok")
            self.assertNotIn("supplier_empty_hint", success)
            normal_empty, _ = capture(
                payload={
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "trade_date", "price", "percent"],
                        "items": [],
                    },
                }
            )
            self.assertEqual(normal_empty["status"], "empty_unverified")
            self.assertNotIn("supplier_empty_hint", normal_empty)
            invalid, _ = capture(payload=[])
            self.assertEqual(invalid["status"], "invalid_response")

    def test_observations_preserve_revisions_and_mirror_integrity(self):
        responses = [
            {
                "code": 0,
                "data": {"fields": ["close", "future_field"], "items": [[1, "extra"]]},
            },
            {
                "code": 0,
                "data": {
                    "fields": ["close", "future_field"],
                    "items": [[2, "revision"]],
                },
            },
        ]
        job = {
            "api_name": "ci_daily",
            "params": {"trade_date": "20260907"},
            "fields": "close",
            "required_fields": ["close"],
            "row_cap": 4000,
        }
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=responses[min(len(seen) - 1, 1)])

        with (
            tempfile.TemporaryDirectory() as directory,
            httpx.Client(
                transport=httpx.MockTransport(handler),
                trust_env=False,
            ) as client,
        ):
            root = Path(directory)
            results = [
                capture_sample(client, "synthetic-test-token", job, root)
                for _ in range(3)
            ]
            self.assertEqual(len(list((root / "objects").glob("*.json"))), 2)
            self.assertEqual(len(list((root / "observations").glob("*.json"))), 3)
            self.assertEqual(seen[0]["token"], "synthetic-test-token")
            for path in root.rglob("*.json"):
                self.assertNotIn(b"synthetic-test-token", path.read_bytes())
            raw = json.loads(
                (
                    root / "objects" / (results[0]["object_sha256"] + ".json")
                ).read_bytes()
            )
            self.assertIn("future_field", raw["data"]["fields"])
            release = "probe-" + "a" * 32
            destination = root / "releases" / release
            destination.mkdir(parents=True)
            (destination / "manifest.json").write_bytes(
                json_bytes({"results": results})
            )
            self.assertEqual(verify_release(root, release)["observations"], 3)
            with (
                patch(
                    "socket.socket.connect",
                    side_effect=AssertionError("network forbidden"),
                ),
                patch(
                    "backend.shared.runtime_secrets.get_secret",
                    side_effect=AssertionError("secret forbidden"),
                ),
            ):
                samples = read_samples(root, release, "ci_daily")
                self.assertEqual(len(samples), 3)
                self.assertEqual(samples[0]["data"]["items"], [[1, "extra"]])
                with self.assertRaises(ValueError):
                    read_samples(root, release, "missing_dataset")
            obj = root / "objects" / (results[0]["object_sha256"] + ".json")
            obj.write_text("corrupted")
            with self.assertRaises(ValueError):
                verify_release(root, release)
            with self.assertRaises(ValueError):
                verify_release(root, "../../outside")

    def test_secret_echo_and_transport_failure_are_safe(self):
        job = {
            "api_name": "trade_cal",
            "params": {},
            "fields": "",
            "row_cap": 6000,
            "required_fields": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200, json={"code": 2002, "msg": "token synthetic-test-token"}
                    )
                )
            ) as client:
                result = capture_sample(client, "synthetic-test-token", job, root)
                self.assertEqual(result["status"], "permission_denied")
                release = "probe-" + "b" * 32
                destination = root / "releases" / release
                destination.mkdir(parents=True)
                (destination / "manifest.json").write_bytes(
                    json_bytes({"results": [result]})
                )
                checked = verify_release(root, release)
                self.assertEqual(checked["observations"], 1)
                self.assertEqual(checked["failed_requests"], 1)
            self.assertTrue(
                all(
                    b"synthetic-test-token" not in p.read_bytes()
                    for p in root.rglob("*.json")
                )
            )

            def timeout(request):
                raise httpx.ReadTimeout("synthetic-test-token", request=request)

            with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
                result = capture_sample(client, "synthetic-test-token", job, root)
                self.assertEqual(result["status"], "transport_error")
                self.assertNotIn("synthetic-test-token", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
