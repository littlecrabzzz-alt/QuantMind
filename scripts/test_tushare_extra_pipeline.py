"""Fixed-release integration for futures/research extras; no network or secrets."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as pipeline  # noqa: E402
from backend.shared.tushare_intake import capture_sample, read_samples  # noqa: E402
from backend.shared.tushare_registry import contract_for  # noqa: E402
from backend.shared.tushare_futures_extra_contracts import (  # noqa: E402
    FIELDS as FUTURES_FIELDS,
    INPUT_FIELDS as FUTURES_INPUTS,
)
from backend.shared.tushare_research_extra_contracts import (  # noqa: E402
    FIELDS as RESEARCH_FIELDS,
    INPUT_FIELDS as RESEARCH_INPUTS,
)
from backend.shared.tushare_store import read_dataset  # noqa: E402

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)
FIELDS = {**FUTURES_FIELDS, **RESEARCH_FIELDS}
INPUTS = {**FUTURES_INPUTS, **RESEARCH_INPUTS}
PARAMS = {
    "fut_trade_cal": {
        "exchange": "CFFEX",
        "start_date": "20260904",
        "end_date": "20260904",
    },
    "fut_daily_adj": {"trade_date": "20260904"},
    "fut_weekly_monthly": {"trade_date": "20260904", "freq": "week"},
    "fut_holding": {"trade_date": "20260904"},
    "fut_index_daily": {"ts_code": "NH0100.NH", "trade_date": "20260904"},
    "fut_weekly_detail": {"week": "202636"},
    "ft_limit": {"trade_date": "20260904"},
    "fina_audit": {"ts_code": "600036.SH"},
    "fina_mainbz": {"ts_code": "600036.SH", "period": "20260630", "type": "P"},
    "disclosure_date": {"end_date": "20260630"},
    "report_rc": {"report_date": "20260904"},
    "stk_surv": {"trade_date": "20260904"},
    "broker_recommend": {"month": "202609"},
}


def sample(api):
    row = dict.fromkeys(FIELDS[api])
    row.update(dict.fromkeys(contract_for(api)["keys"], "source-key"))
    for field in (
        "trade_date",
        "cal_date",
        "report_date",
        "surv_date",
        "week_date",
        "ann_date",
    ):
        if field in row:
            row[field] = "20260904"
    for field, value in {
        "month": "202609",
        "end_date": "20260630",
        "quarter": "2027Q4",
        "week": "202636",
        "freq": "week",
        "exchange": "CFFEX",
    }.items():
        if field in row:
            row[field] = value
    if "ts_code" in row:
        row["ts_code"] = "600036.SH" if api in RESEARCH_FIELDS else "IF.CFX"
    if api == "fut_index_daily":
        row["ts_code"] = "NH0100.NH"
    row["unlisted_supplier_field"] = "原文保留"
    return row


class ExtraPipeline(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.p = pipeline.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("Offline boundary"))
            guard.start()
            self.addCleanup(guard.stop)

    def capture(self, api, params, *, status=200, body=None):
        key = self.p.enqueue(api, params, epoch="offline-extra")
        job = json.loads(
            self.p.db.execute("SELECT job FROM jobs WHERE id=?", (key,)).fetchone()[0]
        )
        source = sample(api)

        def respond(request):
            sent = json.loads(request.content)
            self.assertTrue(set(FIELDS[api]) <= set(sent["fields"].split(",")))
            self.assertTrue(set(sent["params"]) <= set(INPUTS[api]))
            return (
                httpx.Response(status, content=body)
                if body is not None
                else httpx.Response(
                    status,
                    json={
                        "code": 0,
                        "data": {
                            "fields": list(source),
                            "items": [list(source.values())],
                        },
                    },
                )
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = self.p.normalize(
                capture_sample(client, "fixture-token", job, self.root)
            )
        attempt = self.p.db.execute(
            "SELECT tries+1 FROM jobs WHERE id=?", (key,)
        ).fetchone()[0]
        self.p.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (key, attempt, json.dumps(result)),
        )
        self.p.db.execute(
            "UPDATE jobs SET result=?,state=?,tries=tries+1 WHERE id=?",
            (
                json.dumps(result),
                "done" if result["status"] == "sample_ok" else "quality",
                key,
            ),
        )
        self.p.db.commit()
        return result

    def test_all_thirteen_full_fields_fixed_release_and_request_types(self):
        for api in FIELDS:
            for kind in ("P", "D", "I") if api == "fina_mainbz" else (None,):
                params = {**PARAMS[api], **({"type": kind} if kind else {})}
                self.assertEqual(self.capture(api, params)["status"], "sample_ok")
        pinned = self.p.publish()
        for api in FIELDS:
            with self.subTest(api=api):
                table = read_dataset(self.root, pinned, api)
                self.assertEqual(table.num_rows, 3 if api == "fina_mainbz" else 1)
                self.assertTrue(set(FIELDS[api]) <= set(table.column_names))
                self.assertEqual(
                    table.to_pylist()[0]["unlisted_supplier_field"], "原文保留"
                )
                self.assertEqual(
                    json.loads(table.schema.metadata[b"tushare"])["upstream_calls"], 0
                )
        rows = read_dataset(self.root, pinned, "fina_mainbz").to_pylist()
        self.assertEqual(
            {json.loads(r["_request_identity"])["type"] for r in rows}, {"P", "D", "I"}
        )
        for api in ("report_rc", "stk_surv", "fut_weekly_detail"):
            self.assertEqual(
                read_dataset(
                    self.root, pinned, api, start_date="20260904", end_date="20260904"
                ).num_rows,
                1,
            )
        ids = self.p.identifiers()
        self.assertIn("IF.CFX", ids["futures_continuous"])
        self.assertIn("NH0100.NH", ids["futures_indexes"])

    def test_error_bodies_remain_evidence_without_rows_or_reader_crash(self):
        for body in (
            b"<html>unavailable</html>",
            b'{"code":0,"data":{"fields":["ts_code"],"items":[["fake.NH"]]}}',
        ):
            result = self.capture(
                "fut_index_daily", PARAMS["fut_index_daily"], status=500, body=body
            )
            self.assertEqual(self.p.records(result), [])
            self.assertNotIn("parquet", result)
            release_id = "probe-" + "a" * 32
            path = self.root / "releases" / release_id
            path.mkdir(parents=True, exist_ok=True)
            (path / "manifest.json").write_text(json.dumps({"results": [result]}))
            self.assertIsNone(
                read_samples(self.root, release_id, "fut_index_daily")[0]["data"]
            )
        self.assertEqual(self.p.identifiers()["futures_indexes"], [])

    def test_family_validation_isolated_and_reason_gaps_do_not_overwrite(self):
        config = {
            "enable_futures_extra": True,
            "futures_extra_apis": ["fut_trade_cal"],
            "enable_research_extra": True,
            "research_extra_apis": ["report_rc"],
            "history_start": "20260901",
            "plan_jobs_per_tick": 20,
        }
        result = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:futures_extra", result)
        self.assertIn("history:research_extra", result)
        scopes = {r[0] for r in self.p.db.execute("SELECT scope FROM capability")}
        self.assertIn("planning:research_extra:report_rc:pagination_gap", scopes)
        self.assertIn("planning:research_extra:report_rc:refresh_gap", scopes)
        config["research_extra_apis"] = ["unknown_api"]
        result = self.p.plan_extended(config, date(2026, 9, 10))
        self.assertIn("recent:futures_extra", result)
        self.assertNotIn("recent:research_extra", result)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:research_extra'"
            ).fetchone()[0],
            "validation_blocked",
        )


if __name__ == "__main__":
    unittest.main()
