"""Owned live bridge: existing SDK baseline until the product entry exists."""
import asyncio
import functools
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

URL, WORKSPACE, JOURNAL = sys.argv[1:]


def record(value):
    value = {'monotonic': time.monotonic(), **value}
    with Path(JOURNAL).open('a') as stream:
        stream.write(json.dumps(value) + '\n')


_HTTP = httpx.AsyncClient


class ObservedHTTP(_HTTP):
    @functools.wraps(_HTTP.send)
    async def send(self, request, *args, **kwargs):
        if request.method == 'POST' and request.content:
            record({'kind': 'http_request', 'rpc': json.loads(request.content),
                    'context': request.headers.get('X-Attocode-Cancellation-Id'),
                    'workspace': request.headers.get('X-Attocode-Workspace'),
                    'profile': request.headers.get('X-Attocode-Profile'),
                    'credential_sha256': hashlib.sha256(
                        request.headers.get('Authorization', '').encode()).hexdigest()})
        return await super().send(request, *args, **kwargs)


httpx.AsyncClient = ObservedHTTP
candidate = importlib.util.find_spec('attocode_intel.http_proxy') is not None
package = Path(__file__).resolve().parents[1] / 'src' / 'attocode_intel'
sources = {}
for name in ['entrypoint.py', 'onboarding.py', '_http_session.py', 'http_proxy.py']:
    path = package / name
    sources[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
record({'kind': 'bootstrap', 'adapter': 'product-cli' if candidate else 'baseline-sdk',
        'mcp': importlib.metadata.version('mcp'), 'sources': sources})


async def baseline():
    """No automatic cancellation: real unmodified pinned ClientSession."""
    headers = {'Authorization': 'Bearer ' + os.environ['ATTOCODE_PROXY_TEST_TOKEN'],
               'X-Attocode-Workspace': WORKSPACE, 'X-Attocode-Profile': 'full',
               'X-Attocode-Cancellation-Id': str(uuid.uuid4())}
    async with (
        httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=300)) as http,
        streamable_http_client(URL, http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as upstream,
    ):
        initialized = await upstream.initialize()
        server = Server('owned-sdk-bridge-baseline', version=initialized.serverInfo.version,
                        instructions=initialized.instructions)
        for request_type, result_type in [
            (types.ListToolsRequest, types.ListToolsResult),
            (types.CallToolRequest, types.CallToolResult),
            (types.ListResourcesRequest, types.ListResourcesResult),
            (types.ListResourceTemplatesRequest, types.ListResourceTemplatesResult),
            (types.ReadResourceRequest, types.ReadResourceResult),
            (types.ListPromptsRequest, types.ListPromptsResult),
            (types.GetPromptRequest, types.GetPromptResult),
        ]:
            async def forward(request, result_type=result_type):
                return types.ServerResult(await upstream.send_request(
                    types.ClientRequest(request), result_type))
            server.request_handlers[request_type] = forward
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


if candidate:
    from attocode_intel.entrypoint import main

    main(['mcp-proxy', '--url', URL, '--workspace', WORKSPACE,
          '--profile', 'full', '--token-env', 'ATTOCODE_PROXY_TEST_TOKEN'])
else:
    asyncio.run(baseline())
record({'kind': 'closed'})
