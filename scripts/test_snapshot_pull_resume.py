"""Real local-rsync coverage of explicit, unverified snapshot resume boundaries."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dual_node_snapshot as snapshots


@pytest.fixture
def pull_fixture(tmp_path, monkeypatch):
    if not shutil.which('rsync'):
        pytest.skip('Snapshot transport requires rsync')
    remote = tmp_path / 'remote'
    identity = 'snapshot-20261016T181726188112Z'
    source = remote / 'snapshots' / identity
    (source / 'project' / 'data').mkdir(parents=True)
    (source / 'project' / 'data' / 'current.bin').write_bytes(b'actual immutable runtime bytes')
    (source / 'snapshot-scope.json').write_text(json.dumps({'scope': snapshots.SCOPE}))
    (source / 'runtime-manifest.jsonl').write_text(snapshots.manifest(source / 'project', scope=snapshots.SCOPE))
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in source.iterdir() if path.is_file()}
    (source / 'SHA256.json').write_text(json.dumps(hashes))
    (source / 'COMPLETE').touch()
    base = tmp_path / 'local'
    target = base / identity
    (target / 'project' / 'data').mkdir(parents=True)
    (target / 'project' / 'data' / 'stale.bin').write_bytes(b'retain these old downloaded bytes')
    project = tmp_path / 'empty-project'
    (project / 'logs').mkdir(parents=True)
    monkeypatch.setattr(snapshots, 'PROJECT', project)
    monkeypatch.setattr(snapshots, 'REMOTE', str(remote))
    monkeypatch.setattr(snapshots, 'SETTINGS', {'QM_SSH_TARGET': 'fixture'})

    def remote_complete(*args, **kwargs):
        assert args[0] == 'ssh'
        assert (source / 'COMPLETE').is_file()

    def actual_local_transfer(*args):
        command = list(args)
        assert command[-2].startswith('fixture:')
        command[-2] = command[-2].removeprefix('fixture:')
        subprocess.run(command, check=True, capture_output=True)

    monkeypatch.setattr(snapshots, 'run', remote_complete)
    monkeypatch.setattr(snapshots, 'output', lambda *args: str(source))
    monkeypatch.setattr(snapshots, 'transfer', actual_local_transfer)
    return base, target, identity


def test_unverified_explicit_resume_retains_removed_runtime_bytes(pull_fixture):
    base, target, identity = pull_fixture
    protected = base / 'snapshot-20260911T000000000000Z'
    (protected / 'project').mkdir(parents=True)
    (protected / 'COMPLETE').touch()
    (protected / 'VERIFIED').touch()
    sentinel = protected / 'project' / 'user-baseline.bin'
    sentinel.write_bytes(b'never alter a verified recovery point')
    (base / 'latest').symlink_to(protected.name)
    snapshots.pull_snapshot(base, snapshot_id=identity)
    assert not (target / 'project' / 'data' / 'stale.bin').exists()
    retained = list((base / 'retained-unverified' / identity).rglob('stale.bin'))
    assert len(retained) == 1
    assert retained[0].read_bytes() == b'retain these old downloaded bytes'
    assert (target / 'VERIFIED').is_file()
    assert sentinel.read_bytes() == b'never alter a verified recovery point'
    assert (protected / 'VERIFIED').is_file()


@pytest.mark.parametrize('published', [False, True])
def test_verified_or_published_destination_is_not_deleted(pull_fixture, published):
    base, target, identity = pull_fixture
    if published:
        (base / 'latest').symlink_to(target.name)
    else:
        (target / 'COMPLETE').touch()
        (target / 'VERIFIED').touch()
    with pytest.raises(Exception, match='Runtime file checksum mismatch'):
        snapshots.pull_snapshot(base, snapshot_id=identity)
    assert (target / 'project' / 'data' / 'stale.bin').read_bytes() == b'retain these old downloaded bytes'
    assert not (base / 'retained-unverified').exists()
