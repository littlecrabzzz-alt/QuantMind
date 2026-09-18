#!/usr/bin/env python3
"""Offline checks for live-verified financial VIP period pagination."""

from contextlib import ExitStack
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
from backend.shared.tushare_structured_contracts import (  # noqa: E402
    FINANCIAL_VIP_PAGINATION,
)


CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class FinancialVipPaginationTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.pipeline = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        self.stack.enter_context(
            patch("socket.socket.connect", side_effect=AssertionError("no network"))
        )
        self.stack.enter_context(
            patch.object(module, "get_secret", side_effect=AssertionError("no secrets"))
        )

    @staticmethod
    def params(api, period="20260630", report_type="1"):
        params = {"period": period}
        if api != "forecast_vip":
            params["report_type"] = report_type
        return params

    def finish(self, api, rows, *, offset=0, state="done", epoch="20260919"):
        params = self.params(api)
        if offset:
            params["offset"] = offset
        job_id = self.pipeline.enqueue(api, params, 5, epoch)
        result = {
            "api_name": api,
            "status": "sample_ok" if rows else "empty_unverified",
            "row_count": rows,
        }
        if rows < 1000:
            result["pagination_end"] = True
        self.pipeline.db.execute(
            "UPDATE jobs SET state=?,result=?,tries=1 WHERE id=?",
            (state, json.dumps(result), job_id),
        )
        return job_id

    def leaf(
        self,
        api,
        *,
        report_type="1",
        state="pending",
        epoch="20260914",
        ts_code="000001.SZ",
    ):
        params = {**self.params(api, report_type=report_type), "ts_code": ts_code}
        job_id = self.pipeline.enqueue(api, params, 26, epoch)
        self.pipeline.db.execute("UPDATE jobs SET state=? WHERE id=?", (state, job_id))
        return job_id

    def legacy_root(self, api, current_root, epoch="20260914"):
        job = json.loads(
            self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE id=?", (current_root,)
            ).fetchone()[0]
        )
        job["params"].pop("limit")
        logical = module.digest(module.json_bytes(job))
        task_id = module.digest(module.json_bytes([logical, epoch]))
        result = json.dumps(
            {
                "api_name": api,
                "status": "possibly_truncated",
                "row_count": job["row_cap"],
            }
        )
        self.pipeline.db.execute(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,result,group_name) "
            "VALUES(?,?,?,?,?,'split_pending',1,?,'structured')",
            (task_id, logical, epoch, json.dumps(job), 25, result),
        )
        return task_id

    def state(self, job_id):
        return self.pipeline.db.execute(
            "SELECT state FROM jobs WHERE id=?", (job_id,)
        ).fetchone()[0]

    def test_contracts_page_only_exact_period_roots(self):
        self.assertEqual(
            set(FINANCIAL_VIP_PAGINATION),
            {
                "income_vip",
                "balancesheet_vip",
                "cashflow_vip",
                "forecast_vip",
            },
        )
        for api in FINANCIAL_VIP_PAGINATION:
            spec = module.contract_for(api)
            self.assertEqual(spec["pagination"]["page_size"], 1000)
            self.assertEqual(spec["pagination_required_param"], "period")
            self.assertEqual(spec["pagination_forbidden_params"], ["ts_code"])
            root = self.pipeline.enqueue(api, self.params(api), 5, "20260919")
            leaf = self.pipeline.enqueue(
                api,
                {**self.params(api), "ts_code": "000001.SZ"},
                26,
                "20260914",
            )
            root_params, leaf_params = (
                json.loads(row[0])["params"]
                for row in self.pipeline.db.execute(
                    "SELECT job FROM jobs WHERE id IN (?,?) ORDER BY id=? DESC",
                    (root, leaf, root),
                )
            )
            self.assertEqual(root_params["limit"], 1000)
            self.assertNotIn("limit", leaf_params)

    def test_saturated_page_continues_without_identifier_fanout(self):
        api = "cashflow_vip"
        calls = []

        def handler(request):
            payload = json.loads(request.content)
            params = payload["params"]
            calls.append(params.get("offset", 0))
            fields = payload["fields"].split(",")
            size = 2 if not params.get("offset") else 1
            rows = [
                {
                    "ts_code": f"00000{n + 1}.SZ",
                    "end_date": "20260630",
                }
                for n in range(size)
            ]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[row.get(field) for field in fields] for row in rows],
                        "has_more": size == 2,
                    },
                },
            )

        pagination = module.contract_for(api)["pagination"]
        with patch.dict(pagination, {"page_size": 2}):
            self.pipeline.enqueue(api, self.params(api), 5, "20260919")
            self.pipeline.db.commit()
            with httpx.Client(
                transport=httpx.MockTransport(handler), trust_env=False
            ) as client:
                report = self.pipeline.run(
                    client,
                    "synthetic-test-token",
                    {"priority_start": "20200101"},
                    max_requests=2,
                    max_seconds=2,
                    pause=0,
                )
        self.assertEqual(report["requests"], 2)
        self.assertEqual(calls, [0, 2])
        self.assertFalse(
            self.pipeline.db.execute("SELECT 1 FROM partition_children").fetchone()
        )
        self.assertEqual(self.pipeline.status(), {"done": 2})

    def test_closed_chain_compacts_only_matching_open_work(self):
        root = self.finish("cashflow_vip", 1000)
        self.finish("cashflow_vip", 7, offset=1000)
        leaf = self.leaf("cashflow_vip")
        self.pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (leaf,))
        attempt = json.dumps({"api_name": "cashflow_vip", "status": "transport_error"})
        self.pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (leaf, 1, attempt),
        )
        legacy = self.legacy_root("cashflow_vip", root)
        other = self.leaf("cashflow_vip", report_type="2")
        terminal = self.leaf("cashflow_vip", state="done", ts_code="000002.SZ")
        self.pipeline.db.commit()

        report = self.pipeline.compact_financial_vip_coverage()

        self.assertEqual(report["status"], "compacted")
        self.assertEqual(report["complete_scopes"], 1)
        self.assertEqual(report["superseded_leaf_jobs"], 1)
        self.assertEqual(report["superseded_legacy_roots"], 1)
        self.assertEqual(self.state(leaf), "superseded")
        self.assertEqual(self.state(legacy), "superseded")
        self.assertEqual(self.state(other), "pending")
        self.assertEqual(self.state(terminal), "done")
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT result FROM attempts WHERE job_id=?", (leaf,)
            ).fetchone()[0],
            attempt,
        )

    def test_missing_tail_empty_root_and_page_after_tail_do_not_compact(self):
        for period, mode in (
            ("20260331", "missing"),
            ("20250630", "empty"),
            ("20240930", "extra"),
        ):
            params = self.params("forecast_vip", period=period)
            root = self.pipeline.enqueue("forecast_vip", params, 5, "20260919")
            if mode == "missing":
                result = {"row_count": 1000, "status": "possibly_truncated"}
                state = "done"
            elif mode == "empty":
                result = {
                    "row_count": 0,
                    "status": "empty_unverified",
                    "pagination_end": True,
                }
                state = "empty"
            else:
                result = {"row_count": 3, "status": "sample_ok", "pagination_end": True}
                state = "done"
            self.pipeline.db.execute(
                "UPDATE jobs SET state=?,result=? WHERE id=?",
                (state, json.dumps(result), root),
            )
            if mode == "extra":
                extra = self.pipeline.enqueue(
                    "forecast_vip", {**params, "offset": 1000}, 5, "20260919"
                )
                self.pipeline.db.execute(
                    "UPDATE jobs SET state='done',result=? WHERE id=?",
                    (
                        json.dumps(
                            {
                                "row_count": 1,
                                "status": "sample_ok",
                                "pagination_end": True,
                            }
                        ),
                        extra,
                    ),
                )
            self.leaf("forecast_vip", epoch=period)
        self.pipeline.db.commit()

        report = self.pipeline.compact_financial_vip_coverage()

        self.assertEqual(report["status"], "no_complete_scopes")
        self.assertEqual(report["complete_scopes"], 0)
        self.assertGreaterEqual(report["invalid_pages"], 1)
        self.assertFalse(
            self.pipeline.db.execute(
                "SELECT 1 FROM jobs WHERE state='superseded'"
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
