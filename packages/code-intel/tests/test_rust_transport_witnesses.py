"""Actual MCP wire cancellation, distinct from cancelling a gateway coroutine."""
import asyncio
import base64
import hashlib
import json
import os
import shutil
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from rust_transport_child import FIXTURE_KEY
from test_precision_protocol import SERVER


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines(keepends=True)
            if line.endswith('\n')]


def _peer_source(ready, journal, phase):
    source = (SERVER.replace("'helper.py'", "'helper.rs'")
              .replace("'caller.py'", "'caller.rs'").replace("'character': 4", "'character': 7"))
    anchor = "    if method == 'initialize':"
    gate = f"""
    with open({str(journal)!r}, 'a') as stream:
        stream.write(json.dumps({{'kind':'peer_input','method':method,'message':msg}}) + '\\n')
    if method == {'initialize' if phase == 'initialize' else 'textDocument/definition'!r} and not Path({str(ready)!r}).exists():
        continue
"""
    assert source.count(anchor) == 1
    source = source.replace(anchor, gate + '\n' + anchor)
    anchor = 'def send(value):\n'
    output = f"""def send(value):
    with open({str(journal)!r}, 'a') as stream:
        stream.write(json.dumps({{'kind':'peer_output','message':value}}) + '\\n')
"""
    assert source.count(anchor) == 1
    return source.replace(anchor, output)


class _Actor:
    def __init__(self, directory, mode, phase):
        self.directory, self.mode, self.phase = directory, mode, phase
        self.root = directory / 'project with spaces'
        self.evidence = directory / 'evidence'
        self.root.mkdir()
        self.evidence.mkdir()
        self.journal = self.evidence / 'observer.jsonl'
        self.peer_journal = self.evidence / 'peer.jsonl'
        self.ready = directory / 'ready'
        self.peer = self.evidence / 'peer.py'
        self.peer.write_text(_peer_source(self.ready, self.peer_journal, phase))
        files = {'helper.rs': 'pub fn helper() -> i32 { 1 }\npub fn local() -> i32 { helper() }\n',
                 'caller.rs': 'use crate::helper::helper;\npub fn caller() -> i32 { helper() }\n'}
        self.hashes = {}
        for name, text in files.items():
            (self.root / name).write_text(text)
            (self.evidence / name).write_text(text)
            self.hashes[name] = hashlib.sha256(text.encode()).hexdigest()
        self.process = self.pump = self.stderr = self.client = None
        self.tasks = []
        self.responses = {}
        self.wire = []
        self.forced = False

    def record(self, direction, message):
        self.wire.append({'direction': direction, 'monotonic': time.monotonic(), 'message': message})

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    async def start(self):
        bootstrap = Path(__file__).with_name('rust_transport_child.py')
        self.stderr = (self.evidence / 'server.stderr').open('wb')
        package = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': str(package / 'src')}
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, str(bootstrap), self.mode, str(self.root), str(self.peer), str(self.journal),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=self.stderr, env=env, limit=2**20)
        if self.mode == 'stdio':
            self.pump = asyncio.create_task(self.read_stdout())
        else:
            bound = await self.event('http_bound', timeout=10)
            self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{bound['port']}", timeout=12)
            async with asyncio.timeout(10):
                while True:
                    try:
                        response = await self.client.get('/health')
                        if response.status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(.02)
        bootstrap = await self.event('bootstrap')
        assert bootstrap['mcp'] == '1.26.0' and bootstrap['anyio'] == '4.12.1'
        initialized = await self.rpc('initialize', 'initialize', {
            'protocolVersion': '2025-11-25', 'capabilities': {},
            'clientInfo': {'name': 'owned-transport-witness', 'version': '1'}})
        assert initialized['result']['protocolVersion'] == '2025-11-25'
        await self.notify('notifications/initialized', {})
        prepared = await self.call('prepare', 'symbols', {'path': 'helper.rs'})
        assert not prepared.get('isError')

    async def read_stdout(self):
        while line := await self.process.stdout.readline():
            message = json.loads(line)
            self.record('server_to_client', message)
            if 'id' in message and 'method' not in message:
                self.responses[message['id']] = message

    async def send(self, message, *, valid_auth=True):
        self.record('client_to_server', message)
        if self.mode == 'stdio':
            self.process.stdin.write((json.dumps(message) + '\n').encode())
            await self.process.stdin.drain()
            return None
        key = FIXTURE_KEY if valid_auth else 'authored-invalid-fixture-token'
        response = await self.client.post('/mcp/', json=message, headers={
            'Accept': 'application/json, text/event-stream',
            'Authorization': 'Bearer ' + key, 'MCP-Protocol-Version': '2025-11-25'})
        self.record('server_to_client', {'http_status': response.status_code,
                                       'body': base64.b64encode(response.content).decode()})
        return response

    async def rpc(self, identity, method, params):
        response = await self.send({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params})
        if self.mode == 'http':
            assert response.status_code == 200, response.text
            return response.json()
        async with asyncio.timeout(10):
            while identity not in self.responses:
                if self.pump.done():
                    await self.pump
                    raise AssertionError('MCP stdout ended before response')
                await asyncio.sleep(.005)
        return self.responses[identity]

    async def notify(self, method, params, *, valid_auth=True):
        response = await self.send({'jsonrpc': '2.0', 'method': method, 'params': params},
                                   valid_auth=valid_auth)
        if response is not None:
            assert response.status_code == (202 if valid_auth else 401), response.text

    async def call(self, identity, name='inspect_symbol', arguments=None):
        if arguments is None:
            arguments = {'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000}
        response = await self.rpc(identity, 'tools/call', {'name': name, 'arguments': arguments})
        assert 'result' in response, response
        return response['result']

    async def event(self, kind, identity=None, timeout=3):
        async with asyncio.timeout(timeout):
            while True:
                rows = [row for row in _rows(self.journal) if row['kind'] == kind
                        and (identity is None or row.get('request_id') == identity)]
                if rows:
                    return rows[-1]
                if self.process is not None and self.process.returncode is not None:
                    raise AssertionError('Owned server exited before ' + kind)
                await asyncio.sleep(.005)

    async def blocked(self):
        method = 'initialize' if self.phase == 'initialize' else 'textDocument/definition'
        async with asyncio.timeout(3):
            while not any(row.get('method') == method for row in _rows(self.peer_journal)):
                await asyncio.sleep(.005)
        assert not self.ready.exists() and self.process.returncode is None

    async def close(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.client is not None:
            await self.client.aclose()
        if self.process is not None and self.process.returncode is None:
            if self.mode == 'stdio':
                self.process.stdin.close()
            else:
                self.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), 10)
            except TimeoutError:
                self.forced = True
                self.process.kill()
                await self.process.wait()
        if self.pump is not None:
            await asyncio.gather(self.pump, return_exceptions=True)
        if self.stderr is not None:
            self.stderr.close()


@asynccontextmanager
async def _actor(tmp_path, request, record_property, mode, phase):
    actor = _Actor(tmp_path, mode, phase)
    try:
        await actor.start()
        yield actor
    finally:
        await actor.close()
        report = {'mode': mode, 'phase': phase, 'fixture_source_hashes': actor.hashes,
                  'server_pid': getattr(actor.process, 'pid', None),
                  'server_returncode': getattr(actor.process, 'returncode', None), 'forced_cleanup': actor.forced}
        (actor.evidence / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (actor.evidence / 'wire.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in actor.wire))
        output = Path(os.environ.get('QUALITY_TRANSPORT_TRACE_DIR', 'quality-artifacts/transport')) / request.node.name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(actor.evidence, output)
        record_property('transport_evidence', str(output))
        record_property('forced_cleanup', str(actor.forced).lower())
        assert not actor.forced
        assert actor.process is not None and actor.process.returncode in (
            (0,) if mode == 'stdio' else (0, -signal.SIGTERM))
        closed = [row for row in _rows(actor.journal) if row['kind'] == 'gateway_closed']
        assert closed and all(p['returncode'] is not None for p in closed[-1]['processes'])


def _payload(result):
    assert not result.get('isError'), result
    return json.loads(result['content'][0]['text'])


@pytest.mark.parametrize('phase', ['initialize', 'definition'])
async def test_stdio_cancel_notification_reaches_precision(tmp_path, request, record_property, phase):
    async with _actor(tmp_path, request, record_property, 'stdio', phase) as actor:
        target = actor.task(actor.rpc('target', 'tools/call', {
            'name': 'inspect_symbol', 'arguments': {
                'symbol_name': 'helper', 'file_path': 'helper.rs', 'line': 1, 'max_tokens': 8000}}))
        await actor.blocked()
        assert not target.done()
        await actor.notify('notifications/cancelled', {'requestId': 'unknown', 'reason': 'authored control'})
        await actor.rpc('probe', 'tools/list', {})
        assert not target.done() and not any(row['kind'] == 'sdk_cancel' for row in _rows(actor.journal))
        record_property('qualified_input', 'true')
        started = time.monotonic()
        await actor.notify('notifications/cancelled', {'requestId': 'target', 'reason': 'authored cancellation'})
        response = await target
        assert response.get('error', {}).get('message') == 'Request cancelled'
        cancelled = await actor.event('precision_cancelled', 'target', timeout=1)
        assert cancelled['state']['callback_restored'] and cancelled['state']['pending'] == 0
        assert cancelled['state']['completed'] == cancelled['state']['retry_after'] == 0
        async with asyncio.timeout(1):
            result = await actor.call('barrier', 'symbols', {'path': 'helper.rs'})
        assert not result.get('isError')
        record_property('cancel_to_worker_reuse', time.monotonic() - started)
        actor.ready.touch()
        recovered = _payload(await actor.call('recovered'))
        assert recovered['metadata']['precision'] == 'verified'
        assert any(ref['file_path'] == 'caller.rs' and ref['source'] == 'lsp'
                   for ref in recovered['data']['references'])
        await actor.notify('notifications/cancelled', {'requestId': 'recovered', 'reason': 'completed control'})
        assert _payload(await actor.call('after_completed_cancel'))['metadata']['precision'] == 'verified'


@pytest.mark.parametrize('phase', ['initialize', 'definition'])
async def test_stateless_http_notification_is_bounded_without_correlation(
        tmp_path, request, record_property, phase):
    async with _actor(tmp_path, request, record_property, 'http', phase) as actor:
        target = actor.task(actor.call('target'))
        await actor.blocked()
        assert not target.done()
        record_property('qualified_input', 'true')
        await actor.notify('notifications/cancelled', {'requestId': 'target'}, valid_auth=False)
        assert not target.done()
        await actor.notify('notifications/cancelled', {'requestId': 'target', 'reason': 'authored cancellation'})
        response = _payload(await target)
        finished = await actor.event('precision_finished', 'target')
        assert 4.5 <= finished['elapsed'] < 5.8
        assert response['metadata']['precision'] == 'partial'
        assert any(ref['file_path'] == 'helper.rs' for ref in response['data']['references'])
        assert not any(row['kind'] in {'sdk_cancel', 'precision_cancelled'} for row in _rows(actor.journal))
        sessions = [row for row in _rows(actor.journal) if row['kind'] == 'sdk_session']
        assert len(sessions) >= 4 and all(row['stateless'] for row in sessions)
        record_property('http_cancellation_disposition', 'accepted_notification_does_not_correlate_across_stateless_posts')
        actor.ready.touch()
        await asyncio.sleep(1.05)
        recovered = _payload(await actor.call('recovered'))
        assert recovered['metadata']['precision'] == 'verified'
        assert any(ref['file_path'] == 'caller.rs' and ref['source'] == 'lsp'
                   for ref in recovered['data']['references'])


async def test_http_disconnect_is_distinct_from_protocol_cancellation(tmp_path, request, record_property):
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        target = actor.task(actor.call('target'))
        await actor.blocked()
        assert not target.done()
        record_property('qualified_input', 'true')
        target.cancel()
        with pytest.raises(asyncio.CancelledError):
            await target
        finished = await actor.event('precision_finished', 'target', timeout=6)
        assert 4.5 <= finished['elapsed'] < 5.8
        assert not any(row['kind'] == 'precision_cancelled' for row in _rows(actor.journal))
        record_property('disconnect_disposition', 'not_protocol_cancellation_under_2025_11_25')
        actor.ready.touch()
        await asyncio.sleep(1.05)
        assert _payload(await actor.call('recovered'))['metadata']['precision'] == 'verified'
