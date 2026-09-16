#!/usr/bin/env python3
"""Resumable immutable-file precopy; does not copy live SQLite or enable writers."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import atomic_json, utc_now


def precopy(root):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'ARCHIVE_AUTHORITY.json').exists():
        raise ValueError('Archive already owns acquisition; refuse cloud overwrite')
    if shutil.disk_usage(root).free < 300 * 2**30:
        raise ValueError('Keep 300 GiB free before migration')
    topology = dict(line.split('=', 1) for line in
                    (Path(__file__).resolve().parents[1] / 'deploy/dual-node.env').read_text().splitlines()
                    if line and not line.startswith('#'))
    exclusions = ['*.sqlite*', '*.lock', 'ENABLED*', 'CURRENT.json',
                  '*-status.json', 'pipeline-config.json', '*.tmp', '*.part',
                  '.migration/', '.research-exports/', '.manifest-transfer/', '.rsync-partial/']
    command = [shutil.which('rsync') or 'rsync', '-az', '--checksum', '--stats',
               '--timeout=120', '--partial-dir=.rsync-partial', '--rsync-path=sudo -n rsync',
               '-e', 'ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30']
    command += ['--exclude=' + value for value in exclusions]
    command += [topology['QM_SSH_TARGET'] + ':' + topology['QM_REMOTE_PROJECT'] + '/data/tushare/',
                str(root) + '/']
    status = root / 'archive-migration-status.json'
    atomic_json(status, {'stage': 'precopy', 'status': 'running', 'started_at': utc_now(),
                         'cloud_writer_disabled': False, 'migration_verified': False})
    result = subprocess.run(command)
    report = {'stage': 'precopy', 'status': 'copied' if result.returncode == 0 else 'retry_required',
              'returncode': result.returncode, 'updated_at': utc_now(),
              'cloud_writer_disabled': False, 'migration_verified': False}
    atomic_json(status, report)
    return result.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / ".migration.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(precopy(args.root))
