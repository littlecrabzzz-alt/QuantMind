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
            (root / 'pipeline-config.json').write_text(
                '{"enable_documents":true,"document_download_workers":2,'
                '"document_worker_max_documents":240,'
                '"document_worker_max_seconds":85}'
            )
            started, captured, finished = threading.Event(), threading.Event(), threading.Event()
            def documents(*args, **kwargs):
                self.assertEqual(
                    kwargs,
                    {
                        'max_documents': 240,
                        'max_seconds': 85.0,
                        'download_workers': 2,
                    },
                )
                started.set()
                self.assertTrue(captured.wait(2), 'acquisition must overlap documents')
                finished.set()
                return {'status': 'ok', 'processed': 100}
            def acquire(*, before_nonpublication_work):
                before_nonpublication_work()
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
            self.assertEqual(report['cycle_interval_seconds'], 120.0)
            self.assertGreaterEqual(report['updated_at'], report['started_at'])
            self.assertGreaterEqual(report['elapsed_seconds'], 0)

    def test_configurable_cycle_interval_is_bounded(self):
        self.assertEqual(worker.cycle_seconds({}), 120.0)
        self.assertEqual(
            worker.cycle_seconds({'archive_worker_cycle_seconds': 105}), 105.0
        )
        for value in (True, 104, 3601, '105'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.cycle_seconds({'archive_worker_cycle_seconds': value})

    def test_planning_only_resumes_acquisition_after_minimum_delay(self):
        self.assertEqual(worker.next_cycle_delay(105, 58, 'planning_only'), 5)
        self.assertEqual(worker.next_cycle_delay(105, 58, None), 47)

    def test_due_publication_runs_before_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ENABLED').touch()
            (root / 'pipeline-config.json').write_text('{"enable_documents":true}')
            order = []
            def publish(**kwargs):
                order.append('publish')
                return {'status': 'publish_only', 'requests': 0}
            def documents(*args, **kwargs):
                order.append('documents')
                self.assertEqual(
                    kwargs,
                    {
                        'max_documents': 100,
                        'max_seconds': 90.0,
                        'download_workers': 1,
                    },
                )
                return {'status': 'ok', 'processed': 100}
            with patch.dict(os.environ), patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', side_effect=publish), \
                    patch.object(tushare_documents, 'run_documents', side_effect=documents), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**40)), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 0)
            self.assertEqual(order, ['publish', 'documents'])

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
