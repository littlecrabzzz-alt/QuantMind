import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import tushare_research_cache as cache


class ResearchCache(unittest.TestCase):
    def fixture(self, root):
        files, datasets = {}, []
        for api in ('daily', 'fund_daily'):
            raw = json.dumps({'request': {'api_name': api, 'params': {}}}).encode()
            sha = hashlib.sha256(raw).hexdigest()
            obs = 'observations/' + sha + '.json'
            cache.atomic_bytes(root / obs, raw)
            files[obs] = {'sha256': sha, 'bytes': len(raw)}
            table = pa.table({'ts_code': ['000001.SZ'], 'trade_date': ['20260915'],
                              '_observation': [sha + '.json'], '_fetched_at': ['2026-09-16T00:00:00Z']})
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

    def test_subset_integrity_budget_and_atomic_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            target = Path(folder) / 'cache'
            self.fixture(root)
            pointer = cache.prepare(root, ['daily'])
            manifest_path = root / '.research-exports' / pointer['release_id'] / 'manifest.json'
            manifest = json.loads(manifest_path.read_bytes())
            self.assertEqual({d['api_name'] for d in manifest['datasets']}, {'daily'})
            self.assertEqual(len(manifest['files']), 2)
            def request(url, **kwargs):
                name = url.split(':18765/', 1)[1]
                if name == 'CURRENT.json':
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
                report = cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)
                self.assertEqual(report['downloaded_files'], 2)
                self.assertEqual(cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)['downloaded_files'], 0)
                old = (target / 'CURRENT.json').read_bytes()
                (target / next(iter(manifest['files']))).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    cache.pull(target, 'http://127.0.0.1:18765', 1024**2, 0)
                self.assertEqual((target / 'CURRENT.json').read_bytes(), old)
            with self.assertRaisesRegex(ValueError, 'loopback'):
                cache.pull(target, 'http://example.com:80', 1024, 0)


if __name__ == '__main__':
    unittest.main()
