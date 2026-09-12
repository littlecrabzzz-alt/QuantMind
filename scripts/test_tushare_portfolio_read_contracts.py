"""Offline private portfolio contracts and dependency-bound read plans."""

from copy import deepcopy
from datetime import date
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_portfolio_read_contracts as portfolio
from backend.shared.tushare_intake import capture_sample
from backend.shared.tushare_pipeline import Pipeline, _planning_inputs
from backend.shared.tushare_registry import EXTENDED_CONTRACTS, PLANNERS, contract_for
from backend.shared.tushare_store import dataset_schema, read_dataset
from backend.shared import tushare_store

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class PortfolioReadContracts(unittest.TestCase):
    def setUp(self):
        for name in ("socket.socket.connect", "socket.getaddrinfo"):
            blocked = patch(name, side_effect=AssertionError("offline only"))
            blocked.start()
            self.addCleanup(blocked.stop)
        self.today = date(2026, 9, 9)
        self.config = {
            "enable_portfolio_read": True,
            "portfolio_read_snapshot_epoch": "20260909T080000Z",
        }
        self.epoch = "snapshot-20260909T080000Z"

    def observed(self, rows, **changes):
        return {
            "portfolio_read_list": {
                "api_name": "p_list",
                "params": {},
                "epoch": self.epoch,
                "status": "done" if rows else "empty",
                "rows": rows,
                **changes,
            }
        }

    def jobs(self, identifiers=None, **config):
        return list(
            portfolio.iter_portfolio_read_jobs(
                {**self.config, **config}, self.today, identifiers
            )
        )

    def test_all13_columns_exact_input_and_no_mutations(self):
        entries = {
            api: entry
            for entry in json.loads((ROOT / "config/tushare-catalog.json").read_text())[
                "entries"
            ]
            for api in entry["api_names"]
        }
        self.assertEqual(set(portfolio.PORTFOLIO_READ_CONTRACTS), {"p_list", "p_get"})
        self.assertEqual(sum(map(len, portfolio.FIELDS.values())), 13)
        for api, spec in portfolio.PORTFOLIO_READ_CONTRACTS.items():
            self.assertEqual(spec["fields"], entries[api]["output_fields"])
            self.assertEqual(spec["allowed_params"], entries[api]["input_fields"])
            self.assertEqual(spec["fields"], spec["requested_fields"])
            self.assertEqual(spec["fields"], spec["required_fields"])
            self.assertEqual(spec["fields"], spec["nullable_fields"])
            self.assertEqual(spec["fields"], spec["extra_fields"])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertIsNone(spec["date_field"])
            self.assertIsNone(spec["split"])
            self.assertFalse(spec["default_enabled"])
            self.assertFalse(spec["row_cap_verified"])
            self.assertEqual(spec["permission_status"], "unprobed")
            for key in (
                "minimum_points",
                "documented_row_cap",
                "documented_requests_per_minute",
            ):
                self.assertIsNone(spec[key])
        self.assertEqual(
            portfolio.PORTFOLIO_READ_CONTRACTS["p_get"]["required_params"], ["name"]
        )

    def test_default_off_missing_epoch_and_no_history(self):
        for config in (
            {},
            {"enable_portfolio_read": True},
            {"history_start": "19900101"},
        ):
            self.assertEqual(
                list(portfolio.iter_portfolio_read_jobs(config, self.today)), []
            )
        self.assertEqual(
            self.jobs(history_start="19900101"),
            [{"api_name": "p_list", "params": {}, "priority": 10, "epoch": self.epoch}],
        )
        for bad in ("20260908T080000Z", "20260910T080000Z", "20260909", "garbage"):
            with self.assertRaises(ValueError):
                self.jobs(portfolio_read_snapshot_epoch=bad)
        self.assertEqual(
            self.jobs(portfolio_read_snapshot_epoch="20260908T160000Z")[0]["epoch"],
            "snapshot-20260908T160000Z",
        )

    def test_same_epoch_observed_names_only_and_source_unchanged(self):
        rows = [
            {"id": 7, "name": "仅测试组合甲", "desc": None, "new_unknown": ["opaque"]},
            {"id": 8, "name": "  合成组合乙  "},
            {"id": 7, "name": "仅测试组合甲"},
        ]
        source = self.observed(rows)
        before = deepcopy(source)
        jobs = self.jobs(source, portfolio_read_names=["must-not-seed"])
        self.assertEqual(source, before)
        self.assertEqual([j["api_name"] for j in jobs], ["p_list", "p_get", "p_get"])
        self.assertEqual(
            [j["params"] for j in jobs[1:]],
            [{"name": "  合成组合乙  "}, {"name": "仅测试组合甲"}],
        )
        self.assertEqual(self.jobs(source), jobs)
        self.assertEqual(
            self.jobs(None, portfolio_read_names=["must-not-seed"])[0]["params"], {}
        )
        self.assertEqual(
            len(self.jobs(source, portfolio_read_snapshot_epoch="20260909T090000Z")), 1
        )

    def test_empty_is_successful_observation_not_failed_dependency(self):
        source = self.observed([])
        self.assertEqual(self.jobs(source, portfolio_read_apis=["p_get"]), [])
        gaps = portfolio.portfolio_read_prerequisites(source, config=self.config)
        state = next(g for g in gaps if g["reason"] == "observed_no_custom_portfolios")
        self.assertFalse(state["is_failure"])
        self.assertFalse(state["universe_complete"])
        self.assertEqual(state["observed_portfolios"], 0)
        self.assertNotIn(
            "awaiting_stored_list_observation", [g["reason"] for g in gaps]
        )
        for status in ("pending", "permission_denied", "possibly_truncated"):
            self.assertEqual(len(self.jobs(self.observed([], status=status))), 1)

    def test_reject_invalid_or_ambiguous_source_without_private_error_details(self):
        secret_marker = "fixture-private-name"
        invalid = [
            self.observed([{"id": True, "name": secret_marker}]),
            self.observed([{"id": 1, "name": secret_marker + "\n"}]),
            self.observed([{"id": 1, "name": ""}]),
            self.observed(
                [{"id": 1, "name": secret_marker}, {"id": 2, "name": secret_marker}]
            ),
            self.observed([{"id": 1, "name": secret_marker}], status="empty"),
            self.observed([], status="done"),
            self.observed(
                [{"id": 1, "name": secret_marker}, {"id": 1, "name": "changed"}]
            ),
            self.observed([], params={"name": secret_marker}),
            self.observed([], api_name="p_save"),
        ]
        for source in invalid:
            with (
                self.subTest(shape=type(source).__name__),
                self.assertRaises(ValueError) as error,
            ):
                self.jobs(source)
            self.assertNotIn(secret_marker, str(error.exception))
        gaps = portfolio.portfolio_read_prerequisites(
            self.observed([{"id": 1, "name": secret_marker}]), config=self.config
        )
        self.assertNotIn(secret_marker, json.dumps(gaps))

    def test_api_allowlist_no_user_mutations_or_guessed_id_inputs(self):
        for selection in (
            ["p_save"],
            ["p_delete"],
            ["p_get", "p_save"],
            "p_get",
            [None],
        ):
            with self.assertRaises(ValueError):
                self.jobs(portfolio_read_apis=selection)
        source = self.observed([{"id": 1, "name": "fixture"}])
        self.assertEqual(
            self.jobs(source, portfolio_read_apis=["p_get"])[0]["params"],
            {"name": "fixture"},
        )
        spec = portfolio.PORTFOLIO_READ_CONTRACTS["p_get"]
        self.assertEqual(spec["request_identity_fields"], ["name"])
        self.assertEqual(spec["positive_fields"], [])
        self.assertIn("opaque", spec["source_namespace"])
        self.assertIn("user-defined", spec["component_note"])

    def test_lazy_bounded_consumption_retains_full_scope(self):
        source = self.observed(
            [{"id": i, "name": f"synthetic-{i:05d}"} for i in range(1500)]
        )
        stream = portfolio.iter_portfolio_read_jobs(self.config, self.today, source)
        self.assertEqual(len(list(islice(stream, 5))), 5)
        self.assertEqual(len(list(stream)), 1496)


class PortfolioReadRuntime(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            blocked = patch(target, side_effect=AssertionError("offline only"))
            blocked.start()
            self.addCleanup(blocked.stop)

    def capture(self, api, params, rows, epoch):
        task_id = self.pipeline.enqueue(api, params, 10, epoch)
        saved = self.pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (task_id,)
        ).fetchone()
        job = json.loads(saved["job"])

        def respond(request):
            sent = json.loads(request.content)
            self.assertEqual(sent["api_name"], api)
            self.assertEqual(sent["params"], params)
            self.assertEqual(set(sent["fields"].split(",")), set(portfolio.FIELDS[api]))
            fields = list(rows[0]) if rows else portfolio.FIELDS[api]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[row.get(field) for field in fields] for row in rows],
                        "has_more": False,
                    },
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = self.pipeline.normalize(
                capture_sample(client, "test-token-opaque", job, self.root)
            )
        state = "done" if rows else "empty"
        if result["status"] not in ("sample_ok", "empty_unverified"):
            state = "quality"
        with self.pipeline.db:
            self.pipeline.db.execute(
                "INSERT INTO attempts VALUES(?,?,?)",
                (task_id, 1, json.dumps(result)),
            )
            self.pipeline.db.execute(
                "UPDATE jobs SET result=?,state=?,tries=1 WHERE id=?",
                (json.dumps(result), state, task_id),
            )
        return task_id, result

    def test_registry_is_read_only_default_disabled_and_policy_is_snapshot_bound(self):
        self.assertEqual(
            set(EXTENDED_CONTRACTS).intersection(
                {"p_list", "p_get", "p_save", "p_delete"}
            ),
            {"p_list", "p_get"},
        )
        self.assertEqual(set(PLANNERS).intersection({"portfolio_read"}), {"portfolio_read"})
        self.assertEqual(set(contract_for("p_list")), set(EXTENDED_CONTRACTS["p_list"]))
        self.assertEqual(contract_for("p_save"), {})
        self.assertEqual(contract_for("p_delete"), {})
        self.assertFalse({"p_save", "p_delete"}.intersection(tushare_store.KEYS))
        self.assertTrue({"p_list", "p_get"}.issubset(tushare_store.KEYS))
        self.assertEqual(
            list(PLANNERS["portfolio_read"]({}, date(2026, 9, 9), {})), []
        )
        base = {
            "enable_portfolio_read": True,
            "portfolio_read_snapshot_epoch": "20260909T080000Z",
        }
        first = _planning_inputs("portfolio_read", base, {})
        changed = _planning_inputs(
            "portfolio_read",
            {**base, "portfolio_read_snapshot_epoch": "20260909T090000Z"},
            {},
        )
        self.assertNotEqual(first[0], changed[0])

    def test_two_phase_plan_and_fixed_query_preserve_private_component_identity(self):
        config = {
            "enable_portfolio_read": True,
            "portfolio_read_snapshot_epoch": "20260909T080000Z",
            "plan_jobs_per_tick": 20,
        }
        self.pipeline.plan_extended(config, date(2026, 9, 9))
        jobs = [
            json.loads(row[0])
            for row in self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE group_name='portfolio_read' ORDER BY rowid"
            ).fetchall()
        ]
        self.assertEqual([(j["api_name"], j["params"]) for j in jobs], [("p_list", {})])
        epoch = "snapshot-20260909T080000Z"
        self.capture(
            "p_list",
            {},
            [
                {
                    "id": 7,
                    "name": "private-fixture",
                    "desc": None,
                    "create_time": "2026-09-09 08:00:00",
                    "update_time": "2026-09-09 08:00:00",
                }
            ],
            epoch,
        )
        self.pipeline.plan_extended(config, date(2026, 9, 9))
        member = self.pipeline.db.execute(
            "SELECT job FROM jobs WHERE group_name='portfolio_read' "
            "AND json_extract(job,'$.api_name')='p_get'"
        ).fetchone()
        self.assertIsNotNone(member)
        self.assertEqual(json.loads(member[0])["params"], {"name": "private-fixture"})

        self.capture(
            "p_get",
            {"name": "private-fixture"},
            [
                {
                    "id": 11,
                    "ts_code": "000001.SZ",
                    "ts_type": "custom",
                    "name": "component",
                    "desc": None,
                    "weight": 0.25,
                    "create_time": "2026-09-09 08:01:00",
                    "update_time": "2026-09-09 08:01:00",
                    "supplier_extra": {"opaque": True},
                }
            ],
            epoch,
        )
        self.capture(
            "p_get",
            {"name": "another-private-fixture"},
            [
                {
                    "id": 11,
                    "ts_code": "000001.SZ",
                    "ts_type": "custom",
                    "name": "component",
                    "desc": None,
                    "weight": 0.5,
                    "create_time": "2026-09-09 08:02:00",
                    "update_time": "2026-09-09 08:02:00",
                    "supplier_extra": {"opaque": True},
                }
            ],
            epoch,
        )
        release = self.pipeline.publish()
        table = read_dataset(self.root, release, "p_get", codes=["000001.SZ"])
        self.assertEqual(table.num_rows, 2)
        row = table.to_pylist()[0]
        self.assertEqual(row["ts_code"], "000001.SZ")
        self.assertEqual(row["source_ts_code"], "000001.SZ")
        self.assertEqual(row["supplier_extra"], {"opaque": True})
        self.assertEqual(
            {json.loads(item["_request_identity"])["name"] for item in table.to_pylist()},
            {"private-fixture", "another-private-fixture"},
        )
        schema = dataset_schema(self.root, release, "p_get")
        self.assertEqual(schema["visibility"], "account_private")
        self.assertEqual(schema["default_code_field"], "source_ts_code")


if __name__ == "__main__":
    unittest.main()
