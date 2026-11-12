"""Repeated notifications must retain at most one pending delivery per call."""
import asyncio

import anyio
from mcp import types
from mcp.shared.message import SessionMessage


async def test_duplicate_cancellation_retains_one_pending_sender(record_property):
    from attocode_intel.api.mcp_cancellation import CancellationRegistry

    registry = CancellationRegistry()
    owner = ('authored-principal', 'repo', 'daily', 'authored-context')
    send, receive = anyio.create_memory_object_stream(0)
    async with send, receive:
        entry = registry.register(owner, 'target', send)
        message = SessionMessage(types.JSONRPCMessage(types.JSONRPCNotification(
            jsonrpc='2.0', method='notifications/cancelled', params={'requestId': 'target'})))
        tasks = [asyncio.create_task(registry.route(owner, message)) for _ in range(6)]
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert len(registry) == 1 and not entry.forwarded.is_set()
            record_property('entry_registered', 'true')
            record_property('initial_request_forwarded', 'false')
            record_property('duplicate_notifications', '6')
            pending = sum(not task.done() for task in tasks)
            record_property('pending_senders', pending)
            assert pending == 1, 'REGRESSION: duplicate cancellation notifications retain multiple pending senders'
        finally:
            registry.complete(owner, 'target', entry)
            await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert len(registry) == 0
