"""Opt-in, bounded lexical-index diagnostics. No source text or I/O is retained."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field

_CURRENT: ContextVar[IndexProbe | None] = ContextVar("index_probe", default=None)
_DISABLED = nullcontext()
# Exact call counts, but only one in 64 hot calls reads clocks. Sampled durations
# are reported as observations, never extrapolated into full-phase totals.
SAMPLED_PHASES = frozenset({"body.tokenize", "keyword.tokenize", "keyword.serialize"})
SAMPLE_EVERY = 64
PHASES = frozenset(
    {
        "keyword.discovery",
        "keyword.discovery_reuse",
        "keyword.stat",
        "keyword.cache_load",
        "keyword.files",
        "keyword.read",
        "keyword.hash_lookup",
        "keyword.parse",
        "keyword.spans",
        "keyword.documents",
        "keyword.frequencies",
        "keyword.cache_save",
        "keyword.tokenize",
        "keyword.serialize",
        "keyword.sql",
        "keyword.commit",
        "body.open",
        "body.revision",
        "body.discovery",
        "body.stat",
        "body.lock",
        "body.cache_load",
        "body.delete",
        "body.files",
        "body.read",
        "body.spans",
        "body.document",
        "body.tokenize",
        "body.sql",
        "body.commit",
    }
)
COUNTERS = frozenset(
    {
        "keyword.files_started",
        "keyword.discovery_reused",
        "keyword.files_completed",
        "keyword.read_chars",
        "keyword.documents",
        "body.files_started",
        "body.files_completed",
        "body.read_chars",
        "body.windows",
        "body.commits",
        "keyword.commits",
    }
)


@dataclass
class IndexProbe:
    """One warmup attempt, owned by its indexing thread; snapshots may be concurrent.

    Timings are inclusive (nested phases overlap). CPU covers the indexing thread
    only; active CPU cannot be sampled from another thread and is omitted. The
    wall-minus-CPU difference includes scheduling/I/O/waiting, not proven GIL time.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _phases: dict = field(default_factory=dict, repr=False)
    _counts: dict = field(default_factory=dict, repr=False)
    _active: list = field(default_factory=list, repr=False)
    _slow: list = field(default_factory=list, repr=False)
    _observed_calls: dict = field(default_factory=dict, repr=False)

    @contextmanager
    def measure(self, phase, file=None):
        if phase not in PHASES:
            raise ValueError("Unknown index phase")
        wall, cpu = time.monotonic(), time.thread_time()
        frame = (phase, wall)
        with self._lock:
            self._active.append(frame)
        try:
            yield
        finally:
            elapsed, used = time.monotonic() - wall, time.thread_time() - cpu
            with self._lock:
                self._active.remove(frame)
                row = self._phases.setdefault(
                    phase, {"calls": 0, "wall_seconds": 0.0, "thread_cpu_seconds": 0.0}
                )
                row["calls"] += 1
                row["wall_seconds"] += elapsed
                row["thread_cpu_seconds"] += used
                if file is not None:
                    self._slow.append(
                        {"phase": phase, "file": str(file)[:160], "wall_seconds": elapsed}
                    )
                    self._slow.sort(key=lambda r: r["wall_seconds"], reverse=True)
                    del self._slow[8:]

    def count(self, name, amount=1):
        if name not in COUNTERS:
            raise ValueError("Unknown index counter")
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + amount

    def sample_call(self, phase):
        if phase not in SAMPLED_PHASES:
            raise ValueError("Unknown sampled phase")
        with self._lock:
            seen = self._observed_calls.get(phase, 0) + 1
            self._observed_calls[phase] = seen
        return (seen - 1) % SAMPLE_EVERY == 0

    def snapshot(self):
        with self._lock:
            return {
                "schema": 2,
                "sampling": {
                    "every": SAMPLE_EVERY,
                    "phases": sorted(SAMPLED_PHASES),
                    "observed_calls": dict(self._observed_calls),
                    "timing": "sampled calls only; no extrapolation; phases.calls counts timed scopes",
                },
                "timing": "inclusive; completed scopes only; indexing-thread CPU",
                "counts_semantics": "attempted work, not committed rows; commits counted separately",
                "phases": {k: dict(v) for k, v in self._phases.items()},
                "counts": dict(self._counts),
                "slow_files": [dict(r) for r in self._slow],
                "active": [
                    {"phase": p, "wall_seconds": time.monotonic() - start}
                    for p, start in self._active
                ],
            }


@contextmanager
def activate(probe):
    token = _CURRENT.set(probe)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def measure(phase, file=None):
    probe = _CURRENT.get()
    return probe.measure(phase, file) if probe is not None else _DISABLED


def count(name, amount=1):
    probe = _CURRENT.get()
    if probe is not None:
        probe.count(name, amount)


def measured_call(phase, function, *args, **kwargs):
    with measure(phase):
        return function(*args, **kwargs)


def instrument(phase, function):
    probe = _CURRENT.get()
    if probe is None:
        return function
    if phase not in PHASES:
        raise ValueError("Unknown index phase")
    if phase in SAMPLED_PHASES:
        def sampled(*args, **kwargs):
            if probe.sample_call(phase):
                with probe.measure(phase):
                    return function(*args, **kwargs)
            return function(*args, **kwargs)
        return sampled
    from functools import partial

    return partial(measured_call, phase, function)


@contextmanager
def measured_lock(lock, phase):
    with measure(phase):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()
