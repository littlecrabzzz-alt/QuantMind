#!/usr/bin/env python3
"""Single bounded acquisition loop on the verified Mac/NAS archive owner."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
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
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        documents = None
                        def start_documents(config=config):
                            nonlocal documents
                            if (documents is None and config.get('enable_documents')
                                    and shutil.disk_usage(root).free >= 300 * 2**30):
                                documents = pool.submit(
                                    run_documents, root,
                                    max_documents=int(config.get(
                                        'document_worker_max_documents', 100)),
                                    max_seconds=float(config.get(
                                        'document_worker_max_seconds', 90)),
                                    download_workers=min(
                                        2,
                                        max(1, int(config.get(
                                            'document_download_workers', 1))),
                                    ),
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
            time.sleep(max(5, interval - (time.monotonic() - start)))


if __name__ == '__main__':
    raise SystemExit(main())
