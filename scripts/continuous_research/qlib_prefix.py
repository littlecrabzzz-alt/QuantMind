"""Offline candidate for bounded Qlib feature reads; not a provider publisher.

Caller must supply an index from the unchanged global calendar and select the
source/field explicitly. This helper proves neither PIT nor provider admission.
No production freeze/runtime path calls it yet.
"""

import hashlib
import math
import os
import stat
import struct
from pathlib import Path


def feature_prefix(source: Path, cutoff_index: int) -> tuple[bytes, dict]:
    """Read header + allowed float32 values without reading or hashing the future tail.

    Short series retain their real endpoint; missing values retain their bits.
    The final component cannot be a symlink. Parent path ownership and calendar,
    symbol, field and lifecycle validation belong to the future package caller.
    """
    if type(cutoff_index) is not int or cutoff_index < 0:
        raise ValueError("cutoff_index must be a nonnegative global calendar index")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 8 or before.st_size % 4:
            raise ValueError("Expected regular Qlib header plus whole float32 values")
        # os.read is deliberately unbuffered: BufferedReader may prefetch the tail.
        header = os.read(fd, 4)
        if len(header) != 4:
            raise ValueError("Incomplete Qlib start index")
        start = struct.unpack("<f", header)[0]
        if not math.isfinite(start) or start < 0 or not start.is_integer():
            raise ValueError("Invalid Qlib start index")
        start = int(start)
        if start > cutoff_index:
            raise ValueError("Feature starts after cutoff; no values are admissible")
        count = min((before.st_size - 4) // 4, cutoff_index - start + 1)
        values = os.read(fd, count * 4)
        if len(values) != count * 4:
            raise ValueError("Source truncated during prefix read")
        after = os.fstat(fd)
        current = os.stat(source, follow_symlinks=False)
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

        if identity(before) != identity(after) or identity(before) != identity(current):
            raise ValueError("Source changed during prefix read")
    finally:
        os.close(fd)
    payload = header + values
    return payload, {
        "identity_scope": "source_byte_range_only",
        "byte_range": [0, len(payload)],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "start_index": start,
        "end_index": start + count - 1,
        "cutoff_index": cutoff_index,
        "value_count": count,
    }
