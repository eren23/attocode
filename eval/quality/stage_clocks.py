"""Temporary bounded stage clocks; preserve callable work, values and exceptions."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import sys
import threading
import time
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from eval.quality.runner import REPO, write_json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def describe(function):
    code = getattr(function, '__code__', None)
    filename = getattr(code, 'co_filename', None)
    if filename:
        try:
            filename = Path(filename).resolve().relative_to(REPO).as_posix()
        except (OSError, ValueError):
            filename = str(filename)
    return {'module': getattr(function, '__module__', None),
            'qualname': getattr(function, '__qualname__', type(function).__qualname__),
            'file': filename, 'line': getattr(code, 'co_firstlineno', None)}


class StageClocks:
    def __init__(self, directory, *, max_records=20000, max_bytes=8 * 2**20):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stream = (self.directory / 'spans.jsonl').open('xb')
        self.max_records, self.max_bytes = max_records, max_bytes
        self.lock, self.local = threading.RLock(), threading.local()
        self.sequence = self.written = self.bytes = 0
        self.active, self.errors, self.tasks, self.targets = set(), [], [], {}
        self.publication_wall_ns = self.publication_cpu_ns = 0
        self.closed = False

    def _error(self, message):
        with self.lock:
            if message not in self.errors and len(self.errors) < 64:
                self.errors.append(message)

    def _target(self, function):
        key = id(function)
        with self.lock:
            if key not in self.targets:
                try:
                    metadata = describe(function)
                except BaseException as error:
                    self._error('callable metadata: ' + type(error).__name__)
                    metadata = {'module': None, 'qualname': 'unavailable', 'file': None, 'line': None}
                self.targets[key] = (function, metadata)
            return self.targets[key][1]

    def _write(self, raw):
        self.stream.write(raw)
        self.stream.flush()

    def call(self, label, function, /, *args, **kwargs):
        # Metadata and wrapper setup occur outside the measured child, inside its parent.
        target = self._target(function)
        stack = getattr(self.local, 'stack', None)
        if stack is None:
            stack = self.local.stack = []
        with self.lock:
            number = self.sequence
            self.sequence += 1
            self.active.add(number)
        parent = stack[-1] if stack else None
        stack.append(number)
        profiled = sys.getprofile() is not None
        started, cpu_start = time.monotonic_ns(), time.thread_time_ns()
        error = None
        try:
            return function(*args, **kwargs)
        except BaseException as failure:
            error = type(failure).__name__
            raise
        finally:
            cpu_end, finished = time.thread_time_ns(), time.monotonic_ns()
            profiled |= sys.getprofile() is not None
            row = {'id': number, 'parent': parent, 'label': label, 'target': target,
                   'pid': os.getpid(), 'thread_id': threading.get_ident(),
                   'native_thread_id': threading.get_native_id(), 'started_ns': started,
                   'finished_ns': finished, 'cpu_start_ns': cpu_start, 'cpu_end_ns': cpu_end,
                   'status': 'failed' if error else 'passed', 'error_type': error,
                   'profile_active': profiled}
            publish_start, publish_cpu = time.monotonic_ns(), time.thread_time_ns()
            try:
                with self.lock:
                    require(stack.pop() == number, 'non-LIFO stage stack')
                    self.active.remove(number)
                    require(self.written < self.max_records, 'stage record bound exceeded')
                    raw = (json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n').encode()
                    require(self.bytes + len(raw) <= self.max_bytes, 'stage byte bound exceeded')
                    self._write(raw)
                    self.written += 1
                    self.bytes += len(raw)
            except BaseException as observer_error:
                self._error(type(observer_error).__name__ + ': ' + str(observer_error)[:500])
            finally:
                with self.lock:
                    self.publication_wall_ns += time.monotonic_ns() - publish_start
                    self.publication_cpu_ns += time.thread_time_ns() - publish_cpu

    def close(self):
        with self.lock:
            require(not self.active, 'active stages prevent completion')
            require(not self.closed, 'stage recorder already closed')
            self.stream.close()
            self.closed = True
            raw = (self.directory / 'spans.jsonl').read_bytes()
            manifest = {'complete': not self.errors, 'errors': self.errors, 'pid': os.getpid(),
                        'submitted_spans': self.sequence, 'records': self.written, 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'tasks': self.tasks,
                        'max_records': self.max_records, 'max_bytes': self.max_bytes,
                        'publication_wall_ns': self.publication_wall_ns,
                        'publication_cpu_ns': self.publication_cpu_ns,
                        'publication_scope': 'Completed-row serialization/locking/flush only; not all wrapper or clock-read overhead.'}
            write_json(self.directory / 'manifest.json', manifest)
            require(manifest['complete'], 'stage observation incomplete: ' + str(self.errors))
            admit_records(self.directory, manifest)
            return manifest


def admit_records(directory, manifest):
    raw = (Path(directory) / 'spans.jsonl').read_bytes()
    require(manifest['complete'] and not manifest['errors'], 'incomplete stage manifest')
    require(len(raw) == manifest['bytes'] <= manifest['max_bytes']
            and hashlib.sha256(raw).hexdigest() == manifest['sha256'], 'stage bytes changed')
    require(not raw or raw.endswith(b'\n'), 'partial stage row')
    rows = [json.loads(line) for line in raw.splitlines()]
    require(len(rows) == manifest['records'] == manifest['submitted_spans'] <= manifest['max_records'], 'stage inventory differs')
    by_id = {row['id']: row for row in rows}
    require(set(by_id) == set(range(len(rows))) and len(by_id) == len(rows), 'stage IDs differ')
    children = defaultdict(list)
    for row in rows:
        require(row['pid'] == manifest['pid'] and type(row['thread_id']) is int
                and type(row['native_thread_id']) is int, 'stage process/thread differs')
        require(all(type(row[key]) is int and row[key] > 0 for key in
                    ('started_ns', 'finished_ns', 'cpu_start_ns', 'cpu_end_ns')), 'invalid clock type')
        require(row['finished_ns'] > row['started_ns'] and row['cpu_end_ns'] >= row['cpu_start_ns']
                and row['profile_active'] is False, 'invalid stage clock/profile')
        require(row['status'] in ('passed', 'failed')
                and ((row['error_type'] is None) == (row['status'] == 'passed')), 'stage outcome differs')
        thread = row['thread_id'], row['native_thread_id']
        parent = row['parent']
        if parent is not None:
            require(type(parent) is int and parent < row['id'] and parent in by_id, 'invalid stage parent')
            outer = by_id[parent]
            require((outer['thread_id'], outer['native_thread_id']) == thread
                    and outer['started_ns'] <= row['started_ns'] < row['finished_ns'] <= outer['finished_ns']
                    and outer['cpu_start_ns'] <= row['cpu_start_ns'] <= row['cpu_end_ns'] <= outer['cpu_end_ns'], 'stage escapes parent')
        children[(thread, parent)].append(row)
    for siblings in children.values():
        siblings.sort(key=lambda row: row['started_ns'])
        require(all(a['finished_ns'] <= b['started_ns'] and a['cpu_end_ns'] <= b['cpu_start_ns']
                    for a, b in zip(siblings, siblings[1:], strict=False)), 'same-thread stages overlap')
    for task in manifest['tasks']:
        selected = [row for row in rows if row['label'] == task['label']]
        require(len(selected) == 1 and selected[0]['parent'] is None
                and task['submitted_ns'] <= selected[0]['started_ns']
                and selected[0]['status'] == task['status'] and selected[0]['error_type'] == task['error_type'], 'executor future/span differs')
    return rows


def hook_targets():
    from attocode_intel._internal.integrations.context import (
        ast_service,
        ast_snapshot,
        codebase_ast,
        codebase_context,
        cross_references,
        index_repair,
    )

    return [
        *[(f'ast.{name}', ast_service.ASTService, name) for name in (
            'initialize_skeleton', '_snapshot_identity', '_restore_snapshot', '_save_snapshot', '_run_hydration')],
        ('discovery', codebase_context.CodebaseContextManager, 'discover_files'),
        ('summary.restore', ast_snapshot, 'restore_summaries'),
        ('summary.encode', ast_snapshot, 'encode_summaries'),
        ('index.load', cross_references.CrossRefIndex, 'load_from_store'),
        ('index.persist', cross_references.CrossRefIndex, 'persist_files'),
        ('index.repair', index_repair, 'repair_index'),
        ('graph.discovery', codebase_context, 'build_dependency_graph'),
        ('graph.repair', index_repair, 'build_dependency_graph'),
        ('parse.service', ast_service, 'parse_file'),
        ('parse.module', codebase_ast, 'parse_file'),
    ]


class WorkspaceStages:
    def __init__(self, clocks, *, targets=None):
        self.clocks, self.targets = clocks, targets
        self.pending, self.stack = [], ExitStack()

    def __enter__(self):
        from attocode_intel import gateway

        clocks, pending = self.clocks, self.pending
        self.targets = hook_targets() if self.targets is None else self.targets
        for label, owner, name in self.targets:
            original = getattr(owner, name)

            def wrapped(*args, _label=label, _original=original, **kwargs):
                return clocks.call(_label, _original, *args, **kwargs)

            self.stack.enter_context(patch.object(owner, name, functools.wraps(original)(wrapped)))

        class TimedExecutor(gateway.ThreadPoolExecutor):
            def submit(self, function, *args, **kwargs):
                number = len(pending)
                target = args[0] if args and callable(args[0]) else function
                name = getattr(target, '__qualname__', type(target).__qualname__)
                if len(args) > 2 and isinstance(args[2], str):
                    name += ':' + args[2]
                label = f'executor:{number:04d}:' + name
                submitted = time.monotonic_ns()
                future = super().submit(lambda: clocks.call(label, function, *args, **kwargs))
                pending.append(({'sequence': number, 'label': label, 'target': describe(target),
                                 'submitted_ns': submitted}, future))
                return future

        self.stack.enter_context(patch.object(gateway, 'ThreadPoolExecutor', TimedExecutor))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        for declared, future in self.pending:
            record = dict(declared)
            if not future.done() or future.cancelled():
                self.clocks._error('unfinished or cancelled executor task')
                record.update(status='incomplete', error_type=None)
            else:
                failure = future.exception()
                record.update(status='failed' if failure else 'passed',
                              error_type=type(failure).__name__ if failure else None)
            self.clocks.tasks.append(record)
        return False
