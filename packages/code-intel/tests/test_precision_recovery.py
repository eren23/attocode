"""A transient server result must not poison an unchanged workspace session."""
import sys

import pytest
from attocode_intel._internal.integrations.lsp.client import BUILTIN_SERVERS, LanguageServerConfig
from attocode_intel.gateway import OperationGateway
from test_precision_protocol import SERVER


@pytest.mark.parametrize("mode, expected", [("empty", "not_resolved"), ("error", "failed"),
                                           ("timeout", "timeout"), ("references", "no_references")])
async def test_unresolved_server_can_recover_without_source_edit(tmp_path, monkeypatch, mode, expected):
    ready = tmp_path / 'ready'
    requests = tmp_path / 'requests'
    script = tmp_path / 'server.py'
    gate = f'''
    if method in ('textDocument/definition', 'textDocument/references'):
        with open({str(requests)!r}, 'a') as stream: stream.write(method + '\\n')
        if not Path({str(ready)!r}).exists():
            if {mode!r} == 'timeout': continue
            if {mode!r} == 'error':
                send({{'jsonrpc':'2.0', 'id':msg['id'], 'error':{{'code':-32801,'message':'content modified'}}}})
                continue
            if {mode!r} != 'references' or method.endswith('references'):
                send({{'jsonrpc':'2.0', 'id':msg['id'], 'result':None}})
                continue
'''
    script.write_text(SERVER.replace('    result = None', gate + '\n    result = None'))
    monkeypatch.setitem(BUILTIN_SERVERS, 'python', LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=['.py'], language_id='python'))
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'auto')
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'helper.py').write_text('def helper(): return 1\n')
    (root / 'caller.py').write_text('from helper import helper\nhelper()\n')
    import attocode_intel.precision as precision
    clock = [100.0]
    monkeypatch.setattr(precision, '_now', lambda: clock[0], raising=False)
    gateway = OperationGateway(str(root), 'daily', watch=False)
    try:
        async def inspect():
            response = await gateway.execute('inspect_symbol', {
                'symbol_name':'helper', 'file_path':'helper.py', 'line':1})
            assert not response.isError
            return response.structuredContent
        first = await inspect()
        assert first['metadata']['analysis']['precision']['queries'][0]['status'] == expected
        assert any(r['file_path'] == 'caller.py' for r in first['data']['references'])
        # Advance only the retry clock; source files and freshness stay unchanged.
        ready.touch()
        sent = requests.read_text()
        cached = await inspect()
        assert cached['metadata']['analysis']['precision']['status'] == 'partial'
        assert requests.read_text() == sent
        clock[0] += 10
        recovered = await inspect()
        assert recovered['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(r['file_path'] == 'caller.py' and r['source'] == 'lsp'
                   for r in recovered['data']['references'])
        sent = requests.read_text()
        again = await inspect()
        assert again['metadata']['analysis']['precision']['status'] == 'verified'
        assert requests.read_text() == sent  # successful evidence remains cached
    finally:
        await gateway.close()


@pytest.mark.parametrize('transient', ['null', 'content_modified'])
async def test_transient_symbol_lookup_recovers_within_original_deadline(tmp_path, monkeypatch, transient):
    script = tmp_path / 'server.py'
    gate = f'''
    if method in ('textDocument/definition', 'textDocument/references'):
        lookup_count += 1
        if lookup_count <= 3:
            if {transient!r} == 'content_modified':
                send({{'jsonrpc':'2.0','id':msg['id'],'error':{{'code':-32801,'message':'content modified'}}}})
            else:
                send({{'jsonrpc':'2.0','id':msg['id'],'result':None}})
            continue
'''
    script.write_text(SERVER.replace('root = None', 'lookup_count = 0\nroot = None').replace(
        '    result = None', gate + '\n    result = None'))
    monkeypatch.setitem(BUILTIN_SERVERS, 'python', LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=['.py'], language_id='python'))
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'auto')
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'helper.py').write_text('def helper(): return 1\n')
    (root / 'caller.py').write_text('from helper import helper\nhelper()\n')
    gateway = OperationGateway(str(root), 'daily', watch=False)
    try:
        response = await gateway.execute('inspect_symbol', {
            'symbol_name':'helper', 'file_path':'helper.py', 'line':1})
        result = response.structuredContent
        assert not response.isError
        assert result['metadata']['analysis']['precision']['status'] == 'verified'
        assert any(r['source'] == 'lsp' for r in result['data']['references'])
    finally:
        await gateway.close()
