#!/usr/bin/env python3
"""Isolated discovery cache equivalence; no upstream/credentials/production DB."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_discovery_cache as cache_module
from backend.shared import tushare_pipeline as m


class DiscoveryDiskCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.p = m.Pipeline(self.root, {"entries": []})
        self.addCleanup(lambda: self.p.close())
        self.serial = 0
        for name in ('socket.socket.connect', 'socket.getaddrinfo'):
            mock = patch(name, side_effect=AssertionError('offline'))
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(m, 'get_secret', side_effect=AssertionError('no credentials'))
        mock.start()
        self.addCleanup(mock.stop)

    def save(self, code, *, api='stock_basic', fields=None, items=None, job_only=False):
        self.serial += 1
        raw = m.json_bytes({'serial': self.serial, 'data': {
            'fields': fields or ['ts_code', 'unused'],
            'items': items if items is not None else [[code, 1]] * 40}})
        sha = m.digest(raw)
        (self.root / 'objects').mkdir(exist_ok=True)
        path = self.root / 'objects' / (sha + '.json')
        path.write_bytes(raw)
        result = {'api_name': api, 'status': 'sample_ok', 'object_sha256': sha}
        key = self.p.enqueue(api, {'fixture': self.serial}, 1, 'fixture')
        self.p.db.execute('UPDATE jobs SET result=? WHERE id=?', (json.dumps(result), key))
        if not job_only:
            self.p.db.execute('INSERT INTO attempts VALUES(?,?,?)', (key, 1, json.dumps(result)))
        self.p.db.commit()
        return key, result, path

    def compare(self):
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '0'}):
            original = self.p.identifiers()
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '1'}):
            actual = self.p.identifiers()
        self.assertEqual(original, actual)
        return actual, self.p.identifier_timing

    def test_default_off_and_cross_pipeline_warm(self):
        self.save('000001.SZ')
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '0'}):
            self.p.identifiers()
        self.assertFalse((self.root / 'discovery-cache.sqlite').exists())
        self.compare()
        self.p.close()
        self.p = m.Pipeline(self.root, {'entries': []})
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '1'}), patch.object(self.p, 'records', side_effect=AssertionError('warm must not read raw')):
            result = self.p.identifiers()
        self.assertIn('000001.SZ', result['stocks'])
        self.assertEqual(self.p.identifier_timing['body_reads'], 0)
        self.assertEqual(self.p.identifier_timing['disk_cache']['hits'], 1)

    def test_full_membership_add_delete_revision_restore(self):
        key, _, _ = self.save('000001.SZ')
        self.compare()
        snapshot = sqlite3.connect(':memory:')
        self.addCleanup(snapshot.close)
        self.p.db.backup(snapshot)
        _, result, _ = self.save('T600111.SH', job_only=True)
        self.assertIn('T600111.SH', self.compare()[0]['stocks'])
        encoded = json.dumps(result)
        self.p.db.execute('UPDATE attempts SET result=? WHERE job_id=?', (encoded, key))
        self.p.db.execute('UPDATE jobs SET result=? WHERE id=?', (encoded, key))
        self.p.db.commit()
        self.assertNotIn('000001.SZ', self.compare()[0]['stocks'])
        self.p.db.execute('DELETE FROM attempts')
        self.p.db.execute('DELETE FROM jobs')
        self.p.db.commit()
        self.assertEqual(self.compare()[0]['stocks'], [])
        snapshot.backup(self.p.db)
        self.assertEqual(self.compare()[0]['stocks'], ['000001.SZ'])

    def test_stat_replacement_and_projection_version(self):
        _, _, path = self.save('000001.SZ')
        self.compare()
        obj = json.loads(path.read_bytes())
        obj['data']['items'][0][0] = '000002.SZ'
        replacement = path.with_suffix('.tmp')
        replacement.write_bytes(m.json_bytes(obj))
        replacement.replace(path)
        self.assertIn('000002.SZ', self.compare()[0]['stocks'])
        with patch.object(cache_module, 'VERSION', 'test-v2'):
            self.assertEqual(self.compare()[1]['disk_cache']['hits'], 0)
        path.unlink()
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '1'}):
            with self.assertRaises(FileNotFoundError):
                self.p.identifiers()

    def test_corruption_and_cache_loss_fallback(self):
        self.save('000001.SZ')
        self.compare()
        path = self.root / 'discovery-cache.sqlite'
        db = sqlite3.connect(path)
        db.execute("UPDATE projections SET payload=x'00'")
        db.commit()
        db.close()
        self.assertGreater(self.compare()[1]['disk_cache']['errors'], 0)
        path.unlink()
        self.assertEqual(self.compare()[1]['disk_cache']['admitted'], 1)
        path.write_bytes(b'invalid sqlite')
        self.assertGreater(self.compare()[1]['disk_cache']['errors'], 0)

    def test_request_sensitive_bypasses_cache(self):
        self.save('000001.SZ')
        self.compare()
        with patch.object(m, 'contract_for', return_value={'request_identity_fields': ['market']}):
            _, stats = self.compare()
        self.assertEqual(stats['disk_cache']['hits'], 0)
        self.assertEqual(stats['body_reads'], 1)
        self.assertEqual(stats['bypassed'], 1)

    def test_pair_projection_and_duplicate_last_column_preserved(self):
        self.save(None, api='factor_list', fields=['factor_name', 'asset_type', 'ignored'],
                  items=[['f', 'stock', 1], ['f', 'fund', 2], ['f', 'stock', 3]])
        self.save(None, fields=['ts_code', 'ts_code'], items=[['bad', '000001.SZ']])
        self.compare()
        result, stats = self.compare()
        self.assertEqual(result['factor_library_factors'], [{'asset_type': 'fund', 'factor_name': 'f'}, {'asset_type': 'stock', 'factor_name': 'f'}])
        self.assertEqual(result['stocks'], ['000001.SZ'])
        self.assertEqual(stats['disk_cache']['hits'], 2)

    def test_raw_schema_failure_is_not_swallowed(self):
        self.save(None, fields=['ts_code', 'unused'], items=[['000001.SZ']])
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '1'}):
            with self.assertRaises(ValueError):
                self.p.identifiers()

    def test_error_retains_completed_cache_timing(self):
        self.save('000001.SZ')
        self.compare()
        _, _, path = self.save(None, fields=['ts_code', 'unused'], items=[['bad']])
        with patch.dict(os.environ, {'TUSHARE_DISCOVERY_CACHE': '1'}):
            with self.assertRaises(ValueError):
                self.p.identifiers()
        self.assertIn('disk_cache', self.p.identifier_timing)
        self.assertGreater(self.p.identifier_timing['disk_cache']['bytes'], 0)
        self.assertGreater(self.p.identifier_timing['body_reads'], 0)

    def test_fixed_capacity_and_admission_budget_keep_all_sources(self):
        for i in range(25):
            self.save(f'{i:06d}.SZ')
        original_cls = cache_module.DiscoveryCache
        def small(root, **kwargs):
            return original_cls(root, **kwargs, max_bytes=16384, admission_seconds=10)
        with patch.object(cache_module, 'DiscoveryCache', side_effect=small):
            result, stats = self.compare()
        self.assertEqual(len(result['stocks']), 25)
        self.assertLessEqual(stats['disk_cache']['bytes'], 16384)
        self.assertLess(stats['disk_cache']['admitted'], 25)
        (self.root / 'discovery-cache.sqlite').unlink()
        def no_admission(root, **kwargs):
            return original_cls(root, **kwargs, admission_seconds=0)
        with patch.object(cache_module, 'DiscoveryCache', side_effect=no_admission):
            self.assertEqual(self.compare()[1]['disk_cache']['admitted'], 0)

    def test_locked_cache_falls_back_without_waiting(self):
        self.save('000001.SZ')
        self.compare()
        db = sqlite3.connect(self.root / 'discovery-cache.sqlite')
        self.addCleanup(db.close)
        db.execute('BEGIN EXCLUSIVE')
        self.assertEqual(self.compare()[0]['stocks'], ['000001.SZ'])
        db.rollback()

    def test_bounded_decompression_rejects_large_payload(self):
        import zlib
        self.save('000001.SZ')
        self.compare()
        db = sqlite3.connect(self.root / 'discovery-cache.sqlite')
        db.execute('UPDATE projections SET payload=?', (zlib.compress(b' ' * (cache_module.MAX_PAYLOAD + 1)),))
        db.commit()
        db.close()
        self.assertGreater(self.compare()[1]['disk_cache']['errors'], 0)

    def test_source_changes_during_admission_never_cached(self):
        _, result, path = self.save('000001.SZ')
        stat = path.stat()
        key = (result['api_name'], result['object_sha256'], 'sample_ok', None,
               stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        def changed_loader():
            path.write_bytes(path.read_bytes() + b' ')
            return [{'ts_code': '000001.SZ'}]
        with cache_module.DiscoveryCache(self.root, enabled=True) as cache:
            self.assertEqual(cache.read(path, key, {'ts_code'}, changed_loader), [{'ts_code': '000001.SZ'}])
            self.assertEqual(cache.stats['admitted'], 0)

    def test_foreign_db_and_symlink_untouched(self):
        self.save('000001.SZ')
        target = self.root / 'other.sqlite'
        db = sqlite3.connect(target)
        db.execute('CREATE TABLE authoritative(value)')
        db.commit()
        db.close()
        before = target.read_bytes()
        (self.root / 'discovery-cache.sqlite').symlink_to(target)
        self.compare()
        self.assertEqual(target.read_bytes(), before)
        (self.root / 'discovery-cache.sqlite').unlink()
        target.rename(self.root / 'discovery-cache.sqlite')
        self.compare()
        self.assertEqual((self.root / 'discovery-cache.sqlite').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
