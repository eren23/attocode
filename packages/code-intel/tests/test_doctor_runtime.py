"""Doctor reports the runtime reached by a new connection, without credentials."""

import json
import sys
from contextlib import asynccontextmanager

import pytest
from attocode_intel.onboarding import configure_client, diagnose


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A real stdio MCP peer with a version independent of this checkout."""
    home = tmp_path / "temporary home"
    project = tmp_path / "project with spaces"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    executable = tmp_path / "python with spaces"
    executable.symlink_to(sys.executable)
    server = tmp_path / "runtime peer.py"
    server.write_text('''import json, os, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": request["params"]["protocolVersion"],
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "different-installation", "version": "9.8.7"}}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                            for name in ("capabilities", "bootstrap")]}
    elif method == "tools/call":
        payload = {"metadata": {"workspace": os.getcwd()},
                   "data": {"languages": {"python": True}}}
        result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                  "structuredContent": payload, "isError": False}
    else:
        raise RuntimeError(method)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
''')
    entry = {"command": str(executable), "args": [str(server), "argv-secret"],
             "env": {"PRIVATE_TOKEN": "env-secret"}}
    return home, project, entry


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["project", "local", "global"])
async def test_doctor_reports_selected_runtime_and_new_connection(runtime, scope):
    home, project, entry = runtime
    bad_entry = {"command": str(project / "not-selected")}
    (project / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"attocode-code-intel": entry if scope == "project" else bad_entry}}))
    document = {"mcpServers": {"attocode-code-intel": entry if scope == "global" else bad_entry}}
    if scope == "local":
        document["projects"] = {str(project): {"mcpServers": {"attocode-code-intel": entry}}}
    (home / ".claude.json").write_text(json.dumps(document))

    result = await diagnose("claude", project, global_scope=scope == "global")

    assert result["status"] == "ok"
    assert result["configured_command"] == str(home.parent / "python with spaces")
    assert result["probed_server_version"] == "9.8.7"
    assert result["probe_connection"] == "new"
    assert "existing host session" in result["probe_hint"]
    assert result["config"] == str(project / ".mcp.json" if scope == "project"
                                   else home / ".claude.json")
    assert "argv-secret" not in json.dumps(result)
    assert "env-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_remote_doctor_identifies_new_peer_without_exposing_endpoint(runtime, monkeypatch):
    # Replace only the remote transport with a local stdio peer: no network or host session.
    import mcp.client.streamable_http
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, project, entry = runtime

    @asynccontextmanager
    async def local_transport(url, *, http_client):
        assert url == "https://example.invalid/mcp/?token=endpoint-secret"
        async with stdio_client(StdioServerParameters(
            command=entry["command"], args=entry["args"], cwd=str(project)
        )) as streams:
            yield streams

    monkeypatch.setattr(mcp.client.streamable_http, "streamable_http_client", local_transport)
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "attocode-code-intel-remote": {"url": "https://example.invalid/mcp/?token=endpoint-secret",
                                       "headers": {"Authorization": "Bearer header-secret"}},
    }}))

    result = await diagnose("claude", project, remote=True)

    assert result["status"] == "ok"
    assert result["configured_command"] is None
    assert result["probed_server_version"] == "9.8.7"
    assert result["probe_connection"] == "new"
    assert "endpoint-secret" not in json.dumps(result)
    assert "header-secret" not in json.dumps(result)


def test_doctor_cli_reports_fresh_runtime_in_temporary_home(runtime, capsys):
    from attocode_intel.entrypoint import main

    _, project, entry = runtime
    (project / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"attocode-code-intel": entry}}))

    main(["doctor", "--client", "claude", "--project", str(project)])

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["configured_command"] == entry["command"]
    assert result["probed_server_version"] == "9.8.7"
    assert result["probe_connection"] == "new"


@pytest.mark.asyncio
async def test_doctor_reads_source_gateway_version(runtime):
    from attocode_intel import __version__

    _, project, _ = runtime
    (project / "main.py").write_text("def example(): return 1\n")
    configure_client("claude", project)

    result = await diagnose("claude", project)

    assert result["status"] == "ok"
    assert result["probed_server_version"] == __version__
    assert result["probe_connection"] == "new"
