"""Publisher-only predecessor reuse: immutable equivalence and failures, offline."""
from contextlib import ExitStack
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import weakref
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_archive as archive
from backend.shared import tushare_pipeline as m
from scripts.test_tushare_archive import manifest, hashed
from scripts import test_tushare_publish_equivalence as equivalence


class CurrentPublisherEquivalence(unittest.TestCase):
    setUp = equivalence.PublishEquivalence.setUp
    compare_publish = equivalence.PublishEquivalence.compare_publish
    test_three_generations_noop_and_entire_history_are_byte_equal = equivalence.PublishEquivalence.test_three_generations_noop_and_entire_history_are_byte_equal

    @classmethod
    def setUpClass(cls):
        with patch('scripts.test_tushare_publish_equivalence.BASELINE', '84590f6'):
            cls.legacy = staticmethod(equivalence.old_publish())


class RetainReuse(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name in ('socket.socket.connect', 'socket.getaddrinfo'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('offline')))
        name, metadata = hashed(self.root, 'objects', b'original')
        self.document = {'files': {name: metadata}, 'datasets': []}
        self.release, self.raw = manifest(self.root, self.document)
        self.previous = m.manifest_at(self.root, self.release)

    def fast(self, **kwargs):
        return archive.retain_release(self.root, self.release,
                                      _verified_predecessor=self.previous, **kwargs)

    def test_delta_full_validation_and_no_second_decode(self):
        expected = archive.retain_release(self.root, self.release)
        original = json.dumps(self.previous, sort_keys=True)
        timing = {}
        with patch.object(archive, '_manifest_document', side_effect=AssertionError('second decode')), patch.object(Path, 'read_bytes', side_effect=AssertionError('second whole body allocation')):
            result = self.fast(timing=timing)
        self.assertEqual({**self.previous['files'], **result['files']}, expected['files'])
        self.assertTrue(all(p.startswith('archives/') for p in result['files']))
        self.assertEqual(result['verification'], expected['verification'])
        self.assertEqual(json.dumps(self.previous, sort_keys=True), original)
        self.assertTrue(timing['reused_predecessor'])
        self.assertNotIn('manifest_read_parse', timing['stage_seconds'])
        self.assertTrue({'reuse_stat', 'expected_files', 'lock_wait', 'archive_record', 'known_archives'} <= set(timing['completed_stages']))
        self.assertTrue(all(v >= 0 for v in timing['stage_seconds'].values()))
        self.assertEqual(result, self.fast())

    def test_bad_metadata_rejected_without_creating_archive(self):
        cases = [('../escape.json', {'sha256': 'a' * 64, 'bytes': 1}),
                 ('objects/' + 'a' * 64 + '.json', {'sha256': 'b' * 64, 'bytes': 1}),
                 ('objects/' + 'a' * 64 + '.json', {'sha256': 'a' * 64, 'bytes': True})]
        for name, meta in cases:
            with self.subTest(name=name, meta=meta):
                timing = {}
                with self.assertRaises(archive.ArchiveError):
                    archive.retain_release(self.root, self.release,
                                           _verified_predecessor={'files': {name: meta}}, timing=timing)
                self.assertEqual(timing['failed_stage'], 'expected_files')
                self.assertFalse((self.root / 'archives').exists())

    def test_source_changed_after_previous_read_fails_closed(self):
        source = self.root / 'releases' / self.release / 'manifest.json'
        source.write_bytes(self.raw.replace(b'datasets', b'changed!'))
        timing = {}
        with self.assertRaises(archive.ArchiveError):
            self.fast(timing=timing)
        self.assertEqual(timing['failed_stage'], 'archive_record')
        self.assertEqual(archive.archive_inventory(self.root)['recovery']['archived_releases'], [])

    def test_publish_source_replaced_after_read_keeps_current_pointer(self):
        p = m.Pipeline(self.root / 'publisher-race', {'entries': []})
        self.addCleanup(p.close)
        first = p.publish()
        pointer = (p.root / 'CURRENT.json').read_bytes()
        source = p.root / 'releases' / first / 'manifest.json'
        raw = source.read_bytes()
        original = m.manifest_at
        def replaced(*args):
            previous = original(*args)
            source.write_bytes(b'[' + raw[1:])
            return previous
        p.enqueue('trade_cal', {'start_date': '20200101'}, 1, 'fixture')
        try:
            with patch.object(m, 'manifest_at', side_effect=replaced):
                with self.assertRaises(archive.ArchiveError):
                    p.publish()
            self.assertEqual((p.root / 'CURRENT.json').read_bytes(), pointer)
            self.assertEqual(p.publish_timing['failed_stage'], 'retain_previous')
            self.assertEqual(p.publish_timing['retention']['failed_stage'], 'archive_record')
        finally:
            source.write_bytes(raw)

    def test_archive_conflict_and_symlink_fail_closed(self):
        dest = self.root / 'archives' / (self.release[5:] + '.json')
        dest.parent.mkdir()
        dest.write_bytes(self.raw.replace(b'datasets', b'changed!'))
        with self.assertRaises(archive.ArchiveError):
            self.fast()
        dest.unlink()
        dest.symlink_to(self.root / 'releases' / self.release / 'manifest.json')
        with self.assertRaises(archive.ArchiveError):
            self.fast()

    def test_legacy_probe_ignores_private_data_fast_path_and_keeps_twenty_files(self):
        entries = []
        for i in range(20):
            name, metadata = hashed(self.root, 'objects', str(i).encode())
            entries.append({'path': name, **metadata})
        release, _ = manifest(self.root, {'files': entries}, probe=True)
        timing = {}
        result = archive.retain_release(self.root, release,
                                        _verified_predecessor={'files': {}}, timing=timing)
        self.assertFalse(timing['reused_predecessor'])
        self.assertEqual(len([p for p in result['files'] if p.startswith('objects/')]), 20)
        self.assertIn('manifest_read_parse', timing['completed_stages'])

    def test_interruption_after_alias_is_retryable(self):
        with patch.object(archive, '_register', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.fast()
        self.assertEqual((self.root / 'archives' / (self.release[5:] + '.json')).read_bytes(), self.raw)
        first = self.fast()
        self.assertEqual(first, self.fast())
        self.assertEqual(len(first['archived_releases']), 1)

    def test_lock_wait_is_separate_and_lock_is_not_bypassed(self):
        timing, outcome, errors = {}, [], []
        with (self.root / '.archive.lock').open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            def retain():
                try:
                    outcome.append(self.fast(timing=timing))
                except BaseException as error:
                    errors.append(error)
            thread = threading.Thread(target=retain)
            thread.start()
            time.sleep(.06)
            self.assertFalse(outcome)
            fcntl.flock(held, fcntl.LOCK_UN)
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(len(outcome), 1)
        self.assertGreater(timing['stage_seconds']['lock_wait'], .02)

    def test_publish_releases_retained_container_before_serialization(self):
        p = m.Pipeline(self.root / 'publisher', {'entries': []})
        self.addCleanup(p.close)
        first = p.publish()
        p.enqueue('trade_cal', {'start_date': '20200101'}, 1, 'fixture')
        refs = []
        original = archive.retain_release
        encode = m.json_bytes
        class Retained(dict):
            pass
        def retain(*args, **kwargs):
            value = Retained(original(*args, **kwargs))
            refs.append(weakref.ref(value))
            return value
        def serialize(value):
            if isinstance(value, dict) and 'retained_observations_included' in value:
                self.assertTrue(refs)
                self.assertIsNone(refs[-1]())
            return encode(value)
        with patch.object(archive, 'retain_release', side_effect=retain), patch.object(m, 'json_bytes', side_effect=serialize):
            current = p.publish()
        self.assertNotEqual(first, current)
        self.assertIn('retention', p.publish_timing)
        self.assertNotIn(b'reuse_stat', (p.root / 'releases' / current / 'manifest.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
