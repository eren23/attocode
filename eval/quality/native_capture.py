"""Opt-in OCaml fixture evidence; observation must never replace a native result."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from eval.quality.native_experiment import ParserObserver
from eval.quality.runner import REPO

MAX_BYTES = 4 * 2**20
EVENT_BYTES = 64 * 2**10
FOOTER_BYTES = 4096
_ACTIVE = threading.Lock()
_COUNTERS = ('parse_calls', 'native_failures', 'capture_errors', 'dropped_events',
             'oversized_events', 'protocol_errors', 'unfinished_parsers')


def fixture_identity(spec):
    return {key: spec.get(key) for key in ('id', 'repo', 'commit', 'language', 'file', 'source_sha256')}


def source_identity():
    from attocode_intel._internal.integrations.context import ts_parser

    paths = {name: REPO / name for name in (
        'eval/quality/native_capture.py', 'eval/quality/native_experiment.py',
        'eval/quality/corpus.py', 'eval/quality/corpus_capture.py')}
    paths['packages/code-intel/src/attocode_intel/_internal/integrations/context/ts_parser.py'] = Path(ts_parser.__file__)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def encode(value):
    return (json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()


class NativeCapture:
    def __init__(self, path, workspace, spec, *, max_bytes=MAX_BYTES, event_bytes=EVENT_BYTES):
        if type(max_bytes) is not int or not 8192 <= max_bytes <= MAX_BYTES:
            raise ValueError('native capture byte limit must be between 8192 and 4MiB')
        if type(event_bytes) is not int or not 1024 <= event_bytes <= EVENT_BYTES:
            raise ValueError('native capture event limit must be between 1024 and 64KiB')
        self.path = Path(path) if path is not None else None
        self.workspace, self.spec = Path(workspace).resolve(), spec
        self.max_bytes = max_bytes
        available = max_bytes - FOOTER_BYTES
        self.prefix_limit = available * 3 // 4
        self.tail_limit = available - self.prefix_limit
        self.event_bytes = min(event_bytes, self.tail_limit)
        self._file = None
        self._lock = threading.RLock()
        self._tail = deque()
        self._prefix_bytes = self._tail_bytes = self._index = 0
        self._overflow = self._sink_failed = self._closed = self._footer_written = False
        self._pending = {}
        self.worker_error = None
        self.parse_calls = self.native_failures = self.capture_errors = 0
        self.dropped_events = self.oversized_events = self.protocol_errors = 0

    def _io_failure(self):
        self.capture_errors += 1
        self._sink_failed = True

    def _flush(self):
        self._file.flush()
        os.fsync(self._file.fileno())

    def _checkpoint(self):
        if self._sink_failed:
            return
        self._file.seek(self._prefix_bytes)
        self._file.truncate()
        self._file.writelines(self._tail)
        self._flush()

    def _emit(self, kind, *, failure=False, **values):
        self._index += 1
        envelope = {'kind': kind, 'index': self._index, 'monotonic_ns': time.monotonic_ns()}
        raw = encode({**values, **envelope})
        if kind != 'trace_start' and len(raw) > self.event_bytes:
            self.oversized_events += 1
            raw = encode({**envelope, 'kind': 'omitted', 'bytes': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest()})
        if not self._overflow and self._prefix_bytes + len(raw) <= self.prefix_limit:
            if not self._sink_failed:
                self._file.write(raw)
                self._prefix_bytes += len(raw)
                self._flush()
        else:
            self._overflow = True
            self._tail.append(raw)
            self._tail_bytes += len(raw)
            while self._tail_bytes > self.tail_limit:
                self._tail_bytes -= len(self._tail.popleft())
                self.dropped_events += 1
            if failure:
                self._checkpoint()

    def record(self, _request, value):
        """Protected callback: original parser return/raise/reset always wins."""
        with self._lock:
            if self._closed or self._file is None:
                return
            try:
                stage = value['stage']
                key = value.get('parser_id'), value['thread_id']
                if stage == 'timeout_set':
                    self.protocol_errors += int(key in self._pending)
                    self._pending[key] = 'timeout'
                elif stage == 'parse':
                    self.protocol_errors += int(self._pending.get(key) != 'timeout')
                    self._pending[key] = 'parse'
                    self.parse_calls += 1
                    self.native_failures += int(value['outcome'] != 'tree')
                elif stage == 'reset':
                    self.protocol_errors += int(self._pending.pop(key, None) != 'parse')
                self._emit('native', native=value,
                           failure=stage == 'parse' and value['outcome'] != 'tree')
            except Exception:
                self._io_failure()

    def _counts(self):
        return {**{key: getattr(self, key) for key in _COUNTERS if key != 'unfinished_parsers'},
                'unfinished_parsers': len(self._pending), 'worker_error': self.worker_error}

    def summary(self):
        if self.path is None:
            return {'status': 'disabled', 'bytes': 0, **self._counts()}
        try:
            size = self.path.stat().st_size
        except OSError:
            size = None
        complete = self._closed and self._footer_written and size is not None and not any(
            self._counts()[key] for key in _COUNTERS if key not in {'parse_calls', 'native_failures'})
        return {'status': 'complete' if complete else 'incomplete', 'bytes': size, **self._counts()}

    def _finish(self):
        with self._lock:
            if self._file is None:
                self._closed = True
                return
            try:
                if not self._sink_failed:
                    self._checkpoint()
                    counts = self._counts()
                    good = not any(counts[key] for key in _COUNTERS if key not in {'parse_calls', 'native_failures'})
                    footer = encode({'kind': 'trace_end', 'index': self._index + 1,
                                     'monotonic_ns': time.monotonic_ns(),
                                     'status': 'complete' if good else 'incomplete', **counts})
                    if len(footer) > FOOTER_BYTES:
                        raise ValueError('native capture footer overflow')
                    self._file.write(footer)
                    self._flush()
                    self._footer_written = True
            except Exception:
                self._io_failure()
            finally:
                try:
                    self._file.close()
                except Exception:
                    self._io_failure()
                self._file = None
                self._closed = True

    @contextmanager
    def capture(self):
        if self.path is None:
            yield self
            return
        if not _ACTIVE.acquire(blocking=False):
            raise ValueError('an OCaml fixture capture is already active')
        try:
            from attocode_intel._internal.integrations.context import ts_parser

            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open('xb')
            self._emit('trace_start', schema_version=1, workspace=str(self.workspace),
                       fixture=fixture_identity(self.spec), sources=source_identity(),
                       runtime={'pid': os.getpid(), 'python': sys.version, 'platform': platform.platform()},
                       limits={'max_bytes': self.max_bytes, 'event_bytes': self.event_bytes,
                               'prefix_bytes': self.prefix_limit, 'tail_bytes': self.tail_limit})
            original, proxies = ts_parser._get_parser, {}

            def get_parser(language):
                parser = original(language)
                if language != 'ocaml':
                    return parser
                key = id(parser), threading.get_ident()
                with self._lock:
                    if parser is None:
                        self.record({'event': 'native'}, {'stage': 'lookup', 'available': False,
                                    'language': language, 'thread_id': key[1]})
                        return None
                    if key not in proxies:
                        proxies[key] = ParserObserver(parser, self.record, language)
                        self.record({'event': 'native'}, {'stage': 'lookup', 'available': True,
                                    'language': language, 'parser_id': key[0], 'thread_id': key[1]})
                    return proxies[key]

            with patch.object(ts_parser, '_get_parser', get_parser):
                try:
                    yield self
                except BaseException as error:
                    self.worker_error = {'type': type(error).__name__, 'message': str(error)[:256]}
                    try:
                        with self._lock:
                            self._emit('worker_error', error=self.worker_error, failure=True)
                    except Exception:
                        self._io_failure()
                    raise
        finally:
            self._finish()
            _ACTIVE.release()

    def require_complete(self):
        summary = self.summary()
        if summary['status'] == 'disabled':
            return summary
        return read_capture(self.path, self.workspace, self.spec, summary)


def read_capture(path, workspace, spec, producer_summary):
    """Admit raw bytes AND final close status; completeness is not native success."""
    def require(condition, message):
        if not condition:
            raise ValueError('native capture: ' + message)

    require(isinstance(producer_summary, dict) and producer_summary.get('status') == 'complete',
            'missing/incomplete final producer summary')
    path = Path(path)
    try:
        require(0 < path.stat().st_size <= MAX_BYTES, 'file size')
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError('native capture: missing artifact') from error
    require(raw.endswith(b'\n') and len(raw) == producer_summary.get('bytes'), 'partial/changed bytes')
    try:
        lines = raw.splitlines()
        data = [json.loads(line) for line in lines]
        header, footer = data[0], data[-1]
        require(header['kind'] == 'trace_start' and type(header['schema_version']) is int and header['schema_version'] == 1
                and footer['kind'] == 'trace_end' and footer['status'] == 'complete', 'header/footer')
        require(header['workspace'] == str(Path(workspace).resolve())
                and header['fixture'] == fixture_identity(spec) and header['sources'] == source_identity(),
                'source/fixture/workspace mismatch')
        limits = header['limits']
        require(type(limits['max_bytes']) is int and 8192 <= limits['max_bytes'] <= MAX_BYTES
                and len(raw) <= limits['max_bytes']
                and limits['prefix_bytes'] == (limits['max_bytes'] - FOOTER_BYTES) * 3 // 4
                and limits['tail_bytes'] == limits['max_bytes'] - FOOTER_BYTES - limits['prefix_bytes']
                and type(limits['event_bytes']) is int and 0 < limits['event_bytes'] <= min(EVENT_BYTES, limits['tail_bytes']),
                'limits')
        require(type(header['runtime']['pid']) is int and header['runtime']['pid'] > 0, 'process identity')
        for key in _COUNTERS:
            require(type(footer[key]) is int and type(producer_summary.get(key)) is int and footer[key] >= 0
                    and footer[key] == producer_summary.get(key), 'final counter mismatch')
            if key not in {'parse_calls', 'native_failures'}:
                require(footer[key] == 0, 'lost/unfinished capture')
        require(footer['worker_error'] == producer_summary.get('worker_error'), 'worker outcome mismatch')
        states, parses, failures, selected, worker_error = {}, 0, 0, 0, None
        previous = -1
        for number, (line, row) in enumerate(zip(lines, data, strict=True), 1):
            require(type(row['index']) is int and row['index'] == number
                    and type(row['monotonic_ns']) is int and row['monotonic_ns'] >= previous, 'order/clock')
            previous = row['monotonic_ns']
            if row['kind'] == 'trace_start':
                require(number == 1 and len(line) + 1 <= limits['prefix_bytes'], 'header position/size')
            elif row['kind'] == 'trace_end':
                require(number == len(data) and len(line) + 1 <= FOOTER_BYTES, 'footer position/size')
            elif row['kind'] == 'worker_error':
                require(worker_error is None and len(line) + 1 <= limits['event_bytes'], 'worker error event')
                worker_error = row['error']
                require(isinstance(worker_error, dict) and isinstance(worker_error['type'], str)
                        and isinstance(worker_error['message'], str) and len(worker_error['message']) <= 256,
                        'worker error shape')
            else:
                require(row['kind'] == 'native' and len(line) + 1 <= limits['event_bytes'], 'omitted/unknown event')
                native = row['native']
                require(type(native['thread_id']) is int and native['thread_id'] > 0, 'thread identity')
                if native['stage'] == 'lookup' and native['available'] is False:
                    require(native['language'] == 'ocaml', 'lookup language')
                    continue
                key = native['parser_id'], native['thread_id']
                require(type(key[0]) is int and key[0] > 0, 'parser identity')
                if native['stage'] == 'lookup':
                    require(native['available'] is True and native['language'] == 'ocaml' and key not in states, 'lookup')
                    states[key] = 'idle'
                elif native['stage'] == 'timeout_set':
                    require(states.get(key) == 'idle' and type(native['value']) is int
                            and native['value'] == 100_000, 'timeout/state')
                    states[key] = 'timeout'
                elif native['stage'] == 'parse':
                    require(states.get(key) == 'timeout' and native['language'] == 'ocaml'
                            and type(native['bytes']) is int and native['bytes'] >= 0
                            and type(native['limit_micros']) is int and native['limit_micros'] == 100_000
                            and isinstance(native['source_sha256'], str) and len(native['source_sha256']) == 64
                            and all(c in '0123456789abcdef' for c in native['source_sha256'])
                            and all(type(native[k]) is int and native[k] >= 0 for k in ('wall_ns', 'thread_cpu_ns')),
                            'parse source/clocks/state')
                    if native['error'] is None:
                        require(native['outcome'] in {'tree', 'no_tree'}, 'native outcome')
                    else:
                        require(native['error']['type'] == native['outcome']
                                and isinstance(native['error']['message'], str) and len(native['error']['message']) <= 2000,
                                'native exception')
                    states[key] = 'parse'
                    parses += 1
                    failures += int(native['outcome'] != 'tree')
                    selected += int(native['source_sha256'] == spec.get('source_sha256'))
                elif native['stage'] == 'reset':
                    require(states.get(key) == 'parse', 'reset/state')
                    states[key] = 'idle'
                else:
                    raise ValueError('native capture: unknown native stage')
        require(all(s == 'idle' for s in states.values()) and parses == footer['parse_calls']
                and failures == footer['native_failures'] and worker_error == footer['worker_error'], 'lifecycle/counts')
        return {**producer_summary, 'selected_source_parses': selected, 'source_verified': True,
                'worker_pid': header['runtime']['pid']}
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('native capture: malformed artifact') from error
