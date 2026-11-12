"""Cancellation routing: owner/ID boundaries, backpressure, caps and races."""
import asyncio
import uuid
from dataclasses import replace

import anyio
import pytest
from attocode_intel.api.auth.context import AuthContext
from http_cancel_child import CLIENT_ID
from mcp import types
from mcp.shared.message import SessionMessage


def _message(identity):
    return SessionMessage(types.JSONRPCMessage(types.JSONRPCNotification(
        jsonrpc='2.0', method='notifications/cancelled', params={'requestId': identity})))


def _auth():
    return AuthContext(user_id=uuid.UUID('11111111-1111-4111-8111-111111111111'),
                       org_id=uuid.UUID('33333333-3333-4333-8333-333333333333'),
                       auth_method='jwt', scopes=['intelligence:read'])


@pytest.mark.parametrize('change', ['user_id', 'org_id', 'auth_method', 'scopes', 'plan',
                                    'credential', 'workspace', 'profile', 'client_id'])
def test_owner_separates_authority_and_context(change):
    from attocode_intel.api.mcp_cancellation import owner_for

    auth, credential, workspace, profile, client_id = _auth(), 'Bearer authored-credential', 'repo-a', 'daily', CLIENT_ID
    before = owner_for(auth, credential, workspace, profile, client_id)
    if change in {'user_id', 'org_id'}:
        auth = replace(auth, **{change: uuid.UUID('22222222-2222-4222-8222-222222222222')})
    elif change == 'auth_method':
        auth = replace(auth, auth_method='api_key')
    elif change == 'scopes':
        auth = replace(auth, scopes=['intelligence:write'])
    elif change == 'plan':
        auth = replace(auth, plan='team')
    elif change == 'credential':
        credential = 'Bearer authored-rotated-credential'
    elif change == 'workspace':
        workspace = 'repo-b'
    elif change == 'profile':
        profile = 'full'
    else:
        client_id = '87654321-4321-4abc-8abc-123456789abc'
    after = owner_for(auth, credential, workspace, profile, client_id)
    assert before != after and 'authored-credential' not in repr(before)
    assert before == owner_for(_auth(), 'authored-credential', 'repo-a', 'daily', CLIENT_ID)


@pytest.mark.parametrize('client_id', ['', 'bad', '00000000-0000-0000-0000-000000000000',
                                       '12345678-1234-1abc-8abc-123456789abc', 'x' * 65])
def test_invalid_context_refused(client_id):
    from attocode_intel.api.mcp_cancellation import owner_for

    with pytest.raises(ValueError, match='UUID4'):
        owner_for(_auth(), 'Bearer authored-credential', '', 'daily', client_id)


async def test_caps_duplicate_and_typed_ids_do_not_overwrite():
    from attocode_intel.api.mcp_cancellation import CancellationRegistry, RegistrationError

    registry = CancellationRegistry(global_limit=3, owner_limit=2)
    owner, other = ('principal', 'repo', 'daily', CLIENT_ID), ('other', 'repo', 'daily', CLIENT_ID)
    send, receive = anyio.create_memory_object_stream(0)
    async with send, receive:
        integer = registry.register(owner, 1, send)
        string = registry.register(owner, '1', send)
        with pytest.raises(RegistrationError, match='already active'):
            registry.register(owner, 1, send)
        with pytest.raises(RegistrationError, match='Too many'):
            registry.register(owner[:-1] + ('another-context',), 'third', send)
        third = registry.register(other, 1, send)
        with pytest.raises(RegistrationError, match='Too many'):
            registry.register(('fourth', '', '', ''), 1, send)
        assert len(registry) == 3
        registry.complete(owner, 1, integer)
        replacement = registry.register(owner, 1, send)
        registry.complete(owner, 1, integer)  # Old completion cannot remove reused ID.
        assert len(registry) == 3
        for identity, entry, context in ((1, replacement, owner), ('1', string, owner), (1, third, other)):
            registry.complete(context, identity, entry)
        assert len(registry) == 0


async def test_early_cancel_waits_for_initial_request_forwarding():
    from attocode_intel.api.mcp_cancellation import CancellationRegistry

    registry = CancellationRegistry()
    owner = ('principal', '', 'daily', CLIENT_ID)
    send, receive = anyio.create_memory_object_stream(0)
    async with send, receive:
        entry = registry.register(owner, 'target', send)
        registry.activate(owner, 'target')
        message = _message('target')
        task = asyncio.create_task(registry.route(owner, message))
        try:
            await asyncio.sleep(0)
            assert not task.done()
            with pytest.raises(anyio.WouldBlock):
                receive.receive_nowait()
            entry.forwarded.set()
            assert await asyncio.wait_for(receive.receive(), 1) is message
            await asyncio.wait_for(task, 1)
        finally:
            registry.complete(owner, 'target', entry)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert len(registry) == 0


@pytest.mark.parametrize('before_forward', [True, False])
async def test_completion_wakes_waiting_or_blocked_cancel_sender(before_forward):
    from attocode_intel.api.mcp_cancellation import CancellationRegistry

    registry = CancellationRegistry()
    owner = ('principal', '', 'daily', CLIENT_ID)
    send, receive = anyio.create_memory_object_stream(0)
    async with send, receive:
        entry = registry.register(owner, 'target', send)
        registry.activate(owner, 'target')
        if not before_forward:
            entry.forwarded.set()
        task = asyncio.create_task(registry.route(owner, _message('target')))
        try:
            await asyncio.sleep(0)
            assert not task.done()
            registry.complete(owner, 'target', entry)
            await asyncio.wait_for(task, 1)
            with pytest.raises(anyio.WouldBlock):
                receive.receive_nowait()
        finally:
            registry.complete(owner, 'target', entry)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert len(registry) == 0


@pytest.mark.parametrize('identity', [True, 1.0, None, {}, 'unknown'])
async def test_malformed_unknown_or_other_owner_cannot_route(identity):
    from attocode_intel.api.mcp_cancellation import CancellationRegistry

    registry = CancellationRegistry()
    owner = ('principal', '', 'daily', CLIENT_ID)
    send, receive = anyio.create_memory_object_stream(0)
    async with send, receive:
        entry = registry.register(owner, 1, send)
        entry.forwarded.set()
        try:
            await asyncio.wait_for(registry.route(owner, _message(identity)), 1)
            await asyncio.wait_for(registry.route(('other', *owner[1:]), _message(1)), 1)
            with pytest.raises(anyio.WouldBlock):
                receive.receive_nowait()
            assert len(registry) == 1
        finally:
            registry.complete(owner, 1, entry)


async def test_feature_requires_configured_authentication(tmp_path, monkeypatch):
    from attocode_intel.api.mcp_transport import MCPTransport
    from attocode_intel.config import CodeIntelConfig

    monkeypatch.setenv('ATTOCODE_INTEL_WATCH', '0')
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    with pytest.raises(ValueError, match='requires configured authentication'):
        MCPTransport(CodeIntelConfig(project_dir=str(tmp_path), api_key=''))
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '0')
    transport = MCPTransport(CodeIntelConfig(project_dir=str(tmp_path), api_key=''))
    try:
        assert transport.manager.stateless
    finally:
        await transport.gateway.close()


@pytest.mark.parametrize('method', ['initialize', 'tools/call'])
async def test_bridge_excludes_initialize_and_cleans_server_failure(method):
    from attocode_intel.api.mcp_cancellation import CancellationServer, current_owner

    entered, release = asyncio.Event(), asyncio.Event()

    class Server:
        async def run(self, read, write, *args, **kwargs):
            await read.receive()
            entered.set()
            await release.wait()
            if method == 'tools/call':
                raise ValueError('authored server failure')

    bridge = CancellationServer(Server())
    original_send, original_read = anyio.create_memory_object_stream(0)
    wire_send, wire_receive = anyio.create_memory_object_stream(0)
    async with original_send, original_read, wire_send, wire_receive:
        token = current_owner.set(('principal', '', 'daily', CLIENT_ID))
        task = asyncio.create_task(bridge.run(original_read, wire_send, None))
        current_owner.reset(token)
        try:
            await original_send.send(SessionMessage(types.JSONRPCMessage(types.JSONRPCRequest(
                jsonrpc='2.0', id='target', method=method, params={}))))
            await asyncio.wait_for(entered.wait(), 1)
            assert len(bridge.registry) == (0 if method == 'initialize' else 1)
            release.set()
            if method == 'tools/call':
                with pytest.raises(ExceptionGroup):
                    await asyncio.wait_for(task, 1)
            else:
                await asyncio.wait_for(task, 1)
            assert len(bridge.registry) == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_transport_resets_routing_context_on_dispatch_failure(tmp_path, monkeypatch):
    from attocode_intel.api.mcp_cancellation import current_owner
    from attocode_intel.api.mcp_transport import MCPTransport
    from attocode_intel.config import CodeIntelConfig
    from attocode_intel.remote import remote_identity

    monkeypatch.setenv('ATTOCODE_INTEL_WATCH', '0')
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')

    async def auth(authorization):
        return _auth()

    monkeypatch.setattr('attocode_intel.api.auth.resolve_auth', auth)
    transport = MCPTransport(CodeIntelConfig(project_dir=str(tmp_path), api_key='authored-key'))

    async def dispatch(*args):
        assert current_owner.get() is not None and remote_identity.get().user_id == _auth().user_id
        raise ValueError('authored dispatch failure')

    monkeypatch.setattr(transport.manager, 'handle_request', dispatch)
    scope = {'type': 'http', 'headers': [(b'authorization', b'Bearer authored-key'),
                                        (b'x-attocode-cancellation-id', CLIENT_ID.encode())]}
    try:
        with pytest.raises(ValueError, match='authored dispatch failure'):
            await transport(scope, None, None)
        assert current_owner.get() is None and remote_identity.get() is None
    finally:
        await transport.gateway.close()


async def test_cancelled_undelivered_sender_can_be_retried():
    from attocode_intel.api.mcp_cancellation import CancellationRegistry

    registry = CancellationRegistry()
    owner = ('principal', '', 'daily', CLIENT_ID)
    send, receive = anyio.create_memory_object_stream(0)
    async with send, receive:
        entry = registry.register(owner, 'target', send)
        entry.forwarded.set()
        registry.activate(owner, 'target')
        message = _message('target')
        first = asyncio.create_task(registry.route(owner, message))
        retry = None
        try:
            await asyncio.sleep(0)
            assert not first.done()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not entry.sent
            retry = asyncio.create_task(registry.route(owner, message))
            assert await asyncio.wait_for(receive.receive(), 1) is message
            await asyncio.wait_for(retry, 1)
            await asyncio.wait_for(registry.route(owner, message), 1)
            with pytest.raises(anyio.WouldBlock):
                receive.receive_nowait()
        finally:
            registry.complete(owner, 'target', entry)
            first.cancel()
            if retry is not None:
                retry.cancel()
            await asyncio.gather(first, *([retry] if retry is not None else []), return_exceptions=True)
    assert len(registry) == 0
