"""Startup must drain stderr without competing readers or abandoned tasks."""
import asyncio
import json
import logging

import pytest
from attocode_intel._internal.integrations.lsp.client import LanguageServerConfig, _LSPClient


class StderrStream(asyncio.StreamReader):
    def __init__(self, reader_first):
        super().__init__()
        self.reader_first = reader_first
        self.waiting = asyncio.Event()
        self.delivered = asyncio.Event()
        self.conflicts = []

    async def read(self, n=-1):
        if self.reader_first:
            # Let an independently scheduled reader enter first, if present.
            # A single owner still proceeds on the following event-loop turn.
            gate = asyncio.Event()
            asyncio.get_running_loop().call_soon(gate.set)
            await gate.wait()
        result = await super().read(n)
        if result:
            self.delivered.set()
        return result

    async def readuntil(self, separator=b"\n"):
        result = await super().readuntil(separator)
        if result:
            self.delivered.set()
        return result

    async def _wait_for_data(self, name):
        self.waiting.set()
        try:
            return await super()._wait_for_data(name)
        except RuntimeError as error:
            self.conflicts.append(str(error))
            raise


class InMemoryServer:
    """Replace only the external process; use real client framing and streams."""
    def __init__(self, reader_first):
        self.stdout = asyncio.StreamReader()
        self.stderr = StderrStream(reader_first)
        self.stdin = self
        self.returncode = None
        self.pending = []
        self.exited = asyncio.Event()

    def write(self, frame):
        _header, content = frame.split(b"\r\n\r\n", 1)
        self.pending.append(json.loads(content))

    async def drain(self):
        while self.pending:
            message = self.pending.pop(0)
            method = message.get("method")
            if method == "initialize":
                # Initialization completes after stderr has a waiting owner.
                await self.stderr.waiting.wait()
            if "id" in message:
                payload = json.dumps({"jsonrpc": "2.0", "id": message["id"],
                                      "result": {"capabilities": {}} if method == "initialize" else None}).encode()
                self.stdout.feed_data(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
            if method == "exit":
                self.close()

    def close(self):
        if self.returncode is None:
            self.returncode = 0
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.exited.set()

    async def wait(self):
        await self.exited.wait()
        return self.returncode


@pytest.mark.parametrize("reader_first", [False, True], ids=["drain-first", "read-loop-first"])
async def test_stderr_has_one_reader_through_start_and_shutdown(monkeypatch, caplog, reader_first):
    # Regression: another stderr consumer can steal diagnostics or terminate the
    # drain with RuntimeError, depending on which coroutine waits first.
    process = InMemoryServer(reader_first)

    async def spawn(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    caplog.set_level(logging.DEBUG, logger="attocode_intel._internal.integrations.lsp.client")
    client = _LSPClient(LanguageServerConfig("in-memory", language_id="rust"), "file:///workspace", timeout=1)
    reader_task = stderr_task = None
    try:
        async with asyncio.timeout(2):
            await client.start()
            reader_task, stderr_task = client._reader_task, client._stderr_task
            assert client.is_initialized
            process.stderr.feed_data(b"workspace reload evidence\n")
            await process.stderr.delivered.wait()
    finally:
        await client.stop()
    assert process.stderr.conflicts == []
    assert "workspace reload evidence" in caplog.text
    assert process.returncode == 0
    assert reader_task is not None and reader_task.done()
    assert stderr_task is not None and stderr_task.done()
    assert not stderr_task.cancelled() and stderr_task.exception() is None
    assert client._reader_task is None and client._stderr_task is None
