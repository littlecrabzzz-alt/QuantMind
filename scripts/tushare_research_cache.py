#!/usr/bin/env python3
"""Serve verified Mac research slices and pull them into a bounded cloud cache.

Transport is loopback HTTP inside an SSH tunnel, never a public HTTP listener.
The full archive, acquisition databases and credentials are never served.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_pipeline import atomic_json, atomic_bytes, manifest_at

DEFAULT_APIS = ('daily', 'index_daily', 'fund_daily', 'adj_factor', 'daily_basic',
                'index_weight', 'ci_daily', 'sw_daily', 'stock_basic', 'index_basic',
                'fund_basic', 'trade_cal')
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


def prepare(root, apis):
    import pyarrow.parquet as pq
    root = root.resolve()
    pointer = json.loads((root / 'CURRENT.json').read_bytes())
    source = pointer['release_id']
    export = root / '.research-exports'
    key = hashlib.sha256(json.dumps({'format': 2, 'apis': sorted(apis)}).encode()).hexdigest()
    saved = export / (key + '.json')
    if saved.exists():
        old = json.loads(saved.read_bytes())
        if old['source_release_id'] == source:
            return old
    manifest = manifest_at(root, source)
    datasets = [d for d in manifest['datasets'] if d['api_name'] in apis]
    if not datasets:
        raise ValueError('Requested datasets unavailable')
    names = set()
    for dataset in datasets:
        name = dataset['path']
        path = checked(root, name, manifest['files'][name])
        names.add(name)
        for batch in pq.ParquetFile(path).iter_batches(columns=['_observation']):
            for observation in batch.column(0).to_pylist():
                relative = 'observations/' + observation
                if not FILE.fullmatch(relative) or relative not in manifest['files']:
                    raise ValueError('Observation missing from source release')
                names.add(relative)
    schema = manifest.get('schema_path')
    if schema:
        names.add(schema)
    for name in names:
        if not FILE.fullmatch(name):
            raise ValueError('Invalid research file')
        checked(root, name, manifest['files'][name])
    subset = {
        'schema_version': manifest.get('schema_version', 1),
        'source_release_id': source, 'scope': 'research_subset',
        'selected_api_names': sorted(apis), 'datasets': datasets,
        'files': {name: manifest['files'][name] for name in sorted(names)},
        'schema_path': schema, 'history_complete': False,
        'historical_versions_complete': False,
        'coverage': {'research_partitions': len(datasets)},
        'coverage_by_api': [r for r in manifest.get('coverage_by_api', [])
                            if r.get('api_name') in apis],
        'rrg_status': manifest.get('rrg_status', 'unverified'),
        'gaps': ['Research subset only; full acquisition evidence remains in source_release_id'],
    }
    raw = json.dumps(subset, sort_keys=True, ensure_ascii=False).encode()
    sha = hashlib.sha256(raw).hexdigest()
    result = {'release_id': 'data-' + sha, 'manifest_sha256': sha,
              'source_release_id': source}
    atomic_bytes(export / result['release_id'] / 'manifest.json', raw)
    atomic_json(saved, result)
    return result


def serve(root, apis, port):
    root = root.resolve()
    mutex = threading.Lock()
    available = {}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path == '/CURRENT.json':
                    with mutex:
                        pointer = prepare(root, apis)
                        folder = root / '.research-exports' / pointer['release_id']
                        manifest = json.loads((folder / 'manifest.json').read_bytes())
                        available.update(manifest['files'])
                        available['releases/' + pointer['release_id'] + '/manifest.json'] = folder / 'manifest.json'
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
        with urlopen(url + '/CURRENT.json', timeout=600) as response:
            pointer = json.loads(response.read(4096))
        release = pointer['release_id']
        if not RELEASE.fullmatch(release) or pointer['manifest_sha256'] != release[5:]:
            raise ValueError('Invalid release pointer')
        relative = 'releases/' + release + '/manifest.json'
        manifest_path = root / relative
        if not manifest_path.exists():
            if shutil.disk_usage(root).free < reserve + 64 * 1024**2:
                raise ValueError('Insufficient disk reserve')
            fetch(url + '/' + relative, manifest_path)
        manifest = manifest_at(root, release)
        if manifest.get('scope') != 'research_subset':
            raise ValueError('Refusing full archive mirror')
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
        for name, expected in missing:
            if shutil.disk_usage(root).free < reserve + expected['bytes']:
                raise ValueError('Disk reserve reached')
            fetch(url + '/' + name, root / name, expected, expected['bytes'])
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
