"""A controlled real-SDK scheduling gate, not a server latency observation."""
import asyncio
from functools import wraps

import anyio
from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder


async def test_cancellation_waits_for_sdk_handler_activation(monkeypatch, record_property):
    from attocode_intel.api.mcp_cancellation import CancellationServer, current_owner

    before_scope, release_handler, attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cancelled = []
    original_message = Server._handle_message
    original_cancel = RequestResponder.cancel

    class GatedServer(Server):
        @wraps(original_message)
        async def _handle_message(self, message, *args, **kwargs):
            if isinstance(message, RequestResponder) and message.request_id == 'target':
                assert not message._entered
                before_scope.set()
                await release_handler.wait()
            return await original_message(self, message, *args, **kwargs)

    @wraps(original_cancel)
    async def observed_cancel(self):
        if self.request_id == 'target':
            attempted.set()
        return await original_cancel(self)

    monkeypatch.setattr(RequestResponder, 'cancel', observed_cancel)
    server = GatedServer('owned-sdk-handler-scheduling-fixture')
    bridge = CancellationServer(server)
    owner = ('authored-principal', 'repo', 'daily', 'authored-context')

    @server.call_tool(validate_input=False)
    async def blocked(name, arguments):
        # This callback models the production tool-entry signal inside the SDK
        # scope. Conditional lookup lets the baseline fail semantically instead
        # of failing on a missing new method.
        if activate := getattr(bridge.registry, 'activate', None):
            activate(owner, 'target')
        try:
            await anyio.sleep_forever()
        except asyncio.CancelledError:
            cancelled.append('target')
            raise

    original_send, original_read = anyio.create_memory_object_stream(0)
    wire_send, wire_receive = anyio.create_memory_object_stream(0)
    async with original_send, original_read, wire_send, wire_receive:
        token = current_owner.set(owner)
        task = asyncio.create_task(bridge.run(original_read, wire_send,
                                             server.create_initialization_options(), stateless=True))
        current_owner.reset(token)
        route = None
        try:
            request = types.JSONRPCRequest(jsonrpc='2.0', id='target', method='tools/call',
                                           params={'name': 'blocked', 'arguments': {}})
            await original_send.send(SessionMessage(types.JSONRPCMessage(request)))
            await asyncio.wait_for(before_scope.wait(), 1)
            assert len(bridge.registry) == 1 and not release_handler.is_set()
            record_property('entry_registered', 'true')
            record_property('sdk_handler_active', 'false')
            notification = types.JSONRPCNotification(jsonrpc='2.0', method='notifications/cancelled',
                                                      params={'requestId': 'target'})
            route = asyncio.create_task(bridge.registry.route(owner, SessionMessage(types.JSONRPCMessage(notification))))
            # This is an observer window under an explicitly held scheduling
            # gate, not a response-time claim about a real workspace.
            try:
                await asyncio.wait_for(attempted.wait(), .05)
            except TimeoutError:
                pass
            assert not attempted.is_set(), 'REGRESSION: cancellation reaches SDK before its request handler is active'
            release_handler.set()
            response = await asyncio.wait_for(wire_receive.receive(), 1)
            assert response.message.root.id == 'target'
            assert response.message.root.error.message == 'Request cancelled'
            await asyncio.wait_for(route, 1)
            async with asyncio.timeout(1):
                while not cancelled:
                    await asyncio.sleep(0)
        finally:
            release_handler.set()
            if route is not None:
                route.cancel()
                await asyncio.gather(route, return_exceptions=True)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert len(bridge.registry) == 0
