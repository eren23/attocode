"""Real subprocess framing, request ordering and workspace-loop regression."""
import sys

from attocode_intel._internal.integrations.lsp.client import BUILTIN_SERVERS, LanguageServerConfig
from attocode_intel.gateway import OperationGateway

SERVER = r'''
import json, sys
from pathlib import Path
from urllib.parse import unquote, urlparse
root = None
opened = set()
pending_init = None

def send(value):
    body = json.dumps(value).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()

while True:
    header = sys.stdin.buffer.readline()
    if not header:
        break
    if not header.lower().startswith(b'content-length:'):
        continue
    size = int(header.split(b':')[1])
    while sys.stdin.buffer.readline().strip():
        pass
    msg = json.loads(sys.stdin.buffer.read(size))
    method, params = msg.get('method'), msg.get('params') or {}
    if method == 'initialize':
        root = Path(unquote(urlparse(params['rootUri']).path))
        pending_init = msg['id']
        # A server request may reuse a client request ID: direction matters.
        send({'jsonrpc':'2.0','id':msg['id'],'method':'workspace/configuration','params':{'items':[{}]}})
        continue
    if method is None and msg.get('id') == pending_init:
        assert msg['result'] == [None]
        send({'jsonrpc':'2.0','id':pending_init,'result':{'capabilities':{'definitionProvider':True,'referencesProvider':True}}})
        pending_init = None
        continue
    if method == 'textDocument/didOpen':
        opened.add(params['textDocument']['uri'])
    elif method == 'textDocument/didClose':
        opened.discard(params['textDocument']['uri'])
    elif method == 'exit':
        break
    if 'id' not in msg:
        continue
    result = None
    if method in ('textDocument/definition','textDocument/references'):
        uri = params['textDocument']['uri']
        assert uri in opened, 'Query arrived before didOpen'
        assert params['position'] == {'line': 0, 'character': 4}
        def location(path, line):
            return {'uri':path.as_uri(),'range':{'start':{'line':line,'character':0},'end':{'line':line,'character':6}}}
        if method.endswith('definition'):
            result = [location(root/'helper.py', 0)]
        else:
            result = [location(root/'caller.py', i) for i,s in enumerate((root/'caller.py').read_text().splitlines()) if 'helper()' in s]
    send({'jsonrpc':'2.0','id':msg['id'],'result':result})
'''


async def test_precise_references_across_calls_edits_and_shutdown(tmp_path, monkeypatch):
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    monkeypatch.setitem(BUILTIN_SERVERS, "python", LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=[".py"], language_id="python"))
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "auto")
    root = tmp_path / "project"
    root.mkdir()
    (root / "helper.py").write_text("def helper(): return 1\n")
    (root / "caller.py").write_text("from helper import helper\nhelper()\n")
    gateway = OperationGateway(str(root), "daily", watch=False)
    process = None
    try:
        for line in (1, 2):
            result = (await gateway.execute("cross_references", {"symbol_name": "helper"})).structuredContent
            assert result["metadata"]["analysis"]["precision"]["status"] == "verified"
            assert any(r["line"] == line + 1 and r["source"] == "lsp" for r in result["data"]["references"])
            store = next(iter(gateway._stores.values()))
            client = store["service"]._lsp_manager._clients["python"]
            if process is not None:
                assert process is client._process
            process = client._process
            (root / "caller.py").write_text("from helper import helper\n\nhelper()\n")
    finally:
        await gateway.close()
    assert process is not None and process.returncode == 0


async def test_missing_precision_keeps_syntax_results(tmp_path, monkeypatch):
    monkeypatch.setitem(BUILTIN_SERVERS, "python", LanguageServerConfig(
        command="attocode-deliberately-missing-language-server", extensions=[".py"], language_id="python"))
    (tmp_path / "helper.py").write_text("def helper(): return 1\nhelper()\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        result = (await gateway.execute("cross_references", {"symbol_name": "helper"})).structuredContent
        assert result["data"]["references"]
        assert result["metadata"]["analysis"]["precision"]["queries"][0]["status"] == "unavailable"
    finally:
        await gateway.close()


async def test_workspace_eviction_stops_its_language_server(tmp_path, monkeypatch):
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    monkeypatch.setitem(BUILTIN_SERVERS, "python", LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=[".py"], language_id="python"))
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
        (root / "helper.py").write_text("def helper(): return 1\n")
        (root / "caller.py").write_text("helper()\n")
    gateway = OperationGateway(profile="daily", watch=False, max_workspaces=1)
    try:
        await gateway.execute("cross_references", {"workspace": str(roots[0]), "symbol_name": "helper"})
        first = next(iter(gateway._stores.values()))["service"]._lsp_manager._clients["python"]._process
        second = await gateway.execute("cross_references", {"workspace": str(roots[1]), "symbol_name": "helper"})
        assert first.returncode == 0
        assert second.structuredContent["metadata"]["workspace"] == str(roots[1].resolve())
        assert second.structuredContent["metadata"]["analysis"]["precision"]["status"] == "verified"
    finally:
        await gateway.close()


async def test_manual_enrichment_starts_server_and_counts_verified_symbols(tmp_path, monkeypatch):
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    monkeypatch.setitem(BUILTIN_SERVERS, "python", LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=[".py"], language_id="python"))
    (tmp_path / "helper.py").write_text("def helper(): return 1\n")
    (tmp_path / "caller.py").write_text("helper()\n")
    gateway = OperationGateway(str(tmp_path), "full", watch=False)
    try:
        result = await gateway.execute("lsp_enrich", {"files": ["helper.py"]})
        assert not result.isError
        assert "Symbols enriched: 1" in result.content[0].text
    finally:
        await gateway.close()


async def test_noisy_server_timeout_preserves_navigation_and_shuts_down(tmp_path, monkeypatch):
    script = tmp_path / "server.py"
    script.write_text(SERVER.replace("root = None", "sys.stderr.write('x' * 1000000)\nsys.stderr.flush()\nroot = None")
                      .replace("uri = params['textDocument']['uri']", "if method.endswith('references'): continue\n        uri = params['textDocument']['uri']"))
    monkeypatch.setitem(BUILTIN_SERVERS, "python", LanguageServerConfig(
        command=sys.executable, args=[str(script)], extensions=[".py"], language_id="python"))
    (tmp_path / "helper.py").write_text("def helper(): return 1\n")
    (tmp_path / "caller.py").write_text("helper()\n")
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        result = (await gateway.execute("cross_references", {"symbol_name": "helper"})).structuredContent
        assert result["metadata"]["analysis"]["precision"]["queries"][0]["status"] == "timeout"
        assert any(ref["file_path"] == "caller.py" for ref in result["data"]["references"])
        lookup = await gateway.execute("search_symbols", {"name": "helper"})
        assert not lookup.isError
        process = next(iter(gateway._stores.values()))["service"]._lsp_manager._clients["python"]._process
    finally:
        await gateway.close()
    assert process.returncode == 0
