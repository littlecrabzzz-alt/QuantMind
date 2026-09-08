"""PCF raw cash rows through immutable capture, durable planning and offline reads."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_etf_basket_contracts import FIELDS, INPUT_FIELDS
from backend.shared.tushare_intake import capture_sample
from backend.shared.tushare_registry import PLANNERS, contract_for
from backend.shared.tushare_store import read_dataset, export_jsonl

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


def basket(api):
    row = dict.fromkeys(FIELDS[api])
    row.update(
        trade_date="20260625",
        ts_code="517030.SH" if api == "etf_sh_cons" else "159051.SZ",
        con_code="00001.HK" if api == "etf_sh_cons" else "159900.SZ",
        con_name="香港成分" if api == "etf_sh_cons" else "申赎现金",
        qty=0,
        sub_flag="必须",
        cpr="-",
        rdr=0.0,
        exchange="HK" if api == "etf_sh_cons" else "OTH",
    )
    if api == "etf_sh_cons":
        row["sca"] = None
    else:
        row.update(sub_cc=512407.5, red_cc=141173.9)
    row["unknown_supplier_field"] = "原文字段"
    return row


class EtfBasketPipelineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
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

    def capture(self, api, params, rows=None, *, has_more=False):
        key = self.p.enqueue(api, params, epoch="pcf-fixture")
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        job = json.loads(row["job"])
        rows = [basket(api)] if rows is None else rows
        fields = list(rows[0])

        def respond(request):
            sent = json.loads(request.content)
            if api in FIELDS:
                self.assertTrue(set(FIELDS[api]) <= set(sent["fields"].split(",")))
                self.assertTrue(set(params) <= set(INPUT_FIELDS[api]))
                self.assertNotIn("_row_identity", sent["fields"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[r.get(f) for f in fields] for r in rows],
                        "has_more": has_more,
                    },
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            result = capture_sample(client, "fixture", job, self.root)
        result = self.p.normalize(result)
        attempt = row["tries"] + 1
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (key, attempt, json.dumps(result))
        )
        self.p.db.execute(
            "UPDATE jobs SET result=?,state=?,tries=? WHERE id=?",
            (
                json.dumps(result),
                "done" if result["status"] == "sample_ok" else "quality",
                attempt,
                key,
            ),
        )
        self.p.db.commit()
        return (
            self.p.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone(),
            job,
            result,
        )

    def test_raw_scalar_roundtrip_cash_overseas_revisions_and_projection(self):
        expected = {}
        for api in FIELDS:
            first = basket(api)
            rows = [first, {**first, "qty": 0.0, "cpr": 0, "rdr": "-"}]
            expected[api] = rows
            _, _, result = self.capture(
                api, {"ts_code": first["ts_code"], "trade_date": "20260625"}, rows
            )
            self.assertEqual(result["status"], "sample_ok")
            self.assertEqual(contract_for(api)["group"], "etf_basket")
        release = self.p.publish()
        for api in FIELDS:
            table = read_dataset(self.root, release, api)
            self.assertEqual(table.num_rows, 2)
            metadata = json.loads(table.schema.metadata[b"tushare"])
            numeric_fields = contract_for(api)["raw_numeric_fields"]
            self.assertEqual(
                set(metadata["source_scalar_encodings"]), set(numeric_fields)
            )
            self.assertEqual(metadata["upstream_calls"], 0)
            observed = []
            for row in table.to_pylist():
                original = json.loads(row["_raw_numeric_json"])
                self.assertTrue(
                    all(
                        row[f] is None or isinstance(row[f], str)
                        for f in numeric_fields
                    )
                )
                restored = {
                    f: original[f] if f in numeric_fields else row[f]
                    for f in FIELDS[api]
                }
                restored["ts_code"] = row["source_ts_code"]
                restored["unknown_supplier_field"] = row["unknown_supplier_field"]
                observed.append(restored)
                self.assertEqual(
                    row["ts_code"], "SH517030" if api == "etf_sh_cons" else "SZ159051"
                )

            def canonical(values):
                return sorted(
                    json.dumps(r, sort_keys=True, ensure_ascii=False) for r in values
                )

            self.assertEqual(canonical(observed), canonical(expected[api]))
            projected = read_dataset(
                self.root, release, api, fields=["qty", "_raw_numeric_json"]
            )
            self.assertEqual(set(projected.column_names), {"qty", "_raw_numeric_json"})
            destination = self.root.parent / (self.root.name + api + ".jsonl")
            self.addCleanup(lambda p=destination: p.unlink(missing_ok=True))
            export_jsonl(self.root, release, api, destination)
            self.assertTrue(
                all(
                    isinstance(r["qty"], str)
                    and isinstance(r["_raw_numeric_json"], str)
                    for r in map(json.loads, destination.read_text().splitlines())
                )
            )

    def test_discovery_only_etf_basic_including_old_observations(self):
        for code in ("T517030.SH", "159051.SZ"):
            self.capture(
                "etf_basic",
                {},
                [{"ts_code": code, "list_status": "D", "list_date": "20000101"}],
            )
        self.capture("fund_basic", {}, [{"ts_code": "510999.SH", "name": "普通基金"}])
        self.capture(
            "stock_basic",
            {},
            [{"ts_code": "600000.SH", "name": "股票", "symbol": "600000"}],
        )
        self.capture("etf_sz_cons", {"trade_date": "20260625"})
        ids = self.p.identifiers()
        self.assertEqual(ids["etfs"], ["159051.SZ", "T517030.SH"])
        self.assertIn("510999.SH", ids["funds"])
        self.assertNotIn("159900.SZ", ids["etfs"])

    def test_planner_flags_gaps_signature_idempotence_and_family_isolation(self):
        self.assertIn("etf_basket", PLANNERS)
        self.capture(
            "etf_basic",
            {},
            [{"ts_code": "517030.SH", "list_status": "D", "list_date": "20000101"}],
        )
        config = {
            "enable_etf_basket": True,
            "etf_basket_history_start": "20260901",
            "plan_jobs_per_tick": 100,
        }
        stats = self.p.plan_extended(config, date(2026, 9, 9))
        self.assertIn("recent:etf_basket", stats)
        self.assertIn("history:etf_basket", stats)
        n = self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            n, self.p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        )
        old = self.p.db.execute(
            "SELECT signature FROM planning_state WHERE name='history:etf_basket'"
        ).fetchone()[0]
        config["etf_basket_history_start"] = "20260831"
        self.p.plan_extended(config, date(2026, 9, 9))
        self.assertNotEqual(
            old,
            self.p.db.execute(
                "SELECT signature FROM planning_state WHERE name='history:etf_basket'"
            ).fetchone()[0],
        )
        gaps = dict(self.p.db.execute("SELECT scope,reason FROM capability"))
        self.assertIn("planning:etf_basket:etf_sh_cons:publication_gap", gaps)
        self.assertIn(
            "planning:etf_basket:etf_sh_cons:account_permission_unprobed", gaps
        )
        config.update(
            etf_basket_apis=["not_real"],
            enable_research_extra=True,
            research_extra_apis=["report_rc"],
        )
        stats = self.p.plan_extended(config, date(2026, 9, 10))
        self.assertNotIn("recent:etf_basket", stats)
        self.assertIn("recent:research_extra", stats)
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:etf_basket'"
            ).fetchone()[0],
            "validation_blocked",
        )

    def test_range_split_single_day_and_unknown_history_cannot_fake_completion(self):
        for params in (
            {"ts_code": "517030.SH", "start_date": "20260624", "end_date": "20260625"},
            {"ts_code": "517030.SH", "start_date": "20260625", "end_date": "20260625"},
            {"ts_code": "517030.SH"},
        ):
            row, job, result = self.capture("etf_sh_cons", params, has_more=True)
            self.assertEqual(result["status"], "possibly_truncated")
            split = self.p.split_request(row, job, result)
            if params.get("start_date") == "20260624":
                self.assertEqual(split["method"], "date_bisection")
                self.assertEqual(split["children"], 2)
            else:
                self.assertIsNone(split)
            self.assertNotIn("offset", job["params"])
            self.assertNotIn("saturation_fallback", contract_for("etf_sh_cons"))
        self.p.reconcile_partitions()
        self.assertFalse(
            self.p.db.execute(
                "SELECT 1 FROM partition_splits WHERE status='resolved'"
            ).fetchone()
        )

    def test_permission_denial_preserves_raw_evidence_without_data(self):
        key = self.p.enqueue("etf_sh_cons", {"ts_code": "517030.SH"}, epoch="denied")
        job = json.loads(
            self.p.db.execute("SELECT job FROM jobs WHERE id=?", (key,)).fetchone()[0]
        )
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"code": 2002, "msg": "没有权限"}
                )
            ),
            trust_env=False,
        ) as client:
            result = capture_sample(client, "fixture", job, self.root)
        self.assertEqual(self.p.normalize(result)["status"], "permission_denied")
        self.assertTrue((self.root / "observations" / result["observation"]).is_file())
        self.assertNotIn("parquet", result)

    def test_mirror_deploys_contract_module(self):
        import ast

        tree = ast.parse(
            (
                Path(__file__).resolve().parents[1] / "scripts/tushare_mirror.py"
            ).read_text()
        )
        install = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "install_schedule"
        )
        strings = {
            node.value
            for node in ast.walk(install)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("backend/shared/tushare_etf_basket_contracts.py", strings)


if __name__ == "__main__":
    unittest.main()
