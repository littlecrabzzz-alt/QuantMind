import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.shared.tushare_intake import digest, json_bytes
from backend.shared.tushare_registry import EXTENDED_CONTRACTS
from scripts import prepare_tushare_index_daily_balanced_candidate as candidate


class BalancedIndexDailyCandidateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release_sha = "1" * 64
        self.discovery_path = self.root / "discovery.json"
        self.inventory_path = self.root / "inventory.json"
        self.output = self.root / "candidate.json"
        self.codes = {
            "SSE": ["000001.SH", "000002.SH", "000003.SH"],
            "SZSE": ["399001.SZ", "399002.SZ", "399003.SZ"],
            "CSI": ["000300.CSI", "000905.CSI", "000906.CSI"],
        }
        self.discovery = self._discovery()
        self._save(self.discovery_path, self.discovery)
        records = [
            self._record(code, year)
            for codes in self.codes.values()
            for code in codes
            for year in (2024, 2025)
        ]
        records.append(self._record("IF2609.CFX", 2025))
        self.inventory = self._inventory(records)
        self._save(self.inventory_path, self.inventory)

    @staticmethod
    def _save(path, value):
        path.write_bytes(json_bytes(value))

    def _discovery(self):
        markets = {
            market: {
                "codes": codes,
                "codes_count": len(codes),
                "codes_sha256": digest(json_bytes(codes)),
            }
            for market, codes in self.codes.items()
        }
        return {
            "schema_version": 1,
            "kind": "tushare_fixed_release_index_discovery_evidence",
            "source": {
                "release_id": "data-" + self.release_sha,
                "release_manifest_sha256": self.release_sha,
                "release_manifest_bytes": 100,
                "manifest_sha256_verified": True,
                "current_pointer_sha256": "9" * 64,
                "current_pointer_verified": True,
                "fixed_mirror_read_only": True,
                "upstream_calls": 0,
                "credentials_accessed": False,
            },
            "eligible_index_daily_markets": markets,
            "index_basic_source_refs": [
                {
                    "api_name": "index_basic",
                    "bytes": 10,
                    "path": "parquet/" + "2" * 64 + ".parquet",
                    "quality_state": "sample_ok",
                    "rows": 9,
                    "sha256": "2" * 64,
                    "observed_markets": list(self.codes),
                }
            ],
            "cffex_boundary": {
                "family": "futures",
                "eligible_for_index_daily": False,
                "codes_count": 1,
                "source_refs": [{"path": "parquet/" + "3" * 64 + ".parquet"}],
            },
        }

    @staticmethod
    def _record(code, year):
        params = {
            "ts_code": code,
            "start_date": f"{year}0101",
            "end_date": f"{year}1231",
        }
        spec = EXTENDED_CONTRACTS[candidate.API]
        job = {
            "api_name": candidate.API,
            "params": params,
            "fields": ",".join(
                sorted(set(spec["required_fields"]) | set(spec["extra_fields"]))
            ),
            "row_cap": spec["row_cap"],
            "required_fields": spec["required_fields"],
            "nullable_fields": spec["nullable_fields"],
            "positive_fields": spec["positive_fields"],
        }
        logical = digest(json_bytes(job))
        return {
            "task_id": digest(json_bytes([logical, "history"])),
            "logical_key": logical,
            "epoch": "history",
            "priority": 45,
            "group_name": "structured",
            "state": "pending",
            "tries": 0,
            "result": None,
            "attempt_count": 0,
            "job": job,
        }

    def _inventory(self, records, reserved=()):
        reserved = sorted(reserved)
        ids = sorted(record["task_id"] for record in records)
        return {
            "schema_version": 1,
            "kind": "tushare_index_daily_pristine_authority_inventory",
            "source": {
                "release_id": "data-" + self.release_sha,
                "release_manifest_sha256": self.release_sha,
                "current_pointer_sha256": "4" * 64,
                "authority_config_sha256": "5" * 64,
                "pipeline_schema_version": 6,
                "captured_under_shared_lock": True,
                "query_only": True,
                "attempt_join_complete": True,
                "prior_plan_inventory_complete": True,
            },
            "records": records,
            "records_sha256": digest(json_bytes(records)),
            "all_task_ids_sha256": digest(json_bytes(ids)),
            "reserved_task_ids": reserved,
            "reserved_task_ids_sha256": digest(json_bytes(reserved)),
        }

    def _build(self, jobs=6):
        return candidate.build_candidate(
            self.discovery_path,
            candidate.sha(self.discovery_path),
            self.inventory_path,
            candidate.sha(self.inventory_path),
            jobs,
        )

    def test_balances_three_markets_and_excludes_cffex(self):
        value = self._build()
        self.assertEqual(
            value["selected"]["market_counts"], {"SSE": 2, "SZSE": 2, "CSI": 2}
        )
        self.assertEqual(len(value["records"]), 6)
        self.assertNotIn(
            "IF2609.CFX",
            {record["job"]["params"]["ts_code"] for record in value["records"]},
        )
        self.assertEqual(value["unproven_suffix_counts"], {"CFX": 1})
        self.assertFalse(value["limits"]["publish"])
        self.assertFalse(value["limits"]["implicit_queue_allowed"])

    def test_reserved_and_attempted_tasks_cannot_enter(self):
        reserved = self.inventory["records"][0]["task_id"]
        attempted = dict(self.inventory["records"][1])
        attempted["attempt_count"] = 1
        blocked = self._inventory(
            [attempted, *self.inventory["records"][2:]], [reserved]
        )
        self._save(self.inventory_path, blocked)
        with self.assertRaisesRegex(ValueError, "non-pristine"):
            self._build()

    def test_insufficient_one_market_fails_closed(self):
        records = [
            record
            for record in self.inventory["records"]
            if not record["job"]["params"]["ts_code"].endswith(".CSI")
        ]
        self._save(self.inventory_path, self._inventory(records))
        with self.assertRaisesRegex(ValueError, "Insufficient balanced"):
            self._build()

    def test_input_hash_identity_and_hard_limit_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            candidate.build_candidate(
                self.discovery_path,
                "0" * 64,
                self.inventory_path,
                candidate.sha(self.inventory_path),
                6,
            )
        broken = json.loads(self.inventory_path.read_bytes())
        broken["records"][0]["task_id"] = "0" * 64
        self._save(self.inventory_path, broken)
        with self.assertRaisesRegex(ValueError, "Task identity mismatch"):
            self._build()
        with self.assertRaisesRegex(ValueError, "between 1 and 360"):
            candidate.select_records(self.inventory, {}, 361, self.release_sha)

    def test_candidate_is_deterministic_and_self_verifies(self):
        first = self._build(9)
        second = self._build(9)
        self.assertEqual(json_bytes(first), json_bytes(second))
        self._save(self.output, first)
        verified = candidate.verify_candidate(self.output, candidate.sha(self.output))
        self.assertEqual(verified["all_task_ids_sha256"], first["all_task_ids_sha256"])
        changed = json.loads(self.output.read_bytes())
        changed["limits"]["publish"] = True
        self._save(self.output, changed)
        with self.assertRaisesRegex(ValueError, "Invalid balanced candidate"):
            candidate.verify_candidate(self.output, candidate.sha(self.output))

    def test_builder_never_uses_network_or_credentials(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network")):
            value = self._build()
        self.assertEqual(value["boundaries"]["upstream_calls"], 0)
        self.assertFalse(value["boundaries"]["authority_accessed_by_builder"])
        self.assertFalse(value["boundaries"]["credentials_accessed"])


if __name__ == "__main__":
    unittest.main()
