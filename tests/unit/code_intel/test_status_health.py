from __future__ import annotations

from types import SimpleNamespace

from attocode.code_intel import server as code_intel_server
from attocode.code_intel.service import CodeIntelService


def test_semantic_search_status_surfaces_degraded_health(monkeypatch) -> None:
    search_tools = code_intel_server._search_tools
    progress = SimpleNamespace(
        status="idle",
        coverage=0.0,
        indexed_files=0,
        total_files=0,
        failed_files=0,
        elapsed_seconds=0.0,
    )
    mgr = SimpleNamespace(
        provider_name="mock",
        is_available=False,
        is_index_ready=lambda: False,
        get_index_progress=lambda: progress,
    )
    ctx = SimpleNamespace(_files=[], discover_files=lambda: [])
    ast = SimpleNamespace(_store=SimpleNamespace(stats=lambda: {"files": 0}), _ast_cache={})

    monkeypatch.setattr(search_tools, "_get_semantic_search", lambda: mgr)
    monkeypatch.setattr(search_tools, "_get_context_mgr", lambda: ctx)
    monkeypatch.setattr(search_tools, "_get_ast_service", lambda: ast)

    result = search_tools.semantic_search_status()

    assert "Health: degraded" in result
    assert "Discovery count: 0" in result
    assert "AST indexed files: 0" in result
    assert "no_files_discovered" in result


def test_service_indexing_status_includes_health_snapshot(monkeypatch, tmp_path) -> None:
    svc = CodeIntelService(str(tmp_path))
    progress = SimpleNamespace(
        status="indexing",
        coverage=0.5,
        indexed_files=5,
        total_files=10,
        failed_files=0,
        elapsed_seconds=1.2,
    )
    mgr = SimpleNamespace(
        provider_name="mock",
        is_available=True,
        is_index_ready=lambda: True,
        get_index_progress=lambda: progress,
    )
    ctx = SimpleNamespace(_files=[object(), object(), object()], discover_files=lambda: [object(), object(), object()])
    ast = SimpleNamespace(_store=SimpleNamespace(stats=lambda: {"files": 3}), _ast_cache={})

    monkeypatch.setattr(svc, "_get_semantic_search", lambda: mgr)
    monkeypatch.setattr(svc, "_get_context_mgr", lambda: ctx)
    monkeypatch.setattr(svc, "_get_ast_service", lambda: ast)

    result = svc.indexing_status()

    assert result["health_status"] == "healthy"
    assert result["discovery_count"] == 3
    assert result["ast_indexed_files"] == 3
    assert result["active_backend"] == "local"
