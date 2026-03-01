"""Tests for WorkLog progress tracker."""

from __future__ import annotations

from attocode.integrations.tasks.work_log import WorkEntryType, WorkLog


class TestRecord:
    def test_record_action(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.ACTION, "Edited file", tool="edit_file")
        assert wl.entry_count == 1
        entry = wl.entries[0]
        assert entry.type == WorkEntryType.ACTION
        assert entry.description == "Edited file"
        assert entry.tool == "edit_file"

    def test_record_observation(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.OBSERVATION, "File has 100 lines")
        assert wl.entry_count == 1
        assert wl.entries[0].type == WorkEntryType.OBSERVATION

    def test_record_decision(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.DECISION, "Use approach B")
        assert wl.entries[0].type == WorkEntryType.DECISION

    def test_record_error(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.ERROR, "Build failed")
        assert wl.entries[0].type == WorkEntryType.ERROR

    def test_record_milestone(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.MILESTONE, "Tests pass")
        assert wl.entries[0].type == WorkEntryType.MILESTONE

    def test_record_with_iteration(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.ACTION, "Did thing", iteration=5)
        assert wl.entries[0].iteration == 5

    def test_record_has_timestamp(self) -> None:
        wl = WorkLog()
        wl.record(WorkEntryType.ACTION, "Timed")
        assert wl.entries[0].timestamp > 0


class TestShorthandMethods:
    def test_action(self) -> None:
        wl = WorkLog()
        wl.action("Read file", tool="read_file", iteration=1)
        assert wl.entries[0].type == WorkEntryType.ACTION
        assert wl.entries[0].tool == "read_file"
        assert wl.entries[0].iteration == 1

    def test_observation(self) -> None:
        wl = WorkLog()
        wl.observation("Noticed pattern", iteration=2)
        assert wl.entries[0].type == WorkEntryType.OBSERVATION
        assert wl.entries[0].iteration == 2

    def test_decision(self) -> None:
        wl = WorkLog()
        wl.decision("Choose strategy A", iteration=3)
        assert wl.entries[0].type == WorkEntryType.DECISION

    def test_error(self) -> None:
        wl = WorkLog()
        wl.error("Compilation error", iteration=4)
        assert wl.entries[0].type == WorkEntryType.ERROR

    def test_milestone(self) -> None:
        wl = WorkLog()
        wl.milestone("Phase 1 complete", iteration=5)
        assert wl.entries[0].type == WorkEntryType.MILESTONE


class TestGetRecent:
    def test_get_recent_less_than_count(self) -> None:
        wl = WorkLog()
        wl.action("A")
        wl.action("B")
        recent = wl.get_recent(10)
        assert len(recent) == 2

    def test_get_recent_exact_count(self) -> None:
        wl = WorkLog()
        for i in range(5):
            wl.action(f"Entry {i}")
        recent = wl.get_recent(5)
        assert len(recent) == 5

    def test_get_recent_limited(self) -> None:
        wl = WorkLog()
        for i in range(10):
            wl.action(f"Entry {i}")
        recent = wl.get_recent(3)
        assert len(recent) == 3
        # Should be the last 3
        assert recent[0].description == "Entry 7"
        assert recent[1].description == "Entry 8"
        assert recent[2].description == "Entry 9"

    def test_get_recent_default(self) -> None:
        wl = WorkLog()
        for i in range(15):
            wl.action(f"Entry {i}")
        recent = wl.get_recent()
        assert len(recent) == 10  # default count is 10

    def test_get_recent_empty(self) -> None:
        wl = WorkLog()
        assert wl.get_recent(5) == []


class TestGetByType:
    def test_filters_correctly(self) -> None:
        wl = WorkLog()
        wl.action("Action 1")
        wl.error("Error 1")
        wl.action("Action 2")
        wl.milestone("Milestone 1")
        wl.error("Error 2")

        actions = wl.get_by_type(WorkEntryType.ACTION)
        assert len(actions) == 2

        errors = wl.get_by_type(WorkEntryType.ERROR)
        assert len(errors) == 2

        milestones = wl.get_by_type(WorkEntryType.MILESTONE)
        assert len(milestones) == 1

    def test_returns_empty_for_absent_type(self) -> None:
        wl = WorkLog()
        wl.action("Action 1")
        assert wl.get_by_type(WorkEntryType.MILESTONE) == []


class TestGetMilestonesAndErrors:
    def test_get_milestones(self) -> None:
        wl = WorkLog()
        wl.action("Normal work")
        wl.milestone("Phase 1 done")
        wl.error("Something broke")
        wl.milestone("Phase 2 done")

        milestones = wl.get_milestones()
        assert len(milestones) == 2
        assert milestones[0].description == "Phase 1 done"
        assert milestones[1].description == "Phase 2 done"

    def test_get_errors(self) -> None:
        wl = WorkLog()
        wl.action("Normal work")
        wl.error("Error A")
        wl.milestone("Recovered")
        wl.error("Error B")

        errors = wl.get_errors()
        assert len(errors) == 2
        assert errors[0].description == "Error A"
        assert errors[1].description == "Error B"


class TestMaxEntries:
    def test_circular_buffer_trims_old(self) -> None:
        wl = WorkLog(max_entries=5)
        for i in range(10):
            wl.action(f"Entry {i}")
        assert wl.entry_count == 5
        # Should keep the last 5
        descriptions = [e.description for e in wl.entries]
        assert descriptions == ["Entry 5", "Entry 6", "Entry 7", "Entry 8", "Entry 9"]

    def test_exactly_at_limit(self) -> None:
        wl = WorkLog(max_entries=3)
        wl.action("A")
        wl.action("B")
        wl.action("C")
        assert wl.entry_count == 3

    def test_one_over_limit_trims(self) -> None:
        wl = WorkLog(max_entries=3)
        wl.action("A")
        wl.action("B")
        wl.action("C")
        wl.action("D")
        assert wl.entry_count == 3
        descriptions = [e.description for e in wl.entries]
        assert descriptions == ["B", "C", "D"]


class TestClear:
    def test_clear_removes_all(self) -> None:
        wl = WorkLog()
        wl.action("A")
        wl.error("B")
        wl.milestone("C")
        wl.clear()
        assert wl.entry_count == 0
        assert wl.entries == []

    def test_clear_then_record(self) -> None:
        wl = WorkLog()
        wl.action("Old")
        wl.clear()
        wl.action("New")
        assert wl.entry_count == 1
        assert wl.entries[0].description == "New"


class TestGetSummary:
    def test_empty_summary(self) -> None:
        wl = WorkLog()
        assert wl.get_summary() == "No work recorded."

    def test_summary_with_entries(self) -> None:
        wl = WorkLog()
        wl.action("Read config", tool="read_file")
        wl.observation("Config uses JSON")
        wl.decision("Update to YAML")
        wl.error("Parse error")
        wl.milestone("Migration complete")

        summary = wl.get_summary()
        # Check each entry type prefix is present
        assert "-> [read_file] Read config" in summary
        assert "   Config uses JSON" in summary
        assert "** Update to YAML" in summary
        assert "!! Parse error" in summary
        assert "## Migration complete" in summary

    def test_summary_respects_max_entries(self) -> None:
        wl = WorkLog()
        for i in range(30):
            wl.action(f"Entry {i}")
        # Default max_entries for get_summary is 20
        summary = wl.get_summary()
        lines = summary.strip().split("\n")
        assert len(lines) == 20

    def test_summary_custom_max(self) -> None:
        wl = WorkLog()
        for i in range(10):
            wl.action(f"Entry {i}")
        summary = wl.get_summary(max_entries=3)
        lines = summary.strip().split("\n")
        assert len(lines) == 3

    def test_summary_action_without_tool(self) -> None:
        wl = WorkLog()
        wl.action("Manual action")
        summary = wl.get_summary()
        assert "-> Manual action" in summary


class TestEntryCount:
    def test_starts_at_zero(self) -> None:
        wl = WorkLog()
        assert wl.entry_count == 0

    def test_increments(self) -> None:
        wl = WorkLog()
        wl.action("A")
        assert wl.entry_count == 1
        wl.error("B")
        assert wl.entry_count == 2


class TestEntriesProperty:
    def test_returns_copy(self) -> None:
        wl = WorkLog()
        wl.action("A")
        entries = wl.entries
        entries.append(entries[0])  # Modify the returned list
        assert wl.entry_count == 1  # Original unaffected
