"""Useful evidence must not depend on a file landing in the initial skeleton."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from attocode_intel._internal.integrations.context import ast_service
from attocode_intel.gateway import OperationGateway


@pytest.fixture
def cold_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    monkeypatch.setattr(ast_service, "skeleton_budget", lambda *_: 0)
    monkeypatch.setattr(ast_service.ASTService, "start_hydration", lambda _: None)
    (tmp_path / "helper.py").write_text("def locate_value():\n    return 7\n")
    (tmp_path / "caller.py").write_text(
        "from helper import locate_value\ndef caller():\n    return locate_value()\n")
    (tmp_path / "comments.py").write_text("# def locate_value(): documentation only\n")
    (tmp_path / "ignored.py").write_text("def locate_value(): return 99\n")
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    return tmp_path


async def result(gateway, operation, arguments):
    response = await gateway.execute_mcp(operation, arguments)
    assert not response.isError
    return json.loads(response.content[0].text)


async def test_cold_search_returns_definitions_and_keeps_partial_metadata(cold_workspace):
    gateway = OperationGateway(str(cold_workspace), "daily", watch=False)
    try:
        found = await result(gateway, "search_symbols", {"name": "LOCATE_VALUE", "kind": "function"})
        assert [(r["file_path"], r["name"]) for r in found["data"]] == [("helper.py", "locate_value")]
        assert found["metadata"]["analysis"] == "partial"
        assert found["metadata"]["absence_proven"] is False
        assert (await result(gateway, "search_symbols", {"name": "not_a_definition"}))["data"] == []
        (cold_workspace / "helper.py").write_text("def renamed_value():\n    return 8\n")
        old = await result(gateway, "search_symbols", {"name": "locate_value"})
        assert all(r["name"] != "locate_value" for r in old["data"])
        new = await result(gateway, "search_symbols", {"name": "renamed_value"})
        assert new["data"][0]["name"] == "renamed_value"
    finally:
        await gateway.close()


async def test_existing_skeleton_match_does_not_hide_other_definitions(cold_workspace):
    (cold_workspace / "other.py").write_text("def locate_value(): return 2\n")
    gateway = OperationGateway(str(cold_workspace), "daily", watch=False)
    try:
        await result(gateway, "symbols", {"path": "helper.py"})
        found = await result(gateway, "search_symbols", {"name": "locate_", "limit": 10})
        assert {r["file_path"] for r in found["data"]} == {"helper.py", "other.py"}
    finally:
        await gateway.close()


async def test_cold_context_includes_center_and_neighbor_symbols(cold_workspace):
    gateway = OperationGateway(str(cold_workspace), "daily", watch=False)
    try:
        data = await result(gateway, "relevant_context", {"files": ["./caller.py"], "depth": 1})
        context = data["data"]["result"]
        assert "fn caller(" in context
        assert "fn locate_value(" in context
        assert "ignored.py" not in context
        assert data["metadata"]["analysis"] == "partial"
        outside = await result(gateway, "relevant_context", {"files": ["../elsewhere.py"]})
        assert outside["data"]["result"] == "No valid files provided."
    finally:
        await gateway.close()


async def test_qualified_search_finds_method_before_hydration(cold_workspace):
    (cold_workspace / "catalog.py").write_text("class Catalog:\n    def locate(self): return 1\n")
    gateway = OperationGateway(str(cold_workspace), "daily", watch=False)
    try:
        data = await result(gateway, "search_symbols", {"name": "Catalog.locate", "kind": "method"})
        assert data["data"][0]["qualified_name"] == "Catalog.locate"
        assert data["data"][0]["file_path"] == "catalog.py"
    finally:
        await gateway.close()


def test_search_waits_for_inflight_definition_publication(cold_workspace, monkeypatch):
    (cold_workspace / "caller.py").unlink()
    (cold_workspace / "comments.py").unlink()
    ast = ast_service.ASTService(str(cold_workspace))
    ast.initialize_skeleton()
    entered, release, searched = threading.Event(), threading.Event(), threading.Event()
    original_index = ast._index_definitions
    original_search = ast._index.search_definitions

    def delayed_index(path, parsed):
        if path == "helper.py":
            entered.set()
            assert release.wait(3)
        original_index(path, parsed)

    def observed_search(index, *args, **kwargs):
        result = original_search(*args, **kwargs)
        searched.set()
        return result

    monkeypatch.setattr(ast, "_index_definitions", delayed_index)
    monkeypatch.setattr(type(ast._index), "search_definitions", observed_search)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            parse = pool.submit(ast.ensure_file_parsed, "helper.py")
            assert entered.wait(3)
            search = pool.submit(ast.search_symbol, "locate_value")
            searched.wait(0.1)
            release.set()
            assert parse.result(timeout=3)
            assert [(loc.file_path, loc.name) for loc, _ in search.result(timeout=3)] == [
                ("helper.py", "locate_value")]
    finally:
        release.set()
        ast._store.close()
