#!/usr/bin/env python3
"""Resumable immutable-file precopy; does not copy live SQLite or enable writers."""
import argparse
import fcntl
import json
import hashlib
import os
import sqlite3
import socket
import shlex
from contextlib import ExitStack
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
    command = [shutil.which('rsync') or 'rsync', '-az', '--stats',
               '--timeout=600', '--partial-dir=.rsync-partial', '--rsync-path=sudo -n rsync',
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


IGNORED_DIRS = {'.migration', '.research-exports', '.manifest-transfer', '.rsync-partial'}


def inventory_files(root):
    """All stored content, including unpublished objects and old releases."""
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in dirs + files:
            if (Path(directory) / name).is_symlink():
                raise ValueError('Symlink in archive')
        for name in sorted(files):
            if (name.endswith(('.lock', '.tmp', '.part', '-status.json', '-wal', '-shm'))
                    or name.startswith('ENABLED') or name == 'ARCHIVE_AUTHORITY.json'):
                continue
            yield Path(directory) / name


def digest(path):
    sha = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            sha.update(block)
            size += len(block)
    return {'bytes': size, 'sha256': sha.hexdigest()}


def frozen_checkpoint(root, *, wait_locks=False):
    """Called only after disabling Tushare admission and draining its workers.

    Busy locks fail immediately. Nothing enables/disables services here.
    SQLite backup output and file inventory remain private under .migration.
    """
    root = root.resolve()
    if (root / 'ENABLED').exists():
        raise ValueError('Disable Tushare acquisition before checkpoint')
    with ExitStack() as stack:
        for name in ('pipeline.lock', 'documents.lock', '.archive.lock'):
            lock = stack.enter_context((root / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait_locks else fcntl.LOCK_NB))
        if (root / 'ENABLED').exists():
            raise ValueError('Acquisition was reenabled while waiting for locks')
        target = root / '.migration' / ('checkpoint-' + utc_now().replace(':', '-'))
        target.mkdir(parents=True)
        count = total = 0
        inventory = target / 'inventory.jsonl'
        with inventory.open('w') as output:
            for path in inventory_files(root):
                relative = path.relative_to(root).as_posix()
                source = path
                if relative == 'CURRENT.json':
                    source = target / 'CURRENT.json'
                    shutil.copyfile(path, source)
                elif path.suffix in ('.sqlite', '.sqlite3'):
                    source = target / 'databases' / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if path.stat().st_size == 0:
                        source.touch()
                    else:
                        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                            with sqlite3.connect(source) as copy:
                                db.backup(copy)
                                if copy.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                                    raise ValueError('Invalid checkpoint database')
                record = {'path': relative, **digest(source)}
                if source != path:
                    record['checkpoint_path'] = source.relative_to(root).as_posix()
                output.write(json.dumps(record, sort_keys=True) + '\n')
                count += 1
                total += record['bytes']
        if (root / 'ENABLED').exists():
            raise ValueError('Acquisition was reenabled during checkpoint')
        atomic_json(target / 'COMPLETE.json', {
            'created_at': utc_now(), 'files': count, 'bytes': total,
            'inventory': digest(inventory), 'cloud_writer_disabled': True,
        })
        return target


def install_checkpoint(root, checkpoint):
    """Install verified SQLite backups without overwriting an existing writer."""
    root, checkpoint = root.resolve(), checkpoint.resolve()
    if (root / 'ENABLED').exists() or (root / 'ARCHIVE_AUTHORITY.json').exists():
        raise ValueError('Refusing checkpoint installation on an enabled owner')
    proof = json.loads((checkpoint / 'COMPLETE.json').read_bytes())
    inventory = checkpoint / 'inventory.jsonl'
    if digest(inventory) != proof['inventory']:
        raise ValueError('Inventory checksum mismatch')
    with ExitStack() as stack:
        for name in ('.archive-worker.lock', 'pipeline.lock', 'documents.lock', '.archive.lock'):
            lock = stack.enter_context((root / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backups = []
        with inventory.open() as stream:
            for line in stream:
                record = json.loads(line)
                if not record.get('checkpoint_path') or record['path'] == 'CURRENT.json':
                    continue
                relative = Path(record['path'])
                if relative.is_absolute() or '..' in relative.parts or relative.suffix not in ('.sqlite', '.sqlite3'):
                    raise ValueError('Invalid database destination')
                source = checkpoint / 'databases' / relative
                target = root / relative
                for path in (source, target):
                    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                        raise ValueError('Symlink checkpoint path')
                expected = {k: record[k] for k in ('bytes', 'sha256')}
                if digest(source) != expected:
                    raise ValueError('Corrupt database checkpoint')
                if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
                    raise ValueError('Destination has live SQLite state')
                if target.exists() and digest(target) != expected:
                    raise ValueError('Existing database differs; preserve and reconcile it')
                backups.append((source, target, expected))
        needed = sum(info['bytes'] for _, target, info in backups if not target.exists())
        if shutil.disk_usage(root).free < needed + 300 * 2**30:
            raise ValueError('Keep 300 GiB free while installing checkpoints')
        for source, target, expected in backups:
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.part')
            if temporary.is_symlink():
                raise ValueError('Symlink checkpoint staging path')
            try:
                shutil.copyfile(source, temporary)
                if digest(temporary) != expected:
                    raise ValueError('Checkpoint copy checksum mismatch')
                with temporary.open('rb') as stream:
                    os.fsync(stream.fileno())
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return {'status': 'checkpoints_installed', 'databases': len(backups),
                'current_published': False, 'migration_verified': False}


def verify_checkpoint(root, checkpoint, *, staged_current=False):
    """Verify transferred content against a frozen source; never grant ownership."""
    root = root.resolve()
    proof = json.loads((checkpoint / 'COMPLETE.json').read_bytes())
    inventory = checkpoint / 'inventory.jsonl'
    if digest(inventory) != proof['inventory']:
        raise ValueError('Inventory checksum mismatch')
    count = total = 0
    with inventory.open() as stream:
        for line in stream:
            record = json.loads(line)
            relative = Path(record['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Invalid inventory path')
            path = (checkpoint / 'CURRENT.json') if staged_current and record['path'] == 'CURRENT.json' else root / relative
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise ValueError('Symlink in destination')
            if digest(path) != {k: record[k] for k in ('bytes', 'sha256')}:
                raise ValueError('Migration file mismatch: ' + relative.as_posix())
            count += 1
            total += record['bytes']
    if count != proof['files'] or total != proof['bytes']:
        raise ValueError('Inventory totals mismatch')
    report = {'status': 'verified_files', 'files': count, 'bytes': total,
              'inventory': proof['inventory'], 'verified_at': utc_now(),
              'migration_verified': False, 'reason': 'Writer handoff still required'}
    atomic_json(root / 'archive-migration-status.json', report)
    return report


def seal_source(root, checkpoint, owner):
    """Fence the paused source after destination verification; never delete data."""
    root, checkpoint = root.resolve(), checkpoint.resolve()
    if not checkpoint.is_relative_to(root / '.migration') or not owner or len(owner) > 255:
        raise ValueError('Invalid handoff identity')
    if (root / 'ENABLED').exists() or not (root / 'ENABLED.migration-paused').exists():
        raise ValueError('Source must remain paused')
    proof = json.loads((checkpoint / 'COMPLETE.json').read_bytes())
    if digest(checkpoint / 'inventory.jsonl') != proof['inventory']:
        raise ValueError('Source inventory mismatch')
    with ExitStack() as stack:
        for name in ('pipeline.lock', 'documents.lock', '.archive.lock'):
            lock = stack.enter_context((root / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / 'ENABLED').exists():
            raise ValueError('Source resumed during handoff')
        if digest(root / 'CURRENT.json') != digest(checkpoint / 'CURRENT.json'):
            raise ValueError('Source published after checkpoint')
        record = {'owner_hostname': owner, 'inventory': proof['inventory'],
                  'current': digest(checkpoint / 'CURRENT.json'), 'source_paused': True}
        marker = root / 'ARCHIVE_RELOCATED.json'
        if marker.exists() and json.loads(marker.read_bytes()) != record:
            raise ValueError('Source already handed to a different checkpoint or owner')
        atomic_json(marker, record)
        return record


def finalize_archive(root, checkpoint):
    """Verify every local file, fence cloud, then publish local ownership."""
    root, checkpoint = root.resolve(), checkpoint.resolve()
    if (root / 'ENABLED').exists() or (root / 'ARCHIVE_AUTHORITY.json').exists():
        raise ValueError('Archive ownership already active; refuse another handoff')
    # The caller holds .migration.lock, excluding the precopy installer.
    with (root / '.archive-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = verify_checkpoint(root, checkpoint, staged_current=True)
        topology = dict(line.split('=', 1) for line in
                        (Path(__file__).resolve().parents[1] / 'deploy/dual-node.env').read_text().splitlines()
                        if line and not line.startswith('#'))
        remote_root = topology['QM_REMOTE_PROJECT'] + '/data/tushare'
        remote_checkpoint = remote_root + '/.migration/' + checkpoint.name
        command = ['sudo', '-n', '/usr/bin/python3',
                   topology['QM_REMOTE_PROJECT'] + '/scripts/tushare_archive_migrate.py',
                   '--root', remote_root, '--action', 'seal-source',
                   '--checkpoint', remote_checkpoint, '--owner', socket.gethostname()]
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                                 topology['QM_SSH_TARGET'], shlex.join(command)],
                                check=True, capture_output=True, text=True, timeout=120)
        seal = json.loads(result.stdout)
        if (seal.get('owner_hostname') != socket.gethostname()
                or seal.get('inventory') != report['inventory']
                or seal.get('current') != digest(checkpoint / 'CURRENT.json')
                or seal.get('source_paused') is not True):
            raise ValueError('Cloud handoff evidence does not match local verification')
        from backend.shared.tushare_pipeline import atomic_bytes
        atomic_bytes(root / 'CURRENT.json', (checkpoint / 'CURRENT.json').read_bytes())
        atomic_json(root / 'ARCHIVE_AUTHORITY.json', {
            **seal, 'migration_verified': True, 'verified_at': utc_now(),
            'verified_files': report['files'], 'verified_bytes': report['bytes']})
        atomic_bytes(root / 'ENABLED', b'archive-owner\n')
        report.update(status='ownership_transferred', migration_verified=True,
                      cloud_writer_disabled=True, owner_hostname=socket.gethostname())
        atomic_json(root / 'archive-migration-status.json', report)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--action', choices=['precopy', 'checkpoint', 'install-checkpoint', 'verify', 'seal-source', 'finalize'], default='precopy')
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--staged-current', action='store_true')
    parser.add_argument('--wait-locks', action='store_true')
    parser.add_argument('--owner')
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / ".migration.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'precopy':
            raise SystemExit(precopy(args.root))
        elif args.action == 'checkpoint':
            print(frozen_checkpoint(args.root, wait_locks=args.wait_locks))
        else:
            if args.checkpoint is None:
                parser.error('--checkpoint is required')
            if args.action == 'seal-source':
                print(json.dumps(seal_source(args.root, args.checkpoint, args.owner)))
                raise SystemExit(0)
            if args.action == 'finalize':
                print(json.dumps(finalize_archive(args.root, args.checkpoint)))
                raise SystemExit(0)
            if args.action == 'install-checkpoint':
                print(json.dumps(install_checkpoint(args.root, args.checkpoint)))
                raise SystemExit(0)
            print(json.dumps(verify_checkpoint(args.root, args.checkpoint, staged_current=args.staged_current)))
