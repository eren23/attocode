"""Owned stdio process with actual SDK client and complete protocol journals."""
import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from anyio.abc import ObjectSendStream
from mcp import ClientSession, types
from mcp.shared.message import SessionMessage


class Writer(ObjectSendStream):
    def __init__(self, proxy):
        self.proxy = proxy

    async def send(self, message):
        value = message.message.model_dump(by_alias=True, exclude_none=True)
        self.proxy.wire.append({'direction': 'client_to_proxy', 'monotonic': time.monotonic(), 'rpc': value})
        raw = (json.dumps(value) + '\n').encode()
        with (self.proxy.actor.evidence / 'proxy.stdin.raw').open('ab') as stream:
            stream.write(raw)
        self.proxy.process.stdin.write(raw)
        await self.proxy.process.stdin.drain()

    async def aclose(self):
        pass  # The owning fixture closes the process after the SDK context exits.


class Proxy:
    def __init__(self, actor):
        self.actor = actor
        self.wire = []
        self.process = self.pump = self.stderr = None
        self.forced = False
        self.pump_error = None
        self.output_bytes = 0

    async def start(self):
        url = str(self.actor.client.base_url).rstrip('/') + '/mcp/'
        package = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': str(package / 'src'),
               'ATTOCODE_PROXY_TEST_TOKEN': self.actor.tokens['alice']}
        self.stderr = (self.actor.evidence / 'proxy.stderr').open('wb')
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name('http_proxy_child.py')),
            url, str(self.actor.root), str(self.actor.evidence / 'proxy-observer.jsonl'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=self.stderr, env=env, limit=2**20)

    async def read(self, sender):
        try:
            while raw := await self.process.stdout.readline():
                self.output_bytes += len(raw)
                assert self.output_bytes <= 16 * 2**20, 'Owned proxy capture exceeded budget'
                with (self.actor.evidence / 'proxy.stdout.raw').open('ab') as stream:
                    stream.write(raw)
                value = types.JSONRPCMessage.model_validate_json(raw)
                self.wire.append({'direction': 'proxy_to_client', 'monotonic': time.monotonic(),
                                  'rpc': value.model_dump(by_alias=True, exclude_none=True)})
                try:
                    await sender.send(SessionMessage(value))
                except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                    break
        except Exception as exc:
            self.pump_error = type(exc).__name__
            raise
        finally:
            await sender.aclose()

    async def close(self):
        if self.process is not None and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 20)
            except TimeoutError:
                self.forced = True
                self.process.kill()
                await self.process.wait()
        if self.pump is not None:
            if not self.pump.done():
                self.pump.cancel()
            await asyncio.gather(self.pump, return_exceptions=True)
        if self.stderr is not None:
            self.stderr.close()
        evidence = self.actor.evidence
        (evidence / 'proxy-wire.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in self.wire))
        (evidence / 'proxy-report.json').write_text(json.dumps({
            'returncode': getattr(self.process, 'returncode', None), 'forced_cleanup': self.forced,
            'output_bytes': self.output_bytes, 'pump_error': self.pump_error}, indent=2) + '\n')


@asynccontextmanager
async def proxy(actor):
    owned = Proxy(actor)
    try:
        await owned.start()
        sender, reader = anyio.create_memory_object_stream(0)
        async with sender, reader:
            owned.pump = asyncio.create_task(owned.read(sender))
            async with ClientSession(reader, Writer(owned)) as session:
                async with asyncio.timeout(15):
                    await session.initialize()
                yield owned, session
    finally:
        await owned.close()
        assert not owned.forced and owned.process.returncode == 0
        assert owned.pump_error is None
