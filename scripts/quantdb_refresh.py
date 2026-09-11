#!/usr/bin/env python3
"""Reuse snapshot transfer for QuantDB only; retain local work and frozen research inputs."""
import argparse
import ctypes
from contextlib import contextmanager
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import dual_node_snapshot as snapshot
from dual_node_inventory import stat_key
from dual_node_check import sandbox_mount_path


def records(project):
    root = project / 'data/quantdb'
    return {p.relative_to(project).as_posix(): stat_key(p.stat())
            for p in sorted(root.rglob('*.parquet')) if p.is_file() and not p.is_symlink()}


def manifest_rows(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        p = Path(row['path'])
        snapshot.require(not p.is_absolute() and '..' not in p.parts and
                         p.parts[:2] == ('data', 'quantdb') and p.suffix == '.parquet',
                         'Unexpected QuantDB manifest path')
    snapshot.require(len({r['path'] for r in rows}) == len(rows), 'Duplicate manifest path')
    return rows


def write_json(path, value):
    pending = path.with_suffix('.new')
    pending.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    os.replace(pending, path)


@contextmanager
def cloud_sync_lock():
    token = uuid.uuid4().hex
    code = ("from backend.shared.quantdb_sync_jobs import acquire_lock; "
            f"print(acquire_lock('quantmind:daily_sync:lock', '{token}', ttl=7200))")
    acquired = snapshot.output('docker', 'exec', 'quantmind', 'python', '-c', code)
    if acquired != 'True':
        raise snapshot.BusyError('QuantDB acquisition active; retry on next hourly pull')
    try:
        yield
    finally:
        snapshot.run('docker', 'exec', 'quantmind', 'python', '-c',
                     'from backend.shared.quantdb_sync_jobs import release_lock; '
                     f"release_lock('quantmind:daily_sync:lock', '{token}')")


def publish():
    remote = Path(snapshot.REMOTE)
    snapshot.require(os.geteuid() == 0 and (remote / 'AUTHORITY').is_file(), 'Cloud authority required')
    snapshot.require(snapshot.output('findmnt', '-n', '-o', 'UUID', '-T', str(remote)) ==
                     snapshot.SETTINGS['QM_DISK_UUID'], 'Cloud SSD not mounted')
    snapshot.require(shutil.disk_usage(remote).free > 100 * 1024**3, 'Keep 100 GiB recovery reserve')
    base = remote / 'quantdb-snapshots'
    base.mkdir(exist_ok=True)
    with (base / '.lock').open('w') as lock, cloud_sync_lock():
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        project = snapshot.PROJECT
        before = records(project)
        snapshot.require(bool(before), 'QuantDB is empty')
        cache_file = base / 'source-cache.json'
        cached = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        rows = []
        for name, stat in before.items():
            prior = cached.get(name, {})
            digest = prior.get('sha256') if prior.get('stat') == list(stat) else None
            rows.append({'path': name, 'bytes': stat[2], 'sha256': digest or snapshot.digest(project / name)})
        raw = ''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows)
        snapshot.require(records(project) == before, 'QuantDB changed while hashing; retry')
        write_json(cache_file, {r['path']: {'stat': before[r['path']], 'sha256': r['sha256']} for r in rows})
        previous = (base / 'latest').resolve()
        if (previous / 'COMPLETE').exists() and (previous / 'runtime-manifest.jsonl').read_text() == raw:
            print('QuantDB unchanged:', previous, flush=True)
            return
        target = base / '.building'
        (target / 'project/data/quantdb').mkdir(parents=True, exist_ok=True)
        (target / 'COMPLETE').unlink(missing_ok=True)
        reference = previous / 'project/data/quantdb'
        if not reference.is_dir():
            reference = (remote / 'snapshots/latest').resolve() / 'project/data/quantdb'
        args = ['rsync', '-a', '--checksum', '--delete', '--include=*/', '--include=*.parquet', '--exclude=*']
        if reference.is_dir():
            args.append('--link-dest=' + str(reference))
        snapshot.run(*args, str(project / 'data/quantdb') + '/', str(target / 'project/data/quantdb') + '/')
        snapshot.require(records(project) == before, 'QuantDB changed during copy; retry')
        (target / 'runtime-manifest.jsonl').write_text(raw)
        # Reuse independent frozen-copy verification; no DB dump, Tushare, or service stop.
        snapshot.finish_snapshot(target)
        published = base / ('snapshot-quantdb-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        target.rename(published)
        snapshot.publish_link(base, published)
        print('Published QuantDB:', published, flush=True)


def check_local_changes(project, baseline, incoming):
    old = {r['path']: r['sha256'] for r in baseline}
    new = {r['path']: r['sha256'] for r in incoming}
    local = records(project)
    for name in sorted(set(old) | set(new)):
        actual = snapshot.digest(project / name) if name in local else None
        # Already equal to incoming is a safe interrupted retry.
        if actual == new.get(name):
            continue
        if actual != old.get(name):
            raise RuntimeError(f'Local QuantDB edit retained; resolve before refresh: {name}')


def require_local_idle(project):
    snapshot.require(sys.platform == 'darwin', 'Apply only on Mac')
    snapshot.require(not os.getenv('DOCKER_HOST'), 'Unset DOCKER_HOST')
    endpoint = snapshot.output('docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}')
    snapshot.require(endpoint.startswith('unix://') and snapshot.output('docker', 'info', '--format',
                     '{{.OperatingSystem}}') == 'Docker Desktop', 'Local Docker Desktop required')
    running = snapshot.output('docker', 'ps', '--format', '{{.Names}}').splitlines()
    snapshot.require(not any(n.startswith(('qm-train-', 'qm-agent-', 'qm-frozen-', 'qm-ide-run-', 'rdagent-'))
                             for n in running), 'Running experiment: download retained; retry when idle')
    for worker, app in [('quantmind-dev-research-worker', 'backend.services.engine.research.tasks:app'),
                        ('quantmind-dev-celery', 'backend.services.engine.qlib_app.celery_config:celery_app')]:
        if worker not in running:
            continue
        for kind in ('active', 'reserved', 'scheduled'):
            tasks = json.loads(snapshot.output('docker', 'exec', worker, 'celery', '-A', app,
                                              'inspect', kind, '--json', '--timeout=5'))
            snapshot.require(bool(tasks) and not any(tasks.values()), 'Local work pending; retry when idle')
    snapshot.require('quantmind-dev' in running, 'Local backend stopped; downloaded version retained for next start')
    mounts = json.loads(snapshot.output('docker', 'inspect', 'quantmind-dev', '--format', '{{json .Mounts}}'))
    expected = (project / '.local-dev/project/data').resolve()
    snapshot.require(any(m['Destination'] == '/data' and sandbox_mount_path(m['Source'], project) == expected for m in mounts),
                     'Unexpected local data mount')
    return [name for name in ('quantmind-dev-celery', 'quantmind-dev-research-worker', 'quantmind-dev') if name in running]


DERIVED = '''
import json
from datetime import timedelta
from backend.scripts.quantdb_daily_sync import _pg_latest_trade_date, fill_pg_from_parquet
latest = _pg_latest_trade_date()
assert latest is not None, 'Refusing an unexpected empty local market database'
result = fill_pg_from_parquet(start_date=latest + timedelta(days=1))
assert result.get('status') in ('ok', 'skipped'), result
from backend.services.engine.qlib_data_builder import ensure_qlib_cache
from backend.shared.qlib_paths import resolve_qlib_provider_uri
import uuid
from pathlib import Path
import os
root = Path(os.environ.get('QM_QUANTDB_DATA_DIR', '/data/quantdb'))
newest = max(p.name[3:] for p in (root / '1_kline_data/daily_forward').glob('dt=*'))
assert _pg_latest_trade_date().strftime('%Y%m%d') == newest
live = Path(resolve_qlib_provider_uri('CN'))
staged = live.parent / ('.quantdb-qlib-' + uuid.uuid4().hex)
ensure_qlib_cache(quantdb_dir=root, qlib_dir=staged)
calendar = (staged / 'calendars/day.txt').read_text().splitlines()[-1]
assert calendar.replace('-', '') == newest, (calendar, newest)
print(json.dumps({'latest_date': newest, 'pg': result, 'qlib_calendar': calendar, 'qlib_live': str(live), 'qlib_staged': str(staged)}))
'''


def publish_local_directory(staged, live):
    # Docker Desktop does not implement Linux directory exchange on Mac mounts.
    # Publish on the host, where the same APFS atomic operation works.
    if not live.exists():
        staged.rename(live)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renamex_np(os.fsencode(staged), os.fsencode(live), 2) != 0:
        raise OSError(ctypes.get_errno(), 'Atomic local data exchange failed')


def local_cache_path(local, container_path):
    path = Path(container_path)
    for mount, relative in (('/data', 'data'), ('/app/db', 'db')):
        if path.is_relative_to(mount):
            target = local / relative / path.relative_to(mount)
            snapshot.require(target.resolve().is_relative_to((local / relative).resolve()),
                             'Qlib cache escaped local sandbox')
            return target
    raise RuntimeError('Unexpected Qlib cache mount: ' + container_path)


def apply(project, downloaded):
    downloaded = downloaded.resolve()
    snapshot.require((downloaded / 'COMPLETE').is_file() and (downloaded / 'VERIFIED').is_file(),
                     'Only verified completed downloads can be applied')
    state = project / '.local-dev'
    snapshot.require((state / 'READY').is_file(), 'Local sandbox is not initialized')
    incoming = manifest_rows(downloaded / 'runtime-manifest.jsonl')
    receipt = state / 'QUANTDB_SYNC.json'
    prior = json.loads(receipt.read_text()) if receipt.exists() else {}
    if prior.get('snapshot') == str(downloaded) and prior.get('status') == 'applied':
        print('Local QuantDB already applied:', downloaded.name, flush=True)
        return
    lockdir = project / 'logs/local-dev.lock'
    lockdir.mkdir()  # Share the existing local start/stop mutex.
    (lockdir / 'pid').write_text(str(os.getpid()))
    stopped = []
    try:
        stopped = require_local_idle(project)
        previous = Path(prior['snapshot']) if prior.get('snapshot') else (
            project / 'logs/cloud-snapshots' / (state / 'SNAPSHOT_ID').read_text().strip())
        baseline = [json.loads(line) for line in (previous / 'runtime-manifest.jsonl').read_text().splitlines()
                    if json.loads(line)['path'].startswith('data/quantdb/') and json.loads(line)['path'].endswith('.parquet')]
        local = state / 'project'
        snapshot.run('docker', 'stop', '--time', '60', *stopped)
        check_local_changes(local, baseline, incoming)
        if prior.get('snapshot') == str(downloaded) and prior.get('status') == 'files_applied':
            backup = Path(prior['backup'])
        else:
            live = local / 'data/quantdb'
            staged = local / 'data' / ('.quantdb-refresh-' + uuid.uuid4().hex)
            snapshot.run('cp', '-cR', str(live), str(staged))  # APFS clone, including local catalogs.
            rsync = '/opt/homebrew/bin/rsync' if Path('/opt/homebrew/bin/rsync').exists() else 'rsync'
            snapshot.run(rsync, '-a', '--checksum', '--no-owner', '--no-group',
                         str(downloaded / 'project/data/quantdb') + '/', str(staged) + '/')
            new_names = {r['path'] for r in incoming}
            for row in baseline:
                if row['path'] not in new_names:
                    (staged / Path(row['path']).relative_to('data/quantdb')).unlink(missing_ok=True)
            for row in incoming:
                snapshot.require(snapshot.digest(staged / Path(row['path']).relative_to('data/quantdb')) == row['sha256'],
                                 'Staged local checksum mismatch')
            backup = state / ('quantdb-before-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6])
            # Same atomic directory exchange used by Qlib publication; old files survive.
            publish_local_directory(staged, live)
            staged.rename(backup)
            write_json(receipt, {'status': 'files_applied', 'snapshot': str(downloaded), 'backup': str(backup)})
        # Keep the API stopped until files, PG and Qlib agree: no new training
        # request can enter between the data exchange and cache completion.
        result = snapshot.output(
            'env', 'QM_LOCAL_PROJECT=' + str(project), 'QM_LOCAL_STATE=' + str(local),
            'docker', 'compose', '--project-name', 'quantmind-dev',
            '--env-file', str(project / '.env.local'), '-f', str(project / 'docker-compose.yml'),
            '-f', str(project / 'deploy/compose.local-dev.yml'), '--project-directory', str(project),
            'run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'quantmind', '-c', DERIVED)
        validation = json.loads(result.splitlines()[-1])
        qlib_staged = local_cache_path(local, validation['qlib_staged'])
        qlib_live = local_cache_path(local, validation['qlib_live'])
        snapshot.require(qlib_staged.name.startswith('.quantdb-qlib-') and
                         qlib_staged.parent == qlib_live.parent, 'Unexpected staged Qlib path')
        publish_local_directory(qlib_staged, qlib_live)
        qlib_backup = state / ('qlib-before-' + uuid.uuid4().hex)
        if qlib_staged.exists():
            qlib_staged.rename(qlib_backup)
        write_json(receipt, {'status': 'applied', 'snapshot': str(downloaded), 'backup': str(backup),
                             'qlib_backup': str(qlib_backup), 'validation': validation})
        print('Applied local QuantDB:', result, flush=True)
    finally:
        try:
            if stopped:
                snapshot.run('docker', 'start', *stopped)
        finally:
            (lockdir / 'pid').unlink(missing_ok=True)
            lockdir.rmdir()


def refresh(project, base):
    snapshot.PROJECT = project
    snapshot.run('ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', snapshot.SETTINGS['QM_SSH_TARGET'],
                 'sudo -n python3 ' + snapshot.SETTINGS['QM_REMOTE_PROJECT'] + '/scripts/quantdb_refresh.py publish')
    snapshot.pull_snapshot(base, only_new=True, remote_base='quantdb-snapshots')
    downloaded = (base / 'latest').resolve()
    snapshot.require((downloaded / 'VERIFIED').is_file(), 'Download is not verified')
    apply(project, downloaded)


if __name__ == '__main__':
    snapshot.install_signal_handlers()
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['publish', 'refresh', 'apply'])
    parser.add_argument('--project', type=Path, default=snapshot.PROJECT)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.action == 'publish':
        publish()
    elif args.action == 'refresh':
        refresh(args.project, args.root or args.project / 'logs/cloud-snapshots/quantdb')
    else:
        apply(args.project, (args.root or args.project / 'logs/cloud-snapshots/quantdb') / 'latest')
