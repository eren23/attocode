"""Tests for v2 structured API endpoints, file content API, pagination, and repo stats.

Tests HTTP routing and response shapes. Uses the same mock pattern as test_api.py.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import httpx
import pytest
from fastapi import HTTPException

from attocode.code_intel.api import deps
from attocode.code_intel.api.app import create_app
from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_service(project_dir: str = "/tmp/test-project") -> MagicMock:
    """Create a MagicMock with all _data() methods stubbed."""
    svc = MagicMock(spec=CodeIntelService)
    type(svc).project_dir = PropertyMock(return_value=project_dir)

    # v1 text methods (needed for v2 endpoints that still use text)
    for method in (
        "repo_map", "project_summary", "bootstrap", "explore_codebase",
        "relevant_context",
    ):
        getattr(svc, method).return_value = f"stub:{method}"

    # v2 structured _data() methods
    svc.symbols_data.return_value = [
        {"kind": "function", "name": "foo", "qualified_name": "mod.foo",
         "file_path": "src/mod.py", "start_line": 1, "end_line": 5},
    ]
    svc.search_symbols_data.return_value = [
        {"kind": "class", "name": "Bar", "qualified_name": "mod.Bar",
         "file_path": "src/mod.py", "start_line": 10, "end_line": 20},
    ]
    svc.dependencies_data.return_value = {
        "path": "src/mod.py",
        "imports": ["src/utils.py"],
        "imported_by": ["src/main.py"],
    }
    svc.dependency_graph_data.return_value = {
        "start_file": "src/mod.py", "depth": 2,
        "forward": [{"path": "src/utils.py", "depth": 1}],
        "reverse": [{"path": "src/main.py", "depth": 1}],
    }
    svc.impact_analysis_data.return_value = {
        "changed_files": ["src/mod.py"],
        "impacted_files": ["src/main.py", "tests/test_mod.py"],
        "total_impacted": 2,
    }
    svc.cross_references_data.return_value = {
        "symbol": "foo",
        "definitions": [
            {"kind": "function", "name": "foo", "qualified_name": "mod.foo",
             "file_path": "src/mod.py", "start_line": 1, "end_line": 5},
        ],
        "references": [
            {"ref_kind": "call", "file_path": "src/main.py", "line": 10},
        ],
        "total_references": 1,
    }
    svc.file_analysis_data.return_value = {
        "path": "src/mod.py", "language": "python", "line_count": 50,
        "imports": ["os", "sys"], "exports": ["foo", "Bar"],
        "chunks": [
            {"kind": "function", "name": "foo", "parent": None,
             "signature": "def foo(x: int) -> str", "start_line": 1, "end_line": 5},
        ],
    }
    svc.hotspots_data.return_value = {
        "file_hotspots": [
            {"path": "src/big.py", "line_count": 500, "symbol_count": 30,
             "public_symbols": 20, "fan_in": 10, "fan_out": 5,
             "density": 6.0, "composite": 0.95, "categories": ["god-file", "hub"]},
        ],
        "function_hotspots": [
            {"file_path": "src/big.py", "name": "process", "line_count": 100,
             "param_count": 8, "is_public": True, "has_return_type": False},
        ],
        "orphan_files": [],
    }
    svc.conventions_data.return_value = {
        "sample_size": 25, "path": "",
        "stats": {
            "total_functions": 100, "snake_names": 90, "camel_names": 10,
            "typed_return": 60, "typed_params": 50, "total_params": 200,
            "has_docstring_fn": 40, "has_docstring_cls": 5, "total_classes": 10,
            "async_count": 15, "from_imports": 80, "plain_imports": 20,
            "relative_imports": 5, "total_imports": 100,
            "decorator_counts": {"property": 3}, "dataclass_count": 2,
            "abstract_count": 1, "base_classes": {"BaseModel": 5},
            "exception_classes": [], "private_functions": 30,
            "staticmethod_count": 2, "classmethod_count": 1,
            "property_count": 3, "all_exports_count": 4, "file_sizes": [50, 100, 200],
        },
        "dir_stats": {},
    }
    svc.graph_query_data.return_value = {
        "root": "src/mod.py", "direction": "outbound", "depth": 2,
        "hops": [{"depth": 1, "files": ["src/utils.py", "src/helpers.py"]}],
        "total_reachable": 2,
    }
    svc.find_related_data.return_value = {
        "file": "src/mod.py",
        "related": [
            {"path": "src/utils.py", "score": 6, "relation_type": "direct"},
            {"path": "src/helpers.py", "score": 2, "relation_type": "transitive"},
        ],
    }
    svc.community_detection_data.return_value = {
        "method": "louvain", "modularity": 0.45,
        "communities": [
            {"id": 1, "files": ["src/a.py", "src/b.py", "src/c.py"], "size": 3,
             "theme": "src", "internal_edges": 3, "external_edges": 1,
             "hub": "src/a.py", "hub_internal_degree": 2},
        ],
    }
    svc.semantic_search_data.return_value = {
        "query": "authentication",
        "results": [
            {"file_path": "src/auth.py", "score": 0.92, "snippet": "def login()", "line": 10},
        ],
        "total": 1,
    }
    svc.security_scan_data.return_value = {
        "mode": "full", "path": "",
        "findings": [
            {"severity": "high", "category": "hardcoded-secret",
             "file_path": "src/config.py", "line": 5,
             "message": "Hardcoded API key", "suggestion": "Use env var"},
        ],
        "total_findings": 1,
        "summary": {"high": 1, "medium": 0, "low": 0},
    }

    # LSP async _data methods
    svc.lsp_definition_data = AsyncMock(return_value={
        "location": {"file": "src/mod.py", "line": 10, "col": 5},
        "error": None,
    })
    svc.lsp_references_data = AsyncMock(return_value={
        "locations": [
            {"file": "src/main.py", "line": 20, "col": 3},
            {"file": "src/test.py", "line": 5, "col": 1},
        ],
        "total": 2, "error": None,
    })
    svc.lsp_hover_data = AsyncMock(return_value={
        "content": "def foo(x: int) -> str", "file": "src/mod.py",
        "line": 10, "col": 5, "error": None,
    })
    svc.lsp_diagnostics_data.return_value = {
        "file": "src/mod.py",
        "diagnostics": [
            {"severity": "error", "source": "pyright", "code": "reportMissingImports",
             "line": 3, "col": 1, "message": "Import 'foo' not found"},
        ],
        "total": 1, "error": None,
    }
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
    deps._services["default"] = mock_service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    deps.reset()
    CodeIntelService._reset_instances()


# ---------------------------------------------------------------------------
# v2 Analysis Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_symbols(client):
    r = await client.get("/api/v2/projects/default/symbols?path=src/mod.py")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "src/mod.py"
    assert len(data["symbols"]) == 1
    assert data["symbols"][0]["kind"] == "function"
    assert data["symbols"][0]["name"] == "foo"


@pytest.mark.asyncio
async def test_v2_search_symbols(client):
    r = await client.get("/api/v2/projects/default/search-symbols?name=Bar")
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "Bar"
    assert len(data["definitions"]) == 1
    assert data["definitions"][0]["kind"] == "class"


@pytest.mark.asyncio
async def test_v2_dependencies(client):
    r = await client.get("/api/v2/projects/default/dependencies?path=src/mod.py")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "src/mod.py"
    assert "src/utils.py" in data["imports"]
    assert "src/main.py" in data["imported_by"]


@pytest.mark.asyncio
async def test_v2_dependency_graph(client):
    r = await client.post("/api/v2/projects/default/dependency-graph",
                          json={"start_file": "src/mod.py", "depth": 2})
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "edges" in data
    # Root node + forward + reverse deps
    assert len(data["nodes"]) >= 1
    assert any(n["id"] == "src/mod.py" for n in data["nodes"])


@pytest.mark.asyncio
async def test_v2_impact(client):
    r = await client.get("/api/v2/projects/default/impact?files=src/mod.py")
    assert r.status_code == 200
    data = r.json()
    assert data["total_impacted"] == 2
    assert "src/main.py" in data["impacted_files"]


@pytest.mark.asyncio
async def test_v2_cross_refs(client):
    r = await client.get("/api/v2/projects/default/cross-refs?symbol=foo")
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "foo"
    assert len(data["definitions"]) == 1
    assert len(data["references"]) == 1
    assert data["references"][0]["ref_kind"] == "call"


@pytest.mark.asyncio
async def test_v2_file_analysis(client):
    r = await client.get("/api/v2/projects/default/file-analysis?path=src/mod.py")
    assert r.status_code == 200
    data = r.json()
    assert data["language"] == "python"
    assert data["line_count"] == 50
    assert len(data["chunks"]) == 1


@pytest.mark.asyncio
async def test_v2_hotspots(client):
    r = await client.get("/api/v2/projects/default/hotspots")
    assert r.status_code == 200
    data = r.json()
    assert len(data["file_hotspots"]) == 1
    assert data["file_hotspots"][0]["composite"] == 0.95
    assert "god-file" in data["file_hotspots"][0]["categories"]
    assert len(data["function_hotspots"]) == 1


@pytest.mark.asyncio
async def test_v2_conventions(client):
    r = await client.get("/api/v2/projects/default/conventions")
    assert r.status_code == 200
    data = r.json()
    assert data["sample_size"] == 25
    assert data["stats"]["total_functions"] == 100
    assert data["stats"]["snake_names"] == 90


# ---------------------------------------------------------------------------
# v2 Graph Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_graph_query(client):
    r = await client.post("/api/v2/projects/default/graph/query",
                          json={"file": "src/mod.py"})
    assert r.status_code == 200
    data = r.json()
    assert data["root"] == "src/mod.py"
    assert data["total_reachable"] == 2
    assert len(data["hops"]) == 1


@pytest.mark.asyncio
async def test_v2_find_related(client):
    r = await client.post("/api/v2/projects/default/graph/related",
                          json={"file": "src/mod.py"})
    assert r.status_code == 200
    data = r.json()
    assert data["file"] == "src/mod.py"
    assert len(data["related"]) == 2
    assert data["related"][0]["relation_type"] == "direct"


@pytest.mark.asyncio
async def test_v2_communities(client):
    r = await client.get("/api/v2/projects/default/graph/communities")
    assert r.status_code == 200
    data = r.json()
    assert data["method"] == "louvain"
    assert data["modularity"] == 0.45
    assert len(data["communities"]) == 1
    assert data["communities"][0]["size"] == 3


# ---------------------------------------------------------------------------
# v2 Search Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_semantic_search(client):
    r = await client.post("/api/v2/projects/default/search",
                          json={"query": "authentication"})
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "authentication"
    assert data["total"] == 1
    assert data["results"][0]["score"] == 0.92


@pytest.mark.asyncio
async def test_v2_security_scan(client):
    r = await client.post("/api/v2/projects/default/security-scan",
                          json={"mode": "full"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_findings"] == 1
    assert data["findings"][0]["severity"] == "high"


# ---------------------------------------------------------------------------
# v2 LSP Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_lsp_definition(client):
    r = await client.post("/api/v2/projects/default/lsp/definition",
                          json={"file": "src/mod.py", "line": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["location"]["file"] == "src/mod.py"
    assert data["location"]["line"] == 10
    assert data["error"] is None


@pytest.mark.asyncio
async def test_v2_lsp_references(client):
    r = await client.post("/api/v2/projects/default/lsp/references",
                          json={"file": "src/mod.py", "line": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert len(data["locations"]) == 2


@pytest.mark.asyncio
async def test_v2_lsp_hover(client):
    r = await client.post("/api/v2/projects/default/lsp/hover",
                          json={"file": "src/mod.py", "line": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "def foo(x: int) -> str"


@pytest.mark.asyncio
async def test_v2_lsp_diagnostics(client):
    r = await client.get("/api/v2/projects/default/lsp/diagnostics?file=src/mod.py")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["diagnostics"][0]["severity"] == "error"


# ---------------------------------------------------------------------------
# File Content API
# ---------------------------------------------------------------------------


@pytest.fixture()
async def file_client():
    """Client with a real temp directory for file tests."""
    deps.reset()
    CodeIntelService._reset_instances()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        os.makedirs(os.path.join(tmpdir, "src"))
        with open(os.path.join(tmpdir, "src", "main.py"), "w") as f:
            f.write("def main():\n    print('hello')\n")
        with open(os.path.join(tmpdir, "README.md"), "w") as f:
            f.write("# Test Project\n")
        os.makedirs(os.path.join(tmpdir, "src", "utils"))
        with open(os.path.join(tmpdir, "src", "utils", "helpers.py"), "w") as f:
            f.write("x = 1\n")

        mock_svc = _make_mock_service(project_dir=tmpdir)
        config = CodeIntelConfig(project_dir=tmpdir)
        app = create_app(config)
        deps._services["default"] = mock_svc

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

        deps.reset()
        CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_file_content(file_client):
    r = await file_client.get("/api/v1/projects/default/files/src/main.py")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "src/main.py"
    assert "def main():" in data["content"]
    assert data["language"] == "python"
    assert data["line_count"] == 2


@pytest.mark.asyncio
async def test_file_not_found(file_client):
    r = await file_client.get("/api/v1/projects/default/files/nonexistent.py")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_tree(file_client):
    r = await file_client.get("/api/v1/projects/default/tree/src")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "src"
    names = [e["name"] for e in data["entries"]]
    assert "utils" in names
    assert "main.py" in names


@pytest.mark.asyncio
async def test_file_tree_root(file_client):
    r = await file_client.get("/api/v1/projects/default/tree")
    assert r.status_code == 200
    data = r.json()
    names = [e["name"] for e in data["entries"]]
    assert "src" in names
    assert "README.md" in names


@pytest.mark.asyncio
async def test_path_traversal_blocked(file_client):
    # httpx normalizes ../../ at URL level, so the path never reaches our handler
    # as a traversal. The result is a 404 (route not matched) which is safe.
    r = await file_client.get("/api/v1/projects/default/files/../../etc/passwd")
    assert r.status_code in (400, 404)  # blocked either way


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projects_pagination(client):
    r = await client.get("/api/v1/projects?limit=10&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert "has_more" in data
    assert data["limit"] == 10
    assert data["offset"] == 0


# ---------------------------------------------------------------------------
# v2 text endpoints removed (H7) — clients should use v1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_text_endpoints_removed(client):
    """v2 should NOT serve text-only endpoints (map, summary, bootstrap, explore)."""
    r = await client.get("/api/v2/projects/default/map")
    assert r.status_code in (404, 405)
    r = await client.get("/api/v2/projects/default/summary")
    assert r.status_code in (404, 405)
    r = await client.post("/api/v2/projects/default/bootstrap", json={})
    assert r.status_code in (404, 405)
    r = await client.post("/api/v2/projects/default/explore", json={})
    assert r.status_code in (404, 405)


# graph/context is still a valid v2 endpoint
@pytest.mark.asyncio
async def test_v2_graph_context_returns_text(client):
    r = await client.post("/api/v2/projects/default/graph/context",
                          json={"files": ["src/mod.py"]})
    assert r.status_code == 200
    assert "result" in r.json()


# ---------------------------------------------------------------------------
# T2: Path traversal — direct unit tests for _resolve_path
# ---------------------------------------------------------------------------


def test_resolve_path_blocks_dot_dot():
    from attocode.code_intel.api.routes.files import _resolve_path

    with pytest.raises(HTTPException) as exc_info:
        _resolve_path("/srv/project", "../etc/passwd")
    assert exc_info.value.status_code == 400


def test_resolve_path_blocks_prefix_collision():
    """'/srv/project' must not match '/srv/project-other/secret'."""
    from attocode.code_intel.api.routes.files import _resolve_path

    with pytest.raises(HTTPException) as exc_info:
        _resolve_path("/srv/project", "../project-other/secret.txt")
    assert exc_info.value.status_code == 400


def test_resolve_path_allows_valid_subpath(tmp_path):
    from attocode.code_intel.api.routes.files import _resolve_path

    sub = tmp_path / "src"
    sub.mkdir()
    result = _resolve_path(str(tmp_path), "src")
    assert result == str(sub)


# ---------------------------------------------------------------------------
# T3: 413 / 415 tests for file content API
# ---------------------------------------------------------------------------


@pytest.fixture()
async def file_edge_client():
    """Client with edge-case files (large, binary)."""
    deps.reset()
    CodeIntelService._reset_instances()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Large file (over 5 MB)
        large_path = os.path.join(tmpdir, "huge.txt")
        with open(large_path, "w") as f:
            f.write("x" * (6 * 1024 * 1024))

        # Binary file
        bin_path = os.path.join(tmpdir, "image.png")
        with open(bin_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_svc = _make_mock_service(project_dir=tmpdir)
        config = CodeIntelConfig(project_dir=tmpdir)
        app = create_app(config)
        deps._services["default"] = mock_svc

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

        deps.reset()
        CodeIntelService._reset_instances()


@pytest.mark.asyncio
async def test_file_too_large_413(file_edge_client):
    r = await file_edge_client.get("/api/v1/projects/default/files/huge.txt")
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_binary_file_415(file_edge_client):
    r = await file_edge_client.get("/api/v1/projects/default/files/image.png")
    assert r.status_code == 415


# ---------------------------------------------------------------------------
# T4: Unknown project_id returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_project_404(client):
    r = await client.get("/api/v2/projects/nonexistent/symbols?path=foo.py")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# T5: Missing required params return 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symbols_no_path_returns_all(client):
    """v2 symbols endpoint accepts empty path (returns all symbols)."""
    r = await client.get("/api/v2/projects/default/symbols")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == ""


@pytest.mark.asyncio
async def test_missing_required_symbol_422(client):
    r = await client.get("/api/v2/projects/default/cross-refs")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# T7: Pagination boundary tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_offset_past_total(client):
    r = await client.get("/api/v1/projects?limit=10&offset=9999")
    assert r.status_code == 200
    data = r.json()
    assert data["projects"] == []
    assert data["has_more"] is False


# ---------------------------------------------------------------------------
# T8: Empty result cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_hotspots_empty(client, mock_service):
    mock_service.hotspots_data.return_value = {
        "file_hotspots": [], "function_hotspots": [], "orphan_files": [],
    }
    r = await client.get("/api/v2/projects/default/hotspots")
    assert r.status_code == 200
    data = r.json()
    assert data["file_hotspots"] == []
    assert data["function_hotspots"] == []


@pytest.mark.asyncio
async def test_v2_find_related_empty(client, mock_service):
    mock_service.find_related_data.return_value = {
        "file": "src/orphan.py", "related": [],
    }
    r = await client.post("/api/v2/projects/default/graph/related",
                          json={"file": "src/orphan.py"})
    assert r.status_code == 200
    assert r.json()["related"] == []


@pytest.mark.asyncio
async def test_v2_semantic_search_empty(client, mock_service):
    mock_service.semantic_search_data.return_value = {
        "query": "nonexistent", "results": [], "total": 0,
    }
    r = await client.post("/api/v2/projects/default/search",
                          json={"query": "nonexistent"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["results"] == []


# ---------------------------------------------------------------------------
# T9: File tree entry fields verified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_tree_entry_fields(file_client):
    r = await file_client.get("/api/v1/projects/default/tree/src")
    assert r.status_code == 200
    data = r.json()
    file_entries = [e for e in data["entries"] if e["type"] == "file"]
    dir_entries = [e for e in data["entries"] if e["type"] == "dir"]
    assert len(file_entries) > 0
    assert len(dir_entries) > 0
    # File entries have size_bytes and language
    for entry in file_entries:
        assert "size_bytes" in entry
        assert "language" in entry
    # Dir entries have no size
    for entry in dir_entries:
        assert entry["size_bytes"] is None


# ---------------------------------------------------------------------------
# H3+H4: Parameter bounds validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotspots_top_n_capped(client):
    r = await client.get("/api/v2/projects/default/hotspots?top_n=999")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dependency_graph_depth_capped(client):
    r = await client.post("/api/v2/projects/default/dependency-graph",
                          json={"start_file": "src/mod.py", "depth": 100})
    assert r.status_code == 422
