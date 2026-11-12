"""Opt-in cancellation routing between authenticated stateless HTTP POSTs.

Only public SDK message streams are relayed. The original SDK session owns
request dispatch, cancellation scopes and responses. No client state survives
completion, and no notification is stored for a future request.
"""
from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import RFC_4122, UUID

import anyio
from mcp import types
from mcp.shared.message import SessionMessage

current_owner: ContextVar[tuple | None] = ContextVar('http_cancellation_owner', default=None)


def owner_for(auth, authorization, workspace, profile, client_id):
    """Bind a cancellation context to current authority, never to a bare ID."""
    try:
        identifier = UUID(client_id) if len(client_id) <= 64 else None
    except (ValueError, AttributeError, TypeError):
        identifier = None
    if identifier is None or identifier.version != 4 or identifier.variant != RFC_4122:
        raise ValueError('X-Attocode-Cancellation-Id must be a UUID4')
    credential = authorization.removeprefix('Bearer ').strip()
    authority = {
        'method': auth.auth_method, 'user': str(auth.user_id), 'org': str(auth.org_id),
        'scopes': sorted(map(str, auth.scopes or ())), 'plan': auth.plan,
        'credential_sha256': hashlib.sha256(credential.encode()).hexdigest(),
    }
    fingerprint = hashlib.sha256(json.dumps(authority, sort_keys=True).encode()).hexdigest()
    return fingerprint, workspace, profile, str(identifier)


class RegistrationError(ValueError):
    def __init__(self, message, code=-32600):
        super().__init__(message)
        self.code = code


@dataclass(eq=False)
class _Entry:
    stream: object
    forwarded: anyio.Event = field(default_factory=anyio.Event)
    finished: bool = False
    senders: set = field(default_factory=set)


class CancellationRegistry:
    """Event-loop-local, bounded live requests; no credentials or idle clients."""

    def __init__(self, global_limit=256, owner_limit=32):
        self.global_limit, self.owner_limit = global_limit, owner_limit
        self._entries = {}

    def __len__(self):
        return len(self._entries)

    def register(self, owner, identity, stream):
        key = owner, type(identity), identity
        if key in self._entries:
            raise RegistrationError('Request ID is already active in this cancellation context')
        count = sum(context[:-1] == owner[:-1] for context, _, _ in self._entries)
        if len(self) >= self.global_limit or count >= self.owner_limit:
            raise RegistrationError('Too many active cancellable requests', -32000)
        entry = _Entry(stream.clone())
        self._entries[key] = entry
        return entry

    def complete(self, owner, identity, entry):
        key = owner, type(identity), identity
        if self._entries.get(key) is entry:
            del self._entries[key]
        entry.finished = True
        entry.forwarded.set()
        entry.stream.close()
        # Wake senders blocked on an original session that has stopped reading.
        for scope in tuple(entry.senders):
            scope.cancel()

    async def route(self, owner, message):
        identity = (message.message.root.params or {}).get('requestId')
        if type(identity) not in (str, int):
            return
        entry = self._entries.get((owner, type(identity), identity))
        if entry is None:
            return
        await entry.forwarded.wait()
        if entry.finished:
            return
        try:
            stream = entry.stream.clone()
        except anyio.ClosedResourceError:
            return
        with stream, anyio.CancelScope() as scope:
            entry.senders.add(scope)
            try:
                await stream.send(message)
            except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                pass
            finally:
                entry.senders.discard(scope)


class CancellationServer:
    """Relay public SDK streams while preserving actual server execution."""

    def __init__(self, server):
        self.server = server
        self.registry = CancellationRegistry()

    def create_initialization_options(self, *args, **kwargs):
        return self.server.create_initialization_options(*args, **kwargs)

    async def run(self, read_stream, write_stream, *args, **kwargs):
        owner = current_owner.get()
        if owner is None:
            return await self.server.run(read_stream, write_stream, *args, **kwargs)
        to_sdk, sdk_read = anyio.create_memory_object_stream(0)
        sdk_write, from_sdk = anyio.create_memory_object_stream(0)
        owned = {}

        async def inbound():
            async with to_sdk:
                async for message in read_stream:
                    root = message.message.root
                    if isinstance(root, types.JSONRPCNotification) and root.method == 'notifications/cancelled':
                        await self.registry.route(owner, message)
                    entry = None
                    if isinstance(root, types.JSONRPCRequest) and root.method != 'initialize':
                        try:
                            entry = self.registry.register(owner, root.id, to_sdk)
                        except RegistrationError as error:
                            response = types.JSONRPCError(jsonrpc='2.0', id=root.id,
                                                          error=types.ErrorData(code=error.code, message=str(error)))
                            await write_stream.send(SessionMessage(types.JSONRPCMessage(response)))
                            continue
                        owned[type(root.id), root.id] = entry
                    try:
                        await to_sdk.send(message)
                    finally:
                        if entry is not None:
                            entry.forwarded.set()

        async def outbound():
            async with from_sdk:
                async for message in from_sdk:
                    root = message.message.root
                    if isinstance(root, (types.JSONRPCResponse, types.JSONRPCError)):
                        entry = owned.pop((type(root.id), root.id), None)
                        if entry is not None:
                            self.registry.complete(owner, root.id, entry)
                    await write_stream.send(message)

        async with sdk_read, sdk_write, anyio.create_task_group() as group:
            group.start_soon(inbound)
            group.start_soon(outbound)
            try:
                return await self.server.run(sdk_read, sdk_write, *args, **kwargs)
            finally:
                for (_, identity), entry in owned.items():
                    self.registry.complete(owner, identity, entry)
                group.cancel_scope.cancel()
