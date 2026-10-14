"""Search previews must expose evidence, not just a chunk's boilerplate."""

import json
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import bounded_compact, compact_result, response_tokens
from attocode_intel.query_ranking import hit_evidence
from attocode_intel.search_evidence import search_snippet, snippet_window, source_body
from attocode_intel.service import CodeIntelService


def source_hit(body, start=41):
    end = start + len(body.splitlines()) - 1
    return SemanticSearchResult("src/Upload.java", "method", "cleanupUpload",
                                f"src/Upload.java:{start}-{end}\n{body}", 0.5, start, end)


def test_plain_search_shows_late_match_instead_of_header():
    body = "/*\n" + " * Copyright and license boilerplate.\n" * 12 + " */\nvoid cleanupUpload() {}\n"
    hit = SemanticSearchResult(
        "src/Upload.java", "file", "Upload", "src/Upload.java:1-15\n" + body,
        0.5, 1, 15,
    )
    text = SemanticSearchManager.format_results(None, [hit], query="cleanup upload")
    preview = text.split("\n     ")[-1]
    assert "cleanupUpload" in preview


def test_snippet_is_contiguous_with_real_offsets_and_chunk_identity_unchanged():
    body = "/*\n" + " * Copyright and license boilerplate.\n" * 12 + " */\nvoid cleanupUpload() {}\n"
    hit = source_hit(body)
    result = search_snippet(hit, "cleanup upload", 80)
    assert result["snippet"] == " */\nvoid cleanupUpload() {}\n"
    assert (result["snippet_start_line"], result["snippet_end_line"]) == (54, 55)
    assert result["snippet_truncated"]
    assert (hit.start_line, hit.end_line) == (41, 55)
    assert hit.score == 0.5


def test_ties_use_earliest_line_and_exclusions_do_not_win():
    body = "cache cache cache\ncleanupUpload();\n" + "padding();\n" * 10 + "cleanupUpload();\n"
    result = search_snippet(source_hit(body), "cleanup upload without cache", 24)
    assert result["snippet"] == "cleanupUpload();\n"
    assert result["snippet_start_line"] == 42


@pytest.mark.parametrize("query", ["", "unfindable"])
def test_zero_overlap_keeps_prefix(query):
    body = "first line\nsecond line\n"
    result = search_snippet(source_hit(body), query, 15)
    assert result["snippet"] == body[:15]
    assert (result["snippet_start_line"], result["snippet_end_line"]) == (41, 42)
    assert result["snippet_truncated"]


def test_metadata_has_no_invented_source_coordinates():
    hit = SemanticSearchResult("src/Upload.java", "class", "Upload", "class Upload", 0.5)
    result = search_snippet(hit, "upload", 320)
    assert result == {"snippet": "class Upload", "snippet_truncated": False,
                      "snippet_start_line": None, "snippet_end_line": None}


def test_real_first_line_is_not_mistaken_for_an_index_header():
    hit = source_hit("cleanupUpload();\nnext();\n")
    hit.text = "cleanupUpload();\nnext();\n"
    assert source_body(hit) == hit.text
    assert search_snippet(hit, "cleanup upload", 40)["snippet"].startswith("cleanupUpload")
    assert hit_evidence("cleanup", hit)["matched_terms"] == ["cleanup"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_source_line_ranges_survive_line_endings(newline):
    body = newline.join(["padding;" * 10, "cleanupUpload();", "padding;" * 10])
    result = search_snippet(source_hit(body), "cleanup upload", 24)
    assert (result["snippet_start_line"], result["snippet_end_line"]) == (42, 42)
    assert "cleanupUpload" in result["snippet"]


def test_long_single_line_retains_match_and_marks_partial_source():
    body = "padding " * 100 + "cleanupUpload(); " + "padding " * 100
    result = search_snippet(source_hit(body), "cleanup upload", 64)
    assert "cleanupUpload" in result["snippet"]
    assert result["snippet"] in body
    assert len(result["snippet"]) <= 64
    assert (result["snippet_start_line"], result["snippet_end_line"]) == (41, 41)
    assert result["snippet_truncated"]


def test_empty_body_has_no_source_range():
    assert snippet_window("", "cleanup", 40, 41) == {
        "snippet": "", "snippet_start_line": None, "snippet_end_line": None,
        "snippet_truncated": False,
    }


def test_final_budget_shortening_updates_coordinates_and_flag():
    # One hit cannot be removed before its oversized snippet is shortened.
    body = "license " * 80 + "\ncleanupUpload();\n" + "following " * 80
    hit = {"file_path": "src/Upload.java", "name": "cleanupUpload", "chunk_type": "method",
           **search_snippet(source_hit(body), "cleanup upload", 2000)}
    result = bounded_compact({"workspace": "/repo", "truncated": False},
                             {"query": "cleanup upload", "results": [hit],
                              "ranking": {"candidate_pool_count": 1, "delivered_count": 1}}, 180)
    data = json.loads(result.content[0].text)
    assert response_tokens(result) <= 180
    actual = data["data"]["results"][0]
    assert actual["snippet_truncated"]
    assert "cleanupUpload" in actual["snippet"]
    assert actual["snippet_start_line"] == actual["snippet_end_line"] == 42
    assert data["metadata"]["truncated"]
    assert actual["name"] == "cleanupUpload"


@pytest.mark.asyncio
async def test_gateway_preserves_fixed_pool_order_identity_and_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    (tmp_path / "main.py").write_text("def main(): pass\n")
    body = "/*\n" + " * Copyright and license boilerplate.\n" * 12 + " */\nvoid cleanupUpload() {}\n"
    rows = [source_hit(body) for _ in range(10)]
    for index, row in enumerate(rows):
        row.file_path = f"src/worker_{index}/Upload.java"
        row.text = f"{row.file_path}:{row.start_line}-{row.end_line}\n{body}"
        row.score = 0.9 - index / 100
    manager = SimpleNamespace(
        warm=lambda: None, search=lambda *args, **kwargs: rows,
        candidate_diagnostics=lambda: {"status": "ready"},
        format_results=lambda results, query: SemanticSearchManager.format_results(None, results, query),
    )
    monkeypatch.setattr(CodeIntelService, "_get_semantic_search", lambda self: manager)
    monkeypatch.setattr(CodeIntelService, "_search_after_warmup", lambda self, mgr, search: search())
    gateway = OperationGateway(str(tmp_path), "lean", watch=False)
    try:
        for budget in (4000, 1000, 600):
            response = await gateway.execute_mcp("semantic_search", {
                "query": "cleanup upload", "top_k": 10, "max_tokens": budget,
            })
            assert not response.isError, response.content
            assert response_tokens(response) <= budget
            data = json.loads(response.content[0].text)["data"]
            hits = data["results"]
            assert [h["file_path"] for h in hits] == [r.file_path for r in rows[:len(hits)]]
            assert [h["score"] for h in hits] == [r.score for r in rows[:len(hits)]]
            for hit in hits:
                assert hit["name"] == "cleanupUpload" and hit["chunk_type"] == "method"
                assert "cleanupUpload" in hit["snippet"]
                assert hit["line"] == 41 and hit["end_line"] == 55
                assert hit["snippet_start_line"] >= 54 and hit["snippet_end_line"] == 55
                assert hit["snippet_truncated"]
            assert data["ranking"]["delivered_count"] == len(hits)
            if budget == 4000:
                assert len(hits) == 10
                # Exact old hit fields/prefix rule on the same ten candidates.
                # At this budget neither response needs trimming.
                payload = json.loads(response.content[0].text)
                legacy_hits = [{
                    "file_path": row.file_path, "score": row.score,
                    "snippet": body[:320], "snippet_truncated": len(body) > 320,
                    "line": row.start_line, "end_line": row.end_line,
                    **hit_evidence("cleanup upload", row),
                } for row in rows]
                legacy = compact_result(payload["metadata"], {**data, "results": legacy_hits})
                assert response_tokens(legacy) <= 4000
                assert len(legacy_hits) == len(hits)
                assert all("cleanupUpload" not in h["snippet"] for h in legacy_hits)
            else:
                assert data["ranking"]["omitted_results_due_to_budget"] == 10 - len(hits)
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_real_body_index_shows_late_match_with_exact_source_range(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_PROVIDER", "off")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    text = 'def work():\n    """\n' + "    license boilerplate\n" * 20 + '    """\n    cleanup_upload()\n'
    (tmp_path / "worker.py").write_text(text)
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        response = await gateway.execute_mcp("semantic_search", {
            "query": "cleanup upload", "top_k": 1, "file_filter": "worker.py", "max_tokens": 2000,
        })
        assert not response.isError, response.content
        data = json.loads(response.content[0].text)["data"]
        hit = data["results"][0]
        assert hit["file_path"] == "worker.py" and hit["name"] == "work"
        assert hit["snippet"] in text and "cleanup_upload()" in hit["snippet"]
        assert hit["snippet_start_line"] == 23 and hit["snippet_end_line"] == 24
        assert hit["line"] == 1 and hit["end_line"] == 24
        assert hit["snippet_truncated"]
        assert response_tokens(response) <= 2000
    finally:
        await gateway.close()


def test_metadata_hydration_is_exact_bounded_and_does_not_mutate_ranking(tmp_path):
    from attocode_intel.search_evidence import hydrate_selected_sources
    source = "class Owner:\n    def close(self):\n        release_handle()\n\nclass Other:\n    def close(self):\n        wrong_handle()\n"
    (tmp_path / "worker.py").write_text(source)
    hit = SemanticSearchResult("worker.py", "method", "Owner.close", "close metadata", .25)
    other = SemanticSearchResult("worker.py", "method", "Missing.close", "unknown", .5)
    file = SemanticSearchResult("worker.py", "file", "worker.py", "names", .1)
    enriched = hydrate_selected_sources(str(tmp_path), [hit, other, file])
    assert [(h.file_path, h.name, h.score) for h in enriched] == [(h.file_path, h.name, h.score) for h in [hit, other, file]]
    assert hit.start_line == 0 and hit.text == "close metadata"
    assert enriched[0].start_line == 2 and enriched[0].end_line == 3
    assert "release_handle" in enriched[0].text and "wrong_handle" not in enriched[0].text
    assert enriched[1] is other
    assert enriched[2].text == source
    (tmp_path / "worker.py").write_text(source.replace("release_handle", "changed_handle"))
    assert "changed_handle" in hydrate_selected_sources(str(tmp_path), [hit])[0].text
    (tmp_path / "worker.py").unlink()
    assert hydrate_selected_sources(str(tmp_path), [hit])[0] is hit


def test_metadata_hydration_refuses_ambiguous_oversized_and_escaping_source(tmp_path):
    from attocode_intel.search_evidence import hydrate_selected_sources
    (tmp_path / "duplicate.py").write_text("def close(): pass\ndef close(): pass\n")
    (tmp_path / "large.py").write_bytes(b"x" * 1_000_001)
    hits = [SemanticSearchResult(path, kind, name, "metadata", .1) for path, kind, name in [
        ("duplicate.py", "function", "close"), ("large.py", "file", "large.py"),
        ("../outside.py", "file", "outside.py")]]
    assert all(a is b for a, b in zip(hits, hydrate_selected_sources(str(tmp_path), hits), strict=True))
