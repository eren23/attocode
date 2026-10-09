"""Tests for semantic search manager: queue-based reindexing and BM25 keyword search."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from attocode.integrations.context.semantic_search import (
    IndexProgress,
    SemanticSearchManager,
    _tokenize,
)

if TYPE_CHECKING:
    from pathlib import Path


def _bare_manager(root_dir: str, **overrides) -> SemanticSearchManager:
    """Construct a manager via the real constructor, then apply overrides.

    ``__post_init__`` defers the expensive provider load (sets ``_provider=None``
    and ``_keyword_fallback=True``), so the real constructor is cheap and leaves
    every dataclass field populated. Building this way — instead of
    ``__new__`` + hand-listing fields — keeps these tests from silently breaking
    whenever a new field is added to ``SemanticSearchManager``.
    """
    mgr = SemanticSearchManager(root_dir=root_dir)
    for name, value in overrides.items():
        setattr(mgr, name, value)
    return mgr


class TestQueueReindex:
    def test_queue_reindex_deduplicates_same_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = SemanticSearchManager(root_dir=str(tmp_path))
        mgr._keyword_fallback = False
        mgr._store = object()

        # Keep the test deterministic: do not spawn real worker threads.
        monkeypatch.setattr(SemanticSearchManager, "_start_reindex_worker", lambda self: None)

        file_path = tmp_path / "src" / "mod.py"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("x = 1\n", encoding="utf-8")

        mgr.queue_reindex(str(file_path))
        mgr.queue_reindex(str(file_path))

        assert mgr._reindex_queue.qsize() == 1
        rel = file_path.relative_to(tmp_path).as_posix()
        assert rel in mgr._reindex_pending

    def test_queue_reindex_allows_requeue_after_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = SemanticSearchManager(root_dir=str(tmp_path))
        mgr._keyword_fallback = False
        mgr._store = object()
        monkeypatch.setattr(SemanticSearchManager, "_start_reindex_worker", lambda self: None)

        file_path = tmp_path / "a.py"
        file_path.write_text("print('ok')\n", encoding="utf-8")

        mgr.queue_reindex(str(file_path))
        assert mgr._reindex_queue.qsize() == 1

        # Simulate worker completing the queued item.
        queued = mgr._reindex_queue.get_nowait()
        with mgr._reindex_lock:
            mgr._reindex_pending.discard(queued)
        mgr._reindex_queue.task_done()

        mgr.queue_reindex(str(file_path))
        assert mgr._reindex_queue.qsize() == 1

    def test_queue_reindex_noop_when_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = SemanticSearchManager(root_dir=str(tmp_path))
        mgr._keyword_fallback = True
        mgr._store = None
        monkeypatch.setattr(SemanticSearchManager, "_start_reindex_worker", lambda self: None)
        # queue_reindex calls _ensure_provider() first; without stubbing it the
        # real BGE provider loads and flips _keyword_fallback back to False,
        # defeating the simulated "unavailable" state this test is asserting on.
        monkeypatch.setattr(SemanticSearchManager, "_ensure_provider", lambda self: None)

        mgr.queue_reindex(str(tmp_path / "x.py"))
        assert mgr._reindex_queue.qsize() == 0


# ============================================================
# Tokenizer Tests
# ============================================================


class TestTokenizer:
    def test_camel_case_split(self) -> None:
        tokens = _tokenize("checkBudgetLimit")
        assert "check" in tokens
        assert "budget" in tokens
        assert "limit" in tokens

    def test_snake_case_split(self) -> None:
        tokens = _tokenize("check_budget_limit")
        assert "check" in tokens
        assert "budget" in tokens
        assert "limit" in tokens

    def test_stop_words_removed(self) -> None:
        tokens = _tokenize("self is the def for import")
        assert len(tokens) == 0

    def test_min_length_filter(self) -> None:
        tokens = _tokenize("a b cd ef")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens
        assert "ef" in tokens


# ============================================================
# BM25 Keyword Search Content Tests
# ============================================================


class TestKeywordSearchContent:
    """Tests for the BM25 content-aware keyword search."""

    @pytest.fixture()
    def repo_with_files(self, tmp_path: Path) -> Path:
        """Create a mini repo with Python files for search testing."""
        (tmp_path / "budget.py").write_text(
            'def check_budget(amount: float) -> bool:\n'
            '    """Check if the budget allows this amount."""\n'
            '    return amount <= MAX_BUDGET\n'
            '\n'
            'def allocate_budget(task_id: str, tokens: int) -> None:\n'
            '    """Allocate tokens from the budget pool."""\n'
            '    pass\n',
            encoding="utf-8",
        )
        (tmp_path / "economics.py").write_text(
            'class BudgetManager:\n'
            '    """Manages token budget for agent execution."""\n'
            '    def __init__(self):\n'
            '        self.total = 0\n'
            '    def update_baseline(self):\n'
            '        pass\n',
            encoding="utf-8",
        )
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\nversion = "1.0"\n',
            encoding="utf-8",
        )
        test_dir = tmp_path / "tests"
        test_dir.mkdir(exist_ok=True)
        (test_dir / "test_budget.py").write_text(
            'def test_check_budget():\n    assert check_budget(100)\n',
            encoding="utf-8",
        )
        (tmp_path / "auth.py").write_text(
            'def authenticate(user: str, password: str) -> bool:\n'
            '    """Authenticate a user with credentials."""\n'
            '    return True\n',
            encoding="utf-8",
        )
        (tmp_path / "project.py").write_text(
            'class ProjectManager:\n'
            '    """Manage project name and metadata."""\n'
            '    def __init__(self, name: str):\n'
            '        self.name = name\n'
            '    def get_project_name(self) -> str:\n'
            '        return self.name\n',
            encoding="utf-8",
        )
        (tmp_path / "naming.py").write_text(
            'def validate_project_name(name: str) -> bool:\n'
            '    """Validate a project name meets requirements."""\n'
            '    return len(name) > 0 and name.isidentifier()\n',
            encoding="utf-8",
        )
        return tmp_path

    def _make_mgr(self, root: Path) -> SemanticSearchManager:
        return _bare_manager(str(root), _store=None, _indexed=False, _keyword_fallback=True)

    def test_finds_function_by_name(self, repo_with_files: Path) -> None:
        """BM25 should find check_budget() when searching 'budget'."""
        mgr = self._make_mgr(repo_with_files)
        results = mgr._keyword_search("budget", top_k=5, file_filter="")
        paths = [r.file_path for r in results]
        assert any("budget.py" in p for p in paths), f"budget.py not found in {paths}"
        # Should be in top 3
        top3_paths = paths[:3]
        assert any("budget.py" in p for p in top3_paths)

    def test_deprioritizes_config_files(self, repo_with_files: Path) -> None:
        """pyproject.toml should NOT be in top 3 results."""
        mgr = self._make_mgr(repo_with_files)
        results = mgr._keyword_search("project name", top_k=5, file_filter="")
        top3_paths = [r.file_path for r in results[:3]]
        assert not any("pyproject.toml" in p for p in top3_paths), (
            f"pyproject.toml should not be in top 3: {top3_paths}"
        )

    def test_matches_docstring_content(self, repo_with_files: Path) -> None:
        """Should find by docstring content, not just name."""
        mgr = self._make_mgr(repo_with_files)
        results = mgr._keyword_search("authenticate credentials", top_k=5, file_filter="")
        paths = [r.file_path for r in results]
        assert any("auth.py" in p for p in paths), f"auth.py not found in {paths}"

    def test_returns_chunk_level_results(self, repo_with_files: Path) -> None:
        """Should return function/class results, not just file-level."""
        mgr = self._make_mgr(repo_with_files)
        results = mgr._keyword_search("budget", top_k=10, file_filter="")
        chunk_types = {r.chunk_type for r in results}
        assert "function" in chunk_types or "class" in chunk_types, (
            f"Expected function/class chunks, got: {chunk_types}"
        )

    def test_file_filter_respected(self, repo_with_files: Path) -> None:
        """File filter should restrict results to matching files."""
        mgr = self._make_mgr(repo_with_files)
        results = mgr._keyword_search("budget", top_k=10, file_filter="*.py")
        for r in results:
            assert r.file_path.endswith(".py"), f"Non-py file in results: {r.file_path}"

    def test_empty_query_returns_empty(self, repo_with_files: Path) -> None:
        mgr = self._make_mgr(repo_with_files)
        results = mgr._keyword_search("", top_k=5, file_filter="")
        assert results == []


class TestSourceBodyCandidates:
    """Source retrieval complements names/docstrings without a model."""

    def test_cold_request_reports_warming_without_blocking_or_loading_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import threading
        import time

        (tmp_path / "worker.py").write_text("def execute():\n    return 1\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        started = threading.Event()
        release = threading.Event()

        def slow_build(self: SemanticSearchManager) -> None:
            started.set()
            release.wait(timeout=5)
            self._kw_index_built = True

        monkeypatch.setattr(SemanticSearchManager, "_build_keyword_index", slow_build)
        monkeypatch.setattr(SemanticSearchManager, "_sync_body_index", lambda self: None)
        monkeypatch.setattr(
            SemanticSearchManager, "_ensure_provider",
            lambda self: pytest.fail("cold search must not load an embedding model"),
        )
        try:
            begin = time.perf_counter()
            assert mgr.search("execute", top_k=5) == []
            assert time.perf_counter() - begin < 0.5
            assert started.wait(timeout=1)
            assert mgr.candidate_diagnostics()["status"] == "warming"
        finally:
            release.set()
            mgr.wait_for_body_index(timeout=5)

    def test_ready_lexical_search_still_does_not_load_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "worker.py").write_text("def execute(): return 1\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        mgr.search("execute")
        assert mgr.wait_for_body_index()
        monkeypatch.setattr(
            SemanticSearchManager, "_ensure_provider",
            lambda self: pytest.fail("interactive search must not load an embedding model"),
        )
        assert mgr.search("execute")

    def test_finds_body_only_implementation_with_line_span(self, tmp_path: Path) -> None:
        source = tmp_path / "worker.py"
        source.write_text(
            "def execute(value):\n"
            "    intermediate = value + 1\n"
            "    sapphire_handshake = intermediate * 2\n"
            "    return sapphire_handshake\n",
            encoding="utf-8",
        )
        mgr = _bare_manager(str(tmp_path))
        assert mgr._keyword_search("sapphire handshake", 10, "") == []

        mgr.search_candidates("sapphire handshake", top_k=10)
        assert mgr.wait_for_body_index()
        results = mgr.search_candidates("sapphire handshake", top_k=10)

        assert results
        hit = next(r for r in results if r.file_path == "worker.py")
        assert hit.chunk_type == "function"
        assert hit.name == "execute"
        assert hit.start_line <= 3 <= hit.end_line
        assert "sapphire_handshake" in hit.text

    def test_long_query_keeps_its_rarest_body_terms(self, tmp_path: Path) -> None:
        # Body search sends at most 20 words. They must be the rare ones, not the
        # 20 that sort first: "zephyr" sorts after all of the common words.
        common = ["acorn", "anchor", "apex", "arbor", "aspen", "atlas", "aurora", "avenue",
                  "axle", "badge", "bamboo", "banner", "basin", "beacon", "birch", "blaze",
                  "bolt", "breeze", "brick", "brook"]
        for n in range(5):
            (tmp_path / f"filler{n}.py").write_text(
                "def fill():\n" + "".join(f"    {word} = 1\n" for word in common), encoding="utf-8")
        (tmp_path / "target.py").write_text("def run_task():\n    zephyr = 2\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        query = " ".join(common) + " zephyr"
        mgr.search_candidates(query, top_k=10)
        assert mgr.wait_for_body_index()

        assert "target.py" in {r.file_path for r in mgr.search_candidates(query, top_k=10)}

    def test_whole_file_bm25_sees_matches_spread_over_a_file(self, tmp_path: Path) -> None:
        # distractor.py has three query words in one function. target.py has all
        # six words, one per function, so none of its chunks matches as well.
        words = ["quartz", "lantern", "meadow", "harbor", "falcon", "ember"]
        (tmp_path / "distractor.py").write_text(
            "def mixed():\n    quartz = lantern = meadow = 1\n    return quartz\n", encoding="utf-8")
        (tmp_path / "target.py").write_text("".join(
            f"def step{n}():\n    {word} = {n}\n    return {word}\n\n"
            for n, word in enumerate(words)), encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates(" ".join(words), top_k=10)
        assert mgr.wait_for_body_index()
        # Whole-file BM25 is only for long queries, such as a pasted issue.
        issue_words = ["report", "crash", "startup", "config", "parser", "window", "theme", "plugin",
                       "cache", "network", "retry", "timeout", "logger", "version", "python"]

        assert mgr._file_search(words + issue_words, 10, "")[0] == "target.py"
        assert mgr._file_search(words, 10, "") == []
        assert mgr.search_candidates(" ".join(words), top_k=10)[0].file_path == "distractor.py"

    def test_file_fusion_is_equal_weight_rrf_of_file_orders(self, tmp_path: Path) -> None:
        from attocode.integrations.context.semantic_search import SemanticSearchResult

        (tmp_path / "d.py").write_text("D = 1\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        rows = [SemanticSearchResult(file_path=path, chunk_type="function", name=name, text="", score=score)
                for path, name, score in (("a.py", "one", .3), ("b.py", "two", .2), ("a.py", "three", .15),
                                          ("c.py", "four", .1))]

        fused = mgr._fuse_file_order(rows, ["c.py", "d.py"])
        # c.py: 1/63 + 1/61; a.py: 1/61; b.py and d.py tie at 1/62, so the path decides.
        assert [(r.file_path, r.name) for r in fused] == [
            ("c.py", "four"), ("a.py", "one"), ("b.py", "two"), ("d.py", "d.py"), ("a.py", "three")]
        assert [r.score for r in fused] == sorted((r.score for r in fused), reverse=True)

    def test_whole_file_search_skips_docs(self, tmp_path: Path) -> None:
        # A long prose issue matches docs well. Whole-file BM25 ranks code only.
        words = [f"word{chr(97 + n)}zed" for n in range(22)]
        (tmp_path / "notes.md").write_text(" ".join(words) + "\n", encoding="utf-8")
        (tmp_path / "code.py").write_text(f"TEXT = '{' '.join(words)}'\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates(" ".join(words), top_k=10)
        assert mgr.wait_for_body_index()

        assert mgr._file_search(words, 10, "") == ["code.py"]

    def test_invalidation_updates_body_and_removes_deleted_file(self, tmp_path: Path) -> None:
        source = tmp_path / "worker.py"
        source.write_text("def execute():\n    return sapphire_handshake\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates("sapphire", 10)
        assert mgr.wait_for_body_index()
        assert mgr.search_candidates("sapphire", 10)

        source.write_text("def execute():\n    return amber_handshake\n", encoding="utf-8")
        mgr.invalidate_file(str(source))
        mgr.search_candidates("amber", 10)
        assert mgr.wait_for_body_index()
        assert not mgr.search_candidates("sapphire", 10)
        assert mgr.search_candidates("amber", 10)

        # A fresh manager must also trust disk metadata rather than stale FTS rows.
        fresh = _bare_manager(str(tmp_path))
        fresh.search_candidates("amber", 10)
        assert fresh.wait_for_body_index()
        assert not fresh.search_candidates("sapphire", 10)
        source.unlink()
        fresh.invalidate_file(str(source))
        fresh.search_candidates("amber", 10)
        assert fresh.wait_for_body_index()
        assert not fresh.search_candidates("amber", 10)

    def test_direct_edit_does_not_return_stale_body_hit(self, tmp_path: Path) -> None:
        source = tmp_path / "worker.py"
        source.write_text("def execute():\n    return sapphire_handshake\n", encoding="utf-8")
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates("sapphire", 10)
        assert mgr.wait_for_body_index()

        source.write_text("def execute():\n    return amber_handshake\n", encoding="utf-8")
        assert mgr.search_candidates("sapphire", 10) == []
        assert mgr.candidate_diagnostics()["status"] == "warming"
        assert mgr.wait_for_body_index()
        assert not mgr.search_candidates("sapphire", 10)
        assert mgr.search_candidates("amber", 10)

    def test_body_hit_format_includes_exact_window(self, tmp_path: Path) -> None:
        (tmp_path / "worker.py").write_text(
            "def execute():\n    return sapphire_handshake\n", encoding="utf-8",
        )
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates("sapphire", 10)
        assert mgr.wait_for_body_index()
        result = mgr.search_candidates("sapphire", 10)[0]
        formatted = mgr.format_results([result])
        assert f"worker.py:{result.start_line}-{result.end_line}" in formatted
        assert "sapphire_handshake" in formatted

    def test_query_escaping_and_soft_exclusion(self, tmp_path: Path) -> None:
        (tmp_path / "attoswarm_worker.py").write_text(
            "def execute():\n    return ranking_candidate\n", encoding="utf-8",
        )
        (tmp_path / "search_worker.py").write_text(
            "def execute():\n    return ranking_candidate\n", encoding="utf-8",
        )
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates("ranking candidate", top_k=20)
        assert mgr.wait_for_body_index()
        results = mgr.search_candidates(
            'ranking candidate OR "evil"* without unrelated swarm modules', top_k=20,
        )
        paths = [r.file_path for r in results]
        assert "search_worker.py" in paths
        assert "attoswarm_worker.py" in paths  # soft penalty, not exclusion
        assert paths.index("search_worker.py") < paths.index("attoswarm_worker.py")

    def test_fallback_when_fts_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "budget.py").write_text(
            "def budget_limit():\n    return 3\n", encoding="utf-8",
        )
        mgr = _bare_manager(str(tmp_path))
        monkeypatch.setattr(SemanticSearchManager, "_open_body_db", lambda self: None)
        assert mgr.search_candidates("budget limit", top_k=10) == []
        assert mgr.candidate_diagnostics()["status"] == "warming"
        mgr.wait_for_body_index()
        assert mgr._kw_index_built
        results = mgr.search_candidates("budget limit", top_k=10)
        assert any(r.name == "budget_limit" for r in results)

    def test_exclusion_penalty_applies_before_lexical_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from attocode.integrations.context.semantic_search import SemanticSearchResult

        mgr = _bare_manager(str(tmp_path), _kw_index_built=True)
        ranked = [
            SemanticSearchResult(f"swarm_{i}.py", "function", "bootstrap", "bootstrap", 1.0)
            for i in range(5)
        ] + [SemanticSearchResult("service.py", "function", "bootstrap", "bootstrap", 0.9)]
        monkeypatch.setattr(SemanticSearchManager, "_keyword_search", lambda *args: ranked)
        monkeypatch.setattr(SemanticSearchManager, "_body_search", lambda *args: [])
        results = mgr.search_candidates("bootstrap without swarm", top_k=5)
        assert results[0].file_path == "service.py"

    def test_source_body_index_does_not_follow_outside_symlink(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        outside = tmp_path / "private.py"
        outside.write_text("def secret(): return sapphire_handshake\n", encoding="utf-8")
        (root / "linked.py").symlink_to(outside)
        mgr = _bare_manager(str(root))
        mgr.search_candidates("sapphire", top_k=10)
        assert mgr.wait_for_body_index()
        conn = mgr._open_body_db()
        assert conn is not None
        try:
            assert not conn.execute(
                "SELECT 1 FROM body_files WHERE file_path = 'linked.py'",
            ).fetchone()
        finally:
            conn.close()

    def test_body_filter_applies_before_rank_limit(self, tmp_path: Path) -> None:
        for index in range(130):
            (tmp_path / f"worker_{index}.py").write_text(
                "def execute(): return sapphire_handshake\n", encoding="utf-8",
            )
        (tmp_path / "worker.go").write_text(
            "func Execute() string { return sapphire_handshake }\n", encoding="utf-8",
        )
        mgr = _bare_manager(str(tmp_path))
        mgr.search_candidates("sapphire handshake", top_k=5)
        assert mgr.wait_for_body_index()
        results = mgr.search_candidates("sapphire handshake", top_k=5, file_filter="*.go")
        assert any(result.file_path == "worker.go" for result in results)

    def test_source_cache_is_private(self, tmp_path: Path) -> None:
        mgr = _bare_manager(str(tmp_path))
        conn = mgr._open_body_db()
        assert conn is not None
        conn.close()
        db = tmp_path / ".attocode" / "index" / "kw_index.db"
        assert db.stat().st_mode & 0o077 == 0
        assert db.parent.stat().st_mode & 0o077 == 0


# ============================================================
# Background Indexer Tests
# ============================================================


class TestBackgroundIndexer:
    def test_index_progress_defaults(self) -> None:
        progress = IndexProgress()
        assert progress.status == "idle"
        assert progress.coverage == 0.0
        assert progress.total_files == 0

    def test_get_index_progress_no_store(self, tmp_path: Path) -> None:
        mgr = _bare_manager(str(tmp_path), _store=None, _keyword_fallback=True)

        progress = mgr.get_index_progress()
        assert progress.status == "idle"

    def test_is_index_ready_false_when_no_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # attocode.config loads a developer .env at import; this test assumes no model is set.
        monkeypatch.delenv("ATTOCODE_EMBEDDING_MODEL", raising=False)
        mgr = _bare_manager(str(tmp_path), _store=None, _keyword_fallback=True)

        assert mgr.is_index_ready() is False


# ============================================================
# RRF Merge Path Tests (N2)
# ============================================================


class TestRRFMergePath:
    """Test the full search() → RRF fusion path with both vector and keyword hits."""

    def test_rrf_merges_vector_and_keyword_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both vector and keyword results should appear in merged output."""
        from unittest.mock import MagicMock

        from attocode.integrations.context.semantic_search import SemanticSearchResult

        mgr = _bare_manager(str(tmp_path), _keyword_fallback=False, _indexed=True)

        # Mock provider
        provider = MagicMock()
        provider.name = "local:test-model"
        provider.embed.return_value = [[0.1, 0.2, 0.3]]
        provider.embed_query.return_value = [[0.1, 0.2, 0.3]]
        mgr._provider = provider

        # Mock vector store with results (matching model so mismatch guard stays off)
        store = MagicMock()
        store.model_name = "local:test-model"
        store.count.return_value = 100
        vector_result = MagicMock()
        vector_result.id = "func:src/auth.py:authenticate"
        vector_result.file_path = "src/auth.py"
        vector_result.chunk_type = "function"
        vector_result.name = "authenticate"
        vector_result.text = "authenticate user"
        vector_result.score = 0.95
        store.search.return_value = [vector_result]
        mgr._store = store

        # Mock keyword results (different file — keyword-only)
        kw_result = SemanticSearchResult(
            file_path="src/login.py",
            chunk_type="function",
            name="login",
            text="login handler",
            score=0.8,
        )
        monkeypatch.setattr(
            SemanticSearchManager, "_keyword_search",
            lambda self, *a, **kw: [kw_result],
        )
        results = mgr.search("authenticate user", top_k=10, two_stage=True)

        # Both vector and keyword results should be present
        result_files = [r.file_path for r in results]
        assert "src/auth.py" in result_files, f"Vector hit missing: {result_files}"
        assert "src/login.py" in result_files, f"Keyword hit missing: {result_files}"

    def test_rrf_keyword_uses_composite_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keyword results should use composite IDs matching vector key space."""
        from unittest.mock import MagicMock

        from attocode.integrations.context.semantic_search import SemanticSearchResult

        mgr = _bare_manager(str(tmp_path), _keyword_fallback=False, _indexed=True)

        provider = MagicMock()
        provider.embed.return_value = [[0.1, 0.2]]
        mgr._provider = provider

        # Same file in both vector and keyword — should fuse properly
        store = MagicMock()
        store.count.return_value = 100
        vr = MagicMock()
        vr.id = "func:src/budget.py:check_budget"
        vr.file_path = "src/budget.py"
        vr.chunk_type = "function"
        vr.name = "check_budget"
        vr.text = "check budget"
        vr.score = 0.9
        store.search.return_value = [vr]
        mgr._store = store

        kw_result2 = SemanticSearchResult(
            file_path="src/budget.py",
            chunk_type="function",
            name="check_budget",
            text="check budget",
            score=1.0,
        )
        monkeypatch.setattr(
            SemanticSearchManager, "_keyword_search",
            lambda self, *a, **kwargs: [kw_result2],
        )
        results = mgr.search("check budget", top_k=10, two_stage=True)

        # Same file/function should be fused into one result (not duplicated)
        budget_results = [r for r in results if r.file_path == "src/budget.py"]
        assert len(budget_results) == 1, f"Expected 1 fused result, got {len(budget_results)}"
