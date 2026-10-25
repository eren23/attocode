"""Real lexical/structural evidence for opt-in file-context search."""

from __future__ import annotations

import json

import pytest
from attocode_intel.service import CodeIntelService


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    monkeypatch.delenv("ATTOCODE_INTEL_BROAD_RERANK", raising=False)
    body = 'def needle_cache():\n    return "cache needle"\n'
    for n in range(40):
        (tmp_path / f"a{n:02}.py").write_text(body)
    (tmp_path / "z_target.py").write_text(body)
    (tmp_path / "context.py").write_text(
        "from z_target import needle_cache as chosen\ndef execute():\n    return chosen()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_target.py").write_text(
        'from z_target import needle_cache\ndef test_cache():\n    assert needle_cache() == "cache needle"\n'
    )
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text(body)
    svc = CodeIntelService(str(tmp_path))
    mgr = svc._get_semantic_search()
    mgr.warm()
    assert mgr.wait_for_body_index(timeout=10)
    yield svc, mgr, tmp_path
    mgr.close()
    if svc._ast_service is not None and svc._ast_service._store is not None:
        svc._ast_service._store.close()


def test_ordinary_search_needs_no_structural_initialization(project):
    svc, _, _ = project
    data = svc.semantic_search_data("cache needle", top_k=5)
    assert data["results"] and svc._ast_service is None
    assert "context" not in data["ranking"]
    assert all("context_reason" not in row for row in data["results"])


def test_allowed_paths_retrieves_beyond_the_global_limit(project):
    _, mgr, _ = project
    assert mgr.search_candidates("cache needle", top_k=1)[0].file_path != "z_target.py"
    rows = mgr.search_candidates("cache needle", top_k=1, allowed_paths=frozenset({"z_target.py"}))
    assert rows and {r.file_path for r in rows} == {"z_target.py"}


@pytest.mark.parametrize("mask", [frozenset(), frozenset({"z_target.py"})])
def test_allowed_paths_intersects_scope_before_all_limits(project, mask):
    _, mgr, _ = project
    rows = mgr.search_candidates("cache needle", top_k=1, file_filter="a*.py", allowed_paths=mask)
    assert rows == []


def test_literal_fallback_cannot_escape_allowed_paths(project):
    _, mgr, _ = project
    assert mgr._scoped_literal_results("needle_cache", "z_target.py")
    assert (
        mgr._scoped_literal_results(
            "needle_cache", "z_target.py", allowed_paths=frozenset({"context.py"})
        )
        == []
    )


def test_context_import_adds_a_real_target_outside_the_ordinary_pool(project):
    svc, _, _ = project
    ordinary = svc.semantic_search_data("cache needle", top_k=5)
    assert "z_target.py" not in {r["file_path"] for r in ordinary["results"]}
    data = svc.semantic_search_data("cache needle", top_k=5, context_file="context.py")
    target = next(r for r in data["results"] if r["file_path"] == "z_target.py")
    assert "cache needle" in target["snippet"]
    assert target["context_reason"] == {"context_file": "context.py", "relation": "imports"}
    assert data["ranking"]["context"]["applied"] is True
    assert data["ranking"]["context"]["paths"] == ["context.py", "z_target.py"]
    assert data["ranking"]["candidate_pool_count"] <= svc._retrieval_depth(5)


def test_context_importer_finds_actual_test_evidence(project):
    svc, _, _ = project
    data = svc.semantic_search_data("tests cache needle", top_k=5, context_file="z_target.py")
    row = next(r for r in data["results"] if r["file_path"] == "tests/test_target.py")
    assert row["context_reason"]["relation"] == "importer"
    assert data["results"][0]["file_path"].startswith("tests/")


def test_context_keeps_tested_intent_second_slot(project):
    svc, _, _ = project
    data = svc.semantic_search_data(
        "where is cache needle tested", top_k=5, context_file="z_target.py"
    )
    assert not data["results"][0]["file_path"].startswith("tests/")
    assert data["results"][1]["file_path"] == "tests/test_target.py"


@pytest.mark.parametrize("name", ["missing.py", "../outside.py", "/etc/passwd", "ignored.py"])
def test_invalid_context_is_rejected_before_search(project, name):
    svc, _, _ = project
    with pytest.raises(ValueError, match="context_file"):
        svc.semantic_search_data("needle", context_file=name)


def test_context_cannot_follow_an_outside_symlink(project):
    svc, _, root = project
    (root / "escape.py").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="context_file"):
        svc.semantic_search_data("needle", context_file="escape.py")


def test_context_neighborhood_is_capped_deterministically(project):
    svc, mgr, root = project
    (root / "fanout.py").write_text("\n".join(f"import a{n:02}" for n in range(40)))
    mgr.invalidate_file("fanout.py")
    data = svc.semantic_search_data("cache needle", top_k=5, context_file="fanout.py")
    context = data["ranking"]["context"]
    assert context["paths"] == ["fanout.py", *[f"a{n:02}.py" for n in range(31)]]
    assert context["omitted_paths"] == 9


def test_unavailable_graph_is_honest_and_does_not_force_hydration(project, monkeypatch):
    svc, _, _ = project
    from attocode_intel._internal.integrations.context.ast_service import ASTService

    def unavailable(*args, **kwargs):
        raise RuntimeError("structural graph temporarily unavailable")

    monkeypatch.setattr(ASTService, "get_dependencies", unavailable)
    data = svc.semantic_search_data("cache needle", context_file="context.py")
    assert data["results"] and data["ranking"]["context"]["applied"] is False
    assert data["ranking"]["context"]["status"] == "unavailable"


def test_context_followup_preserves_the_file(project):
    svc, _, _ = project
    data = svc.semantic_search_data("cache needle", top_k=1, context_file="context.py")
    assert data["follow_up"]["arguments"]["context_file"] == "context.py"
    next_data = svc.semantic_search_data(**data["follow_up"]["arguments"])
    assert next_data["ranking"]["context"]["file"] == "context.py"


def test_context_vector_mode_is_explicitly_unsupported(project):
    svc, _, _ = project
    with pytest.raises(ValueError, match="context.*vector|vector.*context"):
        svc.semantic_search("needle", context_file="context.py", mode="vector")


async def test_local_http_carries_context_reasons_coordinates_and_followup(project):
    svc, _, _ = project
    from attocode_intel.api.providers.local_provider import LocalSearchProvider

    data = await LocalSearchProvider(svc).semantic_search(
        "cache needle", 1, "", "", context_file="context.py"
    )
    body = data.model_dump(mode="json")
    assert body["context"]["applied"] is True
    assert body["results"][0]["end_line"] >= body["results"][0]["line"]
    assert body["results"][0]["context_reason"]["context_file"] == "context.py"
    assert body["follow_up"]["arguments"]["context_file"] == "context.py"
    ordinary = (
        await LocalSearchProvider(svc).semantic_search("cache needle", 1, "", "")
    ).model_dump(mode="json")
    assert "context" not in ordinary and "follow_up" not in ordinary
    assert (
        "context_reason" not in ordinary["results"][0] and "end_line" not in ordinary["results"][0]
    )


async def test_db_context_is_rejected_without_initializing_a_provider():
    from attocode_intel.api.providers.db_provider import DbSearchProvider
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await DbSearchProvider("unused").semantic_search(
            "needle", 5, "", "", context_file="source.py"
        )
    assert error.value.status_code == 422


async def test_compact_mcp_budget_and_followup_keep_context(project):
    svc, _, root = project
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.output import response_tokens

    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        response = await gateway.execute_mcp(
            "semantic_search",
            {"query": "cache needle", "top_k": 1, "context_file": "context.py", "max_tokens": 2000},
        )
        assert not response.isError
        data = json.loads(response.content[0].text)["data"]
        assert data["ranking"]["context"]["applied"] is True
        assert data["follow_up"]["arguments"]["context_file"] == "context.py"
        assert response_tokens(response) <= 2000
    finally:
        await gateway.close()


def test_no_context_payload_remains_identical_after_context_search(project):
    svc, _, _ = project
    before = svc.semantic_search_data("cache needle", top_k=5)
    svc.semantic_search_data("cache needle", top_k=5, context_file="context.py")
    assert svc.semantic_search_data("cache needle", top_k=5) == before


def test_duplicate_global_hits_keep_their_original_scores(project):
    svc, mgr, _ = project
    global_rows = mgr.search_candidates("cache needle", 24)
    rows, _, _ = svc._contextual_search("cache needle", 24, "", "z_target.py", "keyword")

    def identity(r):
        return r.file_path, r.name, r.start_line, r.end_line

    scores = {identity(r): r.score for r in global_rows}
    shared = [r for r in rows if identity(r) in scores]
    assert shared and all(r.score == scores[identity(r)] for r in shared)
    assert len(rows) == len({identity(r) for r in rows})


def test_context_uses_one_hop_even_when_imports_form_a_cycle(project):
    svc, mgr, root = project
    (root / "third.py").write_text('def needle_cache(): return "cache needle"\n')
    (root / "z_target.py").write_text(
        'import context\nimport third\ndef needle_cache(): return "cache needle"\n'
    )
    mgr.invalidate_file(str(root / "z_target.py"))
    mgr.warm()
    assert mgr.wait_for_body_index(timeout=10)
    data = svc.semantic_search_data("cache needle", context_file="context.py")
    assert data["ranking"]["context"]["paths"] == ["context.py", "z_target.py"]
    assert all(
        r.get("context_reason") is None for r in data["results"] if r["file_path"] == "third.py"
    )


def test_typescript_alias_import_is_a_real_file_relationship(project):
    svc, mgr, root = project
    (root / "target.ts").write_text('export function needleCache() { return "cache needle"; }\n')
    (root / "caller.ts").write_text(
        'import { needleCache as selected } from "./target";\nexport function use() { return selected(); }\n'
    )
    mgr.invalidate_file(str(root / "caller.ts"))
    mgr.warm()
    assert mgr.wait_for_body_index(timeout=10)
    data = svc.semantic_search_data("cache needle", context_file="caller.ts")
    row = next(r for r in data["results"] if r["file_path"] == "target.ts")
    assert row["context_reason"]["relation"] == "imports"


def test_minimal_graph_stays_partial_without_forced_hydration(project):
    svc, _, root = project
    from attocode_intel._internal.integrations.context.ast_service import ASTService

    ast = ASTService(str(root))
    ast.initialize_skeleton(indexing_depth="minimal")
    svc._ast_service = ast
    before = ast.hydration_snapshot()
    data = svc.semantic_search_data("cache needle", context_file="context.py")
    context = data["ranking"]["context"]
    assert context["status"] == "partial" and context["absence_proven"] is False
    assert ast.hydration_snapshot()["parsed_files"] == before["parsed_files"]


def test_source_edit_refreshes_the_observed_import_neighborhood(project):
    svc, mgr, root = project
    assert (
        "z_target.py"
        in svc.semantic_search_data("cache needle", context_file="context.py")["ranking"][
            "context"
        ]["paths"]
    )
    (root / "context.py").write_text(
        "from a00 import needle_cache\ndef execute(): return needle_cache()\n"
    )
    svc.notify_file_changed(["context.py"])
    mgr.warm()
    assert mgr.wait_for_body_index(timeout=10)
    data = svc.semantic_search_data("cache needle", context_file="context.py")
    assert data["ranking"]["context"]["paths"] == ["context.py", "a00.py"]


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_actual_local_http_routes_preserve_context_and_reject_invalid_paths(
    project, monkeypatch, version
):
    import httpx
    from attocode_intel.api.auth import verify_auth
    from attocode_intel.api.providers.local_provider import LocalSearchProvider
    from attocode_intel.api.routes import search as routes
    from fastapi import FastAPI

    svc, _, _ = project

    async def service(_project):
        return svc

    async def provider(_project):
        return LocalSearchProvider(svc)

    monkeypatch.setattr(routes, "get_service_or_404", service)
    monkeypatch.setattr(routes, "get_search_provider", provider)
    app = FastAPI()
    app.dependency_overrides[verify_auth] = lambda: True
    app.include_router(routes.router_v1)
    app.include_router(routes.router_v2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        url = f"/api/{version}/projects/local/search"
        response = await client.post(
            url, json={"query": "cache needle", "top_k": 1, "context_file": "context.py"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        data = json.loads(body["result"]) if version == "v1" else body
        context = data["ranking"]["context"] if version == "v1" else data["context"]
        assert context["applied"] is True
        assert data["follow_up"]["arguments"]["context_file"] == "context.py"
        bad = await client.post(url, json={"query": "needle", "context_file": "../outside.py"})
        assert bad.status_code == 422


async def test_remote_gateway_rejects_context_before_resolving_a_snapshot(project):
    from attocode_intel.gateway import OperationGateway

    async def forbidden(*args):
        raise AssertionError("unsupported context must not open a snapshot")

    gateway = OperationGateway(resolver=forbidden)
    try:
        with pytest.raises(ValueError, match="context_file.*local"):
            await gateway.execute_mcp(
                "semantic_search", {"query": "needle", "context_file": "source.py"}
            )
    finally:
        await gateway.close()


async def test_compact_context_metadata_preserves_budget_with_long_neighbor_names(project):
    _, mgr, root = project
    names = [f"neighbor_{n:02}_" + ("shared_" * 22) for n in range(31)]
    for name in names:
        (root / (name + ".py")).write_text('def needle_cache(): return "cache needle"\n')
    (root / "fanout.py").write_text("\n".join("import " + name for name in names))
    mgr.invalidate_file(str(root / "fanout.py"))
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.output import response_tokens

    gateway = OperationGateway(str(root), "daily", watch=False)
    try:
        response = await gateway.execute_mcp(
            "semantic_search",
            {"query": "cache needle", "top_k": 5, "context_file": "fanout.py", "max_tokens": 2000},
        )
        assert not response.isError
        data = json.loads(response.content[0].text)["data"]
        assert data["results"] and data["ranking"]["context"]["applied"]
        assert "relations" not in data["ranking"]["context"]
        assert "paths" not in data["ranking"]["context"]
        assert response_tokens(response) <= 2000
    finally:
        await gateway.close()


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_http_context_vector_is_rejected_instead_of_ignored(project, monkeypatch, version):
    import httpx
    from attocode_intel.api.auth import verify_auth
    from attocode_intel.api.providers.local_provider import LocalSearchProvider
    from attocode_intel.api.routes import search as routes
    from fastapi import FastAPI

    svc, _, _ = project

    async def service(_project):
        return svc

    async def provider(_project):
        return LocalSearchProvider(svc)

    monkeypatch.setattr(routes, "get_service_or_404", service)
    monkeypatch.setattr(routes, "get_search_provider", provider)
    app = FastAPI()
    app.dependency_overrides[verify_auth] = lambda: True
    app.include_router(routes.router_v1)
    app.include_router(routes.router_v2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/{version}/projects/local/search",
            json={"query": "cache needle", "context_file": "context.py", "mode": "vector"},
        )
        assert response.status_code == 422, response.text


def test_keyword_context_followup_preserves_mode(project):
    svc, _, _ = project
    data = svc.semantic_search_data(
        "cache needle", top_k=1, context_file="context.py", mode="keyword"
    )
    assert data["follow_up"]["arguments"]["mode"] == "keyword"
    next_data = svc.semantic_search_data(**data["follow_up"]["arguments"])
    assert next_data["ranking"]["context"]["file"] == "context.py"
    assert next_data["total"] >= data["total"]


def test_empty_body_mask_does_not_open_database(project, monkeypatch):
    _, mgr, _ = project

    def forbidden(self):
        raise AssertionError("empty mask must not open database")

    monkeypatch.setattr(type(mgr), "_open_body_db", forbidden)
    assert mgr._body_search(["needle"], 5, "", allowed_paths=frozenset()) == []


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_http_keyword_context_followup_preserves_mode(project, monkeypatch, version):
    import httpx
    from attocode_intel.api.auth import verify_auth
    from attocode_intel.api.providers.local_provider import LocalSearchProvider
    from attocode_intel.api.routes import search as routes
    from fastapi import FastAPI

    svc, _, _ = project

    async def service(_project):
        return svc

    async def provider(_project):
        return LocalSearchProvider(svc)

    monkeypatch.setattr(routes, "get_service_or_404", service)
    monkeypatch.setattr(routes, "get_search_provider", provider)
    app = FastAPI()
    app.dependency_overrides[verify_auth] = lambda: True
    app.include_router(routes.router_v1)
    app.include_router(routes.router_v2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        url = f"/api/{version}/projects/local/search"
        response = await client.post(
            url,
            json={
                "query": "cache needle",
                "top_k": 1,
                "context_file": "context.py",
                "mode": "keyword",
            },
        )
        assert response.status_code == 200, response.text
        data = json.loads(response.json()["result"]) if version == "v1" else response.json()
        assert data["follow_up"]["arguments"]["mode"] == "keyword"
        continued = await client.post(url, json=data["follow_up"]["arguments"])
        assert continued.status_code == 200, continued.text
        next_data = json.loads(continued.json()["result"]) if version == "v1" else continued.json()
        context = next_data["ranking"]["context"] if version == "v1" else next_data["context"]
        assert context["file"] == "context.py"
        assert next_data["total"] >= data["total"]
