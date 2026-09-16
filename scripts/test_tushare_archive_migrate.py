import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from scripts.tushare_archive_migrate import frozen_checkpoint, verify_checkpoint


class MigrationCheck(unittest.TestCase):
    def test_checkpoint_is_complete_and_detects_corruption(self):
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
