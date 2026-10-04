"""Broad-query ranking should expose ambiguity without losing implementation hits."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.output import bounded_compact
from attocode_intel.query_ranking import (
    hit_evidence,
    query_concepts,
    query_diagnostics,
    rerank_broad_candidates,
)
from attocode_intel.service import CodeIntelService


def _hit(path: str, name: str, text: str, score: float) -> SemanticSearchResult:
    return SemanticSearchResult(path, "function", name, text, score, 1, 8)


@pytest.fixture(autouse=True)
def enable_experimental_ranking(monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_BROAD_RERANK", "1")


def test_broad_ranker_is_off_by_default_but_file_page_is_diverse(monkeypatch):
    monkeypatch.delenv("ATTOCODE_INTEL_BROAD_RERANK")
    rows = [
        _hit("src/lifecycle.py", "GenerationCounter", "generation", 0.10),
        _hit("src/lifecycle.py", "GenerationGuardedFuture", "generation", 0.09),
        _hit("src/cache.py", "invalidate", "cache generation", 0.02),
        _hit("src/freshness.py", "refresh", "cache generation", 0.01),
    ]
    assert rerank_broad_candidates("cache generation", rows, 3) == [rows[0], rows[2], rows[3]]
    assert rerank_broad_candidates("cache generation", rows, 4) == rows
    assert rerank_broad_candidates("generation", rows, 3) == rows[:3]
    assert rerank_broad_candidates("cache generation", rows, 3, "src/lifecycle.py") == rows[:3]


def test_concept_evidence_promotes_full_match_and_diversifies_files():
    rows = [
        _hit("src/attocode/integrations/lifecycle.py", "GenerationGuardedFuture",
             "generation generation generation", 0.10),
        _hit("src/attocode/integrations/lifecycle.py", "GenerationCounter",
             "generation generation", 0.09),
        _hit("legacy/src/providers/openrouter.py", "chat_with_tools",
             "cache generation", 0.05),
        _hit("packages/code-intel/src/attocode_intel/semantic_search.py", "invalidate_file",
             "cache generation", 0.02),
    ]
    ranked = rerank_broad_candidates("cache generation", rows, top_k=4)
    assert [row.name for row in ranked[:3]] == [
        "invalidate_file", "GenerationGuardedFuture", "chat_with_tools",
    ]
    assert [row.score for row in ranked] == sorted((row.score for row in ranked), reverse=True)
    assert [row.name for row in rerank_broad_candidates("generation", rows, 4)] == [
        row.name for row in rows
    ]
    assert query_concepts("where is cache generation handled without swarm") == (
        "cache", "generation",
    )
    assert hit_evidence("cache generation", ranked[0]) == {
        "matched_terms": ["cache", "generation"], "match_fields": ["source_body"],
    }


def test_scoped_query_does_not_claim_cross_component_ambiguity():
    rows = [
        _hit("legacy/src/providers/openrouter.py", "chat_with_tools", "cache generation", 0.05),
        _hit("packages/code-intel/src/attocode_intel/semantic_search.py", "invalidate_file",
             "cache generation", 0.02),
    ]
    broad = query_diagnostics("cache generation", rows)
    assert broad["ambiguous"] is True
    assert broad["matching_components"] == ["legacy/src/providers", "packages/code-intel"]
    scoped = query_diagnostics("cache generation", rows, "packages/code-intel/src/*")
    assert scoped["ambiguous"] is False
    assert scoped["scope"] == "packages/code-intel/src/*"


def test_explicit_exclusion_is_not_reversed_by_full_match_bonus():
    rows = [
        _hit("src/attoswarm/core/hybrid_coordinator.py", "_bootstrap_manifest",
             "bootstrap budget", 0.15),
        _hit("packages/code-intel/src/attocode_intel/service.py", "bootstrap",
             "bootstrap budget", 0.11),
    ]
    negative = {"swarm"}
    penalized = SemanticSearchManager._penalize_exclusions(rows, negative)
    ranked = rerank_broad_candidates("bootstrap budget without swarm", penalized, 2)
    assert ranked[0].file_path == "packages/code-intel/src/attocode_intel/service.py"
    assert ranked[1].score == penalized[1].score
    assert query_diagnostics("bootstrap budget without swarm", ranked)["ambiguous"] is False


def test_long_queries_and_archive_matches_keep_previous_order():
    long_rows = [
        _hit("src/budget.py", "BudgetStatus", "token budget enforcement", 0.09),
        _hit("docs/notes.md", "notes", "token budget management enforcement", 0.06),
    ]
    assert rerank_broad_candidates("token budget management enforcement", long_rows, 2) == long_rows

    short_rows = [
        _hit("src/lifecycle.py", "GenerationCounter", "generation counter", 0.10),
        _hit("legacy/src/openrouter.ts", "chatWithTools", "cache generation", 0.08),
        _hit("packages/code-intel/src/search.py", "invalidate_file", "cache generation", 0.03),
    ]
    ranked = rerank_broad_candidates("cache generation", short_rows, 3)
    assert ranked[0].file_path == "packages/code-intel/src/search.py"
    assert ranked[1].file_path == "src/lifecycle.py"
    assert ranked[2].file_path == "legacy/src/openrouter.ts"

    docs_rows = [
        _hit("fastapi/routing.py", "route", "websocket routing", 0.10),
        _hit("docs_src/websockets/tutorial.py", "tutorial", "websocket connection", 0.08),
    ]
    assert rerank_broad_candidates("websocket connection", docs_rows, 2) == docs_rows


def test_complete_match_stays_with_best_implementation_component():
    rows = [
        _hit("crates/globset/src/glob.rs", "Glob", "glob pattern", 0.10),
        _hit("crates/cli/src/decompress.rs", "decompress", "glob matching", 0.09),
        _hit("crates/globset/src/lib.rs", "GlobSet", "glob matching", 0.07),
    ]
    ranked = rerank_broad_candidates("glob matching", rows, 3)
    assert [row.file_path for row in ranked] == [
        "crates/globset/src/lib.rs",
        "crates/globset/src/glob.rs",
        "crates/cli/src/decompress.rs",
    ]


def test_structured_search_exposes_match_evidence_and_ambiguity(tmp_path):
    rows = [
        _hit("legacy/src/providers/openrouter.py", "chat_with_tools", "cache generation", 0.15),
        _hit("packages/code-intel/src/attocode_intel/semantic_search.py", "invalidate_file",
             "cache generation", 0.12),
    ]
    service = CodeIntelService(str(tmp_path))
    service._get_semantic_search = lambda: SimpleNamespace(
        search=lambda *_args, **_kwargs: rows,
        candidate_diagnostics=lambda: {"status": "ready"},
    )
    result = service.semantic_search_data("cache generation", top_k=2)
    assert result["ranking"]["query"]["ambiguous"] is True
    assert result["results"][1]["matched_terms"] == ["cache", "generation"]
    assert result["results"][1]["match_fields"] == ["source_body"]

    scoped = service.semantic_search_data(
        "cache generation", top_k=2, file_filter="packages/code-intel/*",
    )
    assert scoped["ranking"]["query"]["ambiguous"] is False


def test_compact_budget_keeps_each_delivered_match_explanation_complete():
    hits = [
        {"file_path": f"src/hit_{i}.py", "snippet": "source " * 35,
         "matched_terms": ["cache", "generation"],
         "match_fields": ["identity", "source_body"]}
        for i in range(8)
    ]
    result = bounded_compact(
        {"workspace": "/repo", "source": "local", "revision": "working-tree"},
        {"results": hits}, 320,
    )
    delivered = json.loads(result.content[0].text)["data"]["results"]
    assert delivered and len(delivered) < len(hits)
    assert all(hit["matched_terms"] == ["cache", "generation"] for hit in delivered)
    assert all(hit["match_fields"] == ["identity", "source_body"] for hit in delivered)


def test_real_source_index_keeps_multiple_interpretations_visible(tmp_path):
    lifecycle = tmp_path / "src" / "attocode" / "integrations" / "lifecycle.py"
    provider = tmp_path / "legacy" / "src" / "providers" / "openrouter.py"
    implementation = tmp_path / "packages" / "code-intel" / "src" / "semantic_search.py"
    for path in (lifecycle, provider, implementation):
        path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle.write_text(
        "class GenerationGuardedFuture:\n"
        "    def wait(self):\n"
        "        generation = generation_counter\n"
        "        return generation\n", encoding="utf-8",
    )
    provider.write_text(
        "def chat_with_tools():\n"
        "    cache = prompt_cache\n"
        "    generation = completion_id\n"
        "    return cache, generation\n", encoding="utf-8",
    )
    implementation.write_text(
        "def invalidate_file(path):\n"
        "    cache = source_cache\n"
        "    generation = body_generation + 1\n"
        "    return cache, generation\n", encoding="utf-8",
    )

    mgr = SemanticSearchManager(str(tmp_path))
    mgr.search_candidates("cache generation", top_k=5)
    assert mgr.wait_for_body_index(timeout=5)
    results = mgr.search_candidates("cache generation", top_k=5)
    assert {row.file_path for row in results[:3]} >= {
        "legacy/src/providers/openrouter.py",
        "packages/code-intel/src/semantic_search.py",
    }
    assert any("lifecycle.py" in row.file_path for row in results)
    assert query_diagnostics("cache generation", results)["ambiguous"] is True
    assert "matches: cache, generation" in mgr.format_results(results, query="cache generation")

    scoped = mgr.search_candidates("cache generation", top_k=5,
                                   file_filter="packages/code-intel/src/*")
    assert scoped and all(row.file_path == "packages/code-intel/src/semantic_search.py"
                          for row in scoped)


def test_equal_lexical_scores_have_stable_file_order_across_cold_builds(tmp_path):
    orders = []
    for root_name, creation_order in (
        ("first", ("beta.py", "alpha.py")),
        ("second", ("alpha.py", "beta.py")),
    ):
        root = tmp_path / root_name
        root.mkdir()
        for name in creation_order:
            (root / name).write_text('def needle():\n    return "needle"\n', encoding="utf-8")
        mgr = SemanticSearchManager(str(root))
        mgr.search_candidates("needle", top_k=8)
        assert mgr.wait_for_body_index(timeout=5)
        orders.append(list(dict.fromkeys(row.file_path for row in mgr.search_candidates(
            "needle", top_k=8,
        ))))
    assert orders[0] == orders[1]
    assert orders[0][:2] == ["alpha.py", "beta.py"]
