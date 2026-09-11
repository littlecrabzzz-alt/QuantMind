"""Focused tests for offline CITIC membership evidence reconciliation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_rrg_member_pit as module


class MemberPitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "mirror"
        self.evidence_dir = self.base / "evidence"
        fixed_manifest_bytes = b"{}\n"
        self.release = "data-" + hashlib.sha256(fixed_manifest_bytes).hexdigest()
        manifest = self.root / "releases" / self.release / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(fixed_manifest_bytes)
        self.evidence_dir.mkdir()
        self.rows = [
            {
                "_row_identity": "1" * 64,
                "l1_code": "CI005001",
                "ts_code": "SH600001",
                "source_l1_code": "CI005001.CI",
                "source_ts_code": "600001.SH",
                "in_date": "20200110",
                "out_date": None,
                "_fetched_at": "2026-09-11T00:00:00+00:00",
            }
        ]

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def resign_after_file_change(self, artifact_root, relative):
        changed = artifact_root / relative
        manifest_path = artifact_root / module.MANIFEST_FILE
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][relative] = {
            "bytes": changed.stat().st_size,
            "sha256": self.digest(changed.read_bytes()),
        }
        raw = (json.dumps(manifest, indent=2) + "\n").encode()
        manifest_path.write_bytes(raw)
        return self.digest(raw)

    def source(self, name, data=b"claimed announcement"):
        path = self.evidence_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {
            "path": name,
            "bytes": len(data),
            "sha256": self.digest(data),
            "url": "https://example.test/" + name,
        }

    def write_evidence(self, announcements, **overrides):
        payload = {
            "schema_version": 1,
            "provider": "CITIC",
            "taxonomy": "CITIC_L1",
            "revision_semantics": "full_replacement",
            "announcements": announcements,
        }
        payload.update(overrides)
        path = self.evidence_dir / "manifest.json"
        path.write_text(json.dumps(payload))
        return path

    def announcement(
        self,
        announcement_id="notice-1",
        revision=1,
        published_at="2020-01-01T16:00:00+08:00",
        changes=None,
        status="published",
        supersedes_revision=None,
        source_name=None,
    ):
        source_name = source_name or f"{announcement_id}-{revision}.pdf"
        return {
            "announcement_id": announcement_id,
            "revision": revision,
            "supersedes_revision": supersedes_revision,
            "status": status,
            "published_at": published_at,
            "taxonomy_version": "CITIC-2020",
            "source": self.source(source_name),
            "changes": changes
            if changes is not None
            else [
                {
                    "source_sector_code": "CI005001.CI",
                    "source_symbol": "600001.SH",
                    "effective_date": "20200110",
                    "action": "add",
                }
            ],
        }

    def run_prepare(self, evidence, output_name="output"):
        table = pa.Table.from_pylist(self.rows).replace_schema_metadata(
            {
                b"tushare": json.dumps(
                    {"release_id": self.release, "upstream_calls": 0}
                ).encode()
            }
        )
        output = self.base / output_name
        with (
            patch.object(
                module,
                "manifest_at",
                return_value={"retained_observations_included": True},
            ),
            patch.object(module, "read_dataset", return_value=table),
        ):
            report = module.prepare(self.root, self.release, evidence, output)
        return report, output

    def test_reconciled_content_does_not_claim_source_authority(self):
        evidence = self.write_evidence([self.announcement()])
        report, output = self.run_prepare(evidence)
        self.assertEqual(report["status"], "content_reconciled")
        self.assertTrue(report["reconciliation"]["content_complete_for_fixed_source"])
        row = pq.read_table(output / module.DATA_FILE).to_pylist()[0]
        self.assertEqual(row["known_at"], "2020-01-01T08:00:00+00:00")
        self.assertEqual(row["entry_announcement_id"], "notice-1")
        self.assertEqual(len(row["entry_source_sha256"]), 64)
        self.assertTrue(row["content_reconciled"])
        self.assertFalse(row["source_authority_verified"])
        self.assertFalse(row["historical_known_at_verified"])
        artifact = json.loads((output / module.MANIFEST_FILE).read_text())
        self.assertEqual(artifact["release_id"], self.release)
        self.assertEqual(
            artifact["evidence_manifest"]["sha256"],
            report["evidence_manifest"]["sha256"],
        )
        self.assertEqual(
            artifact["evidence_manifest"]["locator"], "evidence/manifest.json"
        )
        self.assertGreater(artifact["evidence_manifest"]["bytes"], 0)
        self.assertEqual(
            artifact["fixed_manifest"]["locator"],
            f"releases/{self.release}/manifest.json",
        )
        self.assertGreater(artifact["fixed_manifest"]["bytes"], 0)
        self.assertEqual(
            artifact["fixed_manifest"]["sha256"],
            self.release.removeprefix("data-"),
        )
        self.assertEqual(artifact["status"], "content_reconciled")
        self.assertEqual(
            set(artifact["files"]),
            {
                module.DATA_FILE,
                module.REPORT_FILE,
                "evidence/manifest.json",
                "evidence/notice-1-1.pdf",
            },
        )
        for name, expected in artifact["files"].items():
            path = output / name
            self.assertEqual(path.stat().st_size, expected["bytes"])
            self.assertEqual(self.digest(path.read_bytes()), expected["sha256"])
        self.assertNotIn(str(self.base), json.dumps(report))
        self.assertNotIn(str(self.base), json.dumps(artifact))
        parquet_metadata = json.loads(
            pq.read_schema(output / module.DATA_FILE).metadata[b"rrg_member_pit"]
        )
        self.assertFalse(parquet_metadata["source_authority_verified"])
        self.assertFalse(parquet_metadata["historical_known_at_verified"])
        self.assertNotIn(str(self.base), json.dumps(parquet_metadata))
        self.assertFalse(report["boundaries"]["rrg_case_changed"])
        self.assertFalse(report["boundaries"]["rrg_ready"])
        self.assertFalse(report["boundaries"]["source_authority_verified"])
        self.assertFalse(report["boundaries"]["signal_date_cutoff_evaluated"])
        self.assertFalse(report["boundaries"]["quantdb_changed"])
        self.assertEqual(report["boundaries"]["upstream_calls"], 0)

    def test_artifact_copies_to_a_new_root_and_verifies_without_original_evidence(self):
        evidence = self.write_evidence(
            [self.announcement(source_name="files/notice-1-1.pdf")]
        )
        _, output = self.run_prepare(evidence)
        expected_manifest_sha256 = self.digest(
            (output / module.MANIFEST_FILE).read_bytes()
        )
        copied = self.base / "other-node" / "artifact"
        shutil.copytree(output, copied)
        shutil.rmtree(self.evidence_dir)

        artifact = module.verify_artifact(copied, expected_manifest_sha256)
        bundled = module.load_evidence_manifest(
            copied / artifact["evidence_manifest"]["locator"]
        )
        self.assertEqual(bundled["active_announcements"], 1)
        self.assertEqual(bundled["bytes"], artifact["evidence_manifest"]["bytes"])
        self.assertEqual(bundled["sha256"], artifact["evidence_manifest"]["sha256"])
        self.assertTrue((copied / "evidence" / "files" / "notice-1-1.pdf").is_file())

    def test_tampered_bundled_source_fails_artifact_verification(self):
        evidence = self.write_evidence([self.announcement()])
        _, output = self.run_prepare(evidence)
        expected_manifest_sha256 = self.digest(
            (output / module.MANIFEST_FILE).read_bytes()
        )
        source = output / "evidence" / "notice-1-1.pdf"
        source.write_bytes(source.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            module.verify_artifact(output, expected_manifest_sha256)

    def test_wrong_expected_root_manifest_hash_is_rejected(self):
        evidence = self.write_evidence([self.announcement()])
        _, output = self.run_prepare(evidence)
        with self.assertRaisesRegex(ValueError, "manifest SHA256 mismatch"):
            module.verify_artifact(output, "0" * 64)

    def test_root_manifest_cannot_self_promote_status_or_safety_boundaries(self):
        evidence = self.write_evidence([self.announcement()])
        _, output = self.run_prepare(evidence)
        upgrades = {
            "status": "verified",
            "source_authority_verified": True,
            "historical_known_at_verified": True,
            "rrg_ready": True,
        }
        for field, value in upgrades.items():
            with self.subTest(field=field):
                forged = self.base / f"forged-{field}"
                shutil.copytree(output, forged)
                manifest_path = forged / module.MANIFEST_FILE
                manifest = json.loads(manifest_path.read_text())
                manifest[field] = value
                raw = (json.dumps(manifest, indent=2) + "\n").encode()
                manifest_path.write_bytes(raw)
                with self.assertRaisesRegex(
                    ValueError, "status mismatch|Unsafe artifact promotion"
                ):
                    module.verify_artifact(forged, self.digest(raw))

    def test_parquet_row_promotion_fails_after_inventory_and_root_resigning(self):
        evidence = self.write_evidence([self.announcement()])
        _, output = self.run_prepare(evidence)
        for field in (
            "source_authority_verified",
            "historical_known_at_verified",
        ):
            with self.subTest(field=field):
                forged = self.base / f"forged-parquet-{field}"
                shutil.copytree(output, forged)
                data_path = forged / module.DATA_FILE
                table = pq.read_table(data_path)
                index = table.column_names.index(field)
                promoted = table.set_column(
                    index,
                    field,
                    pa.array([True] + table[field].to_pylist()[1:]),
                )
                pq.write_table(promoted, data_path)
                expected = self.resign_after_file_change(forged, module.DATA_FILE)
                with self.assertRaisesRegex(ValueError, "Parquet row promotion"):
                    module.verify_artifact(forged, expected)

    def test_each_report_boundary_fails_after_inventory_and_root_resigning(self):
        evidence = self.write_evidence([self.announcement()])
        _, output = self.run_prepare(evidence)
        for field, safe_value in module.SAFE_BOUNDARIES.items():
            with self.subTest(field=field):
                forged = self.base / f"forged-report-{field}"
                shutil.copytree(output, forged)
                report_path = forged / module.REPORT_FILE
                report = json.loads(report_path.read_text())
                if isinstance(safe_value, bool):
                    report["boundaries"][field] = not safe_value
                elif isinstance(safe_value, int):
                    report["boundaries"][field] = safe_value + 1
                else:
                    report["boundaries"][field] = safe_value + "-forged"
                report_path.write_text(json.dumps(report, indent=2) + "\n")
                expected = self.resign_after_file_change(forged, module.REPORT_FILE)
                with self.assertRaisesRegex(ValueError, "safety boundaries"):
                    module.verify_artifact(forged, expected)

    def test_closed_interval_requires_entry_and_exit_evidence(self):
        self.rows[0]["out_date"] = "20210110"
        changes = [
            {
                "source_sector_code": "CI005001.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20200110",
                "action": "add",
            },
            {
                "source_sector_code": "CI005001.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20210110",
                "action": "remove",
            },
        ]
        evidence = self.write_evidence([self.announcement(changes=changes)])
        report, output = self.run_prepare(evidence)
        self.assertEqual(report["status"], "content_reconciled")
        row = pq.read_table(output / module.DATA_FILE).to_pylist()[0]
        self.assertEqual(row["exit_known_at"], "2020-01-01T08:00:00+00:00")
        self.assertTrue(row["exit_claimed_evidence_matched"])

        evidence = self.write_evidence([self.announcement()], provider="CITIC")
        report, output = self.run_prepare(evidence, "missing-exit")
        self.assertEqual(report["status"], "blocked_data")
        self.assertEqual(report["reconciliation"]["exit_content_matched_rows"], 0)
        row = pq.read_table(output / module.DATA_FILE).to_pylist()[0]
        self.assertIsNone(row["exit_known_at"])
        self.assertFalse(row["historical_known_at_verified"])

    def test_no_evidence_and_withdrawal_remain_blocked(self):
        empty = self.write_evidence([])
        report, output = self.run_prepare(empty, "empty")
        self.assertEqual(report["status"], "blocked_data")
        self.assertEqual(report["reconciliation"]["content_reconciled_rows"], 0)
        self.assertIsNone(
            pq.read_table(output / module.DATA_FILE).to_pylist()[0]["known_at"]
        )

        first = self.announcement()
        withdrawn = self.announcement(
            revision=2,
            published_at="2020-01-02T16:00:00+08:00",
            status="withdrawn",
            supersedes_revision=1,
            changes=[],
        )
        evidence = self.write_evidence([first, withdrawn])
        report, _ = self.run_prepare(evidence, "withdrawn")
        self.assertEqual(report["status"], "blocked_data")
        self.assertEqual(report["evidence_manifest"]["withdrawn_announcements"], 1)
        self.assertEqual(report["evidence_manifest"]["active_events"], 0)

    def test_provider_timezone_revision_and_hash_are_hard_gates(self):
        cases = []
        cases.append(self.write_evidence([self.announcement()], provider="SW"))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            module.load_evidence_manifest(cases[-1])

        naive = self.announcement(published_at="2020-01-01T16:00:00")
        with self.assertRaisesRegex(ValueError, "published_at"):
            module.load_evidence_manifest(self.write_evidence([naive]))

        broken = self.announcement(revision=2, supersedes_revision=None)
        with self.assertRaisesRegex(ValueError, "revision chain"):
            module.load_evidence_manifest(self.write_evidence([broken]))

        bad_hash = self.announcement()
        bad_hash["source"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256"):
            module.load_evidence_manifest(self.write_evidence([bad_hash]))

    def test_conflicting_and_unmatched_events_cannot_promote_pit(self):
        duplicate = self.announcement()
        conflicting = self.announcement(
            announcement_id="notice-2", source_name="notice-2.pdf"
        )
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            module.load_evidence_manifest(self.write_evidence([duplicate, conflicting]))

        unmatched = self.announcement(
            changes=[
                {
                    "source_sector_code": "CI005999.CI",
                    "source_symbol": "699999.SH",
                    "effective_date": "20200110",
                    "action": "add",
                }
            ]
        )
        report, _ = self.run_prepare(self.write_evidence([unmatched]), "unmatched")
        self.assertEqual(report["status"], "blocked_data")
        self.assertEqual(len(report["reconciliation"]["unmatched_events"]), 1)

    def test_cross_sector_overlapping_fixed_source_intervals_remain_blocked(self):
        self.rows.append(
            {
                **self.rows[0],
                "_row_identity": "2" * 64,
                "l1_code": "CI005002",
                "source_l1_code": "CI005002.CI",
                "in_date": "20210110",
            }
        )
        evidence = self.write_evidence(
            [
                self.announcement(),
                self.announcement(
                    announcement_id="notice-2",
                    source_name="notice-2.pdf",
                    changes=[
                        {
                            "source_sector_code": "CI005002.CI",
                            "source_symbol": "600001.SH",
                            "effective_date": "20210110",
                            "action": "add",
                        }
                    ],
                ),
            ]
        )
        report, _ = self.run_prepare(evidence, "overlap")
        self.assertEqual(report["status"], "blocked_data")
        self.assertEqual(
            report["reconciliation"]["source_interval_conflicts"],
            [
                {
                    "source_symbol": "600001.SH",
                    "left_source_sector_code": "CI005001.CI",
                    "left_effective_from": "20200110",
                    "left_effective_to": None,
                    "right_source_sector_code": "CI005002.CI",
                    "right_effective_from": "20210110",
                    "right_effective_to": None,
                }
            ],
        )

    def test_cross_sector_closed_interval_overlap_remains_blocked(self):
        self.rows[0]["out_date"] = "20220110"
        self.rows.append(
            {
                **self.rows[0],
                "_row_identity": "2" * 64,
                "l1_code": "CI005002",
                "source_l1_code": "CI005002.CI",
                "in_date": "20210110",
                "out_date": None,
            }
        )
        changes = [
            {
                "source_sector_code": "CI005001.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20200110",
                "action": "add",
            },
            {
                "source_sector_code": "CI005001.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20220110",
                "action": "remove",
            },
            {
                "source_sector_code": "CI005002.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20210110",
                "action": "add",
            },
        ]
        report, _ = self.run_prepare(
            self.write_evidence([self.announcement(changes=changes)]),
            "closed-overlap",
        )
        self.assertEqual(report["status"], "blocked_data")
        conflict = report["reconciliation"]["source_interval_conflicts"][0]
        self.assertEqual(conflict["left_source_sector_code"], "CI005001.CI")
        self.assertEqual(conflict["right_source_sector_code"], "CI005002.CI")

    def test_cross_sector_same_day_remove_add_is_a_half_open_boundary(self):
        self.rows[0]["out_date"] = "20210110"
        self.rows.append(
            {
                **self.rows[0],
                "_row_identity": "2" * 64,
                "l1_code": "CI005002",
                "source_l1_code": "CI005002.CI",
                "in_date": "20210110",
                "out_date": None,
            }
        )
        changes = [
            {
                "source_sector_code": "CI005001.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20200110",
                "action": "add",
            },
            {
                "source_sector_code": "CI005001.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20210110",
                "action": "remove",
            },
            {
                "source_sector_code": "CI005002.CI",
                "source_symbol": "600001.SH",
                "effective_date": "20210110",
                "action": "add",
            },
        ]
        report, _ = self.run_prepare(
            self.write_evidence([self.announcement(changes=changes)]),
            "same-day-boundary",
        )
        self.assertEqual(report["status"], "content_reconciled")
        self.assertEqual(report["reconciliation"]["source_interval_conflicts"], [])
        self.assertEqual(
            report["boundaries"]["interval_semantics"],
            "half_open_[effective_from,effective_to)",
        )

    def test_failed_write_leaves_no_final_path_and_can_retry(self):
        evidence = self.write_evidence([self.announcement()])
        output = self.base / "atomic-output"
        with (
            patch.object(
                module, "_validate_artifacts", side_effect=RuntimeError("boom")
            ),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            self.run_prepare(evidence, "atomic-output")
        self.assertFalse(output.exists())
        self.assertEqual(list(self.base.glob(".atomic-output.tmp-*")), [])
        report, retried = self.run_prepare(evidence, "atomic-output")
        self.assertEqual(report["status"], "content_reconciled")
        self.assertTrue(retried.is_dir())

    def test_output_never_overwrites_source_evidence_or_existing_paths(self):
        evidence = self.write_evidence([])
        with self.assertRaisesRegex(ValueError, "outside"):
            self.run_prepare(evidence, "evidence/output")
        existing = self.base / "existing"
        existing.mkdir()
        table = pa.Table.from_pylist(self.rows).replace_schema_metadata(
            {
                b"tushare": json.dumps(
                    {"release_id": self.release, "upstream_calls": 0}
                ).encode()
            }
        )
        with (
            patch.object(
                module,
                "manifest_at",
                return_value={"retained_observations_included": True},
            ),
            patch.object(module, "read_dataset", return_value=table),
            self.assertRaisesRegex(ValueError, "outside"),
        ):
            module.prepare(self.root, self.release, evidence, existing)


if __name__ == "__main__":
    unittest.main()
