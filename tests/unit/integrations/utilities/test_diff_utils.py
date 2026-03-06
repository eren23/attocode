"""Tests for diff utilities."""

from __future__ import annotations

from attocode.integrations.utilities.diff_utils import (
    count_changes,
    similarity_ratio,
    unified_diff,
)


class TestUnifiedDiff:
    def test_identical(self) -> None:
        assert unified_diff("hello", "hello") == ""

    def test_changed(self) -> None:
        diff = unified_diff("hello\n", "world\n")
        assert "-hello" in diff
        assert "+world" in diff

    def test_custom_names(self) -> None:
        diff = unified_diff("a\n", "b\n", old_name="old.py", new_name="new.py")
        assert "old.py" in diff
        assert "new.py" in diff


class TestCountChanges:
    def test_no_changes(self) -> None:
        added, removed, modified = count_changes("hello", "hello")
        assert added == 0
        assert removed == 0
        assert modified == 0

    def test_added_lines(self) -> None:
        added, removed, modified = count_changes("a", "a\nb\nc")
        assert added == 2

    def test_removed_lines(self) -> None:
        added, removed, modified = count_changes("a\nb\nc", "a")
        assert removed == 2

    def test_modified_lines(self) -> None:
        added, removed, modified = count_changes("hello\nworld", "hello\nearth")
        assert modified >= 1


class TestSimilarityRatio:
    def test_identical(self) -> None:
        assert similarity_ratio("hello", "hello") == 1.0

    def test_completely_different(self) -> None:
        ratio = similarity_ratio("aaa", "zzz")
        assert ratio < 0.5

    def test_similar(self) -> None:
        ratio = similarity_ratio("hello world", "hello earth")
        assert 0.3 < ratio < 0.9

    def test_both_empty(self) -> None:
        assert similarity_ratio("", "") == 1.0
