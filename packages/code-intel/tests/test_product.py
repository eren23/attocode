from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.onboarding import configure_client
from attocode_intel.output import bounded_bootstrap, bounded_compact, bounded_text, response_tokens
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
    agent_modules_before = {
        name for name in sys.modules
        if name.startswith(("attocode.agent", "attocode.tui", "attoswarm"))
    }
    root = project(tmp_path / "repo", "helper")
    gateway = OperationGateway(str(root), "daily")
    try:
        result = await gateway.execute("bootstrap", {"task_hint": "helper", "max_tokens": 128})
        from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens

        assert count_tokens(result.content[0].text) <= 128
        assert result.structuredContent["metadata"]["workspace"] == str(root.resolve())
    finally:
        await gateway.close()
    unexpected = [
        name for name in sys.modules
        if name.startswith(("attocode.agent", "attocode.tui", "attoswarm"))
    ]
    assert not set(unexpected) - agent_modules_before, set(unexpected) - agent_modules_before


async def test_hinted_bootstrap_keeps_complete_relevant_result_under_mcp_budget(tmp_path):
    root = project(tmp_path / "repo", "helper")
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("bootstrap", {"task_hint": "helper", "max_tokens": 1500})
        assert response_tokens(result) <= 1500
        body = json.loads(result.content[0].text)["data"]["result"]
        assert body.startswith("## Relevant Code for: helper\n")
        relevant = body.split("\n\n## ", 1)[0]
        assert "helper.py" in relevant
        assert re.search(r"^  1\. \[function\] helper\.py(?::\d+-\d+)? — helper \(score: [0-9.]+\)$",
                         relevant, re.MULTILINE)
        assert "[Truncated;" not in relevant
        assert "## Overview" in body
        no_hint = await gateway.execute_mcp("bootstrap", {"max_tokens": 1500})
        assert json.loads(no_hint.content[0].text)["data"]["result"].startswith("## Overview\n")
        no_match = await gateway.execute_mcp("bootstrap", {
            "task_hint": "unfindable_quasar_identifier", "max_tokens": 1500})
        no_match_body = json.loads(no_match.content[0].text)["data"]["result"]
        assert "No matches in this workspace." in no_match_body
        assert "## Overview" in no_match_body
    finally:
        await gateway.close()


def test_bootstrap_omits_oversized_search_section_without_partial_hit():
    metadata = {"workspace": "/repo", "source": "local", "revision": "working-tree",
                "freshness": "fresh", "truncated": False}
    hit = "## Relevant Code for: helper\nSemantic search results (1):\n" + "  1. [function] " + "x" * 1200
    body = hit + "\n\n## Overview\nSmall project."
    result = bounded_bootstrap(metadata, body, 210)
    assert response_tokens(result) <= 210
    payload = json.loads(result.content[0].text)
    assert payload["metadata"]["truncated"]
    assert payload["data"]["result"].startswith("## Relevant Code\nTop match omitted;")
    assert "  1. [function]" not in payload["data"]["result"]
    assert "## Overview" in payload["data"]["result"]


def test_long_excluded_checkout_paths_do_not_overflow_unrelated_compact_responses():
    metadata = {"workspace": "/repo", "source": "local", "revision": "working-tree",
                "freshness": "fresh", "coverage": {
                    "excluded_checkout_roots": ["src/" + "long-directory/" * 25 + str(i)
                                                for i in range(5)]}}
    result = bounded_compact(metadata, {"result": "ok"}, 200)
    assert response_tokens(result) <= 200
    payload = json.loads(result.content[0].text)
    assert payload["metadata"]["index"]["excluded_checkout_roots_found"] == 5
    assert "long-directory" not in result.content[0].text


async def test_recalled_knowledge_does_not_displace_bootstrap_search(tmp_path, monkeypatch):
    from attocode_intel import local_knowledge

    root = project(tmp_path / "repo", "helper")
    monkeypatch.setattr(local_knowledge, "execute_local_knowledge",
                        lambda *_args, **_kwargs: [{"content": "background " * 300}])
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("bootstrap", {"task_hint": "helper", "max_tokens": 1500})
        assert response_tokens(result) <= 1500
        body = json.loads(result.content[0].text)["data"]["result"]
        assert body.startswith("## Relevant Code for: helper\n")
        assert re.search(
            r"helper\.py(?::\d+-\d+)? — helper \(score:",
            body.split("\n\n## ", 1)[0],
        )
    finally:
        await gateway.close()


async def test_semantic_search_structured_hits_respect_small_budget(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    body = "needle " + "source " * 100
    for index in range(5):
        (root / f"worker_{index}.py").write_text(
            f"def needle_{index}():\n    return {body!r}\n",
        )
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        for _ in range(20):
            response = await gateway.execute("semantic_search", {
                "query": "needle", "mode": "keyword", "top_k": 10, "max_tokens": 240,
            })
            if response.structuredContent["metadata"]["ranking"]["index"]["status"] == "ready":
                break
            await asyncio.sleep(0.05)
        data = response.structuredContent["data"]
        assert len(data["results"]) <= 2
        assert all(len(hit["snippet"]) <= 120 for hit in data["results"])
        assert response.structuredContent["metadata"]["truncated"]
        assert data["ranking"]["omitted_results_due_to_budget"] > 0
        follow_up = data["follow_up"]
        assert follow_up["tool"] == "semantic_search"
        assert follow_up["reruns_current_index"] is True
        assert follow_up["arguments"]["top_k"] == 10
        assert follow_up["arguments"]["max_tokens"] > 240
        expanded = await gateway.execute("semantic_search", follow_up["arguments"])
        expanded_data = expanded.structuredContent["data"]
        assert len(expanded_data["results"]) > len(data["results"])
        assert [hit["file_path"] for hit in expanded_data["results"][:len(data["results"])]] == [
            hit["file_path"] for hit in data["results"]
        ]
        assert expanded_data.get("follow_up") is None
        compact = await gateway.execute_mcp("semantic_search", {
            "query": "needle", "mode": "keyword", "top_k": 2, "max_tokens": 1000,
        })
        compact_data = json.loads(compact.content[0].text)["data"]
        assert compact_data["follow_up"]["arguments"]["top_k"] >= 5
        assert compact_data["follow_up"]["reruns_current_index"] is True
        tightly_bounded = await gateway.execute_mcp("semantic_search", {
            "query": "needle", "mode": "keyword", "top_k": 5, "max_tokens": 600,
        })
        bounded = json.loads(tightly_bounded.content[0].text)
        assert len(bounded["data"]["results"]) < 5
        assert bounded["data"]["ranking"]["delivered_count"] == len(bounded["data"]["results"])
        assert bounded["data"]["ranking"]["omitted_results_due_to_budget"] == (
            5 - len(bounded["data"]["results"])
        )
        assert bounded["metadata"]["ranking"]["delivered_count"] == len(bounded["data"]["results"])
    finally:
        await gateway.close()


async def test_ignored_git_checkout_is_reported_and_can_be_selected(tmp_path):
    root = tmp_path / "outer"
    checkout = root / "src" / "go-checkout"
    checkout.mkdir(parents=True)
    (root / ".gitignore").write_text("src/\n")
    (root / "main.py").write_text("def outer(): return 1\n")
    (checkout / ".git").mkdir()
    (checkout / "go.mod").write_text("module example.test/go-checkout\n")
    (checkout / "main.go").write_text("package main\nfunc Greet() string { return \"hello\" }\n")
    gateway = OperationGateway(profile="daily", watch=False)
    try:
        outer = await gateway.execute_mcp("bootstrap", {"workspace": str(root), "max_tokens": 2000})
        outer_data = json.loads(outer.content[0].text)
        assert outer_data["metadata"]["index"]["excluded_checkout_roots_found"] == 1
        assert "src/go-checkout" in outer_data["data"]["result"]
        assert "workspace=" in outer_data["data"]["result"]
        status = await gateway.execute_mcp("hydration_status", {"workspace": str(root)})
        assert "src/go-checkout" in json.loads(status.content[0].text)["data"]["result"]
        inner = await gateway.execute_mcp("search_symbols", {
            "workspace": str(checkout), "name": "Greet"})
        inner_data = json.loads(inner.content[0].text)
        assert inner_data["metadata"]["workspace"] == str(checkout)
        assert inner_data["data"][0]["file_path"] == "main.go"
    finally:
        await gateway.close()


async def test_bootstrap_reports_checkout_when_no_files_are_included(tmp_path):
    root = tmp_path / "outer"
    checkout = root / "src" / "go-checkout"
    checkout.mkdir(parents=True)
    (root / ".gitignore").write_text("src/\n")
    (checkout / ".git").mkdir()
    (checkout / "main.go").write_text("package main\n")
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("bootstrap", {"max_tokens": 1500})
        body = json.loads(result.content[0].text)["data"]["result"]
        assert "No files discovered" in body
        assert "src/go-checkout" in body
        assert "Select a checkout as workspace" in body
    finally:
        await gateway.close()


async def test_bootstrap_refreshes_checkout_guidance_without_reindex(tmp_path):
    root = tmp_path / "outer"
    (root / "src").mkdir(parents=True)
    (root / ".gitignore").write_text("src/\n")
    (root / "main.py").write_text("def outer(): return 1\n")
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        initial = await gateway.execute_mcp("bootstrap", {"max_tokens": 1500})
        assert "src/go-checkout" not in initial.content[0].text

        checkout = root / "src" / "go-checkout"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        added = await gateway.execute_mcp("bootstrap", {"max_tokens": 1500})
        assert "src/go-checkout" in added.content[0].text
        status = await gateway.execute_mcp("hydration_status", {})
        assert "src/go-checkout" in status.content[0].text

        (checkout / ".git").rmdir()
        removed = await gateway.execute_mcp("bootstrap", {"max_tokens": 1500})
        assert "src/go-checkout" not in removed.content[0].text
    finally:
        await gateway.close()


async def test_bootstrap_reports_incomplete_checkout_scan_without_found_root(tmp_path):
    root = tmp_path / "outer"
    root.mkdir()
    (root / ".gitignore").write_text("src/\n")
    for index in range(129):
        (root / "src" / f"directory-{index}").mkdir(parents=True)
    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("bootstrap", {"max_tokens": 1500})
        body = json.loads(result.content[0].text)["data"]["result"]
        assert "Scan incomplete" in body
        status = await gateway.execute_mcp("hydration_status", {})
        assert "Scan incomplete" in json.loads(status.content[0].text)["data"]["result"]
    finally:
        await gateway.close()


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
            import json

            from attocode_intel.output import response_tokens
            assert result.structuredContent is None
            assert json.loads(result.content[0].text)["metadata"]["source"] == "local"
            assert response_tokens(result) <= 2000
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


def test_instructions_ask_for_notify_file_changed_only_without_a_watcher():
    from attocode_intel.gateway import OperationGateway
    assert "notify_file_changed" not in OperationGateway("", "daily").instructions
    assert "notify_file_changed" in OperationGateway("", "daily", watch=False).instructions
