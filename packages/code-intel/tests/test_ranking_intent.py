"""Regression cases for explicit exclusions in navigation ranking."""

from types import SimpleNamespace

from attocode_intel._internal.integrations.context.reranker import LocalRerankOutcome
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    SemanticSearchResult,
)
from attocode_intel.focused_evidence import file_excerpt, task_terms, terms
from attocode_intel.query_ranking import demote_tests
from attocode_intel.repo_ranker import rank_repo_files
from attocode_intel.service import SEARCH_WARMUP_WAIT, CodeIntelService
from attocode_intel.test_ranking import rank_symbol_tests


def test_task_terms_treat_explicit_exclusion_as_soft_negative():
    positive, negative = task_terms(
        "improve bootstrap ranking without unrelated swarm modules"
    )
    assert {"bootstrap", "ranking"} <= positive
    assert "swarm" not in positive
    assert "swarm" in negative
    assert "unrelated" not in negative


def test_file_excerpt_ignores_excluded_terms():
    # Line 1 matches only the excluded term. Line 60 matches the task.
    lines = ["cache = {}"] + [f"x{n} = {n}" for n in range(58)] + ["def parse_header(): pass"]
    excerpt = file_excerpt(lines, "a.py", "parse header without cache")
    assert excerpt.startswith("File: a.py\n")
    assert "60: def parse_header(): pass" in excerpt
    assert "1: cache" not in excerpt


def test_test_candidates_with_excluded_words_rank_after_task_matches():
    paths = {"tests/test_bootstrap_ranking.py", "tests/test_swarm_ranking.py"}
    ast = SimpleNamespace(
        index=SimpleNamespace(file_symbols={path: [] for path in paths}),
        get_file_symbols=lambda _path: [],
    )
    suggestions = {path: {"priority": 3, "reasons": []} for path in paths}
    rows = rank_symbol_tests(
        ast, suggestions, ["src/bootstrap.py"], None,
        "improve bootstrap ranking without unrelated swarm modules", {},
    )
    assert [row["file_path"] for row in rows] == [
        "tests/test_bootstrap_ranking.py", "tests/test_swarm_ranking.py",
    ]


def test_source_relevance_can_outrank_path_only_repo_map():
    result = rank_repo_files(
        {"src/implementation.py": [], "src/hub.py": [],
         "src/a.py": ["src/hub.py"], "src/b.py": ["src/hub.py"]},
        task_context="ranking candidate generation",
        relevance_by_file={"src/implementation.py": 1.0},
    )
    assert result.entries[0].path == "src/implementation.py"


def test_symbol_task_context_breaks_equal_match_scores_without_hiding_definitions(tmp_path):
    svc = CodeIntelService(str(tmp_path))
    locations = [
        SimpleNamespace(kind="method", name="run", qualified_name="Swarm.run",
                        file_path="src/swarm.py", start_line=3, end_line=7),
        SimpleNamespace(kind="method", name="run", qualified_name="Search.run",
                        file_path="src/search.py", start_line=9, end_line=12),
    ]
    ast = SimpleNamespace(search_symbol=lambda *_args, **_kwargs: [(loc, 1.0) for loc in locations])
    svc._get_ast_service = lambda: ast
    svc._task_file_scores = lambda *_args, **_kwargs: {"src/search.py": 1.0}
    rows = svc.search_symbols_data("run", task_hint="search ranking")
    assert [row["file_path"] for row in rows] == ["src/search.py", "src/swarm.py"]


def test_model_cold_falls_back_without_source_hydration(tmp_path):
    svc = CodeIntelService(str(tmp_path))
    result = SimpleNamespace(file_path="src/search.py", chunk_type="function",
                             name="search", text="summary", score=1.0,
                             start_line=1, end_line=3)
    svc._local_reranker = SimpleNamespace(status="loading", is_available=False)
    svc._rerank_excerpt = lambda *_args: (_ for _ in ()).throw(AssertionError("hydrated while cold"))
    rows, ranking = svc._rank_search_results("search", [result], 1)
    assert rows == [result]
    assert ranking["fallback_reason"] == "loading"


def test_explicit_test_intent_preserves_strong_test_hit(tmp_path):
    svc = CodeIntelService(str(tmp_path))
    rows = [
        SemanticSearchResult("tests/test_bootstrap.py", "function", "test_bootstrap", "", 0.99),
        SemanticSearchResult("src/bootstrap.py", "function", "bootstrap", "", 0.10),
    ]
    ranked, _ = svc._rank_search_results("find the test for bootstrap", rows, 2)
    assert ranked == rows


def test_issue_search_puts_test_files_after_source_files():
    rows = [SemanticSearchResult(path, "function", "parse", "", 0.9 - rank / 10) for rank, path in enumerate(
        ("tests/test_parser.py", "src/parser.py", "src/test_helpers.py", "src/lexer.py"))]
    issue = ("The parser raises IndexError when a config file has nested brackets inside quoted strings. "
             "Steps: create settings with two levels, call load, and the stack trace points at the lexer. "
             "My test reproduces it with pytest.")
    assert len(terms(issue)) > 20  # a long issue says "test" about its reproduction
    assert [row.file_path for row in demote_tests(issue, rows)] == [
        "src/parser.py", "src/lexer.py", "tests/test_parser.py", "src/test_helpers.py"]
    assert demote_tests("parser tests", rows) == rows


def test_search_puts_tests_last_but_task_scores_keep_them(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/widget.py").write_text("def widget_render(layout):\n    return layout\n", encoding="utf-8")
    (tmp_path / "tests/test_widget.py").write_text(
        "def test_widget_render_layout():\n    widget_layout = make_widget_layout()\n"
        "    assert widget_render(widget_layout) == widget_layout\n", encoding="utf-8")
    mgr = SemanticSearchManager(root_dir=str(tmp_path))
    mgr.search_candidates("widget render layout", top_k=10)
    assert mgr.wait_for_body_index()
    kept = [row.file_path for row in mgr.search_candidates("widget render layout", top_k=10, tests_last=False)]
    assert kept[0] == "tests/test_widget.py"
    assert [row.file_path for row in mgr.search_candidates("widget render layout", top_k=10)][0] == "src/widget.py"


def test_related_files_use_task_context_only_to_order_graph_candidates(tmp_path):
    svc = CodeIntelService(str(tmp_path))
    edges = {"src/entry.py": {"src/swarm.py", "src/search.py"}}
    index = SimpleNamespace(
        get_dependencies=lambda path: edges.get(path, set()),
        get_dependents=lambda _path: set(),
        file_dependencies=edges,
    )
    svc._get_ast_service = lambda: SimpleNamespace(
        _to_rel=lambda path: path, _index=index,
    )
    svc._task_file_scores = lambda *_args, **_kwargs: {"src/search.py": 1.0}
    rows = svc.find_related_data("src/entry.py", task_hint="search ranking")["related"]
    assert {row["path"] for row in rows} == {"src/swarm.py", "src/search.py"}
    assert rows[0]["path"] == "src/search.py"
    assert all(row["relation_type"] == "direct" for row in rows)


def test_semantic_search_warming_is_not_reported_as_no_match(tmp_path):
    svc = CodeIntelService(str(tmp_path))
    manager = SimpleNamespace(
        search_candidates=lambda *_args, **_kwargs: [],
        candidate_diagnostics=lambda: {"status": "warming"},
        wait_for_body_index=lambda timeout: False,
        format_results=lambda _rows: "No results found.",
    )
    svc._get_semantic_search = lambda: manager
    text = svc.semantic_search("implementation", mode="keyword")
    assert "warming" in text
    assert "do not prove absence" in text


def test_ready_local_reranker_reorders_bounded_source_candidates(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    return 'old'\n")
    (tmp_path / "b.py").write_text("def b():\n    return 'ranking implementation'\n")
    svc = CodeIntelService(str(tmp_path))
    rows = [
        SemanticSearchResult(file_path="a.py", chunk_type="function", name="a",
                             text="a", score=1.0, start_line=1, end_line=2),
        SemanticSearchResult(file_path="b.py", chunk_type="function", name="b",
                             text="b", score=0.9, start_line=1, end_line=2),
    ]

    def rerank(_query, candidates, top_k):
        assert "ranking implementation" in candidates[1][1]
        return LocalRerankOutcome(
            [(candidates[1][0], candidates[1][1], 2.0),
             (candidates[0][0], candidates[0][1], 1.0)][:top_k], True,
        )

    svc._local_reranker = SimpleNamespace(
        status="ready", is_available=True, max_candidates=24,
        rerank_result=rerank,
    )
    ranked, provenance = svc._rank_search_results("ranking", rows, 2)
    assert [row.file_path for row in ranked] == ["b.py", "a.py"]
    assert provenance["method"] == "local_cross_encoder"


def test_first_search_waits_once_for_a_warming_index():
    state = {"ready": False, "waits": []}
    manager = SimpleNamespace(
        candidate_diagnostics=lambda: {"status": "ready" if state["ready"] else "warming"},
        wait_for_body_index=lambda timeout: state["waits"].append(timeout) or state.update(ready=True),
    )

    def run():
        return ["hit"] if state["ready"] else []

    assert CodeIntelService._search_after_warmup(manager, run) == ["hit"]
    assert CodeIntelService._search_after_warmup(manager, run) == ["hit"]
    assert state["waits"] == [15.0]  # only the cold search waits

    state["ready"] = False
    token = SEARCH_WARMUP_WAIT.set(0.75)  # cross_repo_search sets a short wait for each workspace
    try:
        assert CodeIntelService._search_after_warmup(manager, run) == ["hit"]
    finally:
        SEARCH_WARMUP_WAIT.reset(token)
    assert state["waits"] == [15.0, 0.75]
