"""Cancellation bridge contracts against the real SDK and an external HTTP peer."""
import asyncio
import json
import uuid

import httpx
import pytest
from mcp import types
from mcp.shared.exceptions import McpError


class Peer:
    def __init__(self):
        self.requests = []
        self.entered = {name: asyncio.Event() for name in ['a', 'b']}
        self.release = {name: asyncio.Event() for name in ['a', 'b']}

    async def handle(self, request):
        if request.method != 'POST':
            return httpx.Response(405)
        rpc = json.loads(request.content)
        self.requests.append((rpc, dict(request.headers)))
        method = rpc['method']
        if method == 'notifications/cancelled':
            for old, _ in self.requests:
                if old.get('id') == rpc['params']['requestId']:
                    self.release[old['params']['name']].set()
        if 'id' not in rpc:
            return httpx.Response(202)
        if method == 'initialize':
            result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'owned-http-peer', 'version': '7.6.5'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': name, 'inputSchema': {'type': 'object'}}
                                for name in ['a', 'b', 'later', 'error']]}
        elif method == 'tools/call':
            name = rpc['params']['name']
            if name == 'error':
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': rpc['id'],
                    'error': {'code': -32088, 'message': 'authored error', 'data': {'key': 4}}})
            if name in self.entered:
                self.entered[name].set()
                await self.release[name].wait()
            result = {'content': [{'type': 'text', 'text': name}], 'isError': False}
        else:
            result = {}
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': rpc['id'], 'result': result})


@pytest.fixture
def peer(monkeypatch):
    peer = Peer()
    original = httpx.AsyncClient

    class OwnedHTTP(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, transport=httpx.MockTransport(peer.handle), **kwargs)

    monkeypatch.setattr(httpx, 'AsyncClient', OwnedHTTP)
    return peer


@pytest.mark.parametrize('enabled', [True, False])
async def test_cancel_uses_sdk_wire_id_and_session_remains_usable(peer, enabled):
    from attocode_intel._http_session import http_session

    headers = {'Authorization': 'Bearer authored-secret', 'X-Attocode-Workspace': 'repo with spaces'}
    async with http_session('http://owned.invalid/mcp/', headers=headers,
                            enable_cancellation=enabled) as session:
        await session.initialize()
        task = asyncio.create_task(session.call_tool('a', {}))
        await asyncio.wait_for(peer.entered['a'].wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(.02)
        calls = [r for r, _ in peer.requests if r['method'] == 'tools/call']
        cancels = [r for r, _ in peer.requests if r['method'] == 'notifications/cancelled']
        assert [r['params']['requestId'] for r in cancels] == ([calls[0]['id']] if enabled else [])
        peer.release['a'].set()
        assert (await session.call_tool('later', {})).content[0].text == 'later'
        with pytest.raises(McpError) as error:
            await session.call_tool('error', {})
        assert error.value.error.model_dump() == {
            'code': -32088, 'message': 'authored error', 'data': {'key': 4}}
    assert headers == {'Authorization': 'Bearer authored-secret', 'X-Attocode-Workspace': 'repo with spaces'}
    contexts = {h.get('x-attocode-cancellation-id') for _, h in peer.requests}
    if enabled:
        assert len(contexts) == 1 and uuid.UUID(contexts.pop()).version == 4
    else:
        assert contexts == {None}
    assert all(h['authorization'] == 'Bearer authored-secret' and
               h['x-attocode-workspace'] == 'repo with spaces' for _, h in peer.requests)


async def test_concurrent_requests_do_not_share_cancellation_ticket(peer):
    from attocode_intel._http_session import http_session

    async with http_session('http://owned.invalid/mcp/', enable_cancellation=True) as session:
        await session.initialize()
        a = asyncio.create_task(session.call_tool('a', {}))
        b = asyncio.create_task(session.call_tool('b', {}))
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in peer.entered.values())), 2)
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        await asyncio.sleep(.02)
        assert not b.done()
        requests = {r['params']['name']: r['id'] for r, _ in peer.requests if r['method'] == 'tools/call'}
        cancels = [r['params']['requestId'] for r, _ in peer.requests if r['method'] == 'notifications/cancelled']
        assert cancels == [requests['a']] and requests['a'] != requests['b']
        peer.release['b'].set()
        assert (await b).content[0].text == 'b'


async def test_context_rotates_and_caller_cannot_supply_it(peer):
    from attocode_intel._http_session import http_session

    for _ in range(2):
        async with http_session('http://owned.invalid/mcp/', enable_cancellation=True) as session:
            await session.initialize()
    contexts = [h['x-attocode-cancellation-id'] for r, h in peer.requests if r['method'] == 'initialize']
    assert len(set(contexts)) == 2 and all(uuid.UUID(c).version == 4 for c in contexts)
    with pytest.raises(ValueError, match='session'):
        async with http_session('http://owned.invalid/mcp/', enable_cancellation=True,
                                headers={'x-ATTOCODE-cancellation-ID': str(uuid.uuid4())}):
            pytest.fail('caller context accepted')


@pytest.mark.parametrize('failure', ['blocked', 'closed'])
async def test_enqueue_failure_preserves_original_cancellation(peer, monkeypatch, failure):
    from attocode_intel._http_session import http_session
    from mcp import ClientSession

    original = ClientSession.send_notification
    attempted = asyncio.Event()

    async def send(self, notification, *args, **kwargs):
        if isinstance(notification.root, types.CancelledNotification):
            attempted.set()
            if failure == 'closed':
                raise RuntimeError('owned closed stream')
            await asyncio.Event().wait()
        return await original(self, notification, *args, **kwargs)

    monkeypatch.setattr(ClientSession, 'send_notification', send)
    async with http_session('http://owned.invalid/mcp/', enable_cancellation=True) as session:
        await session.initialize()
        task = asyncio.create_task(session.call_tool('a', {}))
        await asyncio.wait_for(peer.entered['a'].wait(), 2)
        task.cancel('original caller cancellation')
        with pytest.raises(asyncio.CancelledError, match='original caller cancellation'):
            await asyncio.wait_for(task, 2)
        assert attempted.is_set()
        peer.release['a'].set()
        assert (await session.call_tool('later', {})).content[0].text == 'later'
