import json

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import bounded_compact, response_tokens


def decode(result):
    assert not result.isError
    assert result.structuredContent is None
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "helper.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "caller.py").write_text("from helper import helper\ndef caller():\n    return helper()\n")
    (tmp_path / "test_helper.py").write_text("from helper import helper\ndef test_helper():\n    assert helper() == 1\n")
    return tmp_path


async def test_inspection_bundles_source_and_evidence(repository):
    gateway = OperationGateway(str(repository), "daily", watch=False)
    try:
        result = await gateway.execute_mcp("inspect_symbol", {"symbol_name": "helper"})
        data = decode(result)["data"]
        assert response_tokens(result) <= 2000
        assert data["definition"]["file_path"] == "helper.py"
        assert "return 1" in data["source"]["text"]
        assert any(r["file_path"] == "caller.py" for r in data["references"])
        assert any(r["file_path"] == "test_helper.py" for r in data["tests"])
        assert data["follow_up"]["references"]["file_path"] == "helper.py"
        assert not data["absence_proven"]
        legacy = await gateway.execute("inspect_symbol", {"symbol_name": "helper"})
        assert legacy.structuredContent["data"]["definition"] == data["definition"]
        (repository / "helper.py").write_text("\n\ndef helper():\n    return 99\n")
        changed = decode(await gateway.execute_mcp("inspect_symbol", {"symbol_name": "helper"}))["data"]
        assert changed["source"]["start_line"] == 3
        assert "return 99" in changed["source"]["text"]
    finally:
        await gateway.close()


async def test_ambiguous_selection_keeps_reference_uncertainty(repository, monkeypatch):
    (repository / "other.py").write_text("def helper(): return 2\n")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "auto")
    gateway = OperationGateway(str(repository), "daily", watch=False)
    try:
        result = decode(await gateway.execute_mcp("inspect_symbol", {"symbol_name": "helper"}))
        assert result["data"]["status"] == "ambiguous"
        assert result["metadata"]["precision"] == "ambiguous"
        assert "source" not in result["data"]
        selected = decode(await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "helper", "file_path": "helper.py", "line": 1}))["data"]
        assert selected["definition"]["file_path"] == "helper.py"
        assert selected["ambiguous"]
        assert "reference_candidates" in selected["reference_caveat"]
        assert decode(await gateway.execute_mcp("inspect_symbol", {"symbol_name": "unknown"}))["data"]["status"] == "not_found"
        with pytest.raises(ValueError, match="inside"):
            await gateway.execute_mcp("inspect_symbol", {"symbol_name": "helper", "file_path": "../elsewhere.py"})
    finally:
        await gateway.close()


async def test_long_definition_source_pages_keep_every_line_under_budget(repository):
    lines = ["def accumulate(value):",
             *(f"    value += {i}  # maintain the running total for step {i}" for i in range(130)),
             "    return value"]
    (repository / "large.py").write_text("\n".join(lines) + "\n")
    gateway = OperationGateway(str(repository), "daily", watch=False)
    try:
        args = {"symbol_name": "accumulate", "max_tokens": 800}
        received = []
        for _ in range(150):
            result = await gateway.execute_mcp("inspect_symbol", args)
            assert response_tokens(result) <= 800
            data = decode(result)["data"]
            source = data["source"]
            assert source["start_line"] == len(received) + 1
            page = source["text"].splitlines()
            assert page and source["end_line"] == source["start_line"] + len(page) - 1
            if not received:
                assert len(page) < 60  # Exercise additional trimming by the serialized response budget.
            received.extend(page)
            next_source = data["follow_up"]["next_source"]
            if next_source is None:
                break
            assert next_source["line"] == 1
            assert next_source["source_start_line"] == len(received) + 1
            args = {key: value for key, value in next_source.items() if key != "tool"}
            args["max_tokens"] = 800
        assert received == lines
        with pytest.raises(ValueError, match="inside the selected definition"):
            await gateway.execute_mcp("inspect_symbol", {"symbol_name": "accumulate", "source_start_line": len(lines) + 1})
    finally:
        await gateway.close()


async def test_paginated_references_have_no_gaps_under_a_small_budget(repository):
    (repository / "many.py").write_text("from helper import helper\n" + "helper()\n" * 100)
    gateway = OperationGateway(str(repository), "daily", watch=False)
    try:
        expected = (await gateway.execute("cross_references", {"symbol_name": "helper"})).structuredContent["data"]["references"]
        rows, cursor = [], None
        for _ in range(120):
            args = {"symbol_name": "helper", "max_tokens": 650, "page_size": 100}
            if cursor:
                args["cursor"] = cursor
            result = await gateway.execute_mcp("cross_references", args)
            assert response_tokens(result) <= 650
            data = decode(result)["data"]
            rows.extend(data["references"])
            cursor = data["next_cursor"]
            if not cursor:
                break
        assert not cursor
        assert rows == expected
    finally:
        await gateway.close()


async def test_cursor_rejects_other_queries_workspaces_and_edits(repository, tmp_path):
    other = tmp_path / "second"
    other.mkdir()
    (other / "helper.py").write_text("def helper(): return 0\nhelper()\nhelper()\n")
    gateway = OperationGateway(str(repository), "daily", watch=False)
    try:
        args = {"symbol_name": "helper", "page_size": 1}
        first = decode(await gateway.execute_mcp("cross_references", args))["data"]
        assert first["next_cursor"]
        continuation = {**args, "cursor": first["next_cursor"]}
        with pytest.raises(ValueError, match="cursor"):
            await gateway.execute_mcp("cross_references", {**continuation, "symbol_name": "caller"})
        with pytest.raises(ValueError, match="cursor"):
            await gateway.execute_mcp("cross_references", {**continuation, "workspace": str(other)})
        (repository / "caller.py").write_text("from helper import helper\n\nhelper()\n")
        with pytest.raises(ValueError, match="cursor"):
            await gateway.execute_mcp("cross_references", continuation)
    finally:
        await gateway.close()


@pytest.mark.parametrize("budget", [400, 1000, 2000])
def test_complete_budget_unicode_and_provenance(budget):
    result = bounded_compact({"source": "local", "workspace": "/repo", "revision": "working-tree",
                              "analysis": {"status": "partial", "absence_proven": False}},
                             {"references": [{"file_path": "日本語.py", "line": i, "source": "syntax"}
                                              for i in range(500)], "ambiguous": True}, budget)
    assert response_tokens(result) <= budget
    decoded = decode(result)
    assert decoded["metadata"]["workspace"] == "/repo"
    assert not decoded["metadata"]["absence_proven"]
    assert decoded["metadata"]["truncated"]
    assert decoded["data"]["ambiguous"]


def test_tiny_budget_rejected_without_silent_provenance_loss():
    with pytest.raises(ValueError, match="provenance"):
        bounded_compact({"workspace": "/repo", "source": "local", "revision": "working-tree"}, [], 1)


async def test_single_computation_full_compatibility_and_private_timings(repository, monkeypatch, tmp_path):
    from attocode_intel.service import CodeIntelService
    original = CodeIntelService.search_symbols_data
    calls = []

    def counted(self, name, limit=30, kind=""):
        calls.append(name)
        return original(self, name, limit, kind)

    monkeypatch.setattr(CodeIntelService, "search_symbols_data", counted)
    trace = tmp_path / "timings.jsonl"
    monkeypatch.setenv("ATTOCODE_INTEL_TRACE", str(trace))
    gateway = OperationGateway(str(repository), "full", watch=False)
    try:
        result = await gateway.execute_mcp("search_symbols", {"name": "helper"})
        assert result.structuredContent["data"]
        assert result.structuredContent["result"] == result.content[0].text
        assert calls == ["helper"]
        event = json.loads(trace.read_text())
        assert {"freshness", "execution", "queue", "validation"} <= event["timings_ms"].keys()
        assert event["response_tokens"] == response_tokens(result)
        assert str(repository) not in trace.read_text()
        assert trace.stat().st_mode & 0o077 == 0
        catalog = gateway.catalog()
        catalog[0].inputSchema.clear()
        assert gateway.catalog()[0].inputSchema
    finally:
        await gateway.close()


async def test_compact_cross_repo_and_knowledge(repository):
    gateway = OperationGateway(str(repository), "daily", watch=False)
    try:
        with pytest.raises(ValueError, match="acknowledged"):
            await gateway.execute_mcp("record_learning", {
                "type": "gotcha", "description": "must not be saved", "max_tokens": 1})
        assert decode(await gateway.execute_mcp("list_learnings", {}))["data"] == []
        saved = decode(await gateway.execute_mcp("record_learning", {
            "type": "gotcha", "description": "helper returns one", "scope": "helper.py"}))
        assert saved["data"]["id"]
        recalled = decode(await gateway.execute_mcp("recall", {"query": "helper"}))
        assert recalled["data"][0]["description"] == "helper returns one"
        result = await gateway.execute_mcp("cross_repo_search", {"query": "helper", "workspaces": [str(repository)]})
        assert response_tokens(result) <= 2000
        assert all(row["workspace"] == str(repository) for row in decode(result)["data"])
    finally:
        await gateway.close()
