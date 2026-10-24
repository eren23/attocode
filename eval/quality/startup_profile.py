"""Throwaway profile observation; never changes product work or cache policy."""
from __future__ import annotations

import cProfile
import hashlib
import itertools
import os
import pstats
import threading
import time
from pathlib import Path
from unittest.mock import patch

from eval.quality.runner import write_json

_ACTIVE = threading.Lock()


def profile_summary(path):
    stats = pstats.Stats(str(path))
    rows = [{'file': key[0], 'line': key[1], 'function': key[2], 'primitive_calls': value[0],
             'calls': value[1], 'self_seconds': value[2], 'cumulative_seconds': value[3]}
            for key, value in stats.stats.items()]
    return {'total_calls': stats.total_calls, 'total_seconds': stats.total_tt,
            'by_self': sorted(rows, key=lambda r: r['self_seconds'], reverse=True)[:100],
            'by_cumulative': sorted(rows, key=lambda r: r['cumulative_seconds'], reverse=True)[:100]}


def profile_call(path, task, function, *args, **kwargs):
    """Preserve each task's value/exception; flush raw stats before leaving its thread."""
    path = Path(path)
    if path.exists() or path.with_suffix('.json').exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _ACTIVE.acquire(blocking=False):
        raise RuntimeError('overlapping profile scopes would corrupt attribution')
    profiler, error = cProfile.Profile(), None
    started, cpu = time.monotonic_ns(), time.thread_time_ns()
    try:
        return profiler.runcall(function, *args, **kwargs)
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        finished, used_cpu = time.monotonic_ns(), time.thread_time_ns() - cpu
        _ACTIVE.release()
        profiler.dump_stats(str(path))
        summary = profile_summary(path)
        dumped = time.monotonic_ns()
        write_json(path.with_suffix('.json'), {
            'diagnostic_only': True, 'task': task, 'pid': os.getpid(),
            'thread_id': threading.get_ident(), 'native_thread_id': threading.get_native_id(),
            'status': 'failed' if error else 'passed', 'error_type': error,
            'started_ns': started, 'finished_ns': finished, 'profile_dump_finished_ns': dumped,
            'scope_wall_seconds': (finished - started) / 1e9, 'thread_cpu_seconds': used_cpu / 1e9,
            'profile_serialization_seconds': (dumped - finished) / 1e9,
            'profile_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), **summary})


class WorkspaceProfiles:
    """Observe the actual serial workspace executor, including warmup and close."""
    def __init__(self, evidence):
        self.evidence = Path(evidence)
        self.sequence = itertools.count()

    def __enter__(self):
        from attocode_intel import gateway

        observer = self

        class ProfiledExecutor(gateway.ThreadPoolExecutor):
            def submit(self, function, *args, **kwargs):
                number = next(observer.sequence)
                name = getattr(function, '__qualname__', str(function))
                if args and callable(args[0]):
                    name = getattr(args[0], '__qualname__', name)
                    if len(args) > 2 and isinstance(args[2], str):
                        name += ':' + args[2]

                def observed():
                    return profile_call(observer.evidence / f'task-{number:04d}.prof',
                                        name, function, *args, **kwargs)

                return super().submit(observed)

        self.patcher = patch.object(gateway, 'ThreadPoolExecutor', ProfiledExecutor)
        self.patcher.start()
        return self

    def __exit__(self, *exc):
        self.patcher.stop()
