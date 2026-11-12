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
from http_cancel_child import CLIENT_ID, JWT_KEY
from jose import jwt
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


def token(identity):
    user = '22222222-2222-4222-8222-222222222222' if identity == 'bob' else '11111111-1111-4111-8111-111111111111'
    return jwt.encode({'sub': user, 'org': '33333333-3333-4333-8333-333333333333',
                       'type': 'access', 'exp': int(time.time()) + 3600,
                       'scopes': ['intelligence:read'], 'credential_variant': identity},
                      JWT_KEY, algorithm='HS256')


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
        self.headers = {'X-Attocode-Cancellation-Id': CLIENT_ID}
        self.identity = 'alice'
        self.tokens = {name: token(name) for name in ('alice', 'alice2', 'bob')}

    def record(self, direction, message):
        self.wire.append({'direction': direction, 'monotonic': time.monotonic(), 'message': message})

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    async def start(self):
        bootstrap = Path(__file__).with_name('http_cancel_child.py')
        self.stderr = (self.evidence / 'server.stderr').open('wb')
        package = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': str(package / 'src')}
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, str(bootstrap), self.mode, str(self.root), str(self.peer), str(self.journal),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=self.stderr, env=env, limit=2**20)
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

    async def send(self, message, *, valid_auth=True):
        self.record('client_to_server', {'rpc': message, 'identity': self.identity, 'headers': dict(self.headers)})
        key = self.tokens[self.identity] if valid_auth else 'authored-invalid-fixture-token'
        response = await self.client.post('/mcp/', json=message, headers={
            'Accept': 'application/json, text/event-stream',
            'Authorization': 'Bearer ' + key, 'MCP-Protocol-Version': '2025-11-25', **self.headers})
        self.record('server_to_client', {'http_status': response.status_code,
                                       'body': base64.b64encode(response.content).decode()})
        return response

    async def rpc(self, identity, method, params):
        response = await self.send({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params})
        assert response.status_code == 200, response.text
        return response.json()

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
        output = Path(os.environ.get('QUALITY_HTTP_CANCEL_TRACE_DIR', 'quality-artifacts/http-cancellation')) / request.node.name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(actor.evidence, output)
        record_property('transport_evidence', str(output))
        record_property('forced_cleanup', str(actor.forced).lower())
        assert not actor.forced
        assert actor.process is not None and actor.process.returncode in (0, -signal.SIGTERM)
        closed = [row for row in _rows(actor.journal) if row['kind'] == 'gateway_closed']
        assert closed and all(p['returncode'] is not None for p in closed[-1]['processes'])


def _payload(result):
    assert not result.get('isError'), result
    return json.loads(result['content'][0]['text'])


