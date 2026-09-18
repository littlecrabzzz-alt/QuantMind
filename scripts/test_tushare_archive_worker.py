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
                '{"enable_documents":true,"document_download_workers":4,'
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
                        'download_workers': 4,
                        'max_bytes': 25 * 1024 * 1024,
                        'terminal_retry_interval_seconds': 86400.0,
                        'terminal_retry_max_documents': 16,
                        'overlap_parse_download': False,
                        'parse_workers': 1,
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

    def test_document_execution_is_bounded(self):
        self.assertEqual(worker.document_execution({}), 'thread')
        self.assertEqual(
            worker.document_execution({'document_worker_execution': 'process'}),
            'process',
        )
        for value in (None, True, 'fork', 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.document_execution({'document_worker_execution': value})

    def test_document_limits_match_native_production_bounds(self):
        self.assertEqual(
            worker.document_limits({}),
            (100, 90.0, 1, 25 * 1024 * 1024, 86400.0, 16, False, 1),
        )
        self.assertEqual(
            worker.document_limits({
                'document_worker_max_documents': 600,
                'document_worker_max_seconds': 100,
                'document_download_workers': 8,
                'document_max_bytes': 256 * 1024 * 1024,
                'document_terminal_retry_interval_seconds': 3600,
                'document_terminal_retry_max_documents': 64,
                'document_overlap_parse_download': True,
                'document_parse_workers': 2,
            }),
            (600, 100.0, 8, 256 * 1024 * 1024, 3600.0, 64, True, 2),
        )
        for key, value in (
            ('document_worker_max_documents', 0),
            ('document_worker_max_documents', 2501),
            ('document_worker_max_documents', True),
            ('document_worker_max_seconds', 0),
            ('document_worker_max_seconds', 101),
            ('document_worker_max_seconds', True),
            ('document_download_workers', 0),
            ('document_download_workers', 9),
            ('document_download_workers', True),
            ('document_max_bytes', 25 * 1024 * 1024 - 1),
            ('document_max_bytes', 256 * 1024 * 1024 + 1),
            ('document_max_bytes', True),
            ('document_terminal_retry_interval_seconds', 3599),
            ('document_terminal_retry_interval_seconds', 365 * 86400 + 1),
            ('document_terminal_retry_interval_seconds', True),
            ('document_terminal_retry_max_documents', -1),
            ('document_terminal_retry_max_documents', 65),
            ('document_terminal_retry_max_documents', True),
            ('document_overlap_parse_download', 1),
            ('document_overlap_parse_download', 'true'),
            ('document_parse_workers', 0),
            ('document_parse_workers', 5),
            ('document_parse_workers', True),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                worker.document_limits({key: value})
        with self.assertRaises(ValueError):
            worker.document_limits({'document_parse_workers': 2})
        with self.assertRaises(ValueError):
            worker.document_limits({
                'document_parse_workers': 2,
                'document_overlap_parse_download': True,
                'document_download_workers': 1,
            })
        self.assertEqual(worker.document_limits({
            'document_worker_max_documents': 2500,
        })[0], 2500)
        self.assertEqual(worker.document_limits({
            'document_download_workers': 6,
            'document_overlap_parse_download': True,
            'document_parse_workers': 4,
        })[-1], 4)

    def test_document_process_executes_with_task_local_database(self):
        with tempfile.TemporaryDirectory() as directory:
            with worker.ProcessPoolExecutor(
                max_workers=1,
                mp_context=worker.multiprocessing.get_context('spawn'),
            ) as pool:
                report = pool.submit(
                    worker.execute_documents,
                    Path(directory),
                    0,
                    1.0,
                    1,
                    25 * 1024 * 1024,
                    86400.0,
                    16,
                    False,
                    1,
                ).result(timeout=10)
            self.assertEqual(report['status'], 'ok')
            self.assertEqual(report['processed'], 0)
            self.assertTrue((Path(directory) / 'documents.sqlite').exists())

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
                        'max_bytes': 25 * 1024 * 1024,
                        'terminal_retry_interval_seconds': 86400.0,
                        'terminal_retry_max_documents': 16,
                        'overlap_parse_download': False,
                        'parse_workers': 1,
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
