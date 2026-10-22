"""CI evidence must include startup, failure context and bounded stream history."""
import asyncio
import json
import shutil

import pytest


class RustPeer:
    """Only the external process is replaced; client and gateway remain real."""
    def __init__(self, failure=None):
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdin = self
        self.returncode, self.pid = None, 12345
        self.pending, self.documents = [], {}
        self.root = ''
        self.failure = failure
        self.warmed = False
        self.fail_queries = False
        self.exited = asyncio.Event()
        self.sent = []

    def write(self, frame):
        _header, content = frame.split(b'\r\n\r\n', 1)
        self.pending.append(json.loads(content))

    def reply(self, request, result, *, error=None):
        response = {'error': error} if error else {'result': result}
        raw = json.dumps({'jsonrpc': '2.0', 'id': request['id'], **response}).encode()
        self.stdout.feed_data(f'Content-Length: {len(raw)}\r\n\r\n'.encode() + raw)

    async def drain(self):
        while self.pending:
            message = self.pending.pop(0)
            self.sent.append(message)
            method, params = message.get('method'), message.get('params') or {}
            if method == 'initialize':
                self.root = params['rootUri']
                self.stderr.feed_data(b'workspace initial load\n')
                self.reply(message, {'capabilities': {}, 'serverInfo': {'name': 'synthetic-rust-peer', 'version': 'fixture-v1'}},
                           error={'code': -32603, 'message': 'forced initialize failure'} if self.failure == 'warmup' else None)
            elif method in {'textDocument/didOpen', 'textDocument/didChange'}:
                doc = params['textDocument']
                self.documents[doc['uri']] = doc.get('text', params.get('contentChanges', [{}])[0].get('text', ''))
            elif method == 'textDocument/definition':
                uri = params['textDocument']['uri']
                changed = 'second::helper' in self.documents.get(self.root + '/src/lib.rs', '')
                self.fail_queries = self.failure == 'selected_original' or (self.failure == 'selected_after_edit' and changed)
                self.reply(message, None if self.fail_queries else [{'uri': uri, 'range': {
                    'start': {'line': 0, 'character': 7}, 'end': {'line': 0, 'character': 13}}}])
            elif method == 'textDocument/references':
                uri = params['textDocument']['uri']
                changed = 'second::helper' in self.documents.get(self.root + '/src/lib.rs', '')
                active = '/src/second.rs' if changed else '/src/first.rs'
                result = [{'uri': self.root + '/src/lib.rs', 'range': {
                    'start': {'line': 3 if changed else 2, 'character': 35},
                    'end': {'line': 3 if changed else 2, 'character': 41}}}] if uri.endswith(active) else []
                self.reply(message, None if self.fail_queries else result)
                self.warmed = True
            elif method == 'shutdown':
                self.reply(message, None)
            elif method == 'exit':
                self.close()

    def close(self):
        if self.returncode is None:
            self.returncode = 0
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.exited.set()

    async def wait(self):
        await self.exited.wait()
        return self.returncode


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


async def existing_flow(tmp_path, monkeypatch, failure=None):
    from attocode_intel._internal.errors import ToolError
    from test_real_language_server import test_real_server_warmed_selected_definition_and_edit

    peer = None
    which = shutil.which
    monkeypatch.setattr(shutil, 'which', lambda name: '/synthetic/rust-analyzer' if name == 'rust-analyzer' else which(name))
    async def spawn(*args, **kwargs):
        nonlocal peer
        assert peer is None
        peer = RustPeer(failure)
        return peer
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    destination = tmp_path / 'artifacts'
    monkeypatch.setenv('QUALITY_REAL_LSP_LANGUAGES', 'rust')
    monkeypatch.setenv('QUALITY_LSP_TRACE_DIR', str(destination))
    try:
        if failure:
            with pytest.raises(ToolError if failure == 'warmup' else AssertionError):
                await test_real_server_warmed_selected_definition_and_edit(tmp_path / 'workspace', monkeypatch, 'rust')
        else:
            await test_real_server_warmed_selected_definition_and_edit(tmp_path / 'workspace', monkeypatch, 'rust')
    finally:
        if peer is not None:
            peer.close()
    return peer, destination / 'lsp-diagnostic-rust.jsonl'


async def test_real_test_capture_includes_initialize_documents_and_shutdown(tmp_path, monkeypatch):
    peer, path = await existing_flow(tmp_path, monkeypatch)
    assert path.exists(), 'The CI trace must begin before language-server initialization'
    data = rows(path)
    assert data[0]['kind'] == 'trace_start' and data[0]['schema_version'] == 1
    protocol = [r for r in data if r['kind'] == 'protocol']
    initialize = next(r for r in protocol if r['direction'] == 'out' and r['message'].get('method') == 'initialize')
    reply = next(r for r in protocol if r['direction'] == 'in' and 'method' not in r['message'] and r['message'].get('id') == initialize['message']['id'])
    assert reply['message']['result']['serverInfo'] == {'name': 'synthetic-rust-peer', 'version': 'fixture-v1'}
    assert any(r['kind'] == 'stderr' and 'workspace initial load' in r['text'] for r in data)
    changed = next(r for r in protocol if r['direction'] == 'out' and r['message'].get('method') == 'textDocument/didChange')
    assert changed['message']['params']['textDocument']['version'] == 2
    assert any(r.get('documents', {}).get(peer.root + '/src/lib.rs', {}).get('version') == 2 for r in protocol)
    assert data[-1]['kind'] == 'trace_end' and data[-1]['status'] == 'passed'
    assert data[-1]['first_failure'] is None and data[-1]['dropped_events'] == 0
    assert any(r['kind'] == 'server_stop' and r['returncode'] == 0 for r in data)
    assert peer.returncode == 0


@pytest.mark.parametrize('failure', ['warmup', 'selected_original', 'selected_after_edit'])
async def test_original_failure_stage_survives_gateway_cleanup(tmp_path, monkeypatch, failure):
    peer, path = await existing_flow(tmp_path, monkeypatch, failure)
    assert path.exists(), 'Keep initialization and failure evidence on the original failing attempt'
    data = rows(path)
    assert data[-1]['status'] == 'failed'
    assert data[-1]['first_failure']['stage'] == failure
    assert data[-1]['first_failure']['type'] == ('ToolError' if failure == 'warmup' else 'AssertionError')
    assert any(r['kind'] == 'protocol' and r['message'].get('method') == 'initialize' for r in data)
    assert any(r['kind'] == 'server_stop' and r['returncode'] == 0 for r in data)
    assert peer.returncode == 0


def test_bounded_trace_retains_startup_and_recent_tail(tmp_path, monkeypatch):
    from eval.quality.lsp_trace import LSPTrace

    path = tmp_path / 'trace.jsonl'
    trace = LSPTrace(path, 'file:///workspace', max_bytes=16384, event_bytes=1024)
    with trace.capture(monkeypatch):
        trace.record('startup_canary', value='initialize evidence')
        partial = rows(path)
        assert partial[0]['kind'] == 'trace_start'
        assert partial[-1]['kind'] == 'startup_canary'  # Flushed before finalization.
        assert not any(r['kind'] == 'trace_end' for r in partial)
        for index in range(2000):
            trace.record('noise', value='x' * 400, counter=index)
        trace.record('last_canary', value='shutdown evidence')
    data = rows(path)
    assert path.stat().st_size <= 16384
    assert any(r['kind'] == 'startup_canary' for r in data)
    assert any(r['kind'] == 'last_canary' for r in data)
    assert data[-1]['dropped_events'] > 0 and data[-1]['truncated'] is True
    assert [r['index'] for r in data] == sorted({r['index'] for r in data})


def test_oversize_event_cannot_exceed_file_bound(tmp_path, monkeypatch):
    from eval.quality.lsp_trace import LSPTrace

    path = tmp_path / 'trace.jsonl'
    trace = LSPTrace(path, 'file:///workspace', max_bytes=16384, event_bytes=1024)
    with trace.capture(monkeypatch):
        trace.record('large', value='雪' * 10000)
    data = rows(path)
    assert path.stat().st_size <= 16384
    large = next(r for r in data if r['kind'] == 'large')
    assert large['payload_omitted']['bytes'] > 10000 and len(large['payload_omitted']['sha256']) == 64
    assert data[-1]['oversized_events'] == 1 and data[-1]['truncated'] is True


def test_capture_restores_hooks_and_preserves_existing_artifact(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.lsp.client import _LSPClient

    from eval.quality.lsp_trace import LSPTrace

    path = tmp_path / 'trace.jsonl'
    original = _LSPClient._send_message
    with pytest.raises(ValueError, match='original'), LSPTrace(path, 'file:///workspace').capture(monkeypatch):
        raise ValueError('original')
    assert _LSPClient._send_message is original
    assert rows(path)[-1]['first_failure']['message'] == 'original'
    before = path.read_bytes()
    with pytest.raises(FileExistsError), LSPTrace(path, 'file:///workspace').capture(monkeypatch):
        pass
    assert path.read_bytes() == before and _LSPClient._send_message is original


def test_disabled_capture_has_no_hooks_or_artifact(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.lsp.client import _LSPClient

    from eval.quality.lsp_trace import LSPTrace

    original = _LSPClient._send_message
    with LSPTrace(None, 'file:///workspace').capture(monkeypatch) as trace:
        trace.stage('selected_original')
        trace.record('unused')
        assert _LSPClient._send_message is original
    assert list(tmp_path.iterdir()) == []


async def test_other_workspace_calls_are_unchanged_and_unrecorded(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.lsp.client import BUILTIN_SERVERS, _LSPClient

    from eval.quality.lsp_trace import LSPTrace

    sent, received = [], []
    async def send(client, message):
        sent.append(message)
        return 'send sentinel'
    def receive(client, message):
        received.append(message)
        return 'receive sentinel'
    monkeypatch.setattr(_LSPClient, '_send_message', send)
    monkeypatch.setattr(_LSPClient, '_handle_message', receive)
    client = _LSPClient(BUILTIN_SERVERS['rust'], 'file:///other')
    path = tmp_path / 'trace.jsonl'
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}
    with LSPTrace(path, 'file:///chosen').capture(monkeypatch):
        assert await client._send_message(message) == 'send sentinel'
        assert client._handle_message(message) == 'receive sentinel'
    assert sent == received == [message]
    assert not any(row['kind'] == 'protocol' for row in rows(path))
    assert _LSPClient._send_message is send and _LSPClient._handle_message is receive
