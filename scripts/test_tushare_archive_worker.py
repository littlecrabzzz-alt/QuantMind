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
    def test_cycle_log_is_compact_and_keeps_operational_counts(self):
        report = {
            'started_at': '2026-09-18T17:40:02+00:00',
            'updated_at': '2026-09-18T17:41:56+00:00',
            'status': 'completed_cycle',
            'elapsed_seconds': 114.393,
            'free_bytes': 2**40,
            'acquisition': {
                'requests': 633,
                'done': 413195,
                'empty': 352331,
                'pending': 2835888,
                'blocked': 871,
                'split_pending': 10297,
                'permission_blocked': 5847,
                'blocked_obligations': {
                    'total': 871,
                    'by_kind': {
                        'replacement_plan_retained_parent': {
                            'jobs': 800,
                            'apis': {'dc_member': 800},
                        },
                        'unclassified': {
                            'jobs': 71,
                            'apis': {'synthetic': 71},
                        },
                    },
                    'unclassified': 71,
                    'all_blocked_jobs_classified': False,
                    'changes_job_state': False,
                },
                'planning_cadence': {
                    'status': 'deferred',
                    'reason': 'interval_not_due',
                    'large_internal_state': 'x' * 100000,
                },
                'archive': {'archived_releases': ['x' * 100000]},
                'timing': {'failed_stage': None, 'large_internal_state': 'x' * 100000},
            },
            'documents': {
                'status': 'ok',
                'processed': 2221,
                'elapsed_seconds': 102.677,
                'counts': [
                    {'download_status': 'pending', 'parse_status': 'not_attempted', 'documents': 4820134},
                    {'download_status': 'downloaded', 'parse_status': 'parsed', 'documents': 311799},
                ],
                'terminal_recovery': {'scheduled': ['x' * 100000]},
            },
        }
        summary = worker.cycle_log(report)
        self.assertEqual(summary['acquisition']['requests'], 633)
        self.assertEqual(summary['acquisition']['planning_status'], 'deferred')
        self.assertEqual(
            summary['acquisition']['blocked_obligations']['unclassified'], 71
        )
        self.assertEqual(summary['documents']['pending_download'], 4820134)
        self.assertEqual(summary['documents']['parsed'], 311799)
        self.assertNotIn('archive', summary['acquisition'])
        self.assertNotIn('counts', summary['documents'])
        self.assertLess(len(json.dumps(summary)), 2048)

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
                return {'requests': 1, 'archive': {'archived_releases': ['large']}}
            with patch.dict(os.environ), patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', side_effect=acquire), \
                    patch.object(tushare_documents, 'run_documents', side_effect=documents), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**40)), \
                    patch('builtins.print') as printed:
                self.assertEqual(worker.main(), 0)
            self.assertTrue(finished.is_set())
            report = json.loads((root / 'archive-worker-status.json').read_text())
            self.assertEqual(report['documents']['processed'], 100)
            self.assertEqual(report['acquisition']['requests'], 1)
            self.assertEqual(report['cycle_interval_seconds'], 120.0)
            self.assertGreaterEqual(report['updated_at'], report['started_at'])
            self.assertGreaterEqual(report['elapsed_seconds'], 0)
            logged = json.loads(printed.call_args.args[0])
            self.assertEqual(logged['acquisition']['requests'], 1)
            self.assertEqual(logged['documents']['processed'], 100)
            self.assertNotIn('archive', logged['acquisition'])

    def test_configurable_cycle_interval_is_bounded(self):
        self.assertEqual(worker.cycle_seconds({}), 120.0)
        self.assertEqual(
            worker.cycle_seconds({'archive_worker_cycle_seconds': 105}), 105.0
        )
        for value in (True, 104, 3601, '105'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.cycle_seconds({'archive_worker_cycle_seconds': value})

    def test_planning_followup_uses_only_safe_cycle_remainder(self):
        self.assertFalse(worker.acquire_after_planning({}))
        self.assertTrue(worker.acquire_after_planning({
            'archive_worker_acquire_after_planning': True,
        }))
        with self.assertRaises(ValueError):
            worker.acquire_after_planning({
                'archive_worker_acquire_after_planning': 1,
            })
        self.assertIsNone(worker.planning_followup_seconds(False, 105, 40))
        self.assertEqual(worker.planning_followup_seconds(True, 105, 40), 60)
        self.assertEqual(worker.planning_followup_seconds(True, 300, 40), 100)
        self.assertIsNone(worker.planning_followup_seconds(True, 105, 100))

    def test_planning_followup_acquires_without_starting_second_document_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ENABLED').touch()
            (root / 'pipeline-config.json').write_text(
                '{"archive_worker_acquire_after_planning":true,'
                '"enable_documents":true}'
            )
            planning = {
                'status': 'planning_only',
                'requests': 0,
                'planning_cadence': {'status': 'planned'},
                'planning': {'history:global': {'new_jobs': 500}},
                'financial_vip_compaction': {
                    'status': 'compacted',
                    'superseded_leaf_jobs': 123,
                },
                'timing': {'total_elapsed_seconds': 40.0},
            }
            acquired = {'requests': 321, 'done': 1000, 'pending': 2000}
            document_calls = []

            def tick(*args, **kwargs):
                kwargs['before_nonpublication_work']()
                if not args and 'max_seconds' not in kwargs:
                    return planning
                self.assertEqual(kwargs['max_seconds'], 42)
                return dict(acquired)

            def documents(*args, **kwargs):
                document_calls.append((args, kwargs))
                return {'status': 'ok', 'processed': 17}

            with patch.dict(os.environ), \
                    patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', side_effect=tick) as called, \
                    patch.object(tushare_documents, 'run_documents', side_effect=documents), \
                    patch.object(worker, 'planning_followup_seconds', return_value=42), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**40)), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 0)
            self.assertEqual(called.call_count, 2)
            self.assertEqual(len(document_calls), 1)
            report = json.loads((root / 'archive-worker-status.json').read_bytes())
            self.assertEqual(report['status'], 'completed_cycle')
            self.assertEqual(report['acquisition']['requests'], 321)
            self.assertEqual(report['documents']['processed'], 17)
            self.assertEqual(
                report['acquisition']['planning_preflight']['status'],
                'planning_only',
            )
            self.assertEqual(
                report['acquisition']['planning_preflight']['timing'][
                    'total_elapsed_seconds'
                ],
                40.0,
            )
            self.assertEqual(
                report['acquisition']['planning_preflight'][
                    'financial_vip_compaction'
                ]['superseded_leaf_jobs'],
                123,
            )
            self.assertTrue(
                worker.cycle_log(report)['acquisition']['planning_followup']
            )

    def test_document_execution_is_bounded(self):
        self.assertEqual(worker.document_execution({}), 'thread')
        self.assertEqual(
            worker.document_execution({'document_worker_execution': 'process'}),
            'process',
        )
        for value in (None, True, 'fork', 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.document_execution({'document_worker_execution': value})

    def test_worker_passes_reduced_batch_to_documents_when_disk_is_low(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ENABLED').touch()
            (root / 'pipeline-config.json').write_text(json.dumps({
                'enable_documents': True, 'document_worker_max_documents': 2500,
                'document_max_bytes': 256 * 2**20,
            }))
            free = 300 * 2**30 + 2 * (256 * 2**20 + tushare_documents.MAX_PARSE_OUTPUT_BYTES)
            with patch.dict(os.environ), patch('sys.argv', ['worker', '--root', str(root), '--once']), \
                    patch.object(tushare_pipeline, 'authority'), \
                    patch.object(tushare_pipeline, 'tick', return_value={'requests': 1}), \
                    patch.object(tushare_documents, 'run_documents', return_value={'status': 'ok'}) as run, \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 0)
            self.assertEqual(run.call_args.kwargs['max_documents'], 2)
            report = json.loads((root / 'archive-worker-status.json').read_text())
            self.assertEqual(report['document_disk_budget']['admitted_stages'], 2)

    def test_document_disk_budget_preserves_reserve_for_maximum_payloads(self):
        reserve = 300 * 2**30
        payload = tushare_documents.MAX_DOCUMENT_MAX_BYTES
        stage_bytes = payload + tushare_documents.MAX_PARSE_OUTPUT_BYTES
        for free in (reserve - 1, reserve, reserve + stage_bytes - 1,
                     reserve + stage_bytes, reserve + 100 * 2**30, 2**41):
            with self.subTest(free=free):
                count = worker.document_disk_budget(2500, payload, free)
                self.assertGreaterEqual(count, 0)
                self.assertLessEqual(count, 2500)
                self.assertLessEqual(count * stage_bytes, max(0, free - reserve))
        self.assertEqual(worker.document_disk_budget(2500, payload, reserve), 0)
        self.assertEqual(worker.document_disk_budget(2500, payload, 2**41), 2500)

    def test_document_limits_match_native_production_bounds(self):
        self.assertEqual(worker.document_limits({'document_max_bytes': 320 * 2**20})[3], 320 * 2**20)
        self.assertEqual(
            worker.document_limits({}),
            (100, 90.0, 1, 25 * 1024 * 1024, 86400.0, 16, False, 1),
        )
        self.assertEqual(
            worker.document_limits({
                'document_worker_max_documents': 600,
                'document_worker_max_seconds': 100,
                'document_download_workers': 16,
                'document_max_bytes': 256 * 1024 * 1024,
                'document_terminal_retry_interval_seconds': 3600,
                'document_terminal_retry_max_documents': 64,
                'document_overlap_parse_download': True,
                'document_parse_workers': 2,
            }),
            (600, 100.0, 16, 256 * 1024 * 1024, 3600.0, 64, True, 2),
        )
        for key, value in (
            ('document_worker_max_documents', 0),
            ('document_worker_max_documents', 2501),
            ('document_worker_max_documents', True),
            ('document_worker_max_seconds', 0),
            ('document_worker_max_seconds', 101),
            ('document_worker_max_seconds', True),
            ('document_download_workers', 0),
            ('document_download_workers', 17),
            ('document_download_workers', True),
            ('document_max_bytes', 25 * 1024 * 1024 - 1),
            ('document_max_bytes', tushare_documents.MAX_DOCUMENT_MAX_BYTES + 1),
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
        self.assertEqual(
            worker.next_cycle_delay(105, 58, 'planning_only', 'completed_cycle'),
            5,
        )
        self.assertEqual(
            worker.next_cycle_delay(105, 58, None, 'completed_cycle'), 47
        )
        self.assertEqual(
            worker.next_cycle_delay(105, 104.5, None, 'completed_cycle'), 1
        )
        self.assertEqual(worker.next_cycle_delay(105, 104.5, None, 'failed'), 5)
        self.assertEqual(worker.next_cycle_delay(105, 104.5, None), 5)

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
