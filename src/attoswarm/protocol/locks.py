"""Simple file-lock helper using flock."""

from __future__ import annotations

import contextlib
import fcntl
from pathlib import Path
from typing import Iterator


@contextlib.contextmanager
def locked_file(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
