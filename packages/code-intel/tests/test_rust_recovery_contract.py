"""Prospective M5 controls; unqualified until their first online diagnostic run."""
import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest
from test_precision_budget import _gateway, _inspect
from test_precision_protocol import SERVER


def _source_receipt(record_property, phase):
    repo = Path(__file__).resolve().parents[3]
    paths = subprocess.check_output(['git','ls-files','-z'],cwd=repo).decode().split('\0')
    files = {p:hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in paths if p}
    result = {'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
              'files':files}
    record_property('source_' + phase, json.dumps(result))
    return result


def _controlled_source(ready, journal):
    record = f"""
    if method in ('textDocument/didOpen', 'textDocument/didChange',
                  'textDocument/didClose', 'textDocument/definition',
                  'textDocument/references'):
        with open({str(journal)!r}, 'a') as stream:
            stream.write(json.dumps({{'method':method,'params':params}}) + '\\n')
    if method == 'textDocument/didChange' and not Path({str(ready)!r}).exists():
        send({{'jsonrpc':'2.0','method':'experimental/serverStatus',
              'params':{{'health':'ok','quiescent':False}}}})
"""
    gate = f"""
    if method in ('textDocument/definition', 'textDocument/references'):
        if not Path({str(ready)!r}).exists():
            send({{'jsonrpc':'2.0','method':'experimental/serverStatus',
                  'params':{{'health':'ok','quiescent':False}}}})
            send({{'jsonrpc':'2.0','id':msg['id'],'result':None}})
            continue
        send({{'jsonrpc':'2.0','method':'experimental/serverStatus',
              'params':{{'health':'ok','quiescent':True}}}})
"""
    source = SERVER.replace("    if 'id' not in msg:", record + "\n    if 'id' not in msg:")
    source = source.replace('    result = None', gate + '\n    result = None')
    old = "result = [location(root/'caller.py', i) for i,s in enumerate((root/'caller.py').read_text().splitlines()) if 'helper()' in s]"
    assert source.count(old) == 1
    replacement = (
        '(' + old.removeprefix('result = ') + " if (root/'caller.py').is_file() else [])"
        " + [location(root/'helper.py', i) for i,s in enumerate((root/'helper.py').read_text().splitlines())"
        " if i > 0 and 'helper()' in s]"
    )
    return source.replace(old, 'result = ' + replacement)


def _events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize('after_partial', ['edit', 'delete'])
async def test_long_rust_reload_recovers_on_a_later_request(
        tmp_path, monkeypatch, record_property, after_partial):
    import attocode_intel.precision as precision

    ready, journal = tmp_path / 'ready', tmp_path / 'protocol.jsonl'
    ready.touch()
    clock = [1000.0]
    monkeypatch.setattr(precision, '_now', lambda: clock[0])
    source_before = _source_receipt(record_property, 'before')
    gateway, root, _ = _gateway(tmp_path, monkeypatch, _controlled_source(ready, journal))
    record_property('peer_source', (tmp_path / 'server.py').read_text())
    process = None
    try:
        initial = await _inspect(gateway)
        assert initial['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(r['file_path'] == 'caller.rs' and r['line'] == 2 and r['source'] == 'lsp'
                   for r in initial['data']['references'])
        stores = next(iter(gateway._stores.values()))
        process = stores['service']._lsp_manager._clients['rust']._process
        ready.unlink()
        helper, caller = root / 'helper.rs', root / 'caller.rs'
        helper.write_text(helper.read_text() + '\n')
        caller.write_text('use crate::helper::helper;\n\npub fn caller() -> i32 { helper() }\n')
        before = len(_events(journal))
        started = time.monotonic()
        partial = await _inspect(gateway)
        elapsed = time.monotonic() - started
        p = partial['metadata']['analysis']['precision']
        events = _events(journal)[before:]
        assert any(e['method'] == 'textDocument/didChange' for e in events)
        assert any(e['method'] == 'textDocument/definition' for e in events)
        assert not ready.exists() and process.returncode is None
        record_property('qualified_input', 'true')
        record_property('partial_elapsed', elapsed)
        record_property('partial_precision', json.dumps(p))
        record_property('partial_response', json.dumps(partial))
        assert 4.0 <= elapsed < 5.8
        assert p['status'] == 'partial' and p['queries'][0]['status'] == 'not_resolved'
        # This two-file fixture has no crate entrypoint. Preserve the written
        # cross-file call as a candidate, without claiming an import binding.
        assert any(r['file_path'] == 'caller.rs' and r['line'] == 3 and
                   r['source'] != 'lsp' and r['resolution'] == 'same_name_candidate'
                   for r in partial['data']['reference_candidates'])
        assert any(r['file_path'] == 'helper.rs' and r['line'] == 2 and
                   r['source'] != 'lsp' and r['resolution'] == 'same_file'
                   for r in partial['data']['references'])
        assert not any(r['file_path'] == 'caller.rs' and r['line'] == 2 and r['source'] == 'lsp'
                       for r in partial['data']['references'])
        sent = _events(journal)
        cached = await _inspect(gateway)
        assert cached['metadata']['analysis']['precision'] == p
        assert _events(journal) == sent
        response = await gateway.execute('search_symbols', {'name':'local'})
        assert not response.isError
        if after_partial == 'delete':
            caller.unlink()
        ready.touch()
        clock[0] += 2.0  # Only cache time advances; asyncio's deadline remains real.
        recovered = await _inspect(gateway)
        assert recovered['metadata']['analysis']['precision']['status'] == 'verified'
        if after_partial == 'edit':
            assert any(r['file_path'] == 'caller.rs' and r['line'] == 3 and r['source'] == 'lsp'
                       for r in recovered['data']['references'])
        else:
            assert not any(r['file_path'] == 'caller.rs' for r in recovered['data']['references'])
            assert any(e['method'] == 'textDocument/didClose' and
                       e['params']['textDocument']['uri'].endswith('/caller.rs')
                       for e in _events(journal))
        assert stores['service']._lsp_manager._clients['rust']._process is process
        sent = _events(journal)
        again = await _inspect(gateway)
        assert again['metadata']['analysis']['precision']['status'] == 'verified'
        assert _events(journal) == sent
    finally:
        started = time.monotonic()
        await gateway.close()
        record_property('shutdown_elapsed', time.monotonic() - started)
        assert time.monotonic() - started < 6.0
        if journal.exists():
            record_property('protocol', json.dumps(_events(journal)))
        record_property('process_returncode', process.returncode if process else None)
        assert _source_receipt(record_property, 'after') == source_before
    assert process is not None and process.returncode == 0


async def test_cancelled_rust_enrichment_restores_callback_and_can_retry(
        tmp_path, monkeypatch, record_property):
    from attocode_intel.precision import PrecisionSession

    ready, journal = tmp_path / 'ready', tmp_path / 'protocol.jsonl'
    source_before = _source_receipt(record_property, 'before')
    gateway, root, _ = _gateway(tmp_path, monkeypatch, _controlled_source(ready, journal))
    record_property('peer_source', (tmp_path / 'server.py').read_text())
    task = None
    process = None
    try:
        await gateway.execute('symbols', {'path':'helper.rs'})
        stores = next(iter(gateway._stores.values()))
        service = stores['service']
        session = stores.setdefault('precision', PrecisionSession(service))
        manager = service._get_lsp_manager()
        callback = manager.on_result_callback
        assert callback is not None
        worker = next(iter(gateway._workers.values()))

        async def qualify_and_cancel():
            nonlocal task, process
            task = asyncio.create_task(session.enrich('helper', 'helper.rs', 1))
            try:
                async with asyncio.timeout(3):
                    while not journal.exists() or not any(
                            e['method'] == 'textDocument/definition' for e in _events(journal)):
                        await asyncio.sleep(.01)
                assert not task.done() and not ready.exists()
                process = manager._clients['rust']._process
                record_property('qualified_input', 'true')
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert manager.on_result_callback is callback
                assert not session.completed and not session.retry_after
                ready.touch()
                result = await session.enrich('helper', 'helper.rs', 1)
                assert result['status'] == 'verified'
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        def run():
            return stores.setdefault('async_runner', asyncio.Runner()).run(qualify_and_cancel())

        await asyncio.get_running_loop().run_in_executor(worker, run)
        recovered = await _inspect(gateway)
        assert recovered['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(r['file_path'] == 'caller.rs' and r['source'] == 'lsp'
                   for r in recovered['data']['references'])
    finally:
        await gateway.close()
        if journal.exists():
            record_property('protocol', json.dumps(_events(journal)))
        record_property('process_returncode', process.returncode if process else None)
        assert _source_receipt(record_property, 'after') == source_before
    assert process is not None and process.returncode == 0
