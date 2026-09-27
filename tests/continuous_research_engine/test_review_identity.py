"""Evidence packets may only describe terminal runs with matching identities."""

import copy
import hashlib
import unittest
from scripts.continuous_research.review_packets import validate_run


class ReviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "contract": {"end_date": "2026-03-24", "input_manifest_sha256": "etf"}
        }
        self.experiment = {"code": "code", "strategy_id": "1", "revision_id": "rev"}
        self.cfg = {
            "research_id": "program",
            "end_date": "2026-03-24",
            "strategy_id": "1",
            "strategy_revision": "rev",
            "code_sha256": hashlib.sha256(b"code").hexdigest(),
            "data_binding": {"manifest_sha256": "etf"},
        }

    def test_terminal_matched_runs_and_wrong_version_rejection(self):
        for status in ("completed", "failed"):
            validate_run(status, self.cfg, self.experiment, self.state, "program")
        for field, value in (
            ("research_id", "other"),
            ("strategy_revision", "other"),
            ("code_sha256", "other"),
            ("data_binding", {"manifest_sha256": "other"}),
            ("end_date", "2026-03-25"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_run(
                    "completed",
                    dict(self.cfg, **{field: value}),
                    self.experiment,
                    self.state,
                    "program",
                )
        for status in ("pending", "running"):
            with self.assertRaisesRegex(ValueError, "terminal"):
                validate_run(status, self.cfg, self.experiment, self.state, "program")

    def test_stock_binding_expression_and_code_identity(self):
        state = copy.deepcopy(self.state)
        state["stock_contract"] = {
            "manifest_sha256": "stock",
            "snapshot_id": "v2",
            "code_hashes": {"worker": "sha"},
        }
        experiment = {
            "kind": "stock_factor",
            "factor_id": "factor",
            "expression": "rank(x)",
            "input_manifest_sha256": "stock",
        }
        cfg = dict(
            self.cfg,
            factor_id="factor",
            proposal={"factor": {"expression": "rank(x)"}},
            stock_contract=state["stock_contract"],
            data_binding={"manifest_sha256": "stock", "snapshot_id": "v2"},
        )
        validate_run("completed", cfg, experiment, state, "program")
        for field, value in (
            ("factor_id", "other"),
            ("proposal", {}),
            ("stock_contract", {"code_hashes": {"worker": "other"}}),
            ("data_binding", {"manifest_sha256": "other", "snapshot_id": "v2"}),
        ):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "version"),
            ):
                validate_run(
                    "completed",
                    dict(cfg, **{field: value}),
                    experiment,
                    state,
                    "program",
                )
