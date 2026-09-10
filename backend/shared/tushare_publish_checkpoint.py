"""Private, opt-in publication spool. Never part of a released data inventory.

The pipeline lock belongs to the caller. Each committed journal describes one
frozen publication; no live database or credential is copied into this directory.
"""

import hashlib
import json
import os
from pathlib import Path
import re

from backend.shared.tushare_intake import json_bytes

NAME = "publish-staging"
RELEASE = re.compile(r"data-[a-f0-9]{64}")


def _path(root, name):
    root = Path(root)
    directory = root / NAME
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("Unsafe publication spool directory")
    path = directory / name
    if path.is_symlink():
        raise ValueError("Unsafe publication spool file")
    return path


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(root, name, raw):
    path = _path(root, name)
    path.parent.mkdir(exist_ok=True)
    _sync(path.parent.parent)
    temporary = _path(root, name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync(path.parent)


def load(root):
    path = _path(root, "checkpoint.json")
    if not path.exists():
        return None
    saved = json.loads(path.read_bytes())
    if (
        saved.get("version") != 1
        or saved.get("phase") not in ("content", "ready")
        or (
            saved.get("previous_id") is not None
            and not RELEASE.fullmatch(saved["previous_id"])
        )
        or not re.fullmatch(r"[a-f0-9]{64}", saved.get("content_sha256", ""))
        or type(saved.get("content_bytes")) is not int
        or saved["content_bytes"] < 1
        or type(saved.get("self_archive_verified")) is not bool
    ):
        raise ValueError("Invalid publication checkpoint")
    if saved["phase"] == "ready" and not RELEASE.fullmatch(saved.get("release_id", "")):
        raise ValueError("Invalid ready publication identity")
    return saved


def current(root):
    path = Path(root) / "CURRENT.json"
    if path.is_symlink():
        raise ValueError("Unsafe current pointer")
    if not path.exists():
        return None
    saved = json.loads(path.read_bytes())
    release = saved.get("release_id")
    if not isinstance(release, str):
        raise ValueError("Invalid current identity")
    if release.startswith("data-") and (
        not RELEASE.fullmatch(release) or saved.get("manifest_sha256") != release[5:]
    ):
        raise ValueError("Invalid current checksum identity")
    return release


def freeze(root, content, previous_id, self_archive_verified):
    if previous_id is not None and not RELEASE.fullmatch(previous_id):
        raise ValueError("Staged publication requires a data predecessor")
    raw = json_bytes(content)
    saved = {
        "version": 1,
        "phase": "content",
        "previous_id": previous_id,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_bytes": len(raw),
        "self_archive_verified": self_archive_verified,
    }
    _write(root, "content.json", raw)
    _write(root, "checkpoint.json", json_bytes(saved))
    return saved


def content(root, saved):
    raw = _path(root, "content.json").read_bytes()
    if (
        len(raw) != saved["content_bytes"]
        or hashlib.sha256(raw).hexdigest() != saved["content_sha256"]
    ):
        raise ValueError("Publication content checksum mismatch")
    return json.loads(raw)


def ready(root, saved, release_id):
    if not RELEASE.fullmatch(release_id):
        raise ValueError("Invalid publication release")
    saved = {**saved, "phase": "ready", "release_id": release_id}
    _write(root, "checkpoint.json", json_bytes(saved))
    return saved


def verify_ready(root, saved):
    release = saved["release_id"]
    path = Path(root) / "releases" / release / "manifest.json"
    if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
        raise ValueError("Unsafe ready manifest path")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != release[5:]:
        raise ValueError("Ready manifest checksum mismatch")
    if current(root) not in (saved["previous_id"], release):
        raise ValueError("Publication predecessor changed")
    return release


def clear(root):
    # Only our private staging files, after CURRENT already names the verified
    # release. A crash before journal removal resumes the ready phase safely.
    for name in ("content.json", "checkpoint.json"):
        _path(root, name).unlink(missing_ok=True)
    _sync(_path(root, "checkpoint.json").parent)
