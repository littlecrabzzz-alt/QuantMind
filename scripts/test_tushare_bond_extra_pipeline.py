"""Bond runtime acquisition and fixed-reader acceptance, temporary fixtures only."""

from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_bond_extra_contracts import FIELDS, FIELD_METADATA
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_store import read_dataset, dataset_schema
import test_tushare_technical_extra_pipeline as fixtures


def source(api, **updates):
    row = {
        f: "source-label" if m["type"] == "str" else -1.25
        for f, m in FIELD_METADATA[api].items()
    }
    row.update(ts_code="T110001.SH")
    values = {
        "trade_date": "20260904",
        "end_date": "20250630",
        "ann_date": "20260904",
        "rating_date": "20260901",
        "qt_time": "18:36:29",
        "curve_type": "0",
        "curve_term": 0.08,
        "holder_name": None,
    }
    for f, v in values.items():
        if f in row:
            row[f] = v
    if api == "yc_cb":
        row["ts_code"] = "101"
    if api.startswith("bc_"):
        row["ts_code"] = "200013.BC"
    if api == "repo_daily":
        row["ts_code"] = "DR001.IB"
    row["supplier_extra"] = None
    row.update(updates)
    return row


def params(api, **updates):
    p = (
        {"ts_code": "T110001.SH", "period": "20250630"}
        if api == "top10_cb_holders"
        else {"ts_code": "T110001.SH"}
        if api == "cb_rating"
        else {"trade_date": "20260904", "curve_type": "0"}
        if api == "yc_cb"
        else {"trade_date": "20260904"}
    )
    return {**p, **updates}


class BondRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    discovery = fixtures.TechnicalExtraRuntime.discovery
    capture = fixtures.TechnicalExtraRuntime.capture

    def test_full_fields_namespace_source_fixed_date_and_distinct_rows(self):
        old = self.p.publish()
        expected = {}
        for api in FIELDS:
            rows = [source(api), source(api, supplier_extra="revision")]
            if api == "yc_cb":
                rows.append(source(api, ts_code="1001.CB", curve_term=0))
            expected[api] = {module.digest(module.json_bytes(r)): r for r in rows}
            for epoch in ("first", "repeat"):
                self.assertEqual(
                    self.capture(api, params(api), rows, epoch=epoch)[2]["status"],
                    "sample_ok",
                )
        fixed = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, fixed, api)
            self.assertEqual(table.num_rows, len(expected[api]))
            namespace = contract_for(api)["source_namespace"]
            for row in table.to_pylist():
                raw = expected[api][row.get("_raw_row_identity", row["_row_identity"])]
                self.assertEqual(row["ts_code"], namespace + raw["ts_code"])
                for f, v in raw.items():
                    self.assertEqual(row["source_ts_code" if f == "ts_code" else f], v)
            axis = contract_for(api)["date_field"]
            selected = "20250630" if api == "top10_cb_holders" else "20260904"
            self.assertEqual(
                read_dataset(
                    self.root, fixed, api, start_date=selected, end_date=selected
                ).num_rows,
                table.num_rows,
            )
            self.assertEqual(
                dataset_schema(self.root, fixed, api)["default_date_field"], axis
            )
            metadata = json.loads(table.schema.metadata[b"tushare"])
            self.assertEqual(metadata["permission_status"], "unprobed")
            self.assertEqual(metadata["deduplication_mode"], "distinct_supplier_rows")
            self.assertEqual(set(metadata["field_metadata"]), set(FIELDS[api]))
            self.assertEqual(
                metadata["hidden_fields"], contract_for(api)["hidden_fields"]
            )
            for note in ("history_gap", "saturation_gap", "pit_gap", "identity_gap"):
                self.assertEqual(metadata[note], contract_for(api)[note])
            with self.assertRaisesRegex(ValueError, "Dataset unavailable"):
                read_dataset(self.root, old, api)
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                "cb_rating",
                date_field="rating_date",
                start_date="20260901",
                end_date="20260901",
            ).num_rows,
            2,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                "cb_rating",
                start_date="20260901",
                end_date="20260901",
            ).num_rows,
            0,
        )
        self.assertEqual(
            read_dataset(
                self.root, fixed, "yc_cb", fields=["yield", "curve_term"]
            ).num_columns,
            2,
        )
        self.assertEqual(
            {r["ts_code"] for r in read_dataset(self.root, fixed, "yc_cb").to_pylist()},
            {"YC:101", "YC:1001.CB"},
        )
        self.capture(
            "bond_blk",
            params("bond_blk"),
            [source("bond_blk", ts_code="110001.SH")],
            epoch="source-query",
        )
        fixed = self.p.publish()
        self.assertEqual(
            read_dataset(
                self.root,
                fixed,
                "bond_blk",
                code_field="source_ts_code",
                codes=["110001.SH"],
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root, fixed, "bond_blk", codes=["BOND:110001.SH"]
            ).num_rows,
            1,
        )
        with self.assertRaisesRegex(ValueError, "prefix"):
            read_dataset(self.root, fixed, "bond_blk", codes=["110001.SH"])

    def test_yc_request_types_preserved_even_identical_source_and_missing_identity(
        self,
    ):
        for kind in ("0", "1"):
            self.capture("yc_cb", params("yc_cb", curve_type=kind), [source("yc_cb")])
        fixed = self.p.publish()
        rows = read_dataset(self.root, fixed, "yc_cb").to_pylist()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {json.loads(r["_request_identity"])["curve_type"] for r in rows},
            {"0", "1"},
        )
        # The documented filter contradiction is not silently aliased/repaired.
        self.assertEqual({r["curve_type"] for r in rows}, {"0"})
        self.assertIn(
            "example requests curve_type0", contract_for("yc_cb")["documentation_gap"]
        )
        self.capture(
            "yc_cb", {"trade_date": "20260904"}, [source("yc_cb")], epoch="missing"
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            read_dataset(self.root, self.p.publish(), "yc_cb")

    def test_discovery_projection_default_disabled_history_scopes_and_idempotence(self):
        self.p.plan_extended({}, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        sources = [
            ("cb_basic", "110001.SH"),
            ("cb_daily", "T110002.SH"),
            ("cb_issue", "123003.SZ"),
            ("cb_factor_pro", "110004.SH"),
            ("cb_rating", "T110005.SH"),
            ("top10_cb_holders", "123006.SZ"),
            ("stock_basic", "600001.SH"),
            ("repo_daily", "DR001.IB"),
            ("bond_blk", "149001.SZ"),
            ("bc_otcqt", "200013.BC"),
            ("yc_cb", "101"),
        ]
        for api, code in sources:
            self.discovery(
                api,
                [{"ts_code": code}, {"ts_code": 101}]
                if api == "yc_cb"
                else [{"ts_code": code}],
            )
        ids = self.p.identifiers()
        expected = {
            "110001.SH",
            "T110002.SH",
            "123003.SZ",
            "110004.SH",
            "T110005.SH",
            "123006.SZ",
        }
        self.assertEqual(set(ids["bond_extra_convertibles"]), expected)
        self.assertEqual(ids["bonds"], ["110001.SH"])
        self.assertEqual(ids["stocks"], ["600001.SH"])
        self.assertEqual(ids["repo_instruments"], ["DR001.IB"])
        self.assertEqual(ids["bond_trade_instruments"], ["149001.SZ"])
        self.assertEqual(ids["otc_bonds"], ["200013.BC"])
        self.assertEqual(ids["bond_curves"], ["101"])
        cfg = {
            "enable_bond_extra": True,
            "bond_extra_history_start": "20260904",
            "plan_jobs_per_tick": 1000,
        }
        self.p.plan_extended(cfg, date(2026, 9, 4))
        jobs = [
            json.loads(r[0])
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE group_name='bond_extra' AND state='pending'"
            )
        ]
        self.assertEqual({j["api_name"] for j in jobs}, set(FIELDS))
        self.assertEqual(
            {j["params"]["ts_code"] for j in jobs if j["api_name"] == "cb_rating"},
            expected,
        )
        self.assertTrue(
            all(
                set(j["params"]) == {"ts_code"}
                for j in jobs
                if j["api_name"] == "cb_rating"
            )
        )
        self.assertTrue(
            all(
                set(j["params"]) == {"ts_code", "start_date", "end_date"}
                for j in jobs
                if j["api_name"] == "top10_cb_holders"
            )
        )
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(cfg, date(2026, 9, 4))
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], count
        )
        self.assertEqual(
            set(module._planning_inputs("bond_extra", cfg, ids)[1]),
            {"bond_extra_convertibles"},
        )
        self.p.plan_extended(
            {"enable_bond_extra": True, "plan_jobs_per_tick": 1000}, date(2026, 9, 4)
        )
        self.assertIsNotNone(
            self.p.db.execute(
                "SELECT 1 FROM capability WHERE scope='planning:bond_extra:yc_cb:unknown_history_start_requires_scope'"
            ).fetchone()
        )

    def test_validation_blocked_only_this_family_hidden_missing_and_numeric_gap(self):
        ids = self.p.identifiers()
        ids["bond_extra_convertibles"] = ["bad;code"]
        with patch.object(self.p, "identifiers", return_value=ids):
            stats = self.p.plan_extended(
                {
                    "enable_bond_extra": True,
                    "enable_technical_extra": True,
                    "technical_extra_apis": ["stk_factor"],
                    "plan_jobs_per_tick": 100,
                },
                date(2026, 9, 4),
            )
        self.assertNotIn("recent:bond_extra", stats)
        self.assertIn("recent:technical_extra", stats)
        for api, hidden in [
            ("bc_otcqt", "coupon_rate"),
            ("bc_bestotcqt", "best_sell_yield"),
        ]:
            self.assertEqual(
                self.capture(api, params(api), [source(api)], omit=[hidden])[2][
                    "status"
                ],
                "schema_gap",
            )
        # An unexpected raw numeric curve identifier is not retyped or treated as stock.
        with self.assertRaisesRegex(ValueError, "source code must be a string"):
            self.capture(
                "yc_cb",
                params("yc_cb"),
                [source("yc_cb", ts_code=101)],
                epoch="numeric",
            )

    def test_legal_date_splits_report_axis_yc_identity_and_terminal_caps(self):
        for api in FIELDS:
            if api == "cb_rating":
                continue
            request = {"start_date": "20240228", "end_date": "20240301"}
            if api == "top10_cb_holders":
                request["ts_code"] = "T110001.SH"
            if api == "yc_cb":
                request["curve_type"] = "1"
            row, job, result = self.capture(
                api, request, [source(api)], more=True, epoch="range"
            )
            split = self.p.split_request(row, job, result)
            self.assertEqual(split["method"], "date_bisection")
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertEqual(
                {(p["start_date"], p["end_date"]) for p in children},
                {("20240228", "20240229"), ("20240301", "20240301")},
            )
            self.assertTrue(
                all(
                    all(
                        p[k] == v
                        for k, v in request.items()
                        if k not in ("start_date", "end_date")
                    )
                    for p in children
                )
            )
            if api == "top10_cb_holders":
                self.assertTrue(
                    all("trade_date" not in p and "ann_date" not in p for p in children)
                )
        for api in FIELDS:
            row, job, result = self.capture(
                api,
                params(api, ts_code=source(api)["ts_code"]),
                [source(api)],
                more=True,
                epoch="terminal",
            )
            self.assertIsNone(self.p.split_request(row, job, result))
        self.assertTrue(all(not contract_for(a).get("pagination") for a in FIELDS))

    def test_date_fanout_is_asset_specific_and_yc_never_drops_type(self):
        for api, code in [
            ("stock_basic", "600001.SH"),
            ("cb_basic", "110001.SH"),
            ("repo_daily", "DR007.IB"),
            ("bond_blk", "149001.SZ"),
            ("bc_otcqt", "200014.BC"),
            ("yc_cb", "1001.CB"),
        ]:
            self.discovery(api, [{"ts_code": code}])
        for api in ("repo_daily", "bond_blk", "bc_otcqt", "yc_cb"):
            row, job, result = self.capture(api, params(api), [source(api)], more=True)
            split = self.p.split_request(row, job, result)
            self.assertEqual(split["method"], "identifier_fanout")
            self.assertFalse(split["universe_complete"])
            children = [
                json.loads(r[0])["params"]
                for r in self.p.db.execute(
                    "SELECT j.job FROM partition_children c JOIN jobs j ON j.id=c.child_id WHERE c.parent_id=?",
                    (row["id"],),
                )
            ]
            self.assertNotIn("600001.SH", {p["ts_code"] for p in children})
            self.assertNotIn("110001.SH", {p["ts_code"] for p in children})
            self.assertTrue(all(p.items() >= params(api).items() for p in children))
        self.assertEqual(self.p.identifiers()["bonds"], ["110001.SH"])

    def test_real_run_terminal_saturation_preserves_source_and_blocks(self):
        keys = [
            self.p.enqueue(a, params(a, ts_code=source(a)["ts_code"]), 1, "terminal")
            for a in FIELDS
        ]

        def respond(request):
            sent = json.loads(request.content)
            api = sent["api_name"]
            row = source(api)
            self.assertEqual(set(sent["fields"].split(",")), set(FIELDS[api]))
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

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            self.assertEqual(
                self.p.run(
                    client, "fixture", {}, max_requests=8, max_seconds=10, pause=0
                )["requests"],
                8,
            )
        for key in keys:
            row = self.p.db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (key,)
            ).fetchone()
            self.assertEqual(row["state"], "blocked")
            result = json.loads(row["result"])
            self.assertEqual(result["status"], "possibly_truncated")
            self.assertTrue(
                (self.root / "observations" / result["observation"]).is_file()
            )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
