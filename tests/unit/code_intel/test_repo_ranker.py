"""Tests for graph-ranked repo map."""

from __future__ import annotations

import pytest

from attocode.code_intel.repo_ranker import (
    RankedEntry,
    RepoMapResult,
    format_repo_map,
    pagerank,
    rank_repo_files,
)


class TestPageRank:
    def test_empty_graph(self) -> None:
        assert pagerank({}) == {}

    def test_single_node(self) -> None:
        scores = pagerank({"a": []})
        assert "a" in scores
        assert scores["a"] == pytest.approx(1.0, abs=0.01)

    def test_two_nodes_one_link(self) -> None:
        scores = pagerank({"a": ["b"], "b": []})
        # b should rank higher — it receives a link
        assert scores["b"] > scores["a"]

    def test_cycle(self) -> None:
        scores = pagerank({"a": ["b"], "b": ["c"], "c": ["a"]})
        # All should be roughly equal in a cycle
        values = list(scores.values())
        assert max(values) - min(values) < 0.05

    def test_hub_and_spoke(self) -> None:
        # Many files import "core.py"
        adj = {
            "core": [],
            "a": ["core"],
            "b": ["core"],
            "c": ["core"],
            "d": ["core"],
        }
        scores = pagerank(adj)
        # core should have highest rank
        assert scores["core"] == max(scores.values())

    def test_convergence(self) -> None:
        adj = {"a": ["b", "c"], "b": ["c"], "c": ["a"]}
        scores = pagerank(adj, iterations=100)
        total = sum(scores.values())
        assert total == pytest.approx(1.0, abs=0.01)


class TestRankRepoFiles:
    def test_basic_ranking(self) -> None:
        adj = {
            "src/core.py": [],
            "src/utils.py": ["src/core.py"],
            "src/api.py": ["src/core.py", "src/utils.py"],
        }
        result = rank_repo_files(adj)
        assert len(result.entries) > 0
        # core.py should be ranked highest (most imported)
        assert result.entries[0].path == "src/core.py"

    def test_task_relevance_boost(self) -> None:
        adj = {
            "src/auth.py": [],
            "src/core.py": [],
            "src/api.py": ["src/core.py", "src/auth.py"],
        }
        result = rank_repo_files(adj, task_context="fix authentication bug")
        # auth.py should get a relevance boost
        auth_entry = next((e for e in result.entries if e.path == "src/auth.py"), None)
        assert auth_entry is not None

    def test_exclude_tests(self) -> None:
        adj = {
            "src/core.py": [],
            "tests/test_core.py": ["src/core.py"],
        }
        result = rank_repo_files(adj, exclude_tests=True)
        paths = [e.path for e in result.entries]
        assert "tests/test_core.py" not in paths

    def test_include_tests(self) -> None:
        adj = {
            "src/core.py": [],
            "tests/test_core.py": ["src/core.py"],
        }
        result = rank_repo_files(adj, exclude_tests=False)
        paths = [e.path for e in result.entries]
        assert "tests/test_core.py" in paths

    def test_token_budget_truncation(self) -> None:
        adj = {f"src/file{i}.py": [] for i in range(100)}
        result = rank_repo_files(adj, token_budget=50)
        assert result.truncated is True
        assert len(result.entries) < 100

    def test_symbols_included(self) -> None:
        adj = {"src/core.py": []}
        symbols = {"src/core.py": ["CoreClass", "main", "init"]}
        result = rank_repo_files(adj, symbols_by_file=symbols)
        assert result.entries[0].symbols == ["CoreClass", "main", "init"]

    def test_symbols_capped(self) -> None:
        adj = {"src/core.py": []}
        symbols = {"src/core.py": [f"sym{i}" for i in range(20)]}
        result = rank_repo_files(adj, symbols_by_file=symbols)
        assert len(result.entries[0].symbols) <= 10

    def test_categorization(self) -> None:
        adj = {
            "src/core/engine.py": [],
            "src/utils/helpers.py": [],
            "src/api/routes.py": [],
        }
        result = rank_repo_files(adj)
        categories = {e.path: e.category for e in result.entries}
        assert categories["src/core/engine.py"] == "core"
        assert categories["src/utils/helpers.py"] == "util"
        assert categories["src/api/routes.py"] == "api"

    def test_empty_graph(self) -> None:
        result = rank_repo_files({})
        assert result.entries == []
        assert result.total_files == 0


class TestFormatRepoMap:
    def test_format_basic(self) -> None:
        result = RepoMapResult(
            entries=[
                RankedEntry(path="src/core.py", score=0.5, symbols=["Foo", "Bar"], category="core"),
                RankedEntry(path="src/utils.py", score=0.3, symbols=["helper"], category="util"),
            ],
            total_files=10,
            token_budget=1024,
            tokens_used=50,
        )
        text = format_repo_map(result)
        assert "src/core.py" in text
        assert "Foo" in text
        assert "2/10 files" in text

    def test_format_empty(self) -> None:
        result = RepoMapResult(entries=[], total_files=0, token_budget=1024, tokens_used=0)
        assert "No files ranked" in format_repo_map(result)

    def test_format_truncated(self) -> None:
        result = RepoMapResult(
            entries=[RankedEntry(path="a.py", score=0.5, category="module")],
            total_files=100,
            token_budget=50,
            tokens_used=45,
            truncated=True,
        )
        text = format_repo_map(result)
        assert "omitted" in text
