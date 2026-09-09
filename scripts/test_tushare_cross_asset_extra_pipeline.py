"""Six actual runtime paths using temporary storage and MockTransport only."""

from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import Pipeline, _planning_inputs
from backend.shared.tushare_intake import capture_sample, json_bytes
from backend.shared.tushare_cross_asset_extra_contracts import FIELDS
from backend.shared.tushare_registry import (
    CROSS_ASSET_RUNTIME_CONTRACTS as C,
    contract_for,
    PLANNERS,
)
from backend.shared.tushare_store import read_dataset, dataset_schema

CODES = {
    "idx_factor_pro": "801010.SI",
    "fund_factor_pro": "1500011.SZ",
    "cb_factor_pro": "T123456.SZ",
    "index_global": "HSI",
    "sz_daily_info": "中小板",
    "etf_limit": "510300.SH",
}
CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


def source(api, **updates):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        ts_code=CODES[api],
        trade_date="20240229",
        unknown_source_column="保留",
        ann_date="20250301",
    )
    for f, v in {
        "close": -1.25,
        "amount": 0.125,
        "up_limit": 123.5,
        "pre_close": 0.0,
        "asset_type": "ETF",
        "exchange": "SSE",
        "trade_date_doris": "2024-02-29T00:00:00",
        "count": 123,
        "vol": 0,
    }.items():
        if f in row:
            row[f] = v
    row.update(updates)
    return row


class Runtime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p = Pipeline(self.root, CATALOG)
        self.addCleanup(self.p.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("isolated only"))
            guard.start()
            self.addCleanup(guard.stop)

    def capture(
        self,
        api,
        rows,
        params=None,
        when="2026-09-09T01:00:00+00:00",
        more=False,
        epoch="fixture",
    ):
        params = {"trade_date": "20240229"} if params is None else params
        key = self.p.enqueue(api, params, 20, epoch)
        saved = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(saved["job"])

        def respond(request):
            sent = json.loads(request.content)
            if api in FIELDS:
                self.assertTrue(set(FIELDS[api]) <= set(sent["fields"].split(",")))
            fields = list(rows[0])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                        "has_more": more,
                    },
                },
            )

        with (
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
            patch("backend.shared.tushare_intake.utc_now", return_value=when),
        ):
            result = self.p.normalize(capture_sample(client, "fixture", job, self.root))
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            (key, saved["tries"] + 1, json.dumps(result)),
        )
        self.p.db.execute(
            "UPDATE jobs SET result=?,state='done',tries=tries+1 WHERE id=?",
            (json.dumps(result), key),
        )
        self.p.db.commit()
        return (
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone(),
            job,
            result,
        )

    def test_six_full_field_source_metadata_and_default_explicit_dates(self):
        for api in FIELDS:
            self.capture(api, [source(api)])
        release = self.p.publish()
        for api in FIELDS:
            for kwargs in (
                {},
                {"start_date": "20240229", "end_date": "20240229"},
                {
                    "start_date": "20240229",
                    "end_date": "20240229",
                    "date_field": "trade_date",
                },
            ):
                table = read_dataset(self.root, release, api, **kwargs)
                self.assertEqual(table.num_rows, 1)
                row = table.to_pylist()[0]
                src = source(api)
                for key, value in src.items():
                    self.assertEqual(
                        row["source_ts_code"] if key == "ts_code" else row[key],
                        value,
                        (api, key),
                    )
                self.assertEqual(
                    row["ts_code"], C[api]["source_namespace"] + CODES[api]
                )
                self.assertEqual(
                    row["_row_identity"], hashlib.sha256(json_bytes(src)).hexdigest()
                )
                meta = json.loads(table.schema.metadata[b"tushare"])
                self.assertEqual(meta["upstream_calls"], 0)
                for key in (
                    "hidden_fields",
                    "unit_note",
                    "namespace_note",
                    "pit_gap",
                    "history_gap",
                    "field_metadata",
                ):
                    self.assertEqual(meta[key], C[api][key])
            self.assertEqual(
                dataset_schema(self.root, release, api)["default_date_field"],
                "trade_date",
            )
            self.assertEqual(
                read_dataset(
                    self.root, release, api, start_date="20250301", end_date="20250301"
                ).num_rows,
                0,
            )
            self.assertEqual(
                read_dataset(
                    self.root,
                    release,
                    api,
                    codes=[C[api]["source_namespace"] + CODES[api]],
                ).num_rows,
                1,
            )
            self.assertEqual(
                read_dataset(
                    self.root,
                    release,
                    api,
                    codes=[CODES[api]],
                    code_field="source_ts_code",
                ).num_rows,
                1,
            )

    def test_versions_7digits_and_si_ci_and_stock_namespace_unchanged(self):
        for api, code in [
            ("fund_factor_pro", "150001.SZ"),
            ("fund_factor_pro", "1500011.SZ"),
            ("idx_factor_pro", "CI005001.CI"),
            ("idx_factor_pro", "801010.SI"),
            ("cb_factor_pro", "123456.SZ"),
            ("cb_factor_pro", "T123456.SZ"),
            ("index_global", "000001.SH"),
            ("sz_daily_info", "ETF"),
        ]:
            self.capture(api, [source(api, ts_code=code)], epoch=code)
        self.capture(
            "fund_factor_pro",
            [source("fund_factor_pro", close=2)],
            when="2026-09-09T02:00:00+00:00",
            epoch="revision",
        )
        self.capture(
            "daily",
            [{"ts_code": "600000.SH", "trade_date": "20240229", "open": 1, "close": 2}],
            epoch="stock",
        )
        release = self.p.publish()
        self.assertEqual(
            {
                r["ts_code"]
                for r in read_dataset(self.root, release, "fund_factor_pro").to_pylist()
            },
            {"FUND:150001.SZ", "FUND:1500011.SZ"},
        )
        self.assertEqual(
            read_dataset(self.root, release, "fund_factor_pro").num_rows, 3
        )
        self.assertEqual(
            read_dataset(
                self.root, release, "fund_factor_pro", as_of="2026-09-09T01:30:00Z"
            ).num_rows,
            2,
        )
        self.assertEqual(
            read_dataset(self.root, release, "daily").to_pylist()[0]["ts_code"],
            "SH600000",
        )
        self.assertEqual(
            read_dataset(self.root, release, "index_global").to_pylist()[0]["ts_code"],
            "GIDX:000001.SH",
        )

    def test_discovery_isolated_and_attempt_history_observed_fanout(self):
        self.capture(
            "stock_basic", [{"ts_code": "600000.SH", "name": "fixture"}], params={}
        )
        for api in FIELDS:
            self.capture(api, [source(api)], epoch="old-observation")
        self.capture(
            "fund_basic",
            [{"ts_code": "150001.SZ"}, {"ts_code": "000001.OF"}],
            params={},
        )
        self.capture("cb_basic", [{"ts_code": "123456.SZ"}], params={})
        self.capture(
            "ci_index_member",
            [
                {
                    "ts_code": "600000.SH",
                    "l1_code": "CI005001.CI",
                    "l2_code": "CI005002.CI",
                    "l3_code": "CI005003.CI",
                }
            ],
            params={},
        )
        # Lose the latest jobs result, retaining attempts; discovery must keep observed codes.
        self.p.db.execute(
            "UPDATE jobs SET result=NULL WHERE json_extract(job,'$.api_name')='fund_factor_pro'"
        )
        ids = self.p.identifiers()
        self.assertEqual(ids["stocks"], ["600000.SH"])
        self.assertEqual(ids["bonds"], ["123456.SZ"])
        self.assertIn("T123456.SZ", ids["cross_asset_bonds"])
        self.assertIn("1500011.SZ", ids["cross_asset_funds"])
        self.assertNotIn("000001.OF", ids["cross_asset_funds"])
        self.assertIn("CI005003.CI", ids["cross_asset_indexes"])
        self.assertNotIn("600000.SH", ids["cross_asset_indexes"])
        self.assertIn("中小板", ids["cross_asset_sz_boards"])
        self.assertIn("SPX", ids["cross_asset_global_indexes"])
        for api in FIELDS:
            row, job, result = self.capture(
                api, [source(api)], more=True, epoch="saturated"
            )
            with patch.object(
                self.p, "identifiers", return_value={C[api]["saturation_fallback"]: []}
            ):
                outcome = self.p.split_request(row, job, result)
            self.assertFalse(outcome["universe_complete"])
            self.assertEqual(outcome["children"], 1)
            child = self.p.db.execute(
                "SELECT j.job FROM partition_children p JOIN jobs j ON j.id=p.child_id WHERE p.parent_id=?",
                (row["id"],),
            ).fetchone()
            self.assertEqual(json.loads(child[0])["params"]["ts_code"], CODES[api])
            new = self.capture(
                api,
                [
                    source(
                        api,
                        ts_code={
                            "sz_daily_info": "历史板块",
                            "index_global": "OLDX",
                        }.get(api, CODES[api]),
                    )
                ],
                more=True,
                epoch="saturated",
            )[2]
            with patch.object(
                self.p, "identifiers", return_value={C[api]["saturation_fallback"]: []}
            ):
                again = self.p.split_request(row, job, new)
            self.assertFalse(again["universe_complete"])

    def test_run_terminal_saturation_preserves_raw_and_never_claims_complete(self):
        keys = [
            self.p.enqueue(
                api,
                {"ts_code": CODES[api], "trade_date": "20240229"},
                1,
                "run-terminal",
            )
            for api in FIELDS
        ]

        def respond(request):
            api = json.loads(request.content)["api_name"]
            row = source(api)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": list(row),
                        "items": [list(row.values())],
                        "has_more": True,
                    },
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            report = self.p.run(
                client, "fixture", {}, max_requests=6, max_seconds=10, pause=0
            )
        self.assertEqual(report["requests"], 6)
        for key in keys:
            row = self.p.db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (key,)
            ).fetchone()
            result = json.loads(row["result"])
            self.assertEqual(row["state"], "blocked")
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertTrue(
                (self.root / "observations" / result["observation"]).is_file()
            )
            self.assertTrue(
                (self.root / "objects" / (result["object_sha256"] + ".json")).is_file()
            )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )

    def test_default_disabled_history_signature_and_terminal_date_saturation(self):
        self.p.plan_extended({}, date(2024, 3, 10))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        cfg = {
            "enable_cross_asset_extra": True,
            "cross_asset_extra_history_start": "19900101",
            "plan_jobs_per_tick": 100,
        }
        self.p.plan_extended(cfg, date(2024, 3, 10))
        self.assertGreater(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        self.assertNotEqual(
            _planning_inputs("cross_asset_extra", cfg, {}),
            _planning_inputs(
                "cross_asset_extra",
                {**cfg, "cross_asset_extra_history_start": "20000101"},
                {},
            ),
        )
        self.assertIn("cross_asset_extra", PLANNERS)
        self.assertTrue(
            self.p.db.execute(
                "SELECT count(*) FROM capability WHERE scope LIKE 'planning:cross_asset_extra:%'"
            ).fetchone()[0]
        )
        for api in FIELDS:
            row, job, result = self.capture(
                api,
                [source(api)],
                params={"ts_code": CODES[api], "trade_date": "20240229"},
                more=True,
                epoch="terminal",
            )
            self.assertIsNone(self.p.split_request(row, job, result))
            row, job, result = self.capture(
                api,
                [source(api)],
                params={
                    "ts_code": CODES[api],
                    "start_date": "20240228",
                    "end_date": "20240301",
                },
                more=True,
                epoch="date",
            )
            self.assertEqual(
                self.p.split_request(row, job, result)["method"], "date_bisection"
            )
            self.assertEqual(contract_for(api)["group"], "cross_asset_extra")


if __name__ == "__main__":
    unittest.main()
