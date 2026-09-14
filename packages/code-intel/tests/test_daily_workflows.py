from __future__ import annotations

import json

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.onboarding import configure_client


async def test_project_summary_during_background_hydration(tmp_path):
    from threading import Event, Thread
    from types import SimpleNamespace

    (tmp_path / "early.py").write_text("import fastapi\n")
    (tmp_path / "late.py").write_text("import django\n")
    gateway = OperationGateway(str(tmp_path), watch=False)
    reading, hydrated = Event(), Event()
    worker = None

    class EarlyAST:
        @property
        def imports(self):
            reading.set()
            assert hydrated.wait(5), "Background hydration did not finish"
            return [SimpleNamespace(module="fastapi")]

    try:
        await gateway.execute("project_summary", {})
        ast = next(iter(gateway._stores.values()))["service"]._ast_service
        ast._ast_cache = {"early.py": EarlyAST()}

        def hydrate():
            if reading.wait(5):
                ast._ast_cache["late.py"] = SimpleNamespace(
                    imports=[SimpleNamespace(module="django")]
                )
                hydrated.set()

        worker = Thread(target=hydrate, daemon=True)
        worker.start()
        first = await gateway.execute("project_summary", {})
        assert hydrated.is_set()
        assert "FastAPI" in first.content[0].text
        assert "Django" not in first.content[0].text
        second = await gateway.execute("project_summary", {})
        assert "Django" in second.content[0].text
    finally:
        reading.set()
        if worker:
            worker.join(timeout=5)
        await gateway.close()


async def test_knowledge_is_shared_between_local_clients_and_stale(tmp_path):
    (tmp_path / "helpers.py").write_text("def helper(): pass\n")
    first = OperationGateway(str(tmp_path), watch=False)
    recorded = await first.execute(
        "record_learning",
        {
            "type": "convention",
            "description": "Helpers have no side effects",
            "scope": "helpers.py",
        },
    )
    number = recorded.structuredContent["data"]["id"]
    await first.close()
    second = OperationGateway(str(tmp_path), watch=False)
    try:
        (tmp_path / "helpers.py").write_text("def helper(): print('changed')\n")
        recalled = await second.execute("recall", {"query": "helpers"})
        row = recalled.structuredContent["data"][0]
        assert row["id"] == number and row["stale"]
        bootstrap = await second.execute("bootstrap", {"task_hint": "helpers", "max_tokens": 1000})
        assert "Helpers have no side effects" not in bootstrap.content[0].text
        await second.execute("update_learning", {"learning_id": number, "status": "archived"})
        assert not (await second.execute("list_learnings", {})).structuredContent["data"]
    finally:
        await second.close()


async def test_cross_repo_results_have_rank_and_provenance(tmp_path):
    paths = []
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        (root / "helper.py").write_text("def important_helper(): return 1\n")
        paths.append(str(root))
    gateway = OperationGateway(watch=False)
    try:
        result = await gateway.execute(
            "cross_repo_search", {"query": "important_helper", "workspaces": paths}
        )
        assert {row["workspace"] for row in result.structuredContent["data"]} == set(paths)
        assert all(row["fusion_score"] > 0 for row in result.structuredContent["data"])
    finally:
        await gateway.close()


async def test_idle_workspace_eviction_preserves_durable_knowledge(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    gateway = OperationGateway(watch=False, max_workspaces=1)
    try:
        await gateway.execute(
            "record_learning",
            {"workspace": str(a), "type": "gotcha", "description": "Remember eviction"},
        )
        await gateway.execute("capabilities", {"workspace": str(b)})
        assert len(gateway._workers) == 1
        result = await gateway.execute("recall", {"workspace": str(a), "query": "eviction"})
        assert result.structuredContent["data"][0]["description"] == "Remember eviction"
    finally:
        await gateway.close()


async def test_failed_review_is_incomplete_and_scopes_findings(tmp_path, monkeypatch):
    from attocode_intel.service import CodeIntelService

    (tmp_path / "changed.py").write_text("def changed(): pass\n")
    monkeypatch.setattr(
        CodeIntelService,
        "security_scan_data",
        lambda *a, **kw: {
            "findings": [
                {
                    "file_path": "unchanged.py",
                    "message": "HIGH in a header is not a changed-file finding",
                }
            ]
        },
    )
    gateway = OperationGateway(str(tmp_path), watch=False)
    try:
        result = await gateway.execute("review_change", {"files": ["changed.py"], "mode": "quick"})
        assert result.structuredContent["data"]["findings"] == []

        def failed(*args, **kwargs):
            raise RuntimeError("Scanner unavailable")

        monkeypatch.setattr(CodeIntelService, "security_scan_data", failed)
        result = await gateway.execute("review_change", {"files": ["changed.py"], "mode": "quick"})
        assert not result.structuredContent["data"]["complete"]
        assert "incomplete" in result.content[0].text
    finally:
        await gateway.close()


@pytest.mark.parametrize("client,config", [("claude", ".mcp.json"), ("cursor", ".cursor/mcp.json")])
def test_local_and_remote_config_coexist_and_restore_existing(tmp_path, client, config):
    path = tmp_path / config
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = {"command": "custom-intelligence", "args": ["custom"]}
    path.write_text(
        json.dumps(
            {"mcpServers": {"attocode-code-intel": previous, "unrelated": {"command": "unchanged"}}}
        )
    )
    configure_client(client, str(tmp_path))
    configure_client(client, str(tmp_path), server="https://intel.example.com", repo="repo-id")
    servers = json.loads(path.read_text())["mcpServers"]
    assert "attocode-code-intel-remote" in servers and "attocode-code-intel" in servers
    assert servers["unrelated"]["command"] == "unchanged"
    assert "ATTOCODE_API_KEY" in json.dumps(servers["attocode-code-intel-remote"])
    configure_client(client, str(tmp_path), remove=True)
    assert json.loads(path.read_text())["mcpServers"]["attocode-code-intel"] == previous
