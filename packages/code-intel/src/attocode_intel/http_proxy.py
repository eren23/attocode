"""Opt-in stdio bridge for the authenticated Attocode Streamable HTTP endpoint."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from attocode_intel._http_session import http_session


def validate_proxy_options(url, token_env):
    """Validate without including a URL, credential or environment value in errors."""
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {'http', 'https'} and parsed.hostname and
                 not (parsed.username or parsed.password or parsed.query or parsed.fragment) and
                 not any(char.isspace() or ord(char) < 32 for char in url))
        valid = valid and (parsed.port is None or parsed.port > 0)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Proxy URL must be HTTP(S), without credentials, query or fragment') from None
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', token_env):
        raise ValueError('Token environment name must be a valid identifier')


def create_proxy(upstream, initialization):
    """Forward the supported typed method bodies; the two SDK sessions own IDs.

    Keep results intact, including structuredContent, per-content resource URIs,
    cursors, metadata and McpError. Advertise only groups the upstream supports.
    No sampling, elicitation, tasks, subscriptions or progress relay is offered.
    """
    server = Server('attocode-http-proxy', version=initialization.serverInfo.version,
                    instructions=initialization.instructions)
    for capability, request_type, result_type in [
        ('tools', types.ListToolsRequest, types.ListToolsResult),
        ('tools', types.CallToolRequest, types.CallToolResult),
        ('resources', types.ListResourcesRequest, types.ListResourcesResult),
        ('resources', types.ListResourceTemplatesRequest, types.ListResourceTemplatesResult),
        ('resources', types.ReadResourceRequest, types.ReadResourceResult),
        ('prompts', types.ListPromptsRequest, types.ListPromptsResult),
        ('prompts', types.GetPromptRequest, types.GetPromptResult),
    ]:
        if getattr(initialization.capabilities, capability) is None:
            continue

        async def forward(request, result_type=result_type):
            body = types.ClientRequest.model_validate(request.model_dump(
                by_alias=True, exclude_none=True, exclude={'id', 'jsonrpc'}))
            return types.ServerResult(await upstream.send_request(body, result_type))

        server.request_handlers[request_type] = forward
    return server


async def run_proxy(url, *, token_env='ATTOCODE_API_KEY', workspace='', profile='daily'):
    validate_proxy_options(url, token_env)
    if profile not in {'daily', 'full'}:
        raise ValueError('Proxy profile must be daily or full')
    token = os.environ.get(token_env, '')
    if not token or any(ord(c) < 32 or ord(c) > 126 for c in token):
        raise ValueError('Proxy token environment variable is missing or invalid')
    headers = {'Authorization': 'Bearer ' + token, 'X-Attocode-Profile': profile}
    if workspace:
        headers['X-Attocode-Workspace'] = workspace
    async with http_session(url, headers=headers, enable_cancellation=True) as upstream:
        initialized = await upstream.initialize()
        server = create_proxy(upstream, initialized)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
