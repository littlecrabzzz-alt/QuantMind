import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import tushare_archive_worker as worker
from backend.shared import tushare_pipeline
from backend.shared import tushare_documents


class WorkerStatus(unittest.TestCase):
    def test_documents_overlap_acquisition_and_finish_before_cycle_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ENABLED').touch()
            (root / 'pipeline-config.json').write_text('{"enable_documents":true,"document_download_workers":2}')
            started, captured, finished = threading.Event(), threading.Event(), threading.Event()
            def documents(*args, **kwargs):
                self.assertEqual(kwargs, {'max_documents': 100, 'max_seconds': 90, 'download_workers': 2})
                started.set()
                self.assertTrue(captured.wait(2), 'acquisition must overlap documents')
                finished.set()
                return {'status': 'ok', 'processed': 100}
            def acquire():
                self.assertTrue(started.wait(2), 'documents must start before acquisition ends')
                captured.set()
                return {'requests': 1}
            with patch.dict(os.environ), patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', side_effect=acquire), \
                    patch.object(tushare_documents, 'run_documents', side_effect=documents), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**40)), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 0)
            self.assertTrue(finished.is_set())
            report = json.loads((root / 'archive-worker-status.json').read_text())
            self.assertEqual(report['documents']['processed'], 100)
            self.assertEqual(report['acquisition']['requests'], 1)
            self.assertGreaterEqual(report['updated_at'], report['started_at'])
            self.assertGreaterEqual(report['elapsed_seconds'], 0)

    def test_document_failure_is_not_hidden_by_successful_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ENABLED').touch()
            (root / 'pipeline-config.json').write_text('{"enable_documents":true}')
            with patch.dict(os.environ), patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', return_value={'requests': 1}), \
                    patch.object(tushare_documents, 'run_documents', side_effect=OSError), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**40)), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 2)
            report = json.loads((root / 'archive-worker-status.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['error_type'], 'OSError')
            self.assertEqual(report['acquisition']['requests'], 1)

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
