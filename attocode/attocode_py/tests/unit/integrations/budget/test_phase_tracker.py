"""Tests for phase tracker."""

from __future__ import annotations

from attocode.integrations.budget.phase_tracker import AgentPhase, PhaseTracker


class TestPhaseTracker:
    def test_initial_phase(self) -> None:
        pt = PhaseTracker()
        assert pt.current_phase == AgentPhase.EXPLORATION

    def test_read_stays_exploration(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("read_file", 1)
        assert pt.current_phase == AgentPhase.EXPLORATION
        assert pt.files_read == 1

    def test_edit_transitions_to_acting(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("edit_file", 1)
        assert pt.current_phase == AgentPhase.ACTING
        assert pt.files_edited == 1

    def test_write_transitions_to_acting(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("write_file", 1)
        assert pt.current_phase == AgentPhase.ACTING

    def test_bash_after_edits_is_verifying(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("write_file", 1)
        pt.record_tool_use("bash", 2)
        assert pt.current_phase == AgentPhase.VERIFYING

    def test_exploration_nudge(self) -> None:
        pt = PhaseTracker(exploration_nudge_threshold=3)
        for i in range(3):
            nudge = pt.record_tool_use("read_file", i + 1)
        assert nudge is not None
        assert "3 files" in nudge

    def test_no_nudge_before_threshold(self) -> None:
        pt = PhaseTracker(exploration_nudge_threshold=10)
        for i in range(5):
            nudge = pt.record_tool_use("read_file", i + 1)
        assert nudge is None

    def test_no_nudge_if_editing(self) -> None:
        pt = PhaseTracker(exploration_nudge_threshold=3)
        pt.record_tool_use("read_file", 1)
        pt.record_tool_use("edit_file", 2)
        for i in range(5):
            nudge = pt.record_tool_use("read_file", i + 3)
        assert nudge is None

    def test_transitions_recorded(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("read_file", 1)
        pt.record_tool_use("write_file", 2)
        assert len(pt.transitions) >= 1
        assert pt.transitions[-1].to_phase == AgentPhase.ACTING

    def test_summary(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("read_file", 1)
        pt.record_tool_use("write_file", 2)
        s = pt.summary
        assert "acting" in s.lower()
        assert "1" in s  # files read

    def test_reset(self) -> None:
        pt = PhaseTracker()
        pt.record_tool_use("write_file", 1)
        pt.reset()
        assert pt.current_phase == AgentPhase.EXPLORATION
        assert pt.files_read == 0
        assert pt.files_edited == 0
