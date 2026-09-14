"""Opt-in timings outside model responses; never writes source or arguments."""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

timings: ContextVar[dict | None] = ContextVar("intelligence_timings", default=None)


@contextmanager
def measure(name):
    start = time.monotonic()
    try:
        yield
    finally:
        current = timings.get()
        if current is not None:
            current[name] = round(current.get(name, 0) + (time.monotonic() - start) * 1000, 2)


def enabled():
    return bool(os.environ.get("ATTOCODE_INTEL_TRACE"))


def emit(event: dict) -> None:
    destination = os.environ.get("ATTOCODE_INTEL_TRACE")
    if not destination:
        return
    try:
        path = Path(destination).expanduser()
        if not path.is_absolute():
            return
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
    except OSError:
        logging.getLogger(__name__).warning("Could not write intelligence timing trace")
