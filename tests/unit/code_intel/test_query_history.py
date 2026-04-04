"""Tests for the query history tracker module."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from attocode.integrations.context.query_history import (
    QueryHistoryTracker,
    QueryHistoryStats,
    get_query_tracker,
    reset_query_tracker,
)


class TestQueryHistoryTrackSelection:
    """Test tracking selections."""

    def test_track_single_selection(self, tmp_path: Path):
        """A single selection should be tracked."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "bar.py")

        boost = tracker.get_combo_boost("foo", "bar.py")
        assert boost == 0  # Need 3+ for boost

        stats = tracker.get_stats()
        assert stats.total_selections == 1
        assert stats.unique_queries == 1
        assert stats.unique_files == 1

        tracker.close()

    def test_track_multiple_selections(self, tmp_path: Path):
        """Multiple selections of same query+file should increment count."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "bar.py")
        tracker.track_selection("foo", "bar.py")
        tracker.track_selection("foo", "bar.py")

        boost = tracker.get_combo_boost("foo", "bar.py")
        assert boost > 0  # 3 selections = combo boost

        stats = tracker.get_stats()
        assert stats.total_selections == 3
        assert stats.combo_boosts == 1

        tracker.close()


class TestQueryHistoryComboBoost:
    """Test combo boosting."""

    def test_no_boost_below_threshold(self, tmp_path: Path):
        """No boost until min_combo_count (3) reached."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "bar.py")
        assert tracker.get_combo_boost("foo", "bar.py") == 0

        tracker.track_selection("foo", "bar.py")
        assert tracker.get_combo_boost("foo", "bar.py") == 0

        tracker.close()

    def test_boost_activates_at_threshold(self, tmp_path: Path):
        """Boost activates at min_combo_count (3)."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "bar.py")
        tracker.track_selection("foo", "bar.py")
        tracker.track_selection("foo", "bar.py")

        boost = tracker.get_combo_boost("foo", "bar.py")
        assert boost > 0  # 3 * 100 = 300

        tracker.close()

    def test_different_queries_separate(self, tmp_path: Path):
        """Different queries should have separate counts."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "a.py")
        tracker.track_selection("foo", "a.py")
        tracker.track_selection("foo", "a.py")

        tracker.track_selection("bar", "a.py")
        tracker.track_selection("bar", "a.py")

        # foo has combo boost, bar doesn't
        assert tracker.get_combo_boost("foo", "a.py") > 0
        assert tracker.get_combo_boost("bar", "a.py") == 0

        tracker.close()

    def test_combo_boost_batch(self, tmp_path: Path):
        """Test getting boosts for multiple files."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "a.py")
        tracker.track_selection("foo", "a.py")
        tracker.track_selection("foo", "a.py")

        tracker.track_selection("foo", "b.py")

        boosts = tracker.get_combo_boosts_batch("foo", ["a.py", "b.py", "c.py"])

        assert boosts["a.py"] > 0
        assert boosts["b.py"] == 0
        assert boosts["c.py"] == 0

        tracker.close()


class TestQueryHistoryTopFiles:
    """Test getting top files for a query."""

    def test_get_top_files(self, tmp_path: Path):
        """Should return files sorted by count."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "common.py")
        tracker.track_selection("foo", "common.py")
        tracker.track_selection("foo", "common.py")

        tracker.track_selection("foo", "rare.py")
        tracker.track_selection("foo", "rare.py")

        top = tracker.get_top_files_for_query("foo")

        assert len(top) == 2
        assert top[0][0] == "common.py"  # Most selected
        assert top[0][1] == 3  # Count
        assert top[1][0] == "rare.py"
        assert top[1][1] == 2

        tracker.close()


class TestQueryHistoryClear:
    """Test clearing history."""

    def test_clear_all(self, tmp_path: Path):
        """Can clear all history."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "bar.py")
        tracker.track_selection("baz", "qux.py")

        tracker.clear()

        stats = tracker.get_stats()
        assert stats.total_selections == 0

        tracker.close()

    def test_clear_specific_query(self, tmp_path: Path):
        """Can clear history for a specific query."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "bar.py")
        tracker.track_selection("foo", "baz.py")
        tracker.track_selection("qux", "bar.py")
        tracker.track_selection("qux", "bar.py")
        tracker.track_selection("qux", "bar.py")  # Now qux has 3 = combo boost

        count = tracker.clear("foo")

        assert count == 2
        assert tracker.get_combo_boost("foo", "bar.py") == 0
        assert tracker.get_combo_boost("qux", "bar.py") > 0  # qux still has boost

        tracker.close()


class TestQueryHistoryStats:
    """Test statistics."""

    def test_stats(self, tmp_path: Path):
        """Test getting statistics."""
        tracker = QueryHistoryTracker(db_path=tmp_path / "history")

        tracker.track_selection("foo", "a.py")
        tracker.track_selection("foo", "a.py")
        tracker.track_selection("foo", "b.py")
        tracker.track_selection("bar", "c.py")

        stats = tracker.get_stats()

        assert stats.total_selections == 4
        assert stats.total_queries == 3  # foo->a, foo->b, bar->c
        assert stats.unique_queries == 2  # foo, bar
        assert stats.unique_files == 3  # a.py, b.py, c.py

        tracker.close()


class TestQueryHistorySingleton:
    """Test global singleton."""

    def test_singleton(self, tmp_path: Path):
        """get_tracker returns same instance."""
        reset_query_tracker()

        tracker1 = get_query_tracker(db_path=tmp_path / "h1")
        tracker2 = get_query_tracker(db_path=tmp_path / "h2")

        assert tracker1 is tracker2  # Same instance

        reset_query_tracker()

    def test_reset(self, tmp_path: Path):
        """reset_tracker clears singleton."""
        tracker = get_query_tracker(db_path=tmp_path / "h")
        reset_query_tracker()

        new_tracker = get_query_tracker(db_path=tmp_path / "h")
        assert new_tracker is not None
        reset_query_tracker()
