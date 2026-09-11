"""QuantDB refresh regressions; only disposable fixtures, no Docker/network."""
import json
import contextlib
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quantdb_refresh as refresh
import dual_node_snapshot as snapshot


class QuantDBRefresh(unittest.TestCase):
    def test_publish_only_quantdb_and_preserve_previous_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote = Path(tmp); project = remote / 'project'
            data = project / 'data/quantdb/1_kline_data/daily_forward/dt=20260911/data.parquet'
            data.parent.mkdir(parents=True); data.write_text('first')
            research = project / 'data/research/result'; research.parent.mkdir(); research.write_text('private result')
            (remote / 'AUTHORITY').touch()
            with patch.object(snapshot, 'PROJECT', project), patch.object(snapshot, 'REMOTE', str(remote)), \
                 patch.object(snapshot, 'SETTINGS', {'QM_DISK_UUID': 'fixture'}), \
                 patch.object(snapshot, 'output', return_value='fixture'), \
                 patch.object(refresh, 'cloud_sync_lock', return_value=contextlib.nullcontext()), \
                 patch.object(refresh.os, 'geteuid', return_value=0), \
                 patch.object(shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(500 * 1024**3, 0, 500 * 1024**3)):
                refresh.publish()
                first = (remote / 'quantdb-snapshots/latest').resolve()
                self.assertTrue((first / 'COMPLETE').is_file())
                self.assertFalse((first / 'project/data/research').exists())
                data.write_text('second')
                refresh.publish()
                second = (remote / 'quantdb-snapshots/latest').resolve()
                self.assertNotEqual(first, second)
                self.assertEqual((first / 'project' / data.relative_to(project)).read_text(), 'first')
                self.assertEqual((second / 'project' / data.relative_to(project)).read_text(), 'second')
                refresh.publish()
                self.assertEqual((remote / 'quantdb-snapshots/latest').resolve(), second)

    def test_apply_preserves_local_results_and_marks_derived_failure_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); local = root / '.local-dev/project'
            data = local / 'data/quantdb/day.parquet'; data.parent.mkdir(parents=True); data.write_text('old')
            original = {'path': 'data/quantdb/day.parquet', 'sha256': snapshot.digest(data), 'bytes': 3}
            (root / 'logs/cloud-snapshots/snapshot-old').mkdir(parents=True)
            (root / 'logs/cloud-snapshots/snapshot-old/runtime-manifest.jsonl').write_text(json.dumps(original))
            (root / '.local-dev/SNAPSHOT_ID').write_text('snapshot-old'); (root / '.local-dev/READY').touch()
            result = local / 'data/research/valuable-result'; result.parent.mkdir(); result.write_text('keep')
            downloaded = root / 'download'; newfile = downloaded / 'project/data/quantdb/day.parquet'
            newfile.parent.mkdir(parents=True); newfile.write_text('new')
            incoming = {**original, 'sha256': snapshot.digest(newfile)}
            (downloaded / 'runtime-manifest.jsonl').write_text(json.dumps(incoming))
            (downloaded / 'COMPLETE').touch(); (downloaded / 'VERIFIED').touch()
            import subprocess
            events = []
            def run(*args, **kwargs):
                if args[0] == 'docker': events.append(args[1]); return
                return subprocess.run(args, check=True, **kwargs)
            with patch.object(refresh, 'require_local_idle', return_value=['quantmind-dev']), \
                 patch.object(snapshot, 'run', side_effect=run), \
                 patch.object(snapshot, 'output', side_effect=RuntimeError('derived failed')):
                with self.assertRaisesRegex(RuntimeError, 'derived failed'):
                    refresh.apply(root, downloaded)
            receipt = json.loads((root / '.local-dev/QUANTDB_SYNC.json').read_text())
            self.assertEqual(receipt['status'], 'files_applied')
            self.assertEqual((Path(receipt['backup']) / 'day.parquet').read_text(), 'old')
            self.assertEqual(data.read_text(), 'new')
            self.assertEqual(result.read_text(), 'keep')
            self.assertEqual(events[-1], 'start')
            self.assertFalse((root / 'logs/local-dev.lock').exists())

    def test_local_edits_block_but_identical_retries_and_unique_results_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data/quantdb/day.parquet'
            data.parent.mkdir(parents=True)
            data.write_text('old')
            old = [{'path': 'data/quantdb/day.parquet', 'sha256': snapshot.digest(data)}]
            data.write_text('new')
            new = [{'path': old[0]['path'], 'sha256': snapshot.digest(data)}]
            refresh.check_local_changes(root, old, new)
            data.write_text('local experiment')
            with self.assertRaisesRegex(RuntimeError, 'Local QuantDB edit retained'):
                refresh.check_local_changes(root, old, new)
            self.assertEqual(data.read_text(), 'local experiment')
            data.write_text('old')
            unique = root / 'data/quantdb/experiment.parquet'
            unique.write_text('keep')
            refresh.check_local_changes(root, old, new)
            self.assertEqual(unique.read_text(), 'keep')
            data.unlink()
            with self.assertRaisesRegex(RuntimeError, 'Local QuantDB edit retained'):
                refresh.check_local_changes(root, old, new)

    def test_incoming_manifest_cannot_write_outside_quantdb(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest'
            for name in ['/data/quantdb/x.parquet', 'data/quantdb/../x.parquet', 'data/research/x.parquet']:
                path.write_text(json.dumps({'path': name}))
                with self.assertRaisesRegex(RuntimeError, 'Unexpected'):
                    refresh.manifest_rows(path)

    def test_quantdb_snapshot_rejects_wrong_remote_collection(self):
        with patch.object(snapshot, 'output', return_value=snapshot.REMOTE + '/snapshots/snapshot-old'):
            with self.assertRaisesRegex(RuntimeError, 'Invalid snapshot path'):
                snapshot.pull_snapshot(remote_base='quantdb-snapshots')

    def test_busy_apply_releases_local_mutex_without_stopping_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / '.local-dev').mkdir(); (root / 'logs').mkdir()
            (root / '.local-dev/READY').touch()
            download = root / 'download'; download.mkdir()
            (download / 'COMPLETE').touch(); (download / 'VERIFIED').touch()
            (download / 'runtime-manifest.jsonl').write_text('')
            with patch.object(refresh, 'require_local_idle', side_effect=RuntimeError('busy')), patch.object(snapshot, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'busy'):
                    refresh.apply(root, download)
                run.assert_not_called()
            self.assertFalse((root / 'logs/local-dev.lock').exists())


if __name__ == '__main__':
    unittest.main()
