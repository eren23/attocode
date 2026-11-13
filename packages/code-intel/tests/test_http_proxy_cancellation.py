"""Real stdio cancellation automatically reaches its correlated HTTP call."""
import asyncio
import hashlib
import json
import time
import uuid

import pytest
from http_cancel_fixture import _actor, _payload, _rows
from http_proxy_fixture import proxy
from mcp import types
from mcp.shared.exceptions import McpError


@pytest.mark.parametrize('phase', ['initialize', 'definition'])
async def test_stdio_cancel_reaches_http_worker(tmp_path, monkeypatch, request, record_property, phase):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with (
        _actor(tmp_path, request, record_property, 'http', phase) as actor,
        proxy(actor) as (owned, session),
    ):
        await session.list_tools()
        await session.send_ping()  # Local-only: deliberately separate the two ID counters.
        target = actor.task(session.call_tool('inspect_symbol', {
            'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000}))
        await actor.blocked()
        assert not target.done()
        remote = [r for r in _rows(actor.evidence / 'proxy-observer.jsonl')
                  if r['kind'] == 'http_request' and r['rpc'].get('method') == 'tools/call'][-1]
        local = [r['rpc'] for r in owned.wire if r['direction'] == 'client_to_proxy'
                 and r['rpc'].get('method') == 'tools/call'][-1]
        assert local['id'] != remote['rpc']['id']
        assert uuid.UUID(remote['context']).version == 4
        assert remote['credential_sha256'] == hashlib.sha256(
            ('Bearer ' + actor.tokens['alice']).encode()).hexdigest()
        auth = [r for r in _rows(actor.journal) if r['kind'] == 'auth_resolved']
        assert auth[-1]['method'] == 'jwt' and auth[-1]['user_id'] == '11111111-1111-4111-8111-111111111111'
        record_property('qualified_input', 'true')
        record_property('entrypoint', 'stdio_http_proxy')
        record_property('blocked_phase', phase)
        record_property('distinct_rpc_ids', 'true')
        cancellation_started = time.monotonic()
        await session.send_notification(types.ClientNotification(types.CancelledNotification(
            params=types.CancelledNotificationParams(requestId=local['id'], reason='authored caller cancellation'))))
        with pytest.raises(McpError, match='Request cancelled'):
            await asyncio.wait_for(asyncio.shield(target), 2)
        cancelled = None
        try:
            cancelled = await actor.event('precision_cancelled', remote['rpc']['id'], timeout=1)
        except TimeoutError:
            pass
        decision = {'qualified_input': True, 'phase': phase, 'stdio_id': local['id'],
                    'http_id': remote['rpc']['id'], 'local_cancel_response': True,
                    'cancellation_started': cancellation_started, 'observed_at': time.monotonic(),
                    'remote_worker_cancel_observed': cancelled is not None,
                    'http_cancel_notifications_at_decision': sum(
                        r['kind'] == 'http_request' and r['rpc'].get('method') == 'notifications/cancelled'
                        for r in _rows(actor.evidence / 'proxy-observer.jsonl'))}
        (actor.evidence / 'proxy-decision.json').write_text(json.dumps(decision, indent=2) + '\n')
        assert cancelled is not None, (
            'REGRESSION: stdio client cancellation is not forwarded to the active HTTP call')
        notifications = [r for r in _rows(actor.evidence / 'proxy-observer.jsonl')
                         if r['kind'] == 'http_request' and r['rpc'].get('method') == 'notifications/cancelled']
        assert len(notifications) == 1
        assert notifications[0]['rpc']['params']['requestId'] == remote['rpc']['id']
        assert notifications[0]['context'] == remote['context']
        state = cancelled['state']
        assert state['callback_restored'] and state['pending'] == state['completed'] == state['retry_after'] == 0
        assert not (await session.call_tool('symbols', {'path': 'helper.rs'})).isError
        actor.ready.touch()
        recovered = await session.call_tool('inspect_symbol', {
            'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000})
        assert _payload(recovered.model_dump(by_alias=True))['metadata']['precision'] == 'verified'


async def test_proxy_normal_protocol_forwarding(tmp_path, monkeypatch, request, record_property):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with (
        _actor(tmp_path, request, record_property, 'http', 'definition') as actor,
        proxy(actor) as (owned, session),
    ):
        tools = await session.list_tools()
        assert any(t.name == 'capabilities' for t in tools.tools)
        assert not (await session.call_tool('capabilities', {'max_tokens': 16000})).isError
        assert (await session.list_resources()).resources
        assert (await session.list_resource_templates()).resourceTemplates
        contents = await session.read_resource('attocode://guidelines')
        assert contents.contents and contents.contents[0].mimeType == 'text/plain'
        upstream = await actor.rpc('proxy-capability-oracle', 'initialize', {
            'protocolVersion': '2025-11-25', 'capabilities': {},
            'clientInfo': {'name': 'owned-capability-control', 'version': '1'}})
        supports_prompts = 'prompts' in upstream['result']['capabilities']
        assert (owned.initialization.capabilities.prompts is not None) == supports_prompts
        if supports_prompts:
            await session.list_prompts()
        else:
            with pytest.raises(McpError) as missing:
                await session.list_prompts()
            assert missing.value.error.code == -32601
        assert (await session.call_tool('not-a-real-operation', {})).isError


@pytest.mark.parametrize('client', ['codex', 'claude', 'cursor'])
def test_direct_http_configuration_stays_default(tmp_path, client):
    from attocode_intel.onboarding import configure_client

    result = configure_client(client, tmp_path, dry_run=True, server='https://example.invalid',
                              repo='authored-repo', token_env='AUTHORED_TOKEN')
    entry = result['configuration']
    assert entry['url'] == 'https://example.invalid/mcp/' and 'command' not in entry
    assert 'X-Attocode-Cancellation-Id' not in str(entry)
