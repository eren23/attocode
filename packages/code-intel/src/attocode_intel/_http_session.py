"""A live HTTP session can opt into Attocode's tools/call cancellation routing.

The SDK owns JSON-RPC IDs, serialization, responses and timeouts. Observe its
public write stream in the calling task to correlate cancellation with that ID.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import anyio
import httpx
from anyio.abc import ObjectSendStream
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage

CONTEXT_HEADER = 'X-Attocode-Cancellation-Id'


@dataclass
class _Ticket:
    request_id: str | int | None = None


class _ObservedWrite(ObjectSendStream[SessionMessage]):
    def __init__(self, stream, ticket):
        self.stream, self.ticket = stream, ticket

    async def send(self, message):
        ticket = self.ticket.get()
        rpc = message.message.root
        if ticket is not None and isinstance(rpc, types.JSONRPCRequest) and rpc.method == 'tools/call':
            ticket.request_id = rpc.id
        await self.stream.send(message)

    async def aclose(self):
        await self.stream.aclose()


class _CancellationSession(ClientSession):
    def __init__(self, read, write):
        self.ticket = ContextVar('attocode_http_call', default=None)
        super().__init__(read, _ObservedWrite(write, self.ticket))

    async def send_request(self, request, result_type, request_read_timeout_seconds=None,
                           metadata=None, progress_callback=None):
        if not isinstance(request.root, types.CallToolRequest):
            return await super().send_request(request, result_type, request_read_timeout_seconds,
                                              metadata, progress_callback)
        ticket = _Ticket()
        context = self.ticket.set(ticket)
        try:
            return await super().send_request(request, result_type, request_read_timeout_seconds,
                                              metadata, progress_callback)
        except anyio.get_cancelled_exc_class():
            if ticket.request_id is not None:
                # One bounded, best-effort attempt; no sender task survives this call.
                with anyio.move_on_after(1, shield=True):
                    try:
                        await self.send_notification(types.ClientNotification(types.CancelledNotification(
                            params=types.CancelledNotificationParams(
                                requestId=ticket.request_id, reason='Caller cancelled the tool request'))))
                    except (Exception, anyio.get_cancelled_exc_class()):
                        pass
            raise
        finally:
            self.ticket.reset(context)


@asynccontextmanager
async def http_session(url, *, headers=None, enable_cancellation=False):
    """Yield an entered, uninitialized SDK session; own its transport and client.

    Enabled sessions own a fresh UUID4 and fixed headers for their entire life.
    The default uses the unmodified SDK, without an automatic context or notify.
    """
    import uuid

    headers = dict(headers or {})
    if enable_cancellation:
        if any(name.lower() == CONTEXT_HEADER.lower() for name in headers):
            raise ValueError('Cancellation context belongs to the live session')
        headers[CONTEXT_HEADER] = str(uuid.uuid4())
    session_type = _CancellationSession if enable_cancellation else ClientSession
    async with (
        httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=300), follow_redirects=True) as http,
        streamable_http_client(url, http_client=http) as streams,
        session_type(streams[0], streams[1]) as session,
    ):
        yield session
