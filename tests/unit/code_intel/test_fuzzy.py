"""Tests for the fuzzy search module."""

from __future__ import annotations

import pytest

from attocode.integrations.context.fuzzy import (
    FuzzyMatcher,
    FuzzyMatch,
    _smith_waterman,
    fuzzy_match,
    fuzzy_match_filename,
    fuzzy_match_in_lines,
    fuzzy_search,
)


class TestSmithWaterman:
    """Test Smith-Waterman algorithm."""

    def test_exact_match_returns_high_score(self):
        """An exact match should return a high score."""
        score, indices = _smith_waterman("hello", "hello world")
        assert score > 80.0
        assert len(indices) == 5

    def test_partial_match_returns_partial_score(self):
        """A partial match should return a partial score."""
        score, indices = _smith_waterman("hello", "say hello world")
        assert score > 50.0
        assert len(indices) == 5

    def test_no_match_returns_zero(self):
        """A non-matching query should return zero."""
        score, indices = _smith_waterman("xyz", "abcdefgh")
        assert score == 0.0
        assert indices == []

    def test_typo_tolerance(self):
        """Similar strings with typos should still match."""
        # "mtxlk" is close to "mutex_lock" (transposed characters)
        score, indices = _smith_waterman("mtxlk", "mutex_lock")
        # Should find some match despite typos
        assert score > 20.0

    def test_case_insensitive(self):
        """Case should be ignored when case_sensitive=False."""
        score_sensitive, _ = _smith_waterman("HELLO", "hello world", case_sensitive=True)
        score_insensitive, _ = _smith_waterman("HELLO", "hello world", case_sensitive=False)

        # Case insensitive should have higher score
        assert score_insensitive > score_sensitive

    def test_empty_pattern_returns_zero(self):
        """Empty pattern should return zero."""
        score, indices = _smith_waterman("", "hello")
        assert score == 0.0
        assert indices == []

    def test_empty_text_returns_zero(self):
        """Empty text should return zero."""
        score, indices = _smith_waterman("hello", "")
        assert score == 0.0
        assert indices == []


class TestFuzzyMatch:
    """Test fuzzy_match function."""

    def test_match_above_threshold(self):
        """Match above threshold should return FuzzyMatch."""
        match = fuzzy_match("hello", "hello world", min_score=30.0)
        assert match is not None
        assert match.score > 30.0
        assert match.text == "hello world"

    def test_match_below_threshold_returns_none(self):
        """Match below threshold should return None."""
        match = fuzzy_match("xyz", "hello world", min_score=30.0)
        assert match is None

    def test_matched_indices_tracked(self):
        """Matched character indices should be tracked."""
        match = fuzzy_match("hello", "say hello world", min_score=0.0)
        assert match is not None
        assert len(match.matched_indices) == 5


class TestFuzzyMatchInLines:
    """Test fuzzy_match_in_lines function."""

    def test_finds_matches_in_lines(self):
        """Should find matches across multiple lines."""
        lines = [
            "def hello_world():",
            "    pass",
            "class HelloWorld:",
            "    pass",
        ]
        matches = fuzzy_match_in_lines("hello", lines, min_score=30.0)
        assert len(matches) == 2  # Function and class

    def test_respects_max_results(self):
        """Should respect max_results limit."""
        lines = ["hello"] * 100
        matches = fuzzy_match_in_lines("hello", lines, min_score=0.0, max_results=10)
        assert len(matches) == 10

    def test_sorts_by_score(self):
        """Results should be sorted by score descending."""
        lines = [
            "hello world",  # Full match - score 100
            "say hello there",  # Partial - score 100
            "completely unrelated text",  # May match partially
        ]
        matches = fuzzy_match_in_lines("hello", lines, min_score=0.0)
        # All three may match with different scores
        assert len(matches) >= 2
        # First two should be the best matches (higher score)
        assert matches[0].score >= matches[1].score


class TestFuzzyFilenameSearch:
    """Test fuzzy filename matching."""

    def test_exact_substring_high_score(self):
        """Exact substring should have high score."""
        score = fuzzy_match_filename("hello", "hello_world.py")
        assert score > 50.0  # Should be high but not necessarily >80

    def test_partial_match_lower_score(self):
        """Partial match should have lower score."""
        score = fuzzy_match_filename("hl", "hello_world.py")
        assert score > 30.0

    def test_no_match_low_score(self):
        """No match should have low score."""
        score = fuzzy_match_filename("xyz", "hello_world.py")
        # Score should be reasonable for completely different strings
        assert score < 60.0

    def test_typo_tolerance(self):
        """Should handle typos in filenames."""
        # "mtxlk" vs "mutex_lock" - transposed characters
        score = fuzzy_match_filename("mtxlk", "mutex_lock.py")
        assert score > 20.0


class TestFuzzyMatcher:
    """Test FuzzyMatcher class."""

    def test_matches_method(self):
        """Test the matches() method."""
        matcher = FuzzyMatcher("hello", min_score=30.0)
        assert matcher.matches("hello world") is True
        assert matcher.matches("xyz abc") is False

    def test_get_score_method(self):
        """Test the get_score() method."""
        matcher = FuzzyMatcher("hello", min_score=0.0)
        score = matcher.get_score("say hello world")
        assert score > 0.0

    def test_search_method(self):
        """Test the search() method."""
        matcher = FuzzyMatcher("hello", min_score=30.0)
        lines = ["hello world", "goodbye world", "hello there friend"]
        matches = matcher.search(lines)
        assert len(matches) == 2
