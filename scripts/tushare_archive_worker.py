#!/usr/bin/env python3
"""Single bounded acquisition loop on the verified Mac/NAS archive owner."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cycle_seconds(config):
    value = config.get('archive_worker_cycle_seconds', 120)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 105 <= value <= 3600
    ):
        raise ValueError('Invalid archive worker cycle seconds')
    return float(value)


def next_cycle_delay(interval, elapsed, acquisition_status):
    if acquisition_status == 'planning_only':
        return 5
    return max(5, interval - elapsed)


def document_execution(config):
    value = config.get('document_worker_execution', 'thread')
    if value not in ('thread', 'process'):
        raise ValueError('Invalid document worker execution')
    return value


def document_limits(config):
    count = config.get('document_worker_max_documents', 100)
    seconds = config.get('document_worker_max_seconds', 90)
    workers = config.get('document_download_workers', 1)
    max_bytes = config.get('document_max_bytes', 25 * 1024 * 1024)
    retry_interval = config.get('document_terminal_retry_interval_seconds', 86400)
    retry_max = config.get('document_terminal_retry_max_documents', 16)
    overlap = config.get('document_overlap_parse_download', False)
    parse_workers = config.get('document_parse_workers', 1)
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= 1000
        or isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not 0 < seconds <= 100
        or isinstance(workers, bool)
        or not isinstance(workers, int)
        or not 1 <= workers <= 8
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 25 * 1024 * 1024 <= max_bytes <= 256 * 1024 * 1024
        or isinstance(retry_interval, bool)
        or not isinstance(retry_interval, (int, float))
        or not 3600 <= retry_interval <= 365 * 86400
        or isinstance(retry_max, bool)
        or not isinstance(retry_max, int)
        or not 0 <= retry_max <= 64
        or not isinstance(overlap, bool)
        or isinstance(parse_workers, bool)
        or not isinstance(parse_workers, int)
        or not 1 <= parse_workers <= 2
        or parse_workers > 1 and (not overlap or workers == 1)
    ):
        raise ValueError(
            'Invalid document worker bounds: 1..1000 stages, '
            '0..100 seconds, 1..8 downloads, 25..256 MiB, '
            '3600..31536000 retry seconds, 0..64 retries, 1..2 parsers; '
            'two parsers require overlap and downloads > 1'
        )
    return (
        count, float(seconds), workers, max_bytes, float(retry_interval), retry_max,
        overlap, parse_workers,
    )


def execute_documents(
    root,
    max_documents,
    max_seconds,
    download_workers,
    max_bytes,
    terminal_retry_interval_seconds,
    terminal_retry_max_documents,
    overlap_parse_download,
    parse_workers,
):
    from backend.shared.tushare_documents import run_documents
    return run_documents(
        root,
        max_documents=max_documents,
        max_seconds=max_seconds,
        download_workers=download_workers,
        max_bytes=max_bytes,
        terminal_retry_interval_seconds=terminal_retry_interval_seconds,
        terminal_retry_max_documents=terminal_retry_max_documents,
        overlap_parse_download=overlap_parse_download,
        parse_workers=parse_workers,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    os.environ['QM_TUSHARE_ARCHIVE_ROOT'] = str(root)
    os.environ['QM_NODE_ROLE'] = 'archive'
    from backend.shared.tushare_pipeline import authority, tick, atomic_json, utc_now
    from backend.shared.tushare_documents import run_documents
    authority()
    with (root / '.archive-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            start = time.monotonic()
            interval = 120.0
            free = shutil.disk_usage(root).free
            report = {'started_at': utc_now(), 'free_bytes': free,
                      'nas_migration_warning': free < 500 * 2**30}
            try:
                if free < 300 * 2**30:
                    report['status'] = 'blocked_disk_reserve'
                elif not (root / 'ENABLED').exists():
                    report['status'] = 'disabled'
                else:
                    authority()
                    config = json.loads((root / 'pipeline-config.json').read_bytes())
                    interval = cycle_seconds(config)
                    report['cycle_interval_seconds'] = interval
                    # The cloud already used independent acquisition/document workers.
                    # Keep one archive owner and wait for both bounded phases before
                    # another cycle or shutdown; SQLite connections stay task-local.
                    execution = document_execution(config)
                    report['document_execution'] = execution
                    pool_type = (
                        ProcessPoolExecutor if execution == 'process'
                        else ThreadPoolExecutor
                    )
                    pool_options = (
                        {'mp_context': multiprocessing.get_context('spawn')}
                        if execution == 'process' else {}
                    )
                    with pool_type(max_workers=1, **pool_options) as pool:
                        documents = None
                        def start_documents(config=config):
                            nonlocal documents
                            if (documents is None and config.get('enable_documents')
                                    and shutil.disk_usage(root).free >= 300 * 2**30):
                                limits = document_limits(config)
                                count, seconds, workers = limits[:3]
                                documents = pool.submit(
                                    execute_documents, root,
                                    max_documents=count,
                                    max_seconds=seconds,
                                    download_workers=workers,
                                    max_bytes=limits[3],
                                    terminal_retry_interval_seconds=limits[4],
                                    terminal_retry_max_documents=limits[5],
                                    overlap_parse_download=limits[6],
                                    parse_workers=limits[7],
                                )
                        report['acquisition'] = tick(
                            before_nonpublication_work=start_documents
                        )
                        if report['acquisition'].get('status') != 'publish_deferred_documents_active':
                            start_documents()
                        if documents is not None:
                            report['documents'] = documents.result()
                    acquisition_status = report['acquisition'].get('status', '')
                    report['status'] = (acquisition_status if acquisition_status.startswith('blocked')
                                        or acquisition_status in ('disabled', 'already_running')
                                        else 'completed_cycle')
            except Exception as exc:
                report.update(status='failed', error_type=type(exc).__name__)
            report.update(updated_at=utc_now(), elapsed_seconds=round(time.monotonic() - start, 3))
            atomic_json(root / 'archive-worker-status.json', report)
            print(json.dumps(report), flush=True)
            if args.once:
                return 0 if report['status'] == 'completed_cycle' else 2
            time.sleep(next_cycle_delay(
                interval,
                time.monotonic() - start,
                report.get('acquisition', {}).get('status'),
            ))


if __name__ == '__main__':
    raise SystemExit(main())
