"""Actual TCP/JWT cancellation cannot escape its owner, context or typed ID."""
import asyncio

import pytest
from http_cancel_child import CLIENT_ID
from http_cancel_fixture import _actor, _payload, _rows


def _request(identity):
    return {'jsonrpc': '2.0', 'id': identity, 'method': 'tools/call', 'params': {
        'name': 'inspect_symbol', 'arguments': {
            'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000}}}


async def _cancel(actor, identity):
    await actor.notify('notifications/cancelled', {'requestId': identity})


async def test_http_context_and_authority_isolation(tmp_path, monkeypatch, request, record_property):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        await _cancel(actor, 'target')  # Unknown now must not cancel a future reuse.
        await actor.rpc('before', 'tools/list', {})
        target = actor.task(actor.send(_request('target')))
        await actor.blocked()
        assert not target.done()
        record_property('qualified_input', 'true')
        original = dict(actor.headers)
        await actor.notify('notifications/cancelled', {'requestId': 'target'}, valid_auth=False)
        for identity, headers in (
            ('bob', original), ('alice2', original),
            ('alice', {**original, 'X-Attocode-Cancellation-Id': '87654321-4321-4abc-8abc-123456789abc'}),
            ('alice', {**original, 'X-Attocode-Workspace': 'another-workspace'}),
            ('alice', {**original, 'X-Attocode-Profile': 'full'}),
            ('alice', {}),
        ):
            actor.identity, actor.headers = identity, dict(headers)
            await _cancel(actor, 'target')
            await actor.rpc('other-owner-probe', 'tools/list', {})
            assert not target.done()
        assert not any(r['kind'] == 'sdk_cancel' for r in _rows(actor.journal))
        actor.identity, actor.headers = 'alice', original
        await _cancel(actor, 'target')
        await _cancel(actor, 'target')  # Repeated notification after response is harmless.
        response = await asyncio.wait_for(target, 1)
        assert response.json()['error']['message'] == 'Request cancelled'
        await actor.event('precision_cancelled', 'target', timeout=1)
        assert len([r for r in _rows(actor.journal) if r['kind'] == 'sdk_cancel']) == 1
        actor.ready.touch()
        assert _payload(await actor.call('recovered'))['metadata']['precision'] == 'verified'


@pytest.mark.parametrize('mode', ['typed_ids', 'different_contexts'])
async def test_overlapping_ids_route_only_to_selected_post(tmp_path, monkeypatch, request, record_property, mode):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        first_id, second_id = (1, '1') if mode == 'typed_ids' else ('shared', 'shared')
        first = actor.task(actor.send(_request(first_id)))
        await actor.blocked()
        if mode == 'different_contexts':
            actor.headers['X-Attocode-Cancellation-Id'] = '87654321-4321-4abc-8abc-123456789abc'
        second = actor.task(actor.send(_request(second_id)))
        async with asyncio.timeout(1):
            while len([r for r in _rows(actor.journal) if r['kind'] == 'gateway_called'
                       and r['request_id'] in (first_id, second_id) and r['operation'] == 'inspect_symbol']) < 2:
                await asyncio.sleep(.005)
        assert not first.done() and not second.done()
        record_property('qualified_input', 'true')
        await _cancel(actor, second_id)
        second_response = await asyncio.wait_for(second, 1)
        assert second_response.json()['id'] == second_id
        assert second_response.json()['error']['message'] == 'Request cancelled'
        assert not first.done()
        actor.headers['X-Attocode-Cancellation-Id'] = CLIENT_ID
        await _cancel(actor, first_id)
        assert (await asyncio.wait_for(first, 1)).json()['error']['message'] == 'Request cancelled'
        actor.ready.touch()
        assert _payload(await actor.call('recovered'))['metadata']['precision'] == 'verified'


async def test_duplicate_active_id_does_not_dispatch_or_replace_original(tmp_path, monkeypatch, request, record_property):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        first = actor.task(actor.send(_request('target')))
        await actor.blocked()
        duplicate = await actor.send(_request('target'))
        assert duplicate.status_code == 200
        assert duplicate.json()['error']['code'] == -32600
        assert 'already active' in duplicate.json()['error']['message']
        calls = [r for r in _rows(actor.journal) if r['kind'] == 'gateway_called' and r['request_id'] == 'target']
        assert len(calls) == 1 and not first.done()
        record_property('qualified_input', 'true')
        await _cancel(actor, 'target')
        assert (await asyncio.wait_for(first, 1)).json()['error']['message'] == 'Request cancelled'
        actor.ready.touch()
        assert _payload(await actor.call('recovered'))['metadata']['precision'] == 'verified'


@pytest.mark.parametrize('enabled', [True, False])
async def test_context_validation_follows_authentication_and_feature_flag(
        tmp_path, monkeypatch, request, record_property, enabled):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1' if enabled else '0')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        actor.headers['X-Attocode-Cancellation-Id'] = 'invalid-context'
        message = {'jsonrpc': '2.0', 'id': 'probe', 'method': 'tools/list', 'params': {}}
        assert (await actor.send(message, valid_auth=False)).status_code == 401
        response = await actor.send(message)
        assert response.status_code == (400 if enabled else 200)
        actor.headers.clear()
        assert (await actor.send(message)).status_code == 200
