"""Explicit HTTP cancellation reaches the original authenticated SDK session."""
import asyncio
import time

import pytest
from http_cancel_fixture import _actor, _payload, _rows


@pytest.mark.parametrize('phase', ['initialize', 'definition'])
async def test_http_cancel_reaches_precision(tmp_path, monkeypatch, request, record_property, phase):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with _actor(tmp_path, request, record_property, 'http', phase) as actor:
        target = actor.task(actor.rpc('target', 'tools/call', {'name': 'inspect_symbol', 'arguments': {
            'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000}}))
        await actor.blocked()
        assert not target.done()
        auth = [r for r in _rows(actor.journal) if r['kind'] == 'auth_resolved']
        assert auth and auth[-1]['method'] == 'jwt'
        assert auth[-1]['user_id'] == '11111111-1111-4111-8111-111111111111'
        record_property('qualified_input', 'true')
        record_property('entrypoint', 'http')
        record_property('blocked_phase', phase)
        started = time.monotonic()
        await actor.notify('notifications/cancelled', {'requestId': 'target', 'reason': 'authored client cancellation'})
        done, _ = await asyncio.wait({target}, timeout=1)
        assert done, 'REGRESSION: HTTP cancellation does not reach the active precision worker'
        response = await target
        assert response.get('error', {}).get('message') == 'Request cancelled'
        cancelled = await actor.event('precision_cancelled', 'target', timeout=1)
        state = cancelled['state']
        assert state['callback_restored'] and state['pending'] == state['completed'] == state['retry_after'] == 0
        async with asyncio.timeout(1):
            result = await actor.call('barrier', 'symbols', {'path': 'helper.rs'})
        assert not result.get('isError')
        record_property('cancel_to_worker_reuse', time.monotonic() - started)
        actor.ready.touch()
        recovered = _payload(await actor.call('recovered'))
        assert recovered['metadata']['precision'] == 'verified'
        assert any(r['file_path'] == 'caller.rs' and r['source'] == 'lsp' for r in recovered['data']['references'])
        await actor.notify('notifications/cancelled', {'requestId': 'recovered'})
        assert _payload(await actor.call('after_completed_cancel'))['metadata']['precision'] == 'verified'


@pytest.mark.parametrize('mode', ['default_off', 'missing_context'])
async def test_http_default_behavior_remains_bounded(tmp_path, monkeypatch, request, record_property, mode):
    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1' if mode == 'missing_context' else '0')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        if mode == 'missing_context':
            actor.headers.clear()
        target = actor.task(actor.call('target'))
        await actor.blocked()
        assert not target.done()
        record_property('qualified_input', 'true')
        await actor.notify('notifications/cancelled', {'requestId': 'target'})
        result = _payload(await target)
        finished = await actor.event('precision_finished', 'target')
        assert 4.5 <= finished['elapsed'] < 5.8
        assert result['metadata']['precision'] == 'partial'
        assert not any(r['kind'] == 'precision_cancelled' for r in _rows(actor.journal))
        actor.ready.touch()
        await asyncio.sleep(1.05)
        assert _payload(await actor.call('recovered'))['metadata']['precision'] == 'verified'
