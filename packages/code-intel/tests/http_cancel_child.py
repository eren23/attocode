"""Owned online diagnostic bootstrap; production dispatch remains unchanged."""
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import os
import socket
import sys
import threading
import time
from functools import wraps
from pathlib import Path

FIXTURE_KEY = 'authored-transport-fixture-token'
JWT_KEY = 'authored-http-cancellation-jwt-key-for-owned-ci-fixture'
CLIENT_ID = '12345678-1234-4abc-8abc-123456789abc'


def main():
    mode, root, peer, journal = sys.argv[1:]
    lock = threading.Lock()
    sequence = 0
    processes = []
    callbacks = {}

    def record(kind, **data):
        nonlocal sequence
        with lock:
            sequence += 1
            row = {'kind': kind, 'index': sequence, 'monotonic': time.monotonic(),
                   'pid': os.getpid(), **data}
            with Path(journal).open('a') as stream:
                stream.write(json.dumps(row) + '\n')

    os.environ.update(ATTOCODE_INTEL_PRECISION='auto', ATTOCODE_INTEL_WATCH='0',
                      ATTOCODE_MCP_PROFILE='daily')
    from attocode_intel import gateway, precision
    from attocode_intel._internal.integrations.lsp import client
    from mcp.server.lowlevel.server import request_ctx
    from mcp.server.session import ServerSession
    from mcp.shared.session import RequestResponder

    def request_id():
        context = request_ctx.get(None)
        return getattr(context, 'request_id', None)

    def state(service, session=None):
        manager = service._lsp_manager
        return {
            'callback_restored': bool(manager and id(manager) in callbacks
                                      and manager.on_result_callback is callbacks[id(manager)]),
            'pending': sum(len(c._pending) for c in manager._clients.values()) if manager else 0,
            'completed': len(session.completed) if session else None,
            'retry_after': len(session.retry_after) if session else None,
            'processes': [{'pid': p.pid, 'returncode': p.returncode} for p in processes],
        }

    source_files = [gateway.__file__, precision.__file__, client.__file__, __file__]
    record('bootstrap', mode=mode, mcp=importlib.metadata.version('mcp'),
           anyio=importlib.metadata.version('anyio'),
           sources={name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source_files})
    spawn = asyncio.create_subprocess_exec

    @wraps(spawn)
    async def observed_spawn(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        record('lsp_spawn', child_pid=process.pid)
        return process

    asyncio.create_subprocess_exec = observed_spawn
    start = client.LSPManager.start_server

    @wraps(start)
    async def observed_start(self, *args, **kwargs):
        callbacks.setdefault(id(self), self.on_result_callback)
        return await start(self, *args, **kwargs)

    client.LSPManager.start_server = observed_start
    enrich = precision.PrecisionSession.enrich

    @wraps(enrich)
    async def observed_enrich(self, *args, **kwargs):
        record('precision_started', request_id=request_id())
        started = time.monotonic()
        try:
            result = await enrich(self, *args, **kwargs)
        except asyncio.CancelledError:
            record('precision_cancelled', request_id=request_id(),
                   elapsed=time.monotonic() - started, state=state(self.service, self))
            raise
        else:
            record('precision_finished', request_id=request_id(),
                   elapsed=time.monotonic() - started, result=result,
                   state=state(self.service, self))
            return result

    precision.PrecisionSession.enrich = observed_enrich
    execute = gateway.OperationGateway._execute_sync

    @wraps(execute)
    def observed_execute(self, context, name, args, compact=False, timings=None):
        try:
            return execute(self, context, name, args, compact, timings)
        finally:
            if service := context.stores.get('service'):
                record('worker_finished', request_id=request_id(), operation=name,
                       state=state(service, context.stores.get('precision')))

    gateway.OperationGateway._execute_sync = observed_execute
    close = gateway.OperationGateway.close

    @wraps(close)
    async def observed_close(self):
        await close(self)
        record('gateway_closed', processes=[{'pid': p.pid, 'returncode': p.returncode}
                                            for p in processes])

    gateway.OperationGateway.close = observed_close
    cancel = RequestResponder.cancel

    @wraps(cancel)
    async def observed_cancel(self):
        record('sdk_cancel', request_id=self.request_id)
        return await cancel(self)

    RequestResponder.cancel = observed_cancel
    initialize = ServerSession.__init__

    @wraps(initialize)
    def observed_session(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        record('sdk_session', object_id=id(self), stateless=kwargs.get('stateless', False))

    ServerSession.__init__ = observed_session
    client.BUILTIN_SERVERS['rust'] = client.LanguageServerConfig(
        command=sys.executable, args=[peer], extensions=['.rs'], language_id='rust')
    import uvicorn
    from attocode_intel.api.app import create_app
    from attocode_intel.config import CodeIntelConfig

    app = create_app(CodeIntelConfig(project_dir=root, api_key=FIXTURE_KEY))
    # Real JWT verification, authored config; gateway/lifespan remain local so
    # these transport tests do not claim database membership authorization.
    from attocode_intel.api import auth, deps

    auth_config = CodeIntelConfig(database_url='postgresql+asyncpg://unused-auth-fixture',
                                 secret_key=JWT_KEY)
    auth.get_config = lambda: auth_config
    deps.get_config = lambda: auth_config
    resolve = auth.resolve_auth

    @wraps(resolve)
    async def observed_auth(authorization=None):
        context = await resolve(authorization)
        record('auth_resolved', user_id=str(context.user_id), org_id=str(context.org_id),
               method=context.auth_method, scopes=context.scopes,
               credential_sha256=hashlib.sha256(authorization.encode()).hexdigest())
        return context

    auth.resolve_auth = observed_auth


    async def observed_app(scope, receive, send):
        if scope['type'] != 'http':
            return await app(scope, receive, send)

        async def received():
            message = await receive()
            record('http_receive', path=scope['path'], message_type=message['type'],
                   body=base64.b64encode(message.get('body', b'')).decode(),
                   more_body=message.get('more_body', False))
            return message

        async def sent(message):
            record('http_send', path=scope['path'], message_type=message['type'],
                   status=message.get('status'),
                   body=base64.b64encode(message.get('body', b'')).decode())
            await send(message)

        await app(scope, received, sent)

    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        record('http_bound', port=listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(
            observed_app, host='127.0.0.1', log_level='warning', access_log=False,
            timeout_graceful_shutdown=8))
        server.run(sockets=[listener])
    record('bootstrap_exit', processes=[{'pid': p.pid, 'returncode': p.returncode} for p in processes])


if __name__ == '__main__':
    main()
