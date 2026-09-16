import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import tushare_archive_worker as worker
from backend.shared import tushare_pipeline


class WorkerStatus(unittest.TestCase):
    def test_blocked_acquisition_is_not_reported_as_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ENABLED').touch()
            (root / 'pipeline-config.json').write_text('{}')
            with patch.dict(os.environ), patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', return_value={'status': 'blocked_missing_token'}), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**40)), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 2)
            report = json.loads((root / 'archive-worker-status.json').read_bytes())
            self.assertEqual(report['status'], 'blocked_missing_token')


if __name__ == '__main__':
    unittest.main()
