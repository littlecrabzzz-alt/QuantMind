"""Offline bounded provider candidate; never called by freeze/runtime.

Callers declare the original global calendar prefix and a required universe.
Declarations and observed file stability do NOT establish PIT, an atomic input
snapshot, source authenticity, or research admission. No directory discovery or
live fallback. Output is destination/provider, published only after completion.
"""

import bisect
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from scripts.continuous_research.qlib_prefix import feature_prefix


# Explicit offline contract matching QlibDataBuilder's CN binary fields.
FIELDS = frozenset(
    {"open", "high", "low", "close", "volume", "amount", "factor", "change"}
)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected strict ISO date")
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected strict ISO date")
    return value


def _names(values, label):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"Explicit nonempty {label} required")
    if any(
        not isinstance(v, str) or not re.fullmatch(r"[a-z0-9_]+", v) for v in values
    ):
        raise ValueError(f"Unsafe or noncanonical {label}")
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {label}")
    return list(values)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(parent, name, stack, directory_checks):
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    stack.callback(os.close, fd)
    info = os.fstat(fd)
    directory_checks.append((parent, name, (info.st_dev, info.st_ino)))
    return fd


def _absolute_directory(path, stack, directory_checks):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Absolute paths without parent traversal required")
    fd = os.open(path.anchor, DIR_FLAGS)
    stack.callback(os.close, fd)
    for part in path.parts[1:]:
        fd = _directory(fd, part, stack, directory_checks)
    return fd


def _unchanged(directory_checks, file_checks):
    for parent, name, expected in directory_checks:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != expected
        ):
            raise ValueError("Source/output parent directory replaced")
    for parent, name, expected in file_checks:
        if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
            raise ValueError("Source changed during provider construction")


def _calendar_prefix(parent, expected, file_checks):
    name = "day.txt"
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Calendar must be regular")
        # Exact byte prefix from offset zero, no readline/buffered tail prefetch.
        actual = os.read(fd, len(expected))
        if actual != expected:
            raise ValueError("Original global calendar prefix mismatch")
        if _identity(os.fstat(fd)) != _identity(before):
            raise ValueError("Calendar changed during prefix read")
        file_checks.append((parent, name, _identity(before)))
    finally:
        os.close(fd)
    return {
        "path": "calendars/day.txt",
        "identity_scope": "source_byte_range_only",
        "byte_range": [0, len(actual)],
        "sha256": hashlib.sha256(actual).hexdigest(),
    }


def _write(root_fd, relative, payload):
    """Exclusive writes under a newly owned staging directory."""
    with ExitStack() as stack:
        fd = root_fd
        for part in Path(relative).parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            fd = _directory(fd, part, stack, [])
        out = os.open(
            Path(relative).name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=fd,
        )
        stack.callback(os.close, out)
        remaining = memoryview(payload)
        while remaining:
            count = os.write(out, remaining)
            if count <= 0:
                raise OSError("Incomplete output write")
            remaining = remaining[count:]
        os.fsync(out)
        os.lseek(out, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        size = 0
        while block := os.read(out, 1024 * 1024):
            digest.update(block)
            size += len(block)
        if (
            size != len(payload)
            or digest.hexdigest() != hashlib.sha256(payload).hexdigest()
        ):
            raise OSError("Generated output verification failed")
    return {
        "path": relative,
        "identity_scope": "output_whole_file",
        "size": size,
        "sha256": digest.hexdigest(),
    }


def _remove_tree(parent, name):
    """Remove only our unpublished tree, anchored to the original parent fd."""
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        for item in os.listdir(fd):
            if stat.S_ISDIR(os.stat(item, dir_fd=fd, follow_symlinks=False).st_mode):
                _remove_tree(fd, item)
            else:
                os.unlink(item, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)


def build_provider(
    source: Path,
    destination: Path,
    *,
    calendar_prefix: list[str],
    cutoff: str,
    symbols: list[str],
    fields: list[str],
    lifetimes: dict[str, tuple[str, str]],
    benchmark: str | None,
    day_future_endpoint: str | None = None,
) -> dict:
    """Build an offline candidate from explicit declarations, never infer a pool.

    All symbols are mandatory. An explicitly selected future listing is an error,
    not silently filtered. Benchmark gets the same declared fields but is excluded
    from instruments/all.txt unless also explicitly in symbols. Lifetimes are
    caller declarations: no unbounded instruments file is opened to validate them.
    Paths must be absolute with no symlink components (including /tmp aliases).
    Existing destination, even empty, is never replaced.
    """
    source, destination = Path(source), Path(destination)
    for path in (source, destination):
        if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
            raise ValueError(
                "Absolute non-root paths without parent traversal required"
            )
    if (
        source in destination.parents
        or destination in source.parents
        or source == destination
    ):
        raise ValueError("Source and destination must be disjoint")
    if not isinstance(calendar_prefix, (list, tuple)) or not calendar_prefix:
        raise ValueError("Original global calendar prefix required")
    calendar = [_date(value) for value in calendar_prefix]
    if calendar != sorted(set(calendar)) or calendar[-1] != _date(cutoff):
        raise ValueError("Calendar must be ordered, unique and end at cutoff")
    symbols, fields = _names(symbols, "symbols"), _names(fields, "fields")
    if not set(fields) <= FIELDS:
        raise ValueError("Unknown field requested")
    if benchmark is not None:
        _names([benchmark], "benchmark")
    required = sorted(set(symbols + ([benchmark] if benchmark else [])))
    if not isinstance(lifetimes, dict) or set(lifetimes) != set(required):
        raise ValueError("Lifetimes must exactly cover required symbols and benchmark")
    declared, bounded = {}, {}
    for symbol in required:
        life = lifetimes[symbol]
        if not isinstance(life, (list, tuple)) or len(life) != 2:
            raise ValueError("Explicit lifetime pair required")
        start, end = map(_date, life)
        if start > end or start > cutoff or end < calendar[0]:
            raise ValueError(
                "Required symbol lifetime does not overlap allowed calendar"
            )
        lo, hi = (
            bisect.bisect_left(calendar, start),
            bisect.bisect_right(calendar, end) - 1,
        )
        if lo > hi:
            raise ValueError("Required symbol has no allowed calendar date")
        declared[symbol], bounded[symbol] = [start, end], [calendar[lo], calendar[hi]]
    if day_future_endpoint is not None and _date(day_future_endpoint) <= cutoff:
        raise ValueError("day_future endpoint must be strictly after cutoff")
    spec = {
        "calendar_prefix": calendar,
        "cutoff": cutoff,
        "symbols": symbols,
        "fields": fields,
        "lifetimes": declared,
        "benchmark": benchmark,
        "day_future_endpoint": day_future_endpoint,
    }
    encoded_spec = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    calendar_bytes = ("\n".join(calendar) + "\n").encode("ascii")
    directory_checks, file_checks, sources, outputs = [], [], [], []
    with ExitStack() as stack:
        root = _absolute_directory(source, stack, directory_checks)
        parent = _absolute_directory(destination.parent, stack, directory_checks)
        try:
            os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(str(destination))
        calendars = _directory(root, "calendars", stack, directory_checks)
        sources.append(_calendar_prefix(calendars, calendar_bytes, file_checks))
        features = _directory(root, "features", stack, directory_checks)
        temp_name = f".qlib-provider-{uuid.uuid4().hex}.tmp"
        os.mkdir(temp_name, mode=0o700, dir_fd=parent)
        reserved = False
        try:
            stage = _directory(parent, temp_name, stack, [])
            outputs.append(_write(stage, "calendars/day.txt", calendar_bytes))
            if day_future_endpoint:
                outputs.append(
                    _write(
                        stage,
                        "calendars/day_future.txt",
                        calendar_bytes + (day_future_endpoint + "\n").encode(),
                    )
                )
            for symbol in required:
                directory = _directory(features, symbol, stack, directory_checks)
                last_index = calendar.index(bounded[symbol][1])
                first_index = calendar.index(bounded[symbol][0])
                for field in fields:
                    name = field + ".day.bin"
                    before = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    payload, evidence = feature_prefix(
                        Path(name), last_index, dir_fd=directory
                    )
                    if evidence["start_index"] < first_index:
                        raise ValueError("Feature starts before declared lifetime")
                    file_checks.append((directory, name, _identity(before)))
                    relative = f"features/{symbol}/{name}"
                    sources.append({"path": relative, **evidence})
                    outputs.append(_write(stage, relative, payload))
            instruments = "".join(
                f"{s}\t{bounded[s][0]}\t{bounded[s][1]}\n" for s in symbols
            )
            outputs.append(
                _write(stage, "instruments/all.txt", instruments.encode("ascii"))
            )
            _unchanged(directory_checks, file_checks)
            manifest = {
                "schema": "offline_qlib_provider_v1",
                "status": "offline_candidate",
                "provider_path": str(destination / "provider"),
                "source_root": str(source),
                "declaration": spec,
                "declaration_sha256": hashlib.sha256(encoded_spec).hexdigest(),
                "bounded_lifetimes": bounded,
                "sources": sources,
                "outputs": outputs,
                "point_in_time_verified": False,
                "atomic_source_snapshot": False,
                "research_admitted": False,
                "endpoint_role": "interval_metadata_only_not_a_quote_or_trading_day",
            }
            _write(
                stage,
                "provider_manifest.json",
                (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(),
            )
            _unchanged(directory_checks, file_checks)
            # mkdir is an atomic no-clobber reservation; provider appears whole.
            os.mkdir(destination.name, mode=0o700, dir_fd=parent)
            reserved = True
            target = _directory(parent, destination.name, stack, [])
            os.rename(temp_name, "provider", src_dir_fd=parent, dst_dir_fd=target)
            reserved = False
            return manifest
        finally:
            try:
                _remove_tree(parent, temp_name)
            except FileNotFoundError:
                pass
            if reserved:
                os.rmdir(destination.name, dir_fd=parent)
