"""Durable, bounded experiment observations and explicit source identity checks."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


class Journal:
    """One writer/attempt; retain each response once, before calling validators.

    A flushed event references an already fsynced content-addressed blob. A crash
    may leave an unreferenced blob, which is evidence, never a completed event.
    """
    def __init__(self, root, max_bytes):
        if type(max_bytes) is not int or max_bytes < 1024:
            raise ValueError('evidence limit must be at least 1024 bytes')
        self.root, self.max_bytes = Path(root), max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or any(self.root.iterdir()):
            raise ValueError('refusing nonempty or symlink journal')
        (self.root / 'blobs').mkdir()
        (self.root / 'events.jsonl').touch(exist_ok=False)
        self.bytes = 0

    def response(self, request, value):
        raw = encode(value)
        sha = hashlib.sha256(raw).hexdigest()
        relative = f'blobs/{sha}.json'
        path = self.root / relative
        ref = {'path': relative, 'sha256': sha, 'bytes': len(raw)}
        event = encode({'request': request, 'response': ref})
        extra = len(event) + (0 if path.exists() else len(raw))
        if self.bytes + extra > self.max_bytes:
            raise RuntimeError('evidence_budget')
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('evidence blob identity changed')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        with (self.root / 'events.jsonl').open('ab') as stream:
            stream.write(event)
            stream.flush()
            os.fsync(stream.fileno())
        self.bytes += extra
        return ref


def read_source(path, *, errors, newlines):
    """Callers declare the policy of the operation that produced the text."""
    if errors not in {'strict', 'replace'} or newlines not in {'raw', 'universal'}:
        raise ValueError('unsupported source policy')
    with Path(path).open('r', encoding='utf-8', errors=errors,
                         newline='' if newlines == 'raw' else None) as stream:
        return stream.read()


def validate_excerpt(source, snippet, start, end):
    if not isinstance(snippet, str):
        raise ValueError('snippet must be text')
    if source is None:
        if snippet or start is not None or end is not None:
            raise ValueError('source unavailable: cannot claim an excerpt')
        return {'kind': 'metadata_only'}
    if not isinstance(source, str):
        raise ValueError('source must be decoded text')
    lines = source.splitlines(keepends=True)
    if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)
            or not snippet or len(snippet.splitlines()) != end - start + 1):
        raise ValueError('invalid excerpt coordinates')
    if snippet not in ''.join(lines[start - 1:end]):
        raise ValueError('excerpt does not match source coordinates')
    return {'kind': 'source', 'start_line': start, 'end_line': end}


def assert_engine(root):
    """Check selected package AND every loaded child, in each process using it."""
    root = Path(root).resolve()
    importlib.import_module('attocode_intel')
    origins = {}
    for name, module in list(sys.modules.items()):
        if name == 'attocode_intel' or name.startswith('attocode_intel.'):
            path = getattr(module, '__file__', None)
            if path is None or not Path(path).resolve().is_relative_to(root):
                raise ValueError(f'engine_origin: {name} is outside selected package {root}')
            origins[name] = str(Path(path).resolve().relative_to(root))
    return origins
