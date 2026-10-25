"""Budget fitting must preserve a prefix without throwing away rows that fit."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import bounded_compact, compact_result, response_tokens
from attocode_intel.service import CodeIntelService


def fixture():
    rows = [{"file_path": f"src/worker_{i}.py", "name": "accept", "score": 1-i/100,
             "line": 1, "end_line": 1, "snippet": "return accepted", "snippet_start_line": 1,
             "snippet_end_line": 1, "snippet_truncated": False,
             "matched_terms": ["accept"], "match_fields": ["source"]} for i in range(24)]
    return {"workspace": "/repo", "truncated": False}, {
        "query": "accept", "results": rows,
        "ranking": {"candidate_pool_count": 24, "returned_count": 24, "delivered_count": 24}}


def test_budget_fills_prefix_instead_of_halving_with_spare_room():
    metadata, data = fixture()
    response = bounded_compact(metadata, data, 1500)
    payload = json.loads(response.content[0].text)
    actual = payload["data"]["results"]
    assert response_tokens(response) <= 1500
    assert actual == data["results"][:len(actual)]
    probe = deepcopy(payload)
    probe["data"]["results"].append(data["results"][len(actual)])
    probe["data"]["ranking"].update(delivered_count=len(actual)+1,
                                     omitted_results_due_to_budget=23-len(actual))
    probe["metadata"]["ranking"] = deepcopy(probe["data"]["ranking"])
    probe["metadata"].setdefault("omitted", {})["data.results"] = 23-len(actual)
    assert response_tokens(compact_result(probe["metadata"], probe["data"])) > 1500
    assert payload["data"]["ranking"]["omitted_results_due_to_budget"] == 24-len(actual)


def test_budget_does_not_mutate_callers_rows():
    metadata, data = fixture()
    before = deepcopy((metadata, data))
    bounded_compact(metadata, data, 1500)
    assert (metadata, data) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("long_paths,budget", [(False, 2000), (False, 2500), (True, 4000), (True, 32000)])
async def test_gateway_keeps_candidates_until_final_fit_and_offers_progress(tmp_path, monkeypatch, long_paths, budget):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("pass\n")
    prefix = "very_long_unicode_é_path/" * (300 if budget == 32000 else 30) if long_paths else ""
    rows = [SemanticSearchResult(f"{prefix}a{i}.py", "file", "a", "accept", .5, 1, 1) for i in range(24)]
    manager = SimpleNamespace(search=lambda *a, **kw: rows, warm=lambda: None,
                              candidate_diagnostics=lambda: {"status": "ready"},
                              format_results=lambda results, query: SemanticSearchManager.format_results(None, results, query))
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: search())
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        response = await gateway.execute_mcp("semantic_search", {"query": "accept", "top_k": 24, "max_tokens": budget})
        assert not response.isError, response.content
        assert response_tokens(response) <= budget
        payload = json.loads(response.content[0].text)
        data = payload["data"]
        assert [r["file_path"] for r in data["results"]] == [r.file_path for r in rows[:len(data["results"])]]
        if not long_paths:
            assert len(data["results"]) > budget // 120
        if budget == 2500:
            assert len(data["results"]) == 24
            assert not payload["metadata"]["truncated"]
        if len(data["results"]) < 24:
            assert data["ranking"]["omitted_results_due_to_budget"] == 24-len(data["results"])
            follow = data["follow_up"]["arguments"]
            assert follow["top_k"] == 48 and follow["query"] == "accept"
            assert data["follow_up"]["reason"] == "search_deeper"
            assert "revision" not in follow
            if budget == 32000:
                assert follow["max_tokens"] == budget
            else:
                assert follow["max_tokens"] > budget
    finally:
        await gateway.close()


@pytest.mark.parametrize("path_size,budget", [(300, 650), (600, 600)])
@pytest.mark.parametrize("deeper", [False, True])
@pytest.mark.parametrize("long_snippet", [False, True])
def test_new_follow_up_never_crowds_out_previously_delivered_evidence(path_size, budget, deeper, long_snippet):
    import random
    import string

    from attocode_intel.output import bounded_search

    metadata, data = fixture()
    data["results"] = data["results"][:5]
    data["ranking"].update(candidate_pool_count=5, returned_count=5, delivered_count=5)
    rng = random.Random(17)
    for row in data["results"]:
        row["file_path"] = "".join(rng.choices(string.ascii_letters, k=path_size)) + "/a.py"
        row["snippet"] = "accept detail" * (40 if long_snippet else 1)
    before = bounded_compact(metadata, data, budget, search_results=[])
    protected = json.loads(before.content[0].text)["data"]["results"]
    assert protected
    follow = {"tool": "semantic_search", "arguments": {
        "query": "accept", "top_k": 5, "mode": "auto", "workspace": "/repo", "max_tokens": 2000},
        "reruns_current_index": True}
    if deeper:
        follow["reason"] = "search_deeper"
        follow["arguments"]["top_k"] = 10
    result = bounded_search(metadata, data, budget, all_results=data["results"], follow_up=follow)
    assert response_tokens(result) <= budget
    actual = json.loads(result.content[0].text)["data"]["results"]
    assert len(actual) >= len(protected)
    preview_fields = {"snippet", "snippet_start_line", "snippet_end_line", "snippet_truncated"}
    for before, after in zip(protected, actual, strict=False):
        assert {k: v for k, v in before.items() if k not in preview_fields} == {
            k: v for k, v in after.items() if k not in preview_fields}
        assert before["snippet"] in after["snippet"]
        if before["snippet_start_line"] is not None:
            assert after["snippet_start_line"] <= before["snippet_start_line"]
            assert after["snippet_end_line"] >= before["snippet_end_line"]
        else:
            assert after["snippet_start_line"] is after["snippet_end_line"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("top_k,budget,long_paths", [(5, 2000, False), (24, 4000, True)])
async def test_remote_search_follow_up_keeps_resolved_revision(tmp_path, monkeypatch, top_k, budget, long_paths):
    from attocode_intel.remote import remote_profile
    from attocode_intel.request_context import RequestContext

    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("pass\n")
    prefix = "very_long_unicode_é_path/" * 30 if long_paths else ""
    rows = [SemanticSearchResult(f"{prefix}a{i}.py", "file", "a", "accept", .5, 1, 1) for i in range(24)]
    manager = SimpleNamespace(search=lambda *a, **kw: rows, warm=lambda: None,
                              candidate_diagnostics=lambda: {"status": "ready"},
                              format_results=lambda results, query: SemanticSearchManager.format_results(None, results, query))
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: search())
    resolved = []

    async def resolver(workspace, revision, operation):
        resolved.append((workspace, revision, operation))
        return RequestContext(str(tmp_path), workspace, revision="abc123", source="remote")

    gateway = OperationGateway(profile="daily", resolver=resolver, watch=False)
    profile_token = remote_profile.set("daily")
    try:
        result = await gateway.execute_mcp("semantic_search", {
            "workspace": "team-repository", "revision": "release-branch", "query": "accept",
            "top_k": top_k, "max_tokens": budget})
        assert not result.isError, result.content
        data = json.loads(result.content[0].text)["data"]
        follow = data["follow_up"]["arguments"]
        assert follow["revision"] == "abc123"
        await gateway.execute_mcp("semantic_search", follow)
        assert resolved[-1] == ("team-repository", "abc123", "semantic_search")
    finally:
        await gateway.close()
        remote_profile.reset(profile_token)


def test_unfittable_new_hint_keeps_a_usable_response():
    from attocode_intel.output import bounded_search

    metadata, data = fixture()
    before = bounded_compact(metadata, data, 1500, search_results=[])
    protected = json.loads(before.content[0].text)["data"]["results"]
    result = bounded_search(metadata, data, 1500, all_results=data["results"], follow_up={
        "tool": "semantic_search", "arguments": {
            "query": "accept", "workspace": "/" + "nested/" * 2000,
            "top_k": 24, "max_tokens": 4000}, "reruns_current_index": True})
    actual = json.loads(result.content[0].text)["data"]
    assert actual["results"][:len(protected)] == protected
    assert "follow_up" not in actual
    assert response_tokens(result) <= 1500


@pytest.mark.parametrize("upstream_truncated", [False, True])
def test_complete_recovery_reports_only_remaining_truncation(upstream_truncated):
    from attocode_intel.output import bounded_search

    metadata, data = fixture()
    metadata["truncated"] = upstream_truncated
    rows = deepcopy(data["results"])
    data["results"] = rows[:16]
    data["ranking"].update(delivered_count=16, omitted_results_due_to_budget=8)
    result = bounded_search(metadata, data, 2000, all_results=rows)
    payload = json.loads(result.content[0].text)
    assert len(payload["data"]["results"]) == 24
    assert payload["metadata"]["truncated"] is upstream_truncated
    assert not payload["data"]["ranking"].get("omitted_results_due_to_budget")
    assert not payload["metadata"].get("omitted")


def test_existing_oversized_hint_cannot_make_usable_page_fail():
    from attocode_intel.output import bounded_search

    metadata, data = fixture()
    rows = deepcopy(data["results"])
    data["results"] = rows[:16]
    data["ranking"].update(delivered_count=16, omitted_results_due_to_budget=8)
    hint = {"tool": "semantic_search", "arguments": {"workspace": "nested/" * 2000}}
    data["follow_up"] = hint
    result = bounded_search(metadata, data, 1500, all_results=rows, follow_up=hint)
    payload = json.loads(result.content[0].text)
    assert payload["data"]["results"]
    assert "follow_up" not in payload["data"]
    assert response_tokens(result) <= 1500


@pytest.mark.parametrize("budget", [500, 900, 1500, 2500])
@pytest.mark.parametrize("path_size", [0, 80, 300])
@pytest.mark.parametrize("long_snippet", [False, True])
def test_search_delivery_invariants_across_budget_boundaries(budget, path_size, long_snippet):
    from attocode_intel.output import bounded_search

    metadata, data = fixture()
    for row in data["results"]:
        row["file_path"] = "路径/" * path_size + row["file_path"]
        if long_snippet:
            row["snippet"] = "prefix\n" * 30 + "return accepted\n" + "suffix\n" * 30
            row["snippet_end_line"] = 61
            row["end_line"] = 61
    before = deepcopy((metadata, data))
    result = bounded_search(metadata, data, budget, all_results=data["results"])
    page = json.loads(result.content[0].text)
    rows = page["data"]["results"]
    assert response_tokens(result) <= budget
    assert [r["file_path"] for r in rows] == [r["file_path"] for r in data["results"][:len(rows)]]
    assert page["data"]["ranking"]["delivered_count"] == len(rows)
    assert page["data"]["ranking"].get("omitted_results_due_to_budget", 0) == 24 - len(rows)
    assert page["metadata"]["truncated"] == (len(rows) < 24 or any(r["snippet_truncated"] for r in rows))
    assert all(value != 0 for value in page["metadata"].get("omitted", {}).values())
    for row, original in zip(rows, data["results"], strict=False):
        assert row["snippet"] in original["snippet"]
        if row["snippet"]:
            assert 1 <= row["snippet_start_line"] <= row["snippet_end_line"] <= original["end_line"]
    assert (metadata, data) == before


def test_truncation_provenance_itself_is_included_in_budget():
    _, data = fixture()
    data["results"] = data["results"][:1]
    data["results"][0]["snippet_truncated"] = True
    data["ranking"].update(candidate_pool_count=1, returned_count=1, delivered_count=1)
    budget = response_tokens(compact_result({}, data))
    result = bounded_compact({}, data, budget)
    assert response_tokens(result) <= budget


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "keyword"])
async def test_saturated_search_offers_bounded_deeper_followup(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("pass\n")
    rows = [SemanticSearchResult(f"tests/a{i}.py", "file", "a", "accept", .5, 1, 1) for i in range(60)]
    manager = SimpleNamespace(search=lambda query, top_k, **kw: rows[:top_k], warm=lambda: None,
                              candidate_diagnostics=lambda: {"status": "ready"},
                              format_results=lambda results, query: SemanticSearchManager.format_results(None, results, query))
    manager.search_candidates = lambda query, top_k, file_filter: rows[:top_k]
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: search())
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        args = {"query": "accept tests", "top_k": 24, "max_tokens": 8000, "mode": mode}
        visited = []
        for expected in [24, 48, 50]:
            response = await gateway.execute_mcp("semantic_search", args)
            assert not response.isError
            page = json.loads(response.content[0].text)
            data = page["data"]
            assert len(data["results"]) == expected
            assert response_tokens(response) <= args["max_tokens"]
            visited.extend(r["file_path"] for r in data["results"])
            if expected < 50:
                assert data["follow_up"]["reason"] == "search_deeper"
                args = data["follow_up"]["arguments"]
                assert args["top_k"] > expected
                assert args["top_k"] <= 50
                assert args["mode"] == mode
            else:
                assert "follow_up" not in data
        assert "tests/a43.py" in visited
    finally:
        await gateway.close()


def test_deeper_hint_survives_complete_current_pool_without_changing_rows():
    from attocode_intel.output import bounded_search

    metadata, data = fixture()
    follow = {"tool": "semantic_search", "reason": "search_deeper",
              "arguments": {"query": "accept", "top_k": 48, "max_tokens": 8192},
              "reruns_current_index": True}
    result = bounded_search(metadata, data, 4000, all_results=data["results"], follow_up=follow)
    page = json.loads(result.content[0].text)
    assert page["data"]["results"] == data["results"]
    assert page["data"]["follow_up"] == follow
    assert not page["metadata"]["truncated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("count,budget,long_paths", [(17, 8000, False), (50, 32000, True)])
async def test_no_deeper_probe_for_unsaturated_pool_or_automatic_ceiling(
        tmp_path, monkeypatch, count, budget, long_paths):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("pass\n")
    prefix = "very_long_unicode_é_path/" * 300 if long_paths else ""
    rows = [SemanticSearchResult(f"{prefix}a{i}.py", "file", "a", "accept", .5, 1, 1) for i in range(count)]
    manager = SimpleNamespace(search=lambda *a, **kw: rows, warm=lambda: None,
                              candidate_diagnostics=lambda: {"status": "ready"},
                              format_results=lambda results, query: SemanticSearchManager.format_results(None, results, query))
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: search())
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        response = await gateway.execute_mcp("semantic_search", {
            "query": "accept", "top_k": max(24, count), "max_tokens": budget})
        assert not response.isError
        page = json.loads(response.content[0].text)
        assert page["data"]["results"]
        assert "follow_up" not in page["data"]
        assert response_tokens(response) <= budget
    finally:
        await gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_noncompact_search_retains_its_existing_budget_followup(tmp_path, monkeypatch, direct):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("pass\n")
    rows = [SemanticSearchResult(f"a{i}.py", "file", "a", "accept", .5, 1, 1) for i in range(24)]
    manager = SimpleNamespace(search=lambda *a, **kw: rows, warm=lambda: None,
                              candidate_diagnostics=lambda: {"status": "ready"},
                              format_results=lambda results, query: SemanticSearchManager.format_results(None, results, query))
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: search())
    gateway = OperationGateway(str(tmp_path), "full", watch=False)
    try:
        args = {"query": "accept", "top_k": 24, "max_tokens": 2000}
        response = (await gateway.execute("semantic_search", args, compact=False) if direct
                    else await gateway.execute_mcp("semantic_search", args))
        assert not response.isError
        data = response.structuredContent["data"]
        assert len(data["results"]) == 16
        assert data["ranking"]["omitted_results_due_to_budget"] == 8
        follow = data["follow_up"]
        assert follow["arguments"]["top_k"] == 24
        assert follow["arguments"]["max_tokens"] == 4352
        assert "reason" not in follow
        assert "More retrieved candidates" in response.content[0].text
    finally:
        await gateway.close()
