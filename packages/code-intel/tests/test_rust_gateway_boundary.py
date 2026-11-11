"""Gateway cancellation must reach its worker, without changing retry budgets."""
import asyncio
import json
import time

import pytest
from test_precision_budget import _gateway
from test_precision_protocol import SERVER


def _source(ready, journal, phase='definition', failure=False, block=False):
    condition = ("method == 'initialize'" if phase == 'initialize' else
                 "method in ('textDocument/definition', 'textDocument/references')")
    gate = f"""
    with open({str(journal)!r}, 'a') as stream:
        stream.write(json.dumps({{'method': method, 'id': msg.get('id')}}) + '\\n')
    if {condition} and not Path({str(ready)!r}).exists():
        if {failure!r}:
            send({{'jsonrpc': '2.0', 'id': msg['id'], 'error': {{'code': -32603, 'message': 'fixture startup failure'}}}})
        elif {not block and phase != 'initialize'!r}:
            send({{'jsonrpc': '2.0', 'id': msg['id'], 'result': None}})
        continue
"""
    anchor = "    if method == 'initialize':"
    assert SERVER.count(anchor) == 1
    return SERVER.replace(anchor, gate + '\n' + anchor)


def _journal(path):
    if not path.exists():
        return []
    raw = path.read_text()
    return [json.loads(line) for line in raw.splitlines(keepends=True) if line.endswith('\n')]


async def _inspect(gateway):
    response = await gateway.execute_mcp('inspect_symbol', {
        'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000})
    assert not response.isError
    return json.loads(response.content[0].text)


def _snapshot(stores, manager, callback):
    session = stores.get('precision')
    return {
        'callback_restored': manager.on_result_callback is callback,
        'completed': len(session.completed) if session else 0,
        'retry_after': len(session.retry_after) if session else 0,
        'pending': sum(len(client._pending) for client in manager._clients.values()),
    }


@pytest.mark.parametrize('phase', ['initialize', 'definition'])
async def test_public_cancellation_releases_workspace_worker(
        tmp_path, monkeypatch, record_property, phase):
    # Losing the cancellation at run_in_executor leaves this real worker blocked.
    ready, journal = tmp_path / 'ready', tmp_path / 'protocol.jsonl'
    source = _source(ready, journal, phase, block=True)
    processes = []
    spawn = asyncio.create_subprocess_exec

    async def record_spawn(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', record_spawn)
    gateway, _root, _ = _gateway(tmp_path, monkeypatch, source)
    task = None
    try:
        await gateway.execute('symbols', {'path': 'helper.rs'})
        stores = next(iter(gateway._stores.values()))
        manager = stores['service']._get_lsp_manager()
        callback = manager.on_result_callback
        assert callback is not None
        worker = next(iter(gateway._workers.values()))
        task = asyncio.create_task(_inspect(gateway))
        method = 'initialize' if phase == 'initialize' else 'textDocument/definition'
        async with asyncio.timeout(3):
            while not any(event['method'] == method for event in _journal(journal)):
                await asyncio.sleep(.01)
        assert not task.done() and len(processes) == 1 and processes[0].returncode is None
        record_property('qualified_input', 'true')
        record_property('public_entrypoint', 'execute_mcp')
        record_property('blocked_phase', phase)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        started = time.monotonic()
        barrier = asyncio.wrap_future(worker.submit(_snapshot, stores, manager, callback))
        try:
            state = await asyncio.wait_for(asyncio.shield(barrier), 1.0)
        except TimeoutError:
            state = None
        record_property('worker_release_elapsed', time.monotonic() - started)
        record_property('worker_state', json.dumps(state))
        assert state is not None, 'REGRESSION: public cancellation leaves precision running on the workspace worker'
        assert state == {'callback_restored': True, 'completed': 0, 'retry_after': 0, 'pending': 0}
        if phase == 'initialize':
            assert processes[0].returncode is not None
        ready.touch()
        recovered = await _inspect(gateway)
        assert recovered['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(ref['file_path'] == 'caller.rs' and ref['source'] == 'lsp'
                   for ref in recovered['data']['references'])
        if phase == 'definition':
            assert len(processes) == 1  # Healthy server is reused, not killed.
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        started = time.monotonic()
        await gateway.close()
        record_property('shutdown_elapsed', time.monotonic() - started)
        record_property('owned_process_exit_codes', json.dumps([p.returncode for p in processes]))
        record_property('protocol', json.dumps(_journal(journal)))
        assert processes and all(p.returncode is not None for p in processes)


@pytest.mark.parametrize('phase', ['initialize', 'definition'])
@pytest.mark.parametrize('offset, retries', [(-.000001, False), (0.0, True), (.000001, True)],
                         ids=['below', 'equal', 'above'])
async def test_retry_boundary_is_one_second(
        tmp_path, monkeypatch, record_property, phase, offset, retries):
    # Using <= instead of <, or ignoring the cooldown, breaks these public outcomes.
    import attocode_intel.precision as precision

    clock = [1000.0]
    monkeypatch.setattr(precision, '_now', lambda: clock[0])
    ready, journal = tmp_path / 'ready', tmp_path / 'protocol.jsonl'
    gateway, _root, _ = _gateway(
        tmp_path, monkeypatch, _source(ready, journal, phase, failure=phase == 'initialize'))
    try:
        first = await _inspect(gateway)
        outcome = first['metadata']['analysis']['precision']
        assert outcome['status'] == 'partial'
        assert outcome['queries'][0]['status'] == ('failed' if phase == 'initialize' else 'not_resolved')
        ready.touch()
        before = _journal(journal)
        clock[0] = 1001.0 + offset
        result = await _inspect(gateway)
        actual = result['metadata']['analysis']['precision']['status']
        assert actual == ('verified' if retries else 'partial')
        assert (_journal(journal) != before) is retries
        if retries:
            assert any(ref['file_path'] == 'caller.rs' and ref['source'] == 'lsp'
                       for ref in result['data']['references'])
        record_property('qualified_input', 'true')
        record_property('cache_clock', clock[0])
        record_property('precision', json.dumps(result['metadata']['analysis']['precision']))
    finally:
        await gateway.close()


async def test_uncancelled_public_call_retains_verified_evidence(tmp_path, monkeypatch):
    ready, journal = tmp_path / 'ready', tmp_path / 'protocol.jsonl'
    ready.touch()
    gateway, _root, _ = _gateway(tmp_path, monkeypatch, _source(ready, journal))
    try:
        result = await _inspect(gateway)
        assert result['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(ref['file_path'] == 'caller.rs' and ref['source'] == 'lsp'
                   for ref in result['data']['references'])
        before = _journal(journal)
        assert (await _inspect(gateway))['metadata']['analysis']['precision']['status'] == 'verified'
        assert _journal(journal) == before
    finally:
        await gateway.close()
