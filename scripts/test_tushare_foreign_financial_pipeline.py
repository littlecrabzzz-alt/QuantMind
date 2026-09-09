"""Offline eight financial datasets through capture, normalize, publish and reader."""

from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_intake import capture_sample, json_bytes
from backend.shared.tushare_foreign_financial_contracts import FIELDS
from backend.shared.tushare_registry import (
    contract_for,
    PLANNERS,
    foreign_financial_runtime_prerequisites,
)
from backend.shared.tushare_store import read_dataset, dataset_schema

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    for key, value in {
        "ts_code": "00001!A.HK" if api.startswith("hk_") else "BRK.B",
        "end_date": "20250427",
        "ind_name": "营业收入",
        "ind_value": -123.125,
        "ind_type": "Q1",
        "report_type": "单季报",
        "currency": "HKD" if api.startswith("hk_") else "USD",
        "notice_date": "20250620",
        "start_date": 20240101.0 if api.startswith("hk_") else "20240101",
        "operate_income": 0.0,
    }.items():
        if key in row:
            row[key] = value
    row.update(unknown_supplier_column="原始新字段", ann_date="20250707")
    row.update(updates)
    return row


class ForeignFinancialPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("offline only"))
            guard.start()
            self.addCleanup(guard.stop)

    def capture(self, api, rows, params=None, when="2026-09-09T01:00:00+00:00"):
        params = params or {
            "ts_code": rows[0]["ts_code"],
            "start_date": "20250101",
            "end_date": "20251231",
        }
        key = self.p.enqueue(api, params, 25, "fixture")
        saved = self.p.db.execute("select * from jobs where id=?", (key,)).fetchone()
        job = json.loads(saved["job"])

        def response(request):
            sent = json.loads(request.content)
            self.assertTrue(set(FIELDS[api]) <= set(sent["fields"].split(",")))
            self.assertEqual(sent["params"], params)
            fields = list(rows[0])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                    },
                },
            )

        with (
            httpx.Client(
                transport=httpx.MockTransport(response), trust_env=False
            ) as client,
            patch("backend.shared.tushare_intake.utc_now", return_value=when),
        ):
            result = self.p.normalize(capture_sample(client, "fixture", job, self.root))
        attempt = saved["tries"] + 1
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (key, attempt, json.dumps(result))
        )
        self.p.db.execute(
            "UPDATE jobs SET result=?,state='done',tries=? WHERE id=?",
            (json.dumps(result), attempt, key),
        )
        self.p.db.commit()
        return key, job, result

    def test_all_eight_full_columns_fiscal_dates_namespaces_and_source_hash(self):
        originals = {}
        for api in FIELDS:
            originals[api] = source(api)
            _, _, result = self.capture(api, [originals[api]])
            self.assertEqual(result["status"], "sample_ok")
        pinned = self.p.publish()
        for api, src in originals.items():
            self.assertEqual(contract_for(api)["group"], "foreign_financial")
            schema = dataset_schema(self.root, pinned, api)
            self.assertEqual(schema["default_date_field"], "end_date")
            # Unknown ann_date must not silently change the default fiscal axis.
            for filters in (
                {},
                {"start_date": "20250427", "end_date": "20250427"},
                {
                    "date_field": "end_date",
                    "start_date": "20250427",
                    "end_date": "20250427",
                },
                {
                    "date_field": "ann_date",
                    "start_date": "20250707",
                    "end_date": "20250707",
                },
            ):
                table = read_dataset(self.root, pinned, api, **filters)
                self.assertEqual(table.num_rows, 1)
                row = table.to_pylist()[0]
                self.assertTrue(set(src) <= set(table.column_names))
                for f, value in src.items():
                    self.assertEqual(
                        row["source_ts_code"] if f == "ts_code" else row[f], value
                    )
                self.assertEqual(
                    row["ts_code"], "HK00001!A" if api.startswith("hk_") else "USBRK.B"
                )
                self.assertEqual(
                    row["_row_identity"], hashlib.sha256(json_bytes(src)).hexdigest()
                )
                meta = json.loads(table.schema.metadata[b"tushare"])
                self.assertEqual(meta["upstream_calls"], 0)
                self.assertIn("pit_gap", meta)
                self.assertEqual(meta["permission_status"], "unprobed")
            self.assertEqual(
                read_dataset(
                    self.root, pinned, api, start_date="20250707", end_date="20250707"
                ).num_rows,
                0,
            )
            self.assertEqual(
                read_dataset(
                    self.root,
                    pinned,
                    api,
                    codes=["HK00001!A" if api.startswith("hk_") else "USBRK.B"],
                ).num_rows,
                1,
            )
        self.assertEqual(
            read_dataset(
                self.root,
                pinned,
                "us_fina_indicator",
                date_field="notice_date",
                start_date="20250620",
                end_date="20250620",
            ).num_rows,
            1,
        )
        self.assertEqual(self.p.identifiers()["hk_stocks"], ["00001!A.HK"])
        self.assertEqual(self.p.identifiers()["us_stocks"], ["BRK.B"])

    def test_long_form_subjects_report_variants_and_revisions_survive(self):
        for api in FIELDS:
            first = source(api)
            second = source(
                api,
                **(
                    {"operate_income": 99.0, "currency": "CNY"}
                    if api.endswith("fina_indicator")
                    else {"ind_name": "其他收益", "ind_value": None}
                ),
            )
            changed = dict(
                first,
                **(
                    {"operate_income": -1.25}
                    if api.endswith("fina_indicator")
                    else {"ind_value": -999.5}
                ),
            )
            self.capture(api, [first, second])
            self.capture(
                api, [first, second, changed], when="2026-09-09T02:00:00+00:00"
            )
        pinned = self.p.publish()
        for api in FIELDS:
            rows = read_dataset(self.root, pinned, api).to_pylist()
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({r["_row_identity"] for r in rows}), 3)
            self.assertEqual(
                read_dataset(
                    self.root, pinned, api, as_of="2026-09-09T01:30:00Z"
                ).num_rows,
                2,
            )
            if not api.endswith("fina_indicator"):
                self.assertEqual(
                    {r["ind_name"] for r in rows}, {"营业收入", "其他收益"}
                )
                self.assertEqual(
                    {r["ind_value"] for r in rows}, {-123.125, None, -999.5}
                )
            else:
                self.assertIn("CNY", {r["currency"] for r in rows})

    def test_default_off_bounded_resume_gaps_and_recent_configuration_signature(self):
        ids = {"hk_stocks": ["00001!A.HK"], "us_stocks": ["ABC/WS"]}
        with patch.object(self.p, "identifiers", return_value=ids):
            self.p.plan_extended({}, date(2026, 9, 9))
            self.assertEqual(
                self.p.db.execute("select count(*) from jobs").fetchone()[0], 0
            )
            config = {
                "enable_foreign_financial": True,
                "foreign_financial_history_start": "19900101",
                "plan_jobs_per_tick": 2,
            }
            for _ in range(12):
                self.p.plan_extended(config, date(2026, 9, 9))
            self.assertEqual(
                self.p.db.execute("select count(*) from jobs").fetchone()[0], 16
            )
            old = [
                tuple(r)
                for r in self.p.db.execute(
                    "select name,signature from planning_state order by name"
                )
            ]
            self.p.plan_extended(
                {**config, "foreign_financial_recent_days": 401}, date(2026, 9, 9)
            )
            new = [
                tuple(r)
                for r in self.p.db.execute(
                    "select name,signature from planning_state order by name"
                )
            ]
            self.assertNotEqual(old, new)
        scopes = [r[0] for r in self.p.db.execute("select scope from capability")]
        self.assertTrue(any("foreign_financial:us_income:pit_gap" in s for s in scopes))
        self.assertTrue(any("independent_permission_unprobed" in s for s in scopes))
        for family in ("global", "structured", "text"):
            self.assertEqual(
                module._planning_inputs(family, {}, ids),
                module._planning_inputs(
                    family, {"foreign_financial_recent_days": 401}, ids
                ),
            )
        bad_unrelated = {**ids, "stocks": ["bad internal code"]}
        self.assertTrue(foreign_financial_runtime_prerequisites(bad_unrelated))
        self.assertEqual(
            len(
                list(PLANNERS["foreign_financial"]({}, date(2026, 9, 9), bad_unrelated))
            ),
            16,
        )

    def test_real_partition_split_preserves_source_filters_no_pagination(self):
        api = "us_income"
        params = {
            "ts_code": "ABC/WS",
            "start_date": "20240228",
            "end_date": "20240301",
            "report_type": "Q1",
            "ind_name": "其他收益",
        }
        key = self.p.enqueue(api, params, 25, "fixture")
        row = self.p.db.execute("select * from jobs where id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        result = self.p.split_request(row, job)
        self.assertEqual(result["method"], "date_bisection")
        self.assertEqual(result["children"], 2)
        children = [
            json.loads(r[0])["params"]
            for r in self.p.db.execute("select job from jobs where id<>?", (key,))
        ]
        self.assertEqual(
            {(r["start_date"], r["end_date"]) for r in children},
            {("20240228", "20240229"), ("20240301", "20240301")},
        )
        self.assertTrue(
            all(
                {k: v for k, v in c.items() if k not in ("start_date", "end_date")}
                == {
                    k: v
                    for k, v in params.items()
                    if k not in ("start_date", "end_date")
                }
                for c in children
            )
        )
        self.assertTrue(all("offset" not in c and "limit" not in c for c in children))
        self.assertEqual(self.p.split_request(row, job)["method"], "date_bisection")
        self.assertEqual(
            self.p.db.execute("select count(*) from partition_children").fetchone()[0],
            2,
        )
        spec = contract_for("us_fina_indicator")
        self.assertEqual(spec["row_cap"], 200)
        self.assertFalse(spec["row_cap_verified"])

    def test_runner_terminal_saturation_is_blocked_with_raw_evidence(self):
        api = "us_fina_indicator"
        key = self.p.enqueue(
            api,
            {"ts_code": "BRK.B", "start_date": "20250427", "end_date": "20250427"},
            1,
            "terminal",
        )
        row = source(api)

        def response(request):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": list(row), "items": [list(row.values())] * 200},
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(response), trust_env=False
        ) as client:
            result = self.p.run(
                client, "fixture", {}, max_requests=1, max_seconds=10, pause=0
            )
        self.assertEqual(result["requests"], 1)
        saved = self.p.db.execute("select * from jobs where id=?", (key,)).fetchone()
        self.assertEqual(saved["state"], "blocked")
        observed = json.loads(saved["result"])
        self.assertEqual(observed["status"], "possibly_truncated")
        self.assertTrue(
            (self.root / "objects" / (observed["object_sha256"] + ".json")).is_file()
        )
        self.assertTrue((self.root / observed["parquet"]["path"]).is_file())
        self.assertEqual(
            self.p.db.execute("select count(*) from partition_children").fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
