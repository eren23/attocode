"""The source bytes used for one optional vector replacement."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileRevision:
    content: str
    sha256: str
    mtime_ns: int
    size: int
    ctime_ns: int
    mtime: float


def read_file_revision(path: str) -> FileRevision:
    """Read one stable descriptor, with a bounded retry for concurrent writes."""
    for _ in range(2):
        with open(path, 'rb') as source:
            before = os.fstat(source.fileno())
            raw = source.read()
            after = os.fstat(source.fileno())
        def identity(s):
            return s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino
        if identity(before) == identity(after) and len(raw) == after.st_size:
            return FileRevision(raw.decode('utf-8', errors='replace'),
                                hashlib.sha256(raw).hexdigest(), after.st_mtime_ns,
                                after.st_size, after.st_ctime_ns, after.st_mtime)
    raise OSError('Source changed during revision capture')
