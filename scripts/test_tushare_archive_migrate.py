import fcntl
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import tushare_archive_migrate as migration
from scripts.tushare_archive_migrate import frozen_checkpoint, verify_checkpoint, install_checkpoint, finalize_archive, seal_source, sync_frozen


class MigrationCheck(unittest.TestCase):
    def test_relocated_cleanup_requires_preserved_copy_and_keeps_other_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'cloud', Path(directory) / 'mac'
            (source / 'objects').mkdir(parents=True)
            (source / 'objects/a.json').write_text('immutable raw')
            (source / 'CURRENT.json').write_text('{}')
            (source / 'pipeline.sqlite').touch()
            (source / 'ENABLED.migration-paused').touch()
            checkpoint = frozen_checkpoint(source)
            seal = seal_source(source, checkpoint, socket.gethostname())
            shutil.copytree(source, target)
            local_checkpoint = target / checkpoint.relative_to(source.resolve())
            (target / 'ARCHIVE_AUTHORITY.json').write_text(json.dumps({
                **seal, 'migration_verified': True, 'activation_pending': False,
            }))
            (target / 'objects/a.json').write_text('damaged')
            with self.assertRaisesRegex(ValueError, 'preserved payload mismatch'):
                migration.verify_preserved(target, local_checkpoint)
            self.assertFalse((local_checkpoint / 'PRESERVED.json').exists())
            (target / 'objects/a.json').write_text('immutable raw')
            report = migration.verify_preserved(target, local_checkpoint)
            self.assertEqual(report['files'], 1)
            receipt = local_checkpoint / 'PRESERVED.json'
            good_receipt = receipt.read_bytes()
            receipt.write_text(json.dumps({**report, 'files': 999}))
            with patch.object(migration.socket, 'gethostname', return_value='cloud-node'):
                with self.assertRaisesRegex(ValueError, 'totals mismatch'):
                    migration.prune_relocated(source, checkpoint, receipt, apply=True)
            self.assertTrue((source / 'objects/a.json').exists())
            receipt.write_bytes(good_receipt)
            # A file created after the checkpoint is outside deletion authority.
            (source / 'objects/new.json').write_text('preserve unknown')
            with patch.object(migration.socket, 'gethostname', return_value='cloud-node'):
                dry = migration.prune_relocated(source, checkpoint, receipt)
                self.assertEqual(dry['status'], 'dry_run_verified')
                self.assertTrue((source / 'objects/a.json').exists())
                (source / 'ENABLED').touch()
                with self.assertRaisesRegex(ValueError, 'enabled'):
                    migration.prune_relocated(source, checkpoint, receipt, apply=True)
                (source / 'ENABLED').unlink()
                (source / 'objects/a.json').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'Source payload changed'):
                    migration.prune_relocated(source, checkpoint, receipt, apply=True)
                self.assertTrue((source / 'objects/a.json').exists())
                (source / 'objects/a.json').write_text('immutable raw')
                with (source / 'pipeline.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(BlockingIOError):
                        migration.prune_relocated(source, checkpoint, receipt, apply=True)
                done = migration.prune_relocated(source, checkpoint, receipt, apply=True)
                self.assertEqual(done['files'], 1)
                resumed = migration.prune_relocated(source, checkpoint, receipt, apply=True)
                self.assertEqual(resumed['already_absent'], 1)
            self.assertFalse((source / 'objects/a.json').exists())
            for name in ['objects/new.json', 'pipeline.sqlite', 'CURRENT.json', 'ARCHIVE_RELOCATED.json']:
                self.assertTrue((source / name).exists())
            self.assertEqual((target / 'objects/a.json').read_text(), 'immutable raw')

    @patch("scripts.tushare_archive_migrate.shutil.disk_usage", return_value=SimpleNamespace(free=2**40))
    def test_checkpoint_is_complete_and_detects_corruption(self, _disk):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            target = Path(directory) / 'target'
            source.mkdir()
            (source / 'unpublished').mkdir()
            (source / 'unpublished/raw.json').write_text('preserve unpublished history')
            (source / 'CURRENT.json').write_text('{}')
            with sqlite3.connect(source / 'pipeline.sqlite') as db:
                db.execute('CREATE TABLE jobs(id INTEGER)')
                db.execute('INSERT INTO jobs VALUES(7)')
            (source / 'state.sqlite3').touch()
            (source / 'ENABLED').touch()
            with self.assertRaises(ValueError):
                frozen_checkpoint(source)
            (source / 'ENABLED').unlink()
            with (source / 'pipeline.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    frozen_checkpoint(source)
            checkpoint = frozen_checkpoint(source)
            installed = Path(directory) / 'installed'
            installed.mkdir()
            install_checkpoint(installed, checkpoint)
            install_checkpoint(installed, checkpoint)  # Safe resume is idempotent.
            self.assertFalse((installed / 'CURRENT.json').exists())
            with sqlite3.connect(installed / 'pipeline.sqlite') as copied:
                self.assertEqual(copied.execute('SELECT id FROM jobs').fetchall(), [(7,)])
            (installed / 'pipeline.sqlite-wal').touch()
            with self.assertRaisesRegex(ValueError, 'live SQLite'):
                install_checkpoint(installed, checkpoint)
            (installed / 'pipeline.sqlite-wal').unlink()
            (installed / 'pipeline.sqlite').write_bytes(b'existing independent data')
            with self.assertRaisesRegex(ValueError, 'Existing database differs'):
                install_checkpoint(installed, checkpoint)
            self.assertEqual((installed / 'pipeline.sqlite').read_bytes(), b'existing independent data')
            shutil.copytree(source, target)
            for line in (checkpoint / 'inventory.jsonl').read_text().splitlines():
                row = json.loads(line)
                if 'checkpoint_path' in row:
                    shutil.copyfile(source / row['checkpoint_path'], target / row['path'])
            result = verify_checkpoint(target, checkpoint)
            self.assertEqual(result['files'], 4)
            self.assertFalse(result['migration_verified'])
            self.assertFalse((target / 'ARCHIVE_AUTHORITY.json').exists())
            (target / 'CURRENT.json').write_text('old pinned pointer')
            verify_checkpoint(target, checkpoint, staged_current=True)
            self.assertEqual((target / 'CURRENT.json').read_text(), 'old pinned pointer')
            shutil.copyfile(checkpoint / 'CURRENT.json', target / 'CURRENT.json')
            (target / 'unpublished/raw.json').write_text('corrupt')
            with self.assertRaises(ValueError):
                verify_checkpoint(target, checkpoint)
            (checkpoint / 'inventory.jsonl').write_text('tampered')
            with self.assertRaises(ValueError):
                verify_checkpoint(target, checkpoint)

    def test_handoff_requires_matching_cloud_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            (source / 'CURRENT.json').write_text('{}')
            (source / 'ENABLED.migration-paused').touch()
            checkpoint = frozen_checkpoint(source)
            shutil.copytree(source, target)
            copied = target / checkpoint.relative_to(source.resolve())
            marker = seal_source(source, checkpoint, socket.gethostname())
            self.assertEqual(seal_source(source, checkpoint, socket.gethostname()), marker)
            with patch('scripts.tushare_archive_migrate.subprocess.run', return_value=SimpleNamespace(stdout='{}')):
                with self.assertRaisesRegex(ValueError, 'handoff evidence'):
                    finalize_archive(target, copied)
            self.assertFalse((target / 'ENABLED').exists())
            self.assertFalse((target / 'ARCHIVE_AUTHORITY.json').exists())
            original = migration.atomic_json
            def interrupted(path, value):
                if path.name == 'ARCHIVE_AUTHORITY.json' and value.get('migration_verified') is True:
                    raise OSError('simulated process interruption')
                return original(path, value)
            with patch('scripts.tushare_archive_migrate.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(marker))), \
                    patch.object(migration, 'atomic_json', side_effect=interrupted):
                with self.assertRaisesRegex(OSError, 'interruption'):
                    finalize_archive(target, copied)
            state = json.loads((target / 'ARCHIVE_AUTHORITY.json').read_bytes())
            self.assertFalse(state['migration_verified'])
            self.assertTrue(state['activation_pending'])
            with patch('scripts.tushare_archive_migrate.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(marker))):
                report = finalize_archive(target, copied)
            self.assertTrue(report['migration_verified'])
            self.assertTrue((target / 'ENABLED').exists())
            with self.assertRaisesRegex(ValueError, 'already active'):
                finalize_archive(target, copied)
            (source / 'CURRENT.json').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'published after'):
                seal_source(source, checkpoint, socket.gethostname())

    def test_frozen_transfer_rejects_unfinished_source_and_keeps_current(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            target.mkdir()
            (source / 'CURRENT.json').write_text('{}')
            (source / 'pipeline-config.json').write_text('{"batch_requests": 360}')
            (target / 'CURRENT.json').write_text('old release')
            checkpoint = frozen_checkpoint(source)
            proof = json.loads((checkpoint / 'COMPLETE.json').read_bytes())
            with patch('scripts.tushare_archive_migrate.subprocess.run', return_value=SimpleNamespace(stdout='{}')), \
                    patch('scripts.tushare_archive_migrate.precopy') as precopy:
                with self.assertRaisesRegex(ValueError, 'not frozen'):
                    sync_frozen(target, checkpoint.name)
                precopy.assert_not_called()
            def run(command, **kwargs):
                if command[0] == 'ssh':
                    return SimpleNamespace(stdout=json.dumps(proof))
                destination = Path(command[-1])
                if command[-1].endswith('/'):
                    shutil.copytree(checkpoint, destination, dirs_exist_ok=True)
                else:
                    shutil.copyfile(source / 'pipeline-config.json', destination)
                return SimpleNamespace(returncode=0)
            with patch('scripts.tushare_archive_migrate.subprocess.run', side_effect=run), \
                    patch('scripts.tushare_archive_migrate.precopy', return_value=0):
                report = sync_frozen(target, checkpoint.name)
            self.assertTrue(report['cloud_writer_disabled'])
            self.assertEqual((target / 'CURRENT.json').read_text(), 'old release')
            self.assertEqual((target / 'pipeline-config.json').read_bytes(), (source / 'pipeline-config.json').read_bytes())
            self.assertFalse((target / 'ARCHIVE_AUTHORITY.json').exists())

    @unittest.skipUnless(shutil.which('rsync'), 'rsync not installed')
    @patch('scripts.tushare_archive_migrate.shutil.disk_usage', return_value=SimpleNamespace(free=2**40))
    def test_precopy_preserves_hardlinked_manifest_aliases(self, _disk):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            (source / 'archives').mkdir(parents=True)
            (source / 'releases/data-a').mkdir(parents=True)
            canonical = source / 'archives/a.json'
            canonical.write_text('{"immutable":true}')
            (source / 'releases/data-a/manifest.json').hardlink_to(canonical)
            shutil.copytree(source, target)  # Simulate an earlier copy that lost hardlinks.
            self.assertNotEqual((target / 'archives/a.json').stat().st_ino,
                                (target / 'releases/data-a/manifest.json').stat().st_ino)
            original_run = subprocess.run
            def local_transfer(command):
                # Run the production flags on a local fixture; never SSH.
                flags = command[:-2]
                at = flags.index('-e')
                flags = flags[:at] + flags[at+2:]
                flags = [arg for arg in flags if not arg.startswith('--rsync-path=')]
                result = original_run(flags + [str(source) + '/', str(target) + '/'], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                return result
            with patch.object(migration.subprocess, 'run', side_effect=local_transfer):
                self.assertEqual(migration.precopy(target), 0)
            self.assertEqual((target / 'archives/a.json').stat().st_ino,
                             (target / 'releases/data-a/manifest.json').stat().st_ino)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'outside').symlink_to('/tmp', target_is_directory=True)
            with self.assertRaises(ValueError):
                frozen_checkpoint(root)


if __name__ == '__main__':
    unittest.main()
