"""Tests for semantic search manager: queue-based reindexing and BM25 keyword search."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from attocode.integrations.context.semantic_search import (
    IndexProgress,
    SemanticSearchManager,
    _KeywordDoc,
    _tokenize,
)


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

    def test_is_index_ready_false_when_no_store(self, tmp_path: Path) -> None:
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
