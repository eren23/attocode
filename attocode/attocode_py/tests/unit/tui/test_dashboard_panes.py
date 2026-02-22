"""Tests for dashboard panes (SessionInfo, DashboardScreen tab logic)."""

from __future__ import annotations

import pytest

from attocode.tui.widgets.dashboard.session_browser import SessionInfo
from attocode.tui.widgets.dashboard.live_dashboard import LiveTraceAccumulator
from attocode.tui.screens.dashboard import DashboardScreen, _TABS


# ---------------------------------------------------------------------------
# SessionInfo dataclass
# ---------------------------------------------------------------------------


class TestSessionInfo:
    def test_creation(self) -> None:
        info = SessionInfo(
            session_id="abc123",
            goal="Build API",
            model="claude-sonnet",
            duration_seconds=120.5,
            total_tokens=50000,
            total_cost=0.15,
            iterations=10,
            efficiency_score=75.0,
            file_path="/tmp/trace.jsonl",
        )
        assert info.session_id == "abc123"
        assert info.goal == "Build API"
        assert info.model == "claude-sonnet"
        assert info.duration_seconds == 120.5
        assert info.total_tokens == 50000
        assert info.total_cost == 0.15
        assert info.iterations == 10
        assert info.efficiency_score == 75.0
        assert info.file_path == "/tmp/trace.jsonl"

    def test_slots_no_dict(self) -> None:
        info = SessionInfo(
            session_id="x", goal="y", model="z",
            duration_seconds=1.0, total_tokens=0, total_cost=0.0,
            iterations=0, efficiency_score=0.0, file_path="",
        )
        assert not hasattr(info, "__dict__")


# ---------------------------------------------------------------------------
# DashboardScreen — tab definitions and index cycling
# ---------------------------------------------------------------------------


class TestDashboardTabDefinitions:
    def test_tab_count(self) -> None:
        assert len(_TABS) == 5

    def test_tab_keys(self) -> None:
        keys = [t[0] for t in _TABS]
        assert keys == ["1", "2", "3", "4", "5"]

    def test_tab_labels(self) -> None:
        labels = [t[1] for t in _TABS]
        assert labels == ["Live", "Sessions", "Detail", "Compare", "Swarm"]

    def test_tab_pane_ids(self) -> None:
        pane_ids = [t[2] for t in _TABS]
        assert all(pid.startswith("pane-") for pid in pane_ids)


class TestDashboardScreenInit:
    def test_default_tab(self) -> None:
        screen = DashboardScreen()
        assert screen._active_tab_index == 0

    def test_custom_accumulator(self) -> None:
        acc = LiveTraceAccumulator()
        acc.record_llm(100, 0.01)
        screen = DashboardScreen(accumulator=acc)
        assert screen._accumulator is acc
        assert screen._accumulator.total_tokens == 100

    def test_default_trace_dir(self) -> None:
        screen = DashboardScreen()
        assert str(screen._trace_dir).endswith("traces")

    def test_custom_trace_dir(self) -> None:
        screen = DashboardScreen(trace_dir="/tmp/my-traces")
        assert str(screen._trace_dir) == "/tmp/my-traces"


class TestDashboardTabCycling:
    def test_next_tab_wraps(self) -> None:
        """Verify the modular arithmetic for next tab cycling."""
        for start in range(5):
            expected = (start + 1) % 5
            assert (start + 1) % len(_TABS) == expected

    def test_prev_tab_wraps(self) -> None:
        """Verify the modular arithmetic for prev tab cycling."""
        assert (0 - 1) % len(_TABS) == 4
        assert (4 - 1) % len(_TABS) == 3

    def test_in_detail_flag(self) -> None:
        """Detail tab (index 2) should set _in_detail."""
        screen = DashboardScreen()
        # Simulate _switch_tab logic without widget mounting
        screen._active_tab_index = 2
        screen._in_detail = (screen._active_tab_index == 2)
        assert screen._in_detail is True

        screen._active_tab_index = 1
        screen._in_detail = (screen._active_tab_index == 2)
        assert screen._in_detail is False


# ---------------------------------------------------------------------------
# SessionDetailPane tab switching
# ---------------------------------------------------------------------------


class TestSessionDetailPaneTabMap:
    def test_valid_tab_keys(self) -> None:
        from attocode.tui.widgets.dashboard.session_detail import _SUB_TABS
        keys = [t[0] for t in _SUB_TABS]
        assert keys == ["a", "b", "c", "d", "e"]

    def test_sub_tab_labels(self) -> None:
        from attocode.tui.widgets.dashboard.session_detail import _SUB_TABS
        labels = [t[1] for t in _SUB_TABS]
        assert labels == ["Summary", "Timeline", "Tree", "Tokens", "Issues"]


# ---------------------------------------------------------------------------
# ComparePane — initial state
# ---------------------------------------------------------------------------


class TestComparePaneInit:
    def test_no_sessions_initially(self) -> None:
        from attocode.tui.widgets.dashboard.compare_pane import ComparePane
        pane = ComparePane()
        assert pane._session_a is None
        assert pane._session_b is None
