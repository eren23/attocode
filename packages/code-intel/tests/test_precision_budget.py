"""Rust reloads get more time without extending other languages or retry deadlines."""
import sys
import time

import pytest
from attocode_intel._internal.integrations.lsp.client import (
    BUILTIN_SERVERS,
    LSPConfig,
    LSPManager,
    LanguageServerConfig,
)
from attocode_intel.gateway import OperationGateway
from test_precision_protocol import SERVER
from test_precision_recovery import _status_server


def _gateway(tmp_path, monkeypatch, source, language='rust'):
    extension = '.rs' if language == 'rust' else '.py'
    if language == 'rust':
        source = (source.replace("'helper.py'", "'helper.rs'")
                  .replace("'caller.py'", "'caller.rs'")
                  .replace("'character': 4", "'character': 7"))
    script = tmp_path / 'server.py'
    script.write_text(source)
    monkeypatch.setitem(BUILTIN_SERVERS, language, LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=[extension], language_id=language))
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'auto')
    root = tmp_path / 'project'
    root.mkdir()
    if language == 'rust':
        (root / 'helper.rs').write_text('pub fn helper() -> i32 { 1 }\npub fn local() -> i32 { helper() }\n')
        (root / 'caller.rs').write_text('use crate::helper::helper;\npub fn caller() -> i32 { helper() }\n')
    else:
        (root / 'helper.py').write_text('def helper(): return 1\nhelper()\n')
        (root / 'caller.py').write_text('from helper import helper\nhelper()\n')
    return OperationGateway(str(root), 'daily', watch=False), root, extension


async def _inspect(gateway, extension='.rs'):
    response = await gateway.execute('inspect_symbol', {
        'symbol_name': 'helper', 'file_path': 'helper' + extension, 'line': 1})
    assert not response.isError
    return response.structuredContent


@pytest.mark.parametrize('delay', ['initialize', 'definition', 'readiness'])
async def test_rust_recovers_from_a_two_and_a_half_second_delay(tmp_path, monkeypatch, delay):
    if delay == 'readiness':
        source = _status_server(2.5)
    elif delay == 'initialize':
        source = SERVER.replace("        send({'jsonrpc':'2.0','id':pending_init,",
                                "        __import__('time').sleep(2.5)\n        send({'jsonrpc':'2.0','id':pending_init,")
    else:
        source = SERVER.replace('    result = None',
                                "    if method == 'textDocument/definition': __import__('time').sleep(2.5)\n    result = None")
    gateway, _root, _extension = _gateway(tmp_path, monkeypatch, source)
    try:
        result = await _inspect(gateway)
        assert result['metadata']['analysis']['precision']['status'] == 'verified', result
        assert any(r['file_path'] == 'caller.rs' and r['line'] == 2 and r['source'] == 'lsp'
                   for r in result['data']['references'])
    finally:
        await gateway.close()


async def test_running_rust_server_can_reload_after_an_edit(tmp_path, monkeypatch):
    source = (_status_server(2.5)
              .replace('ready = status = False', 'ready = status = reloading = False')
              .replace('threading.Timer(2.5, become_ready)', 'threading.Timer(2.5 if reloading else 0, become_ready)')
              .replace('    result = None', """
    if method == 'textDocument/didChange':
        ready = False
        timer = None
        reloading = True
        if status:
            send({'jsonrpc':'2.0','method':'experimental/serverStatus','params':{'health':'ok','quiescent':False}})
    result = None"""))
    gateway, root, _extension = _gateway(tmp_path, monkeypatch, source)
    try:
        first = await _inspect(gateway)
        assert first['metadata']['analysis']['precision']['status'] == 'verified'
        process = next(iter(gateway._stores.values()))['service']._lsp_manager._clients['rust']._process
        (root / 'caller.rs').write_text('use crate::helper::helper;\n\npub fn caller() -> i32 { helper() }\n')
        changed = await _inspect(gateway)
        assert changed['metadata']['analysis']['precision']['status'] == 'verified', changed
        assert any(r['file_path'] == 'caller.rs' and r['line'] == 3 and r['source'] == 'lsp'
                   for r in changed['data']['references'])
        assert not any(r['file_path'] == 'caller.rs' and r['line'] == 2
                       for r in changed['data']['references'])
        assert next(iter(gateway._stores.values()))['service']._lsp_manager._clients['rust']._process is process
    finally:
        await gateway.close()
    assert process.returncode == 0


@pytest.mark.parametrize('language, lower, upper', [('rust', 4.5, 5.8), ('python', 1.5, 2.8)])
async def test_unresponsive_server_is_bounded_and_preserves_syntax(tmp_path, monkeypatch, language, lower, upper):
    source = SERVER.replace('    result = None',
                            "    if method == 'textDocument/definition': continue\n    result = None")
    gateway, _root, extension = _gateway(tmp_path, monkeypatch, source, language)
    try:
        # Index before timing the enrichment rather than timing native parser startup.
        await gateway.execute('symbols', {'path': 'helper' + extension})
        started = time.monotonic()
        result = await _inspect(gateway, extension)
        assert lower <= time.monotonic() - started < upper
        precision = result['metadata']['analysis']['precision']
        assert precision['status'] == 'partial'
        assert precision['queries'][0]['status'] == 'timeout'
        assert any(r['file_path'] == 'helper' + extension for r in result['data']['references'])
    finally:
        await gateway.close()


async def test_rust_startup_and_lookup_share_one_five_second_deadline(tmp_path, monkeypatch):
    source = (SERVER.replace("        send({'jsonrpc':'2.0','id':pending_init,",
                             "        __import__('time').sleep(2.5)\n        send({'jsonrpc':'2.0','id':pending_init,")
              .replace('    result = None',
                       "    if method == 'textDocument/references': __import__('time').sleep(2.8)\n    result = None"))
    gateway, _root, _extension = _gateway(tmp_path, monkeypatch, source)
    try:
        await gateway.execute('symbols', {'path': 'helper.rs'})
        started = time.monotonic()
        result = await _inspect(gateway)
        assert 4.5 <= time.monotonic() - started < 5.8
        assert result['metadata']['analysis']['precision']['queries'][0]['status'] == 'timeout'
        assert result['data']['references']
    finally:
        await gateway.close()


async def test_client_timeout_override_does_not_leak_to_other_servers(tmp_path, monkeypatch):
    # Both peers use the same framed protocol; only their timeout policies differ.
    script = tmp_path / 'server.py'
    script.write_text(SERVER.replace('    result = None',
                                   "    if method == 'test/delayed': __import__('time').sleep(0.4)\n    result = None"))
    for language in ('rust', 'python'):
        monkeypatch.setitem(BUILTIN_SERVERS, language, LanguageServerConfig(
            command=sys.executable, args=[str(script)], language_id=language))
    manager = LSPManager(LSPConfig(timeout=0.25))
    try:
        await manager.start_server('rust', tmp_path.as_uri(), timeout=5.0)
        await manager.start_server('python', tmp_path.as_uri())
        for language, succeeds in [('rust', True), ('python', False)]:
            client = manager._clients[language]
            if succeeds:
                assert await client._request('test/delayed', {}) is None
            else:
                from attocode_intel._internal.errors import ToolError
                with pytest.raises(ToolError, match='timed out'):
                    await client._request('test/delayed', {})
    finally:
        await manager.stop_all()
