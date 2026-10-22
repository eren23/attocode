"""Opt-in evidence for the synthetic real-server CI fixture, never product tracing.

Retain a flushed startup prefix and a bounded recent tail. A complete capture has
a footer; a killed worker leaves an explicitly incomplete, readable prefix.
Observe the existing stderr consumer without reading the pipe independently.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


class LSPTrace:
    def __init__(self, path: Path | None, root_uri: str, *,
                 max_bytes: int = 4 * 2**20, event_bytes: int = 64 * 2**10):
        if max_bytes < 8192 or event_bytes < 1024:
            raise ValueError("Trace limits must leave room for identity and outcome")
        self.path, self.root_uri = path, root_uri
        self.max_bytes = max_bytes
        available = max_bytes - 4096  # Reserve a separately bounded footer.
        self.prefix_limit = available * 3 // 4
        self.tail_limit = available - self.prefix_limit
        self.event_bytes = min(event_bytes, self.tail_limit)
        self._prefix_bytes = self._tail_bytes = self._index = 0
        self._overflow = False
        self._tail: deque[bytes] = deque()
        self._stage = "setup"
        self._file = None
        self._lock = threading.RLock()
        self.dropped_events = self.oversized_events = self.capture_errors = 0
        self.first_failure = None

    @staticmethod
    def _encode(value):
        return (json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode()

    def record(self, kind, **data):
        if self._file is None:
            return
        with self._lock:
            self._index += 1
            envelope = {"kind": kind, "index": self._index, "stage": self._stage,
                        "monotonic": time.monotonic()}
            try:
                raw = self._encode({**data, **envelope})
                if len(raw) > self.event_bytes:
                    self.oversized_events += 1
                    raw = self._encode({**envelope, "payload_omitted": {
                        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}})
                if not self._overflow and self._prefix_bytes + len(raw) <= self.prefix_limit:
                    self._file.write(raw)
                    self._file.flush()
                    self._prefix_bytes += len(raw)
                else:
                    self._overflow = True
                    self._tail.append(raw)
                    self._tail_bytes += len(raw)
                    while self._tail_bytes > self.tail_limit:
                        self._tail_bytes -= len(self._tail.popleft())
                        self.dropped_events += 1
            except Exception:
                # Instrumentation must not interrupt a protocol operation. The
                # footer exposes this loss; artifact admission rejects it.
                self.capture_errors += 1

    def stage(self, name):
        with self._lock:
            self._stage = name
            self.record("stage", name=name)

    def failed(self, error):
        with self._lock:
            if self.first_failure is None:
                self.first_failure = {"stage": self._stage, "type": type(error).__name__,
                                      "message": str(error)[:256]}
                self.record("failure", error=self.first_failure)

    def _client(self, client):
        return {"root_uri": client._root_uri, "language": client.language_id,
                "pid": getattr(client._process, "pid", None),
                "command": client._config.command, "args": list(client._config.args),
                "documents": {uri: {"version": version, "sha256": digest.hex()}
                              for uri, (version, digest) in client._documents.items()}}

    def _finish(self):
        with self._lock:
            footer = self._encode({"kind": "trace_end", "index": self._index + 1,
                "stage": self._stage, "monotonic": time.monotonic(),
                "status": "failed" if self.first_failure else "passed",
                "first_failure": self.first_failure, "dropped_events": self.dropped_events,
                "oversized_events": self.oversized_events, "capture_errors": self.capture_errors,
                "truncated": bool(self.dropped_events or self.oversized_events or self.capture_errors)})
            assert len(footer) <= 4096
            try:
                self._file.writelines(self._tail)
                self._file.write(footer)
            finally:
                self._file.close()
                self._file = None

    @contextmanager
    def capture(self, monkeypatch):
        if self.path is None:
            yield self
            return
        from attocode_intel._internal.integrations.lsp import client as module

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("xb")  # Never overwrite an earlier attempt.
        caught = None
        try:
            repo = Path(__file__).resolve().parents[2]
            sources = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in (Path(__file__).resolve(), Path(module.__file__).resolve(),
                                    repo / "packages/code-intel/tests/test_real_language_server.py")}
            self.record("trace_start", schema_version=1, root_uri=self.root_uri, sources=sources,
                        limits={"max_bytes": self.max_bytes, "event_bytes": self.event_bytes,
                                "prefix_bytes": self.prefix_limit, "tail_bytes": self.tail_limit},
                        runtime={"python": sys.version, "platform": sys.platform,
                                 "RA_LOG": os.environ.get("RA_LOG")})
            original_send, original_receive = module._LSPClient._send_message, module._LSPClient._handle_message
            original_stderr, original_stop = module._LSPClient._drain_stderr, module._LSPClient.stop

            async def send(client, message):
                chosen = client._root_uri == self.root_uri
                if chosen:
                    self.record("protocol", direction="out", message=message, **self._client(client))
                result = await original_send(client, message)
                if chosen:
                    self.record("send_returned", id=message.get("id"), method=message.get("method"),
                                **self._client(client))
                return result

            def receive(client, message):
                if client._root_uri == self.root_uri:
                    self.record("protocol", direction="in", message=message, **self._client(client))
                return original_receive(client, message)

            async def stderr(client):
                process = client._process
                if client._root_uri != self.root_uri or process is None or process.stderr is None:
                    return await original_stderr(client)
                stream = process.stderr
                original_read = stream.read
                async def read(size=-1):
                    try:
                        chunk = await original_read(size)
                    except BaseException as error:
                        self.record("stderr_end", reason=type(error).__name__, **self._client(client))
                        raise
                    if chunk:
                        self.record("stderr", text=chunk.decode(errors="replace"),
                                    base64=base64.b64encode(chunk).decode("ascii"), bytes=len(chunk),
                                    **self._client(client))
                    else:
                        self.record("stderr_end", reason="eof", **self._client(client))
                    return chunk
                with patch.object(stream, "read", read):
                    return await original_stderr(client)

            async def stop(client):
                process = client._process
                try:
                    return await original_stop(client)
                finally:
                    if client._root_uri == self.root_uri:
                        self.record("server_stop", pid=getattr(process, "pid", None),
                                    returncode=getattr(process, "returncode", None))

            with monkeypatch.context() as hooks:
                hooks.setattr(module._LSPClient, "_send_message", send)
                hooks.setattr(module._LSPClient, "_handle_message", receive)
                hooks.setattr(module._LSPClient, "_drain_stderr", stderr)
                hooks.setattr(module._LSPClient, "stop", stop)
                yield self
        except BaseException as error:
            caught = error
            self.failed(error)
            raise
        finally:
            try:
                self._finish()
            except Exception:
                if caught is None:
                    raise
