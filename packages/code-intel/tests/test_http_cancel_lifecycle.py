"""Public SDK receive lifecycle: normal close and exception-valued items."""
import asyncio

import anyio
from http_cancel_fixture import _actor
from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.shared.message import SessionMessage


async def test_normal_http_notification_teardown_does_not_crash(
        tmp_path, monkeypatch, request, record_property):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        await actor.notify('notifications/cancelled', {'requestId': 'unknown'})
        await actor.rpc('barrier', 'tools/list', {})
    stderr = (actor.evidence / 'server.stderr').read_text()
    crashes = stderr.count('Stateless session crashed')
    record_property('authenticated_http', 'true')
    record_property('normal_notification_accepted', 'true')
    record_property('sdk_crash_count', crashes)
    assert crashes == 0, 'REGRESSION: normal HTTP notification teardown crashes the SDK relay'


async def test_closed_original_input_does_not_cancel_active_sdk_handler(record_property):
    from attocode_intel.api.mcp_cancellation import CancellationServer, current_owner

    before_receive, allow_receive = asyncio.Event(), asyncio.Event()
    body_entered, release_body = asyncio.Event(), asyncio.Event()
    cancelled = []
    send, read = anyio.create_memory_object_stream(0)
    wire_send, wire_read = anyio.create_memory_object_stream(0)

    class GatedReceive:
        calls = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return await self.receive()
            except anyio.EndOfStream:
                raise StopAsyncIteration from None

        async def receive(self):
            self.calls += 1
            if self.calls > 1:
                before_receive.set()
                await allow_receive.wait()
            return await read.receive()

    server = Server('owned-sdk-input-closure-fixture')
    bridge = CancellationServer(server)
    owner = ('authored-principal', 'repo', 'daily', 'authored-context')

    @server.call_tool(validate_input=False)
    async def blocked(name, arguments):
        bridge.registry.activate(owner, 'target')
        body_entered.set()
        try:
            await release_body.wait()
        except asyncio.CancelledError:
            cancelled.append('target')
            raise
        return [types.TextContent(type='text', text='completed')]

    async with send, read, wire_send, wire_read:
        token = current_owner.set(owner)
        task = asyncio.create_task(bridge.run(GatedReceive(), wire_send,
                                             server.create_initialization_options(), stateless=True))
        current_owner.reset(token)
        response_task = None
        try:
            request = types.JSONRPCRequest(jsonrpc='2.0', id='target', method='tools/call',
                                           params={'name': 'blocked', 'arguments': {}})
            await send.send(SessionMessage(types.JSONRPCMessage(request)))
            await asyncio.wait_for(body_entered.wait(), 1)
            await asyncio.wait_for(before_receive.wait(), 1)
            assert len(bridge.registry) == 1
            read.close()
            send.close()
            allow_receive.set()
            await asyncio.wait({task}, timeout=.05)
            record_property('sdk_handler_active', 'true')
            record_property('original_input_closed', 'true')
            record_property('registered', 'true')
            assert not task.done(), 'REGRESSION: normal input closure cancels an active SDK handler'
            assert not cancelled
            response_task = asyncio.create_task(wire_read.receive())
            release_body.set()
            response = await asyncio.wait_for(response_task, 1)
            assert response.message.root.result['content'][0]['text'] == 'completed'
            await asyncio.wait_for(task, 1)
            assert not cancelled
        finally:
            allow_receive.set()
            release_body.set()
            task.cancel()
            if response_task is not None:
                response_task.cancel()
            await asyncio.gather(task, *([response_task] if response_task is not None else []),
                                 return_exceptions=True)
    assert len(bridge.registry) == 0


async def test_exception_value_is_forwarded_to_original_server(record_property):
    from attocode_intel.api.mcp_cancellation import CancellationServer, current_owner

    seen = []

    class RecordingServer:
        async def run(self, read, write, *args, **kwargs):
            seen.append(await read.receive())

    bridge = CancellationServer(RecordingServer())
    send, read = anyio.create_memory_object_stream(0)
    wire_send, wire_read = anyio.create_memory_object_stream(0)
    async with send, read, wire_send, wire_read:
        token = current_owner.set(('authored-principal', 'repo', 'daily', 'authored-context'))
        task = asyncio.create_task(bridge.run(read, wire_send, None))
        current_owner.reset(token)
        error = ValueError('authored transport error value')
        try:
            await send.send(error)
            await asyncio.wait({task}, timeout=.05)
            record_property('exception_value_sent', 'true')
            assert seen == [error], 'REGRESSION: SDK exception stream values are not forwarded unchanged'
            await asyncio.wait_for(task, 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert len(bridge.registry) == 0
