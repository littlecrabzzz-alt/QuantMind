#!/usr/bin/env python3
"""Bound bulk copies on the market data filesystem; never remove data."""
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess

RESERVE = 100 * 2**30
# Recheck before the hard reserve is reached, allowing for in-flight writes.
WRITE_MARGIN = 2 * 2**30


def require_capacity(path, additional=0, reserve=RESERVE):
    free = shutil.disk_usage(path).free
    if additional < 0 or free < reserve + additional:
        raise RuntimeError(f'Storage reserve: free={free}, additional={additional}, reserve={reserve}; bulk write refused')
    return free


def transfer_bytes(stats):
    match = re.search(r'^Total transferred file size:\s*([\d,]+) (?:bytes|B)$', stats, re.MULTILINE)
    if not match:
        raise RuntimeError('Cannot determine rsync capacity estimate; bulk write refused')
    return int(match[1].replace(',', ''))


@contextmanager
def storage_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.storage.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def guarded_run(args, root, **kwargs):
    """Bound a direct child and its process group, including on cancellation."""
    require_capacity(root, WRITE_MARGIN)
    payload = kwargs.pop('input', None)
    if payload is not None:
        # files-from lists may exceed a pipe buffer. A spool cannot deadlock.
        import tempfile
        with tempfile.TemporaryFile() as stream:
            stream.write(payload)
            stream.seek(0)
            return guarded_run(args, root, stdin=stream, **kwargs)
    process = subprocess.Popen(args, start_new_session=True, **kwargs)
    try:
        while True:
            try:
                code = process.wait(timeout=1)
                if code:
                    raise subprocess.CalledProcessError(code, args)
                require_capacity(root, WRITE_MARGIN)
                return subprocess.CompletedProcess(args, code)
            except subprocess.TimeoutExpired:
                require_capacity(root, WRITE_MARGIN)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def install_signal_handlers():
    def interrupted(signum, frame):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        raise InterruptedError(f"Bulk copy interrupted by signal {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--required-bytes', type=int, required=True)
    parser.add_argument('server_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.server_args
    if command[:1] == ['--']:
        command = command[1:]
    if command[:1] != ['--server'] or '--sender' in command:
        parser.error('Only rsync receiver mode is supported')
    with storage_lock(args.root):
        require_capacity(args.root, args.required_bytes + WRITE_MARGIN)
        guarded_run(['rsync', *command], args.root)


if __name__ == '__main__':
    main()
