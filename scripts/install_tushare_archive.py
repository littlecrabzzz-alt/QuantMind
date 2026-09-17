#!/usr/bin/env python3
"""Install the native archive runtime; activation requires verified ownership."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tushare_mirror import install_client_python

PROJECT = Path(__file__).resolve().parents[1]
BASE = Path.home() / 'Library/Application Support/QuantMind'


def prepare(runtime):
    python = install_client_python(runtime)
    names = list(PROJECT.glob('backend/shared/tushare*.py')) + [PROJECT / name for name in (
        'backend/shared/runtime_secrets.py', 'backend/shared/stock_utils.py',
        'scripts/tushare_archive_worker.py', 'scripts/tushare_archive_migrate.py',
        'scripts/tushare_range_queue_migration.py',
        'scripts/tushare_factor_daily_retirement.py',
        'scripts/tushare_stock_lifecycle_migration.py',
        'scripts/tushare_asset_lifecycle_migration.py',
        'scripts/tushare_reassess_saved_quality.py',
        'scripts/tushare_invalid_request_retirement.py',
        'scripts/tushare_research_cache.py', 'config/tushare-catalog.json',
        'deploy/dual-node.env')]
    for source in names:
        target = runtime / source.relative_to(PROJECT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # Native intake also needs SOCKS support when macOS system proxies enable it.
    if subprocess.run([str(python), '-I', '-c', 'import pypdf, socksio; import httpx; httpx.Client().close()'], capture_output=True).returncode:
        uv = shutil.which('uv')
        if not uv:
            raise RuntimeError('uv required to install native client dependencies')
        subprocess.run([uv, 'pip', 'install', '--python', str(python), 'pypdf==6.17.0', 'httpx[socks]==0.28.1'], check=True)
    subprocess.run([str(python), '-I', '-c',
                    'import sys; sys.path.insert(0,sys.argv[1]); '
                    'from backend.shared import tushare_pipeline,tushare_documents; import pypdf,socksio; '
                    'import httpx; httpx.Client().close()',
                    str(runtime)], check=True)
    return python


def activate(root, runtime, python):
    # Check using the deployed runtime before installing an automatic writer.
    env = dict(os.environ, QM_NODE_ROLE='archive', QM_TUSHARE_ARCHIVE_ROOT=str(root))
    subprocess.run([str(python), '-I', '-c',
                    'import sys; sys.path.insert(0,sys.argv[1]); '
                    'from backend.shared.tushare_pipeline import authority; authority()',
                    str(runtime)], env=env, check=True)
    secret = runtime / 'config/archive.env'
    if not secret.is_file() or secret.is_symlink() or secret.stat().st_mode & 0o077:
        raise ValueError('Private archive.env with mode 0600 required')
    label = 'com.quantmind.tushare-archive'
    logs = BASE / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    plist = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    document = {
        'Label': label, 'ProgramArguments': [str(python), '-I', str(runtime / 'scripts/tushare_archive_worker.py'), '--root', str(root)],
        'WorkingDirectory': str(runtime), 'RunAtLoad': True, 'KeepAlive': True,
        'ThrottleInterval': 60,
        'EnvironmentVariables': {'QM_RUNTIME_ENV_FILE': str(secret), 'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
        'StandardOutPath': str(logs / 'tushare-archive.out.log'),
        'StandardErrorPath': str(logs / 'tushare-archive.err.log'),
    }
    target = f'gui/{os.getuid()}/{label}'
    if subprocess.run(['launchctl', 'print', target], capture_output=True).returncode == 0:
        raise ValueError('Archive worker already installed; drain it before upgrading')
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps(document))
    subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=BASE / 'tushare')
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Run on the Mac archive owner')
    runtime = BASE / 'tushare-client'
    if subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/com.quantmind.tushare-archive'], capture_output=True).returncode == 0:
        parser.error('Drain the running archive worker before preparing its runtime')
    python = prepare(runtime)
    if args.activate:
        activate(args.root.resolve(), runtime, python)
    print('Archive runtime prepared' + ('; worker installed' if args.activate else '; acquisition remains disabled'))
