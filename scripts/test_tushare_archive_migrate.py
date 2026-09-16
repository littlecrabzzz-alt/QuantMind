import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.tushare_archive_migrate import frozen_checkpoint, verify_checkpoint, install_checkpoint


class MigrationCheck(unittest.TestCase):
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
            self.assertEqual(result['files'], 3)
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

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'outside').symlink_to('/tmp', target_is_directory=True)
            with self.assertRaises(ValueError):
                frozen_checkpoint(root)


if __name__ == '__main__':
    unittest.main()
