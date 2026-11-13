"""Public request/result forwarding, opt-in configuration and real doctor contracts."""
import json
import sys

import pytest
from mcp import types
from mcp.shared.exceptions import McpError


def initialized(capabilities=None):
    return types.InitializeResult(protocolVersion='2025-11-25',
        capabilities=types.ServerCapabilities.model_validate(capabilities or {'tools': {}, 'resources': {}, 'prompts': {}}),
        serverInfo=types.Implementation(name='owned-peer', version='7.6.5'), instructions='owned instructions')


@pytest.mark.parametrize('wire_request,result', [
    ({'method': 'tools/list', 'params': {'cursor': 'cursor 1', '_meta': {'tag': 'list'}}},
     {'tools': [], 'nextCursor': 'cursor 2', '_meta': {'reply': 1}}),
    ({'method': 'tools/call', 'params': {'name': 'owned', 'arguments': {'x': 2}, '_meta': {'tag': 'call'}}},
     {'content': [{'type': 'text', 'text': 'text'}], 'structuredContent': {'answer': 2}, 'isError': True, '_meta': {'reply': 2}}),
    ({'method': 'resources/list', 'params': {'cursor': 'cursor 3'}}, {'resources': [], 'nextCursor': 'cursor 4'}),
    ({'method': 'resources/templates/list'}, {'resourceTemplates': []}),
    ({'method': 'resources/read', 'params': {'uri': 'owned://requested'}},
     {'contents': [{'uri': 'owned://actual', 'mimeType': 'application/octet-stream', 'blob': 'AQI=', '_meta': {'content': 3}},
                   {'uri': 'owned://text', 'text': 'owned text'}], '_meta': {'reply': 3}}),
    ({'method': 'prompts/list', 'params': {'cursor': 'cursor 5'}}, {'prompts': [], 'nextCursor': 'cursor 6'}),
    ({'method': 'prompts/get', 'params': {'name': 'owned', 'arguments': {'x': '2'}}},
     {'description': 'owned description', 'messages': [{'role': 'user', 'content': {'type': 'text', 'text': 'owned prompt'}}]}),
])
async def test_typed_forwarding_preserves_payload_and_drops_only_wire_envelope(wire_request, result):
    from attocode_intel.http_proxy import create_proxy

    incoming = types.ClientRequest.model_validate({'jsonrpc': '2.0', 'id': 73, **wire_request}).root

    class Upstream:
        async def send_request(self, outgoing, result_type):
            assert outgoing.model_dump(by_alias=True, mode="json", exclude_none=True) == wire_request
            return result_type.model_validate(result)

    server = create_proxy(Upstream(), initialized())
    reply = await server.request_handlers[type(incoming)](incoming)
    # Model defaults may be emitted; all authored content, metadata and per-item URIs survive.
    for key, value in result.items():
        assert reply.root.model_dump(by_alias=True, mode="json", exclude_none=True)[key] == value
    options = server.create_initialization_options()
    assert options.server_version == '7.6.5' and options.instructions == 'owned instructions'


async def test_error_and_unsupported_capabilities_are_not_rewritten():
    from attocode_intel.http_proxy import create_proxy

    class Upstream:
        async def send_request(self, *args):
            raise McpError(types.ErrorData(code=-32088, message='owned error', data={'key': 4}))

    server = create_proxy(Upstream(), initialized({'tools': {}}))
    options = server.create_initialization_options()
    assert options.capabilities.resources is None and options.capabilities.prompts is None
    request = types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(name='owned'))
    with pytest.raises(McpError) as error:
        await server.request_handlers[types.CallToolRequest](request)
    assert error.value.error.model_dump() == {'code': -32088, 'message': 'owned error', 'data': {'key': 4}}


@pytest.mark.parametrize('client', ['codex', 'claude', 'cursor'])
def test_opt_in_proxy_config_is_reversible_and_contains_only_token_name(tmp_path, monkeypatch, client):
    import tomlkit
    from attocode_intel.onboarding import REMOTE_NAME, client_paths, configure_client

    monkeypatch.setenv('OWNED_TOKEN', 'must-not-be-persisted')
    config, _, key = client_paths(client, tmp_path, False)
    config.parent.mkdir(parents=True, exist_ok=True)
    document = {key: {REMOTE_NAME: {'command': 'previous'}, 'unrelated': {'command': 'keep'}}}
    config.write_text(tomlkit.dumps(document) if config.suffix == '.toml' else json.dumps(document))
    preview = configure_client(client, tmp_path, dry_run=True, server='https://example.invalid',
        repo='repo with spaces', token_env='OWNED_TOKEN', profile='full', http_cancellation=True)
    entry = preview['configuration']
    args = entry['args']
    offset = args.index('mcp-proxy')
    assert args[offset:] == ['mcp-proxy', '--url', 'https://example.invalid/mcp/', '--token-env',
                            'OWNED_TOKEN', '--workspace', 'repo with spaces', '--profile', 'full']
    assert 'url' not in entry and entry['command']
    if client == 'codex':
        assert entry['env_vars'] == ['OWNED_TOKEN']
    if client == 'cursor':
        assert entry['type'] == 'stdio'
    configure_client(client, tmp_path, server='https://example.invalid', repo='repo with spaces',
                     token_env='OWNED_TOKEN', http_cancellation=True)
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert 'must-not-be-persisted' not in path.read_text()
            assert 'X-Attocode-Cancellation-Id' not in path.read_text()
    configure_client(client, tmp_path, repo='remote', remove=True)
    restored = tomlkit.parse(config.read_text()) if config.suffix == '.toml' else json.loads(config.read_text())
    assert restored[key] == document[key]


@pytest.mark.parametrize('kwargs', [
    {}, {'profile': 'lean', 'server': 'https://example.invalid'},
    {'server': 'https://name:secret@example.invalid'}, {'server': 'https://example.invalid/?secret=value'},
    {'server': 'https://example.invalid/#secret'}, {'server': 'https://example.invalid', 'token_env': 'BAD=NAME'},
])
def test_opt_in_rejects_invalid_config_without_echoing_secrets(tmp_path, kwargs):
    from attocode_intel.onboarding import configure_client

    with pytest.raises(ValueError) as error:
        configure_client('codex', tmp_path, dry_run=True, http_cancellation=True, **kwargs)
    assert 'secret' not in str(error.value) and 'BAD=NAME' not in str(error.value)


async def test_remote_stdio_doctor_uses_remote_workspace(tmp_path, monkeypatch, request, record_property):
    from attocode_intel import __version__
    from attocode_intel.onboarding import configure_client, diagnose
    from http_cancel_fixture import _actor

    monkeypatch.setenv('ATTOCODE_MCP_HTTP_CANCEL', '1')
    async with _actor(tmp_path, request, record_property, 'http', 'definition') as actor:
        project = tmp_path / 'different client project'
        project.mkdir()
        monkeypatch.setenv('OWNED_DOCTOR_TOKEN', actor.tokens['alice'])
        # Ensure the subprocess imports this immutable checkout, not an installed global tool.
        executable = tmp_path / 'owned python'
        executable.symlink_to(sys.executable)
        monkeypatch.setattr(sys, 'executable', str(executable))
        configure_client('codex', project, server=str(actor.client.base_url), repo=str(actor.root),
                         token_env='OWNED_DOCTOR_TOKEN', http_cancellation=True)
        result = await diagnose('codex', project, remote=True)
        assert result['status'] == 'ok' and result['probed_server_version'] == __version__
        assert result['metadata']['workspace'] != str(project.resolve())
        assert result['probe_connection'] == 'new' and 'existing host session' in result['probe_hint']
        assert actor.tokens['alice'] not in json.dumps(result)
