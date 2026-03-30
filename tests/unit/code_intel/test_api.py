"""Integration tests for the HTTP API (38 routes).

Uses httpx.AsyncClient + ASGITransport with a mocked CodeIntelService.
Tests HTTP routing, status codes, request parsing, and auth — NOT the
underlying code intelligence logic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
import pytest

from attocode.code_intel.api import deps
from attocode.code_intel.api.app import create_app
from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_service(project_dir: str = "/tmp/test-project") -> MagicMock:
    """Create a MagicMock with all CodeIntelService methods stubbed."""
    svc = MagicMock(spec=CodeIntelService)
    type(svc).project_dir = PropertyMock(return_value=project_dir)

    # Sync methods returning stub strings
    for method in (
        "repo_map", "symbols", "search_symbols", "dependencies",
        "impact_analysis", "cross_references", "file_analysis",
        "dependency_graph", "hotspots", "conventions", "project_summary",
        "bootstrap", "explore_codebase", "security_scan",
        "notify_file_changed", "semantic_search", "semantic_search_status", "fast_search",
        "graph_query", "find_related", "community_detection",
        "relevant_context", "repo_map_ranked", "dead_code", "distill",
        "readiness_report", "bug_scan", "code_evolution", "recent_changes",
        "change_coupling", "churn_hotspots", "merge_risk",
        "record_learning", "recall",
        "learning_feedback", "list_learnings",
        "record_adr", "list_adrs", "get_adr", "update_adr_status",
        "lsp_diagnostics",
    ):
        getattr(svc, method).return_value = f"stub:{method}"

    # Async methods
    for method in ("lsp_definition", "lsp_references", "lsp_hover", "lsp_enrich"):
        setattr(svc, method, AsyncMock(return_value=f"stub:{method}"))

    # Internal methods used by reindex
    svc._get_ast_service = MagicMock()
    svc._get_context_mgr = MagicMock()

    return svc


@pytest.fixture()
def mock_service():
    return _make_mock_service()


@pytest.fixture()
async def client(mock_service):
    deps.reset()
    CodeIntelService._reset_instances()

    config = CodeIntelConfig(project_dir="/tmp/test-project")
    app = create_app(config)

    # Inject mock service
    deps._services["default"] = mock_service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    deps.reset()
    CodeIntelService._reset_instances()


@pytest.fixture()
async def auth_client(mock_service):
    """Client with API key auth enabled."""
    deps.reset()
    CodeIntelService._reset_instances()

    config = CodeIntelConfig(project_dir="/tmp/test-project", api_key="testkey")
    app = create_app(config)
    deps._services["default"] = mock_service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    deps.reset()
    CodeIntelService._reset_instances()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_with_project(client):
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ready_without_project():
    deps.reset()
    config = CodeIntelConfig()
    app = create_app(config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/ready")
    assert r.json()["status"] == "not_ready"
    deps.reset()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects(client):
    r = await client.get("/api/v1/projects")
    assert r.status_code == 200
    data = r.json()
    assert len(data["projects"]) >= 1


@pytest.mark.asyncio
async def test_get_project(client):
    r = await client.get("/api/v1/projects/default")
    assert r.status_code == 200
    assert r.json()["id"] == "default"


@pytest.mark.asyncio
async def test_get_project_404(client):
    r = await client.get("/api/v1/projects/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_register_project(client, tmp_path):
    r = await client.post("/api/v1/projects", json={"path": str(tmp_path)})
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_register_bad_path(client):
    r = await client.post("/api/v1/projects", json={"path": "/nonexistent/path/xyz"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_register_blocked_system_dir(auth_client):
    r = await auth_client.post(
        "/api/v1/projects",
        json={"path": "/etc"},
        headers={"Authorization": "Bearer testkey"},
    )
    assert r.status_code == 400
    assert "system directory" in r.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_returns_existing(client, mock_service, tmp_path):
    """Registering the same path twice returns the existing project."""
    # First register creates a new project
    r1 = await client.post("/api/v1/projects", json={"path": str(tmp_path)})
    assert r1.status_code == 200
    pid1 = r1.json()["id"]

    # Second register of same path returns the same project
    r2 = await client.post("/api/v1/projects", json={"path": str(tmp_path)})
    assert r2.status_code == 200
    assert r2.json()["id"] == pid1


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_map(client):
    r = await client.get("/api/v1/projects/default/map")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:repo_map"


@pytest.mark.asyncio
async def test_project_summary(client):
    r = await client.get("/api/v1/projects/default/summary")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:project_summary"


@pytest.mark.asyncio
async def test_symbols(client):
    r = await client.get("/api/v1/projects/default/symbols", params={"path": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:symbols"


@pytest.mark.asyncio
async def test_search_symbols(client):
    r = await client.get("/api/v1/projects/default/search-symbols", params={"name": "Foo"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:search_symbols"


@pytest.mark.asyncio
async def test_dependencies(client):
    r = await client.get("/api/v1/projects/default/dependencies", params={"path": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:dependencies"


@pytest.mark.asyncio
async def test_impact_analysis(client):
    r = await client.get("/api/v1/projects/default/impact", params=[("files", "a.py"), ("files", "b.py")])
    assert r.status_code == 200
    assert r.json()["result"] == "stub:impact_analysis"


@pytest.mark.asyncio
async def test_cross_refs(client):
    r = await client.get("/api/v1/projects/default/cross-refs", params={"symbol": "Foo"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:cross_references"


@pytest.mark.asyncio
async def test_file_analysis(client):
    r = await client.get("/api/v1/projects/default/file-analysis", params={"path": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:file_analysis"


@pytest.mark.asyncio
async def test_dependency_graph(client):
    r = await client.post("/api/v1/projects/default/dependency-graph", json={"start_file": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:dependency_graph"


@pytest.mark.asyncio
async def test_hotspots(client):
    r = await client.get("/api/v1/projects/default/hotspots")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:hotspots"


@pytest.mark.asyncio
async def test_conventions(client):
    r = await client.get("/api/v1/projects/default/conventions")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:conventions"


@pytest.mark.asyncio
async def test_bootstrap(client):
    r = await client.post("/api/v1/projects/default/bootstrap", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:bootstrap"


@pytest.mark.asyncio
async def test_explore(client):
    r = await client.post("/api/v1/projects/default/explore", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:explore_codebase"


@pytest.mark.asyncio
async def test_security_scan(client):
    r = await client.post("/api/v1/projects/default/security-scan", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:security_scan"


@pytest.mark.asyncio
async def test_notify(client):
    r = await client.post("/api/v1/projects/default/notify", json={"files": ["a.py"]})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:notify_file_changed"


@pytest.mark.asyncio
async def test_repo_map_ranked(client):
    r = await client.post("/api/v1/projects/default/repo-map-ranked", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:repo_map_ranked"


@pytest.mark.asyncio
async def test_dead_code(client):
    r = await client.post("/api/v1/projects/default/dead-code", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:dead_code"


@pytest.mark.asyncio
async def test_distill(client):
    r = await client.post("/api/v1/projects/default/distill", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:distill"


@pytest.mark.asyncio
async def test_readiness_report(client):
    r = await client.post("/api/v1/projects/default/readiness-report", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:readiness_report"


@pytest.mark.asyncio
async def test_bug_scan(client):
    r = await client.post("/api/v1/projects/default/bug-scan", json={})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:bug_scan"


@pytest.mark.asyncio
async def test_analysis_404(client):
    r = await client.get("/api/v1/projects/unknown/map")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_search(client):
    r = await client.post("/api/v1/projects/default/search", json={"query": "auth"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:semantic_search"


@pytest.mark.asyncio
async def test_semantic_search_status(client):
    r = await client.get("/api/v1/projects/default/semantic-search-status")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:semantic_search_status"


@pytest.mark.asyncio
async def test_fast_search(client):
    r = await client.post("/api/v1/projects/default/fast-search", json={"pattern": "foo"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:fast_search"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_query(client):
    r = await client.post("/api/v1/projects/default/graph/query", json={"file": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:graph_query"


@pytest.mark.asyncio
async def test_find_related(client):
    r = await client.post("/api/v1/projects/default/graph/related", json={"file": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:find_related"


@pytest.mark.asyncio
async def test_community_detection(client):
    r = await client.get("/api/v1/projects/default/graph/communities")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:community_detection"


@pytest.mark.asyncio
async def test_relevant_context(client):
    r = await client.post("/api/v1/projects/default/graph/context", json={"files": ["a.py"]})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:relevant_context"


@pytest.mark.asyncio
async def test_graph_dsl(client):
    with patch("attocode.code_intel.tools.analysis_tools.graph_dsl", return_value="stub:graph_dsl"):
        r = await client.post("/api/v1/projects/default/graph/dsl", json={"query": "MATCH a RETURN a"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:graph_dsl"


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_learning(client):
    r = await client.post(
        "/api/v1/projects/default/learnings",
        json={"type": "pattern", "description": "test"},
    )
    assert r.status_code == 200
    assert r.json()["result"] == "stub:record_learning"


@pytest.mark.asyncio
async def test_recall(client):
    r = await client.get("/api/v1/projects/default/learnings/recall", params={"query": "test"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:recall"


@pytest.mark.asyncio
async def test_learning_feedback(client):
    r = await client.post(
        "/api/v1/projects/default/learnings/1/feedback",
        json={"helpful": True},
    )
    assert r.status_code == 200
    assert r.json()["result"] == "stub:learning_feedback"


@pytest.mark.asyncio
async def test_list_learnings(client):
    r = await client.get("/api/v1/projects/default/learnings")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:list_learnings"


@pytest.mark.asyncio
async def test_record_adr(client):
    r = await client.post(
        "/api/v1/projects/default/adrs",
        json={"title": "Use X", "context": "Need Y", "decision": "Do Z"},
    )
    assert r.status_code == 200
    assert r.json()["result"] == "stub:record_adr"


@pytest.mark.asyncio
async def test_list_adrs(client):
    r = await client.get("/api/v1/projects/default/adrs")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:list_adrs"


@pytest.mark.asyncio
async def test_get_adr(client):
    r = await client.get("/api/v1/projects/default/adrs/1")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:get_adr"


@pytest.mark.asyncio
async def test_update_adr_status(client):
    r = await client.post("/api/v1/projects/default/adrs/1/status", json={"status": "accepted"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:update_adr_status"


# ---------------------------------------------------------------------------
# LSP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lsp_definition(client):
    r = await client.post("/api/v1/projects/default/lsp/definition", json={"file": "a.py", "line": 1})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:lsp_definition"


@pytest.mark.asyncio
async def test_lsp_references(client):
    r = await client.post("/api/v1/projects/default/lsp/references", json={"file": "a.py", "line": 1})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:lsp_references"


@pytest.mark.asyncio
async def test_lsp_hover(client):
    r = await client.post("/api/v1/projects/default/lsp/hover", json={"file": "a.py", "line": 1})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:lsp_hover"


@pytest.mark.asyncio
async def test_lsp_diagnostics(client):
    r = await client.get("/api/v1/projects/default/lsp/diagnostics", params={"file": "a.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:lsp_diagnostics"


@pytest.mark.asyncio
async def test_lsp_enrich(client):
    r = await client.post("/api/v1/projects/default/lsp/enrich", json={"files": ["a.py"]})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:lsp_enrich"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_evolution(client):
    r = await client.get("/api/v1/projects/default/history/evolution", params={"path": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:code_evolution"


@pytest.mark.asyncio
async def test_recent_changes(client):
    r = await client.get("/api/v1/projects/default/history/recent-changes")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:recent_changes"


@pytest.mark.asyncio
async def test_change_coupling(client):
    r = await client.post("/api/v1/projects/default/history/change-coupling", json={"file": "foo.py"})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:change_coupling"


@pytest.mark.asyncio
async def test_churn_hotspots(client):
    r = await client.get("/api/v1/projects/default/history/churn-hotspots")
    assert r.status_code == 200
    assert r.json()["result"] == "stub:churn_hotspots"


@pytest.mark.asyncio
async def test_merge_risk(client):
    r = await client.post("/api/v1/projects/default/history/merge-risk", json={"files": ["foo.py"]})
    assert r.status_code == 200
    assert r.json()["result"] == "stub:merge_risk"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_no_header_401(auth_client):
    r = await auth_client.get("/api/v1/projects")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_wrong_key_401(auth_client):
    r = await auth_client.get("/api/v1/projects", headers={"Authorization": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_correct_key_200(auth_client):
    r = await auth_client.get("/api/v1/projects", headers={"Authorization": "Bearer testkey"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_wildcard_no_credentials():
    """Wildcard origins should NOT send Access-Control-Allow-Credentials."""
    deps.reset()
    CodeIntelService._reset_instances()
    config = CodeIntelConfig(project_dir="/tmp/test-project", cors_origins=["*"])
    app = create_app(config)
    deps._services["default"] = _make_mock_service()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.options(
            "/health",
            headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
        )
    assert r.headers.get("access-control-allow-credentials") != "true"
    deps.reset()
    CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_cors_specific_origin_allows_credentials():
    """Specific origins should send Access-Control-Allow-Credentials: true."""
    deps.reset()
    CodeIntelService._reset_instances()
    config = CodeIntelConfig(
        project_dir="/tmp/test-project",
        cors_origins=["http://example.com"],
    )
    app = create_app(config)
    deps._services["default"] = _make_mock_service()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.options(
            "/health",
            headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
        )
    assert r.headers.get("access-control-allow-credentials") == "true"
    deps.reset()
    CodeIntelService._reset_instances()


# ---------------------------------------------------------------------------
# Reindex (Tier 1A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reindex_success(client, mock_service):
    r = await client.post("/api/v1/projects/default/reindex")
    assert r.status_code == 200
    assert r.json()["result"] == "Reindex complete"
    mock_service._get_ast_service.assert_called_once()
    mock_service._get_context_mgr.assert_called_once()


@pytest.mark.asyncio
async def test_reindex_404(client):
    r = await client.post("/api/v1/projects/nonexistent/reindex")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reindex_clears_caches(client, mock_service):
    """Verify caches are set to None before reinit methods are called."""
    call_order = []

    def track_ast():
        call_order.append(("get_ast", mock_service._ast_service))

    def track_ctx():
        call_order.append(("get_ctx", mock_service._context_mgr))

    mock_service._get_ast_service.side_effect = track_ast
    mock_service._get_context_mgr.side_effect = track_ctx

    r = await client.post("/api/v1/projects/default/reindex")
    assert r.status_code == 200
    assert call_order[0] == ("get_ast", None)
    assert call_order[1] == ("get_ctx", None)


# ---------------------------------------------------------------------------
# Auth bypass for health endpoints (Tier 1B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_bypasses_auth(auth_client):
    r = await auth_client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_ready_bypasses_auth(auth_client):
    r = await auth_client.get("/ready")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Path security (Tier 1C)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blocked_path", ["/var", "/usr", "/sys", "/proc", "/dev"])
@pytest.mark.asyncio
async def test_register_blocked_prefixes(auth_client, blocked_path):
    with patch("attocode.code_intel.api.routes.projects.os.path.isdir", return_value=True):
        r = await auth_client.post(
            "/api/v1/projects",
            json={"path": blocked_path},
            headers={"Authorization": "Bearer testkey"},
        )
    assert r.status_code == 400
    assert "system directory" in r.json()["detail"]


@pytest.mark.asyncio
async def test_register_path_traversal(auth_client):
    """Path traversal normalizes to a blocked prefix via os.path.abspath."""
    with patch("attocode.code_intel.api.routes.projects.os.path.isdir", return_value=True):
        r = await auth_client.post(
            "/api/v1/projects",
            json={"path": "/tmp/safe/../../etc"},
            headers={"Authorization": "Bearer testkey"},
        )
    assert r.status_code == 400
    assert "system directory" in r.json()["detail"]


@pytest.mark.asyncio
async def test_register_system_dir_allowed_without_auth(client):
    """Without auth configured, system directory blocking is skipped."""
    with (
        patch("attocode.code_intel.api.routes.projects.os.path.isdir", return_value=True),
        patch("attocode.code_intel.api.deps.CodeIntelService.get_instance", return_value=MagicMock()),
    ):
        r = await client.post("/api/v1/projects", json={"path": "/etc"})
    assert r.status_code == 200
    assert "system directory" not in r.text


# ---------------------------------------------------------------------------
# Service error propagation (Tier 1D)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_service_error_propagates(client, mock_service):
    """Unhandled sync errors propagate (→ 500 in production)."""
    mock_service.repo_map.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        await client.get("/api/v1/projects/default/map")


@pytest.mark.asyncio
async def test_async_service_error_propagates(client, mock_service):
    """Unhandled async errors propagate (→ 500 in production)."""
    mock_service.lsp_definition.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        await client.post(
            "/api/v1/projects/default/lsp/definition",
            json={"file": "a.py", "line": 1},
        )


# ---------------------------------------------------------------------------
# Missing required query params → 422 (Tier 2A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symbols_missing_path_422(client):
    r = await client.get("/api/v1/projects/default/symbols")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_symbols_missing_name_422(client):
    r = await client.get("/api/v1/projects/default/search-symbols")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_impact_missing_files_422(client):
    r = await client.get("/api/v1/projects/default/impact")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_cross_refs_missing_symbol_422(client):
    r = await client.get("/api/v1/projects/default/cross-refs")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_lsp_diagnostics_missing_file_422(client):
    r = await client.get("/api/v1/projects/default/lsp/diagnostics")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_code_evolution_missing_path_422(client):
    r = await client.get("/api/v1/projects/default/history/evolution")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Missing/invalid request bodies → 422 (Tier 2B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dependency_graph_empty_body_ok(client):
    """Empty body is valid — start_file defaults to '' and depth to 3."""
    r = await client.post("/api/v1/projects/default/dependency-graph", json={})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_semantic_search_empty_body_422(client):
    r = await client.post("/api/v1/projects/default/search", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_record_learning_empty_body_422(client):
    r = await client.post("/api/v1/projects/default/learnings", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_lsp_definition_empty_body_422(client):
    r = await client.post("/api/v1/projects/default/lsp/definition", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_invalid_json_422(client):
    r = await client.post(
        "/api/v1/projects/default/bootstrap",
        content="not json{",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Path param validation (Tier 2C)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learning_feedback_non_integer_id_422(client):
    r = await client.post(
        "/api/v1/projects/default/learnings/abc/feedback",
        json={"helpful": True},
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/projects/default/map?branch=feature", None),
        ("post", "/api/v1/projects/default/bootstrap?branch=feature", {}),
        ("post", "/api/v1/projects/default/search?branch=feature", {"query": "auth"}),
        ("post", "/api/v1/projects/default/graph/query?branch=feature", {"file": "foo.py"}),
        ("get", "/api/v1/projects/default/lsp/diagnostics?file=a.py&branch=feature", None),
        ("get", "/api/v1/projects/default/files/main.py?branch=feature", None),
        ("get", "/api/v1/projects/default/learnings?branch=feature", None),
        ("get", "/api/v1/projects/default/history/recent-changes?branch=feature", None),
        ("post", "/api/v1/projects/default/adrs?branch=feature", {"title": "T", "context": "C", "decision": "D"}),
    ],
)
@pytest.mark.asyncio
async def test_v1_branch_rejected_in_local_mode(client, method, path, payload):
    request = getattr(client, method)
    kwargs = {"json": payload} if payload is not None else {}
    r = await request(path, **kwargs)
    assert r.status_code == 422
    assert "Branch scoping is only supported" in r.json()["detail"]


# ---------------------------------------------------------------------------
# CORS response headers (Tier 3A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_response_has_allow_origin():
    """Actual GET response (not preflight) includes Allow-Origin header."""
    deps.reset()
    CodeIntelService._reset_instances()
    config = CodeIntelConfig(
        project_dir="/tmp/test-project",
        cors_origins=["http://example.com"],
    )
    app = create_app(config)
    deps._services["default"] = _make_mock_service()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health", headers={"Origin": "http://example.com"})
    assert r.headers.get("access-control-allow-origin") == "http://example.com"
    deps.reset()
    CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_auth_jwt_on_analysis_endpoint():
    """JWT tokens should work on endpoints that previously used verify_api_key."""
    try:
        import jose  # noqa: F401

        from attocode.code_intel.api.auth.jwt import create_access_token
    except ImportError:
        pytest.skip("python-jose not installed")

    deps.reset()
    CodeIntelService._reset_instances()

    user_id = __import__("uuid").uuid4()
    org_id = __import__("uuid").uuid4()

    config = CodeIntelConfig(
        project_dir="/tmp/test-project",
        database_url="postgresql+asyncpg://localhost/test",
        secret_key="test-secret",
    )
    # Patch out DB lifecycle (no real DB in unit tests)
    with patch("attocode.code_intel.api.app._lifespan") as mock_lifespan:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mock_lifespan.side_effect = _noop_lifespan
        app = create_app(config)

    deps._services["default"] = _make_mock_service()

    token = create_access_token(user_id, org_id, scopes=["read:symbols"])
    headers = {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # These endpoints previously used verify_api_key
        r = await c.get("/api/v1/projects/default/map", headers=headers)
        assert r.status_code == 200

        r = await c.get("/api/v1/projects/default/symbols", params={"path": "foo.py"}, headers=headers)
        assert r.status_code == 200

        r = await c.get("/api/v1/projects", headers=headers)
        assert r.status_code == 200

    deps.reset()
    CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_auth_jwt_rejected_without_header_service_mode():
    """Service mode with no auth header should return 401 on guarded endpoints."""
    try:
        import jose  # noqa: F401
    except ImportError:
        pytest.skip("python-jose not installed")

    deps.reset()
    CodeIntelService._reset_instances()

    config = CodeIntelConfig(
        project_dir="/tmp/test-project",
        database_url="postgresql+asyncpg://localhost/test",
        secret_key="test-secret",
    )
    with patch("attocode.code_intel.api.app._lifespan") as mock_lifespan:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mock_lifespan.side_effect = _noop_lifespan
        app = create_app(config)

    deps._services["default"] = _make_mock_service()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/projects/default/map")
        assert r.status_code == 401

    deps.reset()
    CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_cors_non_matching_origin():
    """Non-matching origin should not get Access-Control-Allow-Origin."""
    deps.reset()
    CodeIntelService._reset_instances()
    config = CodeIntelConfig(
        project_dir="/tmp/test-project",
        cors_origins=["http://allowed.com"],
    )
    app = create_app(config)
    deps._services["default"] = _make_mock_service()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health", headers={"Origin": "http://disallowed.com"})
    assert r.headers.get("access-control-allow-origin") != "http://disallowed.com"
    deps.reset()
    CodeIntelService._reset_instances()
