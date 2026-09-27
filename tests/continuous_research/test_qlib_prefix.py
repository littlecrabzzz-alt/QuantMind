"""Synthetic byte-boundary checks. Never opens a real Qlib provider."""

import hashlib
import os
import struct
from unittest.mock import patch

import pytest

from scripts.continuous_research.qlib_prefix import feature_prefix


@pytest.mark.parametrize("start,cutoff,allowed", [(0, 1, 2), (7, 8, 2), (7, 7, 1)])
def test_never_reads_future_tail(tmp_path, start, cutoff, allowed):
    p = tmp_path / "close.day.bin"
    raw = struct.pack("<f", start) + struct.pack("<4f", 11, float("nan"), 9876, 5432)
    p.write_bytes(raw)
    read = os.read
    calls = []

    def bounded(fd, count):
        offset = os.lseek(fd, 0, os.SEEK_CUR)
        calls.append([offset, offset + count])
        assert offset + count <= 4 + 4 * allowed, "future bytes requested"
        return read(fd, count)

    with patch("os.read", bounded):
        payload, evidence = feature_prefix(p, cutoff)
    assert payload == raw[: 4 + 4 * allowed]
    assert calls == [[0, 4], [4, 4 + 4 * allowed]]
    assert evidence["end_index"] == cutoff
    assert evidence["sha256"] == hashlib.sha256(payload).hexdigest()
    assert evidence["identity_scope"] == "source_byte_range_only"
    assert p.read_bytes() == raw


def test_short_series_does_not_pad(tmp_path):
    p = tmp_path / "close.day.bin"
    raw = struct.pack("<3f", 5, 11, 12)
    p.write_bytes(raw)
    payload, evidence = feature_prefix(p, 99)
    assert payload == raw
    assert evidence["end_index"] == 6 and evidence["value_count"] == 2


@pytest.mark.parametrize("header", [float("nan"), float("inf"), -1, 1.5, 10])
def test_bad_or_future_header_rejects_before_value_read(tmp_path, header):
    p = tmp_path / "close.day.bin"
    p.write_bytes(struct.pack("<2f", header, 9876))
    read = os.read
    with patch("os.read", side_effect=read) as spy, pytest.raises(ValueError):
        feature_prefix(p, 8)
    assert [c.args[1] for c in spy.call_args_list] == [4]


@pytest.mark.parametrize("raw", [b"", b"abc", struct.pack("<f", 0), b"123456789"])
def test_malformed_length_rejected_without_read(tmp_path, raw):
    p = tmp_path / "close.day.bin"
    p.write_bytes(raw)
    with patch("os.read") as spy, pytest.raises(ValueError):
        feature_prefix(p, 8)
    spy.assert_not_called()


@pytest.mark.parametrize("cutoff", [-1, True, 1.0, "1"])
def test_invalid_cutoff_does_not_open(cutoff):
    with patch("os.open") as spy, pytest.raises(ValueError):
        feature_prefix("unused", cutoff)
    spy.assert_not_called()


def test_symlink_and_source_change_reject(tmp_path):
    p = tmp_path / "close.day.bin"
    p.write_bytes(struct.pack("<3f", 0, 11, 12))
    link = tmp_path / "alias"
    link.symlink_to(p)
    with pytest.raises(OSError):
        feature_prefix(link, 0)
    read = os.read

    def change(fd, count):
        value = read(fd, count)
        if os.lseek(fd, 0, os.SEEK_CUR) > 4:
            p.write_bytes(struct.pack("<4f", 0, 21, 22, 23))
        return value

    with patch("os.read", change), pytest.raises(ValueError, match="changed"):
        feature_prefix(p, 0)
