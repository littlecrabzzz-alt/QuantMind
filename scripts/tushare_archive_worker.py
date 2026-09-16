#!/usr/bin/env python3
"""Single bounded acquisition loop on the verified Mac/NAS archive owner."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
            free = shutil.disk_usage(root).free
            report = {'updated_at': utc_now(), 'free_bytes': free,
                      'nas_migration_warning': free < 500 * 2**30}
            try:
                if free < 300 * 2**30:
                    report['status'] = 'blocked_disk_reserve'
                elif not (root / 'ENABLED').exists():
                    report['status'] = 'disabled'
                else:
                    report['acquisition'] = tick()
                    config = json.loads((root / 'pipeline-config.json').read_bytes())
                    if config.get('enable_documents') and shutil.disk_usage(root).free >= 300 * 2**30:
                        report['documents'] = run_documents(root, max_documents=100, max_seconds=90,
                                                           download_workers=min(2, max(1, int(config.get('document_download_workers', 1)))))
                    acquisition_status = report['acquisition'].get('status', '')
                    report['status'] = (acquisition_status if acquisition_status.startswith('blocked')
                                        or acquisition_status in ('disabled', 'already_running')
                                        else 'completed_cycle')
            except Exception as exc:
                report.update(status='failed', error_type=type(exc).__name__)
            atomic_json(root / 'archive-worker-status.json', report)
            print(json.dumps(report), flush=True)
            if args.once:
                return 0 if report['status'] == 'completed_cycle' else 2
            time.sleep(max(5, 120 - (time.monotonic() - start)))


if __name__ == '__main__':
    raise SystemExit(main())
