"""Tests for cross-mode search suggestions."""

from __future__ import annotations

import pytest

from attocode.integrations.context.cross_mode import (
    CrossModeSearcher,
    SearchSuggestion,
    _chars_in_order,
    suggest_files_for_grep_query,
    suggest_grep_for_filename_query,
)


class TestCharsInOrder:
    """Test _chars_in_order helper."""

    def test_empty_pattern(self):
        """Empty pattern always returns True."""
        assert _chars_in_order("", "hello") is True

    def test_exact_order(self):
        """Characters in exact order should match."""
        assert _chars_in_order("helo", "hello") is True

    def test_scattered_order(self):
        """Scattered characters in order should match."""
        assert _chars_in_order("hlo", "hello") is True

    def test_wrong_order(self):
        """Characters out of order should not match."""
        assert _chars_in_order("lle", "hello") is False

    def test_partial_match(self):
        """Partial order match works."""
        assert _chars_in_order("hl", "hello") is True
        assert _chars_in_order("ho", "hello") is True


class TestSuggestGrepForFilenameQuery:
    """Test suggest_grep_for_filename_query."""

    def test_returns_suggestions(self, tmp_path):
        """Should return grep suggestions when files exist."""
        # Create test file with matching content
        test_file = tmp_path / "test_file.py"
        test_file.write_text("def foo_bar(): pass")

        suggestions = suggest_grep_for_filename_query(
            query="foo_bar",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        assert len(suggestions) >= 1
        assert any("test_file.py" in s.file_path for s in suggestions)

    def test_respects_max_suggestions(self, tmp_path):
        """Should respect max_suggestions limit."""
        # Create multiple files
        for i in range(20):
            f = tmp_path / f"file_{i}.py"
            f.write_text(f"content_{i}")

        suggestions = suggest_grep_for_filename_query(
            query="content",
            project_dir=str(tmp_path),
            max_suggestions=5,
        )

        assert len(suggestions) <= 5

    def test_no_matches(self, tmp_path):
        """Should return empty list when nothing matches."""
        suggestions = suggest_grep_for_filename_query(
            query="nonexistent_xyz_123",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        assert len(suggestions) == 0


class TestSuggestFilesForGrepQuery:
    """Test suggest_files_for_grep_query."""

    def test_returns_file_suggestions(self, tmp_path):
        """Should return file suggestions when names match."""
        # Create test file
        test_file = tmp_path / "test_module.py"
        test_file.write_text("def foo(): pass")

        suggestions = suggest_files_for_grep_query(
            query="test_module",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        assert len(suggestions) >= 1
        assert any("test_module.py" in s.file_path for s in suggestions)

    def test_sorted_by_score(self, tmp_path):
        """Should return files sorted by score."""
        # Create files with different match quality
        (tmp_path / "exact_match.py").write_text("content")
        (tmp_path / "partial.py").write_text("content")

        suggestions = suggest_files_for_grep_query(
            query="exact",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        if len(suggestions) >= 2:
            assert suggestions[0].score >= suggestions[1].score

    def test_empty_query(self, tmp_path):
        """Should return empty for empty query."""
        suggestions = suggest_files_for_grep_query(
            query="",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        assert len(suggestions) == 0


class TestCrossModeSearcher:
    """Test CrossModeSearcher class."""

    def test_file_search_suggestions(self, tmp_path):
        """Test get_file_search_suggestions via the underlying function."""
        # The CrossModeSearcher uses suggest_grep_for_filename_query internally
        # So we test that function directly
        test_file = tmp_path / "my_file.py"
        test_file.write_text("def my_function(): pass")

        suggestions = suggest_grep_for_filename_query(
            query="my_function",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        assert len(suggestions) >= 1

    def test_grep_suggestions(self, tmp_path):
        """Test get_grep_suggestions via the underlying function."""
        # The CrossModeSearcher uses suggest_files_for_grep_query internally
        test_file = tmp_path / "searchable.py"
        test_file.write_text("hello world")

        suggestions = suggest_files_for_grep_query(
            query="searchable",
            project_dir=str(tmp_path),
            max_suggestions=10,
        )

        assert len(suggestions) >= 1
