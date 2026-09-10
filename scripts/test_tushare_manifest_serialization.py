"""Exact JSON bytes, partial-file failures and CURRENT ordering; no source calls."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import random
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as m


class ManifestSerialization(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            self.stack.enter_context(
                patch(target, side_effect=AssertionError("offline only"))
            )

    def encode(self, value):
        timing = {}
        path, sha = m.serialize_manifest_file(self.root, value, timing)
        raw = path.read_bytes()
        self.assertEqual(raw, m.json_bytes(value))
        self.assertEqual(sha, hashlib.sha256(raw).hexdigest())
        self.assertEqual(timing["bytes"], len(raw))
        self.assertGreater(timing["chunks"], 0)
        return path, timing

    def test_complete_encoder_semantics_and_nonbmp_do_not_change_bytes(self):
        rng = random.Random(91)
        rows = [
            {
                "k": i,
                "float": rng.random(),
                "unicode": '中文🙂\\"\n\t',
                "null": None,
                "flag": i % 2 == 0,
            }
            for i in range(100)
        ]
        for value in (
            {},
            [],
            {
                "rows": rows,
                "negative_zero": -0.0,
                "large": 10**100,
                "nan": float("nan"),
                "inf": float("inf"),
                "tiny": 1e-200,
            },
            {1: "integer key", 2: "two"},
        ):
            self.encode(value)

    def test_multiple_c_chunks_and_default_python_fallback_have_exact_bytes(self):
        value = {"rows": list(range(100001)), "last": "🙂"}
        path, timing = self.encode(value)
        self.assertTrue(timing["eager_chunks"])
        self.assertGreater(timing["chunks"], 1)
        self.assertLess(timing["largest_chunk_bytes"], path.stat().st_size)
        with patch.object(json.encoder, "c_make_encoder", None):
            _, fallback = self.encode(value)
        self.assertFalse(fallback["eager_chunks"])

    def test_source_validation_errors_leave_no_private_partial_file(self):
        cycle = []
        cycle.append(cycle)
        for value, error in (
            (cycle, ValueError),
            ({"bad": object()}, TypeError),
            ({"bad": "\ud800"}, UnicodeEncodeError),
        ):
            with self.subTest(error=error), self.assertRaises(error):
                m.serialize_manifest_file(self.root, value)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_partial_encoding_and_fsync_failure_clean_only_owned_temporary(self):
        unrelated = self.root / ".manifest-unrelated.tmp"
        unrelated.write_bytes(b"keep")

        def partial(*args, **kwargs):
            yield '{"source": '
            raise MemoryError("fixture partial encoding")

        with (
            patch.object(json.JSONEncoder, "iterencode", side_effect=partial),
            self.assertRaises(MemoryError),
        ):
            m.serialize_manifest_file(self.root, {"source": "value"})
        with (
            patch.object(m.os, "fsync", side_effect=OSError("fixture sync")),
            self.assertRaises(OSError),
        ):
            m.serialize_manifest_file(self.root, {"source": "value"})
        self.assertEqual(list(self.root.iterdir()), [unrelated])
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_modes_match_existing_atomic_bytes_and_symlink_directory_rejected(self):
        path, _ = self.encode({"key": "value"})
        old = self.root / "old.json"
        m.atomic_bytes(old, b"old")
        self.assertEqual(
            stat.S_IMODE(path.stat().st_mode), stat.S_IMODE(old.stat().st_mode)
        )
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            m.serialize_manifest_file(link, {})


class PublishFileFailures(unittest.TestCase):
    def setUp(self):
        ManifestSerialization.setUp(self)
        self.p = m.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.p.close)
        self.first = self.p.publish()
        self.pointer = (self.root / "CURRENT.json").read_bytes()
        self.p.enqueue("daily", {"trade_date": "20260904"}, epoch="fixture")
        self.p.db.commit()

    def assert_old(self):
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.assertEqual(list((self.root / "releases").glob(".manifest-*.tmp")), [])

    def test_rename_and_pointer_failures_preserve_current_then_retry_same_release(self):
        original = Path.replace

        def fail_rename(path, target):
            if path.name.startswith(".manifest-"):
                raise OSError("fixture rename")
            return original(path, target)

        with patch.object(Path, "replace", fail_rename), self.assertRaises(OSError):
            self.p.publish()
        self.assert_old()
        self.assertEqual(self.p.publish_timing["failed_stage"], "write_manifest")
        atomic = m.atomic_json

        def fail_pointer(path, value):
            if path.name == "CURRENT.json":
                raise OSError("fixture pointer")
            return atomic(path, value)

        with (
            patch.object(m, "atomic_json", side_effect=fail_pointer),
            self.assertRaises(OSError),
        ):
            self.p.publish()
        self.assert_old()
        sealed = sorted(
            p.parent.name
            for p in (self.root / "releases").glob("data-*/manifest.json")
            if p.parent.name != self.first
        )
        self.assertEqual(len(sealed), 1)
        self.assertEqual(self.p.publish(), sealed[0])
        with patch.object(
            m,
            "serialize_manifest_file",
            side_effect=AssertionError("noop must not serialize"),
        ):
            self.assertEqual(self.p.publish(), sealed[0])

    def test_damaged_sealed_manifest_is_not_hidden_by_filename_or_retry(self):
        original = m.atomic_json

        def fail(path, value):
            if path.name == "CURRENT.json":
                raise OSError("fixture after seal")
            return original(path, value)

        with (
            patch.object(m, "atomic_json", side_effect=fail),
            self.assertRaises(OSError),
        ):
            self.p.publish()
        dest = next(
            p
            for p in (self.root / "releases").glob("data-*/manifest.json")
            if p.parent.name != self.first
        )
        raw = dest.read_bytes()
        dest.write_bytes(b"!" + raw[1:])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.p.publish()
        self.assert_old()
        self.assertEqual(dest.read_bytes(), b"!" + raw[1:])


if __name__ == "__main__":
    unittest.main()
