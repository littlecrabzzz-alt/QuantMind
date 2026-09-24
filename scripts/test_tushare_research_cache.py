import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import tushare_research_cache as cache


class ResearchCache(unittest.TestCase):
    def test_deployment_read_store_is_allowlisted(self):
        from backend.shared.tushare_store import deployed_read_root
        for value, expected in [('archive', '/data/tushare'), ('research-cache', '/data/tushare-research')]:
            with patch.dict(os.environ, {'QM_TUSHARE_READ_STORE': value}):
                self.assertEqual(deployed_read_root(), Path(expected))
        with patch.dict(os.environ, {'QM_TUSHARE_READ_STORE': '/tmp/arbitrary'}):
            with self.assertRaises(ValueError):
                deployed_read_root()

    def fixture(self, root, repeated_provenance=False):
        files, datasets = {}, []
        for api in ('daily', 'fund_daily'):
            observations = []
            for revision in range(2 if repeated_provenance else 1):
                raw = json.dumps({'request': {'api_name': api, 'params': {}}, 'revision': revision}).encode()
                sha = hashlib.sha256(raw).hexdigest()
                obs = 'observations/' + sha + '.json'
                cache.atomic_bytes(root / obs, raw)
                files[obs] = {'sha256': sha, 'bytes': len(raw)}
                observations.append(sha + '.json')
            observations *= 100 if repeated_provenance else 1
            count = len(observations)
            table = pa.table({'ts_code': ['000001.SZ'] * count, 'trade_date': ['20260915'] * count,
                              '_observation': observations, '_fetched_at': ['2026-09-16T00:00:00Z'] * count})
            tmp = root / 'data.parquet'
            pq.write_table(table, tmp)
            raw = tmp.read_bytes()
            tmp.unlink()
            sha = hashlib.sha256(raw).hexdigest()
            name = 'parquet/' + sha + '.parquet'
            cache.atomic_bytes(root / name, raw)
            files[name] = {'sha256': sha, 'bytes': len(raw)}
            datasets.append({'api_name': api, 'path': name, **files[name]})
        raw = json.dumps({'files': files, 'datasets': datasets, 'rrg_status': 'blocked'}).encode()
        sha = hashlib.sha256(raw).hexdigest()
        cache.atomic_bytes(root / 'releases' / ('data-' + sha) / 'manifest.json', raw)
        cache.atomic_json(root / 'CURRENT.json', {'release_id': 'data-' + sha, 'manifest_sha256': sha})

    def test_repeated_provenance_retains_all_sources_and_rejects_corruption(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root, repeated_provenance=True)
                references = {
                    'observations/' + p.name
                    for p in (root / 'observations').iterdir()
                    if json.loads(p.read_bytes())['request']['api_name'] == 'daily'
                }
                self.assertEqual(len(references), 2)
                if corrupt:
                    (root / sorted(references)[-1]).write_bytes(b'corrupt')
                    with self.assertRaisesRegex(ValueError, 'checksum'):
                        cache.prepare(root, ['daily'])
                else:
                    pointer = cache.prepare(root, ['daily'])
                    manifest = json.loads((root / '.research-exports' / pointer['release_id'] / 'manifest.json').read_bytes())
                    self.assertEqual({name for name in manifest['files'] if name.startswith('observations/')}, references)
                    self.assertEqual(len(manifest['files']), 3)

    def test_subset_integrity_budget_and_atomic_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            target = Path(folder) / 'cache'
            self.fixture(root)
            pointer = cache.prepare(root, ['daily'])
            pointer = {**pointer, 'latest_source_release_id': pointer['source_release_id'],
                       'source_lagged': False}
            manifest_path = root / '.research-exports' / pointer['release_id'] / 'manifest.json'
            manifest = json.loads(manifest_path.read_bytes())
            self.assertEqual({d['api_name'] for d in manifest['datasets']}, {'daily'})
            self.assertEqual(len(manifest['files']), 2)
            current_timeouts = []
            def request(url, **kwargs):
                name = url.split(':18765/', 1)[1]
                if name == 'CURRENT.json':
                    current_timeouts.append(kwargs['timeout'])
                    raw = json.dumps(pointer).encode()
                elif name.startswith('releases/'):
                    raw = manifest_path.read_bytes()
                else:
                    raw = (root / name).read_bytes()
                return io.BytesIO(raw)
            with patch.object(cache, 'urlopen', side_effect=request):
                with self.assertRaisesRegex(ValueError, 'budget'):
                    cache.pull(target, 'http://127.0.0.1:18765', 0, 0)
                self.assertFalse((target / 'CURRENT.json').exists())
                with patch.object(cache, 'fetch', side_effect=ValueError('transfer failed')):
                    with self.assertRaisesRegex(ValueError, 'transfer failed'):
                        cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)
                self.assertFalse((target / 'CURRENT.json').exists())
                self.assertEqual(json.loads((target / 'cache-transfer-status.json').read_bytes())['status'], 'failed')
                (target / 'releases' / pointer['release_id'] / 'manifest.json').unlink()
                with patch.object(cache, 'fetch', wraps=cache.fetch) as transfer:
                    report = cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)
                manifest_calls = [call for call in transfer.call_args_list
                                  if '/releases/' in call.args[0]]
                self.assertEqual(manifest_calls[0].kwargs['limit'], cache.MAX_MANIFEST_BYTES)
                self.assertGreater(cache.MAX_MANIFEST_BYTES, 82 * 1024**2)
                self.assertEqual(report['downloaded_files'], 2)
                self.assertEqual(cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)['downloaded_files'], 0)
                old = (target / 'CURRENT.json').read_bytes()
                (target / next(iter(manifest['files']))).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)
                self.assertEqual((target / 'CURRENT.json').read_bytes(), old)
            self.assertGreaterEqual(len(current_timeouts), 5)
            self.assertEqual(set(current_timeouts), {cache.PREPARE_TIMEOUT_SECONDS})
            self.assertEqual(cache.PREPARE_TIMEOUT_SECONDS, 30 * 60)
            with self.assertRaisesRegex(ValueError, 'loopback'):
                cache.pull(target, 'http://example.com:80', 1024, 0)

    def test_stale_verified_release_returns_while_new_release_prepares(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            old = cache.prepare(root, ['daily'])
            latest = 'data-' + 'a' * 64
            cache.atomic_json(root / 'CURRENT.json',
                              {'release_id': latest, 'manifest_sha256': latest[5:]})
            entered, release = threading.Event(), threading.Event()
            def slow_prepare(*_):
                entered.set()
                release.wait(5)
                raise ValueError('new release unavailable')
            publication = cache.SourcePublication(root, ['daily'])
            with patch.object(cache, 'prepare', side_effect=slow_prepare), \
                    patch.object(cache.logging, 'exception'):
                start = time.monotonic()
                pointer, manifest, _ = publication.current()
                self.assertLess(time.monotonic() - start, 1)
                self.assertTrue(entered.wait(1))
                self.assertEqual(pointer['release_id'], old['release_id'])
                self.assertEqual(pointer['latest_source_release_id'], latest)
                self.assertTrue(pointer['source_lagged'])
                self.assertEqual(manifest['source_release_id'], old['source_release_id'])
                self.assertEqual(publication.current()[0]['release_id'], old['release_id'])
                release.set()
                for _ in range(100):
                    if not publication.refreshing:
                        break
                    time.sleep(0.01)
                self.assertFalse(publication.refreshing)

    def test_cached_manifest_corruption_does_not_get_served(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            pointer = cache.prepare(root, ['daily'])
            path = root / '.research-exports' / pointer['release_id'] / 'manifest.json'
            path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                cache.SourcePublication(root, ['daily']).current()

    def test_incremental_export_reuses_retained_partitions_and_checks_new_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            old = cache.prepare(root, ['daily', 'fund_daily'])
            old_manifest = json.loads((root / '.research-exports' / old['release_id']
                                       / 'manifest.json').read_bytes())
            full = json.loads((root / 'releases' / old['source_release_id']
                               / 'manifest.json').read_bytes())
            raw = b'{"request":{"api_name":"daily","params":{}}}'
            obs_sha = hashlib.sha256(raw).hexdigest()
            obs = 'observations/' + obs_sha + '.json'
            cache.atomic_bytes(root / obs, raw)
            table = pa.table({'ts_code': ['000002.SZ'], 'trade_date': ['20260916'],
                              '_observation': [obs_sha + '.json'],
                              '_fetched_at': ['2026-09-17T00:00:00Z']})
            parquet = root / 'new.parquet'
            pq.write_table(table, parquet)
            payload = parquet.read_bytes()
            parquet.unlink()
            parquet_sha = hashlib.sha256(payload).hexdigest()
            name = 'parquet/' + parquet_sha + '.parquet'
            cache.atomic_bytes(root / name, payload)
            full['files'].update({obs: {'sha256': obs_sha, 'bytes': len(raw)},
                                  name: {'sha256': parquet_sha, 'bytes': len(payload)}})
            full['datasets'].append({'api_name': 'daily', 'path': name})
            release_raw = json.dumps(full).encode()
            release_sha = hashlib.sha256(release_raw).hexdigest()
            new_source = 'data-' + release_sha
            cache.atomic_bytes(root / 'releases' / new_source / 'manifest.json', release_raw)
            cache.atomic_json(root / 'CURRENT.json',
                              {'release_id': new_source, 'manifest_sha256': release_sha})
            with patch.object(cache, 'checked', wraps=cache.checked) as integrity:
                pointer = cache.prepare(root, ['daily', 'fund_daily'])
            checked_names = {call.args[1] for call in integrity.call_args_list}
            self.assertIn(name, checked_names)
            self.assertIn(obs, checked_names)
            self.assertFalse(checked_names & set(old_manifest['files']))
            result = json.loads((root / '.research-exports' / pointer['release_id']
                                 / 'manifest.json').read_bytes())
            self.assertEqual(set(result['files']), set(old_manifest['files']) | {name, obs})
            self.assertEqual(pointer['source_release_id'], new_source)

    def test_removed_partition_falls_back_to_exact_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            old = cache.prepare(root, ['daily', 'fund_daily'])
            full = json.loads((root / 'releases' / old['source_release_id']
                               / 'manifest.json').read_bytes())
            full['datasets'] = [d for d in full['datasets'] if d['api_name'] == 'daily']
            release_raw = json.dumps(full).encode()
            release_sha = hashlib.sha256(release_raw).hexdigest()
            new_source = 'data-' + release_sha
            cache.atomic_bytes(root / 'releases' / new_source / 'manifest.json', release_raw)
            cache.atomic_json(root / 'CURRENT.json',
                              {'release_id': new_source, 'manifest_sha256': release_sha})
            with patch.object(cache, 'checked', wraps=cache.checked) as integrity:
                pointer = cache.prepare(root, ['daily', 'fund_daily'])
            daily_path = full['datasets'][0]['path']
            self.assertIn(daily_path,
                          {call.args[1] for call in integrity.call_args_list})
            result = json.loads((root / '.research-exports' / pointer['release_id']
                                 / 'manifest.json').read_bytes())
            self.assertEqual([d['api_name'] for d in result['datasets']], ['daily'])
            self.assertEqual(len(result['files']), 2)


if __name__ == '__main__':
    unittest.main()
