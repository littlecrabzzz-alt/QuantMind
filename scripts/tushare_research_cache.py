#!/usr/bin/env python3
"""Serve verified Mac research slices and pull them into a bounded cloud cache.

Transport is loopback HTTP inside an SSH tunnel, never a public HTTP listener.
The full archive, acquisition databases and credentials are never served.
"""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import RESEARCH_APIS, atomic_json, atomic_bytes, manifest_at, utc_now

DEFAULT_APIS = RESEARCH_APIS
PREPARE_TIMEOUT_SECONDS = 30 * 60
MAX_MANIFEST_BYTES = 512 * 1024**2
FILE = re.compile(r'(?:parquet|observations|schemas)/[a-f0-9]+\.(?:parquet|json)')
RELEASE = re.compile(r'data-[a-f0-9]{64}')


def checked(root, name, expected):
    path = root / name
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Symlink not allowed')
    sha = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            sha.update(block)
            size += len(block)
    if size != expected['bytes'] or sha.hexdigest() != expected['sha256']:
        raise ValueError('File checksum mismatch')
    return path


def source_pointer(root, apis):
    """Use the independent lane only when it covers the entire requested scope."""
    path = root / 'RESEARCH_CURRENT.json'
    if path.is_symlink():
        raise ValueError('Unsafe research pointer')
    if path.exists():
        pointer = json.loads(path.read_bytes())
        if (not RELEASE.fullmatch(pointer.get('release_id', ''))
                or pointer.get('manifest_sha256') != pointer['release_id'][5:]
                or not isinstance(pointer.get('selected_api_names'), list)
                or not all(isinstance(api, str) for api in pointer['selected_api_names'])):
            raise ValueError('Invalid research pointer')
        if set(apis) <= set(pointer['selected_api_names']):
            return pointer
    return json.loads((root / 'CURRENT.json').read_bytes())


def prepare(root, apis):
    import pyarrow.parquet as pq
    root = root.resolve()
    pointer = source_pointer(root, apis)
    source = pointer['release_id']
    export = root / '.research-exports'
    key = hashlib.sha256(json.dumps({'format': 2, 'apis': sorted(apis)}).encode()).hexdigest()
    saved = export / (key + '.json')
    if saved.exists():
        old = json.loads(saved.read_bytes())
        if old['source_release_id'] == source:
            return old
    previous = cached_export(root, apis) if saved.exists() else reusable_export(root, apis)
    manifest = manifest_at(root, source)
    if 'selected_api_names' in pointer and (
            manifest.get('scope') != 'research_structured'
            or manifest.get('selected_api_names') != pointer['selected_api_names']):
        raise ValueError('Research source scope mismatch')
    datasets = [d for d in manifest['datasets'] if d['api_name'] in apis]
    if not datasets:
        raise ValueError('Requested datasets unavailable')
    schema = manifest.get('schema_path')
    paths = {d['path'] for d in datasets}
    previous_paths = set()
    reused = set()
    if previous:
        old_manifest = previous[1]
        previous_paths = {d['path'] for d in old_manifest['datasets']}
        old_files = old_manifest['files']
        # Immutable paths already passed the previous export's SHA checks. Only
        # reuse them when the new full release retains every selected partition
        # and its exact file descriptor; otherwise rebuild the exact subset.
        if (previous_paths <= paths and all(
                manifest['files'].get(name) == expected
                for name, expected in old_files.items())):
            reused = set(old_files)
            if old_manifest.get('schema_path') != schema:
                reused.discard(old_manifest.get('schema_path'))
        else:
            previous_paths.clear()
    names = set(reused)
    for dataset in datasets:
        name = dataset['path']
        if name in previous_paths:
            continue
        path = checked(root, name, manifest['files'][name])
        names.add(name)
        for batch in pq.ParquetFile(path).iter_batches(columns=['_observation']):
            for observation in batch.column(0).unique().to_pylist():
                relative = 'observations/' + observation
                if not FILE.fullmatch(relative) or relative not in manifest['files']:
                    raise ValueError('Observation missing from source release')
                names.add(relative)
    if schema:
        names.add(schema)
    for name in names:
        if not FILE.fullmatch(name):
            raise ValueError('Invalid research file')
        if name not in reused:
            checked(root, name, manifest['files'][name])
    subset = {
        'schema_version': manifest.get('schema_version', 1),
        'source_release_id': source, 'scope': 'research_subset',
        'source_scope': manifest.get('scope'),
        'selected_api_names': sorted(apis), 'datasets': datasets,
        'files': {name: manifest['files'][name] for name in sorted(names)},
        'schema_path': schema, 'history_complete': False,
        'historical_versions_complete': False,
        'coverage': {'research_partitions': len(datasets)},
        'coverage_by_api': [r for r in manifest.get('coverage_by_api', [])
                            if r.get('api_name') in apis],
        'rrg_status': manifest.get('rrg_status', 'unverified'),
        'gaps': ['Research subset only; acquisition completeness is not established'],
        'source_gaps': manifest.get('gaps', []) if 'selected_api_names' in pointer else [],
    }
    raw = json.dumps(subset, sort_keys=True, ensure_ascii=False).encode()
    sha = hashlib.sha256(raw).hexdigest()
    result = {'release_id': 'data-' + sha, 'manifest_sha256': sha,
              'source_release_id': source}
    atomic_bytes(export / result['release_id'] / 'manifest.json', raw)
    atomic_json(saved, result)
    return result


def cached_export(root, apis):
    key = hashlib.sha256(json.dumps({'format': 2, 'apis': sorted(apis)}).encode()).hexdigest()
    saved = root / '.research-exports' / (key + '.json')
    if not saved.exists():
        return None
    result = _checked_export(root, saved)
    if result[1].get('selected_api_names') != sorted(apis):
        raise ValueError('Cached research scope mismatch')
    return result


def _checked_export(root, saved):
    pointer = json.loads(saved.read_bytes())
    release = pointer['release_id']
    if (not RELEASE.fullmatch(release) or pointer['manifest_sha256'] != release[5:]
            or not RELEASE.fullmatch(pointer['source_release_id'])):
        raise ValueError('Invalid cached research release')
    path = root / '.research-exports' / release / 'manifest.json'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pointer['manifest_sha256']:
        raise ValueError('Cached research manifest checksum mismatch')
    manifest = json.loads(raw)
    apis = manifest.get('selected_api_names')
    if (manifest.get('scope') != 'research_subset'
            or manifest.get('source_release_id') != pointer['source_release_id']
            or not isinstance(apis, list) or not all(isinstance(a, str) for a in apis)
            or apis != sorted(set(apis))):
        raise ValueError('Cached research scope mismatch')
    key = hashlib.sha256(json.dumps({'format': 2, 'apis': apis}).encode()).hexdigest()
    if saved.name != key + '.json':
        raise ValueError('Cached research key mismatch')
    return pointer, manifest, path


def reusable_export(root, apis):
    """Reuse a verified narrower export when the requested API set grows."""
    best = None
    for saved in sorted((root / '.research-exports').glob('*.json')):
        try:
            candidate = _checked_export(root, saved)
            manifest = candidate[1]
            if (set(manifest['selected_api_names']) < set(apis)
                    and (best is None or len(manifest['files']) > len(best[1]['files']))):
                best = candidate
        except (OSError, ValueError, KeyError, TypeError):
            # An unrelated invalid cache cannot provide reusable validation.
            # The requested export still performs full checks for those files.
            continue
    return best


class SourcePublication:
    def __init__(self, root, apis):
        self.root, self.apis = root, apis
        self.lock = threading.Lock()
        self.refreshing = False

    def _refresh(self):
        try:
            prepare(self.root, self.apis)
        except Exception:
            logging.exception('Research subset preparation failed; verified release retained')
        finally:
            with self.lock:
                self.refreshing = False

    def current(self):
        source_state = source_pointer(self.root, self.apis)
        source = source_state['release_id']
        with self.lock:
            cached = cached_export(self.root, self.apis)
            if cached is None:
                prepare(self.root, self.apis)
                cached = cached_export(self.root, self.apis)
            elif cached[0]['source_release_id'] != source and not self.refreshing:
                self.refreshing = True
                threading.Thread(target=self._refresh, daemon=True).start()
        pointer, manifest, path = cached
        return {**pointer, 'latest_source_release_id': source,
                'latest_source_published_at': source_state.get('published_at'),
                'source_lagged': pointer['source_release_id'] != source}, manifest, path


def serve(root, apis, port):
    root = root.resolve()
    publication = SourcePublication(root, apis)
    mutex = threading.Lock()
    available = {}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path == '/CURRENT.json':
                    pointer, manifest, folder_manifest = publication.current()
                    with mutex:
                        available.update(manifest['files'])
                        available['releases/' + pointer['release_id'] + '/manifest.json'] = folder_manifest
                    raw = json.dumps(pointer).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                name = self.path.removeprefix('/')
                record = available.get(name)
                if record is None:
                    self.send_error(404)
                    return
                path = record if isinstance(record, Path) else checked(root, name, record)
                with path.open('rb') as stream:
                    self.send_response(200)
                    self.send_header('Content-Length', str(path.stat().st_size))
                    self.end_headers()
                    shutil.copyfileobj(stream, self.wfile, 1024**2)
            except (OSError, ValueError, KeyError, TypeError):
                self.send_error(503, 'Verified archive unavailable')
        def log_message(self, *_):
            pass
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def fetch(url, target, expected=None, limit=64 * 1024**2):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.part')
    sha, size = hashlib.sha256(), 0
    try:
        with urlopen(url, timeout=120) as response, temporary.open('wb') as stream:
            while block := response.read(1024**2):
                size += len(block)
                if size > limit:
                    raise ValueError('Transfer exceeds reservation')
                sha.update(block)
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        if expected and (size != expected['bytes'] or sha.hexdigest() != expected['sha256']):
            raise ValueError('Transfer checksum mismatch')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def pull(root, url, budget, reserve):
    if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', url):
        raise ValueError('Source must be an SSH loopback tunnel')
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'pipeline.sqlite').exists() or (root / 'ENABLED').exists():
        raise ValueError('Refusing acquisition store as cache')
    with (root / '.cache.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with urlopen(
            url + '/CURRENT.json', timeout=PREPARE_TIMEOUT_SECONDS
        ) as response:
            pointer = json.loads(response.read(4096))
        release = pointer['release_id']
        if not RELEASE.fullmatch(release) or pointer['manifest_sha256'] != release[5:]:
            raise ValueError('Invalid release pointer')
        relative = 'releases/' + release + '/manifest.json'
        manifest_path = root / relative
        if not manifest_path.exists():
            if shutil.disk_usage(root).free < reserve + MAX_MANIFEST_BYTES:
                raise ValueError('Insufficient disk reserve')
            fetch(url + '/' + relative, manifest_path, limit=MAX_MANIFEST_BYTES)
        manifest = manifest_at(root, release)
        if manifest.get('scope') != 'research_subset':
            raise ValueError('Refusing full archive mirror')
        if (pointer.get('source_release_id') != manifest.get('source_release_id')
                or not isinstance(pointer.get('latest_source_release_id'), str)
                or not RELEASE.fullmatch(pointer['latest_source_release_id'])
                or pointer.get('source_lagged') != (
                    pointer['source_release_id'] != pointer['latest_source_release_id'])):
            raise ValueError('Research source lag metadata mismatch')
        missing = []
        for name, expected in manifest['files'].items():
            if not FILE.fullmatch(name):
                raise ValueError('Invalid cache object')
            try:
                checked(root, name, expected)
            except FileNotFoundError:
                missing.append((name, expected))
        used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        needed = sum(item['bytes'] for _, item in missing)
        if used + needed > budget or shutil.disk_usage(root).free < reserve + needed:
            raise ValueError('Cache budget exceeded; existing release retained')
        progress = {'status': 'downloading', **pointer, 'total_missing_files': len(missing),
                    'downloaded_files': 0, 'downloaded_bytes': 0, 'needed_bytes': needed,
                    'started_at': utc_now()}
        def save_progress():
            progress['updated_at'] = utc_now()
            atomic_json(root / 'cache-transfer-status.json', progress)
        def download(item):
            name, expected = item
            if shutil.disk_usage(root).free < reserve + expected['bytes']:
                raise ValueError('Disk reserve reached')
            fetch(url + '/' + name, root / name, expected, expected['bytes'])
            return expected['bytes']
        save_progress()
        try:
            # Eight in-flight objects amortize SSH latency; memory stays bounded.
            with ThreadPoolExecutor(max_workers=8) as pool:
                pending = deque()
                items = iter(missing)
                for _ in range(min(8, len(missing))):
                    pending.append(pool.submit(download, next(items)))
                while pending:
                    progress['downloaded_bytes'] += pending.popleft().result()
                    progress['downloaded_files'] += 1
                    item = next(items, None)
                    if item is not None:
                        pending.append(pool.submit(download, item))
                    if progress['downloaded_files'] % 100 == 0:
                        save_progress()
        except Exception as exc:
            progress.update(status='failed', error_type=type(exc).__name__)
            save_progress()
            raise
        progress['status'] = 'downloaded'
        save_progress()
        atomic_json(root / 'CURRENT.json', pointer)
        report = {'status': 'verified', **pointer, 'downloaded_files': len(missing),
                  'selected_api_names': manifest['selected_api_names'],
                  'cache_bytes': used + needed, 'budget_bytes': budget,
                  'upstream_calls': 0}
        atomic_json(root / 'cache-status.json', report)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'pull'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--apis', nargs='+', default=DEFAULT_APIS)
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--source', default='http://127.0.0.1:18765')
    parser.add_argument('--budget-gib', type=int, default=100)
    parser.add_argument('--reserve-gib', type=int, default=100)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'serve':
        serve(args.root, args.apis, args.port)
    else:
        print(json.dumps(pull(args.root, args.source, args.budget_gib * 2**30, args.reserve_gib * 2**30)))
