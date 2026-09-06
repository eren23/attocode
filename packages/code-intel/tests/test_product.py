from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.onboarding import configure_client
from attocode_intel.output import bounded_text
from attocode_intel.request_context import resolve_workspace


def project(root, name):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f'[project]\nname="{name}"\nversion="1"\n')
    (root / "main.py").write_text(f"from helper import {name}\ndef run():\n    return {name}()\n")
    (root / "helper.py").write_text(f"def {name}():\n    return 1\n")
    return root


@pytest.mark.asyncio
async def test_concurrent_workspaces_and_freshness(tmp_path):
    a, b = project(tmp_path / "a", "alpha"), project(tmp_path / "b", "beta")
    gateway = OperationGateway(profile="daily")
    try:

        async def symbols(root):
            return await gateway.execute("symbols", {"workspace": str(root), "path": "helper.py"})

        first, second = await asyncio.gather(symbols(a), symbols(b))
        assert "alpha" in first.content[0].text and "beta" not in first.content[0].text
        assert "beta" in second.content[0].text and "alpha" not in second.content[0].text
        (a / "helper.py").write_text("def replacement():\n    return 2\n")
        updated = await symbols(a)
        assert "replacement" in updated.content[0].text and "alpha" not in updated.content[0].text
        (a / "new.py").write_text("def new_symbol(): pass\n")
        found = await gateway.execute("search_symbols", {"workspace": str(a), "name": "new_symbol"})
        assert "new.py" in found.content[0].text
        (a / "new.py").unlink()
        missing = await gateway.execute(
            "search_symbols", {"workspace": str(a), "name": "new_symbol"}
        )
        assert "new.py" not in missing.content[0].text
        # Only an import changes; function signatures are identical.
        (a / "other.py").write_text("def replacement(): return 3\n")
        (a / "main.py").write_text(
            "from other import replacement\ndef run():\n    return replacement()\n"
        )
        deps = await gateway.execute("dependencies", {"workspace": str(a), "path": "main.py"})
        assert "other.py" in deps.content[0].text
        assert "helper.py" not in deps.content[0].text
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_bootstrap_total_budget_and_no_agent_import(tmp_path):
    root = project(tmp_path / "repo", "helper")
    gateway = OperationGateway(str(root), "daily")
    try:
        result = await gateway.execute("bootstrap", {"task_hint": "helper", "max_tokens": 128})
        from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens

        assert count_tokens(result.content[0].text) <= 128
        assert result.structuredContent["metadata"]["workspace"] == str(root.resolve())
    finally:
        await gateway.close()
    assert not any(
        name.startswith(("attocode.agent", "attocode.tui", "attoswarm")) for name in sys.modules
    )


@pytest.mark.parametrize("budget", [1, 10, 128, 2000])
def test_output_budget_with_unicode(budget):
    from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens

    text, truncated = bounded_text("日本語 🧠 source();\n" * 1000, budget)
    assert count_tokens(text) <= budget
    assert truncated


def test_onboarding_preserves_comments_and_refuses_malformed_config(tmp_path):
    root = project(tmp_path / "space in path", "helper")
    config = root / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text('# user comment\nmodel = "my-model"\n')
    configure_client("codex", str(root))
    content = config.read_text()
    configure_client("codex", str(root))
    assert config.read_text() == content
    assert "# user comment" in content and 'model = "my-model"' in content
    assert (root / "AGENTS.md").read_text().count("<!-- attocode-code-intel:start -->") == 1
    configure_client("codex", str(root), remove=True)
    assert "mcp_servers.attocode-code-intel" not in config.read_text()
    config.write_text("broken = [")
    previous = (root / "AGENTS.md").read_text()
    from tomlkit.exceptions import ParseError

    with pytest.raises(ParseError):
        configure_client("codex", str(root))
    assert config.read_text() == "broken = ["
    assert (root / "AGENTS.md").read_text() == previous


def test_worktree_discovery_and_explicit_selection(tmp_path, monkeypatch):
    root = tmp_path / "worktree"
    (root / "nested").mkdir(parents=True)
    (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/task")
    monkeypatch.chdir(root / "nested")
    assert resolve_workspace() == str(root.resolve())
    assert resolve_workspace(str(root / "nested")) == str((root / "nested").resolve())


def test_remote_install_requires_server_without_writing_config(tmp_path):
    from attocode_intel.entrypoint import main

    with pytest.raises(SystemExit) as exc:
        main(["init", "--client", "claude", "--project", str(tmp_path), "--remote"])
    assert exc.value.code == 1
    assert list(tmp_path.iterdir()) == []
    result = configure_client(
        "claude", str(tmp_path), server="https://intel.example.com", repo="repo-id", dry_run=True
    )
    assert result["configuration"]["type"] == "http"
    assert result["configuration"]["url"] == "https://intel.example.com/mcp/"


@pytest.mark.asyncio
async def test_real_stdio_protocol(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = project(tmp_path / "repo", "protocol_symbol")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "attocode_intel.entrypoint", "--project", str(root), "--profile", "daily"],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    async with asyncio.timeout(30), stdio_client(params) as streams:  # noqa: SIM117
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            assert "bootstrap" in initialized.instructions
            catalog = await session.list_tools()
            assert "capabilities" in {t.name for t in catalog.tools}
            assert "clear_embeddings" not in {t.name for t in catalog.tools}
            result = await session.call_tool("search_symbols", {"name": "protocol_symbol"})
            assert not result.isError
            assert "helper.py" in result.content[0].text
            assert result.structuredContent["metadata"]["source"] == "local"
            guidelines = await session.read_resource("attocode://guidelines")
            assert "bootstrap" in guidelines.contents[0].text
            templates = await session.list_resource_templates()
            assert len(templates.resourceTemplates) == 3
            resource = await session.read_resource("attocode://project/helper.py")
            assert "protocol_symbol" in resource.contents[0].text


def test_real_http_protocol_and_auth(tmp_path):
    from attocode_intel.api.app import create_app
    from attocode_intel.config import CodeIntelConfig
    from starlette.testclient import TestClient

    root = project(tmp_path / "repo", "http_symbol")
    app = create_app(CodeIntelConfig(project_dir=str(root), api_key="test-secret"))
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer test-secret",
    }
    with TestClient(app) as client:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        assert client.post("/mcp/", json=body).status_code == 401
        response = client.post("/mcp/", json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["result"]["serverInfo"]["name"] == "attocode-code-intel"
        body.update(
            method="tools/call", params={"name": "symbols", "arguments": {"path": "helper.py"}}
        )
        result = client.post("/mcp/", json=body, headers=headers).json()["result"]
        assert not result.get("isError"), result
        assert "http_symbol" in result["content"][0]["text"]
